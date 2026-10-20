# Work ledger

The orchestrator's queue of work. Update it when a lane starts, lands or
fails, and when the maintainer rules. Procedure:
`docs/agents/external-lanes.md`. Models: `docs/agents/model-register.md`.

## Before any wave

1. `~/.claude/lane-usage.sh`; log the line (memory `lane-usage-tally`,
   "Pool readings"). Baseline 2026-10-20T14:16Z: claude 5h 19 % / week 49 %; codex 5h 60 % / week 12 %; agy gemini 5h 100 % / week 90 % left; agy-Claude week 14 %; Argon week 81 % left.
2. Check the model lists (`codex debug models`, `agy models`, the Claude
   models in the session) against the register.
3. If this repo uses external lanes: the `lanes` tool `list` (and the tmux
   windows `codex`, `agy` where tmux is installed and `tmux_session` is set).

## Next waves

| Ticket | Route | State | Next |
|---|---|---|---|
| Plan 1 Task 3: defeature chamfers and edge rounds | codex lane, `resume` plan1-task2, unlazy ledger | queued | start after `/session-start` |
| Plan 1 Task 3 review (Tasks 2–3) | agy lane, read-only | queued | after Task 3 lands |
| Plan 1 Tasks 4–7 | codex lanes in order | queued | plan file |
| flake8 gate: `stl2scad/core/converter.py:370` F821 undefined `Any` | ticket → lane-dev | needs ticket | ticket-writer |
| Remove the stray gitlink `.claude/worktrees/sweet-lichterman-8d7d99` (added by 24bb594) from the index | orchestrator, one commit | needs maintainer go | `git rm --cached` |

Wave order: a file two tickets need is changed by the first ticket's lane,
merged, then the second lane starts.

## Rulings to ask

One line each, with the recommended option. Ask 1-2 per round
(AskUserQuestion).

- None open.

## Play / manual checks for the maintainer

One line each: what to check, where, and which ticket it closes.

- Open a Task 1 ground-truth SCAD in OpenSCAD (`tests/data/segmentation/stepped_bar.scad`, `clipped_arc_plate.scad`) and confirm the shapes look as intended.

## Done waves

Newest first: `## Wave N — <date>, <pushed at sha | NOT pushed>` and one line
per ticket.

## Wave 1 — 2026-10-20, NOT pushed

- Plan 1 Task 1, synthetic ground truth: ad41450 (codex lane plan1-task1, one fix round for the rib contact).
- Plan 1 Task 2, regularize + extrusion axis: cbca1ee (codex lane plan1-task2, two rule changes recorded in the plan).
- Orchestration bootstrap: e0447f8.
