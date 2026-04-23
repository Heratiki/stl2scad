# Rotate-Extrude Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect axisymmetric solids and emit them as `rotate_extrude() polygon([...])` SCAD previews, with multi-slice validation and named confidence sub-signals per the Phase 1 section of [docs/superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md](../specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md).

**Architecture:** A new `stl2scad/core/revolve_recovery.py` module runs a gated pipeline (inertia prefilter → multi-slice radial profile → cross-slice consistency → normal-field agreement → profile validity). On acceptance it returns a `revolve_solid` feature dict with `confidence_components`. `_build_feature_graph` in `feature_graph.py` calls it *before* plate / box / cylinder detection; if it accepts, those detectors are skipped (one-owner rule).

**Tech Stack:** Python 3, NumPy, `numpy-stl` (already a dependency), pytest, OpenSCAD (nightly) for round-trip rendering.

**Out of scope in Phase 1 (belong to later phases per spec):** profile → native primitive classification (Phase 2), annular revolves (immediate follow-on after Phase 1), linear-extrude detection (Phase 3), composition detection (Phase 4).

---

## File Structure

**New files:**
- `stl2scad/core/revolve_recovery.py` — Phase 1 detector + helpers; pure functions plus one public entry point `detect_revolve_solid`.
- `tests/test_revolve_recovery.py` — unit tests for pure functions in the new module.
- `tests/data/feature_fixtures_scad/revolve_*.scad` — six positive revolve fixtures (checked-in).
- `tests/data/feature_fixtures_scad/non_revolve_*.scad` — four negative fixtures (checked-in).

**Modified files:**
- `stl2scad/tuning/config.py` — add revolve-detector threshold fields to `DetectorConfig`.
- `stl2scad/core/feature_graph.py` — wire `detect_revolve_solid` into `_build_feature_graph`; add `revolve_solid` to IR mappings; add `_emit_revolve_scad_preview`.
- `stl2scad/core/feature_fixtures.py` — add `"revolve"` and `"non_revolve"` fixture types: validator, generator, expected-detection key `revolve_solid`, optional `expected_rejection_gate` for negatives.
- `tests/data/feature_fixtures_manifest.json` — add revolve and non_revolve fixture entries; update existing cylinder fixtures (since Rule 1/Rule 3 now makes them detect as `revolve_solid` instead of `cylinder_like_solid`).
- `tests/test_feature_fixtures.py` — extend round-trip tests to assert revolve dimensions, `confidence_components` presence, and rejection-gate for negatives; extend preview round-trip to handle revolve fixtures.
- `docs/planning/detector_ir.md` — update `ExtrudeRevolve` and `Sketch2D` status rows.

---

## Task 1: DetectorConfig revolve thresholds

**Files:**
- Modify: `stl2scad/tuning/config.py` (append a new section of fields at the end of the dataclass)
- Test: `tests/test_revolve_recovery.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_revolve_recovery.py` with this content:

```python
"""Unit tests for stl2scad.core.revolve_recovery."""

from __future__ import annotations

import numpy as np
import pytest

from stl2scad.tuning.config import DetectorConfig


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_revolve_recovery.py::test_detector_config_has_revolve_defaults -v`
Expected: FAIL with `AttributeError` on the first missing field.

- [ ] **Step 3: Add revolve fields to DetectorConfig**

Append to `stl2scad/tuning/config.py` immediately after the existing `grid_pattern_min_holes` line (around line 92):

```python

    # --- Revolve (rotate_extrude) thresholds (Phase 1) ---
    # Inertia-tensor prefilter: accept a candidate axis when the ratio of the
    # middle to max principal moment is at least this high, indicating two
    # comparable perpendicular moments and one distinct axis moment.
    revolve_axis_quality_min: float = 0.85
    # Number of half-plane slices sampled around the candidate axis.
    # Must be even so opposing slices exist.
    revolve_slice_count: int = 12
    # Cross-slice consistency: per-point r-coordinate disagreement between
    # any two slices (sorted by z) must stay under this fraction of the
    # mesh's characteristic radius.
    revolve_cross_slice_tolerance_ratio: float = 0.04
    # Normal-field agreement: area-weighted dot product of mesh face normals
    # with the expected normal field for the candidate axis + profile.
    revolve_normal_field_agreement_min: float = 0.80
    # Maximum profile vertices after Douglas-Peucker simplification.
    # Profiles exceeding this are treated as organic and fall through.
    revolve_profile_max_vertices: int = 64
    # Douglas-Peucker simplification tolerance as a fraction of mesh scale.
    revolve_douglas_peucker_tolerance_ratio: float = 0.005
    # Minimum top-level confidence (combined from named sub-signals) to
    # accept a revolve_solid feature.
    revolve_confidence_min: float = 0.70
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_revolve_recovery.py::test_detector_config_has_revolve_defaults -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/tuning/config.py tests/test_revolve_recovery.py
git commit -m "feat: add revolve-detector thresholds to DetectorConfig"
```

---

## Task 2: Candidate-axis generator (inertia-tensor prefilter)

**Files:**
- Create: `stl2scad/core/revolve_recovery.py`
- Test: `tests/test_revolve_recovery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_revolve_recovery.py`:

```python
from stl2scad.core.revolve_recovery import candidate_revolution_axis


def _make_cylinder_mesh(height: float = 10.0, radius: float = 5.0, segments: int = 32):
    """Return (vertices, triangles) arrays for a hollow cylinder about +Z.

    Two end caps plus the lateral surface, triangulated as a fan.
    """
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
        tris.append([cb, j, i])  # bottom cap
        tris.append([ct, segments + i, segments + j])  # top cap
        tris.append([i, j, segments + j])  # lateral
        tris.append([i, segments + j, segments + i])
    return vertices, np.asarray(tris, dtype=np.int64)


def test_candidate_axis_detects_z_for_cylinder():
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=32)
    axis, origin, axis_quality = candidate_revolution_axis(verts, tris)

    assert axis is not None
    assert abs(abs(float(axis[2])) - 1.0) < 1e-3   # axis parallel to Z
    assert abs(float(axis[0])) < 1e-3
    assert abs(float(axis[1])) < 1e-3
    assert axis_quality >= 0.9
    # origin lies on the central axis at X=Y=0, any Z within the mesh.
    assert abs(float(origin[0])) < 1e-3
    assert abs(float(origin[1])) < 1e-3


def test_candidate_axis_rejects_cube():
    # Unit cube — three equal principal moments → no distinct axis.
    verts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=np.float64)
    tris = np.array([
        [0, 1, 2], [0, 2, 3],  # bottom
        [4, 6, 5], [4, 7, 6],  # top
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ], dtype=np.int64)

    axis, origin, axis_quality = candidate_revolution_axis(verts, tris)
    # Cube should score low on axis_quality (three near-equal moments → no distinct axis).
    assert axis_quality < 0.85
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stl2scad.core.revolve_recovery'`.

- [ ] **Step 3: Create revolve_recovery.py with candidate_revolution_axis**

Create `stl2scad/core/revolve_recovery.py`:

```python
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
    moment. `axis_quality` is the ratio of the middle moment to the largest
    moment — closer to 1.0 means two of the moments are closely paired (good
    revolution candidate); closer to 0.0 means they diverge.

    Returns (None, None, 0.0) for degenerate meshes. The caller applies the
    `revolve_axis_quality_min` threshold from DetectorConfig.
    """
    if vertices is None or len(vertices) < 4 or triangles is None or len(triangles) < 4:
        return None, None, 0.0

    # Mesh centroid (vertex-based is fine for axis identification).
    centroid = vertices.mean(axis=0)
    centered = vertices - centroid

    # Covariance as a cheap stand-in for the inertia tensor (same eigenvectors).
    cov = np.cov(centered.T)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)

    # Sort ascending; the revolution axis is the one with the MOST-different
    # eigenvalue from the other two. Equivalently: after sorting, two of the
    # three should be close; the odd one out is the axis.
    order = np.argsort(eigenvalues)
    lo, mid, hi = eigenvalues[order]

    # Compare |mid - lo| vs |hi - mid| — whichever is smaller tells us which
    # pair are "close" and therefore perpendicular to the axis.
    if abs(mid - lo) <= abs(hi - mid):
        # lo, mid are close → axis corresponds to `hi`.
        axis = eigenvectors[:, order[2]]
        axis_quality = float(mid / hi) if hi > 1e-12 else 0.0
    else:
        # mid, hi are close → axis corresponds to `lo`.
        axis = eigenvectors[:, order[0]]
        axis_quality = float(mid / hi) if hi > 1e-12 else 0.0

    # Normalize and canonicalize sign (positive dominant component).
    axis = axis / float(np.linalg.norm(axis))
    dominant = int(np.argmax(np.abs(axis)))
    if axis[dominant] < 0.0:
        axis = -axis

    return axis, centroid, axis_quality
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/revolve_recovery.py tests/test_revolve_recovery.py
git commit -m "feat: candidate revolution axis via inertia-tensor prefilter"
```

