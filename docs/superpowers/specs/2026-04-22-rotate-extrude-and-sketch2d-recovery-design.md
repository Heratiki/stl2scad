# Rotate-Extrude and Sketch2D Recovery — Design

## Status

- **Date:** 2026-04-22
- **Revision:** 2026-04-22 (r2) — robustness pass on dispatch rules, multi-slice validation, segment-based classification.
- **Target roadmap item:** supersedes most of "Beyond dimensional parity #4" in [feature_level_reconstruction.md](../../planning/feature_level_reconstruction.md), and absorbs parts of Immediate priority #1 (rotated/composite fixtures) and the tier-2 primitive expansion that was previously scoped as individual cone/sphere detectors.
- **IR target:** `ExtrudeRevolve` and `Sketch2D` nodes already defined in [detector_ir.md](../../planning/detector_ir.md). This spec makes them detectable.

## Motivation

Most real mechanical parts are "profile + operation" in design intent. A turned part is a 2D profile rotated around an axis. A gasket is a 2D profile extruded linearly. A Christmas-tree ornament, a bottle, a pulley, a lamp shade, a standoff with a flare, and a drinking glass are all solids of revolution — their *natural* parametric representation is one 2D polygon and one `rotate_extrude()`, not a stack of approximating cones.

The detector today approaches these meshes primitive-by-primitive. A cylinder detector fires on cylindrical sides. A cone detector (unbuilt) would fire on conical sides. A stacked-cone Christmas-tree reconstruction via a composition detector would require N primitives and (N−1) union operations. The `rotate_extrude` representation is one node and produces editable output that responds correctly to design-intent edits ("make the tree taller" = change one parameter, not N).

Critically, **axisymmetry detection subsumes single-primitive rotated detection**. A cylinder is a solid of revolution whose profile is a rectangle. A cone is one whose profile is a triangle. A sphere is one whose profile is a semicircle. Building the axisymmetric pipeline and later *classifying the profile shape* to upgrade the emission to `cylinder()` / `cone()` / `sphere()` is a single coherent dispatch instead of three separate detectors with overlapping signal.

## Dispatch rules (architecture-level invariants)

These rules govern how revolve recovery interacts with existing detectors and with future higher-level detectors. They are invariants; every later section of the spec must respect them.

### Rule 1 — Revolve recovery runs early, by *specific* warrant

`detect_revolve_solid()` is called from `_build_feature_graph` before plate / box / cylinder detection. This ordering is **not** a general architectural precedent that future higher-level detectors inherit automatically. It is justified narrowly by the following:

> *Axisymmetric meshes arrive with design intent that primitive-first detection actively destroys.* A short disk classifies as a thin plate today; recovering it as a plate discards the fact that its true parametric representation is a cylinder (and later, via Phase 2, a `cylinder()` primitive). A Christmas tree classifies as nothing today; a composition detector would recover it as N cones, which is verbose and brittle under design edits. In both cases, running the revolve recovery first captures intent that the downstream primitive pipeline cannot.

### Rule 2 — Future `extrude_recovery` does *not* inherit Rule 1

When Phase 3 (linear-extrude recovery) lands, it must **not** be placed ahead of native primitive detection by default. Rationale: many native primitives are *also* valid linear extrusions — a cube is a square extruded, a cylinder is a circle extruded, a box with a hole is a rectangle-with-hole extruded. Emitting `cube([x, y, z])` is more readable than `linear_extrude(z) square([x, y])`, and design-intent is not *destroyed* by primitive-first dispatch the way it is for revolves (the primitive representation is itself editable and parametric). Phase 3 should run *after* plate / box / cylinder detection and fire only when no native primitive matched.

### Rule 3 — One detector path owns emission per feature

Once a detector accepts a mesh region (or the whole mesh) as its own, downstream detectors do not re-claim the same region. In particular:

- If `detect_revolve_solid()` accepts with high confidence, plate / box / cylinder detection is skipped for the same mesh body.
- If `detect_revolve_solid()` rejects (any gate fails), control passes cleanly to the existing pipeline; no revolve-related metadata lingers on features produced by later detectors.
- The emitter receives exactly one feature tree per mesh body. Revolve and cylinder do not both produce a feature dict for the same geometry.

