# Rotate-Extrude and Sketch2D Recovery — Design

## Status

- **Date:** 2026-04-22
- **Target roadmap item:** supersedes most of "Beyond dimensional parity #4" in [feature_level_reconstruction.md](../../planning/feature_level_reconstruction.md), and absorbs parts of Immediate priority #1 (rotated/composite fixtures) and the tier-2 primitive expansion that was previously scoped as individual cone/sphere detectors.
- **IR target:** `ExtrudeRevolve` and `Sketch2D` nodes already defined in [detector_ir.md](../../planning/detector_ir.md). This spec makes them detectable.

## Motivation

Most real mechanical parts are "profile + operation" in design intent. A turned part is a 2D profile rotated around an axis. A gasket is a 2D profile extruded linearly. A Christmas-tree ornament, a bottle, a pulley, a lamp shade, a standoff with a flare, and a drinking glass are all solids of revolution — their *natural* parametric representation is one 2D polygon and one `rotate_extrude()`, not a stack of approximating cones.

The detector today approaches these meshes primitive-by-primitive. A cylinder detector fires on cylindrical sides. A cone detector (unbuilt) would fire on conical sides. A stacked-cone Christmas-tree reconstruction via a composition detector would require N primitives and (N−1) union operations. The `rotate_extrude` representation is one node and produces editable output that responds correctly to design-intent edits ("make the tree taller" = change one parameter, not N).

Critically, **axisymmetry detection subsumes single-primitive rotated detection**. A cylinder is a solid of revolution whose profile is a rectangle. A cone is one whose profile is a triangle. A sphere is one whose profile is a semicircle. Building the axisymmetric pipeline and later *classifying the profile shape* to upgrade the emission to `cylinder()` / `cone()` / `sphere()` is a single coherent dispatch instead of three separate detectors with overlapping signal.

## Phased Plan

This work is scoped as four phases. Phase 1 delivers Christmas-tree-level output end-to-end without any primitive recognition. Each subsequent phase builds on 1 and can land independently.

### Phase 1 — Axisymmetric detection + `rotate_extrude` emission

Goal: any rotationally symmetric mesh produces a `rotate_extrude() polygon([...])` SCAD preview that round-trips.

Components:

1. **Axisymmetry test.** Compute the inertia tensor of the mesh. A solid of revolution has two equal principal moments (the two axes perpendicular to the revolution axis) and one distinct principal moment (along the revolution axis). Confidence score is driven by the ratio similarity and the alignment of face normals with the expected normal field around the detected axis.
2. **Radial-slice profile extraction.** Once an axis is accepted, slice the mesh with a half-plane containing that axis. Project the resulting polyline into the (r, z) plane of the axis's local frame. Merge colinear segments via Douglas-Peucker simplification with a tolerance tied to the mesh's characteristic size.
3. **Profile polygon validation.** The profile must be a simple (non-self-intersecting) polygon that touches the revolution axis at least once (r=0). If not, reject and fall through.
4. **IR emission.** New `Feature` node type `revolve_solid` with:
   - `axis` (world-space 3-vector)
   - `axis_origin` (world-space point on axis)
   - `profile` (list of [r, z] tuples)
   - `confidence`
   - IR wrapping: `BooleanUnion { base: ExtrudeRevolve { profile: Sketch2D(polygon), axis_transform: TransformRotate } }`.
