# Design: convex edge rounds, chamfers and a free-form remainder

Date: 2026-10-20. Pipeline: `--pipeline segmentation` (`stl2scad/core/segmentation/`).

## Intent

Two real stand-in parts fall back to a polyhedron:

- `memo_cartridge` stops at `Unsupported cylinder topology at F17` (`features.py:353`).
- `memo_power_button` stops at the same error at F12.

A builder check ran `segment_mesh` on both parts. The faces that stop the pipeline are not
3D edge rounds between two planes:

- `memo_cartridge` F17 and F18: convex R3 cylinders along Y (the plate extrusion axis). Each is
  tangent to only one plane (F16, normal −Z) and meets the 45° chamfer F11 on a convex edge.
  The draft calls it `convex_arc`, sweep 15.5°. It is a partial profile arc that a chamfer
  cuts.
- `memo_power_button` F12 and F13: convex R0.5 cylinders along Z, tangent to two parallel planes
  that face opposite directions (±X). They are the half-round ends of the 1 mm rib.
- `memo_power_button` R1 rounds (F1816–F1818): along Z, between side walls. They are profile
  corners of a stepped Z extrusion (bar 2 mm tall, head 10 mm).

Each part also has a region that is possibly not a plane or a cylinder:

- `memo_cartridge`: the curved outline of the feet stays as about 570 facet planes. The draft
  fits six arcs there (C120–C125, R 2.2–16).
- `memo_power_button`: about 4 % of the surface (the head side) is free-form, about 1800 facet
  planes.

The user wants to open the converted part and change a fillet radius with a Customizer
slider. The user does not want a full part to become a polyhedron because of one small
free-form region.

## Goals

1. **Edge rounds.** Detect convex edge rounds (cylinder strips tangent to two planes) at any
   orientation. Emit each as a parameter `edge_round_<n>_radius` with a Customizer slider.
2. **Chamfers.** Detect planar chamfers between two planes. Emit each as a parameter
   `chamfer_<n>_width` with a Customizer slider. (Assumption of Claude; the user did not
   reject it.)
3. **Free-form remainder.** When a region cannot be fitted, the rest of the part stays
   parametric and only that region becomes a polyhedron (user decision).
4. **Report.** The diagnostics name each free-form region and give its share of the surface
   area.
5. **Partial profile arcs.** Recover a profile arc that a chamfer or another face cuts (the
   cartridge F17/F18), with a radius slider.
6. **Rib ends.** Recover a 180° half-round end between two parallel opposite planes (the
   button F12/F13), with a radius slider.
7. **Stepped extrusions.** Recover a body that is one profile extruded to more than one height
   (the button bar 2 mm and head 10 mm), with profile corner rounds as sliders.
8. **Cartridge feet: ellipse and curved round.** A measurement on 2026-10-20 (Claude
   subagent; Claude checked foot 1: 25 outline vertices on the ellipse within a relative error
   of 4e-7) answered hand check #3 of `segmentation_real_parts.md`:
   - The large curve of each foot is an exact quarter ellipse, semi-axes a = 3 mm (X) and
     b = 8 mm (Y), centre (24.925, 10.61), tangent to both adjacent straight edges. The facets
     are uneven in angle (parametric steps 1.8° to 5.9°).
   - The small corner is a true R3 arc (9 equal 5° chords), cut short by a 0.74 mm 45° straight.
   - The bottom edges have a round of about R2.4 that follows the elliptical edge. It is curved
     in two directions (not a cylinder or a torus).
   - The six draft arcs C120–C125 are circle fits over the ellipse and are wrong.

   User decisions:
   - Emit the curve as a parametric ellipse (for example `scale([a, b]) circle(1)`) with two
     sliders, `ellipse_<n>_a` and `ellipse_<n>_b`. The pipeline needs an ellipse fit (2D
     profile and elliptic cylinder) beside the circle fit.
   - Recover the R2.4 round along the elliptical edge as a constant-radius round along a curved
     edge, with a radius slider, now. The emitter needs a sweep of the round profile along the
     ellipse (or an equivalent offset construction).
9. **Screw features** (user decision, added after the first review). Recover, with sliders:
   - countersinks: cone angle, head diameter, depth;
   - counterbores: bore diameter, bore depth;
   - modeled threads, internal and external: pitch, thread angle (for example 60° metric),
     major and minor diameter, thread length or depth, handedness.
   A plain hole (for a tap or a heat insert) stays a plain hole. A modeled thread must not come
   out as a plain hole or as a free-form region.

## Done (user decision)

- Synthetic ground truth for each new capability passes first, in axis-aligned, rotated and
  coarse variants.
- `memo_cartridge` and `memo_power_button` pass the Hausdorff gate.
- Each round and each chamfer has a slider.
- The report gives the free-form share.
- Synthetic screw parts (countersink, counterbore, internal and external metric thread) pass,
  in axis-aligned, rotated and coarse variants. No real part with threads is in the done
  criteria, because none is on this machine.

## Decisions of the user