### Rule 4 — Native primitive wins over generic polygon revolve

When a validated revolve profile classifies (Phase 2) to a native primitive (cylinder, cone, sphere, frustum, annular tube) with confidence above the native-primitive threshold, the emitter produces the native primitive call (`cylinder()`, `sphere()`, etc.) rather than the generic `rotate_extrude() polygon([...])` form. The generic revolve is the fall-through for profiles that do *not* classify — Christmas-tree sawtooth, vase curves, stepped shafts, baluster contours.

This is a *dispatch* rule, not a quality optimization: the native form is more readable, more editable, and round-trips more cleanly through human editors. `rotate_extrude(polygon())` is always correct but is only the right emission when nothing simpler applies.

## Phased Plan

This work is scoped as four phases. Phase 1 delivers Christmas-tree-level output end-to-end without any primitive recognition. Each subsequent phase builds on 1 and can land independently.

### Phase 1 — Axisymmetric detection + `rotate_extrude` emission

Goal: any rotationally symmetric mesh whose radial profile touches the axis at least once produces a `rotate_extrude() polygon([...])` SCAD preview that round-trips within tolerance.

Phase 1 is intentionally conservative about what it accepts. The pipeline is a sequence of independent gates; failure at any gate returns `[]` and passes control to downstream detectors. No gate is decisive on its own.

#### 1.1 Candidate-axis generation (prefilter)

Compute the inertia tensor of the mesh and diagonalize it. A solid of revolution has two equal principal moments (perpendicular to the axis) and one distinct principal moment (along the axis). This is **treated strictly as a candidate-axis generator and a coarse prefilter** — it is not proof of revolve intent. Balanced-but-not-revolved objects (a square extrusion, a cube, an equilateral prism, a two-lobed symmetric composite) can pass this screen and must be rejected downstream.

Output of this stage: up to one candidate revolution axis (the principal direction with distinct eigenvalue) plus a scalar `axis_quality` score based on the ratio separation of the principal moments. If no axis meets the minimum `axis_quality` threshold, return `[]`.

#### 1.2 Multi-slice profile recovery and consistency gate

For the candidate axis, sample K half-planes containing the axis at uniformly-spaced angular positions (target K ≥ 8 for Phase 1; the exact number is a config knob). Each half-plane produces a polyline by intersecting the mesh surface with that half-plane and projecting into the axis's local (r, z) frame.

Every recovered slice must:

1. Produce a simple (non-self-intersecting) polyline.
2. Touch the axis (r = 0) at least once. (Annular revolves are excluded from Phase 1 — see §1.5.)
3. Agree with the other slices within a per-point r-coordinate tolerance scaled to mesh size, after sorting by z.

Cross-slice agreement is the dominant robustness gate. It is the signal that distinguishes a true solid of revolution from a balanced composite. A keyway-bearing shaft produces one slice with a notch and several slices without; cross-slice disagreement at the keyway z-range exceeds tolerance; the detector rejects cleanly.

If all K slices pass, aggregate them into a single representative profile. Two acceptable strategies, pick one in implementation: (a) median r at each sampled z across the K slices, or (b) the slice closest to the per-z median under a per-point L² score. (a) is more robust to outliers; (b) preserves real mesh vertices. The spec does not mandate one — both produce a valid `profile` field.

Simplify the aggregated profile via Douglas-Peucker with tolerance tied to characteristic mesh size.

Output of this stage: a candidate `(r, z)` polygon plus a scalar `cross_slice_consistency` score (mean residual / mesh-size).

#### 1.3 Normal-field agreement gate

For the candidate axis and the aggregated profile, compute the expected face-normal field: at each surface point, the expected normal lies in the plane spanned by the axis and the local radial direction, with no circumferential component. Score the actual mesh face-normals against this field (area-weighted dot product).

A mesh that passed §1.1 and §1.2 but fails this gate is an edge case — it can happen on meshes with degenerate triangulation or aggressive smoothing that shifted normals off the revolve surface. Reject and fall through.

Output: a scalar `normal_field_agreement` score.

#### 1.4 Profile validity gate

The aggregated profile must be:

