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


def cross_slice_consistency(
    slices_rz: list[np.ndarray],
    mesh_scale: float,
    num_samples: int = 64,
) -> float:
    """Return a consistency score in [0, 1] across multiple (r, z) slices.

    Each slice is an (N, 2) array of (r, z) points ordered by z. We
    resample every slice to a common set of `num_samples` z-positions,
    interpolate r at each sample, and compute the mean relative disagreement.

    A score of 1.0 means all slices agree within the mesh tolerance; 0.0
    means total disagreement.
    """
    if len(slices_rz) < 2:
        return 0.0
    if mesh_scale <= 0.0:
        return 0.0

    z_mins = [float(s[:, 1].min()) for s in slices_rz]
    z_maxs = [float(s[:, 1].max()) for s in slices_rz]
    z_lo = max(z_mins)
    z_hi = min(z_maxs)
    if z_hi <= z_lo:
        return 0.0

    z_samples = np.linspace(z_lo, z_hi, num_samples)

    def _interp_r(sl: np.ndarray, zs: np.ndarray) -> np.ndarray:
        z = sl[:, 1]
        r = sl[:, 0]
        order = np.argsort(z)
        return np.interp(zs, z[order], r[order])

    r_profiles = np.vstack([_interp_r(s, z_samples) for s in slices_rz])

    per_sample_spread = r_profiles.max(axis=0) - r_profiles.min(axis=0)
    mean_spread = float(per_sample_spread.mean())
    max_spread = float(per_sample_spread.max())

    # Use a blend of mean and max to catch both global drift and localised
    # features (e.g. keyways) that raise max but not mean.
    blended = 0.5 * mean_spread + 0.5 * max_spread
    relative = blended / float(mesh_scale)
    return float(max(0.0, 1.0 - relative * 10.0))


def aggregate_profile(
    slices_rz: list[np.ndarray],
    num_samples: int = 128,
) -> np.ndarray:
    """Aggregate K (r, z) slices into one representative profile via per-z median r."""
    if not slices_rz:
        return np.empty((0, 2), dtype=np.float64)

    z_mins = [float(s[:, 1].min()) for s in slices_rz]
    z_maxs = [float(s[:, 1].max()) for s in slices_rz]
    z_lo = max(z_mins)
    z_hi = min(z_maxs)
    if z_hi <= z_lo:
        return np.empty((0, 2), dtype=np.float64)

    z_samples = np.linspace(z_lo, z_hi, num_samples)

    r_profiles = []
    for s in slices_rz:
        order = np.argsort(s[:, 1])
        r_profiles.append(np.interp(z_samples, s[order, 1], s[order, 0]))
    r_median = np.median(np.vstack(r_profiles), axis=0)

    return np.column_stack([r_median, z_samples])


