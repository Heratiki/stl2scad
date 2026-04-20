"""
Tests for Phase 2 CGAL backend adapter boundary.
"""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
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


def _sample_cylinder_points(
    center: np.ndarray,
    axis: np.ndarray,
    radius: float,
    height: float,
) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    if abs(float(np.dot(axis, np.array([1.0, 0.0, 0.0])))) < 0.9:
        basis_seed = np.array([1.0, 0.0, 0.0])
    else:
        basis_seed = np.array([0.0, 1.0, 0.0])
    basis_u = np.cross(axis, basis_seed)
    basis_u = basis_u / np.linalg.norm(basis_u)
    basis_v = np.cross(axis, basis_u)

    half_height = height * 0.5
    points = []
    for z in (-half_height, -half_height * 0.33, half_height * 0.33, half_height):
        for angle in np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False):
            ring = (
                center
                + axis * z
                + basis_u * (radius * np.cos(angle))
                + basis_v * (radius * np.sin(angle))
            )
            points.append(ring)
    return np.asarray(points, dtype=np.float64)


def _sample_cone_points(
    apex: np.ndarray,
    axis: np.ndarray,
    angle_radians: float,
    t_start: float,
    t_end: float,
) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    if abs(float(np.dot(axis, np.array([1.0, 0.0, 0.0])))) < 0.9:
        basis_seed = np.array([1.0, 0.0, 0.0])
    else:
        basis_seed = np.array([0.0, 1.0, 0.0])
    basis_u = np.cross(axis, basis_seed)
    basis_u = basis_u / np.linalg.norm(basis_u)
    basis_v = np.cross(axis, basis_u)

    points = []
    for t in np.linspace(t_start, t_end, 8):
        radius = abs(np.tan(angle_radians) * t)
        for angle in np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False):
            ring = (
                apex
                + axis * t
                + basis_u * (radius * np.cos(angle))
                + basis_v * (radius * np.sin(angle))
            )
            points.append(ring)
    return np.asarray(points, dtype=np.float64)


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
    if cgal_backend.has_cgal_python_bindings():
        assert "cgal_python_bindings" in capabilities.engines
    assert "sphere" in capabilities.supported_primitives


def test_cgal_capabilities_reports_python_bindings_without_helper(monkeypatch):
    monkeypatch.setattr(cgal_backend, "resolve_cgal_helper_path", lambda *_args: None)
    monkeypatch.setattr(cgal_backend, "has_cgal_python_bindings", lambda: True)

    capabilities = cgal_backend.get_cgal_backend_capabilities()
    assert capabilities is not None
    assert capabilities.cgal_bindings_available is True
    assert "cgal_python_bindings" in capabilities.engines
    assert "sphere" in capabilities.supported_primitives
    assert "cylinder" in capabilities.supported_primitives
    assert "cone" in capabilities.supported_primitives
    assert "composite_union" in capabilities.supported_primitives


def test_parse_cgal_shape_description_parses_cone():
    description = (
        "Type: cone "
        "apex: (0.0, 0.0, 0.0) "
        "axis: (0.0, 0.0, 1.0) "
        "angle: 0.5235987756 "
        "#Pts: 90"
    )
    parsed = cgal_backend._parse_cgal_shape_description(description, total_points=100)
    assert parsed is not None
    assert parsed["primitive_type"] == "cone"
    assert parsed["apex"] == pytest.approx((0.0, 0.0, 0.0))
    assert parsed["axis"] == pytest.approx((0.0, 0.0, 1.0))
    assert parsed["angle"] == pytest.approx(0.5235987756)
    assert parsed["coverage"] == pytest.approx(0.9)