5. **SCAD emitter.** Emit a `rotate_extrude($fn=...)` with a `polygon(points=[...])` child, wrapped in the transform needed to align the local axis with world Z (OpenSCAD's `rotate_extrude` axis). Use named variables for the profile points so downstream edits are readable.

Deliberately excluded from Phase 1: primitive recognition, multi-axis disambiguation when the mesh is spherically symmetric (sphere), handling of `rotate_extrude` with a non-zero inner radius (annular revolve) — both deferred to Phase 2.

### Phase 2 — Profile classification → primitives

Goal: when a detected revolve profile matches a simple parametric shape, upgrade the output from `rotate_extrude(polygon())` to the corresponding primitive call.

- Rectangle profile (4 points, axis-touching on one side) → `cylinder(h, d)`.
- Right-triangle profile (3 points, one leg on axis) → `cylinder(h, d1=..., d2=0)` (cone).
- Semicircle profile (arc from r=0 to r=0 through r=R at z=0) → `sphere(r)`.
- Trapezoid profile (4 points, two parallel to axis at different r) → `cylinder(h, d1, d2)` (frustum).
- Annular rectangle (4 points, none touching axis) → `difference() { cylinder(outer); cylinder(inner); }` or a named `tube()` module.
- Anything else → keep the Phase 1 `rotate_extrude(polygon())` fallback.

Classification is a pattern-match over the simplified profile polygon with tolerances scaled to mesh size. Closes `PrimitiveCone` / `PrimitiveFrustum` / `PrimitiveSphere` / `PrimitiveEllipsoid` gaps from [detector_ir.md](../../planning/detector_ir.md) tier 1 as consequences, not as separate detectors.

### Phase 3 — Linear extrude detection

Goal: meshes with constant cross-section along an axis produce `linear_extrude(h) polygon([...])`.

Components:

1. **Translational-symmetry test.** For a candidate axis, take perpendicular slices at multiple heights and compare them (Fréchet or Hausdorff distance on the 2D outlines). If all slices agree within tolerance, the mesh is translationally symmetric along that axis.
2. **Cross-section extraction.** Project the slice polygon into the (u, v) local plane of the axis and simplify.
3. **IR emission.** `BooleanUnion { base: ExtrudeLinear { profile: Sketch2D(polygon), height, axis_transform } }`.
4. **SCAD emitter.** `linear_extrude(h) polygon(...)` wrapped in alignment transform.

Out of scope for Phase 3: twist, scale taper (`linear_extrude(scale=...)` support), non-convex profiles with holes (the 2D profile can contain `difference()` but detecting that requires the polygon-with-holes extraction — deferred to Phase 4 or later).

### Phase 4 — Composition / stacked detector

Goal: meshes that are *neither* single-axis-revolved *nor* single-axis-extruded but are a *composition* of such objects along a shared axis, unioned together. Example: a stepped shaft, a boss on a plate, a Christmas tree reinterpreted as stacked cones (the less efficient but sometimes-desired representation).

Approach (sketch, subject to revision before Phase 4 starts): segment the mesh along the candidate axis into regions of locally-constant symmetry class, run Phase 1/3 detectors on each segment, emit as `union()` of the segmented results.

Phase 4 is explicitly speculative in this spec. It will get its own design pass when Phases 1-3 have landed and we have real data on where the single-component detectors miss. Do not start Phase 4 until Phases 1-3 are in main.

## Architecture

### New module: `stl2scad/core/revolve_recovery.py`

Phase 1 and Phase 2 live here. Current `feature_graph.py` is already ~2000 lines; adding axisymmetry machinery inline would push it past the point where it's holdable in one editor window. Interface:

```python
def detect_revolve_solid(
    normals: np.ndarray,
    face_areas: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray,
    config: DetectorConfig,
) -> list[dict[str, Any]]:
    """Return 0 or 1 revolve_solid feature dicts."""
```

Called from `_build_feature_graph` *before* plate/box detection. Rationale: if a mesh is axisymmetric, describing it as a plate (which a short-disk cylinder currently is) throws away information. The axisymmetry test is fast (one inertia-tensor diagonalization); cost of running it first is negligible.

Profile-classification (Phase 2) is a separate function `classify_revolve_profile(profile: list[tuple[float, float]]) -> str | None` in the same module. Keeping it separate from detection means Phase 1 can ship before Phase 2 exists, and Phase 2's tests can unit-test the classifier directly against hand-authored profiles without running a full mesh pipeline.

### New module: `stl2scad/core/extrude_recovery.py` (Phase 3)

Same shape, for linear-extrude detection. Deferred.

### Changes to `feature_graph.py`

1. Call `detect_revolve_solid` early in `_build_feature_graph` and short-circuit subsequent detectors if it fires with high confidence.
2. Add `revolve_solid` to `_TYPE_TO_IR_NODE` mapping.
3. Extend `_build_ir_tree` to wrap `revolve_solid` in `BooleanUnion { ExtrudeRevolve { ... } }` with the alignment transform.
4. Extend SCAD preview emitter dispatch to route `revolve_solid` to a new `_emit_revolve_scad_preview`.

### Changes to `detector_ir.md`

Update the status of `ExtrudeRevolve`, `Sketch2D`, `PrimitiveCone`, `PrimitiveSphere`, `PrimitiveEllipsoid` as Phase 1 and Phase 2 land. No new IR types needed — the tier-2 slots already exist.

### Changes to `feature_fixtures.py` and manifest

Add new fixture family `revolve`:

- `revolve_rectangle_profile` — 4-point profile → should classify as cylinder in Phase 2, emit as generic revolve in Phase 1.
- `revolve_triangle_profile` — 3-point profile → cone.
- `revolve_semicircle_profile` — arc → sphere.
- `revolve_christmas_tree` — sawtooth profile with 3-4 teeth → generic `rotate_extrude(polygon())` always (not a primitive).
- `revolve_vase` — smooth curved profile → generic polygon.
- `revolve_stepped_shaft` — staircase profile → generic polygon.
- `revolve_off_axis_z45` — any of the above rotated about a non-world-axis to validate axis-alignment transforms.

Each fixture's manifest entry carries:

- `profile`: the `(r, z)` points the generator draws and `rotate_extrude` sweeps.
- `axis`: revolution axis (world space).
- `expected_detection`: `revolve_solid: true`, plus for Phase 2 fixtures, the expected primitive classification (`cylinder` / `cone` / `sphere` / `frustum` / `polygon`).

Generator produces SCAD of the form:

```openscad
rotate_extrude($fn=128) polygon(points=[[r1,z1], [r2,z2], ...]);
```

optionally wrapped in a rotation transform for off-axis fixtures.

## Data flow

```
STL → mesh arrays
  → inertia tensor
    → axis candidate + axisymmetry confidence
      → radial slice → (r,z) polyline
        → Douglas-Peucker → profile polygon
          → [Phase 2] classify profile → cylinder/cone/sphere/frustum/polygon
            → IR: BooleanUnion { base: (Primitive|ExtrudeRevolve), transform: TransformRotate(axis) }
              → SCAD: primitive call OR rotate_extrude(polygon())
```

Same skeleton applies to linear-extrude in Phase 3 with "inertia tensor + slice" replaced by "slice-similarity along axis + cross-section polygon."

## Error handling & fall-through

Each gate fails closed — if any check doesn't pass its confidence threshold, the function returns `[]` and the caller continues to plate/box/polyhedron detection. The project's rule "conservative by design, 0.70 confidence threshold" applies here:

- Inertia ratio similarity below threshold → not axisymmetric, fall through.
- Radial slice produces a self-intersecting polygon → fall through.
- Profile fails to touch the axis → fall through (Phase 1 does not handle annular revolves; those require Phase 2's annular-rectangle branch).
- Profile has > N points after simplification (N ≈ 64) → likely organic, fall through to `FallbackMesh`.

## Testing strategy

**Phase 1:**

- Unit tests on inertia-tensor axisymmetry scoring with hand-constructed normal/area arrays.
- Unit tests on radial-slice profile extraction with hand-constructed meshes.
- Unit tests on Douglas-Peucker simplification with synthetic polylines.
- Round-trip fixture tests for every `revolve_*` fixture: manifest → SCAD → STL → detector → assertions on `revolve_solid` count, axis direction (within tolerance), profile point count (within ±1 after simplification).
- Negative tests: plate, box, l-bracket, and existing axis-aligned cylinder fixtures must NOT detect as `revolve_solid` with higher confidence than their native type. (A cylinder-along-Z *could* legitimately detect as both; the dispatch rule is that the existing axis-aligned `cylinder_like_solid` detector wins when both fire, to preserve existing fixture behavior.)

**Phase 2:**

- Unit tests on `classify_revolve_profile` with hand-authored profiles for every primitive class and a set of deliberately-ambiguous ones.
- Round-trip fixture tests extended to assert the profile classification when expected.

**Phase 3:**

- Translational-symmetry unit tests with extruded hand-constructed meshes.
- New `extrude_*` fixture family.

**All phases:**

- The three fixture invariants from [CLAUDE.md](../../../CLAUDE.md) stay intact: byte-exact fixture regeneration, dimensional round-trip, roadmap stress-case coverage. Phase 1 extends the stress-case list to include at least one `revolve` fixture.

## Open questions

- **Sphere detection is ambiguous on revolution axis.** A sphere is axisymmetric about *every* axis through its center. Phase 1 should accept any one axis; Phase 2's classifier should recognize the semicircle profile and emit `sphere()` regardless of which axis was chosen. This removes the ambiguity at the right layer.
- **What about near-axisymmetric parts?** A turned part with a single keyway cutout is ~95% axisymmetric. Phase 1 should reject it (the radial slice at the keyway angle produces a different polygon than a slice at a non-keyway angle; the symmetry test catches this). Recovering such parts as `rotate_extrude` + `difference()` is a Phase 4+ item.
- **SCAD `rotate_extrude` convention.** OpenSCAD revolves around the Z axis of the profile's local frame, with profile in the XZ plane (X=r, Z=z). Our axis-alignment transform must map the detected world-space axis onto profile-local Z. Implementation note, not a design question.

## Deferred / explicitly not in this spec

- Threading, knurling, decorative surface features on revolve bodies.
- Revolve-with-cutouts (keyway, flat-on-shaft). Phase 4+.
- 2D profiles with holes (gaskets with bolt circles). Phase 4+.
- Detecting `rotate_extrude(angle=<180)` — partial revolves.

## Success criteria

Phase 1 is complete when:

1. Every Phase 1 `revolve_*` fixture round-trips with its expected profile within tolerance.
2. A Christmas-tree-shaped input mesh emits a `rotate_extrude() polygon([...])` SCAD preview with fewer than 20 polygon points.
3. Existing axis-aligned fixtures (plate, box, cylinder) continue to pass — no regressions in established detectors.
4. Three fixture invariants remain intact.

Phase 2 is complete when:

1. Rectangle-profile fixtures upgrade to `cylinder()`, triangle-profile to `cone()`, semicircle to `sphere()`, trapezoid to `cylinder(d1, d2)`.
2. The Christmas-tree fixture stays as `rotate_extrude(polygon())` (its profile is not a classifiable primitive).
3. [detector_ir.md](../../planning/detector_ir.md) tier-1 cone/sphere/ellipsoid rows flip to "detected."
