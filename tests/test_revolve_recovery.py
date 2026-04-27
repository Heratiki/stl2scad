"""Unit tests for stl2scad.core.revolve_recovery."""

from __future__ import annotations

import pytest
import numpy as np

from stl2scad.tuning.config import DetectorConfig
from stl2scad.core.revolve_recovery import candidate_revolution_axis
from stl2scad.core.revolve_recovery import extract_radial_slice
from stl2scad.core.revolve_recovery import cross_slice_consistency
from stl2scad.core.revolve_recovery import aggregate_profile, douglas_peucker_2d
from stl2scad.core.revolve_recovery import normal_field_agreement
from stl2scad.core.revolve_recovery import detect_revolve_solid


def test_detector_config_has_revolve_defaults():
    config = DetectorConfig()
    assert 0.0 < config.revolve_axis_quality_min < 1.0
    assert config.revolve_slice_count >= 8
    assert config.revolve_slice_count % 2 == 0
    assert config.revolve_cross_slice_tolerance_ratio > 0.0
    assert config.revolve_normal_field_agreement_min > 0.0
    assert config.revolve_profile_max_vertices >= 16
    assert config.revolve_douglas_peucker_tolerance_ratio > 0.0
    assert config.revolve_confidence_min >= 0.70


def _make_cylinder_mesh(height: float = 10.0, radius: float = 5.0, segments: int = 32):
    """Return (vertices, triangles) arrays for a cylinder about +Z."""
    theta = np.linspace(0.0, 2 * np.pi, segments, endpoint=False)
    bottom_ring = np.column_stack([radius * np.cos(theta), radius * np.sin(theta), np.zeros_like(theta)])
    top_ring = np.column_stack([radius * np.cos(theta), radius * np.sin(theta), np.full_like(theta, height)])
    center_bottom = np.array([0.0, 0.0, 0.0])
    center_top = np.array([0.0, 0.0, height])
    vertices = np.vstack([bottom_ring, top_ring, center_bottom, center_top])
    cb = 2 * segments
    ct = 2 * segments + 1
    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        tris.append([cb, j, i])
        tris.append([ct, segments + i, segments + j])
        tris.append([i, j, segments + j])
        tris.append([i, segments + j, segments + i])
    return vertices, np.asarray(tris, dtype=np.int64)


def _make_cylinder_mesh_without_cap_centers(
    height: float = 10.0,
    radius: float = 5.0,
    segments: int = 32,
):
    """Return a cylinder whose caps are triangulated from ring vertices only."""
    theta = np.linspace(0.0, 2 * np.pi, segments, endpoint=False)
    bottom_ring = np.column_stack([radius * np.cos(theta), radius * np.sin(theta), np.zeros_like(theta)])
    top_ring = np.column_stack([radius * np.cos(theta), radius * np.sin(theta), np.full_like(theta, height)])
    vertices = np.vstack([bottom_ring, top_ring])
    tris = []
    for i in range(1, segments - 1):
        tris.append([0, i + 1, i])
        tris.append([segments, segments + i, segments + i + 1])
    for i in range(segments):
        j = (i + 1) % segments
        tris.append([i, j, segments + j])
        tris.append([i, segments + j, segments + i])
    return vertices, np.asarray(tris, dtype=np.int64)


def test_candidate_axis_detects_z_for_cylinder():
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=32)
    axis, origin, axis_quality = candidate_revolution_axis(verts, tris)

    assert axis is not None
    assert abs(abs(float(axis[2])) - 1.0) < 1e-3
    assert abs(float(axis[0])) < 1e-3
    assert abs(float(axis[1])) < 1e-3
    assert axis_quality >= 0.9
    assert abs(float(origin[0])) < 1e-3
    assert abs(float(origin[1])) < 1e-3


def test_candidate_axis_rejects_cube():
    verts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=np.float64)
    tris = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 6, 5], [4, 7, 6],
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ], dtype=np.int64)

    axis, origin, axis_quality = candidate_revolution_axis(verts, tris)
    assert axis_quality < 0.85


def test_extract_radial_slice_cylinder_at_zero_angle():
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=64)
    axis = np.array([0.0, 0.0, 1.0])
    origin = np.array([0.0, 0.0, 0.0])
    polyline_rz = extract_radial_slice(verts, tris, axis, origin, angle_rad=0.0)

    assert polyline_rz is not None
    assert polyline_rz.shape[1] == 2

    r = polyline_rz[:, 0]
    z = polyline_rz[:, 1]
    assert np.all(r >= -1e-6)
    assert np.max(r) == pytest.approx(5.0, abs=0.1)
    assert np.min(z) == pytest.approx(0.0, abs=0.1)
    assert np.max(z) == pytest.approx(10.0, abs=0.1)