- Simple (non-self-intersecting).
- Closed when swept (first and last points lie on r = 0, or the profile forms a closed loop in (r, z) that touches r = 0).
- Have at most `max_profile_vertices` points after simplification (default 64). Profiles beyond this are likely organic and should fall through to `FallbackMesh`.

Output: a scalar `profile_validity` score (e.g. 1.0 if all checks pass, 0.0 otherwise — this is a gate, not a graded metric).

#### 1.5 Acceptance and feature emission

The feature is accepted only when every gate passes. The emitted dict is:

```python
{
    "type": "revolve_solid",
    "axis": [x, y, z],               # unit vector, world space
    "axis_origin": [ox, oy, oz],     # point on axis, world space
    "profile": [(r1, z1), (r2, z2), ...],
    "confidence": <scalar>,
    "confidence_components": {
        "axis_quality":            float,
        "cross_slice_consistency": float,
        "normal_field_agreement":  float,
        "profile_validity":        float,
    },
    "detected_via": "axisymmetric_revolve",
}
```

The top-level `confidence` is computed from the named sub-signals (e.g. min or geometric mean) but the **named sub-signals are preserved in the feature dict** so that threshold tuning, debugging, and fixture diagnostics can inspect each gate independently. This is deliberate: one opaque scalar hides which gate is marginal on a given mesh.

IR wrapping:

```
BooleanUnion {
  base: TransformRotate(axis_alignment) {
    ExtrudeRevolve {
      profile: Sketch2D(polygon)
    }
  }
}
```

where `axis_alignment` rotates the detected world-space axis onto OpenSCAD's `rotate_extrude` convention (Z axis, profile in XZ plane).

#### 1.6 Phase 1 explicitly excludes — follow-on priorities

- **Annular revolves** (profile does not touch the axis — tubes, sleeves, bushings, cup-like forms). *These are common mechanical inputs and are an immediate follow-on priority; they should land shortly after Phase 1, not as a distant deferred enhancement.* The detection pipeline above handles the multi-slice consistency correctly for annular profiles; the only Phase 1 gate they fail is §1.2's "touches the axis" check. Relaxing that check and adding the annular-specific emission path (`difference() { cylinder(outer); cylinder(inner); }` or a named `tube(...)` module) is the natural next slice of work after Phase 1 ships.
- **Partial revolves** (`rotate_extrude(angle < 360)`). Deferred.
- **Near-axisymmetric parts with a keyway or flat.** The multi-slice gate correctly rejects these in Phase 1. Recovering them as `rotate_extrude() + difference()` is a Phase 4+ item.

### Phase 2 — Profile classification → native primitive upgrade

Goal: when a validated revolve profile from Phase 1 classifies as a known parametric shape, the emitter upgrades from `rotate_extrude(polygon())` to the corresponding native primitive. This is where cone / sphere / frustum come online as a consequence of the axisymmetric pipeline.

#### 2.1 Local structured profile representation (not a global IR node)

Phase 2 does **not** add a new global IR node for structured profiles. Instead, it introduces a local, internal representation that lives inside `revolve_recovery.py` and exists only long enough for classification:

- `LineSegment2D { start: (r, z), end: (r, z) }`
- `ArcSegment2D { start: (r, z), end: (r, z), center: (r, z), radius: float, sweep_direction: {cw, ccw} }`

The Phase 1 output (a list of `(r, z)` points) is fed into a segment-fitting step that greedily groups consecutive points into line and arc fits with per-segment residual scaled to mesh size. The output is an ordered list of `LineSegment2D` / `ArcSegment2D` — a **segment graph** of the profile.

This representation is more tolerant to tessellation noise than raw vertex-count logic: a tessellated semicircle has 8-32 line-segment vertices depending on mesh resolution, but it is one `ArcSegment2D` under segment fitting.

#### 2.2 Classification against the segment graph

Primitive classification matches the segment graph against canonical templates:

| Native primitive | Segment graph template |
| --- | --- |
| `cylinder(h, d)` | 3 line segments: axis-touching base, radial cap, axial side (or the mirrored form). |
| `cone(h, d)` | 2 line segments plus an axis closure: axis-touching base + slanted side meeting the axis at the apex. |
| `frustum(h, d1, d2)` | 3 line segments plus axis closure: two parallel radial caps at different r, connected by a slanted side. |
| `sphere(r)` | 1 `ArcSegment2D` from (0, −r) to (0, +r) through (r, 0). |
| `ellipsoid(rx, ry)` | 1 `ArcSegment2D` with unequal axes (elliptic arc). |
| `tube(h, outer_d, inner_d)` | 4 line segments, no axis touching — the annular case from §1.6 once that lands. |

