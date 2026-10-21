# T-016: Cache the OpenSCAD renders that tests make of their own SCAD

Status: landed (worktree-agent-a9fa99a8eacad6ef6, 2026-10-21)
Opened: 2026-10-21 by the orchestrator, from the maintainer's report that test runs are "ridiculously painfully long" and make the computer almost unusable.
Depends on: wave order. Plan 1 Task 6 (adds `tests/test_segmentation_treatments.py`, edits `tests/test_segmentation_compose.py` on its branch) and T-006 (edits `tests/test_segmentation_defeature.py`) merge first, because this ticket touches their test files. No ADR is touched.

## What happens today

- 10 of the 12 files `tests/test_segmentation_*.py` mention OpenSCAD (`grep -lE "run_openscad|openscad"`): bracket, emit, features, defeature, fixtures, regularize, rounded_plate, slabs, review, treatments_truth. Their renders go through `run_openscad` from `stl2scad/core/openscad/runner.py` with `["--render", "-o", stl, scad]`. Examples: `tests/test_segmentation_fixtures.py:65`, `tests/test_segmentation_bracket.py:66,234,241`, `tests/test_segmentation_rounded_plate.py:38,197,207,282`, `tests/test_segmentation_slabs.py:240,262`, `tests/test_segmentation_treatments_truth.py:130,218,322,383`.
- Nothing is cached between runs. The rendering fixtures are `scope="module"` (`test_segmentation_bracket.py:50,60`, `_emit.py:22`, `_treatments_truth.py:123`, `_rounded_plate.py:32`), and `tests/conftest.py:108-111` gives a session-scoped repo-local `tmp_path_factory`. Under `pytest-xdist -n auto` each worker has its own session and modules, so one part can render once per worker in one run, and again on every later run.
- Cost, from lane logs of 2026-10-21: the segmentation "not slow" slice took 315 s for 382 tests; the 34 compose tests alone took 188 s. The maintainer reports the machine is nearly unusable during runs.
- `tests/test_segmentation_compose.py` does not exist on main at the time of writing (the grep finds no such file); it arrives with Plan 1 Task 6. The lane finds its render calls after that merge.
- `openscad --version` prints `OpenSCAD version 2026.10.13` on this machine.

## Rulings (2026-10-21)

Orchestrator defaults. The maintainer asked only for the ticket ("ticket the render cache"); the rest below is the orchestrator's default and the maintainer may overrule it.

- Scope: the renders that tests make of their own truth or input SCAD (SCAD text to STL). Reason: that is the repeated, input-identical work. Out of scope: the validation renders inside `emit_scad` (the Hausdorff gate and the snap loop); that is product code and belongs to T-012. Rejected: a cache inside `run_openscad` for all callers, because it changes product behaviour.
- Key: SHA-256 of the SCAD text, the OpenSCAD version string, and the render arguments (with the input and output paths removed from the arguments). A changed SCAD, OpenSCAD build or argument misses the cache. Rejected: key by file name (stale hits). A SCAD that `include`s or `use`s another file must hash that file too, or the helper must refuse to cache it and render.
- Location: one directory, default repo-local `tests/.render_cache/`, git-ignored. The env var `STL2SCAD_RENDER_CACHE` overrides it with an absolute path, so xdist workers and lane worktrees can share one cache. Rejected: per-worktree default only, since it gives lane worktrees no sharing; the env var covers that.
- Safe under xdist: write the STL to a temp file in the cache directory, then `os.replace` into place. A reader never sees a partial STL. Two workers racing on one key both render; the last replace wins; both files are identical.
- Off switch: `STL2SCAD_RENDER_CACHE=off` disables the cache so every render runs (for a clean check). A failed render is never cached.

## Settled design

- New `tests/render_cache.py` with one function, `cached_render(name, args, scad_path, stl_path, log_path, openscad_path)`. It has the same call shape as the current `run_openscad` calls, so a call site changes by name only. It computes the key, on a hit copies the cached STL to `stl_path` and returns True, on a miss calls `run_openscad`, stores the result atomically, and returns its result.
- It keeps a per-process counter of real renders and, when `STL2SCAD_RENDER_CACHE_LOG` is set, appends one line `render miss <name>` or `render hit <name>` to that file. This is the proof for the acceptance below.
- Call sites in the 10 test files replace the direct `run_openscad` render of test inputs with `cached_render`. No assertion changes. Calls that exercise `run_openscad` itself as the thing under test stay as they are.
- `tests/conftest.py` gets only what the helper needs (for example a session-start note of the cache directory). `.gitignore` gets `tests/.render_cache/`.

## Owns

- `tests/conftest.py`
- `tests/render_cache.py` (new)
- `tests/test_segmentation_*.py` (render call sites only; no assertion change)
- `.gitignore`
- `docs/tickets/T-016-test-render-cache.md` (Status line only)

## Out of scope

- Any file under `stl2scad/` (product code), including `run_openscad` and `emit_scad`. The `emit_scad` validation renders belong to T-012.
- Caching the segmentation or conversion results, or any change to which tests are `slow`.
- Changing a test assertion, tolerance or fixture.
- Non-segmentation test files, unless they already render through the same pattern and the lane lists them in its report.

## Acceptance

- [x] `test_render_cache_hit_skips_render`: a second `cached_render` of the same SCAD text, version and arguments performs 0 OpenSCAD renders (the counter stays at 1) and writes an identical STL.
- [x] `test_render_cache_miss_on_changed_scad`: changing one character of the SCAD text renders again.
- [x] `test_render_cache_off_switch`: with `STL2SCAD_RENDER_CACHE=off` every call renders.
- [x] `test_render_cache_atomic_write`: the cached file appears only through `os.replace`; a stale temp file left in the cache directory is never returned as a hit. A failed render stores nothing.
- [x] Proof on a named file: run `tests/test_segmentation_bracket.py` twice with `STL2SCAD_RENDER_CACHE_LOG` set; the second run's log has 0 `render miss` lines for test inputs.
- [ ] The lane report records measured wall time, before and after, of `tests/test_segmentation_compose.py` (if merged) and of the segmentation "not slow" slice, each with a cold and a warm cache. Measured, not estimated. A lane that may not run the harness asks the orchestrator to run them and records the numbers it is given.
- [x] Existing assertions in all `tests/test_segmentation_*.py` stay unchanged; the diff of those files shows render call sites only.
- [x] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [x] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