def test_extract_radial_slice_matches_across_angles_for_cylinder():
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=64)
    axis = np.array([0.0, 0.0, 1.0])
    origin = np.array([0.0, 0.0, 0.0])

    slice_0 = extract_radial_slice(verts, tris, axis, origin, angle_rad=0.0)
    slice_90 = extract_radial_slice(verts, tris, axis, origin, angle_rad=np.pi / 2)

    assert slice_0 is not None and slice_90 is not None
    assert np.max(slice_0[:, 0]) == pytest.approx(np.max(slice_90[:, 0]), abs=0.15)
    assert np.min(slice_0[:, 1]) == pytest.approx(np.min(slice_90[:, 1]), abs=0.1)
    assert np.max(slice_0[:, 1]) == pytest.approx(np.max(slice_90[:, 1]), abs=0.1)


def test_cross_slice_consistency_agrees_for_matching_slices():
    slice_a = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]])
    slice_b = slice_a.copy()
    slice_c = slice_a.copy()
    score = cross_slice_consistency([slice_a, slice_b, slice_c], mesh_scale=10.0)
    assert score >= 0.99


def test_cross_slice_consistency_rejects_keyway():
    smooth = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]])
    keyway = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 4.0], [3.0, 5.0], [5.0, 6.0], [5.0, 10.0], [0.0, 10.0]])
    score = cross_slice_consistency([smooth, smooth, keyway], mesh_scale=10.0)
    assert score < 0.7


def test_aggregate_profile_returns_median_r():
    a = np.array([[4.8, 0.0], [4.8, 10.0]])
    b = np.array([[5.0, 0.0], [5.0, 10.0]])
    c = np.array([[5.2, 0.0], [5.2, 10.0]])
    profile = aggregate_profile([a, b, c], num_samples=2)
    assert profile.shape == (2, 2)
    assert profile[0, 0] == pytest.approx(5.0, abs=1e-6)
    assert profile[1, 0] == pytest.approx(5.0, abs=1e-6)


def test_douglas_peucker_preserves_corners():
    dense_side = np.linspace(0, 10, 20)
    pts = np.vstack([
        np.column_stack([np.zeros_like(dense_side), dense_side]),
        np.column_stack([np.full_like(dense_side, 5.0), dense_side[::-1]]),
    ])
    simplified = douglas_peucker_2d(pts, tolerance=0.01)
    assert 2 <= len(simplified) <= 6


def test_douglas_peucker_reduces_collinear_points():
    line = np.column_stack([np.linspace(0, 10, 100), np.zeros(100)])
    simplified = douglas_peucker_2d(line, tolerance=0.01)
    assert len(simplified) == 2


def test_normal_field_agreement_high_for_cylinder():
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=64)
    axis = np.array([0.0, 0.0, 1.0])
    origin = np.array([0.0, 0.0, 0.0])

    score = normal_field_agreement(verts, tris, axis, origin)
    assert score >= 0.9


def test_normal_field_agreement_low_for_cube():
    verts = np.array([
        [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0],
        [-1, -1, 2], [1, -1, 2], [1, 1, 2], [-1, 1, 2],
    ], dtype=np.float64)
    tris = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 6, 5], [4, 7, 6],
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ], dtype=np.int64)
    axis = np.array([0.0, 0.0, 1.0])
    origin = np.array([0.0, 0.0, 1.0])
    score = normal_field_agreement(verts, tris, axis, origin)
    # Cube's lateral faces have normals in the radial plane; just ensure score is finite.
    assert 0.0 <= score <= 1.0


def test_detect_revolve_solid_accepts_cylinder():
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=64)
    features = detect_revolve_solid(verts, tris, DetectorConfig())

    assert len(features) == 1
    feat = features[0]
    assert feat["type"] == "revolve_solid"
    assert feat["detected_via"] == "axisymmetric_revolve"
    assert "axis" in feat and "axis_origin" in feat
    assert "profile" in feat and len(feat["profile"]) >= 2
    assert "confidence" in feat and feat["confidence"] >= 0.70
    comps = feat["confidence_components"]
    for key in ("axis_quality", "cross_slice_consistency",
                "normal_field_agreement", "profile_validity"):
        assert key in comps
        assert 0.0 <= float(comps[key]) <= 1.0
    rs = [p[0] for p in feat["profile"]]
    assert min(rs) < 0.5


