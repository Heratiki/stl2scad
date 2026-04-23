# Feature-Level Parametric Reconstruction

## Purpose
Move beyond primitive-only STL conversion toward editable OpenSCAD approximations for arbitrary user STL collections.

## Problem Statement
Primitive fitting can produce compact SCAD for simple geometry, but it does not recover design intent. A useful parametric reverse-engineering workflow should identify editable features such as plates, shells, repeated holes, slots, mirror symmetry, grids, bosses, ribs, tabs, and cutouts.

## Strategy
1. Keep current polyhedron and primitive output as safety fallback.
2. Inventory real STL collections before adding specialized reconstruction rules.
3. Detect generic feature signals first:
   - axis-aligned planar dominance
   - mirror symmetry
   - regular coordinate spacing
   - connectedness and complexity
   - mechanical-like versus organic-like geometry
4. Use inventory results to prioritize reconstruction templates:
   - repeated arrays and grids
   - plate/shell extraction
   - hole/cutout grouping
   - symmetry-based modules
   - reusable parameter variables

## Initial Tooling
`scripts/analyze_feature_inventory.py` scans a folder of STL files and writes JSON with:
1. mesh size and bounding boxes
2. normal/plane dominance
3. coarse symmetry scores
4. coordinate-spacing regularity
5. broad classification (`mechanical_candidate`, `organic_candidate`, or `degenerate_or_flat_candidate`)
6. candidate feature hints

Example:

```bash
python scripts/analyze_feature_inventory.py "C:\Users\herat\OneDrive\3D Files" --output artifacts/feature_inventory_onedrive.json --max-files 100
```

Folder scans support parallel workers. Use `--workers 0` for auto, `--workers 1` for serial, or a fixed count such as `--workers 8`.

`scripts/build_feature_graph.py` builds the first intermediate feature graph. It currently extracts conservative axis-aligned boundary plane pairs, high-confidence `box_like_solid` / `plate_like_solid` candidates, circular `hole_like_cutout` candidates in plate-like solids, rounded `slot_like_cutout` candidates in plate-like solids, and repeated-hole pattern nodes (`linear_hole_pattern` / `grid_hole_pattern`).

Linear hole patterns include explicit `pattern_origin`, `pattern_step`, `pattern_count`, and `pattern_spacing` metadata so SCAD previews can expose editable count/spacing-style loops instead of only listing literal hole centers.

Grid hole patterns include explicit `grid_origin`, `grid_row_step`, `grid_col_step`, `grid_rows`, `grid_cols`, `grid_row_spacing`, and `grid_col_spacing` metadata so SCAD previews can emit nested row/column loops for regular rectangular hole arrays.

Slot cutouts include explicit `start`, `end`, `width`, `length`, and `slot_axis` metadata so SCAD previews can emit editable rounded-slot cutouts using a `hull()` of two through-cut cylinders.

Example:

```bash
python scripts/build_feature_graph.py "C:\Users\herat\OneDrive\3D Files" --output artifacts/feature_graph_onedrive.json --max-files 100
```

For directory inputs, the graph builder can now run inventory first and only
process likely mechanical candidates:

```bash
python scripts/build_feature_graph.py "C:\Users\herat\OneDrive\3D Files" --output artifacts/feature_graph_onedrive.json --inventory-prefilter --inventory-output artifacts/feature_inventory_onedrive.json
```

For a single STL with a high-confidence plate/hole graph, the script can also write an experimental SCAD preview:

```bash
python scripts/build_feature_graph.py input.stl --output artifacts/input_feature_graph.json --scad-preview artifacts/input_feature_preview.scad
```

## Current State Assessment (2026-04-20)

Three interconnected systems are now in place: feature inventory, feature graph, and manifest-driven feature fixtures. The focused feature test slice currently passes in the project virtualenv across `test_feature_inventory.py`, `test_feature_graph.py`, `test_feature_fixtures.py`, and the feature-specific CLI coverage in `test_cli.py`. CLI commands `feature-inventory`, `feature-graph`, and `feature-graph-from-inventory` are wired up with parallel worker support and progress reporting for directory scans, and `feature-graph` directory mode can now optionally inventory-prefilter before graph construction.

### Feature Fixtures (`stl2scad/core/feature_fixtures.py`) — High value

Manifest-driven system that generates known-geometry OpenSCAD plates (with holes, slots, linear/grid patterns), renders them to STL via OpenSCAD, then runs the feature graph detector on the result to verify it finds exactly what was defined. This is a closed-loop ground-truth validation pipeline for feature-graph detection, and it also provides controlled inputs that can be used to tune feature-inventory heuristics.

**Strengths:**

