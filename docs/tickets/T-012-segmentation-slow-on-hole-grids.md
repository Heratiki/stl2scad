# T-012: Segmentation takes minutes on hole-grid plates

Status: open
Opened: 2026-10-20 by the orchestrator, from a measurement of the segmentation pipeline (`emit_scad(None, mesh)`) over the 95 feature fixtures in `tests/data/feature_fixtures_scad/` (2026-10-20; 61 parametric, 34 fallback, 0 exceptions). Fallback is read from the `// Full mesh fallback: <reason>` line and the Hausdorff from the `measured Hausdorff` header line.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

The measurement ran the 95 fixtures at 8-way parallel; the median was 6 s and the total about 52 min. The outliers are dominated by plates with many holes, where the render-per-parameter-snap loop in `emit_scad` renders once per snapped parameter (this cause is the measurer's reading, not yet confirmed by a profile).

Slowest runs (fixture: seconds):

- plate_multi_pattern_mixed_edge: 690.8
- plate_3x3_grid: 595.62
- plate_4x4_grid: 423.71
- negative_torus: 126.22 (fallback)
- negative_sphere: 116.1 (fallback)
- plate_small_hole_grid: 110.32
- plate_grid_two_by_three: 106.93
- plate_mixed_linear_and_slot: 80.85

Why it matters: the corpus and test runs are slow, and a user converting a perforated plate waits over ten minutes. No output is wrong; this is a performance gap.

The standing maintainer rule (2026-10-20) is to ticket every detector false positive or primitive issue; the maintainer may set `wontfix` later.

## Rulings (2026-10-20)

None yet. No fix ruling exists for this ticket.

## Settled design

Nothing is settled. See "Confirm before implementing".

## Confirm before implementing

Not a ruling. Suggested approach, not a ruling: profile first (cProfile on plate_3x3_grid) to confirm where the time goes before changing anything. If it is the render-per-snap loop, candidates are snapping all parameters in one render, a cheaper in-process distance check, or a cap on the number of snaps. The maintainer must confirm an acceptable time target (for example under 60 s for a 4x4 grid) and that the Hausdorff gate semantics stay unchanged.

## Owns

- `stl2scad/core/segmentation/` (the snap and gate path only)
- `tests/test_segmentation_perf.py` (new)

## Out of scope

- Changing the gate limit or what the gate accepts.
- Legacy pipeline speed.
- New primitives.

## Acceptance

- [ ] New test `test_hole_grid_output_unchanged`: plate_3x3_grid output is byte-equal (minus the `// Source:` line) to the output before the change.
- [ ] New test `test_hole_grid_time_budget`: plate_3x3_grid converts within the maintainer-confirmed time target (marked slow if the repo has such a marker).
- [ ] The lane's report states the profile result that justified the change.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
