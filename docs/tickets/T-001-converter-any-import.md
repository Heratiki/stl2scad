# T-001: Import `Any` in converter.py (static gate F821)

Status: open
Opened: 2026-10-20 by the orchestrator, from the failing static gate on main.
Depends on: none

## What happens today

`stl2scad/core/converter.py:370` annotates `device: Any`, but `Any` is never
imported. The typing import at line 14 is
`from typing import Tuple, List, Dict, Optional, Union`. There is no
`TYPE_CHECKING` block and no string-annotation pattern for it. The first gate in
CLAUDE.md "Orchestration settings" fails on main:

`./stl2scad/core/converter.py:370:13: F821 undefined name 'Any'`

(command: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist`).
The annotation sits inside a function body, so it is not evaluated at runtime
and the import still works. Only the linter fails.

## Rulings (2026-10-20)

- Maintainer: fix it in a lane-dev lane (Sonnet). Reason: the gate blocks every
  lane. Rejected: fixing it in the orchestrator session (it edits no code).
- Maintainer: expected fix is to add `Any` to the existing `from typing import`
  line. No behaviour change.

## Settled design

In `stl2scad/core/converter.py` line 14, add `Any` to the existing typing
import. Nothing else changes.

## Owns

- `stl2scad/core/converter.py`
- `docs/tickets/T-001-converter-any-import.md` (Status line only)

## Out of scope

- `stl2scad/core/segmentation/**` (a codex lane works there at the same time;
  do not touch it).
- Any other file, any refactor or reordering of imports, any behaviour change.

## Acceptance

- [ ] The full-repo flake8 command above reports 0.
- [ ] `.venv/bin/python -c "import stl2scad.core.converter"` succeeds.
- [ ] `git diff --name-only main` lists only `stl2scad/core/converter.py` and this ticket.
- [ ] No new tests. Existing tests stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