- Thorough input validation — bounds checking, duplicate detection, geometry-in-plate constraints
- Round-trip test (`test_feature_fixtures.py::test_feature_fixture_round_trip_detection`) is the real payoff: manifest -> SCAD -> STL -> feature graph -> assert counts match. Catches regressions in the detector without relying on hand-labeled data.
- 13 checked-in fixture cases spanning plain plates, linear/grid holes, slots, counterbores, mixed-feature plates, near-boundary holes, high-aspect-ratio plates, small/large hole diameters, boxes with holes, and an L-bracket baseline

**Limitations:**

- Coverage is broader but still focused on conservative axis-aligned solids; rotated features, box cutouts, and more complex composite brackets are still absent
- The current set now covers the first round of edge cases, but it still needs tougher tolerance-boundary geometry and mixed multi-pattern cases on the same plate
- `expected_detection` counts are manually authored, so they're only as good as the author's understanding of what the detector should find
- Round-trip now checks dimensions, but the tolerances (`_CENTER_TOL`, `_DIAMETER_TOL`, etc. in `tests/test_feature_fixtures.py`) are hand-picked; they'll need revisiting as the detector precision improves or as noisier real-world STLs are added.

### Feature Inventory (`stl2scad/core/feature_inventory.py`) — Moderate value

Batch-analyzes STL folders and produces JSON reports with geometry signals (bounding box, normal axis profile, symmetry scores, coordinate spacing regularity) and mechanical-vs-organic classification.

**Strengths:**

- Progress callback, parallel workers, clean report structure
- Candidate feature heuristics (axis-aligned planes, mirror symmetry, regular spacing) are reasonable first-pass signals
- Useful for triaging large STL collections before reconstruction

**Limitations:**

- Mechanical/organic scoring is coarse (weighted sum of 3-4 signals) — works for obvious cases, struggles with ambiguous models
- Classification is per-file, not per-region — a model with both mechanical and organic features gets one label
- Integration now exists as a whole-file prefilter into the feature graph, but the handoff is still binary and coarse; inventory does not yet provide region-level hints or richer detector guidance

### Feature Graph (`stl2scad/core/feature_graph.py`) — High value

Detects axis-aligned boxes, through-holes, slots, and repeated hole patterns (linear + grid) from raw STL geometry, then emits a SCAD preview.

**Strengths:**

- Conservative by design (0.70 confidence threshold) — avoids false positives
- Pattern detection (linear arrays, grids) is genuinely useful for mechanical parts
- SCAD preview emission with parameterized variables produces editable output

**Limitations:**

- Only handles axis-aligned geometry — rotated features are invisible
- Pattern detection depends on hole centers being near-exactly spaced; real-world STLs from meshed CAD may have enough floating-point noise to break it
- `plate_like_solid` requires strictly rectangular top/bottom faces — any chamfer or fillet on a plate edge drops detection to `axis_boundary_plane_pair` only and blocks SCAD preview emission. Observed on multiple real FDM parts (2026-04-20 sample); dominant real-world failure mode.
- `box_like_solid` is detected (including a tolerant-confidence variant) but `emit_feature_graph_scad_preview` only consumes `plate_like_solid` — pure axis-aligned cuboids (e.g. Test_Cube) end up as a feature-graph entry with no parametric preview emitted.

## Real-World Feedback Loop (2026-04-22)

The 2026-04-20 sample made it clear that fixture pass-rate no longer predicts real-world pass-rate. The highest-ROI path toward the project's intent — parametric SCAD output for arbitrary user STLs — is a three-phase loop that goes "measure real failures → close the dominant pattern → expand with supervised data." The detailed items under *Immediate priorities* below are the tactical checklist; this section is the framing that explains their ordering.

### Phase 1: Triage loop over unlabeled real STLs (days)

Run a folder of real STLs (starting with `D:\3D Files\FDM`) through `feature-graph` and bucket the outcomes by detector result: produced a parametric preview, detected features but below confidence threshold, fell through to `axis_boundary_plane_pair` only, or fell through to polyhedron. Rank buckets by which broken-edge pattern or geometry style costs the most parts. The triage loop does not itself fix anything — it replaces guesswork about "which detector gap matters most" with ranked evidence drawn from the user's actual corpus. Cheap to build on top of the existing folder-mode `feature-graph` and the confidence scores the detector already emits.

This is distinct from *Immediate priority #2* ("real-world STLs with authored `expected_detection` counts"): triage works on unlabeled STLs, no hand-authored ground truth required. The two complement each other — triage identifies *which* real parts deserve the investment of authoring ground truth.

### Phase 2: Close the dominant real-world failure pattern (weeks)

