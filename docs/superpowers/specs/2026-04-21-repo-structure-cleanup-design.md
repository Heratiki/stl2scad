# Repo Structure Cleanup — Design

**Date:** 2026-04-21
**Status:** Approved (Option B — "Organized")
**Scope:** Non-code file hygiene + documentation consolidation. The `stl2scad/` package, test `test_*.py` files, and checked-in fixture data are explicitly out of scope.

## Goals

1. Clean up root-level clutter (tracked runtime artifacts that should be gitignored).
2. Consolidate documentation under `docs/` so planning, reviews, and the Cline-style memory bank live in one place.
3. Separate stale generated test outputs from real fixtures under `tests/data/`.
4. Normalize inconsistent script naming (`stl2scad-cgal-helper.py` → `stl2scad_cgal_helper.py`).
5. Preserve every one of the three detector-validation invariants defined in [CLAUDE.md](../../../CLAUDE.md).

## Non-goals

- No changes to Python package layout (no `src/` layout).
- No deletions — only moves, renames, and `git rm --cached` untracking.
- No touching the user's in-flight uncommitted changes on `main`.
- No edits to `stl2scad/` source code.
- No edits to `tests/test_*.py` test logic.

## Target directory structure

```
stl2scad/
├── .github/                          (unchanged)
├── .vscode/                          (unchanged, gitignored)
├── docs/
│   ├── README.md                     ← NEW: index of what each dir holds
│   ├── planning/
│   │   ├── cgal_integration_boundary.md
│   │   ├── feature_level_reconstruction.md
│   │   ├── parametric_conversion_roadmap.md
│   │   ├── phase2_release_checklist.md
│   │   ├── debug_test_plan.md        ← MOVED from tests/
│   │   └── stl2scad_plan.docx
│   ├── reviews/
│   │   └── stl2scad_review.docx
│   ├── memory-bank/                  ← MOVED from root (still gitignored)
│   │   ├── accuracy_verification_plan.md
│   │   ├── activeContext.md
│   │   ├── decisionLog.md
│   │   ├── productContext.md
│   │   ├── progress.md
│   │   └── systemPatterns.md
│   └── superpowers/specs/            ← NEW: design docs (this file lives here)
├── stl2scad/                         (unchanged — off-limits)
├── tests/
│   ├── conftest.py, pytest.ini, __init__.py, utils.py  (unchanged)
│   ├── test_*.py                     (unchanged)
│   └── data/
│       ├── Cube_3d_printing_sample.stl           (unchanged, gitignored)
│       ├── Stanford_Bunny_sample.stl             (unchanged, gitignored)
│       ├── Eiffel_tower_sample.STL               (unchanged, gitignored)
│       ├── Menger_sponge_sample.stl              (unchanged, gitignored)
│       ├── benchmark_fixtures/                   (unchanged — tracked)
│       ├── feature_fixtures_manifest.json        (unchanged — tracked)
│       ├── feature_fixtures_scad/                (unchanged — tracked)
│       └── .generated/                           ← NEW gitignored dir
│           └── (stale Cube_* outputs moved here)
├── scripts/
│   ├── stl2scad_cgal_helper.py       ← RENAMED from stl2scad-cgal-helper.py
│   └── (others unchanged)
├── artifacts/                        (unchanged)
├── README.md, CLAUDE.md, AGENTS.md   (stay at root — convention)
├── setup.py, requirements*.txt       (unchanged)
└── .gitignore                        (updated — see below)
```

## Operation list

### Untrack tracked runtime artifacts (stay on disk)

| Path | Action |
|---|---|
| `.coverage` | `git rm --cached` |
| `chats.db` | `git rm --cached` |
| `.codex` (empty file) | `git rm --cached` |
| `stl2scad.egg-info/` (6 files) | `git rm --cached -r` |
| `tests/data/Cube_3d_printing_sample_verification.html` | `git rm --cached`, then move to `.generated/` |
| `tests/data/Cube_3d_printing_sample_visualizations/*.png` (14 files) | `git rm --cached -r`, then move to `.generated/` |

### Move tracked files with `git mv`

| From | To |
|---|---|
| `tests/debug_test_plan.md` | `docs/planning/debug_test_plan.md` |
| `scripts/stl2scad-cgal-helper.py` | `scripts/stl2scad_cgal_helper.py` |

`memory-bank/` is currently untracked (gitignored), so it's moved with plain `mv` and the gitignore entry is updated to `docs/memory-bank/`.

### Move untracked files (plain `mv`)

The currently-untracked stale Cube debug outputs land under `tests/data/.generated/`:

