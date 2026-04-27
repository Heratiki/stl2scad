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
    moment.  `axis_quality` is 1 minus the relative spread of the closest
    eigenvalue pair — closer to 1.0 means two covariance moments are
    perfectly paired (good revolution candidate); closer to 0.0 means the
    pairing breaks down.

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
    # and one distinct eigenvalue.  The distinct value can be the largest
    # (tall cylinder) or the smallest (short disk), so choose the eigenvector
    # outside the closest eigenvalue pair.
    span = hi - lo
    if span < 1e-12:
        return None, None, 0.0

    if abs(mid - lo) <= abs(hi - mid):
        close_spread = mid - lo
        axis = eigenvectors[:, order[2]].copy()
    else:
        close_spread = hi - mid
        axis = eigenvectors[:, order[0]].copy()
    axis_quality = 1.0 - float(close_spread / span)
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

    Returns None if the intersection is degenerate (fewer than 2 points).
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
            if r < -1e-9:
                continue
            r = max(r, 0.0)  # clamp floating-point rounding near the axis
            z = float(z_coord[e0] + t * (z_coord[e1] - z_coord[e0]))
            intersections.append((r, z))

    if len(intersections) < 2:
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
        d = pt - start
        return float(abs(seg[0] * d[1] - seg[1] * d[0]) / seg_len)

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


def _close_axis_touching_profile(
    profile: np.ndarray,
    slices_rz: list[np.ndarray],
    mesh_scale: float,
) -> np.ndarray:
    """Add axis endpoints to profiles whose raw slices touch the revolution axis.

    OpenSCAD cap triangulation does not guarantee every sampled half-plane has
    an edge crossing the exact axis.  The raw slice set can still prove the
    profile is non-annular when at least one cap slice touches r=0; in that
    case, close the polygon on the axis so the emitted rotate_extrude is solid
    instead of tube-like.
    """
    if len(profile) == 0 or not slices_rz:
        return profile

    axis_tol = 1e-3 * mesh_scale
    if min(float(sl[:, 0].min()) for sl in slices_rz) > axis_tol:
        return profile

    all_points = np.vstack(slices_rz)
    z_lo = float(all_points[:, 1].min())
    z_hi = float(all_points[:, 1].max())
    z_tol = max(mesh_scale * 1e-6, 1e-6)

    closed = profile.copy()
    if abs(float(closed[0, 1]) - z_lo) <= z_tol and float(closed[0, 0]) > axis_tol:
        closed = np.vstack([[0.0, z_lo], closed])
    if abs(float(closed[-1, 1]) - z_hi) <= z_tol and float(closed[-1, 0]) > axis_tol:
        closed = np.vstack([closed, [0.0, z_hi]])
    return closed


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


