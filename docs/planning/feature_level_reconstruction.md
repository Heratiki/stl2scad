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

## Next Milestones
1. Run the inventory against the real STL collection and review aggregate signals.
2. Tighten hole/slot detectors against real files and add confidence thresholds for SCAD emission readiness.
3. Add targeted detectors for the most common candidate feature families.
4. Generate an intermediate feature graph before SCAD emission.
5. Emit feature-based SCAD templates only when confidence is high; otherwise fall back.
6. Add optional user-assisted labeling for ambiguous features.
