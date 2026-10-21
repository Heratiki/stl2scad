# Plan 1: Defeature, Slabs and Hybrid Remainder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-pass step 4 with regularize → defeature → slab slicing → replay, so that chamfers, convex edge rounds, clipped profile arcs, rib ends and stepped extrusions come out parametric, and a region that is not explained passes as a polyhedron region (max 10 % of the surface).

**Architecture:** New modules beside the current step 4. `regularize.py` snaps near-parallel directions. `defeature.py` removes chamfers and edge rounds from the face graph relative to the extrusion axis. `slabs.py` finds cap levels and builds one 2D profile per slab from the analytic side faces (mesh section points where a side face is not analytic). `remainder.py` turns unexplained faces into closed polyhedron regions. `detect_features` dispatches to the new path when the old path cannot explain the part. The old path stays for parts it already explains (regression fence).

**Tech Stack:** Python 3.14, numpy, numpy-stl, networkx, trimesh (closest points only), OpenSCAD nightly for render and booleans. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-20-edge-rounds-design.md` (goals 1–7 and the hybrid remainder). Research: `docs/research/2026-10-20-argon-reconstruction-methods.md` sections A, B, Q2, Q3. Plan 2 (ellipse, round along a curved edge) and plan 3 (screw features) follow.

## Global Constraints

- Do not edit `stl2scad/core/feature_graph.py`, `tests/data/feature_fixtures_manifest.json` or `tests/data/feature_fixtures_scad/`.
- Do not change the gate limit `max(0.05 mm, 0.1 % of bbox diagonal)`, the test tolerances (`plane_normal_deg 1.0`, `plane_offset_mm 0.05`, `cylinder_axis_deg 1.0`, `cylinder_radius_rel 0.02`, `volume_rel 0.001`) or `SNAP_MAX_SHIFT_MM = 1e-3`.
- No `logging.basicConfig` in library code.
- Parameter names: `<kind>_<index>_<dim>`, index from 1: `chamfer_<n>_width`, `edge_round_<n>_radius`, `corner_<n>_radius` (2D profile corner, rib end, clipped profile arc), `step_<n>_height`.
- Customizer: `/* [Group] */` headings, `// [min:step:max]` ranges, `assert()` for linked limits, face provenance comments `// face F<n> ...`.
- Free-form limit: if unexplained faces exceed 10 % of the surface area, the full part is a polyhedron (as today).
- Polyhedron regions stay fixed in the body frame; they do not follow slider changes.
- Symmetric chamfers only. An asymmetric chamfer is reported by name, never emitted as `chamfer_<n>_width`.
- `.gitignore` ignores `*.json` and most `.scad`: add a `!` rule for each new data file; check with `git status -uall`.
- Baseline: 311 passed, 3 failed (`revolve_triangle_profile`). No new failure.
- Test command (headless): `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest <tests> -n auto -q -o addopts="" -p no:logging`.
- Lanes do not commit. Claude verifies each task with its own commands and commits.

## Review Focus

1. **A part the old path already explains** (stencil-like plate, composite bracket, rounded plate): the output must not change. Test: Task 5 `test_old_path_parts_keep_their_output`.
2. **A synthetic round or chamfer that comes out as a remainder region** (lazy label): must fail. Test: Task 6 `test_supported_treatments_never_become_remainder`.
3. **A slider at its range limit** (round radius ≥ the smaller adjacent face width, chamfer width ≥ the plate thickness): render must stop with an assert, not give a broken solid. Test: Task 6 `test_treatment_limits_stop_render`.
4. **Coarse facets** (`$fn = 16`) on an edge round and a rib end: segments and phase must be emitted so the gate passes. Covered by the `coarse` variants in Tasks 1, 3, 4, 6.
5. **An edge treatment on an edge that is oblique in the part frame** (not parallel to a cap or a side): must not be labeled a chamfer or round; it goes to the remainder or fallback. Test: Task 3 `test_oblique_edge_is_not_a_treatment`.

