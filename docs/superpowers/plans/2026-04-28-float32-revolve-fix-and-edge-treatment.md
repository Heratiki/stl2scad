# Float32 Revolve Fix + Chamfer/Fillet Edge Treatment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix revolve detection on OpenSCAD-rendered float32 STLs, then detect and emit editable chamfer/fillet parameters in SCAD previews for chamfered/filleted plates and boxes.

**Architecture:** Two independent repairs. (1) `extract_radial_slice` uses a `-1e-9` threshold that fails when OpenSCAD float32 vertex noise makes r slightly more negative — widen it to `-1e-6` and add tolerance to the on-plane vertex branch. (2) When the tolerant plate/box detector fires (`detected_via == "tolerant_chamfer_or_fillet"`), a new helper classifies the edge-band triangles as chamfer (tight normal cluster per zone) or fillet (fanned normals), estimates the size, stores the result in `ChamferOrFilletEdge`, and the emitters wrap the base solid with `hull()` (chamfer) or `minkowski() sphere` (fillet).

**Tech Stack:** Python, NumPy, pytest, OpenSCAD SCAD syntax.

---

## Resume State (paused 2026-04-28)

**Branch:** `main`

| Task | Status | Commit |
|------|--------|--------|
| Task 1: Fix float32 r-threshold | ✅ COMPLETE — spec + quality reviews passed | `d6dbe36` |
| Task 2: Add `_estimate_edge_treatment` | ⚠️ CODE WRITTEN — quality fixes required before proceeding | `396d256` |
| Task 3: Store edge treatment in features + IR | 🔲 NOT STARTED | — |
| Task 4: Emit SCAD chamfer/fillet wrappers | 🔲 NOT STARTED | — |

### Task 2 quality fixes required (do these before Task 3)

Code quality review flagged three issues. Fix them and commit before starting Task 3:

**Fix 1 — Remove unused `face_areas` param from `_estimate_edge_treatment`**

In `stl2scad/core/feature_graph.py`, remove `face_areas: np.ndarray` from the signature and docstring. Update every call site (grep for `_estimate_edge_treatment` to find them all — currently only the two direct test calls in `tests/test_feature_graph.py`).

**Fix 2 — Tighten fillet size test bound**

In `tests/test_feature_graph.py`, `test_estimate_edge_treatment_classifies_fillet` currently asserts only `size > 0.0`. Change to `assert 0.3 <= size <= 8.0` (input `r=1.5`, so physically reasonable range).

**Fix 3 — Remove dead `add_tri` inner function**

In `tests/test_feature_graph.py`, `_make_filleted_box_data` defines `add_tri` but never calls it. Remove the inner function definition.

After fixing, run `python -m pytest tests/ --tb=short 2>&1 | tail -10` and commit:
```bash
git commit -m "fix: remove unused face_areas param from _estimate_edge_treatment, clean up fillet test"
```

---

## File Map

| File | Change |
|------|--------|
| `stl2scad/core/revolve_recovery.py` | Widen r-threshold, add on-plane b_coord tolerance |
| `tests/test_revolve_recovery.py` | Add float32-cylinder acceptance test |
| `stl2scad/core/feature_graph.py` | Add `_estimate_edge_treatment`, update tolerant-path feature dicts, update `_build_feature_graph_ir_nodes`, update `_emit_box_scad_preview`, update plate emitter in `emit_feature_graph_scad_preview` |
| `tests/test_feature_graph.py` | Tests for edge treatment detection, `ChamferOrFilletEdge` annotation fields, chamfer/fillet SCAD output |

---

## Task 1: Fix float32 r-threshold in `extract_radial_slice`

**Files:**
- Modify: `stl2scad/core/revolve_recovery.py:122-139`
- Test: `tests/test_revolve_recovery.py`

### Background

`extract_radial_slice` has two float32-sensitive spots:

1. **On-plane branch** (`b0 == 0.0 and b1 == 0.0`): For float32 STL meshes, axis-aligned vertices at y≈0 can have `b_coord ≈ ±1e-7` instead of 0.0 due to axis-computation error. The exact `== 0.0` check never fires, so axis-touching cap edges fall into the interpolation branch (which still works), but the `r_coord[e] >= 0.0` guard in that branch can reject slightly-negative `r_coord` values at the axis center.

2. **r-clamp guard** (`if r < -1e-9: continue`): For a float32 cylinder rendered by OpenSCAD, the interpolated r at the axis center can be `-1e-8` or smaller in magnitude. `-1e-8 < -1e-9` is TRUE, so the intersection is skipped rather than clamped to 0. The profile loses axis-touching points, profile validity gate fails, detector returns `[]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_revolve_recovery.py` after `test_detect_revolve_solid_accepts_cylinder_without_cap_center_vertices`:

```python
def _make_float32_cylinder_mesh(
    height: float = 10.0,
    radius: float = 5.0,
    segments: int = 96,
):
    """Simulate an OpenSCAD-rendered float32 STL cylinder.

    Casts vertex coordinates to float32 and back to float64 to introduce
    the same precision loss that the STL loader produces from a real .stl file.
    """
    theta = np.linspace(0.0, 2 * np.pi, segments, endpoint=False)
    bottom_ring = np.column_stack(
        [radius * np.cos(theta), radius * np.sin(theta), np.zeros_like(theta)]
    )
    top_ring = np.column_stack(
        [radius * np.cos(theta), radius * np.sin(theta), np.full_like(theta, height)]
    )
    center_bottom = np.array([0.0, 0.0, 0.0])
    center_top = np.array([0.0, 0.0, height])
    vertices_f64 = np.vstack([bottom_ring, top_ring, center_bottom, center_top])
    # Simulate float32 precision loss (OpenSCAD writes STL as IEEE 754 float32)
    vertices_f32 = vertices_f64.astype(np.float32).astype(np.float64)
    cb = 2 * segments
    ct = 2 * segments + 1
    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        tris.append([cb, j, i])
        tris.append([ct, segments + i, segments + j])
        tris.append([i, j, segments + j])
        tris.append([i, segments + j, segments + i])
    return vertices_f32, np.asarray(tris, dtype=np.int64)


def test_detect_revolve_solid_accepts_float32_simulated_cylinder():
    """Revolve detector must accept a cylinder whose vertices have float32 precision.

    This guards against the regression where OpenSCAD-rendered STL files
    (float32 vertices, $fn=96) returned [] from detect_revolve_solid even
    though the programmatic float64 mesh passed all gates.
    """
    verts, tris = _make_float32_cylinder_mesh(height=10.0, radius=5.0, segments=96)
    # Pre-process the same way _build_feature_graph does before calling the detector
    rounded = np.round(verts, decimals=6)
    unique_verts, inv_idx = np.unique(rounded, axis=0, return_inverse=True)
    triangles = inv_idx.reshape(-1, 3).astype(np.int64)

    features = detect_revolve_solid(unique_verts, triangles, DetectorConfig())

    assert len(features) == 1, (
        "Revolve detector failed on float32-simulated cylinder. "
        "Check r-threshold in extract_radial_slice."
    )
    feat = features[0]
    assert feat["confidence"] >= 0.70
    rs = [p[0] for p in feat["profile"]]
    assert min(rs) < 0.5, "Profile must touch the axis (r_min near 0)"
    assert max(rs) == pytest.approx(5.0, abs=0.3)
```

