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


def test_conversion_worker_passes_backend_options(monkeypatch, test_output_dir):
    captured = {}

    def _fake_stl2scad(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(main_window, "stl2scad", _fake_stl2scad)

    worker = main_window.ConversionWorker(
        "input.stl",
        str(test_output_dir / "output.scad"),
        tolerance=1e-5,
        debug=True,
        parametric=True,
        recognition_backend="cgal",
        compute_backend="gpu",
    )

    worker.run()

    assert captured["args"] == (
        "input.stl",
        str(test_output_dir / "output.scad"),
        1e-5,
        True,
        True,
    )
    assert captured["kwargs"] == {
        "recognition_backend": "cgal",
        "compute_backend": "gpu",
    }


def test_verification_worker_passes_regeneration_and_sample_seed(
    monkeypatch, test_output_dir
):
    calls = {"convert": None, "verify": None}

    class _FakeResult:
        def save_report(self, output_file):
            Path(output_file).write_text("{}", encoding="utf-8")

    def _fake_stl2scad(*args, **kwargs):
        calls["convert"] = {"args": args, "kwargs": kwargs}
        Path(args[1]).write_text("sphere(r=2);", encoding="utf-8")
        return object()

    def _fake_verify_conversion(*args, **kwargs):
        calls["verify"] = {"args": args, "kwargs": kwargs}
        return _FakeResult()

    monkeypatch.setattr(main_window, "stl2scad", _fake_stl2scad)
    monkeypatch.setattr(main_window, "verify_conversion", _fake_verify_conversion)

    scad_file = test_output_dir / "regenerated.scad"
    worker = main_window.VerificationWorker(
        stl_file="input.stl",
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

    worker.run()

    assert calls["convert"] is not None
    assert calls["convert"]["kwargs"] == {
        "tolerance": 1e-6,
        "parametric": True,
        "recognition_backend": "trimesh_manifold",
        "compute_backend": "cpu",
    }
    assert calls["verify"] is not None
    assert calls["verify"]["args"][:3] == (
        "input.stl",
        str(scad_file),
        {"volume": 1.0, "surface_area": 2.0, "bounding_box": 0.5},
    )
    assert calls["verify"]["kwargs"] == {"debug": False, "sample_seed": 123}


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

    monkeypatch.setattr(main_window, "stl2scad", _unexpected_stl2scad)
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