# T-011: Rectangular cutouts, pockets and notches give a wrong model that only the gate stops

Status: open
Opened: 2026-10-20 by the orchestrator, from a measurement of the segmentation pipeline (`emit_scad(None, mesh)`) over the 95 feature fixtures in `tests/data/feature_fixtures_scad/` (2026-10-20; 61 parametric, 34 fallback, 0 exceptions). Fallback is read from the `// Full mesh fallback: <reason>` line and the Hausdorff from the `measured Hausdorff` header line.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

Segmentation does not model non-circular cutouts or pockets. Instead of refusing early, it builds a solid that ignores them, and the Hausdorff gate in `emit_scad` catches the wrong model and forces a polyhedron fallback. This is a wrong-model (false positive caught by the gate, not by the detector). The detector reports success on a part it does not explain; only the gate keeps it from shipping. Plan 1 (`docs/superpowers/plans/2026-10-20-defeature-slabs-hybrid.md`) covers chamfers, edge rounds, clipped arcs and stepped extrusions; it does not name rectangular pockets or cutouts.

Measured (fixture: reason, measured Hausdorff mm, seconds):

- plate_rectangular_through_cutout: Unsnapped feature solid failed the Hausdorff gate, 2, 2.09
- plate_rectangular_top_pocket: same, 2, 1.45
- plate_two_rectangular_pockets: same, 3, 1.35
- box_with_top_notch: same, 6, 1.05
- box_two_cutouts: same, 4, 0.99
- box_side_cutout (extra .scad, not in manifest): same, 7.458, 0.97
- plate_cutout_and_hole: Unsupported through-cut section: expected circular hole or stadium, n/a, 0.17 (the through-cut path refuses early, correctly, but the part still has no output)

The standing maintainer rule (2026-10-20) is to ticket every detector false positive or primitive issue; the maintainer may set `wontfix` later.

## Rulings (2026-10-20)

None yet. No fix ruling exists for this ticket.

## Settled design

Nothing is settled. See "Confirm before implementing".

## Confirm before implementing

Not a ruling. Suggested approach, not a ruling: (1) make the detector reject early with a named reason when a cap-to-cap or blind-pocket region is not a circle or stadium, instead of emitting a solid that the gate then rejects; (2) add rectangular cutout and pocket primitives (through, blind) with `<kind>_<index>_<dim>` parameters relative to the host face; (3) route stepped planar loops to the slab/step path of plan 1 if plan 1 can express them. The maintainer must confirm which parts are wanted and whether (1) alone is enough as a first step.

## Owns

`stl2scad/core/segmentation/` (the module the maintainer picks after the design is confirmed) and a new `tests/test_segmentation_<topic>.py`

## Out of scope

- Circular holes, stadium slots (already supported).
- Chamfers and edge rounds (plan 1).
- Counterbores and countersinks (plan 3).

## Acceptance

- [ ] New test `test_rectangular_cutout_is_not_a_silent_wrong_solid`: for plate_rectangular_through_cutout the pipeline either emits the cutout or records a named rejection before the gate; the gate is not the first thing that notices.
- [ ] New test `test_rectangular_cutout_fixtures_pass_gate`: the six fixtures above (list in the test) have a Hausdorff below the gate, per the confirmed scope.
- [ ] New test `test_cutout_and_hole_combines`: plate_cutout_and_hole yields both a cutout and a hole.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
