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

## Current State Assessment (2026-04-27)

Four interconnected systems are now in place: feature inventory, feature graph, revolve recovery, and linear-extrude recovery. The full test suite passes (259 tests) in the project virtualenv across `test_feature_inventory.py`, `test_feature_graph.py`, `test_feature_fixtures.py`, `test_linear_extrude_recovery.py`, `test_revolve_recovery.py`, and the feature-specific CLI coverage in `test_cli.py`. CLI commands `feature-inventory`, `feature-graph`, and `feature-graph-from-inventory` are wired up with parallel worker support and progress reporting for directory scans, and `feature-graph` directory mode can now optionally inventory-prefilter before graph construction.

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

Detects plates, boxes, cylinders, rotated plates/boxes, through-holes, slots, repeated hole patterns (linear + grid), axisymmetric revolves, linear extrudes, and conservative disconnected planar/prismatic composite unions from raw STL geometry, then emits a SCAD preview when confidence is high enough.

**Strengths:**

- Conservative by design (0.70 confidence threshold) — avoids false positives
- Pattern detection (linear arrays, grids) is genuinely useful for mechanical parts
- Rotated plate/box recovery now gives the detector a path beyond world-axis-aligned fixtures
- `rotate_extrude()` and `linear_extrude()` recovery cover single-profile solids that are not well represented as simple boxes/plates/cylinders
- Conservative disconnected-component composition now emits `BooleanUnion` previews for multi-part planar/prismatic assemblies when every component independently clears confidence gates
- SCAD preview emission with parameterized variables produces editable output

**Limitations:**

- Pattern detection still depends on holes and slots being regular enough to survive STL tessellation noise.
- Current preview emission is still not the same thing as a production IR-to-SCAD emitter wired into the normal `convert` / `batch` / GUI workflows.
- Cutout support is strongest for through-holes and slots; blind holes, counterbores from mesh, countersinks, pockets, and notches remain open.
- Tolerant chamfer/fillet recognition preserves a base primitive, but edge kind and exact radius/distance recovery are not complete.
- Composition detection is still limited to conservative disconnected assemblies. Nested/containment-heavy subtraction shells, overlap ownership, and full mixed-feature composition with explicit positive/negative polarity still require a higher-level partitioning strategy.

## Real-World Feedback Loop (2026-04-22)

The 2026-04-20 sample made it clear that fixture pass-rate no longer predicts real-world pass-rate. The highest-ROI path toward the project's intent — parametric SCAD output for arbitrary user STLs — is a three-phase loop that goes "measure real failures → close the dominant pattern → expand with supervised data." The detailed items under *Immediate priorities* below are the tactical checklist; this section is the framing that explains their ordering.

### Phase 1: Triage loop over unlabeled real STLs (days)

Run a folder of real STLs (starting with `D:\3D Files\FDM`) through `feature-graph` and bucket the outcomes by detector result: produced a parametric preview, detected features but below confidence threshold, fell through to `axis_boundary_plane_pair` only, or fell through to polyhedron. Rank buckets by which broken-edge pattern or geometry style costs the most parts. The triage loop does not itself fix anything — it replaces guesswork about "which detector gap matters most" with ranked evidence drawn from the user's actual corpus. Cheap to build on top of the existing folder-mode `feature-graph` and the confidence scores the detector already emits.

This is distinct from *Immediate priority #2* ("real-world STLs with authored `expected_detection` counts"): triage works on unlabeled STLs, no hand-authored ground truth required. The two complement each other — triage identifies *which* real parts deserve the investment of authoring ground truth.

### Local and public reproducibility loop (2026-04-28)

The project should support three levels of reproducible real-world feedback. They are deliberately separate because the legal and engineering constraints are different.

1. **User-local corpus loop.** Users can run the detector against any STL folder they have rights to use locally, without committing the STLs or linking them from the repo. A local manifest under a gitignored path such as `.local/` should capture file path, sha256, file size, bounds, detector config version, optional user-authored labels, and notes. The user can then re-run the same local benchmark after detector changes and compare triage/recall deltas. This is valuable for project refinement even when the raw models are private or cannot be redistributed.
2. **Sanitized report loop.** Users may upstream aggregate results without the STLs: bucket counts, failure signatures, detector-family deltas, rounded dimensions, anonymized hash IDs, and representative notes. These reports are useful for prioritization, but they are not a hard merge gate because maintainers cannot independently reproduce private local files.
3. **Public batch loop.** Use a public dataset in small, deterministic chunks, preferably 100 STL files at a time, with a committed manifest that records source IDs, license strings, source URLs, sha256 hashes, and selection seed. The actual downloaded STL cache can remain gitignored. Anyone can recreate the batch from the manifest.

