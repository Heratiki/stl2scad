# T-014: Shaft with a keyway falls back in segmentation

Status: open
Opened: 2026-10-20 by the orchestrator, from a measurement of the segmentation pipeline (`emit_scad(None, mesh)`) over the 95 feature fixtures in `tests/data/feature_fixtures_scad/` (2026-10-20; 61 parametric, 34 fallback, 0 exceptions). Fallback is read from the `// Full mesh fallback: <reason>` line and the Hausdorff from the `measured Hausdorff` header line.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

non_revolve_shaft_with_keyway falls back with "Unsupported cylinder topology at F0" (0.3 s, no Hausdorff measured). The cylinder face is cut by the keyway slot, so it is not a full or simply bounded cylinder, and step 4 refuses it. The fallback is safe. Plan 1 covers extrusions with edge treatments and profile arcs; a keyway cut along a cylinder's side is not named in it, and revolves are out of scope there (see T-010). This is the same refusal reason that appears for box_rounded_edges (plan 1, edge rounds), revolve_semicircle_profile (T-010) and plate_counterbore_and_slot (plan 3), but the cause here is a slot cut into a cylindrical side, so it is its own gap.

The standing maintainer rule (2026-10-20) is to ticket every detector false positive or primitive issue; the maintainer may set `wontfix` later.

## Rulings (2026-10-20)

None yet. No fix ruling exists for this ticket.

## Settled design

Nothing is settled. See "Confirm before implementing".

## Confirm before implementing

Not a ruling. Suggested approach, not a ruling: model the shaft as a cylinder body plus a rectangular groove (subtractive box on the cylinder side) with `keyway_<n>_width` and `keyway_<n>_depth` parameters, or as an extrusion whose section profile contains the notch (a slab with a single profile loop). The maintainer must confirm which representation, and whether T-011's rectangular cutout primitive should be reused.

## Owns

`stl2scad/core/segmentation/` (the module the maintainer picks after the design is confirmed) and a new `tests/test_segmentation_<topic>.py`

## Out of scope

- Revolved solids (T-010).
- Rectangular cutouts in plates and boxes (T-011).

## Acceptance

- [ ] New test `test_keyway_shaft_is_parametric`: non_revolve_shaft_with_keyway has no `Full mesh fallback` line and a Hausdorff below the gate.
- [ ] New test `test_keyway_dimensions_edit`: changing the keyway width in the emitted SCAD matches the ground truth rendered with the same value.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
