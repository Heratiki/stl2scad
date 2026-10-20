"""Legacy revolve tests moved from tests/test_feature_graph.py (T-003).

Run with STL2SCAD_LEGACY_TESTS=1. The whole-mesh revolve detector is archived in
stl2scad.legacy and is off by default; tests that build a feature graph enable it.
"""

import warnings

import numpy as np
import pytest

from stl2scad.tuning.config import DetectorConfig


def test_ir_tree_wraps_revolve_solid_as_extrude_revolve():
    from stl2scad.legacy.feature_graph import _build_ir_tree

    graph = {
        "schema_version": 1,
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
            "confidence": 0.9,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.98,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
        }],
    }
    ir = _build_ir_tree(graph)
    assert ir is not None
    assert len(ir) == 1
    root = ir[0]["root"]
    assert root["type"] == "BooleanUnion"
    child = root["children"][0]
    assert child["type"] == "TransformRotate"
    assert child["child"]["type"] == "ExtrudeRevolve"
    sketch = child["child"]["profile"]
    assert sketch["type"] == "Sketch2D"
    assert sketch["kind"] == "polygon"
    assert len(sketch["points"]) == 4


def test_emit_revolve_scad_preview_generates_rotate_extrude():
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
            "confidence": 0.9,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.98,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "rotate_extrude" in scad
    assert "polygon" in scad
    assert "5" in scad and "10" in scad


def test_build_feature_graph_detects_revolve_before_cylinder(tmp_path):
    """Rule 1: revolve recovery runs before cylinder detection."""
    import numpy as np
    from stl.mesh import Mesh as StlMesh
    from stl2scad.legacy.feature_graph import build_feature_graph_for_stl

    def _cyl(h, r, seg):
        theta = np.linspace(0, 2*np.pi, seg, endpoint=False)
        br = np.column_stack([r*np.cos(theta), r*np.sin(theta), np.zeros_like(theta)])
        tr = np.column_stack([r*np.cos(theta), r*np.sin(theta), np.full_like(theta, h)])
        cb = np.array([0.0, 0.0, 0.0])
        ct = np.array([0.0, 0.0, h])
        verts = np.vstack([br, tr, cb, ct])
        icb = 2*seg
        ict = 2*seg+1
        tris = []
        for i in range(seg):
            j = (i+1) % seg
            tris.append([icb, j, i])
            tris.append([ict, seg+i, seg+j])
            tris.append([i, j, seg+j])
            tris.append([i, seg+j, seg+i])
        return verts, np.asarray(tris, dtype=np.int64)

    verts, tris = _cyl(10.0, 5.0, 64)
    mesh = StlMesh(np.zeros(len(tris), dtype=StlMesh.dtype))
    for fi, tri in enumerate(tris):
        mesh.vectors[fi] = verts[tri]
    stl_path = tmp_path / "cyl.stl"
    mesh.save(str(stl_path))

    graph = build_feature_graph_for_stl(
        stl_path, config=DetectorConfig(enable_revolve_detection=True)
    )
    types = [f["type"] for f in graph["features"]]
    assert types.count("revolve_solid") == 1
    assert types.count("cylinder_like_solid") == 0


