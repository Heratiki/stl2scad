"""Axisymmetric (rotate_extrude) solid recovery from STL meshes.

Phase 1: detect meshes whose design intent is a 2D profile revolved around
an axis, and return them as `revolve_solid` feature dicts with a validated
profile polygon and named confidence sub-signals.

See docs/superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md
for the spec driving this module.
"""

from __future__ import annotations

from typing import Optional

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


def extract_radial_slice(
    vertices: np.ndarray,
    triangles: np.ndarray,
    axis: np.ndarray,
    origin: np.ndarray,
    angle_rad: float,
) -> Optional[np.ndarray]:
    """Slice the mesh with a half-plane containing `axis` rotated by `angle_rad`.

    Returns an (N, 2) array of (r, z) points in the axis-local frame, ordered
    by z. The half-plane is the set of points p where the vector (p - origin)
    has zero component along the in-plane binormal and non-negative component
    along the in-plane radial direction.

    Returns None if the intersection is degenerate (fewer than 3 points).
    """
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / float(np.linalg.norm(axis))

    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    radial0 = ref - float(np.dot(ref, axis)) * axis
    radial0 /= float(np.linalg.norm(radial0))
    binormal0 = np.cross(axis, radial0)
    radial = np.cos(angle_rad) * radial0 + np.sin(angle_rad) * binormal0
    binormal = np.cos(angle_rad) * binormal0 - np.sin(angle_rad) * radial0

    points_rel = vertices - origin
    b_coord = points_rel @ binormal
    r_coord = points_rel @ radial
    z_coord = points_rel @ axis

    intersections: list[tuple[float, float]] = []
    for tri in triangles:
        for e0, e1 in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            b0, b1 = float(b_coord[e0]), float(b_coord[e1])
            if b0 == 0.0 and b1 == 0.0:
                if r_coord[e0] >= 0.0:
                    intersections.append((float(r_coord[e0]), float(z_coord[e0])))
                if r_coord[e1] >= 0.0:
                    intersections.append((float(r_coord[e1]), float(z_coord[e1])))
                continue
            if (b0 > 0.0 and b1 > 0.0) or (b0 < 0.0 and b1 < 0.0):
                continue
            t = b0 / (b0 - b1)
            r = float(r_coord[e0] + t * (r_coord[e1] - r_coord[e0]))
            if r < 0.0:
                continue
            z = float(z_coord[e0] + t * (z_coord[e1] - z_coord[e0]))
            intersections.append((r, z))

    if len(intersections) < 3:
        return None

    polyline = np.asarray(intersections, dtype=np.float64)
    rounded = np.round(polyline, decimals=6)
    _, unique_idx = np.unique(rounded, axis=0, return_index=True)
    polyline = polyline[np.sort(unique_idx)]
    order = np.argsort(polyline[:, 1])
    return polyline[order]
