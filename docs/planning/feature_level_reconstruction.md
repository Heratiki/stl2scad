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
- 5 fixture cases: plain plate, single hole, 2-hole linear pattern, 2x3 grid, slot

**Limitations:**

- Only supports `plate` fixture type — no boxes, cylinders, or freeform composites
- 5 test cases are a good start but thin — no edge cases like very small holes, oblique slots, mixed patterns on one plate, or tolerance-boundary geometry
- `expected_detection` counts are manually authored, so they're only as good as the author's understanding of what the detector should find

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

### Immediate priorities

1. **Expand fixture variety** — the 5 current plate cases don't stress the detector much. Add mixed-feature plates (holes + slots on one plate), near-boundary holes, varying plate aspect ratios, and very small/large hole diameters.
2. **Non-plate fixture types** — extend beyond plates to boxes-with-holes, L-brackets, etc. to exercise the feature graph's box detection path.
3. **Connect inventory -> graph** — the inventory and feature graph are currently independent pipelines. Have the inventory pre-filter files and feed likely-mechanical candidates into the feature graph to complete the workflow.

### Ongoing

1. Tighten hole/slot detectors against real files and add confidence thresholds for SCAD emission readiness.
2. Add targeted detectors for the most common candidate feature families.
3. Emit feature-based SCAD templates only when confidence is high; otherwise fall back.
4. Add optional user-assisted labeling for ambiguous features.
