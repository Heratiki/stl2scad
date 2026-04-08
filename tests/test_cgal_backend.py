"""
Tests for Phase 2 CGAL backend adapter boundary.
"""

import json
from pathlib import Path
import subprocess

import numpy as np
import stl

from stl2scad.core import cgal_backend
from stl2scad.core import recognition as recognition_module
from stl2scad.core.verification import verification as verification_module
from stl2scad.core.converter import stl2scad
from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures


def _simple_mesh() -> stl.mesh.Mesh:
    mesh = stl.mesh.Mesh(np.zeros(1, dtype=stl.mesh.Mesh.dtype))
    mesh.vectors[0] = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
    )
    return mesh


def test_resolve_cgal_helper_path_from_env(monkeypatch, test_output_dir):
    helper_file = test_output_dir / "cgal_helper.exe"
    helper_file.write_text("placeholder")
    monkeypatch.setenv(cgal_backend.CGAL_HELPER_ENV_VAR, str(helper_file))

    resolved = cgal_backend.resolve_cgal_helper_path()
    assert resolved is not None
    assert Path(resolved) == helper_file.resolve()


def test_detect_primitive_with_cgal_parses_success(monkeypatch):
    def _fake_run(*args, **kwargs):
        _ = args
        request = json.loads(kwargs["input"])
        assert request["operation"] == "detect_primitive"
        payload = {
            "detected": True,
            "scad": "sphere(r=2);",
            "primitive_type": "sphere",
            "confidence": 0.93,
            "diagnostics": {"backend": "cgal_helper"},
        }
        return subprocess.CompletedProcess(
            args=kwargs.get("args", []),
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(
        cgal_backend, "resolve_cgal_helper_path", lambda _: "fake-helper"
    )
    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = cgal_backend.detect_primitive_with_cgal(
        _simple_mesh(), helper_path="ignored"
    )
    assert result is not None
    assert result.detected is True
    assert result.scad == "sphere(r=2);"
    assert result.primitive_type == "sphere"
    assert result.confidence == 0.93


def test_detect_primitive_with_cgal_handles_invalid_output(monkeypatch):
    def _fake_run(*args, **kwargs):
        _ = args
        _ = kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="not-json",
            stderr="",
        )

    monkeypatch.setattr(
        cgal_backend, "resolve_cgal_helper_path", lambda _: "fake-helper"
    )
    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = cgal_backend.detect_primitive_with_cgal(
        _simple_mesh(), helper_path="ignored"
    )
    assert result is None


def test_cgal_helper_capabilities_end_to_end():
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "stl2scad-cgal-helper.py"
    ).resolve()

    capabilities = cgal_backend.get_cgal_backend_capabilities(
        helper_path=str(helper_path)
    )
    assert capabilities is not None
    assert capabilities.helper_mode == "prototype"
    assert "detect_primitive" in capabilities.operations
    assert "geometric_region_fallback" in capabilities.engines
    assert "sphere" in capabilities.supported_primitives


def test_cgal_capabilities_reports_python_bindings_without_helper(monkeypatch):
    monkeypatch.setattr(cgal_backend, "resolve_cgal_helper_path", lambda *_args: None)
    monkeypatch.setattr(cgal_backend, "has_cgal_python_bindings", lambda: True)

    capabilities = cgal_backend.get_cgal_backend_capabilities()
    assert capabilities is not None
    assert capabilities.cgal_bindings_available is True
    assert "cgal_python_bindings" in capabilities.engines
    assert "sphere" in capabilities.supported_primitives


def test_cgal_python_bindings_detect_sphere_when_available(test_data_dir):
    if not cgal_backend.has_cgal_python_bindings():
        return

    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    result = cgal_backend.detect_primitive_with_cgal(
        stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_sphere.stl")),
        helper_path="not-needed-for-python-bindings",
    )
    assert result is not None
    assert result.detected is True
    assert result.primitive_type == "sphere"
    assert result.scad is not None and "sphere(" in result.scad
    assert result.diagnostics is not None
    assert result.diagnostics["engine"] == "cgal_python_bindings"


