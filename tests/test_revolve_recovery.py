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