| Area | Decision |
|---|---|
| Edge treatments | Rounds and chamfers are now in scope. This replaces "Edge treatments come later" in `segmentation_composite_bracket.md`. |
| Adjustable | The radius of each round is a Customizer slider. |
| Remainder | Hybrid. Parametric for the fitted regions, polyhedron for the free-form region. This replaces "All or nothing" in `segmentation_composite_bracket.md`. |
| Free-form limit | If the free-form share is more than 10 % of the surface area, the full part is a polyhedron, as before. |
| Polyhedron placement | The polyhedron region stays fixed in the body frame and moves with the body. It does not follow a slider change. |
| Snapping | Snapping moves a value by 0.001 mm or less (`emit.py` `SNAP_MAX_SHIFT_MM`). Confirmed. |
| Scope | Grow the scope to goals 5–8, and keep "done": both real parts pass the gate. |
| Progress rule | (User, 2026-10-20.) More work must not block improvements or new fixtures. A region that the pipeline cannot make parametric yet can pass as a polyhedron region (hybrid, within the 10 % limit). Full parametric output is the long-term goal. Organic shapes are the hardest and possibly never become parametric. Thus each goal ships as soon as its fixtures pass, and a real part can pass the gate with polyhedron regions before goals 8 and 9 are complete. |
| Feet outline | A parametric ellipse with two semi-axis sliders (the measured geometry is an ellipse, not arcs). The round along its bottom edge is parametric now. |
| Architecture | Adopt the Argon blueprint (`docs/research/2026-10-20-argon-reconstruction-methods.md`, section A): replace the one-pass step 4 with (1) constrained regularization of the fitted faces, (2) iterative defeaturing of the face graph (corner blends, then rounds and chamfers, then bosses, holes, counterbores) with extension of the host faces to the sharp edge, (3) multi-height slab slicing into 2D profiles (lines, circular arcs, elliptical arcs), then replay of the removed features. The existing tests and the stencil result are the regression fence. |
| Corners | Corners where rounds or chamfers meet (sphere patch, torus on a boss top, a round that meets a chamfer at a vertex) are out of scope now. They may go to the free-form polyhedron. The synthetic parts include no such corners. |

## Non-goals

- A check that a slider change does not distort the model near a polyhedron region. The user
  wants this later, not now.
- Concave 3D fillets that do not span the extrusion (other half of review #5).
- Revolves, drafted extrusions, sweeps, disconnected bodies (review #6).
- The 3 known failures of `revolve_triangle_profile`. The user said not to fix them now.
- The Hero Me corpus. It is not on this machine.

## Anti-goals

- **A lazy free-form label.** The pipeline must not mark a region free-form because it is
  hard. An exact round or chamfer in the synthetic ground truth must come out parametric. A
  test must fail if a synthetic round or chamfer becomes free-form.
- **Tuning to the drafts.** Nobody checked `tests/data/segmentation/real/*_expected.json` by
  hand. Do not tune thresholds to them.
- **Weaker gates.** Do not change the gate limit (max(0.05 mm, 0.1 % of the bbox diagonal)),
  the tolerances or the snap limit to make a part pass.

## Constraints

- Do not edit `feature_graph.py`, the fixture manifest or the fixture SCAD.
- No `logging.basicConfig` in library code.
- Ground truth comes before pipeline code. Each synthetic part has hand-written exact faceted
  volumes (the method of `tests/data/segmentation/composite_bracket*.scad`).
- `.gitignore` ignores `*.json` and most `.scad`. Each new data file needs a `!` rule. Check
  with `git status -uall`.
- The Hausdorff gate still applies to the full output part, polyhedron regions included.
- Current baseline: 311 passed, 3 failed (`revolve_triangle_profile`). No new failure.

## Calls of Claude (the user can change them)

- **Orientation.** "Any orientation" means that the full part is rotated (as in
  `composite_bracket_rotated.scad`). An edge that is oblique inside the part frame (for example
  on a sloped face) is out of scope. Known limits #2 and #4 stay.
- **Names.** A round that is a 2D profile corner keeps `corner_<n>_radius` (the stencil output
  does not change). A 3D edge round between two faces gets `edge_round_<n>_radius`. A partial
  profile arc and a rib end are profile corners, so they get `corner_<n>_radius`.
- **Chamfers.** Symmetric chamfers only (equal setback on the two faces, any angle), one
  parameter `chamfer_<n>_width`. The synthetic parts use 45°. An asymmetric chamfer is out of
  scope; a test must show that it is reported, not silently mislabeled.

- **Thread output.** The SCAD is self-contained. It does not need BOSL2 or another library,
  because the output must render on a plain OpenSCAD installation.

## Left to the builder

- How to cut a free-form region into a closed solid, and how to join it to the parametric
  body (`union()` or `difference()`, depending on polarity).
- How to decide that a region is free-form (after the plane, cylinder and coarse-strip fits
  fail).
- How to emit a round or a chamfer in SCAD (for example, subtract an edge profile along the
  edge, or use `hull()` / `minkowski()` on the body).
- The exact synthetic parts, if each new capability has axis-aligned, rotated and coarse
  variants.
- How the slider range of a round or chamfer is limited (for example, an `assert()` that the
  radius is less than half of the smaller adjacent face width).
