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

- First step is early rejection with a named reason, so no wrong model reaches the gate. Reason: smallest safe step. Rejected: building cutout and pocket primitives in this ticket.
- The cutout and pocket primitives come later, likely from plan 1 slab work (Task 4 onward, `docs/superpowers/plans/2026-10-20-defeature-slabs-hybrid.md`).

## Settled design

When a cap-to-cap or blind-pocket region is not a circle or stadium, the detector rejects early with a named reason (a new reason string, for example `rectangular cutout or pocket not supported`) and the pipeline falls back to polyhedron. The Hausdorff gate is no longer the first thing to notice. No rectangular primitives are added here; a later ticket adds them, likely on the plan 1 slab work.

## Owns

`stl2scad/core/segmentation/` (the module the maintainer picks after the design is confirmed) and a new `tests/test_segmentation_<topic>.py`

## Out of scope

- Circular holes, stadium slots (already supported).
- Chamfers and edge rounds (plan 1).
- Counterbores and countersinks (plan 3).

## Acceptance

- [ ] New test `test_rectangular_cutout_is_not_a_silent_wrong_solid`: for plate_rectangular_through_cutout the pipeline records the new named rejection before the gate; the gate is not the first thing that notices.
- [ ] New test `test_rectangular_cutout_fixtures_fall_back_with_named_reason`: plate_rectangular_through_cutout, plate_rectangular_top_pocket, plate_two_rectangular_pockets, box_with_top_notch, box_two_cutouts and box_side_cutout each fall back with the new named reason, and none fails the Hausdorff gate.
- [ ] plate_cutout_and_hole falls back with the new named reason (or its existing refusal reason, unchanged); no cutout-plus-hole output is required.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
