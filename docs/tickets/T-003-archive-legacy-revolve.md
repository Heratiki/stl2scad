# T-003: Archive the legacy revolve detector behind a flag

Status: landed (worktree-agent-a420ea3416132c235, 2026-10-20)
Opened: 2026-10-20 by the orchestrator, from a read-only survey and the maintainer's rulings.
Depends on: none

## What happens today

- `stl2scad/core/revolve_recovery.py` (665 lines) holds the whole-mesh revolve detector: `classify_revolve_profile` at :371-531 and `detect_revolve_solid` at :533.
- The only production caller is the lazy import at `stl2scad/core/feature_graph.py:461` (block :460-474). A revolve result suppresses the later cylinder/plate/box checks (:515-540: `if not revolve_features` guards the linear-extrude and composite-solid steps).
- `stl2scad/core/segmentation/**` never imports it, and no plan or spec reuses it. CLAUDE.md names whole-mesh classification as the root cause of the parametric stall.
- `DetectorConfig` (`stl2scad/tuning/config.py:14`) carries the revolve knobs at :102-114 (`revolve_axis_quality_min` ... `revolve_phase2_circle_fit_tolerance_ratio`). No flag turns the detector off.
- Tests: `tests/test_revolve_recovery.py` (27 tests; `test_detect_revolve_solid_accepts_cylinder_without_cap_center_vertices` fails today, pre-existing at 7999581). About 17 revolve tests in `tests/test_feature_graph.py` (:2308-2800; direct imports of `revolve_recovery` at :2554, :2594, :2612, :2630, :2655, :2675). In `tests/test_feature_fixtures.py`: revolve round-trip branch (:664-683), `test_revolve_fixture_exposes_confidence_components` (:1563), `test_revolve_fixture_preview_round_trip` (:1604), `test_revolve_fixture_phase2_primitive_upgrade` (:1652). The manifest holds 17 revolve/non_revolve fixtures.
- The lane must re-verify these line numbers before editing; they were measured on 2026-10-20 at main.

## Rulings (2026-10-20)

- Flag off, then move. Add `enable_revolve_detection: bool = False` to `DetectorConfig` in `stl2scad/tuning/config.py`. `feature_graph.py` runs revolve detection only when it is True. Reason: default behaviour should stop depending on the whole-mesh detector without deleting code. Rejected: delete outright.
- Move `stl2scad/core/revolve_recovery.py` to `stl2scad/legacy/revolve_recovery.py` (new package with `__init__.py`). Keep a thin `stl2scad/core/revolve_recovery.py` re-export with a `DeprecationWarning` only if something outside tests imports it; otherwise no shim. (Survey: only `feature_graph.py` imports it outside tests, and that import moves to the new path, so expect no shim.)
- Move `tests/test_revolve_recovery.py` and the revolve tests of `tests/test_feature_graph.py` to `tests/legacy/`. `tests/legacy/conftest.py` skips the directory unless env `STL2SCAD_LEGACY_TESTS=1`. Those tests enable the flag. Dead revolve emitters in `feature_graph.py` stay for a later cleanup.
- Fixtures: keep every manifest entry and `.scad` file unchanged (byte-exact regeneration and roadmap-coverage tests unchanged). The revolve round-trip, preview, Phase 2 and confidence tests in `tests/test_feature_fixtures.py` become `pytest.mark.xfail(strict=False, reason="revolve detector archived (T-003)")`, only for fixtures of type revolve or whose expected detection changes because revolve is off. Non_revolve negatives should still pass. If a non-revolve fixture (e.g. `cylinder_narrow_tall`, `revolve_fat_disk`) changes detection, the lane lists it in its report and xfails it by name with the same reason. Never weaken a tolerance. Rejected: edit the manifest or loosen tolerances.

## Settled design

- `DetectorConfig.enable_revolve_detection = False`. In `feature_graph.py`, wrap the import and the vertex-dedup plus `detect_revolve_solid` call in `if resolved.enable_revolve_detection:`; otherwise `revolve_features = []`. The downstream `if not revolve_features` guards stay as they are. The lazy import points at `stl2scad.legacy.revolve_recovery`.
- `git mv` the module and the tests so history follows. Imports in moved tests change to `stl2scad.legacy.revolve_recovery`; tests that call `build_feature_graph` pass a config with the flag True.
- Xfail on fixture tests is applied per fixture (parametrize marks or an in-test `pytest.xfail` on the fixture name), so passing non-revolve fixtures are not hidden.
- The lane reports which fixtures changed detection.

## Owns

- `stl2scad/core/revolve_recovery.py`
- `stl2scad/legacy/**`
- `stl2scad/core/feature_graph.py`
- `stl2scad/tuning/config.py`
- `tests/test_revolve_recovery.py`
- `tests/test_feature_graph.py`
- `tests/test_feature_fixtures.py`
- `tests/legacy/**`

## Out of scope

- `tests/conftest.py`, `tests/test_conversion.py`, `tests/test_debug.py`, `tests/test_verification.py` (T-002 owns them).
- `stl2scad/core/segmentation/**` and `tests/test_segmentation_*.py`.
- `CLAUDE.md`, the fixture manifest and `.scad` files.
- Deleting the dead revolve emitters in `feature_graph.py`; fixing the pre-existing failing test.
- Removing the revolve knobs from `DetectorConfig`.

## Acceptance

- [x] `enable_revolve_detection` exists, defaults False, and gates the call at `feature_graph.py`.
- [x] `git grep -n revolve_recovery -- stl2scad/core` shows only the gated lazy import (or nothing).
- [x] Revolve tests moved to `tests/legacy/` with the skip conftest; with `STL2SCAD_LEGACY_TESTS=1` they run with the flag on and fail only on `test_detect_revolve_solid_accepts_cylinder_without_cap_center_vertices` (known, pre-existing).
- [x] Fixture tests: revolve ones xfail(strict=False) with the stated reason; `test_feature_fixture_manifest_matches_checked_in_scad` and `test_feature_fixture_manifest_covers_roadmap_stress_cases` unchanged and passing; non_revolve negatives pass.
- [x] No assertion deleted, no tolerance loosened; the report lists every non-revolve fixture whose detection changed.
- [x] Scoped run shows 0 failed (xfails allowed; the lane may run it): `flock /tmp/stl2scad-pytest.lock env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -n auto -q -o addopts="" -p no:logging tests/test_feature_fixtures.py tests/test_feature_graph.py tests/test_ir.py tests/legacy`
- [x] `tests/test_segmentation_*.py` untouched.
- [x] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [x] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` (0) and `node scripts/check-tickets.mjs`.

Do NOT run the test harness beyond the scoped command above. Stage paths explicitly.