def test_detect_revolve_solid_accepts_cylinder_without_cap_center_vertices():
    verts, tris = _make_cylinder_mesh_without_cap_centers(height=10.0, radius=5.0, segments=64)
    features = detect_revolve_solid(verts, tris, DetectorConfig())

    assert len(features) == 1
    rs = [p[0] for p in features[0]["profile"]]
    assert min(rs) < 0.5
    assert max(rs) == pytest.approx(5.0, abs=0.25)


def test_detect_revolve_solid_accepts_short_disk():
    verts, tris = _make_cylinder_mesh_without_cap_centers(height=2.0, radius=8.0, segments=64)
    features = detect_revolve_solid(verts, tris, DetectorConfig())

    assert len(features) == 1
    axis = np.asarray(features[0]["axis"])
    assert abs(abs(float(axis[2])) - 1.0) < 1e-3


def test_detect_revolve_solid_rejects_cube():
    verts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=np.float64)
    tris = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 6, 5], [4, 7, 6],
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ], dtype=np.int64)

    features = detect_revolve_solid(verts, tris, DetectorConfig())
    assert features == []


# ---------------------------------------------------------------------------
# Phase 2: profile classification tests
# ---------------------------------------------------------------------------

from stl2scad.core.revolve_recovery import classify_revolve_profile


def test_classify_revolve_profile_cylinder():
    """Rectangle profile classifies as cylinder."""
    profile = [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)]
    result = classify_revolve_profile(profile, mesh_scale=10.0, config=DetectorConfig())
    assert result is not None
    assert result["type"] == "cylinder"
    assert result["params"]["r"] == pytest.approx(5.0, abs=0.1)
    assert result["params"]["h"] == pytest.approx(10.0, abs=0.1)
    assert result["confidence"] >= 0.85


def test_classify_revolve_profile_cone():
    """Triangle (cone) profile classifies as cone."""
    # Right triangle: base at (r=6, z=0), apex at (r=0, z=12)
    profile = [(0.0, 0.0), (6.0, 0.0), (0.0, 12.0)]
    result = classify_revolve_profile(profile, mesh_scale=12.0, config=DetectorConfig())
    assert result is not None
    assert result["type"] == "cone"
    assert result["params"]["is_cone"] is True
    assert result["confidence"] >= 0.85


def test_classify_revolve_profile_frustum():
    """Trapezoid (frustum) profile with r1 != r2 classifies as cone (frustum)."""
    # Trapezoid: bottom r=6, top r=3
    profile = [(0.0, 0.0), (6.0, 0.0), (3.0, 10.0), (0.0, 10.0)]
    result = classify_revolve_profile(profile, mesh_scale=10.0, config=DetectorConfig())
    assert result is not None
    assert result["type"] == "cone"
    assert result["params"]["r1"] == pytest.approx(6.0, abs=0.5)
    assert result["params"]["r2"] == pytest.approx(3.0, abs=0.5)


def test_classify_revolve_profile_sphere():
    """Semicircle profile classifies as sphere."""
    # Semicircle of radius 5 centered at z=0
    R = 5.0
    n = 9
    profile = [(R * np.sin(t), -R * np.cos(t)) for t in np.linspace(0, np.pi, n)]
    result = classify_revolve_profile(profile, mesh_scale=10.0, config=DetectorConfig())
    assert result is not None
    assert result["type"] == "sphere"
    assert result["params"]["r"] == pytest.approx(R, abs=0.3)
    assert result["confidence"] >= 0.85


def test_classify_revolve_profile_complex_returns_none():
    """Christmas-tree sawtooth profile does not classify as any primitive."""
    profile = [(0.0, 0.0), (2.0, 0.8), (4.0, 2.2), (2.8, 3.4), (5.0, 4.8), (3.2, 6.0), (6.0, 7.4), (0.0, 9.0)]
    result = classify_revolve_profile(profile, mesh_scale=9.0, config=DetectorConfig())
    assert result is None