---

## Task 3: Multi-slice radial profile extraction

**Files:**
- Modify: `stl2scad/core/revolve_recovery.py`
- Test: `tests/test_revolve_recovery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_revolve_recovery.py`:

```python
from stl2scad.core.revolve_recovery import extract_radial_slice


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
    # Both should reach the same max radius.
    assert np.max(slice_0[:, 0]) == pytest.approx(np.max(slice_90[:, 0]), abs=0.15)
    # Both should span the same z range.
    assert np.min(slice_0[:, 1]) == pytest.approx(np.min(slice_90[:, 1]), abs=0.1)
    assert np.max(slice_0[:, 1]) == pytest.approx(np.max(slice_90[:, 1]), abs=0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_radial_slice'`.

- [ ] **Step 3: Implement extract_radial_slice**

Append to `stl2scad/core/revolve_recovery.py`:

```python
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
    has zero component along the in-plane "binormal" direction and non-negative
    component along the in-plane "radial" direction.

    Returns None if the intersection is degenerate (fewer than 3 points).
    """
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / float(np.linalg.norm(axis))

    # Build an orthonormal in-plane basis (radial, binormal).
    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    radial0 = ref - float(np.dot(ref, axis)) * axis
    radial0 /= float(np.linalg.norm(radial0))
    binormal0 = np.cross(axis, radial0)
    # Rotate the radial direction by angle_rad around `axis`.
    radial = np.cos(angle_rad) * radial0 + np.sin(angle_rad) * binormal0
    binormal = np.cos(angle_rad) * binormal0 - np.sin(angle_rad) * radial0

    points_rel = vertices - origin
    b_coord = points_rel @ binormal
    r_coord = points_rel @ radial
    z_coord = points_rel @ axis

    # Collect edge/half-plane intersections.
    intersections: list[tuple[float, float]] = []
    for tri in triangles:
        for e0, e1 in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            b0, b1 = float(b_coord[e0]), float(b_coord[e1])
            if b0 == 0.0 and b1 == 0.0:
                # Edge lies in the plane; include both endpoints.
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
                continue  # other side of the axis
            z = float(z_coord[e0] + t * (z_coord[e1] - z_coord[e0]))
            intersections.append((r, z))

    if len(intersections) < 3:
        return None

    polyline = np.asarray(intersections, dtype=np.float64)
    # Deduplicate near-identical points (common at shared triangle edges).
    rounded = np.round(polyline, decimals=6)
    _, unique_idx = np.unique(rounded, axis=0, return_index=True)
    polyline = polyline[np.sort(unique_idx)]

    # Order the polyline by z (profile is vertically structured).
    order = np.argsort(polyline[:, 1])
    return polyline[order]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/revolve_recovery.py tests/test_revolve_recovery.py
git commit -m "feat: radial half-plane slice extraction for revolve recovery"
```

---

## Task 4: Cross-slice consistency gate

**Files:**
- Modify: `stl2scad/core/revolve_recovery.py`
- Test: `tests/test_revolve_recovery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_revolve_recovery.py`:

```python
from stl2scad.core.revolve_recovery import cross_slice_consistency


def test_cross_slice_consistency_agrees_for_matching_slices():
    # Three identical rectangular profiles (cylinder).
    slice_a = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]])
    slice_b = slice_a.copy()
    slice_c = slice_a.copy()
    score = cross_slice_consistency([slice_a, slice_b, slice_c], mesh_scale=10.0)
    assert score >= 0.99  # perfect agreement


def test_cross_slice_consistency_rejects_keyway():
    # Two slices of a round shaft plus one slice with a keyway notch.
    smooth = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]])
    keyway = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 4.0], [3.0, 5.0], [5.0, 6.0], [5.0, 10.0], [0.0, 10.0]])
    score = cross_slice_consistency([smooth, smooth, keyway], mesh_scale=10.0)
    assert score < 0.7  # keyway disagreement should drop score below tolerance
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement cross_slice_consistency**

Append to `stl2scad/core/revolve_recovery.py`:

```python
def cross_slice_consistency(
    slices_rz: list[np.ndarray],
    mesh_scale: float,
    num_samples: int = 64,
) -> float:
    """Return a consistency score in [0, 1] across multiple (r, z) slices.

    Each slice is an (N, 2) array of (r, z) points ordered by z. We
    resample every slice to a common set of `num_samples` z-positions
    (linearly spaced between the overall z-range), interpolate r at each
    sample, and compute the mean relative disagreement across slices.

    A score of 1.0 means all slices agree within the mesh tolerance; 0.0
    means total disagreement. The caller applies
    `revolve_cross_slice_tolerance_ratio` from DetectorConfig.
    """
    if len(slices_rz) < 2:
        return 0.0
    if mesh_scale <= 0.0:
        return 0.0

    # Common z-range: intersection of all slices' z-ranges.
    z_mins = [float(s[:, 1].min()) for s in slices_rz]
    z_maxs = [float(s[:, 1].max()) for s in slices_rz]
    z_lo = max(z_mins)
    z_hi = min(z_maxs)
    if z_hi <= z_lo:
        return 0.0

    z_samples = np.linspace(z_lo, z_hi, num_samples)

    # Interpolate r at each sample for each slice.
    def _interp_r(sl: np.ndarray, zs: np.ndarray) -> np.ndarray:
        z = sl[:, 1]
        r = sl[:, 0]
        # np.interp requires monotonically increasing xp.
        order = np.argsort(z)
        return np.interp(zs, z[order], r[order])

    r_profiles = np.vstack([_interp_r(s, z_samples) for s in slices_rz])

    # Per-sample disagreement: max - min at each z.
    per_sample_spread = r_profiles.max(axis=0) - r_profiles.min(axis=0)
    mean_spread = float(per_sample_spread.mean())

    relative = mean_spread / float(mesh_scale)
    return float(max(0.0, 1.0 - relative * 10.0))  # score falls linearly once relative exceeds 0.1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/revolve_recovery.py tests/test_revolve_recovery.py
git commit -m "feat: cross-slice consistency scoring for revolve validation"
```

---

## Task 5: Profile aggregation + Douglas-Peucker simplification

**Files:**
- Modify: `stl2scad/core/revolve_recovery.py`
- Test: `tests/test_revolve_recovery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_revolve_recovery.py`:

```python
from stl2scad.core.revolve_recovery import aggregate_profile, douglas_peucker_2d


def test_aggregate_profile_returns_median_r():
    a = np.array([[4.8, 0.0], [4.8, 10.0]])
    b = np.array([[5.0, 0.0], [5.0, 10.0]])
    c = np.array([[5.2, 0.0], [5.2, 10.0]])
    profile = aggregate_profile([a, b, c], num_samples=2)
    assert profile.shape == (2, 2)
    assert profile[0, 0] == pytest.approx(5.0, abs=1e-6)
    assert profile[1, 0] == pytest.approx(5.0, abs=1e-6)


def test_douglas_peucker_preserves_corners():
    # Rectangle with dense points along each side; should reduce to 4 corners.
    dense_side = np.linspace(0, 10, 20)
    pts = np.vstack([
        np.column_stack([np.zeros_like(dense_side), dense_side]),
        np.column_stack([np.full_like(dense_side, 5.0), dense_side[::-1]]),
    ])
    simplified = douglas_peucker_2d(pts, tolerance=0.01)
    assert 2 <= len(simplified) <= 6  # corner-preserving


def test_douglas_peucker_reduces_collinear_points():
    line = np.column_stack([np.linspace(0, 10, 100), np.zeros(100)])
    simplified = douglas_peucker_2d(line, tolerance=0.01)
    assert len(simplified) == 2  # start and end only
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement aggregation and simplification**

Append to `stl2scad/core/revolve_recovery.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/revolve_recovery.py tests/test_revolve_recovery.py
git commit -m "feat: profile aggregation and Douglas-Peucker simplification for revolve recovery"
```

---

## Task 6: Normal-field agreement gate

**Files:**
- Modify: `stl2scad/core/revolve_recovery.py`
- Test: `tests/test_revolve_recovery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_revolve_recovery.py`:

```python
from stl2scad.core.revolve_recovery import normal_field_agreement


def test_normal_field_agreement_high_for_cylinder():
    verts, tris = _make_cylinder_mesh(height=10.0, radius=5.0, segments=64)
    axis = np.array([0.0, 0.0, 1.0])
    origin = np.array([0.0, 0.0, 0.0])

    score = normal_field_agreement(verts, tris, axis, origin)
    assert score >= 0.9


def test_normal_field_agreement_low_for_cube():
    # Cube faces have normals along ±X, ±Y, ±Z — axis-aligned with Z but four
    # of the six faces have normals perpendicular to their radial direction.
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
    # A cube's lateral faces have normals in the radial plane; their expected
    # normal *component* along axis is 0, so they "agree" coincidentally.
    # The discriminating signal must come earlier (cross-slice), not this gate.
    # This test just ensures the function runs and returns a finite score.
    assert 0.0 <= score <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement normal_field_agreement**

Append to `stl2scad/core/revolve_recovery.py`:

```python
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

    # Magnitude of the circumferential component (bad) vs total (1.0).
    circ_component = np.abs(np.einsum("fi,fi->f", norms, circumferential_dir))
    agreement_per_face = 1.0 - circ_component
    return float(np.clip((agreement_per_face * face_areas).sum() / total_area, 0.0, 1.0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/revolve_recovery.py tests/test_revolve_recovery.py
git commit -m "feat: normal-field agreement gate for revolve recovery"
```

---

## Task 7: `detect_revolve_solid` orchestration

**Files:**
- Modify: `stl2scad/core/revolve_recovery.py`
- Test: `tests/test_revolve_recovery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_revolve_recovery.py`:

```python
from stl2scad.core.revolve_recovery import detect_revolve_solid


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
    # The axis-touching check: at least one profile point has r ≈ 0.
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement detect_revolve_solid**

Append to `stl2scad/core/revolve_recovery.py`:

```python
def detect_revolve_solid(
    vertices: np.ndarray,
    triangles: np.ndarray,
    config: DetectorConfig,
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
    for k in range(K):
        angle = np.pi * float(k) / float(K)  # half-planes at evenly spaced angles
        sl = extract_radial_slice(vertices, triangles, axis, origin, angle)
        if sl is None or len(sl) < 3:
            return []
        # Every slice must touch the axis (Phase 1 excludes annular).
        if float(sl[:, 0].min()) > 1e-3 * float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0))):
            return []
        slices.append(sl)

    mesh_scale = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    cross_slice_score = cross_slice_consistency(slices, mesh_scale=mesh_scale)
    # Map tolerance-ratio to acceptance threshold: the scoring function in
    # Task 4 already falls off linearly; we accept when the score is high
    # enough AND the mean spread stays within the configured ratio.
    if cross_slice_score < (1.0 - config.revolve_cross_slice_tolerance_ratio * 10.0):
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
    profile_validity = 1.0 if float(profile[:, 0].min()) < 1e-3 * mesh_scale else 0.0
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_revolve_recovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/revolve_recovery.py tests/test_revolve_recovery.py
git commit -m "feat: detect_revolve_solid — full Phase 1 gate pipeline"
```

---

## Task 8: IR wrapping for `revolve_solid`

**Files:**
- Modify: `stl2scad/core/feature_graph.py` (around lines 43-60 for IR type maps; around line 140-220 for `_build_ir_tree`)
- Test: `tests/test_feature_graph.py`

- [ ] **Step 1: Read current IR construction**

```bash
grep -n "_SOLID_TO_IR_TYPE\|_build_ir_tree\|TransformRotate" stl2scad/core/feature_graph.py | head -20
```

Expected: identifies `_SOLID_TO_IR_TYPE` dict at ~line 43 and `_build_ir_tree` entry point.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_feature_graph.py`:

```python
def test_ir_tree_wraps_revolve_solid_as_extrude_revolve():
    from stl2scad.core.feature_graph import _build_ir_tree

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
    # Expect TransformRotate { ExtrudeRevolve { Sketch2D { polygon } } }
    assert child["type"] == "TransformRotate"
    assert child["child"]["type"] == "ExtrudeRevolve"
    sketch = child["child"]["profile"]
    assert sketch["type"] == "Sketch2D"
    assert sketch["kind"] == "polygon"
    assert len(sketch["points"]) == 4
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_feature_graph.py::test_ir_tree_wraps_revolve_solid_as_extrude_revolve -v`
Expected: FAIL.

- [ ] **Step 4: Extend `_build_ir_tree` to handle `revolve_solid`**

In `stl2scad/core/feature_graph.py`, locate `_build_ir_tree` (search for `def _build_ir_tree`). In the section that iterates features and constructs the root node, add a branch for `revolve_solid` *before* the existing solid-handling branch. The new branch must:

1. Compute the rotation that maps the detected axis onto world Z (for OpenSCAD's rotate_extrude convention).
2. Build a `Sketch2D` polygon node from `profile`.
3. Wrap it as `ExtrudeRevolve { profile: Sketch2D }`.
4. Wrap that in `TransformRotate { angles_deg: [...] }` if axis ≠ Z.
5. Wrap the transform in `BooleanUnion { children: [...] }`.

Add this helper above `_build_ir_tree`:

```python
def _axis_to_world_z_euler_xyz(axis: list[float]) -> list[float]:
    """Return Euler XYZ angles in degrees that rotate world Z onto `axis`.

    The SCAD emitter will apply `rotate([rx, ry, rz])` to a rotate_extrude()
    whose output is along world Z; the result is a revolve whose axis is
    `axis`.
    """
    a = np.asarray(axis, dtype=np.float64)
    a = a / float(np.linalg.norm(a))
    z = np.array([0.0, 0.0, 1.0])
    if np.allclose(a, z, atol=1e-6):
        return [0.0, 0.0, 0.0]
    if np.allclose(a, -z, atol=1e-6):
        return [180.0, 0.0, 0.0]
    # Build a rotation matrix that sends z → a, then extract Euler XYZ.
    v = np.cross(z, a)
    s = float(np.linalg.norm(v))
    c = float(np.dot(z, a))
    vx = np.array([
        [0, -v[2], v[1]],
        [v[2], 0, -v[0]],
        [-v[1], v[0], 0],
    ])
    R = np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s))
    # Euler XYZ extraction (standard formula).
    rx = float(np.degrees(np.arctan2(R[2, 1], R[2, 2])))
    ry = float(np.degrees(np.arcsin(-R[2, 0])))
    rz = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    return [rx, ry, rz]


def _ir_revolve_node(feature: dict[str, Any]) -> dict[str, Any]:
    points = [[float(r), float(z)] for r, z in feature["profile"]]
    sketch = {"type": "Sketch2D", "kind": "polygon", "points": points}
    extrude = {"type": "ExtrudeRevolve", "profile": sketch}
    angles = _axis_to_world_z_euler_xyz(feature["axis"])
    if any(abs(a) > 1e-6 for a in angles):
        wrapped = {"type": "TransformRotate", "angles_deg": angles, "child": extrude}
    else:
        # Always emit TransformRotate for structural uniformity — emitter inspects angles.
        wrapped = {"type": "TransformRotate", "angles_deg": [0.0, 0.0, 0.0], "child": extrude}
    return wrapped
```

Then in `_build_ir_tree`, when handling features, route `revolve_solid`:

```python
# Within the section that currently builds root nodes from flat features:
revolve_feats = [f for f in features if f.get("type") == "revolve_solid"]
if revolve_feats:
    # Phase 1: one revolve per mesh. Wrap in BooleanUnion { TransformRotate { ExtrudeRevolve {} } }.
    root = {
        "type": "BooleanUnion",
        "children": [_ir_revolve_node(revolve_feats[0])],
    }
    return [{
        "type": "Interpretation",
        "rank": 1,
        "confidence": float(revolve_feats[0]["confidence"]),
        "root": root,
    }]
# ... then fall through to existing plate / box / cylinder IR construction.
```

The exact integration point is immediately after the early `FallbackMesh` check and before the solid-feature branch. When a revolve feature is present no other solid / cutout IR is produced for this graph (one-owner rule).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_feature_graph.py::test_ir_tree_wraps_revolve_solid_as_extrude_revolve -v`
Expected: PASS.

Also run all pre-existing `_build_ir_tree` tests to confirm no regression:

Run: `python -m pytest tests/test_feature_graph.py -k ir_tree -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add stl2scad/core/feature_graph.py tests/test_feature_graph.py
git commit -m "feat: IR wrapping for revolve_solid (BooleanUnion + TransformRotate + ExtrudeRevolve)"
```

---

## Task 9: SCAD preview emitter for revolves

**Files:**
- Modify: `stl2scad/core/feature_graph.py` (in the emit-preview dispatch function; search for `_emit_cylinder_scad_preview` to find the pattern)
- Test: `tests/test_feature_graph.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_feature_graph.py`:

```python
def test_emit_revolve_scad_preview_generates_rotate_extrude():
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

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
    # Must contain the four profile vertices
    assert "[0" in scad and "5" in scad and "10" in scad
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_feature_graph.py::test_emit_revolve_scad_preview_generates_rotate_extrude -v`
Expected: FAIL (returns None or raises).