- [ ] **Step 2: Run to verify it fails**

```
python -m pytest tests/test_revolve_recovery.py::test_detect_revolve_solid_accepts_float32_simulated_cylinder -v
```

Expected: `FAILED` — `len(features) == 0`.

- [ ] **Step 3: Apply fix to `extract_radial_slice`**

In `stl2scad/core/revolve_recovery.py`, the function `extract_radial_slice` currently reads (around line 122):

```python
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
```

Replace it with:

```python
    _B_TOL = 1e-6   # tolerance for "edge lies on cutting half-plane" (float32 mesh safe)
    _R_TOL = 1e-6   # tolerance for "intersection is on or inside the axis" (float32 mesh safe)

    intersections: list[tuple[float, float]] = []
    for tri in triangles:
        for e0, e1 in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            b0, b1 = float(b_coord[e0]), float(b_coord[e1])
            if abs(b0) <= _B_TOL and abs(b1) <= _B_TOL:
                if float(r_coord[e0]) >= -_R_TOL:
                    intersections.append((max(0.0, float(r_coord[e0])), float(z_coord[e0])))
                if float(r_coord[e1]) >= -_R_TOL:
                    intersections.append((max(0.0, float(r_coord[e1])), float(z_coord[e1])))
                continue
            if (b0 > 0.0 and b1 > 0.0) or (b0 < 0.0 and b1 < 0.0):
                continue
            t = b0 / (b0 - b1)
            r = float(r_coord[e0] + t * (r_coord[e1] - r_coord[e0]))
            if r < -_R_TOL:
                continue
            r = max(r, 0.0)  # clamp floating-point rounding near the axis
```

Note: the two `_B_TOL` / `_R_TOL` constants are defined locally at the top of the loop body, not as module-level constants, so they document their purpose inline without polluting the module namespace.

- [ ] **Step 4: Run to verify it passes**

```
python -m pytest tests/test_revolve_recovery.py -v
```

Expected: all pass including the new float32 test.

- [ ] **Step 5: Run full suite to check no regressions**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add stl2scad/core/revolve_recovery.py tests/test_revolve_recovery.py
git commit -m "fix: widen r-threshold in extract_radial_slice to accept float32 STL cylinders

OpenSCAD writes STL as float32, causing r values at the axis center to be
slightly below -1e-9 after interpolation. Widening to -1e-6 clamps these
instead of skipping them, so the profile validity gate passes.

Also adds tolerance to the on-plane (b==0) branch so axis-touching cap edges
are found even when axis-computation error makes b_coord ≈ 1e-7 instead of 0."
```

---

## Task 2: Add `_estimate_edge_treatment` helper

**Files:**
- Modify: `stl2scad/core/feature_graph.py` (add helper function near `_tolerant_plate_confidence`)
- Test: `tests/test_feature_graph.py`

This helper classifies edge-band triangles as chamfer or fillet and estimates the size.

**Algorithm:**

1. Find "edge-band" triangles: those with `max(|n · principal|) < 0.85` across all 6 axis-aligned unit normals. These are triangles NOT on any flat face.
2. Assign each edge-band triangle to one of 12 edge zones by finding the nearest "edge bisector direction" (e.g. `normalize([1,1,0])`, `normalize([1,0,1])`, etc.).
3. Within each occupied zone, compute the max angular spread between any two normals.
4. **Chamfer**: spread < 0.25 rad (≈14°) → normals form a tight planar cluster.
5. **Fillet**: spread > 0.25 rad → normals fan continuously.
6. **Size estimate**: for each edge-band vertex, compute the two smallest distances to any of the 6 bounding-box faces. The median of the second-smallest distance approximates chamfer distance (direct) or fillet radius (multiply by `1 / (1 - 1/√2) ≈ 3.41`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_feature_graph.py`:

