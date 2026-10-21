# Handoff

**Last Updated:** 2026-10-21 03:30Z — wave 4 landed: T-006 (chamfer edge tested against its own host-face line), Plan 1 Tasks 5+6 (compose path, remainder regions, emit; `plate_counterbore_and_slot` and `plate_cutout_and_hole` now parametric); T-016 (test render cache) written; T-008 FAILED verification on the combined code and is unmerged (`lane/t008`); full run at 922d2ae: 540 passed, 220 skipped, 28 xfailed, 0 failed; not pushed; nothing deployed (no deploy step).

## Next session, first three things

1. Run `/session-start`. Ask the maintainer for the T-008 dispatch ruling (section 4, "Open"); recommended: only real treatment candidates (a face with a cap/side pair) get a `rejected` entry, "no host pair" goes to a diagnostics list that does not trigger the compose path, and the `best_sides` tie tolerance is checked against `prism_triangle` and the composite bracket.
2. Wave 5: the T-008 fix round on `lane/t008` (its test scope must include `tests/test_segmentation_compose.py`, `tests/test_segmentation_treatments.py` and the fixture slice, because `defeature.py` feeds the compose dispatch). In parallel, T-016 (test render cache, Sonnet lane-dev; touches test files only). Then Plan 1 Task 7 (codex, NEW session, not a resume) and T-015.
3. Maintainer hand check (open since session 2): convert one real part (`stl2scad part.stl out.scad`) and open it in OpenSCAD.

## What Is Currently In-Flight

- `lane/t008` (worktree `.claude/worktrees/lane/t008`, HEAD b591664 = lane commit 15a3623 + a merge of main for verification). Not running. Next action: a fix round after the ruling; then `lane-verifier` with the wider test scope; merge on PASS, or `scripts/lane-worktree.sh rm lane/t008 --force` if the maintainer drops it.
- Nothing else runs. The only other worktree is main.

## 4. Session 2026-10-21 (first session of the day)

Landed (main, `--no-ff`; each lane checked by lane-verifier):
- T-006 (a671f01; agy gemini-3.8-flash-high, lanes t006 + t006-fix): `_oblique` compares the edge with its own cap/side intersection line; `_host_pairs` picks `best_side`. Maintainer ruling 2026-10-21: the old `test_oblique_edge_is_not_a_treatment` (a regular chamfer on a 20 degree wall) is legal under T-006; renamed `test_regular_chamfer_on_20_degree_wall_is_found`, expects `chamfer_1`. `test_genuinely_oblique_edge_still_rejected` keeps the guard.
- Plan 1 Tasks 5+6 (6e650b9; codex gpt-6.1-sol high; Task 5 resumed the plan1-task4 session, Task 6 a new session stacked on it). Maintainer ruling: merge the two together, because Task 5 alone changed three known-gap fallback reasons. Result: two known gaps converted parametric (moved in `fixture_expectations.json`, counts match the manifest), `non_revolve_shaft_with_keyway` keeps its old reason, the 7 old-path SHA-256 hashes (recorded at 5099629) still match.
- T-016 ticket (test render cache; maintainer-reported slow test runs).
- CLAUDE.md rule "Test scope" (maintainer 2026-10-21): a lane runs only its own test files; suite-verifier runs the full suite once after the merge. The maintainer rejected a per-worktree lock and `nice`/`-n 4`.
- Full run at 922d2ae: 540 passed, 220 skipped, 28 xfailed, 0 failed (7 min 8 s).

Not verified by the maintainer: no SCAD output of Tasks 5-6 (slabs, treatments, remainder polyhedra) was opened in OpenSCAD by hand.

