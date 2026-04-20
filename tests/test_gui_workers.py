"""
Focused tests for GUI worker plumbing.
"""

from pathlib import Path

from stl2scad.gui import main_window


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