Extend the tolerant-detection approach that already works for `plate_plain_chamfered_edges` to whichever geometry the Phase 1 triage ranks highest. On the 2026-04-20 sample that is most likely filleted plate and box edges, which would satisfy *Immediate priority #1*. Each pattern closed moves real-world pass-rate directly; triage re-run after each closure tells us whether the fix generalized and what the next dominant pattern is.

### Phase 3: ABC dataset as a supervised corpus (months)

The [ABC Dataset](https://deep-geometry.github.io/abc-dataset/) (~1M CAD models with STEP/B-rep ground truth, Koch et al. 2019) is the only public dataset that supplies real parametric supervision for what this project emits. STEP files carry feature trees (holes, fillets, extrusions) that can be compared directly against detector output. Wiring it in is weeks of STEP-parser work per feature family, so this is a phase-3 investment — valuable only once Phase 2 has lifted real-world pass-rate meaningfully above today's baseline, because extra supervision cannot be consumed productively while common real-world geometry still fails to detect at all.

### Traps to avoid

- **Do not run `tune_detector` against the synthetic fixture corpus as the project's optimization target.** With synthetic pass-rate decoupled from real-world pass-rate, tuning in this regime overfits the synthetic distribution at the cost of real parts. Defer tuning until a real-world-weighted scoring function exists (scored via Phase 1 triage data plus the labeled real-world fixtures from *Immediate priority #2*).
- **Do not start Phase 3 before Phase 2 raises the detector's floor.** Supervised data only helps a detector that can already represent the features being supervised.

## Next Milestones

### Recently completed (2026-04-22)

The Next Work Package scoped for 2026-04-22 → 2026-05-31 (Tracks A–D) shipped ahead of schedule; all four tracks are complete.

- **Track A — Real-world triage harness** (commits `d981455`, `b29d1f1`, `2c1c4ca`). `scripts/build_feature_graph.py` accepts `--triage-output`; `scripts/summarize_feature_triage.py` produces the ranked failure-pattern summary used to drive Track B prioritization.
- **Track B — Tolerant plate/box generalization** (commits `e50e04a`, `11a9cee`, `d981455`, plus `d79026a`). Manifest now carries `plate_plain_filleted_edges`, `plate_filleted_linear_holes`, `box_rounded_edges`, and `box_rounded_edges_with_top_notch`. Box detection was enhanced; `emit_feature_graph_scad_preview` emits a parametric `cube()`/`translate()` preview for high-confidence `box_like_solid` bases at parity with plates. `test_feature_fixture_preview_round_trip_detection` passes for all plate and box fixtures including `box_rounded_edges`. **Track B is closed.**
- **Track C — Real-world labeled micro-corpus + recall merge-gate** (commits `9e80cc9`, `5ee5081`). `tests/test_real_world_corpus.py`, `tests/test_feature_real_world_smoke.py`, `tests/test_score_real_world_corpus.py`, and `scripts/score_real_world_corpus.py` enforce the baseline merge-gate; detector threshold changes now diff against the committed baseline.
- **Track D — Grid-pattern parametric SCAD emission** (in [stl2scad/core/feature_graph.py:524-525](../../stl2scad/core/feature_graph.py#L524-L525)). Grid patterns emit nested `for (row = ...) for (col = ...)` loops with named `_rows`/`_cols` variables; preview round-trip holds.
- **Detector auto-tuning infrastructure** (commits `fbff9ca`, `74191ab`, `11ff8b4`, `463655a`, `86a3311`, `450523e`, `f733894`, `7fc25e5`, `432cff1`, `aa8aede`). `DetectorConfig` replaces hardcoded thresholds; [scripts/tune_detector.py](../../scripts/tune_detector.py) drives an Optuna search across 25 thresholds with stratified train/holdout and LOO CV; writeup in [detector_autotune_results.md](detector_autotune_results.md). Running tuning was allowed only after Track C's merge-gate existed (Execution Order rule 3).
- **Detector IR vocabulary defined** — [detector_ir.md](detector_ir.md) documents the target IR (Interpretation / Boolean / Transform / Pattern / Primitive / Cutout / Sketch / ExtrudeLinear / Edge / Strategy layers) and maps every current `feature_graph` node type onto it. Non-executable contract; referenced by Immediate priorities below.
- **Boolean + Transform IR wrapping** (2026-04-22). `_build_ir_tree()` in [stl2scad/core/feature_graph.py](../../stl2scad/core/feature_graph.py) builds a ranked `Interpretation` list and attaches it as `graph["ir_tree"]`. Each detected primitive is wrapped in `BooleanDifference { base: Primitive, cuts: [...] }` or `BooleanUnion { children: [Primitive] }`; cutout placements are lifted into `TransformTranslate` nodes; pattern holes are subsumed into `PatternLinear` / `PatternGrid` nodes with no standalone duplication; meshes with no solid produce `FallbackMesh`. The flat `graph["features"]` list is unchanged (backward compat). Seven new tests in `test_feature_graph.py` cover the full schema. This is **Immediate priority #2 closed**.
- **Chamfer/Fillet IR promotion** (2026-04-22). Every `plate_like_solid` and `box_like_solid` feature node now carries a `detected_via` field (`"strict"` or `"tolerant_chamfer_or_fillet"`). When the tolerant path fired, `_build_ir_tree()` injects a `ChamferOrFilletEdge` annotation node into the `BooleanDifference` cuts list so downstream emitters can see the edge treatment rather than it being silently absorbed by confidence arithmetic. Five new tests cover the `detected_via` field and the IR node. **Immediate priority #1 closed** (kind disambiguation — chamfer vs fillet — is a future refinement once the detector can measure edge curvature).
- **Inventory-guided family-confidence selection** (2026-04-22). `InventorySelectionConfig` now supports `min_family_confidence` plus an optional `allowed_families` subset (`plate`, `box`, `cylinder`), and both `feature-graph` CLI entry points expose those filters. This moves the inventory-prefilter handoff beyond a binary whole-file mechanical gate and lets real-world triage focus on the detector family being improved. A latent `symmetry_sum` bug in cylinder-family inventory scoring was fixed in the same pass.
- **Cylinder as a positive primitive** (2026-04-22, commit `7afe08a`). `_extract_cylinder_like_solid` ([stl2scad/core/feature_graph.py:1054](../../stl2scad/core/feature_graph.py#L1054)) detects solid axis-aligned cylinders along X, Y, or Z; `_emit_cylinder_scad_preview` produces parametric `cylinder()` calls with axis-alignment rotation; three fixtures (`cylinder_plain`, `cylinder_short_disk`, `cylinder_x_axis`) with dimensional round-trip assertions. Cylinder detection runs *before* plate/box classification so a disk is correctly classified as a cylinder rather than a thin plate.
- **Rotated plate detection** (2026-04-22, commit `705efe9`). `_extract_rotated_plate_solid` uses area-weighted normal covariance to find any dominant normal direction and a 2D minimum-area rectangle to recover the in-plane rotation, producing full 3D orientation recovery — not limited to world-axis rotations. IR tree wraps rotated plates in `TransformRotate { BooleanDifference { PrimitivePlate, ... } }`; SCAD emitter produces `rotate([rx,ry,rz]) translate(...) cube(...)`. Fixtures: `plate_plain_rotated_z30`, `plate_plain_rotated_x30`, plus `box_z_through_hole_rotated_z25` as a negative-class guard.
- **Negative-class fixtures** (2026-04-20, commit `325a894`). `negative_sphere` and `negative_torus` fixtures with explicit `expected_detection` asserting the detector stays silent on non-plate / non-box organic shapes.
- **Richer inventory-to-detector guidance** (2026-04-22, commits `dea19be`, `6046929`). `_detector_guidance()` in [stl2scad/core/feature_inventory.py:770](../../stl2scad/core/feature_inventory.py#L770) produces per-file detector routing hints (focus, preferred_families, symmetry_axes, regular_spacing_axes); per-axis `region_hint` fields give region-level context. Feature graph consumes these into `inventory_context` at [stl2scad/core/feature_graph.py:340-347](../../stl2scad/core/feature_graph.py#L340-L347). This closes the "region-level hints and family-specific routing metadata instead of only whole-file admission control" gap previously listed under Immediate priority #3.

### Recently completed (2026-04-20)

- **Tolerant chamfered-plate detection** — `plate_like_solid` no longer requires intact side boundary planes when the thinnest axis still has strong opposing planar support and those faces fill an axis-aligned rectangular footprint. This closes the specific failure mode where simple edge-chamfered plates fell through to `axis_boundary_plane_pair` only. The feature-fixture corpus now includes `plate_plain_chamfered_edges` as a checked-in regression case.
- **Schema-v2 candidate interpretation checks** — feature fixtures can now declare ranked interpretation candidates, and the harness can rank those candidates against an observed feature graph via `rank_feature_fixture_candidates`. The `box_hollow_ambiguous` fixture now includes a real interior cavity and a round-trip test asserts the intended interpretation ranks first.
- **Single-step inventory-prefiltered graph workflow** — folder-level feature graph generation can now run inventory first, persist the inventory optionally, and build graphs only for files classified as `mechanical_candidate`. This is exposed in both `scripts/build_feature_graph.py` and `python -m stl2scad feature-graph --inventory-prefilter`.
- **Dimensional round-trip assertions** — `test_feature_fixture_round_trip_detection` now compares detected feature dimensions against the manifest within per-field tolerances (hole diameter/center, slot width/length, counterbore through/bore/depth, plate and box extents, linear/grid pattern origin/step/spacing).
- **Counterbore depth generator fix** — `counterbore_hole` module now takes explicit `plate_thickness` and anchors the bore at `plate_thickness - bore_depth`, eliminating the compounded 0.1mm offset. All 11 affected `.scad` fixtures were regenerated.
- **CI-hard-fail for missing OpenSCAD** — `test_feature_fixture_round_trip_detection` fails (no longer silently skips) when `CI=true` and the OpenSCAD binary is unavailable.
- **Manifest `schema_version` enforcement** — `load_feature_fixture_manifest` rejects unknown schema versions, and the checked-in fixture manifest is now schema version 2 with explicit candidate interpretations.
- **Parametric preview round-trip** — SCAD previews now declare named variables for supported plate geometry and cutouts, and `test_feature_fixture_preview_round_trip_detection` re-renders those previews to STL and re-checks detector counts plus supported dimensions.

### Immediate priorities

Reprioritized 2026-04-22 (late) after rotated plates, cylinder-as-positive-primitive, negative-class fixtures, and richer inventory guidance all landed end-of-day. The active front has moved up a tier: **Sketch2D + `rotate_extrude` recovery**, which unifies cone/sphere/ellipsoid detection with solids-of-revolution support and is the roadmap's single largest outstanding win.

1. **Sketch2D + `rotate_extrude` recovery — Phase 1** (see [Current Work Package](#current-work-package-phase-1-axisymmetric-rotate_extrude-recovery) below; full spec in [docs/superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md](../superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md)). Axisymmetry detection → radial profile extraction → `rotate_extrude() polygon([...])` emission. Subsumes the individual cone/sphere/ellipsoid detectors that were previously scoped separately.
2. **Rotated cutouts on rotated plates.** The rotated-plate detector ([stl2scad/core/feature_graph.py:938](../../stl2scad/core/feature_graph.py#L938)) handles plate bodies at arbitrary orientation, but `_candidate_cutout_axes` still operates in world coordinates, so a rotated plate with holes/slots/patterns detects only the plate and misses the cutouts. Fix: extend cutout extraction to operate in the plate's local (u, v, thickness) frame when `detected_via == "rotated_plate"`.
3. **Rotated-box detector (positive path).** `box_z_through_hole_rotated_z25` exists today only as a negative fixture asserting the detector does NOT misfire on rotated cuboids. Mirror the rotated-plate approach (dominant normal-pair detection extended from one axis-pair to three) to produce positive detection. Flip the negative fixture to a positive expectation once the detector lands.
4. **Sketch2D + `rotate_extrude` recovery — Phase 2** (profile classification → primitive upgrade). Closes [detector_ir.md](detector_ir.md) tier-1 cone / sphere / frustum / ellipsoid rows as a consequence of the axisymmetric pipeline, rather than as standalone detectors.

### Beyond dimensional parity

Once the IR wrapping (priority #2) lands, the detector output becomes a tree, and these next steps become tractable:

1. **Detector-native interpretation ranking** — schema-v2 fixtures and harness-side candidate ranking are already in place, including a real hollow-box ambiguity fixture. Next step: make the detector emit ranked `Interpretation` candidates directly (per [detector_ir.md](detector_ir.md)) so the fixture harness can compare declared ranking/confidence against detector-produced ranking/confidence, not only against observed feature-count matches.
2. **Manifest schema as a versioned contract** — `schema_version` is already enforced on load; next is documenting the schema so third-party fixture authors (or future detectors) have a stable target.
3. ~~**Tier-2 primitive expansion** — cone/frustum, sphere, ellipsoid.~~ *Reframed 2026-04-22: absorbed into Immediate priority #1 / #4 (Sketch2D + `rotate_extrude` recovery). Each tier-2 primitive is a special case of a solid of revolution — rectangle profile → cylinder, triangle → cone, semicircle → sphere, trapezoid → frustum. Building the axisymmetric pipeline with a profile classifier gets all four primitives as a consequence instead of as four separate detectors.*
4. ~~**Sketch2D + ExtrudeLinear / ExtrudeRevolve recovery from mesh cross-sections**~~ — *Promoted 2026-04-22 from this "Beyond dimensional parity" list to the active work package. Full spec in [docs/superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md](../superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md). Phase 1 (axisymmetric `rotate_extrude`) is Immediate priority #1; Phase 3 (linear extrude) stays deferred until Phase 1–2 land.*

(Noise-injection fixtures were promoted out of this section on 2026-04-20 and landed via Track C on 2026-04-22.)
(Negative-class fixtures landed 2026-04-20 as `negative_sphere` and `negative_torus`; closed as a standing priority. Re-apply the pattern as new primitives come online via the axisymmetric pipeline.)

### Ongoing

1. Tighten hole/slot detectors against real files and add confidence thresholds for SCAD emission readiness.
2. Add targeted detectors for the most common candidate feature families.
3. Emit feature-based SCAD templates only when confidence is high; otherwise fall back.
4. Add optional user-assisted labeling for ambiguous features.

## Current Work Package — Phase 1: Axisymmetric `rotate_extrude` recovery

**Status:** specification landed 2026-04-22. Implementation plan pending (via superpowers:writing-plans after spec review).

**Full spec:** [docs/superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md](../superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md).

**One-line summary:** axisymmetric meshes produce `rotate_extrude() polygon([...])` SCAD output. A Christmas-tree ornament becomes one sawtooth profile polygon and one revolve, not N stacked cones.

**Why this is the critical path now:** the previous work package (rotated fixtures, cylinder as positive primitive, inventory guidance, negative-class fixtures) is complete. Building tier-2 primitives (cone/frustum/sphere/ellipsoid) as individual detectors duplicates signal the axisymmetric pipeline already produces — one detector subsumes all four. Sketch2D + `rotate_extrude` was previously listed under "Beyond dimensional parity #4" as the single largest outstanding roadmap win; promoting it ahead of individual tier-2 detectors avoids throwaway work.

**Phase boundaries:**
- **Phase 1:** axisymmetry test + radial slice + profile polygon + `rotate_extrude()` emission. Every axisymmetric solid emits as a polygon revolve.
- **Phase 2:** profile classifier upgrades recognizable polygons to `cylinder()` / `cone()` / `sphere()` / frustum.
- **Phase 3:** linear-extrude detector (same shape, translational symmetry instead of rotational). Deferred.
- **Phase 4:** composition detector for meshes that are neither single-revolve nor single-extrude but compositions of such. Explicitly speculative until Phases 1-3 are in main.

**Acceptance criteria for Phase 1:**
1. Every Phase 1 `revolve_*` fixture round-trips with its expected profile within tolerance.
2. A Christmas-tree-shaped input mesh emits a `rotate_extrude() polygon([...])` preview with fewer than 20 polygon points.
3. No regressions in existing axis-aligned plate / box / cylinder detection.
4. The three fixture invariants from [CLAUDE.md](../../CLAUDE.md) remain intact.

---

## Previous Work Package — status: fully shipped (2026-04-22)

Tracks A–D, Boolean + Transform IR wrapping, chamfer/fillet IR promotion, rotated plate detection, cylinder as positive primitive, negative-class fixtures, and richer inventory-to-detector guidance are all complete.

The track definitions below are retained for provenance and for the acceptance-criteria language they establish.

---

## Next Work Package (original: 2026-04-22 to 2026-05-31)

This package turns the immediate priorities into a short, test-first execution sequence. It is intentionally scoped to improve real-world parametric-preview recall before adding broader detector families.

This package covers Phase 1 (Track A) and Phase 2 (Track B) of the Real-World Feedback Loop, plus supporting infrastructure (Tracks C and D). Phase 3 (ABC dataset integration) is deliberately excluded — it remains a separate future investment once Phase 2 has measurably lifted real-world pass-rate.

### Track A: Real-world triage harness (unlabeled)

Goal: make "where and why detection fails" measurable on the user's corpus, not anecdotal.

1. Add a triage report mode to `scripts/build_feature_graph.py` for directory inputs:
   - per-file terminal bucket (`parametric_preview`, `feature_graph_no_preview`, `axis_pairs_only`, `polyhedron_fallback`, `error`)
   - top-level aggregate counts and percentages
   - optional `--triage-output artifacts/feature_graph_triage.json`
2. Include failure-shape metadata for non-preview cases:
   - dominant axis pair confidence summary
   - whether opposing major planes exist on the thinnest axis
   - whether plate/box rectangular footprint checks failed
3. Emit a ranked top-N failure-pattern summary (default N=5) across the `axis_pairs_only` and `feature_graph_no_preview` buckets, keyed on the failure-shape metadata above, weighted by part count. This is the evidence Track B uses to pick which tolerant-detection variant to build first — without it, Phase 2 prioritization is guesswork.
4. Add fixture-independent regression checks in `tests/test_feature_graph.py` for triage schema, bucket accounting, and ranked-pattern shape.

Acceptance criteria:

1. Running `feature-graph` on a directory with `--triage-output` always emits a valid JSON report, even when some files error.
2. The report totals reconcile: `sum(bucket_counts.values()) == files_processed`.
3. The report includes a `ranked_failure_patterns` array with at most N entries, each carrying a shape signature, a part count, and a representative example filename.
4. Existing CLI behavior remains unchanged when triage flags are omitted.

### Track B: Tolerant box/plate generalization

Goal: close the dominant real-world failure mode where fillets/chamfers break strict side-edge assumptions, and bring box preview emission to parity with plates.

1. Extend tolerant rectangular-footprint logic for plate edges (chamfered plate is already covered):
   - filleted plate edges
2. Bring axis-aligned cuboids to parity with plates. The detector already emits `box_like_solid` with tolerant-confidence handling at [stl2scad/core/feature_graph.py:579](../../stl2scad/core/feature_graph.py#L579); the real gap is the preview emitter:
   - verify tolerant box detection covers filleted/chamfered outer edges with the same rigor as the chamfered-plate path, and extend it where gaps are found
   - extend `emit_feature_graph_scad_preview` (currently early-returns at [stl2scad/core/feature_graph.py:185-187](../../stl2scad/core/feature_graph.py#L185-L187) when no `plate_like_solid` is present) to emit a `cube()` / `translate()` parametric preview for a high-confidence `box_like_solid` base, with supported cutouts on its faces
3. Keep conservative gating:
   - require strong opposing support on candidate principal axes
   - retain high-confidence thresholds for preview emission
4. Add new manifest fixtures (generated + checked-in):
   - `plate_plain_filleted_edges`
   - `box_plain_filleted_edges`
   - one mixed plate case combining filleted perimeter and a regular hole pattern

Acceptance criteria:

1. `python -m pytest tests/test_feature_fixtures.py -v` passes with regenerated fixture SCAD files.
2. The new fixtures round-trip with expected counts and dimensions under current tolerances.
3. A pure axis-aligned cuboid fixture (e.g. `box_plain_filleted_edges`) produces a non-empty parametric SCAD preview and the preview round-trips via `test_feature_fixture_preview_round_trip_detection`.
4. Existing sharp-edge fixture behavior is unchanged.

### Track C: Real-world labeled micro-corpus + recall metric

Goal: prevent synthetic-only optimization by tracking a small but explicit real-world score.

1. Introduce a checked-in mini-corpus manifest for real STLs (small, curated, and stable):
   - provenance metadata (`source`, `license`); only include STLs that are self-authored or carry an explicitly permissive license (CC0, CC-BY, public domain). STLs lacking clear provenance do not enter the corpus, even if they are diagnostically interesting — triage (Track A) can still process them locally without them being committed.
   - file fingerprint metadata (sha256, bounds) to detect drift
   - authored `expected_detection` counts and selected dimensions
2. Add `tests/test_feature_real_world_smoke.py` (or equivalent) that runs locally when corpus files are present and skips cleanly (not fails) when absent. CI wiring for the corpus is out of scope for this package; the test is local-only for now.
3. Add a simple recall score artifact emitted by the test run:
   - per-feature-family recall
   - preview-ready part ratio
4. Commit an initial baseline recall artifact produced from the local run; future changes diff against it.

Acceptance criteria:

1. Missing corpus files produce a clear, actionable skip when the test is run locally; absence is not a failure at this stage.
2. A baseline recall artifact is produced locally and committed as the seed baseline. CI archival is deferred to a later package.
3. Changes to detector thresholds must not merge without reporting delta against the committed baseline — this is the merge-gate form of the "do not tune against synthetic-only" trap.

### Track D: Grid-pattern parametric SCAD emission

Goal: use existing `grid_hole_pattern` metadata to emit editable nested loops instead of literal center lists.

1. Update SCAD preview emitter to use:
   - `grid_origin`
   - `grid_row_step` / `grid_col_step`
   - `grid_rows` / `grid_cols`
2. Keep existing per-hole fallback when grid metadata is incomplete or low-confidence.
3. Add preview round-trip assertions so generated loops still re-detect expected grid counts and spacings.

Acceptance criteria:

1. At least one grid fixture preview emits nested loop structure with named row/column variables.
2. Preview re-render still passes `test_feature_fixture_preview_round_trip_detection` for grid cases.
3. SCAD remains deterministic (stable ordering and variable naming) to avoid noisy fixture diffs.

## Exit Criteria For This Package

The package is considered complete when all of the following are true:

1. Triage reports quantify bucketed real-world outcomes for a target directory, and emit a ranked top-N failure-pattern summary that informs Phase 2 prioritization.
2. Tolerant detection covers both chamfered and filleted plate/box edge variants in fixtures, and pure axis-aligned cuboids emit a parametric preview.
3. A small labeled real-world corpus exists with reproducible recall reporting and a committed baseline artifact.
4. Grid-pattern previews are loop-parameterized and pass round-trip assertions.
5. The feature-fixture invariants remain intact:
   - byte-exact fixture regeneration
   - dimensional round-trip verification
   - roadmap stress-case coverage

## Execution Order & Dependencies

Plans in this doc span four sections (Real-World Feedback Loop, Immediate priorities, Beyond dimensional parity, Ongoing) plus the Next Work Package. This section is the sequencing rulebook that keeps them from stepping on each other and routes effort toward the project's end goal — parametric SCAD output for arbitrary user STLs.

**Rules (dependency order):**

1. **Fixture invariants are always gates, never lag indicators.** The three invariants from [CLAUDE.md](../../CLAUDE.md) (byte-exact regeneration, dimensional round-trip, roadmap stress-case coverage) must pass through every change. If any invariant breaks, fix it before touching anything else — do not relax the invariant to unblock downstream work.
2. ~~**Track A (triage) must ship before Track B commits to specific variants.**~~ *Satisfied 2026-04-22. Triage shipped and was used to scope Track B's filleted-edge work.*
3. ~~**Track C (labeled corpus + recall merge-gate) must exist before `scripts/tune_detector.py` is ever run as an optimization target.**~~ *Satisfied 2026-04-22. Merge-gate shipped in commit `5ee5081`; auto-tuning run followed, with results in [detector_autotune_results.md](detector_autotune_results.md).*
4. ~~**Track D (grid-pattern SCAD emission) is independent.**~~ *Satisfied 2026-04-22. Grid-loop emission shipped.*
5. ~~**Boolean + Transform IR wrapping must ship before new positive primitives merge.**~~ *Satisfied 2026-04-22. IR wrapping shipped in commit `4447707`; cylinder and rotated-plate detectors shipped after it with correct polarity/transform wrapping. The rule still logically applies to any NEW primitive class — it just has no outstanding blockers today.*
6. ~~**Rotated/composite fixtures come after IR wrapping.**~~ *Satisfied 2026-04-22. Rotated-plate detection landed with `TransformRotate` wrapping already in place. Remaining rotated work (cutouts on rotated plates, rotated-box detector) is listed as Immediate priorities #2 and #3 and can proceed in any order against the current IR.*
7. **"Beyond dimensional parity" items come after Immediate priorities are cleared.** They promote schema/ranking infrastructure, which pays off once the baseline detector is hitting more real parts. Running them earlier produces infrastructure for geometry the detector still can't handle.
8. **Phase 3 (ABC dataset integration) is the last investment.** Start it only after Track C's recall baseline shows real-world pass-rate has measurably lifted. Supervised data cannot productively train a detector that cannot yet represent the features being supervised.
9. **"Ongoing" items (tighter thresholds, user-assisted labeling, confidence gating) run cross-cutting.** They are not milestone-gated, but they should not overtake a blocked track — finish the blocked track first.

**Cadence rule (regression fence):** after each Track completes, re-run triage (Track A) and re-score recall (Track C) before starting the next Track. A regression in either stops forward motion until the regression is explained or reverted. This prevents one Track's optimization from silently hurting another's target.

**Parallelism summary (updated 2026-04-22 late):**

- Completed end-of-day 2026-04-22: Tracks A–D, IR wrapping, chamfer/fillet IR, rotated-plate detection, cylinder as positive primitive, negative-class fixtures, and richer inventory guidance.
- Critical path: Immediate #1 (Sketch2D + `rotate_extrude` Phase 1) → Immediate #2 (rotated cutouts on rotated plates) → Immediate #3 (rotated-box detector) → Immediate #4 (Sketch2D + `rotate_extrude` Phase 2 / profile classification) → Phase 3 linear extrude → Phase 4 composition detector → ABC dataset (Phase 3 of Real-World Feedback Loop).
- Parallel to anything: Ongoing items (threshold tightening, user-assisted labeling, confidence gating).
- Cadence rule still applies: after each Immediate priority closes, re-run triage and re-score recall before starting the next.
- Rule 5 (Boolean + Transform IR wrapping must precede new positive primitives) remains in force. The axisymmetric revolve detector is a new positive primitive class and inherits the existing `BooleanUnion` wrapping slot — no further IR prerequisite.