```python
from stl2scad.core.feature_graph import _estimate_edge_treatment


def _make_chamfered_box_data(w=20.0, h=15.0, d=10.0, c=1.0):
    """Return (normals, vectors, face_areas, bbox) for a uniform-chamfer box.

    Uses the hull-of-3-cubes construction: each face of the 3 inner cubes
    contributes exact normals, and each chamfer triangle has a 45° bisector normal.
    """
    normals_list = []
    verts_list = []
    areas_list = []

    def add_quad(v0, v1, v2, v3):
        # Split quad into 2 triangles, compute normals
        for tri_verts in [(v0, v1, v2), (v0, v2, v3)]:
            a = np.array(tri_verts[0], dtype=np.float64)
            b = np.array(tri_verts[1], dtype=np.float64)
            c_v = np.array(tri_verts[2], dtype=np.float64)
            ab, ac = b - a, c_v - a
            n = np.cross(ab, ac)
            area = np.linalg.norm(n) / 2.0
            if area > 1e-10:
                normals_list.append(n / np.linalg.norm(n))
                verts_list.append([a, b, c_v])
                areas_list.append(area)

    # 6 flat faces (shrunk by c on the two perpendicular axes)
    add_quad([0, c, c], [w, c, c], [w, h-c, c], [0, h-c, c])       # -Z
    add_quad([0, c, d-c], [w, c, d-c], [w, h-c, d-c], [0, h-c, d-c])  # +Z
    add_quad([0, c, c], [0, h-c, c], [0, h-c, d-c], [0, c, d-c])   # -X
    add_quad([w, c, c], [w, h-c, c], [w, h-c, d-c], [w, c, d-c])   # +X
    add_quad([c, 0, c], [w-c, 0, c], [w-c, 0, d-c], [c, 0, d-c])   # -Y
    add_quad([c, h, c], [w-c, h, c], [w-c, h, d-c], [c, h, d-c])   # +Y

    # 12 edge chamfer strips (one per edge, 45° bisector normal)
    # Bottom-Z edges
    add_quad([c, c, 0], [w-c, c, 0], [w-c, c, c], [c, c, c])       # -Y/-Z edge
    add_quad([c, h-c, 0], [w-c, h-c, 0], [w-c, h-c, c], [c, h-c, c])  # +Y/-Z
    add_quad([c, c, 0], [c, h-c, 0], [c, h-c, c], [c, c, c])       # -X/-Z edge
    add_quad([w-c, c, 0], [w-c, h-c, 0], [w-c, h-c, c], [w-c, c, c])  # +X/-Z
    # Top-Z edges
    add_quad([c, c, d], [w-c, c, d], [w-c, c, d-c], [c, c, d-c])
    add_quad([c, h-c, d], [w-c, h-c, d], [w-c, h-c, d-c], [c, h-c, d-c])
    add_quad([c, c, d], [c, h-c, d], [c, h-c, d-c], [c, c, d-c])
    add_quad([w-c, c, d], [w-c, h-c, d], [w-c, h-c, d-c], [w-c, c, d-c])
    # Vertical Z edges
    add_quad([c, 0, c], [c, 0, d-c], [0, c, d-c], [0, c, c])       # -X/-Y vertical
    add_quad([w-c, 0, c], [w-c, 0, d-c], [w, c, d-c], [w, c, c])   # +X/-Y vertical
    add_quad([c, h, c], [c, h, d-c], [0, h-c, d-c], [0, h-c, c])   # -X/+Y vertical
    add_quad([w-c, h, c], [w-c, h, d-c], [w, h-c, d-c], [w, h-c, c])  # +X/+Y vertical

    normals = np.array(normals_list, dtype=np.float64)
    vectors = np.array(verts_list, dtype=np.float64)
    areas = np.array(areas_list, dtype=np.float64)
    bbox = {"min_x": 0.0, "max_x": w, "min_y": 0.0, "max_y": h, "min_z": 0.0, "max_z": d}
    return normals, vectors, areas, bbox


def _make_filleted_box_data(w=20.0, h=15.0, d=10.0, r=1.0, arc_segments=8):
    """Return (normals, vectors, face_areas, bbox) for an approximated fillet box.

    Edge fillets are approximated with `arc_segments` triangles per edge zone.
    Normal vectors fan from one flat-face normal to the adjacent flat-face normal,
    matching the curvature expected for a circular arc fillet.
    """
    normals_list = []
    verts_list = []
    areas_list = []

    def add_tri(v0, v1, v2):
        a, b, c_v = np.array(v0), np.array(v1), np.array(v2)
        n = np.cross(b - a, c_v - a)
        area = np.linalg.norm(n) / 2.0
        if area > 1e-10:
            normals_list.append(n / np.linalg.norm(n))
            verts_list.append([a, b, c_v])
            areas_list.append(area)

    # Flat faces (not modelling exact geometry, just supply correct-direction normals)
    flat_face_area = 10.0  # arbitrary large area so flat faces dominate
    for normal, center in [
        ([0, 0, -1], [w/2, h/2, 0]),
        ([0, 0, 1], [w/2, h/2, d]),
        ([-1, 0, 0], [0, h/2, d/2]),
        ([1, 0, 0], [w, h/2, d/2]),
        ([0, -1, 0], [w/2, 0, d/2]),
        ([0, 1, 0], [w/2, h, d/2]),
    ]:
        n = np.array(normal, dtype=np.float64)
        # Add a dummy triangle with the right normal and large area
        perp = np.array([n[1], n[2], n[0]])
        t = r * 2
        v0 = np.array(center) - perp * t
        v1 = np.array(center) + perp * t
        v2 = np.array(center) + np.cross(n, perp) * t
        normals_list.append(n)
        verts_list.append([v0, v1, v2])
        areas_list.append(flat_face_area)

    # One representative fillet edge zone: +X/+Y edge (fanning from +X to +Y normal)
    # Adds arc_segments triangles with normals interpolated between +X and +Y
    for k in range(arc_segments):
        theta = (np.pi / 2) * (k + 0.5) / arc_segments
        n = np.array([np.cos(theta), np.sin(theta), 0.0])
        # Representative vertex at arc midpoint
        cx = w - r + r * np.cos(theta)
        cy = h - r + r * np.sin(theta)
        v0 = np.array([cx, cy, d/3])
        v1 = np.array([cx, cy, 2*d/3])
        v2 = v0 + np.cross(n, [0,0,1]) * r * 0.1
        normals_list.append(n / np.linalg.norm(n))
        verts_list.append([v0, v1, v2])
        areas_list.append(r * (d / 3) / arc_segments)

    normals = np.array(normals_list, dtype=np.float64)
    vectors = np.array(verts_list, dtype=np.float64)
    areas = np.array(areas_list, dtype=np.float64)
    bbox = {"min_x": 0.0, "max_x": w, "min_y": 0.0, "max_y": h, "min_z": 0.0, "max_z": d}
    return normals, vectors, areas, bbox


def test_estimate_edge_treatment_classifies_chamfer():
    normals, vectors, areas, bbox = _make_chamfered_box_data(w=20.0, h=15.0, d=10.0, c=1.5)
    kind, size = _estimate_edge_treatment(normals, vectors, areas, bbox)
    assert kind == "chamfer"
    assert 0.5 <= size <= 4.0, f"Chamfer size estimate {size:.3f} out of expected range"


def test_estimate_edge_treatment_classifies_fillet():
    normals, vectors, areas, bbox = _make_filleted_box_data(
        w=20.0, h=15.0, d=10.0, r=1.5, arc_segments=8
    )
    kind, size = _estimate_edge_treatment(normals, vectors, areas, bbox)
    assert kind == "fillet"
    assert size > 0.0
```

