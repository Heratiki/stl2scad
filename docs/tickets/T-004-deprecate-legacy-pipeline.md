# T-004: Deprecate the legacy pipeline; segmentation becomes the default

Status: open. Route: Opus lane-dev (design inside).
Opened: 2026-10-20 by the ticket-writer, from the maintainer's rulings of the same date. Rewrites the original T-004 (large cylinder detected as a box).
Depends on: T-003 (merged 730d6b4)

Note: the original T-004 subject, the false `box_like_solid` on `cylinder_large_diameter` with the revolve detector off, is superseded by this ticket. The legacy detectors no longer run after T-004, so the false positive cannot occur on any live path. Its xfail name list (`_REVOLVE_ARCHIVED_NON_REVOLVE_FIXTURES`) moves to `tests/legacy/` with the legacy round-trip tests.

## What happens today

- `stl2scad convert` defaults to `--pipeline legacy` (`stl2scad/cli.py` lines 126-130, help "default: legacy"). `verify`, `batch` and the GUI (`stl2scad/gui/main_window.py` line 47) call the legacy `stl2scad()` from `stl2scad/core/converter.py`.
- `stl2scad/core/converter.py` holds both the legacy conversion path and two helpers the live code needs, `get_openscad_path()` and `run_openscad()`. Segmentation (`segmentation/emit.py:10`, `segmentation/solid.py:14`) and verification (`verification/metrics.py:17`, `verification/visualization.py:14`) import them from there, so the live code depends on a module that is about to be archived.
- `stl2scad/core/verification/verification.py` converts through the legacy `stl2scad()`.
- Importer survey (`git grep` on 2026-10-20, source side; the lane must re-run it):
  - `stl2scad/__init__.py:5` imports `stl2scad`, `ConversionStats`, `STLValidationError` from `core.converter`.
  - `stl2scad/cli.py:18-32` imports from `core.converter`, `core.feature_graph`, `core.feature_inventory`, `core.recognition` (`SUPPORTED_RECOGNITION_BACKENDS`).
  - `stl2scad/core/converter.py:89-90` imports `feature_graph` and `recognition`.
  - `stl2scad/core/perf_baseline.py:20` imports `stl2scad` from `.converter`.
  - `stl2scad/core/recognition_sweep.py:16` imports `recognition`.
  - `stl2scad/core/feature_inventory.py:387` imports `feature_graph` (lazily).
  - `stl2scad/corpus/engine.py:34`, `stl2scad/tuning/local_corpus.py:18-20`, `stl2scad/tuning/scoring.py:14`, `stl2scad/tuning/thingi10k.py:323,430` import `feature_graph` / `feature_inventory`.
  - `stl2scad/tuning/real_world_corpus.py:13` imports `_bbox` from `feature_inventory`.
  - `stl2scad/gui/main_window.py:47-60` imports `converter`, `feature_graph`, `feature_inventory`, `recognition`.
  - Scripts: `scripts/analyze_feature_inventory.py`, `build_feature_graph.py`, `build_feature_graph_from_inventory.py`, `evaluate_models.py`, `run_recognition_sweep.py`, `stl2scad_cgal_helper.py` (imports `core.recognition`), `summarize_single_feature_graph.py`, `tune_detector.py` (imports `get_openscad_path, run_openscad`).
  - Tests that import these modules (`git grep -l`): `tests/test_cgal_backend.py`, `test_cli.py`, `test_conversion.py`, `test_debug.py`, `test_detector_scoring.py`, `test_feature_fixtures.py`, `test_feature_graph.py`, `test_feature_inventory.py`, `test_ir.py`, `test_linear_extrude_recovery.py`, `test_openscad.py`, `test_phase0_benchmarks.py`, `test_recognition_sweep.py`, `test_verification.py`, `test_visualization.py`, and the segmentation tests `test_segmentation_bracket.py`, `_defeature.py`, `_emit.py`, `_profiles.py`, `_rounded_plate.py`, `_treatments_truth.py`.
- `stl2scad/core/openscad/` exists and holds only `command_builder.py`. The lane decides whether the new module goes there or at `stl2scad/core/openscad_runner.py`.
- CLAUDE.md ("Failure analysis", "Segmentation pipeline status") says the default is still `legacy`.

## Rulings (2026-10-20)

- The legacy pipeline can no longer run. Segmentation is the default. `--pipeline` stays for future pipelines; its choices become `segmentation` (default) and `legacy`. `--pipeline legacy` prints a deprecation warning to stderr, writes nothing, and exits 2. Rejected: keeping legacy runnable behind a flag.
- Scope is all conversion entry points: `convert`, `verify`, `batch` and the GUI (`stl2scad/gui/main_window.py`) convert through segmentation.
- `--parametric`, `--recognition-backend` and similar legacy-only flags stay accepted, print a deprecation warning, and are ignored. Reason: existing scripts keep parsing.
- The `feature-graph`, feature-graph-inventory and inventory analysis commands that only run the legacy detectors print a deprecation warning and exit 2 without work.
- Keep, by moving not archiving: `get_openscad_path()` and `run_openscad()` leave `stl2scad/core/converter.py` for their own module, keeping the Windows `"OpenSCAD (Nightly)"` substring check. Every importer is updated. Also kept: `verification/metrics` (Hausdorff), `ir.py`, the fixture manifest, the generator `stl2scad/core/feature_fixtures.py`, and the SCAD library. `verification/verification.py` converts through segmentation instead of the legacy `stl2scad()`.
- Archive to `stl2scad/legacy/`, as T-003 did: `feature_graph.py`, `recognition.py`, `linear_extrude_recovery.py`, `recognition_sweep.py`, the legacy `stl2scad()` conversion path, and anything else only they use. The lane lists the importers with `git grep` first (survey above is the starting point).
- Tests: legacy-detector tests move to `tests/legacy/` (skipped unless `STL2SCAD_LEGACY_TESTS=1`; `tests/legacy/conftest.py` exists). In `tests/test_feature_fixtures.py` the byte-exact regeneration test and the roadmap-coverage test stay in place; the legacy detection round-trip tests move to `tests/legacy/`. The segmentation retarget of the round-trip is T-009, which runs after T-004.
- Docs: CLAUDE.md belongs to the orchestrator; the lane does not edit it. README and docs usage lines that show legacy commands are updated by the lane.