Open:
- T-008 (lane/t008): correct alone (its 90 defeature/truth tests pass), but on the combined code 19 compose/treatment tests fail, 4 of 7 old-path hashes change (composite bracket: "Rejected treatment F9 has ambiguous hosts"), and `prism_triangle` falls back. Cause: new `rejected` entries ("no host pair", "ambiguous hosts" from the `best_sides` tie tolerance) trigger the Task 5 dispatch (`features.py` about line 661: compose when `rejected` is not empty). The T-008 ruling "every dropped candidate gets a reason" conflicts with that dispatch rule. Verifier ledger: `.unlazy/verify-lane-t008/GATES.md`.
- Lane-panel (maintainer-reported: progress and estimates looked wrong): (a) a codex `--resume` joins the new lane to the first job of the session chain (`jobId` of plan1-task5 was `codex:plan1-task2@...`, `round: 14`), so its estimate mixes five tasks and `register.py append` refuses a plan1-task5 row ("exists"); (b) the panel shows progress only by ticked gates, and a brief that ticks at the end shows 0 the whole time; (c) agy lanes started in a worktree register as `agy-pid<N>` with no lane name (t006 = pid180721, t006-fix = pid274937, t008 = pid388227). Fix in `~/Source/lane-panel` (this host and GitHub). Not ticketed: the maintainer has not asked for a fix lane yet.
- Slow lanes: test runs take 3-5 min each and all lanes share one pytest lock; T-016 and the test-scope rule address this. Start codex lanes in a new session per task (a 14-round resume chain is slow).
- `.scratch/lanes/*/GATES.md` show unmet in `gate-check --status` because the lanes ticked them by hand without unlazy approvals; the lane-verifier re-ran them. `.unlazy/` keeps the old scopes plus `verify-lane-t006` (G3 abandoned, a wrong guess of the verifier) and `verify-lane-t008` (G3, G4 unmet = the T-008 failure). None removed.
- Codex 5h pool at 76 % (03:25Z); no codex lane before its reset.

## 3. Session 2026-10-20 (fourth session of the day)

Landed (main, `--no-ff`; each lane checked by lane-verifier and a scoped suite-verifier run before its merge):
- T-007 (0fd713a): in an extrusion-axis tie, the axis that explains more kept treatments wins, then cap area; 1 % band unchanged. First commit broke `test_oblique_edge_is_not_a_treatment` (caught by the scoped run); one fix round counts only treatments that defeature keeps.
- T-005 (0b81078): `_side_frame` sign from the mesh centroid; a dominant-face tie-break (support, area, id); `write_text(..., encoding="utf-8")` in `emit.py` and `solid.py`. Maintainer ruling: a side face with an equal-area opposite twin keeps the world-axis sign. lane-verifier showed that non-symmetric parts with equal opposite walls also reach that fallback, so numbering can still change with orientation for them: T-015 (8239599).
- Plan 1 Task 4 (9fb6f58): `stl2scad/core/segmentation/slabs.py` (`Slab`, `slab_levels`, `slab_profiles`), 15 tests; not wired into dispatch yet (Task 5). Limits: a region with more than one section chain or a branched face graph raises `ValueError`; rule clarifications are in the plan and `.scratch/lanes/plan1-task4/REPORT.md` (this host only).
- Full run at 9fb6f58: 441 passed, 220 skipped, 30 xfailed, 0 failed.

Out of repo (this host and GitHub): lane-panel 0.7.1 (Codex usage reader skips rollouts with no reading; a Codex Desktop import of 23 sessions had hidden every reading) and 0.7.2 (Claude estimates); claude-config 4b541bc (`lane-usage.sh`, same fix). Source repos: `~/Source/lane-panel`, `~/Source/claude-config`; `~/.claude/plugins/marketplaces/heratiki-mods` is a pull-only copy.

Open:
- The handoff's earlier Codex reset time (22:06Z) was wrong; the 82 % window had reset at 18:06Z.
- `.unlazy/` has 13 old scopes from waves 1–2, all met except `ticket-gaps` (one abandoned gate, known). None removed.
- Codex still loads lane-panel 0.7.0 from its own plugin cache (`~/.codex/plugins/cache/heratiki-mods/lane-panel/0.7.0`) and warns that its `hooks.json` has an unknown field `modules`.
- The register row `plan1-task3` (20:27Z, 362.9 min) holds the plan1-task4 resume merged into it; there is no separate plan1-task4 row.
- Not verified by hand: no SCAD output of this session was opened in OpenSCAD.

## 2. Session 2026-10-20 (third session of the day)

