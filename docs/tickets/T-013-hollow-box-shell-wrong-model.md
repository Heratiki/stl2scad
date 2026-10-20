# T-013: Hollow box gives a wrong model that only the gate stops

Status: open
Opened: 2026-10-20 by the orchestrator, from a measurement of the segmentation pipeline (`emit_scad(None, mesh)`) over the 95 feature fixtures in `tests/data/feature_fixtures_scad/` (2026-10-20; 61 parametric, 34 fallback, 0 exceptions). Fallback is read from the `// Full mesh fallback: <reason>` line and the Hausdorff from the `measured Hausdorff` header line.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

box_hollow_ambiguous (a hollow box shell) is built as a solid by segmentation, giving a measured Hausdorff of 5 mm; the gate then forces a polyhedron fallback ("Unsnapped feature solid failed the Hausdorff gate", 0.9 s). This is a wrong-model (false positive caught by the gate): the detector does not recognise an enclosed cavity or inner shell. `CLAUDE.md` already notes that legacy box detection can false-positive on hollow shells; this is the segmentation-side instance. No plan covers hollow bodies or inner shells.

The standing maintainer rule (2026-10-20) is to ticket every detector false positive or primitive issue; the maintainer may set `wontfix` later.

## Rulings (2026-10-20)

None yet. No fix ruling exists for this ticket.

## Settled design

Nothing is settled. See "Confirm before implementing".

## Confirm before implementing

Not a ruling. Suggested approach, not a ruling: detect an inner closed shell (a second connected surface with inward-facing normals) and either emit it as a `difference()` of an inner solid, or reject with a named reason. The maintainer must confirm whether ambiguous cavities are in scope (the fixture name says the interpretation is ambiguous) and what the expected result for this fixture is.

## Owns

`stl2scad/core/segmentation/` (the module the maintainer picks after the design is confirmed) and a new `tests/test_segmentation_<topic>.py`

## Out of scope

- Through-holes and pockets (T-011).
- Legacy `feature_graph.py` box detection (T-004).

## Acceptance

- [ ] New test `test_hollow_box_not_emitted_as_solid`: box_hollow_ambiguous either emits a model within the gate or records a named rejection before the gate.
- [ ] New test `test_solid_box_unchanged`: box_cubic stays parametric.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
