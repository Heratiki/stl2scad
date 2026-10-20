# Work ledger

The orchestrator's queue of work. Update it when a lane starts, lands or
fails, and when the maintainer rules. Procedure:
`docs/agents/external-lanes.md`. Models: `docs/agents/model-register.md`.

## Before any wave

1. `~/.claude/lane-usage.sh`; log the line (memory `lane-usage-tally`,
   "Pool readings"). Reading 2026-10-20T18:06Z: claude 5h 10 % / week 52 %; codex 5h 82 % used (resets 22:06Z) / week 15 %; agy gemini 5h 100 % / week 89 % left; agy-Claude week 14 %; Argon week 81 % left. Codex is above 80 % of its 5h window: no new codex lane before its reset.
2. Check the model lists (`codex debug models`, `agy models`, the Claude
   models in the session) against the register.
3. If this repo uses external lanes: the `lanes` tool `list` (and the tmux
   windows `codex`, `agy` where tmux is installed and `tmux_session` is set).

## Next waves

| Ticket | Route | State | Next |
|---|---|---|---|
| Plan 1 Task 4: slab levels and section profiles | codex lane (`resume` plan1-task3) | queued | first of wave 3; plan file |
| Plan 1 Tasks 5–7 | codex lanes in order | queued | after Task 4 |
| T-005 orientation-dependent treatment numbering (+ UTF-8 temp SCAD writes in `emit.py:245`, `solid.py:211`) | codex lane | open, ruled | owns `defeature.py`; one at a time with T-006, T-008 (same file) |
| T-006 chamfer on a non-orthogonal wall rejected | codex lane | open, ruled | after T-005 |
| T-007 extrusion-axis tie-break loses the chamfer on tall posts | codex lane | open, ruled | owns `regularize.py`; can run beside T-005 |
| T-008 chamfer on a split host wall dropped with no reason | codex lane | open, ruled | after T-006 |
| T-010 revolved solids (cylinders, cones, stepped shafts first) | codex lane | open, ruled | after Plan 1 Task 4 (slabs) |
| T-011 rectangular cutouts / pockets: early named rejection | codex lane | open, ruled | small; any wave |
| T-012 segmentation speed + multi-core for one part | codex lane | open, ruled | profile first |
| T-013 hollow box as negative primitive (void shells) | codex lane | open, ruled (in scope) | after T-011 |
| T-014 shaft keyway as an extruded profile | codex lane | open, ruled | after Plan 1 Task 4 |

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