Classification tolerances scale to mesh size. A match produces a classification string (`"cylinder"`, `"cone"`, `"sphere"`, ...) with its own confidence score, which is carried alongside the Phase 1 sub-signals.

Raw point-count heuristics can remain as secondary filters (e.g. "a classified cylinder must have ≤ 4 profile points after simplification") but they are **not** the primary classification strategy. A raw-point-count-first approach would mis-classify tessellation-noisy profiles and miss arc-based primitives entirely.

#### 2.3 Emitter dispatch

Per Rule 4: if classification succeeds above the native-primitive threshold, the SCAD emitter produces the native call. If classification falls through (a Christmas-tree sawtooth, a vase curve, a stepped shaft), the emitter produces `rotate_extrude() polygon([...])`.

Phase 2 flips [detector_ir.md](../../planning/detector_ir.md) tier-1 rows for `PrimitiveCone`, `PrimitiveFrustum`, `PrimitiveSphere`, and `PrimitiveEllipsoid` from "not detected" to "detected via revolve profile classification."

### Phase 3 — Linear extrude detection

Goal: meshes with constant cross-section along an axis produce `linear_extrude(h) polygon([...])`.

Components:

1. **Translational-symmetry test.** For a candidate axis, take perpendicular slices at multiple heights and compare them (Fréchet or Hausdorff distance on the 2D outlines). Multi-slice consistency is the same robustness pattern as Phase 1 §1.2.
2. **Cross-section extraction.** Project an aggregated slice into the (u, v) local plane of the axis and simplify.
3. **Segment-graph classification.** Apply the same `LineSegment2D` / `ArcSegment2D` fitting and template matching as Phase 2, but over 2D cross-section polygons instead of (r, z) profiles. This lets `linear_extrude(square(...))` → `cube()`, `linear_extrude(circle(...))` → `cylinder()`, and so on.
4. **IR emission.** `BooleanUnion { base: ExtrudeLinear { profile: Sketch2D(polygon), height, axis_transform } }`.
5. **SCAD emitter.** `linear_extrude(h) polygon(...)` wrapped in alignment transform, **only when** the segment-graph classifier does not match a native primitive. Per Rule 2, Phase 3 runs *after* plate / box / cylinder detection and only fires if nothing native claimed the mesh. Per Rule 4, native primitive wins over generic `linear_extrude(polygon())`.

Out of scope for Phase 3: twist, scale taper (`linear_extrude(scale=...)` support), non-convex profiles with holes. Deferred to Phase 4 or later.

### Phase 4 — Composition / stacked detector

Goal: meshes that are *neither* single-axis-revolved *nor* single-axis-extruded but are a *composition* of such objects along a shared axis, unioned together. Example: a stepped shaft, a boss on a plate, a Christmas tree reinterpreted as stacked cones.

Approach (sketch, subject to revision before Phase 4 starts): segment the mesh along the candidate axis into regions of locally-constant symmetry class, run Phase 1 / 3 detectors on each segment, emit as `union()` of the segmented results.

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
    """Return 0 or 1 revolve_solid feature dicts.

    Runs the full gate sequence from §1.1–§1.5. Returns [] if any gate
    fails. Returns a one-element list with confidence_components filled
    in when every gate passes.
    """
```

Called from `_build_feature_graph` **before** plate / box / cylinder detection (per Rule 1). The axisymmetry prefilter (§1.1) is fast (one inertia-tensor diagonalization); cost of running it first is negligible. The full gate sequence is only exercised when the prefilter passes.

Phase 2 classification lives in the same module:

```python
def fit_profile_segments(
    profile: list[tuple[float, float]],
    mesh_scale: float,
) -> list[Segment2D]: ...

def classify_revolve_profile(
    segments: list[Segment2D],
    mesh_scale: float,
) -> tuple[str | None, float]:  # (primitive_name, confidence)
    ...