def douglas_peucker_2d(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Simplify a 2D polyline by Douglas-Peucker."""
    if len(points) <= 2:
        return points.copy()

    def _perp_distance(pt: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
        seg = end - start
        seg_len = float(np.linalg.norm(seg))
        if seg_len < 1e-12:
            return float(np.linalg.norm(pt - start))
        return float(abs(np.cross(seg, pt - start)) / seg_len)

    def _recurse(idx_lo: int, idx_hi: int, keep: list[bool]) -> None:
        if idx_hi <= idx_lo + 1:
            return
        start = points[idx_lo]
        end = points[idx_hi]
        max_dist = 0.0
        max_idx = idx_lo
        for i in range(idx_lo + 1, idx_hi):
            d = _perp_distance(points[i], start, end)
            if d > max_dist:
                max_dist = d
                max_idx = i
        if max_dist > tolerance:
            keep[max_idx] = True
            _recurse(idx_lo, max_idx, keep)
            _recurse(max_idx, idx_hi, keep)

    keep = [False] * len(points)
    keep[0] = True
    keep[-1] = True
    _recurse(0, len(points) - 1, keep)
    return points[np.asarray(keep)]


def normal_field_agreement(
    vertices: np.ndarray,
    triangles: np.ndarray,
    axis: np.ndarray,
    origin: np.ndarray,
) -> float:
    """Score how well face normals agree with a revolve's expected normal field.

    For a solid of revolution about `axis`, every surface normal should lie in
    the plane spanned by `axis` and the local radial direction — it should
    have no circumferential component. We score this by the area-weighted
    fraction of the normal that is NOT circumferential.
    """
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / float(np.linalg.norm(axis))

    tri_verts = vertices[triangles]  # (F, 3, 3)
    v0, v1, v2 = tri_verts[:, 0], tri_verts[:, 1], tri_verts[:, 2]
    face_normals = np.cross(v1 - v0, v2 - v0)
    face_areas = 0.5 * np.linalg.norm(face_normals, axis=1)
    total_area = float(face_areas.sum())
    if total_area < 1e-12:
        return 0.0
    norms = np.where(face_areas[:, None] > 1e-12, face_normals / (2.0 * face_areas[:, None]), 0.0)

    centroids = tri_verts.mean(axis=1)
    rel = centroids - origin
    axial = (rel @ axis)[:, None] * axis
    radial = rel - axial
    radial_len = np.linalg.norm(radial, axis=1, keepdims=True)
    radial_dir = np.where(radial_len > 1e-9, radial / np.maximum(radial_len, 1e-12), 0.0)
    circumferential_dir = np.cross(np.broadcast_to(axis, radial_dir.shape), radial_dir)

    circ_component = np.abs(np.einsum("fi,fi->f", norms, circumferential_dir))
    agreement_per_face = 1.0 - circ_component
    return float(np.clip((agreement_per_face * face_areas).sum() / total_area, 0.0, 1.0))


def _max_r_per_z(slice_rz: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """Reduce a raw slice to one point per z-level, keeping the maximum r.

    Half-plane slicing produces multiple intersections at the same z when the
    plane crosses a flat cap: the cap's interior triangle edges contribute
    low-r points that create spurious cross-slice variance.  Keeping only the
    outermost (max-r) point per z-level removes that noise.
    """
    z = slice_rz[:, 1]
    r = slice_rz[:, 0]
    order = np.argsort(z)
    z_sorted = z[order]
    r_sorted = r[order]

    result_z: list[float] = []
    result_r: list[float] = []
    i = 0
    n = len(z_sorted)
    while i < n:
        j = i + 1
        while j < n and abs(z_sorted[j] - z_sorted[i]) < tol:
            j += 1
        result_z.append(float(z_sorted[i]))
        result_r.append(float(r_sorted[i:j].max()))
        i = j
    return np.column_stack([result_r, result_z])


def detect_revolve_solid(
    vertices: np.ndarray,
    triangles: np.ndarray,
    config: "DetectorConfig",
) -> list[dict[str, Any]]:
    """Phase 1 revolve detector. Returns [] on any gate failure, else a
    one-element list containing a `revolve_solid` feature dict.
    """
    if vertices is None or triangles is None:
        return []
    if len(vertices) < 4 or len(triangles) < 4:
        return []

    # §1.1 Candidate-axis prefilter
    axis, origin, axis_quality = candidate_revolution_axis(vertices, triangles)
    if axis is None or axis_quality < config.revolve_axis_quality_min:
        return []

    # §1.2 Multi-slice profile recovery
    K = config.revolve_slice_count
    slices: list[np.ndarray] = []
    mesh_scale = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    for k in range(K):
        angle = np.pi * float(k) / float(K)
        sl = extract_radial_slice(vertices, triangles, axis, origin, angle)
        if sl is None or len(sl) < 3:
            return []
        # Phase 1 excludes annular: every slice must touch the axis.
        if float(sl[:, 0].min()) > 1e-3 * mesh_scale:
            return []
        slices.append(sl)

    # Pre-process slices for cross-consistency: keep max-r per z-level so that
    # flat-cap interior crossings (which vary per angle) do not inflate the
    # variance.  The raw slices are still used for aggregation.
    slices_outer = [_max_r_per_z(sl) for sl in slices]
    cross_slice_score = cross_slice_consistency(slices_outer, mesh_scale=mesh_scale)
    # Accept when score is above the threshold derived from the tolerance ratio.
    cross_threshold = 1.0 - config.revolve_cross_slice_tolerance_ratio * 10.0
    if cross_slice_score < cross_threshold:
        return []

    # §1.2 Aggregate + simplify
    profile_raw = aggregate_profile(slices)
    if len(profile_raw) < 2:
        return []
    dp_tol = mesh_scale * config.revolve_douglas_peucker_tolerance_ratio
    profile = douglas_peucker_2d(profile_raw, tolerance=dp_tol)

    # §1.3 Normal-field agreement
    nf_score = normal_field_agreement(vertices, triangles, axis, origin)
    if nf_score < config.revolve_normal_field_agreement_min:
        return []

    # §1.4 Profile validity
    if len(profile) > config.revolve_profile_max_vertices:
        return []
    # Use the raw slices (already verified to touch the axis in §1.2) rather
    # than the aggregated simplified profile to determine profile_validity.
    # The median aggregation in aggregate_profile can lose the r=0 cap points
    # for solids with flat end-caps (e.g. cylinders), so checking the profile
    # min-r would falsely reject valid revolve candidates.
    slices_min_r = min(float(sl[:, 0].min()) for sl in slices)
    profile_validity = 1.0 if slices_min_r < 1e-3 * mesh_scale else 0.0
    if profile_validity < 1.0:
        return []

    # §1.5 Acceptance
    axis_q = float(axis_quality)
    cs_q = float(cross_slice_score)
    nf_q = float(nf_score)
    pv_q = float(profile_validity)
    confidence = min(axis_q, cs_q, nf_q, pv_q)
    if confidence < config.revolve_confidence_min:
        return []

    return [{
        "type": "revolve_solid",
        "detected_via": "axisymmetric_revolve",
        "axis": [float(x) for x in axis],
        "axis_origin": [float(x) for x in origin],
        "profile": [(float(r), float(z)) for r, z in profile],
        "confidence": confidence,
        "confidence_components": {
            "axis_quality": axis_q,
            "cross_slice_consistency": cs_q,
            "normal_field_agreement": nf_q,
            "profile_validity": pv_q,
        },
    }]