- `Cube_3d_printing_sample.scad`
- `Cube_3d_printing_sample_debug.scad`
- `Cube_3d_printing_sample_debug.echo`
- `Cube_3d_printing_sample_debug_analysis.log`
- `Cube_3d_printing_sample_debug_echo.log`
- `Cube_3d_printing_sample_debug_preview.log`

### New files

- `docs/README.md` — one-page index of `docs/planning/`, `docs/reviews/`, `docs/memory-bank/`, `docs/superpowers/specs/`.

### `.gitignore` changes

Add:
```
.coverage
chats.db
.codex
stl2scad.egg-info/
tests/data/.generated/
```

Update:
```
memory-bank/      →  docs/memory-bank/
```

## Reference updates

Every moved path needs a grep-based sweep of incoming references. Expected hit sites (must be verified, not assumed):

| Change | Likely-affected files |
|---|---|
| `memory-bank/` → `docs/memory-bank/` | `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `README.md`, `docs/planning/*` |
| `tests/debug_test_plan.md` → `docs/planning/debug_test_plan.md` | `tests/README.md`, planning docs |
| `stl2scad-cgal-helper.py` → `stl2scad_cgal_helper.py` | `stl2scad/core/cgal_backend.py`, `docs/planning/cgal_integration_boundary.md`, `CLAUDE.md`, any `subprocess` callers |
| Stale Cube outputs → `.generated/` | `tests/README.md` if it describes fixture layout |

Auto-memory files at `C:\Users\herat\.claude\projects\c--Users-herat-source-stl2scad\memory\` will be updated if they reference moved paths (checked during implementation).

## Validation strategy

### Invariants that must hold

Per [CLAUDE.md](../../../CLAUDE.md), the three non-negotiable detector-validation tests:

1. `test_feature_fixture_manifest_matches_checked_in_scad` — byte-exact regeneration.
2. `test_feature_fixture_round_trip_detection` — dimensional round-trip.
3. `test_feature_fixture_manifest_covers_roadmap_stress_cases` — roadmap coverage.

### Pre-reorg baseline

1. Run `pytest tests/ -v 2>&1 | tee /tmp/pre_reorg_pytest.log` — capture pass/skip/fail counts.
2. Confirm uncommitted work on `main` (feature_fixtures.py, feature_graph.py, manifest, tests, new plate_plain_chamfered_edges.scad) is isolated from reorg commits. Do not mix.

### Per-commit verification

After each logical chunk:
- `python -c "import stl2scad; import stl2scad.core.feature_graph; import stl2scad.core.feature_fixtures"` — imports resolve.
- `pytest tests/test_feature_fixtures.py -x` — fastest detector feedback.
- Only proceed if green.

### Post-reorg full validation

1. Re-run `pytest tests/ -v`; diff against baseline. Any new failure or changed skip count blocks merge.
2. End-to-end smoke: `python scripts/build_feature_graph.py tests/data/Cube_3d_printing_sample.stl --output /tmp/postreorg_graph.json`.
3. Renamed-script smoke: `python scripts/stl2scad_cgal_helper.py --help` (or equivalent).

### Commit sequence

Each commit is independently revertable:

1. `.gitignore` additions only.
2. Untrack runtime artifacts (`.coverage`, `chats.db`, `.codex`, `stl2scad.egg-info/`).
3. Move stale Cube debug outputs to `tests/data/.generated/`.
4. Move `memory-bank/` → `docs/memory-bank/` + update gitignore + doc references.
5. Move `tests/debug_test_plan.md` → `docs/planning/` + update references.
6. Rename `scripts/stl2scad-cgal-helper.py` → `stl2scad_cgal_helper.py` + update callers.
7. Add `docs/README.md` index.

### Rollback

If any commit breaks an invariant, `git revert` that specific commit. No destructive ops (`reset --hard`, force push, etc.).

### Out of scope for validation

- Testing `venv/` regeneration. The `stl2scad.egg-info/` removal will be picked up on the next `pip install -e .`, but this is not part of the reorg verification.
- Changes to CI (no CI paths reference the moved files based on the expected grep scope).

## Explicitly untouched

- All `stl2scad/` package source.
- All `tests/test_*.py` files and their imports.
- `tests/data/benchmark_fixtures/`, `tests/data/feature_fixtures_scad/`, `tests/data/feature_fixtures_manifest.json`.
- `artifacts/` contents and layout.
- `setup.py`, `requirements.txt`, `requirements-dev.txt`, `.github/`, `.vscode/`.
- Root sample STLs (untracked, stay in place).
- User's uncommitted changes on `main`.
