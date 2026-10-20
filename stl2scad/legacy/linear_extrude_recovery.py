"""Linear extrude solid recovery from STL meshes.

Dispatch rule (Rule 2): this module runs AFTER native primitive detection
(plate/box/cylinder/revolve), only when no native primitive matched.
Integration into feature_graph.py is deferred.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from stl2scad.tuning.config import DetectorConfig


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _perpendicular_axes(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two unit vectors perpendicular to *axis* (and to each other)."""
    axis = np.asarray(axis, dtype=np.float64)
    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = ref - float(np.dot(ref, axis)) * axis
    u /= float(np.linalg.norm(u))
    v = np.cross(axis, u)
    v /= float(np.linalg.norm(v))
    return u, v


def _cap_squareness(vertices: np.ndarray, axis: np.ndarray) -> float:
    """Squareness (min_extent / max_extent) of cap vertices perpendicular to *axis*.

    Returns 1.0 for a perfectly square cap, approaching 0.0 for very elongated caps.
    Returns 0.0 when the bounding box is degenerate.
    """
    proj = vertices @ axis
    p_min, p_max = float(proj.min()), float(proj.max())
    if p_max - p_min < 1e-9:
        return 0.0
    tol = (p_max - p_min) * 0.05
    cap_mask = (proj <= p_min + tol) | (proj >= p_max - tol)
    cap_verts = vertices[cap_mask]
    if len(cap_verts) < 2:
        return 0.0
    u, _v = _perpendicular_axes(axis)
    binormal = np.cross(axis, u)
    binormal /= float(np.linalg.norm(binormal))
    u_coords = cap_verts @ u
    v_coords = cap_verts @ binormal
    du = float(u_coords.max() - u_coords.min())
    dv = float(v_coords.max() - v_coords.min())
    if max(du, dv) < 1e-9:
        return 0.0
    return float(min(du, dv) / max(du, dv))


def _candidate_extrude_axis(
    vertices: np.ndarray,
    triangles: np.ndarray,
) -> tuple[Optional[np.ndarray], float]:
    """Find the extrusion axis by trying all three canonical axes.

    For each candidate axis we compute:
    - *cap_quality*: fraction of total mesh area in cap faces (normal·axis ≥ 0.9).
    - *squareness*: how square the cap bounding box is in the perpendicular plane
      (min_extent / max_extent).  A 10×10×20 box has squareness=1.0 along Z and
      0.5 along X/Y, so Z is correctly preferred for the tall box.

    Selection: highest squareness wins; cap_quality breaks ties.
    Reported axis_quality = squareness (independent of aspect ratio, always ≥ 0.25
    for any box with a non-degenerate cap).

    Returns (axis, axis_quality).  axis is a unit vector; axis_quality ∈ [0, 1].
    Returns (None, 0.0) for degenerate meshes.
    """
    if vertices is None or len(vertices) < 4 or triangles is None or len(triangles) < 4:
        return None, 0.0

    tri_verts = vertices[triangles]  # (F, 3, 3)
    v0, v1, v2 = tri_verts[:, 0], tri_verts[:, 1], tri_verts[:, 2]
    cross = np.cross(v1 - v0, v2 - v0)
    face_areas = 0.5 * np.linalg.norm(cross, axis=1)
    total_area = float(face_areas.sum())
    if total_area < 1e-14:
        return None, 0.0

    face_normals = np.zeros_like(cross)
    valid = face_areas > 1e-14
    face_normals[valid] = cross[valid] / (2.0 * face_areas[valid, None])

    candidates: list[np.ndarray] = [
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
    ]

    best_axis: Optional[np.ndarray] = None
    best_squareness = -1.0
    best_cap_quality = 0.0

    for cand in candidates:
        dot = face_normals @ cand
        pos_mask = dot >= 0.9
        neg_mask = dot <= -0.9
        cap_area = float(face_areas[pos_mask].sum() + face_areas[neg_mask].sum())
        cap_quality = cap_area / total_area
        squareness = _cap_squareness(vertices, cand)

        # Prefer axis with highest squareness; cap_quality breaks ties.
        if (squareness > best_squareness + 1e-6) or (
            abs(squareness - best_squareness) <= 1e-6 and cap_quality > best_cap_quality
        ):
            best_squareness = squareness
            best_cap_quality = cap_quality
            best_axis = cand.copy()

    if best_axis is None or best_squareness < 1e-6:
        return None, 0.0
    return best_axis, best_squareness


