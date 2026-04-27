"""Tests for stl2scad.core.linear_extrude_recovery."""

from __future__ import annotations

import numpy as np
import pytest

from stl2scad.core.linear_extrude_recovery import detect_linear_extrude_solid


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------


def _make_box(lx: float, ly: float, lz: float):
    """Return (vertices, triangles) for an axis-aligned box."""
    v = np.array(
        [
            [0, 0, 0],
            [lx, 0, 0],
            [lx, ly, 0],
            [0, ly, 0],
            [0, 0, lz],
            [lx, 0, lz],
            [lx, ly, lz],
            [0, ly, lz],
        ],
        dtype=np.float64,
    )
    t = np.array(
        [
            [0, 2, 1],
            [0, 3, 2],
            [4, 5, 6],
            [4, 6, 7],
            [0, 1, 5],
            [0, 5, 4],
            [2, 3, 7],
            [2, 7, 6],
            [1, 2, 6],
            [1, 6, 5],
            [0, 4, 7],
            [0, 7, 3],
        ],
        dtype=np.int64,
    )
    return v, t


def _make_sphere(r: float = 5.0, stacks: int = 8, slices: int = 8):
    """Return (vertices, triangles) for a UV sphere."""
    verts: list[list[float]] = []
    for i in range(stacks + 1):
        phi = np.pi * i / stacks
        for j in range(slices):
            theta = 2 * np.pi * j / slices
            verts.append(
                [
                    r * np.sin(phi) * np.cos(theta),
                    r * np.sin(phi) * np.sin(theta),
                    r * np.cos(phi),
                ]
            )
    verts_arr = np.array(verts, dtype=np.float64)
    tris: list[list[int]] = []
    for i in range(stacks):
        for j in range(slices):
            a = i * slices + j
            b = i * slices + (j + 1) % slices
            c = (i + 1) * slices + j
            d = (i + 1) * slices + (j + 1) % slices
            tris.extend([[a, b, c], [b, d, c]])
    return verts_arr, np.array(tris, dtype=np.int64)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detect_linear_extrude_accepts_box():
    """A rectangular box should be accepted as a linear_extrude_solid."""
    v, t = _make_box(20.0, 10.0, 5.0)
    results = detect_linear_extrude_solid(v, t)

    assert len(results) > 0, "Expected a detection but got empty result"
    feat = results[0]
    assert feat["type"] == "linear_extrude_solid"
    assert feat["confidence"] > 0.5

    # Detected height should be within 20 % of the true extrude height (5.0)
    detected_height = feat["height"]
    assert abs(detected_height - 5.0) / 5.0 < 0.20, (
        f"Height {detected_height:.3f} too far from expected 5.0"
    )


def test_detect_linear_extrude_rejects_sphere():
    """A sphere should not match as a linear extrude solid."""
    v, t = _make_sphere()
    results = detect_linear_extrude_solid(v, t)
    assert results == [], f"Expected [], got {results}"


def test_confidence_components_present():
    """confidence_components must contain all three required keys."""
    v, t = _make_box(20.0, 10.0, 5.0)
    results = detect_linear_extrude_solid(v, t)
    assert len(results) > 0, "Expected a detection"

    cc = results[0]["confidence_components"]
    assert "axis_quality" in cc
    assert "cross_section_consistency" in cc
    assert "profile_validity" in cc


def test_detect_linear_extrude_axis_aligned_with_box_z():
    """For a tall box (z is the long axis), the detector should find a z-dominant axis."""
    v, t = _make_box(10.0, 10.0, 20.0)
    results = detect_linear_extrude_solid(v, t)
    assert len(results) > 0, "Expected a detection for tall box"

    axis = results[0]["axis"]
    # The z component should dominate (absolute value > 0.8)
    assert abs(axis[2]) > 0.8, (
        f"Expected z-dominant axis, got axis={axis}"
    )


def test_detect_linear_extrude_profile_nonempty():
    """The profile polygon must have at least 3 vertices."""
    v, t = _make_box(20.0, 10.0, 5.0)
    results = detect_linear_extrude_solid(v, t)
    assert len(results) > 0, "Expected a detection"

    profile = results[0]["profile"]
    assert len(profile) >= 3, f"Profile too short: {len(profile)} points"
