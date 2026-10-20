# Composite bracket: first target for the segmentation pipeline

Status: spec, 2026-10-20. Source: the failure analysis in [CLAUDE.md](../../CLAUDE.md).

## Purpose

The whole-mesh detectors reject real parts. This bracket is the first part that the
new pipeline must round-trip through steps 1–4. The bracket has one example of each
unsolved problem: a feature that adds material (boss), a feature that removes material
(blind hole), and a fillet. A second variant has a rotation that is not on a world axis.

Do not tune the old detectors to pass this target. The target is for the new pipeline.

## Files

| File | Content |
|---|---|
| `tests/data/segmentation/composite_bracket.scad` | The part, hand-written. It is not generated from the fixture manifest. |
| `tests/data/segmentation/composite_bracket_rotated.scad` | The same part, `rotate([17, 31, 9]) translate([-20, -15, -17.5])`. |
| `tests/data/segmentation/composite_bracket_expected.json` | Ground truth: 13 faces, 25 edges, 4 features, volume, tolerances. |
| `tests/test_segmentation_bracket.py` | Harness tests (pass now) and target tests (strict xfail now). |

The 96-fixture manifest and its three invariants do not change.

## Geometry (part frame, mm, `$fn = 64`)

| Feature | Definition | Polarity |
|---|---|---|
| Base | `[0,40] × [0,30] × [0,5]` | additive |
| Wall | `[0,5] × [0,30] × [0,35]` | additive |
| Fillet | R3, axis Y, center line `(8, y, 8)`, between base top and wall inner face | additive |
| Boss | Ø12, axis Z at `(25, 15)`, from z = 5 to z = 11 | additive |
| Blind hole | Ø5, axis Z at `(34, 24)`, from z = 5 down to z = 2 | subtractive |

Volume: 11177.62 mm³. The mesh from OpenSCAD agrees within 0.1 %.

Faces: 10 planes and 3 cylinders. The fillet and the hole wall are concave. The boss
side is convex. The fillet meets the base top and the wall inner face on tangent edges.
The boss foot edge and the hole floor edge are concave. All other edges are convex.

## Acceptance

The pipeline passes when these tests pass for both variants, with no change to the tolerances:

1. `test_segmentation_recovers_faces_and_edges`: 13 faces, each of the correct kind.
   - Plane normal within 1°, plane offset within 0.05 mm.
   - Cylinder axis within 1°, cylinder radius within 2 %.
   - Cylinder convexity and every edge convexity are correct.
2. `test_features_recovered_with_polarity_and_hausdorff`: the four features have the correct polarity, and radius, height and depth are within 2 %. The Hausdorff distance from the output to the input mesh is less than 0.05 mm.

3. `test_emitted_scad_is_labeled_and_adjustable`: the emitted SCAD passes the gate (below). It has
   Customizer groups and ranges, and it has the parameters `boss_1_height`, `blind_hole_1_depth` and
   `fillet_1_radius`. When `boss_1_height` changes from 6 to 9, only the boss region of the
   rendered part changes.

When a target test passes, its strict xfail fails. Then remove the marker.

## Output decisions (agreed 2026-10-20)

| Area | Decision |
|---|---|
| Adjustable | Feature parameters. Edge treatments (chamfer, full round) come later. The fillet radius is a parameter now. |
| Customizer | `/* [Group] */` headings and `// [min:step:max]` ranges. An `assert()` stops a render that breaks a link between values, for example `blind_hole_1_depth < base_thickness`. |
| Placement | Each feature is relative to its host face. When `base_thickness` changes, the boss moves with the top face. |
| Remainder | All or nothing. If the output fails the gate, the full part is a polyhedron. |
| Gate | Hausdorff distance from `stl2scad/core/verification/metrics.py`, with an absolute limit: the larger of 0.05 mm and 0.1 % of the bounding-box diagonal. |
| Snapping | Use the coarsest round value (1, 0.1 or 0.01 mm) that still passes the gate. Keep the raw value in a comment. |
| Frame | Parameters are in the part frame. One `multmatrix()` at the top puts the part back in its position. |
| IR | Typed frozen dataclasses with `to_dict()`, which writes the current dict form. |
| Provenance | Face IDs go in the IR nodes and in SCAD comments, for example `// face F7 base_top (plane)`. Triangle lists go in the JSON report only. |
| Naming | `<kind>_<index>_<dim>`, for example `boss_1_height`. The index starts at 1. |
| Profile | Rectangle, L, U and T profiles get named dimensions. Other profiles become a labeled point list. |
| Rollout | CLI flag `--pipeline segmentation`. The old detectors stay the default until the new pipeline does better on the fixtures and on the real parts. |
| Next target | 2 or 3 of the simplest Hero Me parts from the local corpus, each with an expected JSON that is checked by hand. |

## API that the tests expect

Module: `stl2scad/core/segmentation.py` (it can be a package).

- `segment_mesh(mesh: stl.mesh.Mesh) -> SegmentationResult`
  - `result.faces`: a list of faces. Each face has:
    - `kind`: `"plane"`, `"cylinder"`, `"cone"`, `"sphere"` or `"torus"`.
    - `convexity`: `"convex"` or `"concave"` for curved faces.
    - `triangle_indices`.
    - `distance_to(expected: dict) -> float`, to rank candidates.
    - `matches(expected: dict, tol: dict) -> bool`, which uses the `tolerances` keys of the JSON.
  - `result.edge_convexity(face_a, face_b) -> "convex" | "concave" | "tangent"`.
- `detect_features(result) -> list[Feature]`. A feature has `kind` (the same strings as the JSON), `polarity`, and the dimensions `radius`, `height` and `depth` where they apply.
- `hausdorff_to_mesh(features, mesh) -> float`, in mm.
- `emit_scad(features, mesh) -> str`: the labeled, adjustable SCAD source.
- `gate_limit_mm(mesh) -> float`: the gate limit for this mesh.

The implementation can change this API if it also changes the tests in the same commit.

## Pipeline steps for this target

1. Load and repair: weld vertices, use float64, set tolerances relative to the part size.
2. Segment: region growing on normals and curvature, then RANSAC fits for planes and cylinders at any orientation.
3. Region adjacency graph: one node for each face, and edges with the convexity from the dihedral angle. A small angle is tangent.
4. Features: the dominant directions come from the plane normals. Concave cylinders are holes and convex cylinders are bosses. A concave cylinder strip between two planes is a fillet. Emit through the IR ([detector_ir.md](detector_ir.md)).
5. Emit: labeled, adjustable SCAD as in the output decisions, then check the gate.
