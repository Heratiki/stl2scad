# T-010: Segmentation falls back on every revolved solid, cone, sphere and torus

Status: open
Opened: 2026-10-20 by the orchestrator, from a measurement of the segmentation pipeline (`emit_scad(None, mesh)`) over the 95 feature fixtures in `tests/data/feature_fixtures_scad/` (2026-10-20; 61 parametric, 34 fallback, 0 exceptions). Fallback is read from the `// Full mesh fallback: <reason>` line and the Hausdorff from the `measured Hausdorff` header line.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

`stl2scad/core/segmentation/` has no revolve primitive: step 4 only builds extruded bodies (caps plus side profile) and cylinder holes/bosses. The edge-rounds spec (`docs/superpowers/specs/2026-10-20-edge-rounds-design.md`, "Out of scope" about line 110) lists revolves as out of scope for plans 1-3, so no plan covers this. The legacy revolve detector was archived by T-003 (`enable_revolve_detection`) and is not reusable by segmentation.

Measured over the fixtures, all fall back (fixture: reason, Hausdorff mm, seconds):

- revolve_triangle_profile: No matching opposite section caps for an extruded body, n/a, 0.35
- revolve_vase: same reason, n/a, 4.16
- revolve_vase_dome (extra .scad, not in manifest): same, n/a, 2.61
- revolve_stepped_shaft: same, n/a, 5.13
- revolve_christmas_tree: same, n/a, 5.51
- revolve_frustum_trapezoid: same, n/a, 1.98
- revolve_inverted_cone: same, n/a, 1.98
- revolve_annular_tube: An arc profile needs a straight side to define its frame, n/a, 0.33
- revolve_semicircle_profile: Unsupported cylinder topology at F0, n/a, 2.69
- revolve_fat_disk: Unsnapped feature solid failed the Hausdorff gate, 1.5, 8.15
- revolve_rectangle_profile: Unsnapped feature solid failed the Hausdorff gate, 4.998, 8.08
- revolve_y_axis: Unsnapped feature solid failed the Hausdorff gate, 3.999, 7.36
- cone_shallow, cone_steep, negative_cone: No matching opposite section caps for an extruded body, n/a, 1.65 / 1.82 / 1.86
- negative_sphere: Unsnapped feature solid failed the Hausdorff gate, 9.667, 116.1
- negative_torus: No matching opposite section caps for an extruded body, n/a, 126.22

The fixtures named negative_* are negative cases for the legacy detector; under segmentation a polyhedron fallback is the safe result for them today, so whether sphere/torus should become primitives is a maintainer decision. The gate-caught Hausdorff cases (revolve_fat_disk, revolve_rectangle_profile, revolve_y_axis) are wrong models stopped by the gate, not false positives that ship. The fallback is safe; the gap is that no revolved part gets parametric output.

The standing maintainer rule (2026-10-20) is to ticket every detector false positive or primitive issue; the maintainer may set `wontfix` later.

## Rulings (2026-10-20)

None yet. No fix ruling exists for this ticket.

## Settled design

Nothing is settled. See "Confirm before implementing".

## Confirm before implementing

Not a ruling. Suggested approach, not a ruling: add a revolve feature to segmentation. Detect a dominant axis from cylinder/cone/sphere/torus fit axes, section the mesh in an axial half-plane to get a 2D profile, emit `rotate_extrude` with profile points as parameters. Open questions: which kinds are in scope (cone, sphere, torus as their own primitives or as profiles), the parameter naming, the fixture-by-fixture expected result, and whether negative_sphere and negative_torus should stay a polyhedron fallback.

## Owns

- `stl2scad/core/segmentation/` (new revolve module and the dispatch in `features.py`, `to_ir.py`)
- `tests/test_segmentation_revolve.py` (new)

## Out of scope

- Reviving or editing the archived legacy revolve detector (T-003).
- Convex edge rounds, chamfers, ellipses, screw features (plans 1-3).
- Speed of the sphere and torus fallbacks (T-012).

## Acceptance

- [ ] New test `test_revolve_fixtures_are_parametric`: each of the 11 manifest revolve fixtures (list in the test) produces output with no `Full mesh fallback` line and a Hausdorff below the gate.
- [ ] New test `test_revolve_profile_parameters_edit`: changing one profile parameter in the emitted SCAD matches the ground-truth SCAD rendered with the same value.
- [ ] New test `test_cone_fixtures_are_parametric`: cone_shallow, cone_steep and negative_cone follow the maintainer's confirmed outcome.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