def test_recognition_cgal_fallbacks_to_trimesh_when_no_cgal_detection(monkeypatch):
    mesh = _simple_mesh()

    monkeypatch.setattr(recognition_module, "_has_cgal_dependencies", lambda: True)
    monkeypatch.setattr(
        recognition_module, "_has_trimesh_manifold_dependencies", lambda: True
    )
    monkeypatch.setattr(
        recognition_module, "detect_primitive_with_cgal", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        recognition_module,
        "_detect_primitive_trimesh_manifold",
        lambda *args, **kwargs: "cube([1,1,1]);",
    )

    scad = recognition_module.detect_primitive(mesh, backend="cgal")
    assert scad is not None
    assert "cube(" in scad


def test_cgal_helper_prototype_end_to_end(test_data_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "stl2scad-cgal-helper.py"
    ).resolve()

    result = cgal_backend.detect_primitive_with_cgal(
        stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_sphere.stl")),
        helper_path=str(helper_path),
    )
    assert result is not None
    assert result.detected is True
    assert result.scad is not None and "sphere(" in result.scad
    assert result.primitive_type == "sphere"
    assert result.confidence is not None
    assert result.diagnostics is not None
    assert result.diagnostics["engine"] in {
        "cgal_python_bindings",
        "geometric_region_fallback",
    }
    if result.diagnostics["engine"] == "cgal_python_bindings":
        assert result.diagnostics["sample_point_count"] > 0
        assert result.diagnostics["shapes"][0]["coverage"] >= 0.85
    else:
        assert result.diagnostics["component_count"] == 1
        assert result.diagnostics["assigned_component_count"] == 1


def test_converter_cgal_backend_uses_helper_and_emits_metadata(
    test_data_dir, test_output_dir, monkeypatch
):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "stl2scad-cgal-helper.py"
    ).resolve()
    monkeypatch.setenv(cgal_backend.CGAL_HELPER_ENV_VAR, str(helper_path))

    output_scad = test_output_dir / "cgal_helper_output.scad"
    stl2scad(
        str(fixtures_dir / "primitive_sphere.stl"),
        str(output_scad),
        parametric=True,
        recognition_backend="cgal",
    )

    content = output_scad.read_text()
    assert "sphere(" in content
    assert "recognition_backend_requested: cgal" in content
    assert "recognition_backend_used: cgal" in content
    assert "recognized_primitive_type: sphere" in content


def test_verify_existing_conversion_report_includes_conversion_metadata(
    test_output_dir, monkeypatch
):
    stl_file = test_output_dir / "dummy.stl"
    stl_file.write_text("unused")
    scad_file = test_output_dir / "dummy.scad"
    scad_file.write_text(
        "\n".join(
            [
                "//",
                "// STL to SCAD Conversion",
                "// recognition_backend_requested: cgal",
                "// recognition_backend_used: cgal",
                "// recognized_primitive_type: sphere",
                "// recognition_confidence: 0.930000",
                '// recognition_diagnostics: {"backend":"cgal_helper"}',
                "//",
                "",
                "sphere(r=2);",
            ]
        )
    )

    monkeypatch.setattr(
        verification_module,
        "get_stl_metrics",
        lambda *_args, **_kwargs: {
            "mesh": object(),
            "bounding_box": {"width": 1.0, "height": 1.0, "depth": 1.0},
        },
    )
    monkeypatch.setattr(
        verification_module,
        "calculate_scad_metrics",
        lambda *_args, **_kwargs: {
            "mesh": object(),
            "bounding_box": {"width": 1.0, "height": 1.0, "depth": 1.0},
        },
    )
    monkeypatch.setattr(
        verification_module,
        "compare_metrics",
        lambda *_args, **_kwargs: {
            "volume": {"difference_percent": 0.0},
            "surface_area": {"difference_percent": 0.0},
            "bounding_box": {
                "width": {"difference_percent": 0.0},
                "height": {"difference_percent": 0.0},
                "depth": {"difference_percent": 0.0},
            },
        },
    )

    result = verification_module.verify_existing_conversion(
        stl_file,
        scad_file,
        tolerance={"volume": 1.0, "surface_area": 1.0, "bounding_box": 1.0},
    )
    metadata = result.report.get("conversion_metadata", {})
    assert metadata["recognition_backend_used"] == "cgal"
    assert metadata["recognized_primitive_type"] == "sphere"
    assert metadata["recognition_confidence"] == 0.93
    assert metadata["recognition_diagnostics"]["backend"] == "cgal_helper"
