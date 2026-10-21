# T-017: Name a test for the "ambiguous hosts" rejection in defeature

Status: open
Opened: 2026-10-21 by the orchestrator, from the maintainer's request ("ticket the ambiguous hosts test").
Depends on: T-008 (merged 9ebe34d), T-016 (render cache). No ADR is touched.

## What happens today

- `stl2scad/core/segmentation/defeature.py:213-215` appends `rejected.append((face.id, "ambiguous hosts"))` when a candidate face has more than one cap/side pair (`len(pairs) > 1`).
- `grep -n ambiguous tests/test_segmentation_defeature.py` finds nothing. No test names this rejection, so a change that stops producing it, or produces it for the wrong faces, passes unnoticed.
- T-008 changed the `best_sides` tie tolerance from `atol = sine` (about 0.5 degrees) to `atol = 1e-5` (`.scratch/lanes/t008-r2/REPORT.md` lines 24-26) and merged coplanar host faces before pairing. The T-008 round-1 report (`.scratch/lanes/t008/REPORT.md` lines 61-63) measured one case: a corner cut across a 90 degree corner gave 2 pairs (two non-coplanar walls with a tied dot product), `treatments == []` and `rejected == (('F6', 'ambiguous hosts'),)`. That was under the old tolerance. Round 2 states that true symmetries (a symmetric 45 degree corner cut) still tie to within 1e-8 to 1e-10, but no test checks it.
- `tests/test_segmentation_defeature.py` calls `run_openscad` directly at lines 181, 232, 266, 293 and 336 (each as `["--render", "-o", ..., ...]`). T-016 left this file out because T-008 owned it then. T-008 is merged, so the file can use `tests.render_cache.cached_render`, as `tests/test_segmentation_bracket.py:21,67,237` does.

## Rulings (2026-10-21)

Orchestrator defaults; the maintainer asked only for the ticket and may overrule these.

- Add one test, `test_symmetric_corner_cut_is_rejected_as_ambiguous_hosts`, in `tests/test_segmentation_defeature.py`. Reason: the reject path is documented behaviour with no test. Rejected: testing `_host_pairs` directly, because it is private and the public `defeature()` result is the contract.
- Convert the render call sites in that file to `cached_render`. Reason: T-016 deferred them; the file now has no other owner. Rejected: leaving them, since each is an uncached OpenSCAD render on every run.
- Test only; no product code change. If the case does not give "ambiguous hosts" under `atol = 1e-5`, the lane stops and reports it. That is a finding, not a test to weaken or to bend until it passes.

## Settled design

- New test in `tests/test_segmentation_defeature.py`, following the existing T-008 tests: write SCAD text to `tmp_path`, render with `cached_render`, then `segment_mesh(Mesh.from_file(...))` and `defeature(...)`.
- Geometry: a block with a symmetric 45 degree cut across one 90 degree vertical corner (the cut plane's normal is at 45 degrees between the two adjacent walls, so both walls tie in dot product). The cut face is the candidate.
- Asserts, for the cut face id `fid` (found as the planar face whose normal is horizontal and at 45 degrees to both walls):
  - `(fid, "ambiguous hosts") in output.rejected`
  - `fid not in {t.face_id for t in output.treatments}`
  - `fid not in {d[0] for d in output.diagnostics}`
- All existing `run_openscad(` calls in the file become `cached_render(name, ["--render"], scad, stl, log, openscad_path)`; the `run_openscad` import is dropped if unused.

## Owns

- `tests/test_segmentation_defeature.py`
- `docs/tickets/T-017-ambiguous-hosts-test.md`

## Out of scope

- Any change to `stl2scad/core/segmentation/**` or to the tolerance.
- Other rejection reasons ("no host pair", "non-positive size").
- Other test files and `tests/render_cache.py`.

## Acceptance

- [ ] `test_symmetric_corner_cut_is_rejected_as_ambiguous_hosts`: the cut face is in `rejected` with reason "ambiguous hosts", not in `treatments`, not in `diagnostics`.
- [ ] No `run_openscad(` call remains in `tests/test_segmentation_defeature.py`; the renders use `cached_render`.
- [ ] Existing tests in `tests/test_segmentation_defeature.py` keep their assertions unchanged.
- [ ] Test scope: run only `tests/test_segmentation_defeature.py`, as the maintainer ruled on 2026-10-21.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