---

### Task 1: Synthetic ground truth

**Files:**
- Create: `tests/data/segmentation/chamfered_block.scad`, `edge_round_block.scad`, `clipped_arc_plate.scad`, `stepped_bar.scad`, `dome_plate.scad`, `asymmetric_chamfer_block.scad`, plus `<name>_rotated.scad` and `<name>_fn16_rotated.scad` for the first four, and `dome_plate_large.scad`
- Create: `tests/data/segmentation/treatments_expected.json`
- Create: `tests/test_segmentation_treatments_truth.py`
- Modify: `.gitignore` (add `!tests/data/segmentation/<name>*.scad` for each name and `!tests/data/segmentation/treatments_expected.json`)

**Interfaces:**
- Produces: `treatments_expected.json` with one entry per part: `name`, `variants` (same schema as `rounded_plate_expected.json`: `scad`, `rotate_deg [17,31,9]`, `translate_before`, `tessellation`, `volume_mm3`), `faces`, `edges`, `features` (kind, dims, faces), `parameters` (Customizer name → value), `tolerances` (copy of the rounded-plate values). Each part SCAD has top-level variables for its design values, so a test can render it with `-D name=value`.

Parts (all in the part frame, mm, extrusion axis Z, `$fn = 64` unless coarse):

| Name | Geometry | Expected features |
|---|---|---|
| `chamfered_block` | cube 60 × 40 × 8; symmetric 45° chamfer, width 2, on both top long edges (along X, full length) | body rectangle 60 × 40 h 8; `chamfer_1_width` 2, `chamfer_2_width` 2 |
| `edge_round_block` | cube 60 × 40 × 10; convex round R3 on the top front edge (along X, full length); symmetric 45° chamfer width 1.5 on the top back edge | body; `edge_round_1_radius` 3; `chamfer_1_width` 1.5 |
| `clipped_arc_plate` | 40 × 20 rectangle with four R3 corners, extruded 10; a 45° chamfer width 2 along the full bottom front edge (y = 0, z = 0), extended in X past the part so it also cuts the two front corner arcs | body rounded rectangle, `corner_1..4_radius` 3; `chamfer_1_width` 2 |
| `stepped_bar` | bar 30 × 6 h 2; head 6 × 6 h 10 at x ∈ [24, 30] with R1 vertical corners on its free end; rib 1 wide, x ∈ [4, 24], centred on the bar, h 10, half-round R0.5 ends | 3 levels (0, 2, 10); `step_1_height` 2, `step_2_height` 10; head corners `corner_<n>_radius` 1; rib ends `corner_<n>_radius` 0.5 |
| `dome_plate` | 60 × 40 × 4 plate; on the top, an ellipsoid half-dome, semi-axes 6 × 4 × 3 at (30, 20, 4) | body parametric; one additive remainder, share < 10 % |
| `dome_plate_large` | same plate; ellipsoid half-dome 28 × 18 × 10 | free-form share > 10 % → full polyhedron |
| `asymmetric_chamfer_block` | cube 60 × 40 × 8; top front edge cut with setbacks 2 (on top) and 4 (on front) | body; no chamfer parameter; one remainder region named "asymmetric chamfer" |

- [ ] **Step 1: Write `test_segmentation_treatments_truth.py`** with, for each part and variant: `test_faceted_volume_formula` (closed-form volume of the faceted solid from the face counts, `abs=1e-9` against the JSON, and the rendered mesh volume within `volume_rel`), `test_expected_planes_have_mesh_support` (as in `test_segmentation_rounded_plate.py`), `test_ground_truth_references_are_consistent` (face ids unique, every edge references known faces, every face owned by exactly one feature). Reuse `_rotation` and `openscad_path` from `tests/test_segmentation_bracket.py`.
- [ ] **Step 2: Run it to see it fail** (missing files). Expected: FAIL, file not found.
- [ ] **Step 3: Write the SCAD files and the JSON by hand.** Derive each volume formula in a comment in the test (polygon area `n r² sin(2π/n) / 2` for faceted arcs; chamfer prism `w² / 2 · length`). The ellipsoid dome volume uses the rendered mesh only (no closed form); mark that part `volume_mm3: null` and test only `volume > plate volume`.
- [ ] **Step 4: Run** `tests/test_segmentation_treatments_truth.py`. Expected: all PASS.
- [ ] **Step 5: Check the data files are tracked:** `git status -uall tests/data/segmentation` lists every new file. Commit: `test: add synthetic ground truth for chamfers, edge rounds, steps and free-form domes`.