Landed (main, merges with `--no-ff`; each lane checked by lane-verifier, T-004 also by a codex adversarial review):
- T-001 (6a765ae): `Any` import; the flake8 gate is green.
- T-002 (ec44300): cube STL fixture is xdist-safe (13 flaky failures gone).
- Plan 1 Task 3 (d13c881): `stl2scad/core/segmentation/defeature.py`. An agy review found 7 points; 5 confirmed by repro, ticketed as T-005..T-008.
- T-003 (730d6b4): legacy revolve detector archived.
- T-004 (c792e76): the legacy pipeline cannot run. Segmentation is the default and only conversion path (`stl2scad/core/conversion.py`); `--pipeline legacy` warns and exits 2; legacy code in `stl2scad/legacy/`, tests in `tests/legacy/` (run with `STL2SCAD_LEGACY_TESTS=1`). OpenSCAD helpers in `stl2scad/core/openscad/runner.py`. Review round added: `networkx` and `trimesh` required, STL validation restored, Python ≥3.10, UTF-8 output.
- T-009 (38aa5f9): `tests/test_segmentation_fixtures.py`. Of 95 fixtures, 61 parametric (all counts match the manifest), 34 known gaps listed by reason in `tests/data/segmentation/fixture_expectations.json`; 16 `slow` fixtures run only with `-m slow` (about 13 min).
- Agent guides (`CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`) describe the new pipeline and invariant 2.
- Outside this repo: lane-panel 0.7.0 (`~/.claude/mods/lane-panel`, this host; pushed to GitHub `Heratiki/lane-panel` at 99ff902). GNOME idle action on AC set to `nothing` on FlipIt (battery still suspends).

Maintainer rulings of this session:
- Ticket every detector false positive and new primitive issue without asking; the maintainer may set `wontfix` (memory `ticket-detector-defects`).
- Retire the legacy pipeline completely; keep `--pipeline` for future pipelines; exit 2 for `legacy`.
- Fixture round-trip runs through segmentation now; slow fixtures behind a marker.
- Rulings recorded in T-005..T-008 and T-010..T-014 (T-013 hollow box is in scope as a negative primitive; T-012 adds multi-core for one part).
- The panel's push Button warns and never blocks for policy.

Not verified by the maintainer: no converted SCAD was opened in OpenSCAD by hand.

Open issues (no ticket, small):
- About 5 tests in `tests/legacy/test_cgal_backend.py` resolve a path one level too short; they fail only with `STL2SCAD_LEGACY_TESTS=1`.
- `pytest.ini`: the old `markers =` block (openscad, conversion, visualization) sits under `[coverage:html]` and is not read; harmless while `--strict-markers` is off.
- `l_bracket_wide` has no manifest entry; its expected counts come from its own first output (`"manifest": false`).
- The slow fixtures and T-012: one part uses one core; the hole-grid plates take 7–12 min.
- `.unlazy/ticket-gaps/GATES.md` has one abandoned gate (G3, a wrong regex, replaced by G4); not a work item.
- Reusable check scripts from T-004 (dependency audit, move checker, validator corpus run) are in `.scratch/t004-checks/` (ignored, this host only).

## 1. Session 2026-10-20 (second session of the day)

Landed:
- Spec `docs/superpowers/specs/2026-10-20-edge-rounds-design.md` (approved): convex edge rounds, symmetric chamfers, clipped profile arcs, rib ends, stepped extrusions, cartridge feet as a parametric ellipse plus a round along the curved edge, screw features (countersink, counterbore, modeled threads), hybrid free-form remainder (max 10 % of the surface).
- Argon research `docs/research/2026-10-20-argon-reconstruction-methods.md`; its architecture (regularize → defeature → slab slicing → replay) is adopted.
- Plan 1 `docs/superpowers/plans/2026-10-20-defeature-slabs-hybrid.md` (7 tasks). Plans 2 (ellipse, curved-edge round) and 3 (screw features) follow.
- Task 1: synthetic ground truth (`tests/data/segmentation/treatments_expected.json`, 15 SCAD files, `tests/test_segmentation_treatments_truth.py`).
- Task 2: `stl2scad/core/segmentation/regularize.py` (`regularize`, `extrusion_axis`). The axis rule changed twice; the plan records why.

User rulings of this session (also in the spec):
- Progress rule: hard regions may pass as polyhedron regions for now; full parametric is the long-term goal.
- Snapping moves a value by 0.001 mm or less (confirmed).
- The `memo_cartridge` feet are an exact quarter ellipse 3 × 8 mm (measured; the draft arcs C120–C125 are wrong).

Not verified by the maintainer: none of the new SCAD output has been opened in OpenSCAD by hand yet.

Open:
- The baseline has 3 known failures (`revolve_triangle_profile`); the user said not to fix them now.
- The flake8 gate failure above.

Ledger: `docs/agents/work-ledger.md` (queue and Wave 1). Outside this repo (this host only; also on GitHub): lane-panel mod at `~/.claude/mods/lane-panel` (0.6.0, GitHub `Heratiki/lane-panel`); global config `~/.claude` (GitHub `Heratiki/claude-config`).