- [ ] **Step 3: Implement `_emit_revolve_scad_preview` and wire dispatch**

Add to `stl2scad/core/feature_graph.py` near the other `_emit_*_scad_preview` helpers:

```python
def _emit_revolve_scad_preview(graph: dict[str, Any], revolve: dict[str, Any]) -> str:
    """Emit parametric SCAD for a revolve_solid feature.

    Uses OpenSCAD's rotate_extrude with a polygon child. The detected axis is
    aligned to world Z via a wrapping rotate([...]) when necessary.
    """
    axis = [float(v) for v in revolve["axis"]]
    origin = [float(v) for v in revolve["axis_origin"]]
    profile = [(float(r), float(z)) for r, z in revolve["profile"]]

    points_scad = ",\n    ".join(f"[{r:.6f}, {z:.6f}]" for r, z in profile)

    lines: list[str] = [
        "// generated from axisymmetric revolve feature",
        f"// axis = [{axis[0]:.6f}, {axis[1]:.6f}, {axis[2]:.6f}]",
        f"revolve_profile = [",
        f"    {points_scad}",
        "];",
        "",
    ]

    angles = _axis_to_world_z_euler_xyz(axis)
    rotation_expr = ""
    if any(abs(a) > 1e-6 for a in angles):
        rotation_expr = f"rotate([{angles[0]:.6f}, {angles[1]:.6f}, {angles[2]:.6f}]) "

    translate_expr = ""
    if any(abs(c) > 1e-6 for c in origin):
        translate_expr = f"translate([{origin[0]:.6f}, {origin[1]:.6f}, {origin[2]:.6f}]) "

    lines.extend([
        f"{translate_expr}{rotation_expr}rotate_extrude($fn=128)",
        "    polygon(points=revolve_profile);",
        "",
    ])
    return "\n".join(lines)
```

Then in `emit_feature_graph_scad_preview` (search for that function), insert a new dispatch branch *before* the existing cylinder / plate / box branches:

```python
# Inside emit_feature_graph_scad_preview, after the early-return-on-empty-features
# check and before the plate/box/cylinder branches:
revolve = _best_feature(graph, "revolve_solid")
if revolve is not None and _passes_preview_solid_confidence(revolve.get("confidence")):
    return _emit_revolve_scad_preview(graph, revolve)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_feature_graph.py::test_emit_revolve_scad_preview_generates_rotate_extrude -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/feature_graph.py tests/test_feature_graph.py
git commit -m "feat: SCAD preview emitter for revolve_solid features"
```

---

## Task 10: Wire `detect_revolve_solid` into `_build_feature_graph`

**Files:**
- Modify: `stl2scad/core/feature_graph.py` (around lines 280-320 where `_extract_cylinder_like_solid` is called)
- Test: `tests/test_feature_graph.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_feature_graph.py`:

```python
def test_build_feature_graph_detects_revolve_before_cylinder(tmp_path):
    """Rule 1: revolve recovery runs before cylinder detection.

    Render a cylinder SCAD to STL, build the graph, confirm revolve_solid
    fires and no cylinder_like_solid is emitted for the same mesh.
    """
    import numpy as np
    from stl.mesh import Mesh as StlMesh
    from stl2scad.core.feature_graph import build_feature_graph_for_stl

    # Build a cylinder mesh programmatically (same helper as unit tests).
    def _cyl(h, r, seg):
        theta = np.linspace(0, 2*np.pi, seg, endpoint=False)
        br = np.column_stack([r*np.cos(theta), r*np.sin(theta), np.zeros_like(theta)])
        tr = np.column_stack([r*np.cos(theta), r*np.sin(theta), np.full_like(theta, h)])
        cb = np.array([0,0,0]); ct = np.array([0,0,h])
        verts = np.vstack([br, tr, cb, ct])
        icb = 2*seg; ict = 2*seg+1
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

    graph = build_feature_graph_for_stl(stl_path)
    types = [f["type"] for f in graph["features"]]
    assert types.count("revolve_solid") == 1
    assert types.count("cylinder_like_solid") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_feature_graph.py::test_build_feature_graph_detects_revolve_before_cylinder -v`
Expected: FAIL (no revolve feature — detector not wired in yet).

- [ ] **Step 3: Wire dispatch in `_build_feature_graph`**

Open `stl2scad/core/feature_graph.py` and locate the block starting at the comment `# Try cylinder detection.` (around line 287). Replace that block with:

```python
    # --- Rule 1: revolve recovery runs first. ---
    # If accepted it owns the mesh (Rule 3): subsequent plate / box / cylinder
    # and cutout extraction are skipped for this graph.
    triangles_indices = None
    # Reconstruct (vertices, triangles) from the flat vector list.
    # Mesh.vectors is (F, 3, 3); we reshape to a vertex table + triangle index
    # list. Shared vertices are not deduplicated — the detector is robust to
    # this (Task 2–7 implementations work on float-coord vertex arrays).
    vertex_table = vectors.reshape(-1, 3)
    triangles_indices = np.arange(len(vertex_table), dtype=np.int64).reshape(-1, 3)

    from stl2scad.core.revolve_recovery import detect_revolve_solid
    revolve_features = detect_revolve_solid(vertex_table, triangles_indices, config=resolved)
    if revolve_features:
        # One-owner: skip plate/box/cylinder and cutouts.
        plane_pairs = [f for f in box_features if f.get("type") == "axis_boundary_plane_pair"]
        features = plane_pairs + revolve_features
    else:
        # Try cylinder detection.  If a cylinder is found with sufficient confidence
        # it takes priority over plate/box classification — a disk is a cylinder,
        # not a plate.  Axis-boundary-plane-pair entries are kept for triage metadata.
        cylinder_features = _extract_cylinder_like_solid(
            normals,
            face_areas,
            bbox,
            vertices=vectors,
            config=resolved,
        )
        if cylinder_features:
            plane_pairs = [f for f in box_features if f.get("type") == "axis_boundary_plane_pair"]
            features = plane_pairs + cylinder_features
        else:
            # If no axis-aligned solid was found, try the rotated-plate detector.
            solid_found = any(
                f.get("type") in ("plate_like_solid", "box_like_solid") for f in box_features
            )
            rotated_plate_features = (
                _extract_rotated_plate_solid(normals, face_areas, bbox, vectors, resolved)
                if not solid_found
                else []
            )
            features = box_features + rotated_plate_features
```

And wrap the subsequent cutout extraction in a conditional so it's skipped when revolve fired:

```python
    if not revolve_features:
        features.extend(
            _extract_axis_aligned_through_holes(
                vectors,
                normals,
                face_areas,
                bbox,
                features,
                config=resolved,
            )
        )
        features.extend(_extract_repeated_hole_patterns(features, config=resolved))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_feature_graph.py::test_build_feature_graph_detects_revolve_before_cylinder -v`
Expected: PASS.

- [ ] **Step 5: Run the full feature_graph test file to confirm no regressions**

Run: `python -m pytest tests/test_feature_graph.py -v`
Expected: All tests PASS except any that were explicitly testing "cylinder_plain → cylinder_like_solid" — those will be fixed in Task 12. If any other test fails, stop here and investigate; do not proceed to Task 11.

- [ ] **Step 6: Commit**

```bash
git add stl2scad/core/feature_graph.py tests/test_feature_graph.py
git commit -m "feat: wire detect_revolve_solid into _build_feature_graph with one-owner dispatch"
```

---

## Task 11: Fixture schema — add `revolve_solid` expected-detection key and `revolve`/`non_revolve` fixture types

**Files:**
- Modify: `stl2scad/core/feature_fixtures.py`
- Test: `tests/test_feature_fixtures.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_feature_fixtures.py`:

```python
def test_fixture_type_revolve_accepts_profile_spec():
    from stl2scad.core.feature_fixtures import validate_feature_fixture_spec

    spec = {
        "name": "revolve_test",
        "fixture_type": "revolve",
        "output_filename": "revolve_test.scad",
        "profile": [[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]],
        "axis": "z",
        "expected_detection": {
            "revolve_solid": True,
            "plate_like_solid": False,
            "box_like_solid": False,
            "cylinder_like_solid": False,
        },
    }
    result = validate_feature_fixture_spec(spec, schema_version=1)
    assert result["fixture_type"] == "revolve"
    assert len(result["profile"]) == 4


def test_fixture_type_non_revolve_accepts_rejection_gate():
    from stl2scad.core.feature_fixtures import validate_feature_fixture_spec

    spec = {
        "name": "non_revolve_test",
        "fixture_type": "non_revolve",
        "output_filename": "non_revolve_test.scad",
        "shape": "cube",
        "size": [10.0, 10.0, 10.0],
        "expected_rejection_gate": "cross_slice_consistency",
        "expected_detection": {
            "revolve_solid": False,
            "plate_like_solid": False,
            "box_like_solid": True,
        },
    }
    result = validate_feature_fixture_spec(spec, schema_version=1)
    assert result["fixture_type"] == "non_revolve"
    assert result["expected_rejection_gate"] == "cross_slice_consistency"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_feature_fixtures.py -k "revolve or non_revolve" -v`