def test_emit_revolve_scad_preview_cylinder_upgrade_emits_cylinder():
    """Phase 2: rectangle profile with primitive_upgrade emits cylinder() call."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
            "confidence": 0.95,
            "confidence_components": {
                "axis_quality": 0.97, "cross_slice_consistency": 0.98,
                "normal_field_agreement": 0.95, "profile_validity": 1.0,
            },
            "primitive_upgrade": {
                "type": "cylinder",
                "params": {"r": 5.0, "h": 10.0, "z_lo": 0.0},
                "confidence": 0.96,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "cylinder(" in scad
    assert "rotate_extrude" not in scad
    assert "revolve_r" in scad


def test_emit_revolve_scad_preview_cone_upgrade_emits_cylinder_r1_r2():
    """Phase 2: cone profile with primitive_upgrade emits cylinder(r1=..., r2=...) call."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (6.0, 0.0), (0.0, 12.0)],
            "confidence": 0.92,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.96,
                "normal_field_agreement": 0.94, "profile_validity": 1.0,
            },
            "primitive_upgrade": {
                "type": "cone",
                "params": {"r1": 6.0, "r2": 0.0, "h": 12.0, "z_lo": 0.0, "is_cone": True},
                "confidence": 0.93,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "cylinder(r1=" in scad
    assert "rotate_extrude" not in scad


def test_emit_revolve_scad_preview_sphere_upgrade_emits_sphere():
    """Phase 2: sphere profile with primitive_upgrade emits sphere() call."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, -5.0), (5.0, 0.0), (0.0, 5.0)],
            "confidence": 0.91,
            "confidence_components": {
                "axis_quality": 0.93, "cross_slice_consistency": 0.95,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
            "primitive_upgrade": {
                "type": "sphere",
                "params": {"r": 5.0, "z_center": 0.0},
                "confidence": 0.91,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "sphere(" in scad
    assert "rotate_extrude" not in scad


def test_emit_revolve_scad_preview_annular_emits_difference_cylinders():
    """Annular revolve emits difference() of two cylinders."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "annular_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(3.0, 0.0), (6.0, 0.0), (6.0, 10.0), (3.0, 10.0)],
            "inner_r": 3.0,
            "outer_r": 6.0,
            "confidence": 0.92,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.97,
                "normal_field_agreement": 0.93, "profile_validity": 1.0,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "difference()" in scad
    assert "revolve_inner_r" in scad
    assert "revolve_outer_r" in scad
    assert "rotate_extrude" not in scad


def test_emit_revolve_scad_preview_fallback_without_upgrade():
    """Without primitive_upgrade, generic rotate_extrude is emitted."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (2.0, 0.8), (4.0, 2.2), (0.0, 9.0)],
            "confidence": 0.90,
            "confidence_components": {
                "axis_quality": 0.93, "cross_slice_consistency": 0.95,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "rotate_extrude" in scad
    assert "polygon" in scad


def test_normal_field_agreement_ignores_degenerate_faces_without_warning():
    from stl2scad.legacy.revolve_recovery import normal_field_agreement

    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    triangles_valid = np.array([[0, 1, 2]], dtype=np.int64)
    triangles_with_degenerate = np.array([[0, 1, 2], [0, 1, 3]], dtype=np.int64)
    axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    origin = np.array([0.0, 0.0, 0.0], dtype=np.float64)

    score_valid = normal_field_agreement(vertices, triangles_valid, axis, origin)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        score_with_degenerate = normal_field_agreement(
            vertices,
            triangles_with_degenerate,
            axis,
            origin,
        )

    runtime_warnings = [
        warning for warning in caught if issubclass(warning.category, RuntimeWarning)
    ]
    assert runtime_warnings == []
    assert np.isclose(score_with_degenerate, score_valid)


# ---------------------------------------------------------------------------
# Phase 2 revolve profile classifier direct unit tests
# ---------------------------------------------------------------------------

def test_classify_revolve_profile_rectangle_returns_cylinder():
    """A rectangle profile in (r, z) must classify as cylinder."""
    from stl2scad.legacy.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    profile = [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    assert result is not None, "Rectangle profile must produce a cylinder upgrade"
    assert result["type"] == "cylinder"
    assert abs(result["params"]["r"] - 5.0) < 0.1
    assert abs(result["params"]["h"] - 10.0) < 0.1
    assert result["confidence"] >= config.revolve_phase2_min_confidence


def test_classify_revolve_profile_triangle_returns_cone():
    """A right-triangle profile must classify as cone (r2=0)."""
    from stl2scad.legacy.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    profile = [(0.0, 0.0), (6.0, 0.0), (0.0, 12.0)]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    assert result is not None, "Triangle profile must produce a cone upgrade"
    assert result["type"] == "cone"
    assert result["params"]["is_cone"] is True
    assert result["confidence"] >= config.revolve_phase2_min_confidence


def test_classify_revolve_profile_semicircle_returns_sphere():
    """A semicircular arc profile must classify as sphere."""
    import math
    from stl2scad.legacy.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    r_expected = 8.0
    # Sample a half-circle: r^2 + (z - R)^2 = R^2, z from 0 to 2R
    # r = sqrt(R^2 - (z - R)^2)
    n_samples = 12
    profile = []
    for i in range(n_samples + 1):
        z = 2.0 * r_expected * i / n_samples
        r = math.sqrt(max(0.0, r_expected**2 - (z - r_expected)**2))
        profile.append((r, z))
    mesh_scale = 20.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    assert result is not None, "Semicircle profile must produce a sphere upgrade"
    assert result["type"] == "sphere"
    assert abs(result["params"]["r"] - r_expected) < 0.5
    assert result["confidence"] >= config.revolve_phase2_min_confidence


def test_classify_revolve_profile_complex_returns_none():
    """A complex sawtooth profile must NOT classify as any primitive."""
    from stl2scad.legacy.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    # Sawtooth: alternating high/low r values at multiple z levels
    profile = [
        (0.0, 0.0), (5.0, 0.0), (1.0, 2.0), (5.0, 4.0),
        (1.0, 6.0), (5.0, 8.0), (0.0, 10.0),
    ]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    # A sawtooth profile is not a cylinder, cone, or sphere.
    assert result is None, f"Complex sawtooth profile must not upgrade, got: {result}"


def test_classify_revolve_profile_disabled_by_config():
    """When revolve_phase2_min_confidence=1.1, no profile should pass."""
    import dataclasses
    from stl2scad.legacy.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = dataclasses.replace(DetectorConfig(), revolve_phase2_min_confidence=1.1)
    profile = [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)
    assert result is None, "No profile should pass with min_confidence > 1.0"


def test_revolve_rectangle_profile_emits_cylinder_preview():
    """The rect-profile revolve fixture's SCAD preview should emit cylinder() (Phase 2 upgrade)."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    # Build a synthetic revolve_solid feature with primitive_upgrade=cylinder
    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
                "confidence": 0.95,
                "confidence_components": {
                    "axis_quality": 0.95, "cross_slice_consistency": 0.95,
                    "normal_field_agreement": 0.95, "profile_validity": 1.0,
                },
                "primitive_upgrade": {
                    "type": "cylinder",
                    "params": {"r": 5.0, "h": 10.0, "z_lo": 0.0},
                    "confidence": 0.99,
                },
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "cylinder(" in preview, f"Expected cylinder() in preview, got:\n{preview}"
    assert "rotate_extrude" not in preview, "Phase 2 cylinder should NOT use rotate_extrude"