### Task 2: Regularize directions

**Files:**
- Create: `stl2scad/core/segmentation/regularize.py`
- Test: `tests/test_segmentation_regularize.py`

**Interfaces:**
- Produces: `regularize(result: SegmentationResult, *, max_deg: float = 0.5) -> SegmentationResult` — same face ids, `triangle_indices`, `graph` and `mesh`; plane normals and cylinder axes that are within `max_deg` of each other (or of the opposite direction) get the area-weighted mean direction; the up-to-three dominant directions that are within `max_deg` of 90° to each other are made exactly orthogonal (Gram–Schmidt, largest area first). Each plane keeps its least-squares offset for the new normal; each cylinder is re-fitted with the axis fixed.
- Produces: `extrusion_axis(result: SegmentationResult) -> np.ndarray` — among the dominant plane-normal directions `d`, the one that minimizes the **unexplained area**: the area of faces that are neither a cap (plane normal ∥ d), nor a side (plane normal ⟂ d, or cylinder axis ∥ d), nor a candidate treatment (a plane, or a convex cylinder with axis ⟂ d, that is adjacent to one cap and one side). Ties (within 1 % of the total area) go to the larger cap area. A full-circle cylinder (boss, blind hole, through hole) with its end caps counts as explained for any `d`. A cylinder is a candidate treatment only when it is tangent to one cap and one side (not to two caps, as a rib end is when `d` lies across the rib). (Changed 2026-10-20 after Task 2: the first rule, "maximize cap + side area", picked X for the chamfered blocks, because chamfers along X are sides of an X extrusion.)

- [ ] **Step 1: Write tests.** `test_regularize_makes_bracket_directions_exact`: on the rotated composite bracket, every pair of plane normals has an angle in {0°, 90°, 180°} within 1e-9°, every face id is unchanged, and `hausdorff_to_mesh(detect_features(regularized), mesh)` stays < 0.05 mm. `test_regularize_leaves_distinct_directions`: two planes 2° apart keep their normals (within 1e-12). `test_extrusion_axis_of_treatment_parts`: Z (in the part frame, rotated back) for every Task 1 part and variant.
- [ ] **Step 2: Run, expect FAIL** (module missing).
- [ ] **Step 3: Implement** the two functions.
- [ ] **Step 4: Run** the new tests and `tests/test_segmentation_*.py`. Expected: new tests PASS; the old ones unchanged.
- [ ] **Step 5: Commit** `feat: regularize fitted directions and find the extrusion axis`.

### Task 3: Defeature chamfers and edge rounds

**Files:**
- Create: `stl2scad/core/segmentation/defeature.py`
- Test: `tests/test_segmentation_defeature.py`

**Interfaces:**
- Consumes: `regularize`, `extrusion_axis` (Task 2).
- Produces:

```python
@dataclass(frozen=True)
class EdgeTreatment:
    id: str                       # "chamfer_1", "edge_round_1"
    kind: Literal["chamfer", "edge_round"]
    face_id: str
    hosts: tuple[str, str]        # the two plane faces it replaces the sharp edge of
    size: float                   # chamfer width (equal setback on both hosts) or round radius, mm
    edge_point: Vector            # a point on the virtual sharp edge (host plane intersection), world
    edge_direction: Vector        # unit, world
    segments: int | None = None   # facet count of a round, as Cylinder.segments
    radial_reference: Vector | None = None

@dataclass(frozen=True)
class Defeatured:
    result: SegmentationResult    # treatment faces removed from faces and graph
    axis: Vector                  # extrusion axis
    treatments: tuple[EdgeTreatment, ...]
    rejected: tuple[tuple[str, str], ...]   # (face_id, reason), e.g. ("F7", "asymmetric chamfer")

def defeature(result: SegmentationResult) -> Defeatured
```

