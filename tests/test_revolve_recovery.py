"""Unit tests for stl2scad.core.revolve_recovery."""

from __future__ import annotations

import pytest
import numpy as np

from stl2scad.tuning.config import DetectorConfig
from stl2scad.core.revolve_recovery import candidate_revolution_axis


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
