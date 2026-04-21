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

For a single STL with a high-confidence plate/hole graph, the script can also write an experimental SCAD preview:

```bash
python scripts/build_feature_graph.py input.stl --output artifacts/input_feature_graph.json --scad-preview artifacts/input_feature_preview.scad
```

## Current State Assessment (2026-04-13)

Three interconnected systems are now in place: feature inventory, feature graph, and manifest-driven feature fixtures. The focused feature test slice currently passes in the project virtualenv across `test_feature_inventory.py`, `test_feature_graph.py`, `test_feature_fixtures.py`, and the feature-specific CLI coverage in `test_cli.py`. CLI commands `feature-inventory` and `feature-graph` are wired up with parallel worker support and progress reporting for directory scans.

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
- No integration yet with the feature graph or reconstruction pipeline — informational only

### Feature Graph (`stl2scad/core/feature_graph.py`) — High value

Detects axis-aligned boxes, through-holes, slots, and repeated hole patterns (linear + grid) from raw STL geometry, then emits a SCAD preview.

**Strengths:**

- Conservative by design (0.70 confidence threshold) — avoids false positives
- Pattern detection (linear arrays, grids) is genuinely useful for mechanical parts
- SCAD preview emission with parameterized variables produces editable output

**Limitations:**

- Only handles axis-aligned geometry — rotated features are invisible
- Pattern detection depends on hole centers being near-exactly spaced; real-world STLs from meshed CAD may have enough floating-point noise to break it

## Next Milestones

### Recently completed (2026-04-20)

- **Dimensional round-trip assertions** — `test_feature_fixture_round_trip_detection` now compares detected feature dimensions against the manifest within per-field tolerances (hole diameter/center, slot width/length, counterbore through/bore/depth, plate and box extents, linear/grid pattern origin/step/spacing).
- **Counterbore depth generator fix** — `counterbore_hole` module now takes explicit `plate_thickness` and anchors the bore at `plate_thickness - bore_depth`, eliminating the compounded 0.1mm offset. All 11 affected `.scad` fixtures were regenerated.
- **CI-hard-fail for missing OpenSCAD** — `test_feature_fixture_round_trip_detection` fails (no longer silently skips) when `CI=true` and the OpenSCAD binary is unavailable.
- **Manifest `schema_version` enforcement** — `load_feature_fixture_manifest` rejects any manifest whose schema_version is not 1, with a dedicated negative test.
- **Parametric preview round-trip** — SCAD previews now declare named variables for supported plate geometry and cutouts, and `test_feature_fixture_preview_round_trip_detection` re-renders those previews to STL and re-checks detector counts plus supported dimensions.

### Immediate priorities

1. **Connect inventory -> graph** — the inventory and feature graph are currently independent pipelines. Have the inventory pre-filter files and feed likely-mechanical candidates into the feature graph to complete the workflow.
2. **Expand beyond axis-aligned fixtures** — add rotated and more composite non-plate fixtures once the conservative baseline remains stable.
3. **Tighten edge-case coverage** — keep adding tolerance-boundary geometry and multi-pattern plates that mirror real-world noisy CAD exports.

### Beyond dimensional parity

Once the round-trip is asserting dimensions, the fixture pipeline becomes the backbone for the parametric-SCAD work. The natural follow-ons:

1. **Confidence-scored candidate fixtures** — introduce manifest entries that declare *multiple* valid interpretations (e.g., hollow box = one `difference()` of two cubes OR six wall slabs) and an expected ranking. The detector's ranked output must put the intended interpretation at the top with a confidence above threshold. This turns the fixture system into the ground truth for the interactive-selection modes already described in the long-term vision.
2. **Negative-class fixtures** — add deliberately non-mechanical and ambiguous shapes (organic blobs, near-primitives that should NOT classify as primitives, L-brackets with and without a bracket primitive implemented) and assert the detector stays silent or falls through to polyhedron. Guards against detector over-reach as new primitives come online.
3. **Noise-injection fixtures** — generate the manifest STLs with controlled perturbation (vertex jitter, normal flipping on a fraction of triangles, small non-manifold gaps) and assert the detector still produces the right feature graph. Real CAD-exported STLs aren't pristine; this closes the gap between synthetic fixtures and field data.
4. **Promote the manifest schema to a versioned contract** — `schema_version` already exists; start enforcing it on load and document the schema so third-party fixture authors (or future detectors) have a stable target.

### Ongoing

1. Tighten hole/slot detectors against real files and add confidence thresholds for SCAD emission readiness.
2. Add targeted detectors for the most common candidate feature families.
3. Emit feature-based SCAD templates only when confidence is high; otherwise fall back.
4. Add optional user-assisted labeling for ambiguous features.
