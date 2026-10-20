# T-002: Cube STL test race under pytest-xdist

Status: landed (worktree-agent-a39a573524f2e7b01, 2026-10-20)
Opened: 2026-10-20 by the orchestrator, from the first full run (`pytest -n auto`).
Depends on: none

## What happens today

Under the full run, 13 tests fail with `FileNotFoundError` for `tests/data/cube.stl`:
`tests/test_conversion.py` (9 tests), `tests/test_debug.py::test_debug_features`,
`tests/test_verification.py` (3 tests). Run serially, all pass.

- `tests/test_verification.py:145-151` (inside the test that lists `test_data_dir.glob("*.stl")`):
  when no STL is found it calls `create_cube_stl(test_data_dir / "cube.stl")`,
  which writes into `tests/data/`. The other `create_cube_stl` calls (lines 247,
  274-275) write to `test_output_dir`, not `tests/data`.
- `tests/conftest.py:60-66` (`sample_stl_file`) returns
  `tests/data/Cube_3d_printing_sample.stl` if present, else `tests/data/cube.stl`.
  `tests/test_debug.py:56-58` has the same fallback.
- `*.stl` is git-ignored, so neither file exists on a fresh checkout; every
  reader falls back to `cube.stl`. Another xdist worker reads it before (or while)
  the writer creates it, so the read fails. Serially the writer test happens to
  run first or the file is left over from an earlier run.

The fault is a test-order dependency on a file that only one test creates, in a
shared directory.

## Rulings (2026-10-20)

- Maintainer: fix it in a Sonnet lane-dev lane. Reason: it blocks a green full
  run. Rejected: fixing in the orchestrator session, or marking the tests
  serial (hides the dependency).
- Maintainer: the cube STL each test reads is produced by a fixture that is safe
  under xdist. Prefer a per-test or per-session tmp path (`tmp_path` /
  `tmp_path_factory`) passed in, so no test writes into `tests/data`. Rejected:
  committing `cube.stl` (the `*.stl` ignore rule forbids it without a `!` rule).
- Maintainer: do not weaken or delete any assertion.

## Settled design

- Make the cube STL a fixture in `tests/conftest.py` that writes the cube once
  (session-scoped via `tmp_path_factory`, with xdist-safe, worker-unique paths,
  or per-test via `tmp_path`) and returns its path. `create_cube_stl` may move to
  conftest or be imported from the test module; the lane chooses.
- `sample_stl_file` keeps preferring `tests/data/Cube_3d_printing_sample.stl`
  when it exists, else returns the generated cube path (not `tests/data/cube.stl`).
- `tests/test_debug.py` and `tests/test_verification.py` (lines ~145-151) take the
  fixture instead of locating or writing `tests/data/cube.stl`.
- In `tests/test_conversion.py` change only lines that locate `cube.stl`, if any.
- The tests' assertions stay as they are.

## Owns

- `tests/conftest.py`
- `tests/test_verification.py`
- `tests/test_debug.py`
- `tests/test_conversion.py` (only lines that locate `cube.stl`)

## Out of scope

- `stl2scad/core/segmentation/**` (a codex lane works there at the same time).
- Detector or converter code; other tests; the `.gitignore`.
- Adding or removing assertions.

## Acceptance

- [x] With `tests/data/cube.stl` deleted first, this command passes three times in
  a row: `flock /tmp/stl2scad-pytest.lock env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -n auto -q -o addopts="" -p no:logging tests/test_conversion.py tests/test_debug.py tests/test_verification.py`.
  This scoped command, with flock, is the acceptance check and the lane may run
  it; it must not run the full suite.
- [x] After those runs `tests/data/cube.stl` does not exist.
- [x] The same three files pass serially (same command without `-n auto`).
- [x] No assertion is removed or weakened; the diff adds or changes only file
  location and fixture code.
- [x] No new test is required; the three files above are the check.
- [x] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [x] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness beyond the scoped acceptance command above. Stage paths explicitly.