def _canonical_extrude_axis_candidates(
    vertices: np.ndarray,
    triangles: np.ndarray,
) -> list[tuple[np.ndarray, float]]:
    """Return canonical extrusion axes with their cap-shape quality.

    The legacy detector selected a single axis before checking slice
    consistency.  Real prismatic parts often have elongated end caps, so a side
    axis can look "more square" than the true extrusion axis.  Keep the same
    cap-quality metric, but let the public detector run full gates on every
    canonical axis before choosing the best interpretation.
    """
    if vertices is None or len(vertices) < 4 or triangles is None or len(triangles) < 4:
        return []

    candidates: list[tuple[np.ndarray, float]] = []
    for axis in (
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
    ):
        quality = _cap_squareness(vertices, axis)
        if quality > 1e-6:
            candidates.append((axis, quality))

    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def _slice_cross_section_2d(
    vertices: np.ndarray,
    triangles: np.ndarray,
    axis: np.ndarray,
    height: float,  # projection value along axis for the cutting plane
    u: np.ndarray,
    v: np.ndarray,
) -> np.ndarray:
    """Intersect mesh edges with the plane (axis·x = height) and return 2D points."""
    proj = vertices @ axis  # (N,)
    points_2d: list[tuple[float, float]] = []

    for tri in triangles:
        for e0, e1 in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            p0, p1 = float(proj[e0]), float(proj[e1])
            if (p0 - height) * (p1 - height) > 1e-12:
                continue  # same side
            if abs(p1 - p0) < 1e-14:
                # Edge lies in the plane — add both endpoints
                for idx in (e0, e1):
                    pt = vertices[idx]
                    points_2d.append((float(pt @ u), float(pt @ v)))
                continue
            t = (height - p0) / (p1 - p0)
            pt = vertices[e0] + t * (vertices[e1] - vertices[e0])
            points_2d.append((float(pt @ u), float(pt @ v)))

    if not points_2d:
        return np.empty((0, 2), dtype=np.float64)
    arr = np.asarray(points_2d, dtype=np.float64)
    # Deduplicate
    rounded = np.round(arr, 6)
    _, uid = np.unique(rounded, axis=0, return_index=True)
    return arr[np.sort(uid)]


def _cross_section_consistency(
    slices_2d: list[np.ndarray],
    mesh_scale: float,
    num_angles: int = 32,
) -> float:
    """Score cross-section consistency by comparing bounding-box extents.

    For each slice, compute the axis-aligned bounding box dimensions [dx, dy].
    Compare across slices: mean relative spread in each dimension.  A box has
    identical bounding boxes across all slices → score near 1.0.

    Falls back gracefully when a slice has fewer than 2 points.
    """
    if not slices_2d or mesh_scale <= 0.0:
        return 0.0

    extents: list[tuple[float, float]] = []
    for pts in slices_2d:
        if len(pts) < 2:
            continue
        dx = float(pts[:, 0].max() - pts[:, 0].min())
        dy = float(pts[:, 1].max() - pts[:, 1].min())
        extents.append((dx, dy))

    if len(extents) < 2:
        return 0.0

    dx_arr = np.array([e[0] for e in extents])
    dy_arr = np.array([e[1] for e in extents])

    def _relative_spread(arr: np.ndarray) -> float:
        rng = float(arr.max() - arr.min())
        mid = float(arr.mean())
        if mid < 1e-9:
            return 0.0
        return rng / mid

    spread = 0.5 * (_relative_spread(dx_arr) + _relative_spread(dy_arr))
    return float(max(0.0, 1.0 - spread * 5.0))


