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

- Target: every fixture converts in under 30 s, so the T-009 `slow` marker can be removed. Reason: maintainer target. Rejected: a 60 s target for the 4x4 grid only.
- Profile first and report the hotspot before changing code. Reason: the render-per-snap cause is unconfirmed. Rejected: optimising on the measurer's reading.
- Make segmentation of one part use more than one core in the near future, if feasible. Reason: maintainer ruling. Evidence: during the T-009 slow fixture run (12 slow fixtures, 12 min 45 s wall, 245 % CPU on 8 cores), the two hole-grid plates each held one core at about 100 % while six cores were idle; machine load was about 1.2 of 8. Rejected: leaving a single part single-threaded and relying only on cross-file parallelism.

## Settled design

Step 1: cProfile on plate_3x3_grid (and the other listed outliers); report the hotspot in the lane report before any code change. Step 2: change only the snap and gate path as the profile justifies; gate semantics and limit stay unchanged and the output stays byte-equal.

Step 3 (parallelism, per the multi-core ruling): after the profile, find the independent work units inside one part and run them in parallel. Candidates to check: the per-feature and per-snap OpenSCAD renders and Hausdorff checks (subprocess-bound; a process or thread pool fits), per-region RANSAC and fitting, and per-shell work (T-013 void shells). Constraints:

- The result is deterministic: same output bytes and same feature numbering regardless of worker count.
- The worker count is capped. Env var `STL2SCAD_WORKERS`; default = number of cores when run alone, 1 under pytest-xdist (`pytest -n auto` already runs one process per core).
- No new heavy dependency without a maintainer ruling.

## Owns

- `stl2scad/core/segmentation/` (the snap and gate path only)
- `tests/test_segmentation_perf.py` (new)

## Out of scope

- Changing the gate limit or what the gate accepts.
- Legacy pipeline speed.
- New primitives.

## Acceptance

- [ ] New test `test_hole_grid_output_unchanged`: plate_3x3_grid output is byte-equal (minus the `// Source:` line) to the output before the change.
- [ ] New test `test_hole_grid_time_budget`: plate_3x3_grid converts in under 30 s, and every fixture in the 95-fixture set converts in under 30 s (the T-009 `slow` marker can then be removed).
- [ ] A hole-grid plate's wall time drops by at least half on 8 cores (against `STL2SCAD_WORKERS=1`) with identical output bytes.
- [ ] The lane's report states the profile result (hotspot) that justified the change, and was written before the code change.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
