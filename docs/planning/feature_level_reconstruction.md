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

`scripts/build_feature_graph.py` builds the first intermediate feature graph. It currently extracts conservative axis-aligned boundary plane pairs and high-confidence `box_like_solid` / `plate_like_solid` candidates.

Example:

```bash
python scripts/build_feature_graph.py "C:\Users\herat\OneDrive\3D Files" --output artifacts/feature_graph_onedrive.json --max-files 100
```

## Next Milestones
1. Run the inventory against the real STL collection and review aggregate signals.
2. Add targeted detectors for the most common candidate feature families.
3. Generate an intermediate feature graph before SCAD emission.
4. Emit feature-based SCAD templates only when confidence is high; otherwise fall back.
5. Add optional user-assisted labeling for ambiguous features.
