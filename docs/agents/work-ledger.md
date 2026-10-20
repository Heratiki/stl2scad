# Work ledger

The orchestrator's queue of work. Update it when a lane starts, lands or
fails, and when the maintainer rules. Procedure:
`docs/agents/external-lanes.md`. Models: `docs/agents/model-register.md`.

## Before any wave

1. `~/.claude/lane-usage.sh`; log the line (memory `lane-usage-tally`,
   "Pool readings"). Reading 2026-10-20T20:35Z (after wave 3): claude 5h 22 % / week 54 %; codex 5h 21 % / week 21 %; agy gemini 5h 100 % / week 89 % left; agy-Claude week 14 %; Argon week 81 % left. Before wave 3 (20:01Z): claude 5h 16 % / week 53 %; codex 5h 0 % / week 15 %.
2. Check the model lists (`codex debug models`, `agy models`, the Claude
   models in the session) against the register.
3. If this repo uses external lanes: the `lanes` tool `list` (and the tmux
   windows `codex`, `agy` where tmux is installed and `tmux_session` is set).

## Next waves

| Ticket | Route | State | Next |
|---|---|---|---|
| Plan 1 Task 5: remainder regions and the new dispatch | codex lane (`resume` plan1-task4) | queued | first of wave 4; plan file |
| Plan 1 Tasks 6–7 | codex lanes in order | queued | after Task 5 |
| T-006 chamfer on a non-orthogonal wall rejected | lane-dev (Sonnet) or codex | open, ruled | owns `defeature.py`; one at a time with T-008, T-015 |
| T-008 chamfer on a split host wall dropped with no reason | lane-dev or codex | open, ruled | after T-006 |
| T-015 part-intrinsic numbering for twin side faces | lane-dev (Opus, design inside) or codex | open, ruled | `defeature.py`; after T-006 or T-008 |
| T-010 revolved solids (cylinders, cones, stepped shafts first) | codex lane | open, ruled | slabs landed; can start |
| T-011 rectangular cutouts / pockets: early named rejection | codex lane | open, ruled | small; any wave |
| T-012 segmentation speed + multi-core for one part | codex lane | open, ruled | profile first |
| T-013 hollow box as negative primitive (void shells) | codex lane | open, ruled (in scope) | after T-011 |
| T-014 shaft keyway as an extruded profile | codex lane | open, ruled | slabs landed; can start |

Wave order: a file two tickets need is changed by the first ticket's lane,
merged, then the second lane starts. Plan 1 Task 4 and T-005..T-008 all touch
`stl2scad/core/segmentation/**`: give each lane its owned files and run
`defeature.py` tickets one at a time.

## Rulings to ask

One line each, with the recommended option. Ask 1-2 per round
(AskUserQuestion).

- None open.

## Play / manual checks for the maintainer

One line each: what to check, where, and which ticket it closes.

- Convert a real part with the new default pipeline (`stl2scad part.stl out.scad`) and open the result in OpenSCAD (closes nothing; first hand check after T-004).
- Open a Task 1 ground-truth SCAD in OpenSCAD (`tests/data/segmentation/stepped_bar.scad`, `clipped_arc_plate.scad`) and confirm the shapes look as intended.

## Done waves

Newest first: `## Wave N — <date>, <pushed at sha | NOT pushed>` and one line
per ticket.

## Wave 3 — 2026-10-20, NOT pushed

- T-007 extrusion-axis tie prefers the axis that explains treatments: 0fd713a (Sonnet lane-dev; first commit broke `test_oblique_edge_is_not_a_treatment`, fixed in one round by counting only treatments defeature keeps).
- T-005 treatment numbering from a centroid-anchored frame, + UTF-8 temp SCAD writes: 0b81078 (Sonnet lane-dev). Twin side faces keep the world-axis sign (maintainer ruling 2026-10-20); follow-up T-015 (8239599).
- Plan 1 Task 4, slab levels and section profiles: 9fb6f58 (codex lane plan1-task4, gpt-6.1-sol high, resume of plan1-task3). Known limits in `.scratch/lanes/plan1-task4/REPORT.md`: multi-chain or branched regions raise ValueError.
- Out of repo: lane-panel 0.7.1 (Codex usage reader past imported rollouts, f4826c8) and claude-config 4b541bc (`lane-usage.sh`), both pushed. Claude estimate fix in session `lane-panel-estimates`.
- Full run at 9fb6f58: 441 passed, 220 skipped, 30 xfailed, 0 failed.

## Wave 2 — 2026-10-20, pushed to 608296f; 4 commits after it NOT pushed

- T-001 flake8 `Any` import: 6a765ae (Sonnet lane-dev).
- Stray gitlink removed: 8a352d7 (orchestrator).
- T-002 xdist-safe cube STL fixture: ec44300 (Sonnet lane-dev).
- Plan 1 Task 3, defeature chamfers and edge rounds: d13c881 (codex lane plan1-task3; agy review → T-005..T-008).
- T-003 archive the legacy revolve detector: 730d6b4 (Sonnet lane-dev).
- T-004 deprecate the legacy pipeline, segmentation is the default: c792e76 (Opus lane-dev; codex adversarial review found 4 defects, fixed in one round).
- T-009 fixture round-trip through segmentation: 38aa5f9 (Sonnet lane-dev).
- lane-panel 0.7.0 (layout cap, short-pane budget, push warnings): 99ff902 in `~/.claude/mods/lane-panel`, pushed to GitHub.
- Tickets written: T-004..T-014. Full run at c63516a's parent 38aa5f9: 419 passed, 220 skipped, 30 xfailed, 0 failed.

## Wave 1 — 2026-10-20, pushed

- Plan 1 Task 1, synthetic ground truth: ad41450 (codex lane plan1-task1, one fix round for the rib contact).
- Plan 1 Task 2, regularize + extrusion axis: cbca1ee (codex lane plan1-task2, two rule changes recorded in the plan).
- Orchestration bootstrap: e0447f8.