def classify_revolve_profile(
    profile: list[tuple[float, float]],
    mesh_scale: float,
    config: "DetectorConfig",
) -> Optional[dict[str, Any]]:
    """Attempt to classify a simplified revolve profile as a native primitive.

    Returns a dict with keys {type, params, confidence} when a native primitive
    matches with confidence >= config.revolve_phase2_min_confidence, else None.

    Primitive types returned:
      "cylinder" — rectangle profile: params = {r, h, z_lo}
      "cone"     — right triangle / linear frustum: params = {r1, r2, h, z_lo}
      "sphere"   — semicircle arc profile: params = {r, z_center}

    Phase 2 does NOT produce a new IR node type. The returned dict is stored on
    the revolve_solid feature as "primitive_upgrade" and consumed only by the
    SCAD emitter.
    """
    if not profile or len(profile) < 2:
        return None

    pts = list(profile)
    r_vals = [p[0] for p in pts]
    z_vals = [p[1] for p in pts]
    r_max = max(r_vals)
    z_lo = min(z_vals)
    z_hi = max(z_vals)
    h = z_hi - z_lo

    if r_max < 1e-9 or h < 1e-9 or mesh_scale < 1e-9:
        return None

    tol_r = mesh_scale * config.revolve_phase2_rect_tolerance_ratio
    tol_z = mesh_scale * config.revolve_phase2_rect_tolerance_ratio

    # --- Cylinder check: rectangle profile ---
    # A cylinder's (r,z) profile is a rectangle with two edges at r=0 and r=r_max,
    # and two edges at z=z_lo and z=z_hi. Every profile point must lie near one of
    # the four rectangle edges.
    cylinder_residuals: list[float] = []
    for r, z in pts:
        d_axis = r                      # distance to r=0 edge
        d_outer = abs(r - r_max)        # distance to r=r_max edge
        d_bottom = abs(z - z_lo)        # distance to z=z_lo edge
        d_top = abs(z - z_hi)           # distance to z=z_hi edge
        cylinder_residuals.append(min(d_axis, d_outer, d_bottom, d_top))
    cyl_mean_res = sum(cylinder_residuals) / len(cylinder_residuals)
    cyl_confidence = max(0.0, 1.0 - cyl_mean_res / r_max)

    # Additional structural check: the profile must include points near all 4 corners.
    # Without this, a single diagonal line segment would score well.
    has_axis_lo = any(r < tol_r and abs(z - z_lo) < tol_z for r, z in pts)
    has_axis_hi = any(r < tol_r and abs(z - z_hi) < tol_z for r, z in pts)
    has_outer_lo = any(abs(r - r_max) < tol_r and abs(z - z_lo) < tol_z for r, z in pts)
    has_outer_hi = any(abs(r - r_max) < tol_r and abs(z - z_hi) < tol_z for r, z in pts)

    if (has_axis_lo and has_axis_hi and has_outer_lo and has_outer_hi
            and cyl_confidence >= config.revolve_phase2_min_confidence):
        return {
            "type": "cylinder",
            "params": {"r": float(r_max), "h": float(h), "z_lo": float(z_lo)},
            "confidence": float(cyl_confidence),
        }

    # --- Cone/frustum check: the lateral profile is a straight line from
    # (r_bottom, z_lo) to (r_top, z_hi), with the endpoints on or near the axis
    # at one or both ends.
    # We compute r values at z_lo and z_hi by linear interpolation/extrapolation
    # across all points, then check the residual of every point from that line.
    if len(pts) >= 2:
        # Fit a line r = a*z + b to the outermost profile points.
        # Use the points NOT on the axis to fit the slant.
        outer_pts = [(r, z) for r, z in pts if r > tol_r]
        if len(outer_pts) >= 2:
            # Linear least-squares fit: r = a*z + b
            z_arr = np.array([p[1] for p in outer_pts])
            r_arr = np.array([p[0] for p in outer_pts])
            if len(outer_pts) == 1:
                a, b = 0.0, float(outer_pts[0][0])
            else:
                # np.polyfit: r = a*z + b
                coeffs = np.polyfit(z_arr, r_arr, 1)
                a, b = float(coeffs[0]), float(coeffs[1])
            r_bottom = float(np.clip(a * z_lo + b, 0.0, None))
            r_top = float(np.clip(a * z_hi + b, 0.0, None))
            # Residual: every non-axis point should lie near the slant line
            cone_residuals: list[float] = []
            for r, z in pts:
                if r < tol_r:
                    continue  # axis points are valid cone/frustum caps
                r_expected = a * z + b
                cone_residuals.append(abs(r - r_expected))
            if cone_residuals:
                cone_mean_res = sum(cone_residuals) / len(cone_residuals)
                cone_confidence = max(0.0, 1.0 - cone_mean_res / r_max)
                # A cone has one end at r=0; a frustum has both ends > 0
                is_cone = r_bottom < tol_r or r_top < tol_r
                if cone_confidence >= config.revolve_phase2_min_confidence:
                    return {
                        "type": "cone",
                        "params": {
                            "r1": float(max(r_bottom, 0.0)),
                            "r2": float(max(r_top, 0.0)),
                            "h": float(h),
                            "z_lo": float(z_lo),
                            "is_cone": bool(is_cone),
                        },
                        "confidence": float(cone_confidence),
                    }

    # --- Sphere check: profile fits a circle arc in (r, z) space
    # A sphere profile is a semicircle: r^2 + (z - z_c)^2 = R^2,
    # with z_c = (z_lo + z_hi) / 2, R = h / 2 (for a full sphere).
    # Check if the profile fits this pattern.
    z_c = (z_lo + z_hi) / 2.0
    R_expected = h / 2.0
    if R_expected > 0:
        sphere_residuals = [
            abs(np.sqrt(max(0.0, R_expected**2 - (z - z_c)**2)) - r)
            for r, z in pts
        ]
        sphere_mean_res = sum(sphere_residuals) / len(sphere_residuals)
        sphere_confidence = max(0.0, 1.0 - sphere_mean_res / R_expected)
        # Sphere profile must touch the axis at both ends
        touches_axis_lo = any(r < tol_r and abs(z - z_lo) < tol_z for r, z in pts)
        touches_axis_hi = any(r < tol_r and abs(z - z_hi) < tol_z for r, z in pts)
        if (touches_axis_lo and touches_axis_hi
                and sphere_confidence >= config.revolve_phase2_min_confidence):
            return {
                "type": "sphere",
                "params": {"r": float(R_expected), "z_center": float(z_c)},
                "confidence": float(sphere_confidence),
            }

    return None


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
        if sl is None or len(sl) < 2:
            return []
        slices.append(sl)

    # Phase 1 excludes partial revolves and non-axisymmetric shapes, but we
    # now support both solid revolves (profile touches the axis, r_min ≈ 0)
    # and annular revolves (profile is a ring/tube that does NOT touch the
    # axis).  The detected_via field distinguishes the two cases so the
    # emitter can produce the appropriate SCAD.
    slices_min_r = min(float(sl[:, 0].min()) for sl in slices)
    slices_max_r = max(float(sl[:, 0].max()) for sl in slices)
    axis_tol = 1e-3 * mesh_scale

    # A solid revolve touches the axis; an annular revolve does not.
    is_annular = slices_min_r > axis_tol
    if is_annular:
        # Annular: there must be a meaningful inner radius (not just noise)
        # and the inner/outer ratio must be < 0.95 (otherwise it's degenerate).
        inner_r = float(slices_min_r)
        outer_r = float(slices_max_r)
        if outer_r < 1e-9 or inner_r / outer_r > 0.95:
            return []

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
    profile = _close_axis_touching_profile(profile, slices, mesh_scale)

    # §1.3 Normal-field agreement
    nf_score = normal_field_agreement(vertices, triangles, axis, origin)
    if nf_score < config.revolve_normal_field_agreement_min:
        return []

    # §1.4 Profile validity
    if len(profile) > config.revolve_profile_max_vertices:
        return []
    # For solid revolves: at least one raw slice must touch the axis (r=0).
    # For annular revolves this check is skipped — they intentionally don't
    # touch the axis.
    profile_validity = 1.0 if (is_annular or slices_min_r < 1e-3 * mesh_scale) else 0.0
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

    detected_via = "annular_revolve" if is_annular else "axisymmetric_revolve"
    feature: dict[str, Any] = {
        "type": "revolve_solid",
        "detected_via": detected_via,
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
    }

    if is_annular:
        feature["inner_r"] = float(inner_r)
        feature["outer_r"] = float(outer_r)

    # §Phase 2: attempt primitive classification of the validated profile.
    if config.revolve_phase2_enabled:
        upgrade = classify_revolve_profile(
            [(float(r), float(z)) for r, z in profile],
            mesh_scale,
            config,
        )
        if upgrade is not None:
            feature["primitive_upgrade"] = upgrade

    return [feature]