Rules (relative to the extrusion axis): a **chamfer** is a plane whose normal is neither ∥ nor ⟂ to the axis, with exactly two plane neighbours across convex edges (one cap, one side) and the chamfer normal within 0.5° of their bisector; the width is the setback on the hosts. A plane with the same topology that is not on the bisector goes to `rejected` with reason `"asymmetric chamfer"`. An **edge round** is a convex cylinder with axis ⟂ to the extrusion axis, tangent to two planes (one cap, one side). A treatment whose edge direction is neither ∥ to a cap nor in a side plane goes to `rejected` with reason `"oblique edge"`. Cylinders with axis ∥ to the extrusion axis are profile arcs and stay in the graph.

Implementation clarifications for Task 3 (2026-10-20):

- Count the two sharp-edge **hosts**, not transverse end planes bounding a finite strip. For a planar treatment the cap/side intersection line must lie in the treatment plane; for a round it must parallel the cylinder axis. The block fixtures also have left/right end-plane neighbours, so counting all neighbours would incorrectly reject their intended treatments.
- "Oblique in the part frame" uses the extrusion direction and a cap-plane basis anchored to dominant side-plane support. A 20-degree diagonal inside the cap plane is rejected even though it is mathematically parallel to that cap. This makes the stated oblique-edge test precise without using world-axis directions; signs affect numbering only.

- [x] **Step 1: Write tests.** `test_chamfers_and_rounds_are_removed` (each Task 1 part with treatments, each variant: ids, kinds and `size` within 2 % of the JSON; hosts match the JSON faces; the remaining faces equal the JSON faces minus the treatment faces). `test_asymmetric_chamfer_is_rejected_by_name` (`rejected == (("<face>", "asymmetric chamfer"),)`, no treatment). `test_profile_arcs_are_not_treatments` (rounded plate and stencil-like corner arcs stay faces). `test_oblique_edge_is_not_a_treatment` (a block whose chamfered edge is rotated 20° in the top plane: no treatment, one `"oblique edge"` rejection).
- [x] **Step 2: Run, expect FAIL.**
- [x] **Step 3: Implement `defeature`.**
- [x] **Step 4: Run** the new tests and `tests/test_segmentation_*.py`. Expected: PASS; no change elsewhere.
- [x] **Step 5: Commit** `feat: defeature symmetric chamfers and convex edge rounds`. The orchestrator starts the Agy review lane on Tasks 2–3 after this implementation lane stops (see Execution).

### Task 4: Slab levels and section profiles

**Files:**
- Create: `stl2scad/core/segmentation/slabs.py`
- Test: `tests/test_segmentation_slabs.py`

**Interfaces:**
- Consumes: `Defeatured` (Task 3); `Profile`, `ProfileSegment` from `features.py`; `arc_points`, `profile_points` from `sections.py`.
- Produces:

```python
@dataclass(frozen=True)
class Slab:
    index: int                     # 1-based
    bottom: float                  # part-frame z
    top: float
    loops: tuple[Profile, ...]     # CCW outer loops, CW holes, part-frame XY
    face_ids: tuple[str, ...]      # side and cap faces owned by this slab
    point_face_ids: tuple[str, ...] = ()  # side faces given as section points (not analytic)

def slab_levels(defeatured: Defeatured, frame: np.ndarray) -> list[float]
def slab_profiles(defeatured: Defeatured, frame: np.ndarray) -> list[Slab]
```