```

Keeping segment fitting and classification as distinct functions means Phase 1 can ship before Phase 2 exists, and Phase 2's tests can unit-test segment fitting and the classifier directly against hand-authored profiles without running a full mesh pipeline.

### New module: `stl2scad/core/extrude_recovery.py` (Phase 3)

Same shape, for linear-extrude detection. Runs *after* plate / box / cylinder detection per Rule 2. Deferred.

### Changes to `feature_graph.py`

1. Call `detect_revolve_solid` early in `_build_feature_graph` and short-circuit subsequent detectors when it accepts (per Rules 1 and 3).
2. Add `revolve_solid` to `_TYPE_TO_IR_NODE` mapping.
3. Extend `_build_ir_tree` to wrap `revolve_solid` in `BooleanUnion { TransformRotate { ExtrudeRevolve { ... } } }` with the axis-alignment transform.
4. Extend SCAD preview emitter dispatch to route `revolve_solid` to a new `_emit_revolve_scad_preview`. Per Rule 4, the emitter checks the Phase 2 classification result (if present) and emits the native primitive call, otherwise emits `rotate_extrude(polygon())`.

### Changes to `detector_ir.md`

Update the status of `ExtrudeRevolve`, `Sketch2D`, `PrimitiveCone`, `PrimitiveFrustum`, `PrimitiveSphere`, `PrimitiveEllipsoid` as Phase 1 and Phase 2 land. No new global IR types needed — the tier-2 slots already exist, and the `LineSegment2D` / `ArcSegment2D` representation is local to `revolve_recovery.py` and does not appear in feature-graph JSON output.

### Changes to `feature_fixtures.py` and manifest

Add new fixture family `revolve`:

Phase 1 positive fixtures:

- `revolve_rectangle_profile` — 4-point profile → generic revolve in Phase 1, classifies as cylinder in Phase 2.
- `revolve_triangle_profile` — 3-point profile → generic revolve in Phase 1, cone in Phase 2.
- `revolve_semicircle_profile` — arc → generic revolve in Phase 1, sphere in Phase 2.
- `revolve_christmas_tree` — sawtooth profile with 3-4 teeth → generic `rotate_extrude(polygon())` always (not a primitive).
- `revolve_vase` — smooth curved profile → generic polygon.
- `revolve_stepped_shaft` — staircase profile → generic polygon.
- `revolve_off_axis_z45` — any of the above rotated about a non-world-axis to validate axis-alignment transforms.

Phase 1 negative fixtures (expected to be rejected — see also Testing §below):

- `non_revolve_cube` — passes inertia screening as a degenerate case; must fail cross-slice consistency.
- `non_revolve_symmetric_composite` — e.g. two mirrored bosses on a plate; balanced inertia tensor but clearly not a revolve.
- `non_revolve_shaft_with_keyway` — near-axisymmetric everywhere except a single angular slot; must fail cross-slice consistency at the keyway z-range.
- `non_revolve_square_prism` — square extrusion; balanced inertia about the extrude axis but cross-slice polyline is a square at every angle, not a radial profile.

Each positive fixture's manifest entry carries:

- `profile`: the `(r, z)` points the generator draws and `rotate_extrude` sweeps.
- `axis`: revolution axis (world space).
- `expected_detection`: `revolve_solid: true`, plus for Phase 2 fixtures, the expected primitive classification (`cylinder` / `cone` / `sphere` / `frustum` / `polygon`).

Each negative fixture's manifest entry carries:

- `expected_detection`: `revolve_solid: false`, plus an optional `expected_rejection_gate` field (`"cross_slice_consistency"`, `"profile_validity"`, etc.) so round-trip tests can assert *why* the detector rejected, not just that it did.

Generator produces SCAD of the form:

```openscad
rotate_extrude($fn=128) polygon(points=[[r1,z1], [r2,z2], ...]);
```

optionally wrapped in a rotation transform for off-axis fixtures.

## Data flow

```
STL → mesh arrays
  → inertia tensor → candidate axis + axis_quality      [§1.1 prefilter]
    → K radial slices → K (r,z) polylines               [§1.2]
      → cross-slice consistency gate                    [§1.2]
        → aggregate + Douglas-Peucker → profile polygon [§1.2]
          → normal-field agreement gate                 [§1.3]
            → profile validity gate                     [§1.4]
              → [Phase 2] segment fit → classification  [§2.1 / §2.2]
                → IR: BooleanUnion { TransformRotate { ExtrudeRevolve | Primitive } }
                  → SCAD: native primitive OR rotate_extrude(polygon())
