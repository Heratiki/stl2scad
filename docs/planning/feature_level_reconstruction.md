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
- No `box_like_solid` primitive — pure axis-aligned cuboids (e.g. Test_Cube) produce only axis-pair features, never a parametric preview.

## Next Milestones

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

Reprioritized 2026-04-20. A 6-STL sample from a real FDM collection (`D:\3D Files\FDM`) produced a parametric SCAD preview for only 1 part; four of the other five were symmetric plates or boxes that fell through to `axis_boundary_plane_pair` only. Fixture pass-rate is no longer a proxy for real-world pass-rate — the synthetic corpus is axis-aligned and has sharp edges, while real mechanical parts almost always carry chamfers or fillets on broken edges.

1. **Finish tolerant plate/box detection** — simple edge-chamfered plates are now covered, but filleted variants and box/cuboid detection still need the same tolerance so broken outer edges do not collapse otherwise-obvious parametric bases back to boundary-plane-only output.
2. **Noise + real-world recall as a first-class metric** — add controlled-perturbation fixtures (vertex jitter, flipped normals, small non-manifold gaps) and a handful of real-world STLs with authored `expected_detection` counts, so "real-world recall" becomes a number we track alongside synthetic fixture pass-rate. Promoted from "Beyond dimensional parity" because synthetic-only coverage is now the dominant failure mode.
3. **Grid-pattern SCAD emission** — detector already emits `grid_hole_pattern` with full `grid_origin`/`grid_rows`/`grid_cols` metadata, but the preview emitter falls back to a hardcoded center list. Wire the existing metadata into nested row/column loops so grid-hole parts produce fully parametric SCAD.
4. **Expand beyond axis-aligned fixtures** — add rotated and more composite non-plate fixtures once the conservative baseline remains stable.
5. **Improve inventory-guided selection quality** — move beyond a binary whole-file mechanical/organic gate so inventory can contribute richer, detector-relevant prioritization.

### Beyond dimensional parity

Once the round-trip is asserting dimensions, the fixture pipeline becomes the backbone for the parametric-SCAD work. The natural follow-ons:

1. **Detector-native interpretation ranking** — schema-v2 fixtures and harness-side candidate ranking are now in place, including a real hollow-box ambiguity fixture. The next step is to make the detector emit ranked interpretation candidates directly so the fixture harness can compare declared ranking/confidence against detector-produced ranking/confidence, not only against observed feature-count matches.
2. **Negative-class fixtures** — add deliberately non-mechanical and ambiguous shapes (organic blobs, near-primitives that should NOT classify as primitives, L-brackets with and without a bracket primitive implemented) and assert the detector stays silent or falls through to polyhedron. Guards against detector over-reach as new primitives come online.
3. **Promote the manifest schema to a versioned contract** — `schema_version` already exists; start enforcing it on load and document the schema so third-party fixture authors (or future detectors) have a stable target.

(Noise-injection fixtures were promoted out of this section into "Immediate priorities" on 2026-04-20; see item 2 above.)

### Ongoing

1. Tighten hole/slot detectors against real files and add confidence thresholds for SCAD emission readiness.
2. Add targeted detectors for the most common candidate feature families.
3. Emit feature-based SCAD templates only when confidence is high; otherwise fall back.
4. Add optional user-assisted labeling for ambiguous features.