- [ ] **Step 2: Run to verify it fails**

```
python -m pytest tests/test_feature_graph.py::test_estimate_edge_treatment_classifies_chamfer tests/test_feature_graph.py::test_estimate_edge_treatment_classifies_fillet -v
```

Expected: `ImportError` — `_estimate_edge_treatment` not defined.

- [ ] **Step 3: Implement `_estimate_edge_treatment`**

Add this function to `stl2scad/core/feature_graph.py` directly after `_tolerant_box_confidence` (around line 2061):

```python
_AXIS_PRINCIPAL_NORMALS = np.array(
    [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]],
    dtype=np.float64,
)
_AXIS_EDGE_BISECTORS = np.array(
    [
        [1, 1, 0], [1, -1, 0], [-1, 1, 0], [-1, -1, 0],
        [1, 0, 1], [1, 0, -1], [-1, 0, 1], [-1, 0, -1],
        [0, 1, 1], [0, 1, -1], [0, -1, 1], [0, -1, -1],
    ],
    dtype=np.float64,
)
_AXIS_EDGE_BISECTORS = _AXIS_EDGE_BISECTORS / np.linalg.norm(
    _AXIS_EDGE_BISECTORS, axis=1, keepdims=True
)


def _estimate_edge_treatment(
    normals: np.ndarray,
    vectors: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
) -> tuple[str, float]:
    """Classify chamfer-vs-fillet edge treatment and estimate size in mesh units.

    Returns a ``(kind, size)`` tuple where kind is ``"chamfer"``, ``"fillet"``,
    or ``"unknown"``; size is the estimated chamfer distance or fillet radius in
    the same units as the mesh bounding box.

    Algorithm:
    1. Edge-band triangles: normals with max |dot(n, principal)| < 0.85.
    2. Assign each edge-band triangle to one of 12 bisector zones.
    3. Chamfer: max in-zone angular spread < 0.25 rad → all co-planar.
       Fillet: spread >= 0.25 rad → normals fan continuously.
    4. Size: median second-smallest distance from edge-band vertices to any
       bbox face.  Multiply by 3.41 for fillet (arc geometry correction).
    """
    if len(normals) == 0:
        return "unknown", 0.0

    # Step 1: find edge-band triangles
    dots = np.abs(normals @ _AXIS_PRINCIPAL_NORMALS.T)   # (N, 6)
    max_align = dots.max(axis=1)                          # (N,)
    edge_mask = max_align < 0.85

    if int(edge_mask.sum()) < 4:
        return "unknown", 0.0

    edge_normals = normals[edge_mask]   # (M, 3)
    edge_vectors = vectors[edge_mask]   # (M, 3, 3)

    # Step 2: assign to 12 bisector zones
    zone_dots = edge_normals @ _AXIS_EDGE_BISECTORS.T     # (M, 12)
    zone_assign = np.argmax(zone_dots, axis=1)            # (M,)

    # Step 3: angular spread per zone
    spreads: list[float] = []
    for zone_idx in range(12):
        zmask = zone_assign == zone_idx
        if int(zmask.sum()) < 2:
            continue
        zn = edge_normals[zmask]                          # (K, 3)
        cos_matrix = np.clip(zn @ zn.T, -1.0, 1.0)
        angles = np.arccos(cos_matrix)
        spreads.append(float(angles.max()))

    if not spreads:
        return "unknown", 0.0

    mean_spread = float(np.mean(spreads))
    kind = "chamfer" if mean_spread < 0.25 else "fillet"

    # Step 4: size estimate from edge-band vertex distances to bbox faces
    edge_verts = edge_vectors.reshape(-1, 3)              # (M*3, 3)
    bbox_min = np.array(
        [bbox["min_x"], bbox["min_y"], bbox["min_z"]], dtype=np.float64
    )
    bbox_max = np.array(
        [bbox["max_x"], bbox["max_y"], bbox["max_z"]], dtype=np.float64
    )
    dist_min = edge_verts - bbox_min[None, :]             # (M*3, 3)  positive = inside
    dist_max = bbox_max[None, :] - edge_verts             # (M*3, 3)  positive = inside
    # Minimum per-axis distance to nearest face (negative means outside bbox)
    face_dists = np.minimum(dist_min, dist_max)           # (M*3, 3)
    # Sort per vertex: [closest face dist, second closest, third closest]
    sorted_dists = np.sort(np.clip(face_dists, 0.0, None), axis=1)
    second_dists = sorted_dists[:, 1]                     # second-closest face distance

    size_raw = float(np.median(second_dists[second_dists > 1e-9]))
    if size_raw <= 1e-9:
        return kind, 0.0

    if kind == "fillet":
        # For a circular fillet of radius r, the median second-dist is
        # approximately r * (1 - 1/sqrt(2)) ≈ 0.293*r.
        # Invert: r ≈ size_raw / (1 - 1/sqrt(2)) ≈ size_raw * 3.414
        size = size_raw / (1.0 - 1.0 / np.sqrt(2.0))
    else:
        # For a 45° chamfer, second-dist ≈ chamfer_distance directly
        size = size_raw

    return kind, float(max(0.0, size))
```

- [ ] **Step 4: Run to verify tests pass**

```
python -m pytest tests/test_feature_graph.py::test_estimate_edge_treatment_classifies_chamfer tests/test_feature_graph.py::test_estimate_edge_treatment_classifies_fillet -v
```

