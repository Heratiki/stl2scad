"""
Focused tests for GUI worker plumbing.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from stl2scad.gui import main_window


_APP = None


def _get_qapplication():
    global _APP
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(["test-stl2scad-gui"])
    _APP = app
    return app


def test_verification_worker_skips_regeneration_for_existing_scad(
    monkeypatch, test_output_dir
):
    verify_calls = {}

    class _FakeResult:
        def save_report(self, output_file):
            Path(output_file).write_text("{}", encoding="utf-8")

    def _unexpected_stl2scad(*_args, **_kwargs):
        raise AssertionError("stl2scad should not run for existing SCAD verification")

    def _fake_verify_conversion(*args, **kwargs):
        verify_calls["args"] = args
        verify_calls["kwargs"] = kwargs
        return _FakeResult()

    monkeypatch.setattr(main_window, "convert_stl_to_scad", _unexpected_stl2scad)
    monkeypatch.setattr(main_window, "verify_conversion", _fake_verify_conversion)

    scad_file = test_output_dir / "existing.scad"
    scad_file.write_text("cube([1,1,1]);", encoding="utf-8")
    worker = main_window.VerificationWorker(
        stl_file="input.stl",
        scad_file=str(scad_file),
        tolerance={"volume": 1.0, "surface_area": 2.0, "bounding_box": 0.5},
        conversion_tolerance=1e-6,
        parametric=False,
        recognition_backend="native",
        compute_backend="auto",
        regenerate_scad=False,
        visualize=False,
        html_report=False,
        sample_seed=None,
    )

    worker.run()

    assert verify_calls["args"][:2] == ("input.stl", str(scad_file))
    assert verify_calls["kwargs"] == {"debug": False, "sample_seed": None}


def test_load_scad_conversion_metadata_parses_recognition_fields(test_output_dir):
    scad_file = test_output_dir / "diagnostics.scad"
    scad_file.write_text(
        "//\n"
        "// STL to SCAD Conversion\n"
        "// recognition_backend_requested: cgal\n"
        "// recognition_backend_used: trimesh_manifold_fallback\n"
        "// recognized_primitive_type: cylinder\n"
        "// recognition_confidence: 0.987654\n"
        "// recognition_fallback_reason: cgal_declined_detection\n"
        "// recognition_diagnostics: {\"engine\": \"geometric_region_fallback\", \"component_count\": 1}\n"
        "//\n\n"
        "cylinder(h=10, r=2);\n",
        encoding="utf-8",
    )

    metadata = main_window._load_scad_conversion_metadata(str(scad_file))

    assert metadata["recognition_backend_requested"] == "cgal"
    assert metadata["recognition_backend_used"] == "trimesh_manifold_fallback"
    assert metadata["recognized_primitive_type"] == "cylinder"
    assert metadata["recognition_confidence"] == 0.987654
    assert metadata["recognition_fallback_reason"] == "cgal_declined_detection"
    assert metadata["recognition_diagnostics"] == {
        "engine": "geometric_region_fallback",
        "component_count": 1,
    }


def test_format_recognition_diagnostics_renders_summary_and_json():
    text = main_window._format_recognition_diagnostics(
        {
            "recognition_backend_requested": "cgal",
            "recognition_backend_used": "cgal",
            "recognition_attempted": "true",
            "recognized_primitive_type": "sphere",
            "recognition_confidence": 0.95,
            "recognition_diagnostics": {"engine": "cgal_python_bindings", "sample_point_count": 128},
        }
    )

    assert "Requested backend: cgal" in text
    assert "Used backend: cgal" in text
    assert "Recognition attempted: true" in text
    assert "Primitive type: sphere" in text
    assert "Confidence: 0.950" in text
    assert '"engine": "cgal_python_bindings"' in text


def test_main_window_updates_recognition_diagnostics_from_conversion_metadata(
    monkeypatch, test_output_dir
):
    _get_qapplication()
    window = main_window.MainWindow()
    try:
        scad_file = test_output_dir / "converted.scad"
        scad_file.write_text(
            "//\n"
            "// STL to SCAD Conversion\n"
            "// recognition_backend_requested: native\n"
            "// recognition_backend_used: native\n"
            "// recognized_primitive_type: box\n"
            "//\n\n"
            "cube([1, 2, 3]);\n",
            encoding="utf-8",
        )
        window.current_scad_file = str(scad_file)

        stats = main_window.ConversionStats(
            original_vertices=12,
            deduplicated_vertices=8,
            faces=12,
            metadata={},
        )

        monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
        window.conversion_finished(stats)

        text = window.recognition_diagnostics_view.toPlainText()
        assert "Requested backend: native" in text
        assert "Primitive type: box" in text
    finally:
        window.close()


def test_main_window_updates_recognition_diagnostics_from_verification_report(monkeypatch):
    _get_qapplication()
    window = main_window.MainWindow()
    try:
        result = type(
            "FakeVerificationResult",
            (),
            {
                "passed": True,
                "report": {
                    "conversion_metadata": {
                        "recognition_backend_requested": "cgal",
                        "recognition_backend_used": "trimesh_manifold_fallback",
                        "recognition_fallback_reason": "cgal_declined_detection",
                    }
                },
            },
        )()
        payload = {
            "result": result,
            "report_file": "verification.json",
            "html_file": None,
            "scad_file": "converted.scad",
        }

        monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
        window.verification_finished(payload)

        text = window.recognition_diagnostics_view.toPlainText()
        assert "Requested backend: cgal" in text
        assert "Used backend: trimesh_manifold_fallback" in text
        assert "Fallback reason: cgal_declined_detection" in text
    finally:
        window.close()


# --- T-004: the GUI converts through segmentation only ---------------------


def _record_emit(monkeypatch):
    from stl2scad.core import segmentation

    calls = []

    def emit(features, mesh, *, source_file):
        calls.append((features, len(mesh.vectors), source_file))
        return "// segmentation\ncube(2);\n"

    monkeypatch.setattr(segmentation, "emit_scad", emit)
    return calls


def _cube_stl(directory, name="input.stl"):
    from tests.test_segmentation_geometry import cube, mesh_of

    path = directory / name
    mesh_of(cube()).save(str(path))
    return path


def test_conversion_worker_uses_segmentation(monkeypatch, test_output_dir):
    calls = _record_emit(monkeypatch)
    source = _cube_stl(test_output_dir)
    target = test_output_dir / "output.scad"
    finished, errors = [], []

    # Legacy options are still accepted by the constructor and ignored.
    worker = main_window.ConversionWorker(
        str(source),
        str(target),
        tolerance=1e-5,
        debug=True,
        parametric=True,
        recognition_backend="cgal",
        compute_backend="gpu",
    )
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)
    worker.run()

    assert errors == []
    assert calls == [(None, 12, str(source))]
    assert target.read_text() == "// segmentation\ncube(2);\n"
    assert isinstance(finished[0], main_window.ConversionStats)
    assert finished[0].faces == 12
    assert finished[0].metadata["pipeline"] == "segmentation"

    batch_in = test_output_dir / "batch_in"
    batch_in.mkdir()
    batch_source = _cube_stl(batch_in, "part.stl")
    batch_out = test_output_dir / "batch_out"

    class _FakeResult:
        passed = True

        def save_report(self, output_file):
            Path(output_file).write_text("{}", encoding="utf-8")

    monkeypatch.setattr(main_window, "verify_conversion", lambda *a, **k: _FakeResult())
    batch = main_window.BatchWorker(
        str(batch_in),
        str(batch_out),
        tolerance={"volume": 1.0, "surface_area": 2.0, "bounding_box": 0.5},
        html_report=False,
        parametric=True,
        recognition_backend="native",
        compute_backend="auto",
        sample_seed=None,
    )
    batch_errors = []
    batch.error.connect(batch_errors.append)
    batch.run()

    assert batch_errors == []
    assert calls[1:] == [(None, 12, str(batch_source))]
    assert (batch_out / "part.scad").read_text() == "// segmentation\ncube(2);\n"


def test_verification_worker_regenerates_through_segmentation(
    monkeypatch, test_output_dir
):
    calls = _record_emit(monkeypatch)
    source = _cube_stl(test_output_dir)
    scad_file = test_output_dir / "regenerated.scad"
    verify_calls = {}

    class _FakeResult:
        def save_report(self, output_file):
            Path(output_file).write_text("{}", encoding="utf-8")

    def _fake_verify_conversion(*args, **kwargs):
        verify_calls["args"] = args
        verify_calls["kwargs"] = kwargs
        verify_calls["scad"] = Path(args[1]).read_text()
        return _FakeResult()

    monkeypatch.setattr(main_window, "verify_conversion", _fake_verify_conversion)
    worker = main_window.VerificationWorker(
        stl_file=str(source),
        scad_file=str(scad_file),
        tolerance={"volume": 1.0, "surface_area": 2.0, "bounding_box": 0.5},
        conversion_tolerance=1e-6,
        parametric=True,
        recognition_backend="trimesh_manifold",
        compute_backend="cpu",
        regenerate_scad=True,
        visualize=False,
        html_report=False,
        sample_seed=123,
    )
    errors = []
    worker.error.connect(errors.append)
    worker.run()

    assert errors == []
    assert calls == [(None, 12, str(source))]
    assert verify_calls["scad"] == "// segmentation\ncube(2);\n"
    assert verify_calls["kwargs"] == {"debug": False, "sample_seed": 123}


def test_legacy_panel_workers_report_deprecation(test_output_dir):
    workers = [
        main_window.FeatureInventoryWorker(
            str(test_output_dir), str(test_output_dir / "inv.json"), True, None, 1
        ),
        main_window.FeatureGraphWorker(
            "single_file",
            input_path=str(test_output_dir / "x.stl"),
            output_json=str(test_output_dir / "graph.json"),
        ),
        main_window.LocalCorpusScoringWorker(
            "manifest.json", str(test_output_dir / "score.json"), None, None, None, 5
        ),
        main_window.RealWorldCorpusScoringWorker(
            "manifest.json", str(test_output_dir / "rw.json"), None, None, False
        ),
    ]
    for worker in workers:
        errors, finished = [], []
        worker.error.connect(errors.append)
        worker.finished.connect(finished.append)
        worker.run()
        assert finished == []
        assert len(errors) == 1 and "Deprecated (T-004)" in errors[0]
    assert sorted(p.name for p in test_output_dir.iterdir()) == []