Approach: levels are the merged heights of planes with normal ∥ axis (tolerance `mesh.diagonal * 2e-5`). For each pair of adjacent levels, the active side faces are planes with normal ⟂ axis and cylinders with axis ∥ axis whose triangles span the slab. At mid-height, each plane gives a line and each cylinder an arc (keep `segments` and phase as in `sections.py`); order them by graph adjacency and trim at neighbour intersections. A side face that is neither (for example an elliptic wall) gives the mesh section polyline at mid-height for that span and its id goes in `point_face_ids`. Adjacent slabs with equal loops (within tolerance) merge.

- [x] **Step 1: Write tests.** `test_stepped_bar_levels_and_loops` (levels `[0, 2, 10]` within 0.01; slab 1 one loop = bar ∪ head outline; slab 2 loops = head with two R1 arcs + rib with two R0.5 arcs; arc radii within 2 %; all variants). `test_clipped_arc_plate_profile` (after defeature: one slab, one loop with four R3 arcs; the chamfer does not change the loop). `test_point_face_ids_for_non_analytic_side` (an extruded ellipse plate 3 × 8 quarter-ellipse corner: the elliptic wall id is in `point_face_ids`, and the loop is within 0.001 mm of the true section).
- [x] **Step 2: Run, expect FAIL.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** the new tests and `tests/test_segmentation_*.py`. Expected: PASS.
- [x] **Step 5: Commit** `feat: slice multi-height slabs into analytic section profiles`.

Implementation clarifications for Task 4 (2026-10-20):

- Filter face-graph edges by whether their source mesh edges cross the slab midpoint. Two faces touching below a step are not necessarily neighbors above it. This keeps the head and free-ended rib separate without changing segmentation.
- A source face spanning multiple intervals is owned by its first slab; later section segments retain its ID. Upward caps belong below their level and downward caps above it. Equal-section merges retain both intervals' side provenance. Faces wholly outside the recovered cap intervals remain unowned for the later remainder stage.
- The elliptic-wall test supplies an independently meshed, hand-labeled nonanalytic region. Task 4 consumes that region as section points; detecting or grouping elliptic walls remains outside this task. No new analytic surface type or ellipse fit is introduced.

### Task 5: Remainder regions and the new dispatch

**Files:**
- Create: `stl2scad/core/segmentation/remainder.py`
- Create: `stl2scad/core/segmentation/compose.py`
- Modify: `stl2scad/core/segmentation/features.py` (`FeatureKind` gets `"slab"`, `"chamfer"`, `"edge_round"`, `"remainder"`; `Feature` gets `remainder_triangles: tuple[tuple[Vector, Vector, Vector], ...] = ()` and `reason: str | None = None`; `detect_features` dispatch)
- Test: `tests/test_segmentation_compose.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: `FREE_FORM_LIMIT = 0.10` in `remainder.py`; `remainder_regions(result: SegmentationResult, explained: set[str], frame) -> list[Feature]` — connected groups of unexplained faces, each a `Feature(kind="remainder", polarity=..., face_ids=..., remainder_triangles=<closed solid in world coordinates>, reason=...)`; the solid is closed by projecting the open boundary loop onto the extended host plane(s) and extending it `_join_epsilon` into the body; polarity is additive when the region is outside the parametric body, subtractive when inside. `free_form_share(result, regions) -> float` (area of region faces / total area). `compose_features(result: SegmentationResult) -> list[Feature]` in `compose.py`: regularize → defeature → slabs → existing secondary features (boss, blind hole, through hole, fillet) on the slab body → remainder; raises `ValueError("free-form share X % exceeds 10 %")` above the limit. Each rejected treatment becomes a remainder with `reason` set to its rejection reason.
- `detect_features` order: pin; then `compose_features` when `defeature(...).treatments` or `.rejected` is not empty; else the existing section and cylinder paths; if those raise `ValueError`, `compose_features`.

- [x] **Step 1: Write tests.** `test_old_path_parts_keep_their_output` (for the composite bracket, rounded plate and all their variants, `emit_scad(None, mesh)` is byte-equal to the output at the parent commit, recorded in the test as a SHA-256 of the text with the `// Source:` line removed). `test_compose_feature_kinds` (each Task 1 part: feature kinds and counts equal the JSON). `test_dome_is_one_additive_remainder` (`dome_plate`: one `remainder`, additive, share < 0.10). `test_large_dome_exceeds_limit` (`compose_features` raises with "exceeds 10 %"). `test_asymmetric_chamfer_becomes_named_remainder` (`reason == "asymmetric chamfer"`).
- [x] **Step 2: Run, expect FAIL.**
- [x] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests and `tests/test_segmentation_*.py`. Expected: PASS. Ran both: the 34 compose tests pass; G7 is explicitly abandoned because three known-gap diagnostics now reach the Task 6 IR/emitter. This lane cannot change those adapters or `fixture_expectations.json`; the handoff question is in its REPORT.md.
- [x] **Step 5: Commit** `feat: compose slabs, treatments and remainder regions in detect_features`.