def test_cgal_cylinder_geometry_is_enriched_from_sample_points():
    center = np.array([1.5, -2.0, 0.75], dtype=np.float64)
    axis = np.array([0.0, 1.0, 1.0], dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    points = _sample_cylinder_points(center, axis, radius=2.0, height=6.0)

    shape = {
        "primitive_type": "cylinder",
        "center": tuple(center),
        "axis": tuple(axis),
        "radius": 2.0,
        "coverage": 0.95,
    }
    enriched = cgal_backend._enrich_shape_geometry_from_points(shape, points)

    assert enriched is not None
    assert enriched["primitive_type"] == "cylinder"
    assert enriched["height"] == pytest.approx(6.0, rel=0.05)
    assert np.asarray(enriched["finite_center"]) == pytest.approx(center, rel=1e-6)


def test_cgal_cone_geometry_is_enriched_from_sample_points():
    apex = np.array([1.5, -0.5, 2.0], dtype=np.float64)
    axis = np.array([0.0, 1.0, 1.0], dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    angle = np.deg2rad(30.0)
    points = _sample_cone_points(apex, axis, angle, t_start=1.0, t_end=5.0)

    shape = {
        "primitive_type": "cone",
        "apex": tuple(apex),
        "axis": tuple(axis),
        "angle": float(angle),
        "coverage": 0.92,
    }
    enriched = cgal_backend._enrich_shape_geometry_from_points(shape, points)

    assert enriched is not None
    assert enriched["primitive_type"] == "cone"
    assert enriched["height"] == pytest.approx(4.0, rel=0.08)
    assert enriched["radius_start"] == pytest.approx(np.tan(angle) * 1.0, rel=0.1)
    assert enriched["radius_end"] == pytest.approx(np.tan(angle) * 5.0, rel=0.1)


def test_shape_description_to_scad_emits_oriented_cylinder():
    shape = {
        "primitive_type": "cylinder",
        "axis": (0.0, 1.0, 0.0),
        "radius": 2.0,
        "height": 6.0,
        "finite_center": (1.0, 2.0, 3.0),
    }

    scad = cgal_backend._shape_description_to_scad(shape)
    assert scad is not None
    assert "cylinder(h=6.000000, r=2.000000, center=true, $fn=96);" in scad
    assert "translate([1.000000, 2.000000, 3.000000])" in scad
    assert "rotate(" in scad


def test_shape_description_to_scad_emits_oriented_cone_frustum():
    shape = {
        "primitive_type": "cone",
        "axis": (0.0, 0.0, 1.0),
        "height": 4.0,
        "radius_start": 0.5,
        "radius_end": 2.5,
        "finite_center": (0.0, 0.0, 0.0),
    }

    scad = cgal_backend._shape_description_to_scad(shape)
    assert scad is not None
    assert "cylinder(h=4.000000, r1=0.500000, r2=2.500000, center=true, $fn=96);" in scad


def test_try_assemble_multi_shape_union_accepts_disjoint_shapes():
    shapes = [
        {
            "primitive_type": "sphere",
            "center": (0.0, 0.0, 0.0),
            "radius": 1.0,
            "coverage": 0.46,
        },
        {
            "primitive_type": "sphere",
            "center": (4.0, 0.0, 0.0),
            "radius": 1.0,
            "coverage": 0.45,
        },
    ]

    scad, confidence, selected, reason = cgal_backend._try_assemble_multi_shape_union(
        shapes
    )
    assert scad is not None
    assert "union()" in scad
    assert "sphere(" in scad
    assert confidence == pytest.approx(0.91)
    assert selected is not None
    assert len(selected) == 2
    assert reason is None


def test_try_assemble_multi_shape_union_rejects_overlapping_shapes():
    shapes = [
        {
            "primitive_type": "sphere",
            "center": (0.0, 0.0, 0.0),
            "radius": 2.0,
            "coverage": 0.5,
        },
        {
            "primitive_type": "sphere",
            "center": (1.0, 0.0, 0.0),
            "radius": 2.0,
            "coverage": 0.45,
        },
    ]

    scad, confidence, selected, reason = cgal_backend._try_assemble_multi_shape_union(
        shapes
    )
    assert scad is None
    assert confidence is None
    assert selected is None
    assert reason == "overlapping_component_bboxes"


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


def test_cgal_python_bindings_detect_composite_union_when_available(test_data_dir):
    if not cgal_backend.has_cgal_python_bindings():
        return

    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    sphere_mesh = stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_sphere.stl"))
    translated = stl.mesh.Mesh(
        np.zeros(len(sphere_mesh.vectors), dtype=stl.mesh.Mesh.dtype)
    )
    translated.vectors = np.asarray(sphere_mesh.vectors, dtype=np.float64)
    translated.vectors += np.array([30.0, 0.0, 0.0], dtype=np.float64)

    merged_vectors = np.concatenate(
        [
            np.asarray(sphere_mesh.vectors, dtype=np.float64),
            np.asarray(translated.vectors, dtype=np.float64),
        ],
        axis=0,
    )
    merged_mesh = stl.mesh.Mesh(
        np.zeros(len(merged_vectors), dtype=stl.mesh.Mesh.dtype)
    )
    merged_mesh.vectors = merged_vectors
    if hasattr(merged_mesh, "update_normals"):
        merged_mesh.update_normals()

    result = cgal_backend.detect_primitive_with_cgal(
        merged_mesh,
        helper_path="not-needed-for-python-bindings",
    )
    assert result is not None
    assert result.detected is True
    assert result.primitive_type == "composite_union"
    assert result.scad is not None
    assert "union()" in result.scad
    assert result.diagnostics is not None
    assert result.diagnostics["engine"] == "cgal_python_bindings"
    assert result.diagnostics.get("multi_shape_attempted") is True


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


def test_cgal_helper_command_detects_rotated_cylinder_fixture(test_data_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "stl2scad-cgal-helper.py"
    ).resolve()
    mesh = stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_cylinder_rotated.stl"))

    result = subprocess.run(
        [sys.executable, str(helper_path), "detect-primitive", "--format", "json"],
        input=json.dumps(
            {
                "operation": "detect_primitive",
                "tolerance": 0.01,
                "mesh": {"triangles": mesh.vectors.tolist()},
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["detected"] is True
    assert payload["primitive_type"] == "cylinder"
    assert "cylinder(" in payload["scad"]
    diagnostics = payload["diagnostics"]
    assert diagnostics["engine"] in {"cgal_python_bindings", "geometric_region_fallback"}
    if diagnostics["engine"] == "geometric_region_fallback":
        assert diagnostics["component_count"] == 1
        assert diagnostics["assigned_component_count"] == 1
    else:
        assert diagnostics["sample_point_count"] > 0


def test_cgal_helper_command_detects_cone_fixture(test_data_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "stl2scad-cgal-helper.py"
    ).resolve()
    mesh = stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_cone.stl"))

    result = subprocess.run(
        [sys.executable, str(helper_path), "detect-primitive", "--format", "json"],
        input=json.dumps(
            {
                "operation": "detect_primitive",
                "tolerance": 0.01,
                "mesh": {"triangles": mesh.vectors.tolist()},
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["detected"] is True
    assert payload["primitive_type"] == "cone"
    assert "cylinder(" in payload["scad"]
    assert "r1=" in payload["scad"]
    assert "r2=" in payload["scad"]

    diagnostics = payload["diagnostics"]
    assert diagnostics["engine"] in {"cgal_python_bindings", "geometric_region_fallback"}
    if diagnostics["engine"] == "cgal_python_bindings":
        assert diagnostics["sample_point_count"] > 0
    else:
        assert diagnostics["component_count"] == 1
        assert diagnostics["assigned_component_count"] == 1


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