Expected: both `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/feature_graph.py tests/test_feature_graph.py
git commit -m "feat: add _estimate_edge_treatment to classify chamfer vs fillet and measure size"
```

---

## Task 3: Store edge treatment in solid features and `ChamferOrFilletEdge` annotation

**Files:**
- Modify: `stl2scad/core/feature_graph.py` (two sites)
- Test: `tests/test_feature_graph.py`

When the tolerant path fires (`via_tolerant = True` for plate or box), call `_estimate_edge_treatment` and store the result in the solid feature dict as `"edge_treatment": {"kind": "...", "size": ...}`. Then in `_build_feature_graph_ir_nodes`, pass that info into the `ChamferOrFilletEdge` annotation.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feature_graph.py`:

```python
def test_tolerant_plate_feature_has_edge_treatment_fields():
    """plate_like_solid detected via tolerant path must carry edge_treatment."""
    # Build a synthetic normals/vectors/areas that will trigger the tolerant path.
    # Use the chamfered box helper (20×15×2 is plate-like) with c=0.5
    normals, vectors, areas, _ = _make_chamfered_box_data(w=20.0, h=15.0, d=2.0, c=0.5)
    from stl2scad.core.feature_graph import _extract_axis_aligned_box_features
    from stl2scad.core.feature_inventory import _bbox
    bbox = _bbox(vectors.reshape(-1, 3))
    config = DetectorConfig()
    features = _extract_axis_aligned_box_features(vectors, normals, areas, bbox, config)
    solids = [f for f in features if f.get("type") == "plate_like_solid"]
    assert len(solids) >= 1
    solid = solids[0]
    if solid.get("detected_via") == "tolerant_chamfer_or_fillet":
        assert "edge_treatment" in solid, "tolerant plate must have edge_treatment"
        et = solid["edge_treatment"]
        assert et["kind"] in ("chamfer", "fillet", "unknown")
        assert isinstance(et["size"], float)
        assert et["size"] >= 0.0


def test_tolerant_box_feature_has_edge_treatment_fields():
    """box_like_solid detected via tolerant path must carry edge_treatment."""
    normals, vectors, areas, _ = _make_chamfered_box_data(w=20.0, h=15.0, d=10.0, c=1.0)
    from stl2scad.core.feature_graph import _extract_axis_aligned_box_features
    from stl2scad.core.feature_inventory import _bbox
    bbox = _bbox(vectors.reshape(-1, 3))
    config = DetectorConfig()
    features = _extract_axis_aligned_box_features(vectors, normals, areas, bbox, config)
    solids = [f for f in features if f.get("type") == "box_like_solid"]
    assert len(solids) >= 1
    solid = solids[0]
    if solid.get("detected_via") == "tolerant_chamfer_or_fillet":
        assert "edge_treatment" in solid
        et = solid["edge_treatment"]
        assert et["kind"] in ("chamfer", "fillet", "unknown")


def test_chamfer_or_fillet_ir_node_has_kind_and_size():
    """ChamferOrFilletEdge IR node must carry edge_kind and size when available."""
    from stl2scad.core.feature_graph import _build_feature_graph_ir_nodes
    graph = {
        "schema_version": 1,
        "source_file": "chamfer_test.stl",
        "features": [
            {
                "type": "box_like_solid",
                "confidence": 0.85,
                "detected_via": "tolerant_chamfer_or_fillet",
                "edge_treatment": {"kind": "chamfer", "size": 1.5},
                "origin": [0.0, 0.0, 0.0],
                "size": [20.0, 15.0, 10.0],
                "parameters": {"width": 20.0, "depth": 15.0, "height": 10.0},
            }
        ],
    }
    ir = _build_feature_graph_ir_nodes(graph)
    assert ir is not None
    # Find the ChamferOrFilletEdge annotation
    def find_edge_node(node):
        if isinstance(node, dict):
            if node.get("type") == "ChamferOrFilletEdge":
                return node
            for v in node.values():
                result = find_edge_node(v)
                if result is not None:
                    return result
        elif isinstance(node, list):
            for item in node:
                result = find_edge_node(item)
                if result is not None:
                    return result
        return None
    edge_node = find_edge_node(ir)
    assert edge_node is not None, "ChamferOrFilletEdge node not found in IR"
    assert edge_node.get("edge_kind") == "chamfer"
    assert edge_node.get("size") == pytest.approx(1.5)