**Recommended public source:** [Thingi10K](https://huggingface.co/datasets/Thingi10K/Thingi10K) / [Thingi10K GitHub](https://github.com/Thingi10K/Thingi10K). It contains 10,000 real-world 3D-printing models, mostly STL, with per-model license metadata. For repo-safe batches, filter initially to public-domain-style entries (`Creative Commons - Public Domain Dedication`, `Public Domain`) and optionally permissive software-style entries (`BSD License`). CC-BY entries are usable only if attribution metadata is preserved carefully.

**Secondary public source:** [Smithsonian Open Access](https://www.si.edu/openaccess) / [Smithsonian 3D Open Access](https://3d.si.edu/collections/openaccesshighlights). CC0-designated 3D assets are legally clean, but they are usually glTF/glb/obj rather than STL and are less mechanically focused, so they are better as converted broad-geometry or organic/negative-class stress cases.

**Use with caution:** [NIH 3D](https://3d.nih.gov/) has open biomedical models, but licensing is per-entry and must be filtered. [ABC Dataset](https://deep-geometry.github.io/abc-dataset/) is technically excellent for CAD supervision, but model copyrights remain with creators and licensing flows through Onshape terms, so treat it as a later local/research corpus rather than a redistributable repo fixture source. ShapeNet is not a good fit for repo inclusion because access/use is research/education constrained and model copyrights remain with original creators.

Planned tooling:

```bash
# Private local reproducibility, no STL redistribution.
python scripts/create_local_corpus.py "D:\3D Files\FDM" --output .local/fdm_corpus.json
python scripts/build_feature_graph.py "D:\3D Files\FDM" --output artifacts/fdm_graphs.json --triage-output artifacts/fdm_triage.json
python scripts/summarize_feature_triage.py artifacts/fdm_triage.json --top 25
python scripts/score_local_corpus.py --manifest .local/fdm_corpus.json --output artifacts/fdm_score.json

# Public reproducibility from deterministic Thingi10K batches.
python scripts/import_thingi10k_batch.py --licenses "Creative Commons - Public Domain Dedication,Public Domain,BSD License" --limit 100 --seed 1 --output tests/data/thingi10k_batch_001_manifest.json
python scripts/materialize_thingi10k_batch.py --manifest tests/data/thingi10k_batch_001_manifest.json --cache .local/thingi10k
python scripts/score_thingi10k_batch.py --manifest tests/data/thingi10k_batch_001_manifest.json --cache .local/thingi10k --output artifacts/thingi10k_batch_001_score.json
```

The minimal user-local loop is now implemented by `scripts/create_local_corpus.py`,
`scripts/score_local_corpus.py`, and `stl2scad/tuning/local_corpus.py`. It records
private STL fingerprints, bounds, detector config version/config, and inventory
metadata; re-runs feature-graph triage; reports fingerprint drift; and computes
optional labeled recall when a local case has fixture-style `labels`.

### Automated in-memory improvement loop (future)

The script-based corpus loop above is the observable interface. The longer-term goal is an in-memory compute loop that keeps most intermediate state out of the filesystem, iterates over detector hypotheses, and only retains output that is relevant to review, approval, or reproducibility.

**Intent:** run a bounded local optimization/review cycle over a local corpus or deterministic public batch, measure whether candidate changes improve feature recovery, and produce review-ready implementation patches. A candidate that reaches the human/Frontier LLM review stage should already be in a state that can be added to the project directly: code changes, tests, fixture updates, generated golden files, scoring deltas, and rollback context included. Human or Frontier LLM review is an approval and verification step, not a request for the reviewer to finish implementation work.

**In-memory operating model:**

1. Load a corpus manifest plus a bounded set of STL meshes into memory, using an LRU cache when the corpus is larger than memory.
2. Run feature inventory, feature graph extraction, SCAD preview emission, and optional OpenSCAD preview round-trip checks without writing per-stage JSON for every file.
3. Score each candidate using multiple signals: preview-ready ratio, labeled-case correctness, geometric round-trip agreement, confidence stability, fixture regression status, and failure-bucket movement.
4. Generate and evaluate bounded hypotheses: detector config changes, confidence-gate changes, narrow detector-family patches, emitter patches, or new synthetic fixture proposals.
5. Keep only review-relevant retained artifacts: candidate patch, summary score delta, representative failure IDs/hashes, minimal anonymized geometric signatures, newly generated fixtures/golden files, logs needed to reproduce failures, and explicit rejection reasons for discarded candidates.
6. Discard irrelevant intermediate outputs by default: per-file transient graphs, temporary SCAD previews, temporary rendered STLs, low-scoring hypothesis traces, and verbose geometry dumps unless the candidate is promoted for review.
7. For promoted candidates, generate a visual review bundle: rendered source STL, rendered candidate SCAD output, visual diff/overlay, geometric metric summary, and the emitted SCAD code displayed alongside the render so reviewers can judge both shape fidelity and human editability.

**Review boundary:**

- The loop may use a local model for cheap summarization or clustering assistance, but a local model is not a correctness oracle.
- Frontier LLM review may be used for higher-quality code/design review, but it should receive a complete candidate patch and concise evidence bundle.
- Human approval should include a visual diff check between the rendered STL and rendered SCAD result, plus direct inspection of the generated SCAD code for readability, parameter naming, and ease of editing.
- Approval requires deterministic gates: fixture invariants, focused detector tests, local/public corpus score deltas, and any affected golden-output regeneration.
- The loop must not silently edit checked-in fixture expectations, lower confidence thresholds to inflate preview counts, commit private corpus data, or accept unlabeled local improvements that regress labeled or fixture-backed cases.

**Maintainability boundary:** keep this engine outside detector internals, e.g. under `stl2scad/corpus/` or `stl2scad/improvement_loop/`. The engine may import detectors and emit patches, but detectors should remain deterministic, directly testable modules. If profiling later shows Python orchestration is too slow, move hot geometry kernels behind narrow Rust/C/C++ extension boundaries rather than rewriting the policy/review layer.

### Phase 2: Close the dominant real-world failure pattern (weeks)

Extend the tolerant-detection approach that already works for `plate_plain_chamfered_edges` to whichever geometry the Phase 1 triage ranks highest. On the 2026-04-20 sample that is most likely filleted plate and box edges, which would satisfy *Immediate priority #1*. Each pattern closed moves real-world pass-rate directly; triage re-run after each closure tells us whether the fix generalized and what the next dominant pattern is.

### Phase 3: ABC dataset as a supervised corpus (months)

The [ABC Dataset](https://deep-geometry.github.io/abc-dataset/) (~1M CAD models with STEP/B-rep ground truth, Koch et al. 2019) is the only public dataset that supplies real parametric supervision for what this project emits. STEP files carry feature trees (holes, fillets, extrusions) that can be compared directly against detector output. Wiring it in is weeks of STEP-parser work per feature family, so this is a phase-3 investment — valuable only once Phase 2 has lifted real-world pass-rate meaningfully above today's baseline, because extra supervision cannot be consumed productively while common real-world geometry still fails to detect at all.

### Traps to avoid

- **Do not run `tune_detector` against the synthetic fixture corpus as the project's optimization target.** With synthetic pass-rate decoupled from real-world pass-rate, tuning in this regime overfits the synthetic distribution at the cost of real parts. Defer tuning until a real-world-weighted scoring function exists (scored via Phase 1 triage data plus the labeled real-world fixtures from *Immediate priority #2*).
- **Do not start Phase 3 before Phase 2 raises the detector's floor.** Supervised data only helps a detector that can already represent the features being supervised.

## Next Milestones

### Recently completed (2026-04-29)

- **Composite planar/prismatic union pass (disconnected components)** — `feature_graph.py` now attempts a conservative composition pass after single-solid detectors. It splits meshes into connected components, selects per-component high-confidence planar/prismatic solids (`plate_like_solid`, `box_like_solid`, `cylinder_like_solid`, `linear_extrude_solid`), tags them as `composite_component`, and emits a top-level `BooleanUnion` interpretation in `ir_tree` when at least two components are valid.
- **Containment guard for ambiguous subtraction-like composites** — the composition pass rejects high-containment component layouts (`max_containment > 0.50`) so nested shell-like cases are not incorrectly promoted as unions.
- **Composite-path regression coverage** — `tests/test_feature_graph.py` now includes `test_feature_graph_scad_preview_emits_composite_prismatic_union` and `test_feature_graph_composite_path_declines_subtraction_shell`; focused detector tests and fixture invariants pass (`tests/test_feature_graph.py`, `tests/test_feature_fixtures.py`).

### Recently completed (2026-04-27)

- **Phase 3 — `linear_extrude` recovery** (`stl2scad/core/linear_extrude_recovery.py` wired into `feature_graph.py`). `detect_linear_extrude_solid` runs after all native primitive detectors fail (revolve → cylinder → plate → box → rotated-plate → rotated-box → linear-extrude dispatch order). Cross-section consistency gate + axis-quality gate + confidence threshold prevent false positives on spheres and tori. IR tree produces `ExtrudeLinear { Sketch2D(polygon) }` wrapped in `TransformRotate` when off-axis. SCAD preview emitter produces `linear_extrude(height=...) polygon([...])` calls. Fixtures updated: `negative_hex_prism` (hex prisms are correctly identified as linear extrusions), `l_bracket_plain` (L-shaped cross-section extruded along Y). All 259 tests pass.

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

### Immediate priorities (2026-04-29)

The 2026-04-27 active items have landed in current `main`: revolve profile classification/primitive upgrades, rotated-plate local-frame cutouts, rotated-box positive detection, and rotated-box local-frame hole extraction. The focused detector slice (`tests/test_feature_fixtures.py`, `tests/test_feature_graph.py`, `tests/test_revolve_recovery.py`, `tests/test_linear_extrude_recovery.py`) passes on the current checkout. The remaining work is now about making those capabilities useful on broad, messy, user-provided STL collections and turning the feature graph into full production SCAD output.

1. ~~**Integrate feature-graph/IR emission into normal conversion.**~~ *Complete (2026-04-29).* Feature-graph is now the primary parametric path in `converter.py::stl2scad()`: it runs first on every `--parametric` invocation. Legacy primitive-recognition backends (native/trimesh_manifold/cgal) run as fallback when feature-graph produces no high-confidence output. GUI, CLI, and batch paths all inherit this automatically since they call `stl2scad()`. Known limitation: `box_like_solid` can false-positive on hollow shells (tracked under Immediate priority #3).
2. **Build the user-local, Thingi10K, and in-memory improvement loops.** Add `create_local_corpus`, `score_local_corpus`, `import_thingi10k_batch`, `materialize_thingi10k_batch`, and `score_thingi10k_batch` tooling first, then layer an in-memory improvement engine over the same scoring contracts. The local loop gives user-specific reproducibility without redistributing models; the Thingi10K loop gives public, deterministic 100-file batches for shared regression runs; the in-memory loop turns high-confidence findings into review-ready patches while retaining only artifacts needed for approval.
3. **Fill missing negative-feature detectors.** Counterbore fixture generation exists, but counterbore recovery from raw meshes is not complete. Add blind holes, counterbores, countersinks, rectangular pockets, notches, and face-local cutouts with explicit boolean polarity under `BooleanDifference`.
4. **Promote tolerant edge recognition into editable edge treatment.** Today chamfered/filleted plates and boxes are recognized tolerantly and represented by a coarse `ChamferOrFilletEdge` annotation. Distinguish chamfer vs fillet, recover radius/distance, and emit editable SCAD modules or approximations.
5. **Add structural feature families.** Shells/enclosure halves, bosses, ribs/webs, tabs/flanges, and brackets are the next major class of CAD intent that single primitive/extrude/revolve detectors do not capture.
6. **Expand pattern recovery.** Linear and grid hole patterns exist. Add radial patterns, mirror patterns, and repeated non-hole feature patterns so emitted SCAD uses loops/modules rather than duplicated literals.
7. **Expand composition detection beyond disconnected unions.** A conservative disconnected planar/prismatic union pass is now shipped. Remaining work is ownership and polarity recovery for overlapping/nested components (especially subtraction shells), mixed connected-feature partitioning, and cross-feature parametric relationship preservation in one editable model.
8. **Make interpretation ranking detector-native.** Schema-v2 fixtures and harness-side ranking exist, and `ir_tree` carries an `Interpretation` wrapper. The detector should emit ranked alternative interpretations directly so ambiguity can be evaluated without relying only on flat feature-count matches.
9. **Document fixture and corpus schemas.** `schema_version` is enforced, but third-party fixture authors and future corpus contributors need stable schema documentation for synthetic fixtures, local corpus manifests, Thingi10K batch manifests, and sanitized reports.
10. **Defer ABC/STEP supervision until the real-world floor is higher.** ABC remains valuable for later B-rep/STEP supervision, but it should follow the local/Thingi10K loop and common-feature detector expansion.

### Multi-feature composition target

The end-state for full parametric SCAD output is not only recognizing one fixture-like feature in an STL. The detector needs to recognize multiple individual feature families within one mesh, infer how they combine, and emit a single editable SCAD file that preserves the part's functional relationships.

Target behavior:

1. **Segment a single STL into candidate design features.** Identify base solids, added features, subtractive cutouts, edge treatments, and repeated patterns in local coordinate frames.
2. **Assign polarity and ownership.** Decide which features are positive material (`union`) and which are negative material (`difference`), and attach cutouts to the correct parent feature or face.
3. **Recover constraints and parameters.** Prefer named dimensions and relationships over literal coordinates: thickness, hole diameter, spacing, offsets from edges, pattern counts, boss radius, rib thickness, pocket depth, fillet radius, and local axes.
4. **Compose features into one IR tree.** Use `BooleanUnion`, `BooleanDifference`, `Transform*`, `Pattern*`, `ExtrudeLinear`, `ExtrudeRevolve`, and primitive nodes so each detected feature remains independently editable while still reconstructing the whole part.
5. **Emit maintainable SCAD.** Generate modules and variables that expose functional dimensions rather than only reproducing mesh coordinates. A user should be able to edit a hole diameter, plate thickness, pattern spacing, boss height, or shell thickness without manually repairing unrelated geometry.
6. **Verify the composed result.** Render the emitted SCAD, compare it back to the source STL, and require both geometric agreement and detector re-recognition of the intended editable features.

This implies a shift from "best single primitive" detection to "feature assembly" detection. A simple example is a plate with a boss, two slots, a grid of holes, chamfered perimeter, and a side notch: the target SCAD is one `difference()`/`union()` assembly with named parameters, not six independent previews or a polyhedron fallback.

### Beyond dimensional parity

The detector output now includes a tree-shaped `ir_tree`, so the next step is not just adding dimensions to existing nodes. The project needs higher-level design-intent recovery:

1. **Detector-native interpretation ranking** — schema-v2 fixtures and harness-side candidate ranking are already in place, including a real hollow-box ambiguity fixture. Next step: make the detector emit ranked `Interpretation` candidates directly (per [detector_ir.md](detector_ir.md)) so the fixture harness can compare declared ranking/confidence against detector-produced ranking/confidence, not only against observed feature-count matches.
2. **Manifest schema as a versioned contract** — `schema_version` is already enforced on load; next is documenting the schema so third-party fixture authors (or future detectors) have a stable target.
3. **Production IR-to-SCAD emitter** — preview emission proves the feature graph can produce editable SCAD snippets. A production emitter should consume `ir_tree`, factor reusable modules/variables/patterns, and decide when to emit feature SCAD versus polyhedron fallback.
4. ~~**Tier-2 primitive expansion** — cone/frustum, sphere, ellipsoid.~~ *Reframed 2026-04-22: absorbed into Immediate priority #1 / #4 (Sketch2D + `rotate_extrude` recovery). Each tier-2 primitive is a special case of a solid of revolution — rectangle profile → cylinder, triangle → cone, semicircle → sphere, trapezoid → frustum. Building the axisymmetric pipeline with a profile classifier gets all four primitives as a consequence instead of as four separate detectors.*
5. ~~**Sketch2D + ExtrudeLinear / ExtrudeRevolve recovery from mesh cross-sections**~~ — *Promoted 2026-04-22 from this list to the active work package. Phase 1 (axisymmetric `rotate_extrude`) is complete (2026-04-24). Phase 3 (linear extrude) is complete (2026-04-27). Phase 2 (profile classification) is Immediate priority #4.*

(Noise-injection fixtures were promoted out of this section on 2026-04-20 and landed via Track C on 2026-04-22.)
(Negative-class fixtures landed 2026-04-20 as `negative_sphere` and `negative_torus`; closed as a standing priority. Re-apply the pattern as new primitives come online via the axisymmetric pipeline.)

### Ongoing

1. Tighten hole/slot/cutout detectors against real files and add confidence thresholds for SCAD emission readiness.
2. Add targeted detectors for the most common feature families identified by local and Thingi10K triage.
3. Emit feature-based SCAD templates only when confidence is high; otherwise fall back.
4. Add optional user-assisted labeling for ambiguous local corpus cases.
5. Re-run local corpus and public batch scores after every detector family lands.

## Previous Work Package — Phase 2: Profile Classification & Primitive Upgrade

**Status:** Complete in current `main` (verified 2026-04-28). Phase 1 and Phase 3 are also shipped.

**What landed:** Given a detected `revolve_solid` with axial profile `polygon(pts)`, the detector classifies clean 2D profile shapes (right triangle → cone/frustum, semicircle → sphere, rectangle → cylinder, trapezoid → frustum/cone-style `cylinder(r1=..., r2=...)`) and emits compact SCAD instead of generic `rotate_extrude()` when confidence is high. This unifies cone/sphere/frustum/cylinder detection under one axisymmetric pipeline rather than four separate detectors.

**Acceptance criteria:**
1. At least three profile shapes (cone, sphere, cylinder) are classified and emit their primitive form in both IR and SCAD. ✓
2. Fixtures with `phase2_expected_primitive` cover cylinder, cone/frustum, and sphere-style upgrades. ✓
3. Phase 2 fixtures pass preview round-trip assertions. ✓
4. No regressions in existing revolve, linear-extrude, or axis-aligned detection tests. ✓
5. The three fixture invariants from [CLAUDE.md](../../CLAUDE.md) remain intact. ✓

**Design notes:**
- Profile classification is deterministic (only shape, not noise): polygon edge count, angle distribution, curvature (via residuals from line fit), convexity.
- Reserve high confidence for "clean" matches (e.g., exactly 3 points for right triangle, semicircular arc for sphere); lower confidence for ambiguous or noisy profiles.
- When confidence is below threshold, fall back to generic `rotate_extrude()` in preview output.
- Add profile-classification test coverage in `test_revolve_recovery.py` for representative polygon shapes.

---

## Prior Work Packages — Phase 1 & Phase 3: Axisymmetric & Linear Extrude Recovery

**Status:** Complete (Phase 1: 2026-04-24, Phase 3: 2026-04-27).

### Phase 1: Axisymmetric `rotate_extrude` recovery

**Phase 1 Status:** Complete (2026-04-24). Tasks 1–19 are complete. The cylinder manifest flip is landed, positive `revolve_*` and negative `non_revolve_*` fixtures are in the checked-in SCAD library, revolve confidence/profile/preview round-trip assertions are in place, `detector_ir.md` marks `ExtrudeRevolve` + `Sketch2D(polygon)` as detected, and the test suite passes (`259 tests`).

**Blocking issue:** resolved. OpenSCAD-rendered cylinder STLs now pass the revolve detector.

**Full spec:** [docs/superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md](../superpowers/specs/2026-04-22-rotate-extrude-and-sketch2d-recovery-design.md).

**One-line summary:** axisymmetric meshes produce `rotate_extrude() polygon([...])` SCAD output. A Christmas-tree ornament becomes one sawtooth profile polygon and one revolve, not N stacked cones.

**Why this is the critical path now:** the previous work package (rotated fixtures, cylinder as positive primitive, inventory guidance, negative-class fixtures) is complete. Building tier-2 primitives (cone/frustum/sphere/ellipsoid) as individual detectors duplicates signal the axisymmetric pipeline already produces — one detector subsumes all four. Sketch2D + `rotate_extrude` was previously listed under "Beyond dimensional parity #4" as the single largest outstanding roadmap win; promoting it ahead of individual tier-2 detectors avoids throwaway work.

**Phase boundaries:**
- **Phase 1:** axisymmetry test + radial slice + profile polygon + `rotate_extrude()` emission. Every axisymmetric solid emits as a polygon revolve. ✓ Complete (2026-04-24).
- **Phase 2:** profile classifier upgrades recognizable polygons to `cylinder()` / `cone()` / `sphere()` / frustum. ✓ Complete in current `main` (verified 2026-04-28).
- **Phase 3:** linear-extrude detector (translational symmetry instead of rotational). ✓ Complete (2026-04-27).
- **Phase 4:** composition detector for meshes that are neither single-revolve nor single-extrude but compositions of such. Initial disconnected planar/prismatic union support is now in `main`; remaining scope is overlap/subtraction ownership and connected mixed-feature partitioning.

**Acceptance criteria for Phase 1:**
1. Every Phase 1 `revolve_*` fixture round-trips with its expected profile within tolerance. ✓
2. A Christmas-tree-shaped input mesh emits a `rotate_extrude() polygon([...])` preview with fewer than 20 polygon points. ✓
3. No regressions in existing axis-aligned plate / box / cylinder detection. ✓
4. The three fixture invariants from [CLAUDE.md](../../CLAUDE.md) remain intact. ✓

### Phase 3: Linear `linear_extrude` recovery

**Phase 3 Status:** Complete (2026-04-27). `stl2scad/core/linear_extrude_recovery.py` is wired into `_build_feature_graph` with full gate pipeline.

**What's landed:** `detect_linear_extrude_solid` runs after all native primitive detectors fail (revolve → cylinder → plate → box → rotated-plate → rotated-box → linear-extrude dispatch order). Cross-section consistency gate + axis-quality gate + confidence threshold prevent false positives on spheres and tori. IR tree produces `ExtrudeLinear { Sketch2D(polygon) }` wrapped in `TransformRotate` when off-axis. SCAD preview emitter produces `linear_extrude(height=...) polygon([...])` calls. Fixtures: `negative_hex_prism` (hex prisms are correctly identified as linear extrusions), `l_bracket_plain` (L-shaped cross-section extruded along Y). All 259 tests pass.

**What remains:** none for Phase 3. Phase 2 profile classification is also complete in current `main`; Phase 4 has started with disconnected planar/prismatic unions, and the next work is overlap/subtraction ownership plus connected mixed-feature composition.

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
- **Critical path: ~~Immediate #1 (Sketch2D + `rotate_extrude` Phase 1)~~ → Immediate #2 (rotated cutouts on rotated plates) → Immediate #3 (rotated-box detector) → Immediate #4 (Sketch2D + `rotate_extrude` Phase 2 / profile classification) → ~~Phase 3 linear extrude~~ → Phase 4 composition detector → ABC dataset (Phase 3 of Real-World Feedback Loop).
- Parallel to anything: Ongoing items (threshold tightening, user-assisted labeling, confidence gating).
- Cadence rule still applies: after each Immediate priority closes, re-run triage and re-score recall before starting the next.
- Rule 5 (Boolean + Transform IR wrapping must precede new positive primitives) remains in force. The axisymmetric revolve detector is a new positive primitive class and inherits the existing `BooleanUnion` wrapping slot — no further IR prerequisite.

## Parallel Coding Agent Plan (2026-04-27)

This section updates the execution model from sequential tracks to a bounded parallel plan. It is intentionally scoped so multiple coding agents can work concurrently with low merge conflict risk while preserving the fixture and recall gates.

### Objectives for this cycle

1. Close Immediate priority #2 (rotated cutouts on rotated plates).
2. Close Immediate priority #3 (rotated-box positive detector).
3. Start Immediate priority #4 (Phase 2 profile classification for revolve outputs) without blocking #2/#3.
4. Keep triage and real-world recall merge-gate green at every integration point.

### Agent workstream split

#### Agent A — Rotated Cutout Local-Frame Extraction (Immediate #2)

**Primary files:**
- `stl2scad/core/feature_graph.py`
- `tests/test_feature_graph.py`
- `tests/test_feature_fixtures.py`
- `tests/data/feature_fixtures_manifest.json`

**Scope:**
1. Extend cutout candidate extraction to run in plate-local `(u, v, t)` coordinates when `detected_via == "rotated_plate"`.
2. Detect rotated holes, slots, and linear/grid patterns using local-frame geometry, then map metadata back to world coordinates for IR and preview.
3. Preserve existing axis-aligned path behavior bit-for-bit for non-rotated plates.

**Deliverables:**
1. Local-frame extraction helper(s) with deterministic axis/sign conventions.
2. New rotated-fixture manifest entries for hole, slot, and at least one pattern case on rotated plates.
3. Passing fixture round-trip (counts + dimensions) and preview round-trip for the new rotated cases.

**Out of scope:**
- Rotated-box positive detection logic.
- Revolve profile classification.

#### Agent B — Rotated Box Positive Detection + Preview (Immediate #3)

**Primary files:**
- `stl2scad/core/feature_graph.py`
- `tests/test_feature_graph.py`
- `tests/test_feature_fixtures.py`
- `tests/data/feature_fixtures_manifest.json`

**Scope:**
1. Add positive rotated-box detection using dominant orthogonal normal-pair recovery and oriented extents.
2. Emit IR nodes with transform wrapping compatible with existing `Boolean*` + `TransformRotate` conventions.
3. Enable parametric preview emission for high-confidence rotated boxes (base solid first; cutouts may remain conservative if confidence is low).

**Deliverables:**
1. Positive `box_like_solid` rotated detection path with confidence gating.
2. Promotion of `box_z_through_hole_rotated_z25` from negative to positive expectation (or replacement with equivalent positive fixture if geometry requires).
3. Stable preview output for rotated boxes and passing round-trip assertions where confidence criteria are met.

**Out of scope:**
- Rotated plate local-frame cutout extraction internals.
- Revolve Phase 2 classifier decisions.

#### Agent C — Revolve Phase 2 Profile Classifier (Immediate #4, partial)

**Primary files:**
- `stl2scad/core/revolve_recovery.py`
- `stl2scad/core/feature_graph.py`
- `tests/test_feature_graph.py`
- `tests/test_feature_fixtures.py`

**Scope:**
1. Add profile-shape classification over recovered revolve polygon profiles.
2. Promote high-confidence profile classes to primitive-specific preview emission (`cylinder()`, cone/frustum form, `sphere()`), while preserving `rotate_extrude()` fallback.
3. Keep all annular and non-simple profiles on conservative `rotate_extrude()` output unless strict classifier confidence is met.

**Deliverables:**
1. Classifier module/functions with explicit thresholds and rationale comments.
2. Tests covering true-positive class upgrades and guardrails against vase-like false upgrades.
3. No regression in existing revolve fixtures and preview round-trip checks.

**Out of scope:**
- New fixture families unrelated to revolve classification.
- Inventory/triage schema changes.

#### Agent D — Regression Fence and Scoring Steward (cross-cutting)

**Primary files/scripts:**
- `scripts/build_feature_graph.py`
- `scripts/summarize_feature_triage.py`
- `scripts/score_real_world_corpus.py`
- `tests/test_score_real_world_corpus.py`
- `artifacts/real_world_recall_baseline.json` (update only if explicitly approved)

**Scope:**
1. Keep triage and recall tooling stable while Agents A/B/C land.
2. Run cadence checks after each integration branch merge and summarize deltas.
3. Flag regressions with culprit commit ranges and bucket-level impact.

**Deliverables:**
1. Per-merge triage delta note (`parametric_preview`, `feature_graph_no_preview`, `axis_pairs_only`, `polyhedron_fallback`).
2. Per-merge recall merge-gate result and feature-family deltas.
3. Optional tooling hardening only when needed to prevent flaky gate behavior.

**Out of scope:**
- Detector feature changes unless required to repair gate correctness.

### Conflict-avoidance contract

1. One-owner rule for core functions per branch:
   - Agent A owns rotated plate cutout path and related helpers.
   - Agent B owns rotated box detector entry points and rotated-box preview branch.
   - Agent C owns revolve classifier entry points and promotion logic.
2. Shared-file etiquette for `feature_graph.py`:
   - each agent edits only their designated section boundaries;
   - helper signatures added by one agent must be consumed, not rewritten, by others.
3. Fixture manifest etiquette:
   - only one agent regenerates and commits `.scad` fixture outputs for a given merge slice to preserve byte-exact diffs.

### Branch and merge topology

1. `agent/a-rotated-cutouts`
2. `agent/b-rotated-box`
3. `agent/c-revolve-phase2`
4. `agent/d-regression-fence`
5. Integration branch: `integration/parallel-2026-04-27`

Merge sequence into integration branch:
1. Agent A and Agent B in parallel (no dependency).
2. Agent C rebased onto integration after A/B land (to absorb shared `feature_graph.py` shape changes).
3. Agent D runs gates and publishes deltas after each merge.
4. Final squash or linear merge to `main` only after all required gates pass.

### Required gate runbook (after each merge)

1. `python -m pytest tests/test_feature_graph.py -q`
2. `python -m pytest tests/test_feature_fixtures.py -v`
3. `python -m pytest tests/test_real_world_corpus.py -q`
4. `python scripts/build_feature_graph.py "D:\3D Files\FDM" --output artifacts/fdm_graphs.json --triage-output artifacts/feature_graph_triage.json`
5. `python scripts/summarize_feature_triage.py artifacts/feature_graph_triage.json --top 10`
6. `python scripts/score_real_world_corpus.py --manifest tests/data/real_world_corpus_manifest.json --baseline artifacts/real_world_recall_baseline.json --output artifacts/real_world_recall_maintainer.json --delta-output artifacts/real_world_recall_delta_maintainer.json --merge-gate`

### Merge acceptance criteria for this parallel cycle

1. Immediate priorities #2 and #3 are closed with fixtures and round-trip tests.
2. Immediate priority #4 has at least one profile-class promotion path merged behind conservative thresholds, with no revolve regressions.
3. No fixture invariant regressions:
   - byte-exact regeneration
   - dimensional round-trip
   - roadmap stress-case coverage
4. Real-world merge-gate passes (or, if baseline update is intended, baseline change is reviewed and approved in the same PR).