Implementation clarifications for Task 5 (2026-10-20):

- `Feature.loops: tuple[Profile, ...] = ()` preserves all islands and holes of one slab; `profile` remains its primary loop. A slab uses `position.z` for its bottom, `height` for its interval length, and `length`/`width` for its overall part-frame X/Y spans. This avoids splitting the stepped head and rib into two slab features or dropping a loop.
- Composition uses a private support copy to fill holes in planar hosts and extend removed host cuts to their sharp intersections before calling `slab_profiles`. Convex hulls supply connected planar section hints only; the fitted planes/cylinders and height-filtered source graph still determine final profile edges. Original source triangles and areas remain untouched for provenance and remainders.
- A body cap must touch an extrusion-compatible side. A tiny planar polar facet on a tessellated dome belongs to the remainder, not a new slab level. Boss/hole secondary classification requires a full circumference; half-round rib ends and partial profile corners remain sketch arcs.
- Remainder closures use the extended host plane (or host-plane intersection), preserve the measured patch, and add a scale-relative overlap of `mesh.diagonal * 1e-6`. Closure welding and manifold/winding/volume checks remain in float64; source surface share excludes artificial closure triangles.
- A proved existing named section takes priority over a competing treatment-axis hypothesis. This preserves thin rounded plates that the axis heuristic can reinterpret as four spatial rounds. The old path now rejects partial-cylinder bosses and oblique body facets it did not reconstruct; otherwise stepped profiles and domes could be silently omitted until the final gate.
- If both detection paths reject a part, keep the original fallback diagnostic and chain the compose failure. The explicit free-form-share limit keeps its own diagnostic. This preserves existing known-gap reasons without changing their expectations.
- Coalesce neighboring short facet lines into an arc only when their endpoints and midpoint match that arc's input polygon within the existing section tolerance. Preserve all their face IDs and the arc phase/count. This restores whole adjustable R3 corners where a clipped source strip left a few fitted facet planes.

### Task 6: Validation solid, IR and emit

**Files:**
- Modify: `stl2scad/core/segmentation/solid.py` (`_validation_source` for the new kinds)
- Create: `stl2scad/core/segmentation/compose_ir.py` (`compose_to_ir(features) -> ParametricModel`)
- Modify: `stl2scad/core/segmentation/to_ir.py` (route to `compose_to_ir` when any feature is `slab`, `chamfer`, `edge_round` or `remainder`)
- Modify: `stl2scad/core/segmentation/emit.py` (header lines for remainder regions)
- Test: `tests/test_segmentation_treatments.py`

**Interfaces:**
- Consumes: Task 5 features; `ParametricModel`, `Binding` from `to_ir.py`.
- Produces SCAD of this shape: `union()` of one `linear_extrude` per slab (`step_<n>_height` drives each top level; the parameter is the height above the part bottom); `difference()` with one cutter per treatment along its edge (round: square `r × r` minus a circle `r` with the emitted `segments` and phase; chamfer: right triangle with legs `w`); a remainder region as `polyhedron()` inside `union()` (additive) or `difference()` (subtractive), with no parameter. Header lines: `// Free-form region remainder_<n>: faces F.., area A mm2, reason <reason>` for each region and `// Free-form share: S % (limit 10 %)`. Limits: `assert(edge_round_<n>_radius < min(host widths))`, `assert(chamfer_<n>_width < min(host widths))`, `assert(step_1_height < step_2_height ...)`.