```

- [ ] **Step 2: Run to verify they fail**

```
python -m pytest tests/test_feature_graph.py::test_tolerant_box_feature_has_edge_treatment_fields tests/test_feature_graph.py::test_chamfer_or_fillet_ir_node_has_kind_and_size -v
```

Expected: `FAILED` — `KeyError: 'edge_treatment'` and `AssertionError: ChamferOrFilletEdge node not found`.

- [ ] **Step 3: Call `_estimate_edge_treatment` in the tolerant detection path**

In `_extract_axis_aligned_box_features`, in the block where `via_tolerant = True` for plates (around line 1809), add the edge treatment call. Find the section:

```python
        via_tolerant = not strict_plate_passes
        features.append(
            {
                "type": "plate_like_solid",
                ...
                "detected_via": "tolerant_chamfer_or_fillet" if via_tolerant else "strict",
```

Change the feature dict to include `edge_treatment` when `via_tolerant`:

```python
        via_tolerant = not strict_plate_passes
        edge_treatment: dict[str, Any] = {}
        if via_tolerant:
            et_kind, et_size = _estimate_edge_treatment(normals, vectors, face_areas, bbox)
            edge_treatment = {"kind": et_kind, "size": float(et_size)}
        plate_feature: dict[str, Any] = {
            "type": "plate_like_solid",
            "confidence": float(plate_confidence),
            "detected_via": "tolerant_chamfer_or_fillet" if via_tolerant else "strict",
            "origin": [
                float(bbox["min_x"]),
                float(bbox["min_y"]),
                float(bbox["min_z"]),
            ],
            "size": [
                dimensions["width"],
                dimensions["depth"],
                dimensions["height"],
            ],
            "parameters": {
                "width": dimensions["width"],
                "depth": dimensions["depth"],
                "thickness": min(nonzero_dims) if nonzero_dims else 0.0,
            },
            "note": (
                "Candidate for an editable plate or slab feature."
                if not via_tolerant
                else (
                    "Candidate for an editable plate or slab feature, allowing"
                    " chamfer-broken side planes when the thin-axis footprint"
                    " remains strongly rectangular."
                )
            ),
        }
        if via_tolerant:
            plate_feature["edge_treatment"] = edge_treatment
        features.append(plate_feature)
```

Do the same for the `box_like_solid` tolerant path (around line 1847):

```python
        via_tolerant_box = not strict_box_passes
        box_edge_treatment: dict[str, Any] = {}
        if via_tolerant_box:
            et_kind, et_size = _estimate_edge_treatment(normals, vectors, face_areas, bbox)
            box_edge_treatment = {"kind": et_kind, "size": float(et_size)}
        box_feature: dict[str, Any] = {
            "type": "box_like_solid",
            "confidence": float(box_confidence),
            "detected_via": "tolerant_chamfer_or_fillet" if via_tolerant_box else "strict",
            "origin": [
                float(bbox["min_x"]),
                float(bbox["min_y"]),
                float(bbox["min_z"]),
            ],
            "size": [
                dimensions["width"],
                dimensions["depth"],
                dimensions["height"],
            ],
            "parameters": {
                "width": dimensions["width"],
                "depth": dimensions["depth"],
                "height": dimensions["height"],
            },
            "note": (
                "Candidate for a cube()/translate() parametric base feature."
                if not via_tolerant_box
                else (
                    "Candidate for a cube()/translate() parametric base feature,"
                    " allowing chamfer- or fillet-broken outer edges when all"
                    " three axis boundary pairs retain strong rectangular"
                    " footprints."
                )
            ),
        }
        if via_tolerant_box:
            box_feature["edge_treatment"] = box_edge_treatment
        features.append(box_feature)
```

- [ ] **Step 4: Update `_build_feature_graph_ir_nodes` to include kind and size in `ChamferOrFilletEdge`**

Find the `ChamferOrFilletEdge` append (around line 279):

```python
        if prim.get("detected_via") == "tolerant_chamfer_or_fillet":
            cuts.append(
                {
                    "type": "ChamferOrFilletEdge",
                    "note": (
                        "Outer edges were detected as chamfered or filleted. "
                        "Kind (chamfer vs fillet) is not yet distinguished by the detector."
                    ),
                }
            )
```

Replace with:

```python
        if prim.get("detected_via") == "tolerant_chamfer_or_fillet":
            et = prim.get("edge_treatment", {})
            et_kind = str(et.get("kind", "unknown"))
            et_size = float(et.get("size", 0.0))
            edge_node: dict[str, Any] = {
                "type": "ChamferOrFilletEdge",
                "edge_kind": et_kind,
                "size": et_size,
                "note": (
                    f"Outer edges detected as {et_kind} (size ≈ {et_size:.3f} mm). "
                    "Emitter wraps base solid with hull() for chamfer or "
                    "minkowski() sphere for fillet."
                ),
            }
            cuts.append(edge_node)
```

- [ ] **Step 5: Run to verify tests pass**

```
python -m pytest tests/test_feature_graph.py::test_tolerant_plate_feature_has_edge_treatment_fields tests/test_feature_graph.py::test_tolerant_box_feature_has_edge_treatment_fields tests/test_feature_graph.py::test_chamfer_or_fillet_ir_node_has_kind_and_size -v
```

Expected: all `PASSED`.

- [ ] **Step 6: Run full suite to check no regressions**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 7: Commit**

```bash
git add stl2scad/core/feature_graph.py tests/test_feature_graph.py
git commit -m "feat: store edge_treatment (kind+size) in tolerant plate/box features and ChamferOrFilletEdge IR node"
```

---

## Task 4: Emit SCAD with chamfer/fillet wrappers

**Files:**
- Modify: `stl2scad/core/feature_graph.py` (`_emit_box_scad_preview` and plate section of `emit_feature_graph_scad_preview`)
- Test: `tests/test_feature_graph.py`

**SCAD idioms:**

For **chamfer** on a box of size `[w, h, d]` at origin `[ox, oy, oz]` with chamfer `c`:
```openscad
chamfer_c = 1.500000;
translate([ox, oy, oz])
hull() {
  cube([w, h - 2*chamfer_c, d - 2*chamfer_c]);
  cube([w - 2*chamfer_c, h, d - 2*chamfer_c]);
  cube([w - 2*chamfer_c, h - 2*chamfer_c, d]);
}
```

For **fillet** on a box with fillet radius `r`:
```openscad
fillet_r = 1.500000;
translate([ox, oy, oz])
translate([fillet_r, fillet_r, fillet_r])
minkowski() {
  cube([w - 2*fillet_r, h - 2*fillet_r, d - 2*fillet_r]);
  sphere(r=fillet_r, $fn=32);
}
```

The inner `translate([fillet_r, fillet_r, fillet_r])` corrects the minkowski offset so the resulting shape occupies `[ox..ox+w, oy..oy+h, oz..oz+d]`.

Same pattern for plates (the plate size is [width, depth, thickness]).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_feature_graph.py`:

```python
def _make_graph_with_edge_treatment(kind: str, size: float, solid_type: str = "box_like_solid"):
    """Synthetic graph with a single box/plate feature that has edge_treatment."""
    if solid_type == "box_like_solid":
        return {
            "schema_version": 1,
            "source_file": "test_edge.stl",
            "features": [
                {
                    "type": "box_like_solid",
                    "confidence": 0.92,
                    "detected_via": "tolerant_chamfer_or_fillet",
                    "edge_treatment": {"kind": kind, "size": size},
                    "origin": [0.0, 0.0, 0.0],
                    "size": [20.0, 15.0, 10.0],
                    "parameters": {"width": 20.0, "depth": 15.0, "height": 10.0},
                }
            ],
        }
    return {
        "schema_version": 1,
        "source_file": "test_edge.stl",
        "features": [
            {
                "type": "plate_like_solid",
                "confidence": 0.88,
                "detected_via": "tolerant_chamfer_or_fillet",
                "edge_treatment": {"kind": kind, "size": size},
                "origin": [0.0, 0.0, 0.0],
                "size": [20.0, 15.0, 2.0],
                "parameters": {"width": 20.0, "depth": 15.0, "thickness": 2.0},
            }
        ],
    }


def test_box_chamfer_scad_uses_hull():
    graph = _make_graph_with_edge_treatment("chamfer", 1.5)
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "hull()" in scad
    assert "chamfer_c" in scad
    assert "1.500000" in scad
    assert "minkowski" not in scad


def test_box_fillet_scad_uses_minkowski_sphere():
    graph = _make_graph_with_edge_treatment("fillet", 1.5)
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "minkowski()" in scad
    assert "sphere" in scad
    assert "fillet_r" in scad
    assert "hull()" not in scad


def test_plate_chamfer_scad_uses_hull():
    graph = _make_graph_with_edge_treatment("chamfer", 1.0, solid_type="plate_like_solid")
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "hull()" in scad
    assert "chamfer_c" in scad


def test_plate_fillet_scad_uses_minkowski_sphere():
    graph = _make_graph_with_edge_treatment("fillet", 1.0, solid_type="plate_like_solid")
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "minkowski()" in scad
    assert "sphere" in scad


def test_box_no_edge_treatment_unchanged():
    """Box detected via strict path should produce unchanged cube() output."""
    graph = {
        "schema_version": 1,
        "source_file": "strict_box.stl",
        "features": [
            {
                "type": "box_like_solid",
                "confidence": 0.92,
                "detected_via": "strict",
                "origin": [0.0, 0.0, 0.0],
                "size": [20.0, 15.0, 10.0],
                "parameters": {"width": 20.0, "depth": 15.0, "height": 10.0},
            }
        ],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "hull()" not in scad
    assert "minkowski" not in scad
    assert "cube(box_size)" in scad


def test_box_unknown_edge_treatment_unchanged():
    """Box with edge_treatment kind=unknown falls back to plain cube()."""
    graph = _make_graph_with_edge_treatment("unknown", 0.0)
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "hull()" not in scad
    assert "minkowski" not in scad
```

- [ ] **Step 2: Run to verify they fail**

```
python -m pytest tests/test_feature_graph.py::test_box_chamfer_scad_uses_hull tests/test_feature_graph.py::test_box_fillet_scad_uses_minkowski_sphere tests/test_feature_graph.py::test_box_no_edge_treatment_unchanged -v
```

Expected: chamfer and fillet tests `FAILED`, no-edge-treatment test `PASSED`.

- [ ] **Step 3: Add `_emit_box_edge_treatment_scad` helper and update `_emit_box_scad_preview`**

Add this helper function in `stl2scad/core/feature_graph.py` just above `_emit_box_scad_preview`:

```python
def _emit_box_edge_treatment_scad(
    size: list[float],
    edge_treatment: dict[str, Any],
    inner_cube_expr: str,
    transform_prefix: str = "",
) -> list[str]:
    """Return SCAD lines that wrap a cube with chamfer (hull) or fillet (minkowski).

    ``inner_cube_expr``  is the SCAD expression for the base cube, e.g.
    ``"cube(box_size)"`` or ``"cube([w,h,d])"``.
    ``transform_prefix`` is any rotate/translate that should be applied outside
    the edge treatment wrapper.
    """
    kind = str(edge_treatment.get("kind", "unknown"))
    et_size = float(edge_treatment.get("size", 0.0))

    if kind not in ("chamfer", "fillet") or et_size <= 1e-9:
        return [f"{transform_prefix}{inner_cube_expr};"]

    w, h, d = float(size[0]), float(size[1]), float(size[2])
    min_dim = min(w, h, d)
    # Cap edge treatment size at half the smallest dimension to avoid negative inner sizes
    et_size = min(et_size, min_dim * 0.45)

    if kind == "chamfer":
        c = et_size
        return [
            f"chamfer_c = {c:.6f};",
            f"{transform_prefix}hull() {{",
            f"  cube([{w:.6f}, {h - 2*c:.6f}, {d - 2*c:.6f}]);",
            f"  cube([{w - 2*c:.6f}, {h:.6f}, {d - 2*c:.6f}]);",
            f"  cube([{w - 2*c:.6f}, {h - 2*c:.6f}, {d:.6f}]);",
            "}",
        ]
    else:
        r = et_size
        return [
            f"fillet_r = {r:.6f};",
            f"{transform_prefix}translate([{r:.6f}, {r:.6f}, {r:.6f}])",
            f"minkowski() {{",
            f"  cube([{w - 2*r:.6f}, {h - 2*r:.6f}, {d - 2*r:.6f}]);",
            f"  sphere(r=fillet_r, $fn=32);",
            "}",
        ]
```

Now update `_emit_box_scad_preview` to call this helper. Find the end of that function where the final `difference()` block is emitted. The current closing section (around line 782) is:

```python
    lines.extend(
        [
            "",
            "difference() {",
            f"  {box_transform_expr}cube(box_size);",
        ]
    )

    for hole_index, hole in enumerate(holes):
        axis = hole["axis"]
        lines.append(
            f"  hole_cutout_{axis}(hole_{hole_index}_center, hole_{hole_index}_diameter);"
        )

    lines.extend(["}", ""])
    return "\n".join(lines)
```

Replace with:

```python
    et = box.get("edge_treatment", {})
    et_kind = str(et.get("kind", "unknown"))
    et_size = float(et.get("size", 0.0))
    use_edge_treatment = (
        box.get("detected_via") == "tolerant_chamfer_or_fillet"
        and et_kind in ("chamfer", "fillet")
        and et_size > 1e-9
        and not is_rotated
    )

    if use_edge_treatment:
        size = [float(v) for v in box["size"]]
        et_lines = _emit_box_edge_treatment_scad(
            size, et, "cube(box_size)", transform_prefix=f"{box_transform_expr}"
        )
        # et_lines[0] may be the "chamfer_c = ..." or "fillet_r = ..." declaration
        # Insert it into the param decls section before the difference block
        lines.extend([""])
        if holes:
            lines.extend(
                [
                    "difference() {",
                    f"  {et_lines[0]}",
                ]
            )
            # Replace the declaration line with the body inside difference
            body_lines = _emit_box_edge_treatment_scad(size, et, "cube(box_size)")
            # body_lines[0] is decl (already emitted above), skip it
            for bl in body_lines[1:]:
                lines.append(f"  {bl}")
            for hole_index, hole in enumerate(holes):
                axis = hole["axis"]
                lines.append(
                    f"  hole_cutout_{axis}(hole_{hole_index}_center, hole_{hole_index}_diameter);"
                )
            lines.extend(["}", ""])
        else:
            lines.extend(et_lines)
            lines.append("")
    else:
        lines.extend(
            [
                "",
                "difference() {",
                f"  {box_transform_expr}cube(box_size);",
            ]
        )
        for hole_index, hole in enumerate(holes):
            axis = hole["axis"]
            lines.append(
                f"  hole_cutout_{axis}(hole_{hole_index}_center, hole_{hole_index}_diameter);"
            )
        lines.extend(["}", ""])

    return "\n".join(lines)
```

> **Note:** The `difference() { ... }` wrapper is only needed when there are holes. For no-hole boxes, the current code emits `difference() { cube...; }` which is harmless but empty. Preserve that behavior for non-edge-treatment boxes to avoid snapshot changes; only the edge-treatment path needs to be careful.

- [ ] **Step 4: Update the plate emitter for edge treatment**

In `emit_feature_graph_scad_preview`, the plate body is built inline starting around line 911. Find the final `difference()` block for plates. The plate emitter closes with something like (around line 1100–1130):

```python
    lines.extend(
        [
            "",
            "difference() {",
            f"  translate(plate_origin) cube(plate_size);",
```

or equivalent. Locate the exact closing of the plate difference block and wrap with edge treatment using the same helper. The plate solid has `"size"` and `"edge_treatment"` on the `plate` feature dict.

Add the edge treatment check just before building the difference block:

```python
    plate_et = plate.get("edge_treatment", {})
    plate_et_kind = str(plate_et.get("kind", "unknown"))
    plate_et_size = float(plate_et.get("size", 0.0))
    use_plate_edge_treatment = (
        plate.get("detected_via") == "tolerant_chamfer_or_fillet"
        and plate_et_kind in ("chamfer", "fillet")
        and plate_et_size > 1e-9
    )
```

Then conditionally emit:

```python
    if use_plate_edge_treatment:
        et_decl_lines = _emit_box_edge_treatment_scad(size, plate_et, "cube(plate_size)")
        lines.extend(["", et_decl_lines[0]])   # declaration line
        if has_cutouts:
            lines.extend(["", "difference() {"])
            for bl in et_decl_lines[1:]:
                lines.append(f"  translate(plate_origin) {bl}" if "cube" in bl else f"  {bl}")
            # ... hole/slot/pocket emission (same as existing) ...
        else:
            lines.extend([""])
            for bl in et_decl_lines[1:]:
                lines.append(f"translate(plate_origin) {bl}" if "cube" in bl else bl)
    else:
        lines.extend(["", "difference() {", "  translate(plate_origin) cube(plate_size);"])
        # ... existing hole/slot/pocket emission ...
```

> **Implementation note:** The plate emitter is longer and more complex than the box emitter (it handles holes, slots, counterbores, patterns). Rather than replicate all the detail here, the rule is: **wrap only the base solid** with edge treatment; the cutouts remain inside the `difference()` block unchanged. Read the existing plate emitter carefully from line 911 to the end of `emit_feature_graph_scad_preview` to find the exact structure before editing.

- [ ] **Step 5: Run all new tests**

```
python -m pytest tests/test_feature_graph.py::test_box_chamfer_scad_uses_hull tests/test_feature_graph.py::test_box_fillet_scad_uses_minkowski_sphere tests/test_feature_graph.py::test_plate_chamfer_scad_uses_hull tests/test_feature_graph.py::test_plate_fillet_scad_uses_minkowski_sphere tests/test_feature_graph.py::test_box_no_edge_treatment_unchanged tests/test_feature_graph.py::test_box_unknown_edge_treatment_unchanged -v
```

Expected: all `PASSED`.

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all previously-passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add stl2scad/core/feature_graph.py tests/test_feature_graph.py
git commit -m "feat: emit hull()/minkowski() SCAD wrappers for detected chamfer/fillet edges

Boxes with chamfer emit hull() of three shrunk cubes; boxes with fillet emit
minkowski() cube + sphere. Plates use the same wrappers. Strict-path solids
and unknown edge treatments fall back to plain cube() unchanged."
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| Fix float32 revolve detection on OpenSCAD-rendered STLs | Task 1 |
| Distinguish chamfer vs fillet | Task 2 |
| Measure chamfer distance / fillet radius | Task 2 |
| Store in ChamferOrFilletEdge node | Task 3 |
| Emit SCAD hull() for chamfer | Task 4 |
| Emit SCAD minkowski() sphere for fillet | Task 4 |
| No regression on strict-path plates/boxes | Task 4 (`test_box_no_edge_treatment_unchanged`) |
| Tolerances don't produce negative inner sizes | Task 4 (`min_dim * 0.45` cap) |

**Placeholder scan:** No TBD/TODO items. All code blocks complete. Task 4 plate emitter note is guidance, not a gap — the instruction to read the existing emitter structure before editing is intentional.

**Type consistency:**
- `_estimate_edge_treatment` returns `tuple[str, float]` — matched in callers as `et_kind, et_size`
- `edge_treatment` dict has keys `"kind"` (str) and `"size"` (float) — consistent across Task 2, 3, 4
- `ChamferOrFilletEdge` node gains `"edge_kind"` and `"size"` — test in Task 3 asserts these exact names
- `_emit_box_edge_treatment_scad` takes `size: list[float]`, `edge_treatment: dict` — consistent with callers