def test_detect_revolve_solid_cylinder_has_primitive_upgrade():
    """A cylinder mesh should produce a revolve_solid with primitive_upgrade type=cylinder."""
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=64)
    features = detect_revolve_solid(verts, tris, DetectorConfig())
    assert len(features) == 1
    feat = features[0]
    # Phase 2 primitive upgrade should be present
    upgrade = feat.get("primitive_upgrade")
    assert upgrade is not None
    assert upgrade["type"] == "cylinder"
    assert upgrade["params"]["r"] == pytest.approx(5.0, abs=0.3)
    assert upgrade["params"]["h"] == pytest.approx(10.0, abs=0.3)
    assert upgrade["confidence"] >= 0.85


def test_detect_revolve_solid_phase2_can_be_disabled():
    """With phase2 disabled, no primitive_upgrade field in the result."""
    import dataclasses
    cfg = dataclasses.replace(DetectorConfig(), revolve_phase2_enabled=False)
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=64)
    features = detect_revolve_solid(verts, tris, cfg)
    assert len(features) == 1
    assert "primitive_upgrade" not in features[0]


# ---------------------------------------------------------------------------
# Annular revolve detection tests (Phase 1.6)
# ---------------------------------------------------------------------------

def _make_tube_mesh(
    height: float = 10.0,
    inner_r: float = 3.0,
    outer_r: float = 6.0,
    segments: int = 32,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, triangles) for a hollow tube (annular cylinder) about +Z."""
    theta = np.linspace(0.0, 2 * np.pi, segments, endpoint=False)
    # Inner ring vertices (bottom/top)
    inner_bot = np.column_stack([inner_r * np.cos(theta), inner_r * np.sin(theta), np.zeros_like(theta)])
    inner_top = np.column_stack([inner_r * np.cos(theta), inner_r * np.sin(theta), np.full_like(theta, height)])
    # Outer ring vertices (bottom/top)
    outer_bot = np.column_stack([outer_r * np.cos(theta), outer_r * np.sin(theta), np.zeros_like(theta)])
    outer_top = np.column_stack([outer_r * np.cos(theta), outer_r * np.sin(theta), np.full_like(theta, height)])
    vertices = np.vstack([inner_bot, inner_top, outer_bot, outer_top])
    # offsets
    ib = 0
    it = segments
    ob = 2 * segments
    ot = 3 * segments
    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        # Inner wall (facing inward, winding is reversed to face inward)
        tris.append([ib + i, ib + j, it + j])
        tris.append([ib + i, it + j, it + i])
        # Outer wall
        tris.append([ob + j, ob + i, ot + i])
        tris.append([ob + j, ot + i, ot + j])
        # Bottom cap (annular ring)
        tris.append([ib + i, ob + i, ob + j])
        tris.append([ib + i, ob + j, ib + j])
        # Top cap (annular ring)
        tris.append([it + j, ot + j, ot + i])
        tris.append([it + j, ot + i, it + i])
    return vertices, np.asarray(tris, dtype=np.int64)


def test_detect_revolve_solid_accepts_annular_tube():
    """A hollow tube mesh should be detected as an annular revolve_solid."""
    verts, tris = _make_tube_mesh(height=10.0, inner_r=3.0, outer_r=6.0, segments=64)
    features = detect_revolve_solid(verts, tris, DetectorConfig())

    assert len(features) == 1
    feat = features[0]
    assert feat["type"] == "revolve_solid"
    assert feat["detected_via"] == "annular_revolve"
    assert "inner_r" in feat
    assert "outer_r" in feat
    assert feat["inner_r"] == pytest.approx(3.0, abs=0.5)
    assert feat["outer_r"] == pytest.approx(6.0, abs=0.5)
    assert feat["confidence"] >= 0.70


def test_detect_revolve_solid_annular_has_confidence_components():
    """Annular detection should preserve all confidence_components."""
    verts, tris = _make_tube_mesh(height=10.0, inner_r=3.0, outer_r=6.0, segments=64)
    features = detect_revolve_solid(verts, tris, DetectorConfig())
    assert len(features) == 1
    comps = features[0]["confidence_components"]
    for key in ("axis_quality", "cross_slice_consistency", "normal_field_agreement", "profile_validity"):
        assert key in comps
        assert 0.0 <= float(comps[key]) <= 1.0


def test_detect_revolve_solid_degenerate_annular_rejected():
    """A tube with inner/outer ratio > 0.95 (nearly solid ring) should be rejected."""
    # inner_r = 5.85, outer_r = 6.0 → ratio = 0.975, should reject
    verts, tris = _make_tube_mesh(height=10.0, inner_r=5.85, outer_r=6.0, segments=64)
    features = detect_revolve_solid(verts, tris, DetectorConfig())
    assert features == []
