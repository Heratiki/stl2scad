"""Axisymmetric (rotate_extrude) solid recovery from STL meshes.

Phase 1: detect meshes whose design intent is a 2D profile revolved around
an axis, and return them as `revolve_solid` feature dicts with a validated
profile polygon and named confidence sub-signals.

See docs/superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md
for the spec driving this module.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from stl2scad.tuning.config import DetectorConfig


def candidate_revolution_axis(
    vertices: np.ndarray,
    triangles: np.ndarray,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray], float]:
    """Return (axis, axis_origin, axis_quality) via inertia-tensor prefilter.

    A solid of revolution has two equal principal moments and one distinct
    moment.  `axis_quality` is 1 minus the relative spread of the two
    smallest eigenvalues — closer to 1.0 means two of the covariance
    moments are perfectly paired (good revolution candidate); closer to 0.0
    means all three are equally spread (cube-like) or the pairing breaks
    down.

    Returns (None, None, 0.0) for degenerate meshes. The caller applies the
    `revolve_axis_quality_min` threshold from DetectorConfig.
    """
    if vertices is None or len(vertices) < 4 or triangles is None or len(triangles) < 4:
        return None, None, 0.0

    centroid = vertices.mean(axis=0)
    centered = vertices - centroid

    # Build a face-area-weighted covariance matrix so the metric is less
    # sensitive to non-uniform vertex sampling along the surface.
    cov = np.zeros((3, 3))
    for tri in triangles:
        v0 = centered[tri[0]]
        v1 = centered[tri[1]]
        v2 = centered[tri[2]]
        pts = np.array([v0, v1, v2])
        area = 0.5 * float(np.linalg.norm(np.cross(v1 - v0, v2 - v0)))
        if area < 1e-14:
            continue
        tc = pts.mean(axis=0)
        cov += area * (np.outer(tc, tc) + pts.T @ pts / 6.0)

    # Fall back to plain vertex covariance if all faces were degenerate.
    if np.max(np.abs(cov)) < 1e-14:
        cov = np.cov(centered.T)

    eigenvalues, eigenvectors = np.linalg.eigh(cov)

    # Sort ascending: lo, mid, hi.
    order = np.argsort(eigenvalues)
    lo, mid, hi = eigenvalues[order]

    # For a surface of revolution the covariance has two equal eigenvalues
    # (the two axes perpendicular to the revolution axis) and one distinct
    # eigenvalue (the revolution axis itself).  In a covariance matrix the
    # spread *along* the revolution axis dominates, so the revolution axis
    # is the eigenvector for the *largest* (hi) eigenvalue.
    #
    # axis_quality: 1.0 means lo==mid perfectly (pure solid of revolution);
    # 0.0 means all eigenvalues are equal (sphere or cube).
    span = hi - lo
    if span < 1e-12:
        return None, None, 0.0

    axis_quality = 1.0 - float((mid - lo) / span)

    axis = eigenvectors[:, order[2]].copy()
    axis = axis / float(np.linalg.norm(axis))

    # Canonical sign: positive along the dominant component.
    dominant = int(np.argmax(np.abs(axis)))
    if axis[dominant] < 0.0:
        axis = -axis

    return axis, centroid, axis_quality