def test_revolve_triangle_profile_emits_cone_preview():
    """Triangle-profile revolve should emit cylinder(r1=..., r2=...) via Phase 2."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (6.0, 0.0), (0.0, 12.0)],
                "confidence": 0.92,
                "confidence_components": {
                    "axis_quality": 0.92, "cross_slice_consistency": 0.92,
                    "normal_field_agreement": 0.92, "profile_validity": 1.0,
                },
                "primitive_upgrade": {
                    "type": "cone",
                    "params": {"r1": 6.0, "r2": 0.0, "h": 12.0, "z_lo": 0.0, "is_cone": True},
                    "confidence": 0.97,
                },
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "cylinder(" in preview, f"Expected cylinder() for cone in preview, got:\n{preview}"
    assert "r1=" in preview or "revolve_r1" in preview, f"Expected r1 parameter, got:\n{preview}"
    assert "rotate_extrude" not in preview


def test_revolve_sphere_profile_emits_sphere_preview():
    """Sphere-profile revolve should emit sphere() via Phase 2."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (8.0, 8.0), (0.0, 16.0)],
                "confidence": 0.90,
                "confidence_components": {
                    "axis_quality": 0.90, "cross_slice_consistency": 0.90,
                    "normal_field_agreement": 0.90, "profile_validity": 1.0,
                },
                "primitive_upgrade": {
                    "type": "sphere",
                    "params": {"r": 8.0, "z_center": 8.0},
                    "confidence": 0.95,
                },
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "sphere(" in preview, f"Expected sphere() in preview, got:\n{preview}"
    assert "rotate_extrude" not in preview


def test_revolve_no_upgrade_uses_rotate_extrude():
    """A revolve feature WITHOUT primitive_upgrade must still emit rotate_extrude."""
    from stl2scad.legacy.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (5.0, 2.0), (4.0, 5.0), (3.0, 8.0), (0.0, 10.0)],
                "confidence": 0.90,
                "confidence_components": {
                    "axis_quality": 0.90, "cross_slice_consistency": 0.90,
                    "normal_field_agreement": 0.90, "profile_validity": 1.0,
                },
                # No primitive_upgrade key
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "rotate_extrude" in preview, f"Expected rotate_extrude in fallback, got:\n{preview}"