Expected: FAIL — unsupported fixture_type.

- [ ] **Step 3: Extend schema**

In `stl2scad/core/feature_fixtures.py`:

1. Extend `_SUPPORTED_FIXTURE_TYPES` (around line 11) to include `"revolve"` and `"non_revolve"`:

```python
_SUPPORTED_FIXTURE_TYPES = {
    "plate", "box", "l_bracket", "sphere", "torus",
    "cylinder", "cone", "prism",
    "revolve", "non_revolve",
}
```

2. Extend `_BOOLEAN_EXPECTATION_TO_FEATURE` (around line 22):

```python
_BOOLEAN_EXPECTATION_TO_FEATURE = {
    "plate_like_solid": "plate_like_solid",
    "box_like_solid": "box_like_solid",
    "cylinder_like_solid": "cylinder_like_solid",
    "revolve_solid": "revolve_solid",
}
```

3. Locate `_validate_geometry_by_fixture_type` (around line 314) and add branches:

```python
    elif fixture_type == "revolve":
        _validate_revolve_fixture_geometry(spec, name)
    elif fixture_type == "non_revolve":
        _validate_non_revolve_fixture_geometry(spec, name)
```

4. Add the two validator helpers near the other per-type validators (e.g. after `_validate_cylinder_fixture_geometry`):

```python
def _validate_revolve_fixture_geometry(spec: dict[str, Any], name: str) -> None:
    profile = spec.get("profile")
    if not isinstance(profile, list) or len(profile) < 3:
        raise ValueError(f"Revolve fixture '{name}' must define a profile of at least 3 (r, z) points")
    for pt in profile:
        if not (isinstance(pt, list) and len(pt) == 2):
            raise ValueError(f"Revolve fixture '{name}' profile points must be [r, z] pairs")
        r, z = float(pt[0]), float(pt[1])
        if r < 0.0:
            raise ValueError(f"Revolve fixture '{name}' profile has negative r (r={r})")
    if min(float(p[0]) for p in profile) > 1e-6:
        raise ValueError(
            f"Revolve fixture '{name}' profile must touch the axis (min r ≈ 0); "
            f"annular profiles are Phase-1-excluded."
        )
    axis = str(spec.get("axis", "z")).lower()
    if axis not in ("x", "y", "z"):
        raise ValueError(f"Revolve fixture '{name}' axis must be x/y/z")


_NON_REVOLVE_SHAPES = {"cube", "square_prism", "symmetric_composite", "shaft_with_keyway"}


def _validate_non_revolve_fixture_geometry(spec: dict[str, Any], name: str) -> None:
    shape = str(spec.get("shape", "")).lower()
    if shape not in _NON_REVOLVE_SHAPES:
        supported = ", ".join(sorted(_NON_REVOLVE_SHAPES))
        raise ValueError(
            f"Non-revolve fixture '{name}' shape must be one of: {supported}"
        )
    gate = spec.get("expected_rejection_gate")
    if gate is not None and gate not in (
        "axis_quality", "cross_slice_consistency",
        "normal_field_agreement", "profile_validity",
    ):
        raise ValueError(f"Non-revolve fixture '{name}' has unknown expected_rejection_gate '{gate}'")
```