- [ ] **Step 1: Write tests** (each Task 1 part and variant, rendered by OpenSCAD):
  - `test_emitted_treatment_parts_pass_gate`: `"polyhedron("` absent for `chamfered_block`, `edge_round_block`, `clipped_arc_plate`, `stepped_bar`; Hausdorff < `gate_limit_mm`.
  - `test_customizer_parameters`: `openscad --export-format=param` gives `min`, `step`, `max`, `caption` for every name in the JSON `parameters`, with `initial` within 0.001 mm of the design value.
  - `test_slider_edit_matches_ground_truth`: set `edge_round_1_radius` to 4, `chamfer_1_width` to 3, `step_1_height` to 3 (one at a time) in the emitted SCAD; render the ground-truth SCAD with `-D` the same value; Hausdorff between the two < `gate_limit_mm`.
  - `test_treatment_limits_stop_render`: radius 25 on `edge_round_block` and width 9 on `chamfered_block` make OpenSCAD fail with an assert message.
  - `test_supported_treatments_never_become_remainder`: no `Free-form region` line for the four parts above.
  - `test_dome_plate_is_hybrid`: one `polyhedron(` inside a `union()`, Hausdorff < gate, header share < 10 %; plate parameters still in the Customizer.
  - `test_large_dome_falls_back`: the whole output is the fallback polyhedron and the header names the share.
  - `test_asymmetric_chamfer_is_reported`: no `chamfer_1_width`; a `Free-form region` line with `reason asymmetric chamfer`; Hausdorff < gate.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests and the full baseline command. Expected: new tests PASS; baseline 311 + new passed, the same 3 failed.
- [ ] **Step 5: Commit** `feat: emit slabs, edge treatments and hybrid remainder regions`. Then start an Agy review lane on Tasks 4–6.

### Task 7: Real parts and documentation

**Files:**
- Modify: `docs/planning/segmentation_real_parts.md` (new results table), `docs/planning/segmentation_composite_bracket.md` ("Output decisions": Edge treatments, Remainder; "Known limits": remove review #5 for convex rounds), `CLAUDE.md` (status section)
- Modify: `tests/data/segmentation/real/memo_cartridge_expected.json` (replace C120–C125 arcs by the measured quarter ellipse, mark `hand_check` for the feet as done)

- [ ] **Step 1: Run** `.venv/bin/stl2scad convert <stl> <out.scad> --pipeline segmentation` for `memo_stencil6`, `memo_cartridge`, `memo_power_button` (paths in the `source_stl` fields). Record for each: parametric / hybrid / polyhedron, Hausdorff, free-form share, remainder reasons.
- [ ] **Step 2: Check** that `memo_stencil6` output is unchanged (Hausdorff 0.00001 mm, no `Free-form region` line).
- [ ] **Step 3: Write the results** into the docs. Do not tune any threshold to these parts.
- [ ] **Step 4: Run** the full baseline command. Expected: the same 3 failures only.
- [ ] **Step 5: Commit** `docs: record plan 1 results on the real parts`.

## Execution

- Codex builds each task as a `--resume` of lane `seg-fixes` (it keeps its context of this code), `sandbox workspace-write`, `effort high`, `task build`. Each brief names the task, its tests, the Global Constraints, and "do not commit".
- After each task: Claude runs the task tests and `tests/test_segmentation_*.py`, checks each claim with its own command, fixes small faults, and commits.
- Agy review lanes after Tasks 3 and 6 (read-only, findings file). Claude acts on findings with `superpowers:receiving-code-review`.