```

Same skeleton applies to linear-extrude in Phase 3 with "inertia tensor + K radial slices" replaced by "K perpendicular slices along the candidate extrude axis + slice-similarity," and Phase 3 running *after* plate / box / cylinder detection per Rule 2.

## Error handling & fall-through

Each gate fails closed — if any check doesn't pass its threshold, the function returns `[]` and the caller continues to plate / box / polyhedron detection. The project's rule "conservative by design, 0.70 confidence threshold" applies here, but the revolve detector is stricter than most because its sub-signals are independent and each is a hard gate:

- §1.1 `axis_quality` below threshold → not axisymmetric under inertia; fall through.
- §1.2 any slice self-intersects, or profiles disagree beyond tolerance → fall through.
- §1.2 any slice fails to touch the axis → fall through (Phase 1 excludes annular; see §1.5).
- §1.3 normal-field agreement below threshold → fall through.
- §1.4 profile has > `max_profile_vertices` points after simplification → likely organic; fall through to `FallbackMesh`.

`confidence_components` is preserved on the feature dict even on acceptance, so ambiguous cases (all gates passed marginally) are visible in JSON output rather than hidden behind one scalar.

## Testing strategy

**Phase 1 — positive:**

- Unit tests on inertia-tensor `axis_quality` scoring with hand-constructed normal / area arrays.
- Unit tests on multi-slice profile extraction — sliced hand-constructed meshes must produce expected (r, z) polylines per slice.
- Unit tests on cross-slice consistency scoring — hand-constructed matching and deliberately-disagreeing slice sets.
- Unit tests on Douglas-Peucker simplification with synthetic polylines.
- Round-trip fixture tests for every positive `revolve_*` fixture: manifest → SCAD → STL → detector → assertions on `revolve_solid` count, axis direction (within tolerance), profile point count (within ±1 after simplification), and `confidence_components` all above per-gate thresholds.

**Phase 1 — negative (symmetry-without-revolve):**

This is where the cross-slice consistency gate earns its complexity. The following must *not* detect as `revolve_solid`, and the round-trip test should assert which gate caught them:

- `non_revolve_cube` — inertia tensor is degenerate (three equal moments); §1.1 may pass or the prefilter's tie-breaker picks any axis; §1.2 must catch it (cross-slice disagreement — a cube sliced radially produces different polylines at 0°, 45°, 90°).
- `non_revolve_square_prism` — balanced about the extrude axis; §1.1 passes; §1.2 fails because the radial slice at 0° is a rectangle different from the slice at 45°.
- `non_revolve_symmetric_composite` — two bosses on a plate, symmetric about a vertical axis; §1.1 may pass; §1.2 fails because slices through the bosses differ from slices between them.
- `non_revolve_shaft_with_keyway` — near-axisymmetric cylinder with a single axial keyway; §1.1 passes easily; §1.2 fails at the keyway z-range.
- Existing axis-aligned plate, box, l-bracket fixtures must NOT detect as `revolve_solid`. Plates will fail §1.1 or §1.2; boxes as above; l-brackets fail §1.1.
- Existing axis-aligned cylinder fixtures *will* detect as `revolve_solid` in Phase 1 — this is correct and desired (a cylinder *is* a revolve). Per Rule 3, when revolve detection fires, cylinder detection is skipped, so there is no double-counting. The round-trip test must confirm this: the feature list contains one `revolve_solid` and zero `cylinder_like_solid` for Phase 1 cylinder fixtures. In Phase 2, the profile classifies as `cylinder` and the emitter produces `cylinder()`, preserving existing fixture output at the SCAD-emission level.

**Phase 2:**

- Unit tests on `fit_profile_segments` with hand-authored (r, z) polylines — a 32-vertex tessellated semicircle must fit to one `ArcSegment2D`; a 4-vertex rectangle to 3 `LineSegment2D`.
- Unit tests on `classify_revolve_profile` with hand-authored segment graphs for every primitive class and a set of deliberately-ambiguous ones (e.g. a frustum with nearly-equal radii that should still classify as frustum, not cylinder).
- Round-trip fixture tests extended to assert the profile classification when expected.

**Phase 3:**

- Translational-symmetry unit tests with extruded hand-constructed meshes.
- Multi-slice consistency negative tests analogous to Phase 1's — twisted extrudes must fail translational consistency.
- New `extrude_*` fixture family.

**All phases:**

- The three fixture invariants from [CLAUDE.md](../../../CLAUDE.md) stay intact: byte-exact fixture regeneration, dimensional round-trip, roadmap stress-case coverage. Phase 1 extends the stress-case list to include at least one `revolve` positive fixture and at least one `non_revolve_*` negative fixture.

## Open questions

- **Sphere detection is ambiguous on revolution axis.** A sphere is axisymmetric about *every* axis through its center. §1.1 can accept any one axis; §1.2's multi-slice check confirms revolve intent regardless of which axis was chosen; §2.2's semicircle template matches regardless of orientation. The ambiguity is handled structurally — no special-case code needed.
- **What K for multi-slice sampling?** A config knob, default K = 8. Larger K catches narrower keyways at the cost of per-mesh time. Tunable per fixture if needed.
- **Aggregation strategy choice** (median r vs closest-slice) is left to implementation; both satisfy the spec.
- **SCAD `rotate_extrude` convention.** OpenSCAD revolves around the Z axis of the profile's local frame, with profile in the XZ plane (X = r, Z = z). The `TransformRotate` in the IR must map the detected world-space axis onto profile-local Z. Implementation note, not a design question.

## Deferred / explicitly not in this spec

- Threading, knurling, decorative surface features on revolve bodies.
- Revolve-with-cutouts (keyway, flat-on-shaft). Phase 4+.
- 2D profiles with holes in `linear_extrude` (gaskets with bolt circles). Phase 4+.
- Detecting `rotate_extrude(angle < 360)` — partial revolves.
- Detecting twist / taper in linear extrudes.

## Immediate follow-on after Phase 1

**Annular revolves (tubes, sleeves, bushings, cups)** are deliberately excluded from Phase 1 by the "profile must touch the axis" gate in §1.4, but they are **not** a distant future item. They are common mechanical inputs and should land shortly after Phase 1 ships. The required changes are bounded: relax the axis-touching gate for profiles whose (r, z) trace forms a closed non-axis-touching loop, add an annular emission path (`difference() { cylinder(outer); cylinder(inner); }` as a fallback; named `tube(h, outer_d, inner_d)` module under Phase 2's classifier), and add matching fixtures.

## Success criteria

Phase 1 is complete when:

1. Every Phase 1 positive `revolve_*` fixture round-trips with its expected profile within tolerance, and every Phase 1 negative `non_revolve_*` fixture is rejected with the expected gate identified in `expected_rejection_gate`.
2. A Christmas-tree-shaped input mesh emits a `rotate_extrude() polygon([...])` SCAD preview with fewer than 20 polygon points.
3. Existing axis-aligned fixtures (plate, box, l-bracket) continue to pass — no regressions in established detectors. Existing cylinder fixtures emit `cylinder()` via Phase 2, or `rotate_extrude(polygon())` if only Phase 1 has shipped (see Rule 3 / Rule 4 dispatch).
4. `confidence_components` is present on every accepted `revolve_solid` feature dict.
5. The three fixture invariants remain intact.

Phase 2 is complete when:

1. Rectangle-profile fixtures upgrade to `cylinder()`, triangle-profile to `cone()`, semicircle to `sphere()`, trapezoid to frustum via `cylinder(d1, d2)`.
2. The Christmas-tree fixture stays as `rotate_extrude(polygon())` (its profile is not a classifiable primitive).
3. Tessellation-noisy profile variants (e.g. a semicircle discretized at 16, 32, 64 vertices) all classify as sphere — segment fitting handles the noise; classification does not regress as mesh resolution changes.
4. [detector_ir.md](../../planning/detector_ir.md) tier-1 cone / frustum / sphere / ellipsoid rows flip to "detected via revolve profile classification."