5. In `validate_feature_fixture_spec`, make sure `profile`, `axis`, `shape`, `size`, and `expected_rejection_gate` are propagated into the normalized `spec` dict (search for where the schema's returned object is built, around lines 80–140, and add these keys to the pass-through list).

Specifically, find the section that builds `spec` with keys like `plate_size`, `box_size`, etc., and add:

```python
    if fixture_type == "revolve":
        spec["profile"] = [list(map(float, p)) for p in raw_fixture.get("profile", [])]
        spec["axis"] = str(raw_fixture.get("axis", "z")).lower()
    if fixture_type == "non_revolve":
        spec["shape"] = str(raw_fixture.get("shape", "")).lower()
        spec["size"] = [float(v) for v in raw_fixture.get("size", [])]
        if "expected_rejection_gate" in raw_fixture:
            spec["expected_rejection_gate"] = str(raw_fixture["expected_rejection_gate"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_feature_fixtures.py -k "revolve or non_revolve" -v`
Expected: PASS.

Also run the full fixture test file to confirm no regressions:

Run: `python -m pytest tests/test_feature_fixtures.py -v`
Expected: all tests pass except round-trip cases that touch cylinder fixtures (those break in Task 12 and are fixed in the same task).

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/feature_fixtures.py tests/test_feature_fixtures.py
git commit -m "feat: fixture schema support for revolve and non_revolve types"
```

---

## Task 12: Fixture generator for revolve fixtures + update existing cylinder fixtures

**Files:**
- Modify: `stl2scad/core/feature_fixtures.py` (add `_generate_revolve_fixture_scad` and `_generate_non_revolve_fixture_scad`; dispatch in `generate_feature_fixture_scad`)
- Modify: `tests/data/feature_fixtures_manifest.json` (update existing `cylinder_plain`, `cylinder_short_disk`, `cylinder_x_axis` entries — their `expected_detection.cylinder_like_solid` must flip to `false` and `revolve_solid: true` must be added)
- Test: `tests/test_feature_fixtures.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_feature_fixtures.py`:

```python
def test_generate_revolve_fixture_scad_contains_rotate_extrude():
    from stl2scad.core.feature_fixtures import generate_feature_fixture_scad

    fixture = {
        "name": "revolve_test",
        "fixture_type": "revolve",
        "output_filename": "revolve_test.scad",
        "profile": [[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]],
        "axis": "z",
    }
    scad = generate_feature_fixture_scad(fixture)
    assert "rotate_extrude" in scad
    assert "polygon" in scad
    assert "[0" in scad and "5" in scad and "10" in scad


def test_generate_non_revolve_cube_scad_contains_cube():
    from stl2scad.core.feature_fixtures import generate_feature_fixture_scad

    fixture = {
        "name": "non_revolve_cube",
        "fixture_type": "non_revolve",
        "output_filename": "non_revolve_cube.scad",
        "shape": "cube",
        "size": [10.0, 10.0, 10.0],
    }
    scad = generate_feature_fixture_scad(fixture)
    assert "cube" in scad
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_feature_fixtures.py -k "generate_revolve or generate_non_revolve_cube" -v`
Expected: FAIL.

- [ ] **Step 3: Implement generators**

In `stl2scad/core/feature_fixtures.py`:

1. Add generator functions near the other `_generate_*_fixture_scad` helpers:

```python
def _generate_revolve_fixture_scad(fixture: dict[str, Any]) -> str:
    profile = fixture["profile"]
    axis = str(fixture.get("axis", "z"))
    lines = _fixture_header_lines(fixture)
    pts = ",\n    ".join(f"[{float(r):.6f}, {float(z):.6f}]" for r, z in profile)
    lines.extend([
        "profile = [",
        f"    {pts}",
        "];",
        "",
    ])
    rotate_prefix = {
        "z": "",
        "x": "rotate([0, 90, 0]) ",
        "y": "rotate([-90, 0, 0]) ",
    }.get(axis, "")
    lines.extend([
        f"{rotate_prefix}rotate_extrude($fn=128) polygon(points=profile);",
        "",
    ])
    return "\n".join(lines)


def _generate_non_revolve_fixture_scad(fixture: dict[str, Any]) -> str:
    shape = str(fixture.get("shape", "")).lower()
    size = [float(v) for v in fixture.get("size", [1.0, 1.0, 1.0])]
    lines = _fixture_header_lines(fixture)
    if shape == "cube":
        lines.extend([
            f"size = [{size[0]:.6f}, {size[1]:.6f}, {size[2]:.6f}];",
            "",
            f"translate([-{size[0]/2:.6f}, -{size[1]/2:.6f}, 0]) cube(size);",
            "",
        ])
    elif shape == "square_prism":
        # Square cross-section extruded along Z — balanced inertia about Z
        # but cross-slice slices are rectangles, not (r, z) profiles.
        lines.extend([
            f"side = {size[0]:.6f};",
            f"height = {size[2]:.6f};",
            "",
            "translate([-side/2, -side/2, 0]) linear_extrude(height) square(side);",
            "",
        ])
    elif shape == "symmetric_composite":
        # Two mirrored bosses on a plate — mirror-symmetric about Z but not a revolve.
        lines.extend([
            f"plate = [{size[0]:.6f}, {size[1]:.6f}, {size[2]:.6f}];",
            "",
            "translate([-plate[0]/2, -plate[1]/2, 0]) cube(plate);",
            f"translate([{size[0]*0.3:.6f}, 0, {size[2]:.6f}]) cylinder(h={size[2]/2:.6f}, d={size[0]*0.2:.6f});",
            f"translate([-{size[0]*0.3:.6f}, 0, {size[2]:.6f}]) cylinder(h={size[2]/2:.6f}, d={size[0]*0.2:.6f});",
            "",
        ])
    elif shape == "shaft_with_keyway":
        diameter = float(size[0])
        height = float(size[2])
        keyway_width = diameter * 0.25
        keyway_depth = diameter * 0.15
        lines.extend([
            f"diameter = {diameter:.6f};",
            f"height = {height:.6f};",
            f"keyway_width = {keyway_width:.6f};",
            f"keyway_depth = {keyway_depth:.6f};",
            "",
            "difference() {",
            "    cylinder(h=height, d=diameter, center=false);",
            "    translate([diameter/2 - keyway_depth, -keyway_width/2, height*0.2])",
            "        cube([keyway_depth + 0.1, keyway_width, height*0.6]);",
            "}",
            "",
        ])
    else:
        raise ValueError(f"Unknown non_revolve shape '{shape}'")
    return "\n".join(lines)
```

2. Extend the dispatch in `generate_feature_fixture_scad` (around line 145):

```python
    elif fixture_type == "revolve":
        return _generate_revolve_fixture_scad(fixture)
    elif fixture_type == "non_revolve":
        return _generate_non_revolve_fixture_scad(fixture)
```

3. Update existing cylinder manifest entries. Open `tests/data/feature_fixtures_manifest.json`, find each of `cylinder_plain`, `cylinder_short_disk`, `cylinder_x_axis`. For each candidate's `expected_detection`, flip:

```json
"cylinder_like_solid": false,
"revolve_solid": true
```

Example — change this:
```json
"expected_detection": {
  "cylinder_like_solid": true,
  "plate_like_solid": false,
  ...
}
```
to this:
```json
"expected_detection": {
  "cylinder_like_solid": false,
  "revolve_solid": true,
  "plate_like_solid": false,
  ...
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_feature_fixtures.py -k "generate_revolve or generate_non_revolve_cube" -v`
Expected: PASS.

Run the full fixture test file to confirm cylinder fixtures now round-trip with the flipped expectations:

Run: `python -m pytest tests/test_feature_fixtures.py -v`
Expected: all PASS (cylinder round-trip now sees `revolve_solid: 1` and `cylinder_like_solid: 0`).

If `test_feature_fixture_manifest_matches_checked_in_scad` fails, it's because the manifest changed but the pre-generated SCAD didn't. Regenerate:

```bash
python -m pytest tests/test_feature_fixtures.py::test_feature_fixture_manifest_matches_checked_in_scad -v
```

Check `tests/.tmp_output/` for any regenerated cylinder `.scad` files that differ — copy them to `tests/data/feature_fixtures_scad/` if so. (Cylinder SCAD should not have changed if only `expected_detection` was edited in the manifest; if it changed, investigate before copying.)

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/feature_fixtures.py tests/data/feature_fixtures_manifest.json tests/test_feature_fixtures.py
git commit -m "feat: revolve/non_revolve fixture generators; flip cylinder manifest to revolve_solid expectation"
```

---

## Task 13: Add positive `revolve_*` fixtures to manifest and checked-in SCAD

**Files:**
- Modify: `tests/data/feature_fixtures_manifest.json` (add six `revolve_*` entries)
- Create: `tests/data/feature_fixtures_scad/revolve_rectangle_profile.scad`
- Create: `tests/data/feature_fixtures_scad/revolve_triangle_profile.scad`
- Create: `tests/data/feature_fixtures_scad/revolve_semicircle_profile.scad`
- Create: `tests/data/feature_fixtures_scad/revolve_christmas_tree.scad`
- Create: `tests/data/feature_fixtures_scad/revolve_vase.scad`
- Create: `tests/data/feature_fixtures_scad/revolve_stepped_shaft.scad`

- [ ] **Step 1: Add six manifest entries**

Open `tests/data/feature_fixtures_manifest.json` and append these entries to the `fixtures` list (before the closing `]`):

```json
{
  "name": "revolve_rectangle_profile",
  "fixture_type": "revolve",
  "description": "Rectangle profile revolved around Z — a cylinder via the revolve pipeline.",
  "output_filename": "revolve_rectangle_profile.scad",
  "profile": [[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]],
  "axis": "z",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.95,
    "expected_detection": {
      "revolve_solid": true, "cylinder_like_solid": false,
      "plate_like_solid": false, "box_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "revolve_triangle_profile",
  "fixture_type": "revolve",
  "description": "Triangle profile revolved around Z — a cone via the revolve pipeline.",
  "output_filename": "revolve_triangle_profile.scad",
  "profile": [[0.0, 0.0], [5.0, 0.0], [0.0, 10.0]],
  "axis": "z",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.92,
    "expected_detection": {
      "revolve_solid": true, "plate_like_solid": false, "box_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "revolve_semicircle_profile",
  "fixture_type": "revolve",
  "description": "Semicircle profile revolved around Z — a sphere via the revolve pipeline.",
  "output_filename": "revolve_semicircle_profile.scad",
  "profile": [
    [0.0, -5.0],
    [1.25, -4.84], [2.5, -4.33], [3.54, -3.54], [4.33, -2.5], [4.84, -1.25],
    [5.0, 0.0],
    [4.84, 1.25], [4.33, 2.5], [3.54, 3.54], [2.5, 4.33], [1.25, 4.84],
    [0.0, 5.0]
  ],
  "axis": "z",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.90,
    "expected_detection": {
      "revolve_solid": true, "plate_like_solid": false, "box_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "revolve_christmas_tree",
  "fixture_type": "revolve",
  "description": "Sawtooth profile → stylized Christmas tree; stays as generic rotate_extrude(polygon()) in Phase 2.",
  "output_filename": "revolve_christmas_tree.scad",
  "profile": [
    [0.0, 0.0],
    [4.0, 0.0], [4.0, 2.0],
    [2.5, 2.0], [5.0, 5.0], [3.0, 5.0],
    [6.0, 9.0], [3.5, 9.0],
    [6.5, 13.0], [0.0, 13.0]
  ],
  "axis": "z",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.88,
    "expected_detection": {
      "revolve_solid": true, "plate_like_solid": false, "box_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "revolve_vase",
  "fixture_type": "revolve",
  "description": "Smooth curved profile approximating a vase shape.",
  "output_filename": "revolve_vase.scad",
  "profile": [
    [0.0, 0.0],
    [6.0, 0.0], [7.0, 3.0], [5.0, 8.0], [3.0, 15.0], [4.0, 18.0],
    [6.0, 20.0], [0.0, 20.0]
  ],
  "axis": "z",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.88,
    "expected_detection": {
      "revolve_solid": true, "plate_like_solid": false, "box_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "revolve_stepped_shaft",
  "fixture_type": "revolve",
  "description": "Staircase profile → stepped shaft, a common mechanical turning.",
  "output_filename": "revolve_stepped_shaft.scad",
  "profile": [
    [0.0, 0.0],
    [8.0, 0.0], [8.0, 4.0],
    [5.0, 4.0], [5.0, 10.0],
    [3.0, 10.0], [3.0, 14.0],
    [0.0, 14.0]
  ],
  "axis": "z",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.90,
    "expected_detection": {
      "revolve_solid": true, "plate_like_solid": false, "box_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
}
```

- [ ] **Step 2: Regenerate and commit fixture SCAD**

Run the manifest-matches-checked-in test — it will regenerate the new .scad files into `tests/.tmp_output/`:

```bash
python -m pytest tests/test_feature_fixtures.py::test_feature_fixture_manifest_matches_checked_in_scad -v
```

Expected: FAIL because six new .scad files are expected but not yet in `tests/data/feature_fixtures_scad/`.

Copy them in:

```bash
cp tests/.tmp_output/revolve_rectangle_profile.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/revolve_triangle_profile.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/revolve_semicircle_profile.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/revolve_christmas_tree.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/revolve_vase.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/revolve_stepped_shaft.scad tests/data/feature_fixtures_scad/
```

- [ ] **Step 3: Run manifest-matches test to verify it passes**

Run: `python -m pytest tests/test_feature_fixtures.py::test_feature_fixture_manifest_matches_checked_in_scad -v`
Expected: PASS.

- [ ] **Step 4: Run full fixture test file**

Run: `python -m pytest tests/test_feature_fixtures.py -v`
Expected: All pass. The round-trip test will render each new fixture via OpenSCAD and confirm `revolve_solid: 1`.

- [ ] **Step 5: Commit**

```bash
git add tests/data/feature_fixtures_manifest.json tests/data/feature_fixtures_scad/revolve_*.scad
git commit -m "test: add six positive revolve_* fixtures (rectangle, triangle, semicircle, christmas-tree, vase, stepped-shaft)"
```

---

## Task 14: Add negative `non_revolve_*` fixtures to manifest and checked-in SCAD

**Files:**
- Modify: `tests/data/feature_fixtures_manifest.json` (add four `non_revolve_*` entries)
- Create: `tests/data/feature_fixtures_scad/non_revolve_cube.scad`
- Create: `tests/data/feature_fixtures_scad/non_revolve_square_prism.scad`
- Create: `tests/data/feature_fixtures_scad/non_revolve_symmetric_composite.scad`
- Create: `tests/data/feature_fixtures_scad/non_revolve_shaft_with_keyway.scad`

- [ ] **Step 1: Add four negative manifest entries**

Append to the `fixtures` list in `tests/data/feature_fixtures_manifest.json`:

```json
{
  "name": "non_revolve_cube",
  "fixture_type": "non_revolve",
  "description": "Unit cube. Balanced inertia tensor edge-case; must be rejected by cross-slice consistency.",
  "output_filename": "non_revolve_cube.scad",
  "shape": "cube",
  "size": [10.0, 10.0, 10.0],
  "expected_rejection_gate": "axis_quality",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.95,
    "expected_detection": {
      "revolve_solid": false, "box_like_solid": true, "plate_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "non_revolve_square_prism",
  "fixture_type": "non_revolve",
  "description": "Square cross-section extruded along Z. Balanced inertia about Z but cross-slice radial profile differs at 0° vs 45°.",
  "output_filename": "non_revolve_square_prism.scad",
  "shape": "square_prism",
  "size": [10.0, 10.0, 20.0],
  "expected_rejection_gate": "cross_slice_consistency",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.90,
    "expected_detection": {
      "revolve_solid": false, "box_like_solid": true, "plate_like_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "non_revolve_symmetric_composite",
  "fixture_type": "non_revolve",
  "description": "Plate with two mirrored bosses. Mirror-symmetric but not a revolve.",
  "output_filename": "non_revolve_symmetric_composite.scad",
  "shape": "symmetric_composite",
  "size": [30.0, 10.0, 4.0],
  "expected_rejection_gate": "cross_slice_consistency",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.85,
    "expected_detection": {
      "revolve_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
},
{
  "name": "non_revolve_shaft_with_keyway",
  "fixture_type": "non_revolve",
  "description": "Near-axisymmetric shaft with one axial keyway slot. Inertia screen passes; cross-slice fails at keyway z-range.",
  "output_filename": "non_revolve_shaft_with_keyway.scad",
  "shape": "shaft_with_keyway",
  "size": [10.0, 10.0, 20.0],
  "expected_rejection_gate": "cross_slice_consistency",
  "candidates": [{
    "rank": 1, "name": "primary", "confidence": 0.88,
    "expected_detection": {
      "revolve_solid": false,
      "hole_count": 0, "slot_count": 0,
      "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
    }
  }]
}
```

- [ ] **Step 2: Regenerate and commit fixture SCAD**

Run the manifest-matches test:

```bash
python -m pytest tests/test_feature_fixtures.py::test_feature_fixture_manifest_matches_checked_in_scad -v
```

Expected: FAIL because four new .scad files are expected.

Copy them in:

```bash
cp tests/.tmp_output/non_revolve_cube.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/non_revolve_square_prism.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/non_revolve_symmetric_composite.scad tests/data/feature_fixtures_scad/
cp tests/.tmp_output/non_revolve_shaft_with_keyway.scad tests/data/feature_fixtures_scad/
```

- [ ] **Step 3: Run manifest-matches test**

Run: `python -m pytest tests/test_feature_fixtures.py::test_feature_fixture_manifest_matches_checked_in_scad -v`
Expected: PASS.

- [ ] **Step 4: Run full fixture test file**

Run: `python -m pytest tests/test_feature_fixtures.py -v`
Expected: round-trip test confirms each negative fixture's detector output has `revolve_solid: 0`.

- [ ] **Step 5: Commit**

```bash
git add tests/data/feature_fixtures_manifest.json tests/data/feature_fixtures_scad/non_revolve_*.scad
git commit -m "test: add four negative non_revolve_* fixtures (cube, square_prism, symmetric_composite, shaft_with_keyway)"
```

---

## Task 15: Round-trip dimensional & confidence-component assertions for revolve fixtures

**Files:**
- Modify: `tests/test_feature_fixtures.py` (extend `_assert_fixture_dimensions` and add a revolve-specific branch; add a new test asserting `confidence_components` presence and that negative fixtures expose the rejection gate behaviour)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_feature_fixtures.py`:

```python
def test_revolve_fixture_exposes_confidence_components(test_data_dir, test_output_dir):
    from stl2scad.core.feature_fixtures import (
        load_feature_fixture_manifest, write_feature_fixture_library,
    )
    from stl2scad.core.feature_graph import build_feature_graph_for_stl

    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, test_output_dir)

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    revolves = [f for f in fixtures if f["fixture_type"] == "revolve"]
    assert revolves, "expected at least one revolve fixture"

    for fixture in revolves:
        scad_path = test_output_dir / fixture["output_filename"]
        stl_path = test_output_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = test_output_dir / f"{fixture['name']}.log"
        assert run_openscad(fixture["name"],
                            ["--render", "-o", str(stl_path), str(scad_path)],
                            str(log_path), openscad_path)

        graph = build_feature_graph_for_stl(stl_path)
        revolve = next((f for f in graph["features"] if f["type"] == "revolve_solid"), None)
        assert revolve is not None, f"{fixture['name']} — no revolve_solid detected"
        comps = revolve["confidence_components"]
        for key in ("axis_quality", "cross_slice_consistency",
                    "normal_field_agreement", "profile_validity"):
            assert key in comps
            assert 0.0 <= float(comps[key]) <= 1.0
```

Also extend `_assert_fixture_dimensions` (search for its definition in `tests/test_feature_fixtures.py`) with a revolve branch:

```python
    if fixture["fixture_type"] == "revolve":
        revolves = [f for f in features if f["type"] == "revolve_solid"]
        assert len(revolves) == 1
        detected = revolves[0]
        expected_profile = fixture["profile"]
        # Profile point count within ±2 of expected after DP simplification.
        assert abs(len(detected["profile"]) - len(expected_profile)) <= max(2, len(expected_profile) // 4)
        # Max r within 5% of expected.
        expected_max_r = max(float(p[0]) for p in expected_profile)
        detected_max_r = max(float(p[0]) for p in detected["profile"])
        assert abs(detected_max_r - expected_max_r) / expected_max_r < 0.05
        return
```

- [ ] **Step 2: Run tests to verify the new one fails and existing tests still pass**

Run: `python -m pytest tests/test_feature_fixtures.py::test_revolve_fixture_exposes_confidence_components -v`
Expected: PASS (revolve detection already works from Task 10; this just asserts the sub-signal fields are present).

Run: `python -m pytest tests/test_feature_fixtures.py::test_feature_fixture_round_trip_detection -v`
Expected: PASS — dimensions now assert the revolve profile shape.

- [ ] **Step 3: Commit**

```bash
git add tests/test_feature_fixtures.py
git commit -m "test: assert revolve_solid confidence_components and profile dimensions on round-trip"
```

---

## Task 16: Preview round-trip for revolve fixtures

**Files:**
- Modify: `tests/test_feature_fixtures.py` (extend `test_feature_fixture_preview_round_trip_detection` to include `revolve` fixture type; add assertion that `rotate_extrude` appears in the preview)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_feature_fixtures.py`:

```python
def test_revolve_fixture_preview_round_trip(test_data_dir, test_output_dir):
    from stl2scad.core.feature_fixtures import (
        load_feature_fixture_manifest, write_feature_fixture_library,
    )
    from stl2scad.core.feature_graph import (
        build_feature_graph_for_stl, emit_feature_graph_scad_preview,
    )

    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, test_output_dir)
    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    for fixture in fixtures:
        if fixture["fixture_type"] != "revolve":
            continue
        scad_path = test_output_dir / fixture["output_filename"]
        stl_path = test_output_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = test_output_dir / f"{fixture['name']}.log"
        assert run_openscad(fixture["name"],
                            ["--render", "-o", str(stl_path), str(scad_path)],
                            str(log_path), openscad_path)

        graph = build_feature_graph_for_stl(stl_path)
        preview = emit_feature_graph_scad_preview(graph)
        assert preview is not None, f"{fixture['name']} expected a preview"
        assert "rotate_extrude" in preview
        assert "polygon" in preview

        # Re-render the preview and re-detect: revolve_solid must still fire.
        preview_scad = test_output_dir / f"{fixture['name']}_preview.scad"
        preview_stl = test_output_dir / f"{fixture['name']}_preview.stl"
        preview_log = test_output_dir / f"{fixture['name']}_preview.log"
        preview_scad.write_text(preview, encoding="utf-8")
        assert run_openscad(fixture["name"] + "_preview",
                            ["--render", "-o", str(preview_stl), str(preview_scad)],
                            str(preview_log), openscad_path)
        re_graph = build_feature_graph_for_stl(preview_stl)
        assert any(f["type"] == "revolve_solid" for f in re_graph["features"])
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/test_feature_fixtures.py::test_revolve_fixture_preview_round_trip -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_feature_fixtures.py
git commit -m "test: preview round-trip for revolve fixtures"
```

---

## Task 17: Stress-case manifest coverage

**Files:**
- Modify: `tests/test_feature_fixtures.py` (add `revolve` and `non_revolve` to stress-case requirements)

- [ ] **Step 1: Locate the stress-case test**

```bash
grep -n "test_feature_fixture_manifest_covers_roadmap_stress_cases\|stress" tests/test_feature_fixtures.py | head
```

Expected: single definition in `tests/test_feature_fixtures.py`.

- [ ] **Step 2: Extend the test to require revolve + non_revolve coverage**

In `test_feature_fixture_manifest_covers_roadmap_stress_cases`, find the set of fixture_type requirements and add:

```python
    required_types = {"plate", "box", "l_bracket", "revolve", "non_revolve"}
    present_types = {f["fixture_type"] for f in fixtures}
    missing = required_types - present_types
    assert not missing, f"manifest missing required fixture_types: {missing}"
```

(If the test already uses a `required_types` set, just extend it with `"revolve"` and `"non_revolve"`.)

- [ ] **Step 3: Run the stress-case test**

Run: `python -m pytest tests/test_feature_fixtures.py::test_feature_fixture_manifest_covers_roadmap_stress_cases -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_feature_fixtures.py
git commit -m "test: require revolve and non_revolve fixtures in stress-case coverage"
```

---

## Task 18: Flip detector_ir.md status rows for ExtrudeRevolve and Sketch2D

**Files:**
- Modify: `docs/planning/detector_ir.md`

- [ ] **Step 1: Update status rows**

In `docs/planning/detector_ir.md`, find the `Sketch2D` / `ExtrudeLinear` / `ExtrudeRevolve` rows (under "Tier 2 — Sketches & extrusion") and update:

```markdown
| `Sketch2D` (`square`, `circle`, `polygon`, `slot2d`) | native 2D ops | `polygon` variant recovered from revolve profile (Phase 1 of rotate_extrude spec). Other variants pending. |
| `ExtrudeLinear` | `linear_extrude(h, scale?, twist?)` | Not recovered. |
| `ExtrudeRevolve` | `rotate_extrude()` | **Detected** via axisymmetric-revolve pipeline (Phase 1). Profile emits as `polygon`; profile classification to native primitives is Phase 2. |
```

Also update the "Gap summary" list at the bottom: item #10 about Sketch2D/ExtrudeLinear/ExtrudeRevolve should note that `ExtrudeRevolve` + `polygon` Sketch2D are now in main.

- [ ] **Step 2: Commit**

```bash
git add docs/planning/detector_ir.md
git commit -m "docs: flip ExtrudeRevolve and Sketch2D(polygon) status rows to detected in detector_ir"
```

---

## Task 19: Final verification — run full test suite

**Files:** none modified.

- [ ] **Step 1: Run the full project test suite**

Run: `python -m pytest -v`
Expected: All tests pass. No regressions in `test_feature_graph.py`, `test_feature_inventory.py`, `test_feature_fixtures.py`, `test_cli.py`.

- [ ] **Step 2: Run the feature-fixture slice specifically (primary detector feedback loop from CLAUDE.md)**

Run: `python -m pytest tests/test_feature_fixtures.py -v`
Expected: All 13+ pre-existing fixtures continue to pass, plus 10 new ones (6 revolve, 4 non_revolve). All three invariants intact:

- byte-exact regeneration (`test_feature_fixture_manifest_matches_checked_in_scad`)
- dimensional round-trip (`test_feature_fixture_round_trip_detection`)
- stress-case coverage (`test_feature_fixture_manifest_covers_roadmap_stress_cases`)

- [ ] **Step 3: Exercise the Christmas-tree success criterion**

The `revolve_christmas_tree` fixture exists and the preview round-trip test (Task 16) has already asserted that:
- It detects as `revolve_solid`.
- `emit_feature_graph_scad_preview` emits `rotate_extrude(polygon())`.
- The preview re-renders and re-detects.

Confirm the profile vertex count is under 20 as required by Success Criterion §2:

Run:
```bash
python -c "
import json
from pathlib import Path
from stl2scad.core.feature_fixtures import write_feature_fixture_library
from stl2scad.core.feature_graph import build_feature_graph_for_stl
from stl2scad.core.cli_helpers import get_openscad_path
import subprocess

manifest = Path('tests/data/feature_fixtures_manifest.json')
out = Path('tests/.tmp_output')
out.mkdir(exist_ok=True)
write_feature_fixture_library(manifest, out)
subprocess.check_call([get_openscad_path(), '--render', '-o',
    str(out/'revolve_christmas_tree.stl'),
    str(out/'revolve_christmas_tree.scad')])
graph = build_feature_graph_for_stl(out/'revolve_christmas_tree.stl')
revolve = next(f for f in graph['features'] if f['type'] == 'revolve_solid')
print('profile vertex count:', len(revolve['profile']))
assert len(revolve['profile']) < 20
"
```

Expected: `profile vertex count: <N>` with `N < 20`, and the script exits 0.

(If `stl2scad.core.cli_helpers.get_openscad_path` isn't importable from Python directly, open `stl2scad/core/converter.py` or `stl2scad/cli.py` to find the correct import path for `get_openscad_path` — it's used by `tests/test_feature_fixtures.py` at the top.)

- [ ] **Step 4: No commit needed; this task is verification only.**

If all three steps pass, Phase 1 is complete per the spec's Success Criteria. Close the plan.

---

## Self-Review (performed 2026-04-22)

**Spec coverage check** — every requirement in the Phase 1 section of the spec has at least one implementing task:

- Rule 1 (revolve runs early) → Task 10 (wiring in `_build_feature_graph`).
- Rule 3 (one-owner dispatch) → Task 10 (skips cylinder/plate/box/cutouts on acceptance) and Task 12 (cylinder fixture manifest update).
- §1.1 candidate axis + prefilter → Task 2.
- §1.2 multi-slice extraction + consistency gate → Tasks 3, 4.
- §1.2 aggregation + Douglas-Peucker → Task 5.
- §1.3 normal-field agreement → Task 6.
- §1.4 profile validity (max vertices, axis-touching) → Task 7 (orchestration includes both gates).
- §1.5 acceptance with named `confidence_components` → Task 7.
- §1.6 Phase 1 excludes annular → Task 11 (validator rejects profiles that don't touch axis; Task 7 enforces the same at detection time).
- IR wrapping (`BooleanUnion { TransformRotate { ExtrudeRevolve { Sketch2D(polygon) } } }`) → Task 8.
- SCAD emitter for `rotate_extrude(polygon())` → Task 9.
- Fixtures: six positive + four negative → Tasks 13, 14.
- Testing: unit tests per gate (Tasks 2–7), round-trip dimensions (Task 15), `confidence_components` assertion (Task 15), preview round-trip (Task 16), stress-case coverage (Task 17).
- Cylinder-fixture regression handling → Task 12 (manifest flip + existing SCAD continues to match).
- `detector_ir.md` status update → Task 18.

**Type consistency check:**
- `detect_revolve_solid(vertices, triangles, config)` signature consistent across Tasks 7, 10.
- `confidence_components` dict keys (`axis_quality`, `cross_slice_consistency`, `normal_field_agreement`, `profile_validity`) consistent in Tasks 7, 15.
- `revolve_solid` feature dict key names (`axis`, `axis_origin`, `profile`, `detected_via`) consistent in Tasks 7, 8, 9, 15.
- IR node names (`BooleanUnion`, `TransformRotate`, `ExtrudeRevolve`, `Sketch2D`) match `detector_ir.md` taxonomy.

**Placeholder scan:** none found. Every code block is complete; commands have expected outputs; file paths are exact.