## Settled design

- New module for `get_openscad_path()` / `run_openscad()`; signatures and the Nightly check unchanged. `converter.py` is removed or archived; `stl2scad/__init__.py` stops exporting the legacy `stl2scad()` and exports the segmentation entry point instead (the lane picks the names, keeping `ConversionStats` and `STLValidationError` if segmentation or the CLI still use them).
- `cli.py`: one helper prints the deprecation warning to stderr. `convert`, `verify`, `batch` call the segmentation conversion. Deprecated commands and flags use the same helper.
- GUI: the convert worker calls segmentation; legacy-only GUI panels (graph, inventory) are disabled or report the deprecation. Design inside: the lane chooses, keeping the GUI importable headless (`QT_QPA_PLATFORM=offscreen`).
- `stl2scad/legacy/` modules keep their own relative imports working among themselves. Nothing under `stl2scad/` outside `stl2scad/legacy/` imports `stl2scad.legacy`.
- Scripts under `scripts/` that import archived modules get a deprecation exit or import from `stl2scad.legacy` (scripts are outside `stl2scad/`, so this is allowed there); the lane decides each.
- Segmentation files change by import lines only.

## Owns

- `stl2scad/**` except `stl2scad/core/segmentation/**` (import-line edits only there)
- `tests/**` except `tests/test_segmentation_*.py` and `tests/data/**` (see Confirm before implementing)
- `scripts/**` (import fixes only)
- `README.md`, `docs/**` usage lines
- `docs/tickets/T-004-deprecate-legacy-pipeline.md` (Status line only)

## Confirm before implementing

- The segmentation tests (`tests/test_segmentation_bracket.py`, `_defeature.py`, `_emit.py`, `_profiles.py`, `_rounded_plate.py`, `_treatments_truth.py`) import from `core.converter` and so need import-line edits, but the brief excludes `tests/test_segmentation_*.py` from the owned paths. The maintainer must allow import-line-only edits there, or those tests break. Recommended: allow import-line edits only.
- Wave conflict: T-005..T-008 own segmentation files. They must not run at the same time as the import-line edits in `stl2scad/core/segmentation/**` and these tests. Run T-004 alone or in wave order.

## Out of scope

- Any behaviour change in segmentation. Import lines only.
- Retargeting the fixture round-trip to segmentation (T-009).
- Performance work.
- Editing CLAUDE.md (orchestrator; see below).
- Deleting the archived code. It moves to `stl2scad/legacy/`.

## CLAUDE.md after T-004 (the orchestrator edits it)

- "Segmentation pipeline status": the default is `segmentation`; `--pipeline legacy` warns on stderr, writes nothing, exits 2.
- Failure-analysis section marked historical; the legacy detectors live in `stl2scad/legacy/` and run only under `STL2SCAD_LEGACY_TESTS=1` tests.
- The "Three invariants" text and "Conventions" paragraph point at `stl2scad/core/openscad_runner.py` (or the chosen module) for `get_openscad_path()`. Invariant 2 wording comes from T-009.

## Acceptance

- [ ] `stl2scad convert in.stl out.scad` uses segmentation (default pipeline).
- [ ] `stl2scad convert --pipeline legacy in.stl out.scad`: deprecation warning on stderr, no output file, exit code 2. A CLI test asserts all three.
- [ ] `--parametric` and `--recognition-backend` are accepted, warn, and are ignored (a CLI test asserts the warning and a successful segmentation convert).
- [ ] `feature-graph`, feature-graph-inventory and inventory commands warn and exit 2 without work (CLI test).
- [ ] `verify`, `batch` and the GUI convert path call segmentation; `verification/verification.py` no longer calls the legacy `stl2scad()`.
- [ ] `get_openscad_path()` and `run_openscad()` live in their own module with the Nightly check intact; all importers updated.
- [ ] `git grep -nE "stl2scad\.legacy|from \.+legacy" -- stl2scad ':!stl2scad/legacy'` prints nothing.
- [ ] Legacy-detector tests moved to `tests/legacy/`; `tests/test_feature_fixtures.py` keeps the byte-exact regeneration and roadmap-coverage tests unchanged. No assertion weakened in any non-legacy test; tests whose subject is legacy behaviour move, they are not edited.
- [ ] Scoped pytest for CLI, conversion, verification and visualization tests passes (lane may run scoped, with the flock prefix from `test_scoped`; never the full run).
- [ ] Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` (0 across the full repo) and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
