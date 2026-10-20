# Handoff

**Last Updated:** 2026-10-20 18:10Z — wave 2 landed: T-001, T-002, T-003, T-004 (segmentation is the only pipeline), T-009 (fixture round-trip through segmentation), Plan 1 Task 3; tickets T-005..T-008, T-010..T-014 open with rulings; full run at 38aa5f9: 419 passed, 220 skipped, 30 xfailed, 0 failed; 4 commits not pushed (maintainer pushes with the panel); nothing deployed (no deploy step).

## Next session, first three things

1. Run `/session-start`. Codex was at 82 % of its 5h window at 18:06Z (reset 22:06Z); read the pools before a codex lane.
2. Wave 3: Plan 1 Task 4 (slab levels and section profiles) as a codex lane (`resume` plan1-task3), from `docs/superpowers/plans/2026-10-20-defeature-slabs-hybrid.md`. In parallel, T-007 (`regularize.py`) and then T-005 (`defeature.py`) as codex lanes with disjoint owned files. Queue and order: `docs/agents/work-ledger.md`.
3. Maintainer hand check: convert one real part with the new default (`stl2scad part.stl out.scad`) and open it in OpenSCAD. No SCAD output of this session was opened by hand.

## What Is Currently In-Flight

Nothing. No lane, worktree or background task runs; only the main tree exists.

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