def _douglas_peucker_2d(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Simplify a 2D polyline by Douglas-Peucker."""
    if len(points) <= 2:
        return points.copy()

    def _perp(pt: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
        seg = end - start
        seg_len = float(np.linalg.norm(seg))
        if seg_len < 1e-12:
            return float(np.linalg.norm(pt - start))
        d = pt - start
        return float(abs(seg[0] * d[1] - seg[1] * d[0]) / seg_len)

    def _recurse(lo: int, hi: int, keep: list[bool]) -> None:
        if hi <= lo + 1:
            return
        start, end = points[lo], points[hi]
        max_d, max_i = 0.0, lo
        for i in range(lo + 1, hi):
            d = _perp(points[i], start, end)
            if d > max_d:
                max_d, max_i = d, i
        if max_d > tolerance:
            keep[max_i] = True
            _recurse(lo, max_i, keep)
            _recurse(max_i, hi, keep)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    _recurse(0, len(points) - 1, keep)
    return points[np.asarray(keep)]


def _build_profile_from_slices(
    slices_2d: list[np.ndarray],
    num_angles: int = 32,
    tolerance_ratio: float = 0.005,
    mesh_scale: float = 1.0,
) -> np.ndarray:
    """Aggregate slices into a 2D profile polygon via angle-bucketed max-radius.

    For each of *num_angles* angle buckets (0..2π), find the vertex furthest
    from the centroid across all slices (the "convex hull approximation").
    Then Douglas-Peucker simplify the result.
    """
    # Pool all 2D points
    all_pts = np.vstack(slices_2d) if slices_2d else np.empty((0, 2), dtype=np.float64)
    if len(all_pts) < 3:
        return np.empty((0, 2), dtype=np.float64)

    centroid = all_pts.mean(axis=0)
    rel = all_pts - centroid
    angles = np.arctan2(rel[:, 1], rel[:, 0])
    radii = np.linalg.norm(rel, axis=1)

    bucket_edges = np.linspace(-np.pi, np.pi, num_angles + 1)
    profile_pts: list[np.ndarray] = []
    for i in range(num_angles):
        lo, hi = bucket_edges[i], bucket_edges[i + 1]
        mask = (angles >= lo) & (angles < hi)
        if not mask.any():
            continue
        idx = int(np.argmax(radii[mask]))
        bucket_pts = all_pts[mask]
        profile_pts.append(bucket_pts[idx])

    if len(profile_pts) < 3:
        return np.empty((0, 2), dtype=np.float64)

    poly = np.asarray(profile_pts, dtype=np.float64)
    tol = tolerance_ratio * mesh_scale
    simplified = _douglas_peucker_2d(poly, tol)
    return simplified


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_linear_extrude_solid(
    vertices: np.ndarray,  # (N, 3) unique vertices
    triangles: np.ndarray,  # (M, 3) int64 triangle indices
    config: Optional[DetectorConfig] = None,
) -> list[dict[str, Any]]:
    """Detect whether the mesh is a linear-extrude solid.

    Returns a list with one feature dict when the mesh passes all gates,
    otherwise returns [].

    Parameters
    ----------
    vertices:
        (N, 3) float64 array of unique vertex positions.
    triangles:
        (M, 3) int64 array of triangle indices into *vertices*.
    config:
        Detector tuning parameters.  Uses defaults when None.
    """
    if config is None:
        config = DetectorConfig()

    if vertices is None or len(vertices) < 4:
        return []
    if triangles is None or len(triangles) < 4:
        return []

    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)

    mesh_scale = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    if mesh_scale < 1e-9:
        return []

    best: Optional[dict[str, Any]] = None
    for axis, axis_quality in _canonical_extrude_axis_candidates(vertices, triangles):
        # ------------------------------------------------------------------
        # Gate 1 — cap axis
        # ------------------------------------------------------------------
        if axis_quality < config.linear_extrude_axis_quality_min:
            continue

        # ------------------------------------------------------------------
        # Gate 2 — cross-section consistency
        # ------------------------------------------------------------------
        proj = vertices @ axis
        h_min = float(proj.min())
        h_max = float(proj.max())
        height = h_max - h_min
        if height < 1e-9:
            continue

        u, v = _perpendicular_axes(axis)
        K = 6
        sample_heights = np.linspace(
            h_min + height * 0.05,
            h_max - height * 0.05,
            K,
        )

        slices_2d: list[np.ndarray] = []
        for h in sample_heights:
            pts = _slice_cross_section_2d(vertices, triangles, axis, float(h), u, v)
            slices_2d.append(pts)

        consistency = _cross_section_consistency(slices_2d, mesh_scale)
        if consistency < config.linear_extrude_cross_section_consistency_min:
            continue

        # ------------------------------------------------------------------
        # Gate 3 — profile extraction
        # ------------------------------------------------------------------
        profile_arr = _build_profile_from_slices(
            slices_2d,
            num_angles=32,
            tolerance_ratio=0.005,
            mesh_scale=mesh_scale,
        )
        n_profile = len(profile_arr)
        if n_profile < 3 or n_profile > config.linear_extrude_max_profile_vertices:
            continue

        profile_validity = 1.0

        # ------------------------------------------------------------------
        # Gate 4 — confidence and candidate selection
        # ------------------------------------------------------------------
        confidence = float(
            0.4 * axis_quality + 0.4 * consistency + 0.2 * profile_validity
        )
        if confidence < config.linear_extrude_confidence_min:
            continue

        # Axis origin = projection of centroid onto the axis's min plane
        centroid = vertices.mean(axis=0)
        origin = centroid - float(centroid @ axis - h_min) * axis

        # Canonical sign: positive along the dominant axis component
        canonical_axis = axis.copy()
        dominant = int(np.argmax(np.abs(canonical_axis)))
        if canonical_axis[dominant] < 0.0:
            canonical_axis = -canonical_axis

        candidate = {
            "type": "linear_extrude_solid",
            "confidence": confidence,
            "detected_via": "linear_extrude",
            "axis": canonical_axis.tolist(),
            "axis_origin": origin.tolist(),
            "height": float(height),
            "profile": profile_arr.tolist(),
            "confidence_components": {
                "axis_quality": float(axis_quality),
                "cross_section_consistency": float(consistency),
                "profile_validity": profile_validity,
            },
        }
        if best is None or confidence > float(best["confidence"]) + 1e-9:
            best = candidate
        elif (
            best is not None
            and abs(confidence - float(best["confidence"])) <= 1e-9
            and height < float(best["height"])
        ):
            best = candidate

    return [best] if best is not None else []
