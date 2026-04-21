# Repo Structure Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up root-level clutter, consolidate docs under `docs/`, separate stale generated test outputs, and normalize script naming — without breaking the three detector-validation invariants.

**Architecture:** Sequential commits, one per logical chunk. Each commit is independently revertable via `git revert`. Per-commit smoke tests with a fast detector test (`tests/test_feature_fixtures.py`) plus a full suite at the end. `git mv` preserves history for tracked moves; `git rm --cached` untracks files without deleting them.

**Tech Stack:** git, bash, Python 3, pytest, OpenSCAD (Nightly — required for byte-exact fixture test).

**Spec reference:** [docs/superpowers/specs/2026-04-21-repo-structure-cleanup-design.md](../specs/2026-04-21-repo-structure-cleanup-design.md)

---

## Task 0: Pre-flight — capture baseline

**Files:**
- Create: `/tmp/pre_reorg_pytest.log` (ephemeral)

- [ ] **Step 1: Confirm clean working tree**

Run:
```bash
git status
```

Expected output: `On branch main` + `nothing to commit, working tree clean` (or only the spec/plan files under `docs/superpowers/` as staged/committed). If there are unrelated in-flight changes, stop and ask the user before proceeding.

- [ ] **Step 2: Capture baseline pytest output**

Run:
```bash
python -m pytest tests/ -v 2>&1 | tee /tmp/pre_reorg_pytest.log
```

Expected: a pass/skip/fail line like `===== X passed, Y skipped, Z deselected in Ns =====`. Record the exact numbers — every subsequent task must match.

- [ ] **Step 3: Confirm import smoke**

Run:
```bash
python -c "import stl2scad; import stl2scad.core.feature_graph; import stl2scad.core.feature_fixtures; print('ok')"
```

Expected output: `ok`

- [ ] **Step 4: No commit** — this task is read-only baseline capture.

---

## Task 1: Update `.gitignore` with new entries

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add new gitignore entries**

Edit `.gitignore` to add the following entries under existing relevant sections. After the section ending at line 56 (`tests/data/Cube_3d_printing_sample_debug.echo`), add a new section:

```
# Runtime/build artifacts that accidentally got tracked
.coverage
chats.db
.codex
stl2scad.egg-info/

# Generated test outputs (kept locally, never committed)
tests/data/.generated/
```

Do NOT modify the existing `memory-bank/` line yet — that changes in Task 4.

- [ ] **Step 2: Confirm gitignore is still valid**

Run:
```bash
git check-ignore -v .coverage chats.db .codex stl2scad.egg-info/PKG-INFO
```

Expected: each path prints a `.gitignore:<line>` match. Note: already-tracked files still appear in `git ls-files`; gitignore only suppresses untracked files. That's intentional — Task 2 does the untracking.

- [ ] **Step 3: Run smoke test**

Run:
```bash
python -m pytest tests/test_feature_fixtures.py -x
```

Expected: pass/skip count matches the baseline subset.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "$(cat <<'EOF'
chore: extend .gitignore for runtime artifacts and generated test outputs

Adds entries for .coverage, chats.db, .codex, stl2scad.egg-info/, and
tests/data/.generated/. Does not untrack already-committed files —
that follows in subsequent commits.
EOF
)"
```

Expected: single commit created, working tree clean.

---

## Task 2: Untrack root-level runtime artifacts

**Files:**
- Untrack: `.coverage`, `chats.db`, `.codex`, `stl2scad.egg-info/PKG-INFO`, `stl2scad.egg-info/SOURCES.txt`, `stl2scad.egg-info/dependency_links.txt`, `stl2scad.egg-info/entry_points.txt`, `stl2scad.egg-info/requires.txt`, `stl2scad.egg-info/top_level.txt`

- [ ] **Step 1: Verify files exist on disk before untracking**

Run:
```bash
ls -la .coverage chats.db .codex stl2scad.egg-info/
```

Expected: all files/directory exist. If any is missing, stop — we shouldn't untrack something that isn't there.

- [ ] **Step 2: Untrack each file (keep on disk)**

Run:
```bash
git rm --cached .coverage chats.db .codex
git rm --cached -r stl2scad.egg-info/
```

Expected: `rm '.coverage'`, `rm 'chats.db'`, etc. — these print `rm` but leave files on disk because of `--cached`.

- [ ] **Step 3: Verify files still exist on disk**

Run:
```bash
ls -la .coverage chats.db .codex stl2scad.egg-info/PKG-INFO
```

Expected: all still present (untrack only, no deletion).

- [ ] **Step 4: Verify now-untracked status**

Run:
```bash
git status --short | grep -E "^\?\? (\.coverage|chats\.db|\.codex|stl2scad\.egg-info)"
```

Expected: no output — those paths should NOT appear as untracked because they're in `.gitignore` from Task 1. If any show up, re-check that Task 1 landed.

- [ ] **Step 5: Run smoke test**

Run:
```bash
python -m pytest tests/test_feature_fixtures.py -x
```

Expected: pass/skip count matches baseline.

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "$(cat <<'EOF'
chore: untrack runtime artifacts that should never have been committed

Runs `git rm --cached` on .coverage, chats.db, .codex, and
stl2scad.egg-info/. Files stay on disk locally; .gitignore (updated
in the previous commit) keeps them out of future commits.
EOF
)"
```

Expected: single commit, working tree clean.

---

## Task 3: Move stale Cube debug outputs to `tests/data/.generated/`

**Files:**
- Create: `tests/data/.generated/` (directory)
- Untrack + move: `tests/data/Cube_3d_printing_sample_verification.html`
- Untrack + move: `tests/data/Cube_3d_printing_sample_visualizations/` (14 PNGs)
- Move (already untracked): `Cube_3d_printing_sample.scad`, `Cube_3d_printing_sample_debug.scad`, `Cube_3d_printing_sample_debug.echo`, `Cube_3d_printing_sample_debug_analysis.log`, `Cube_3d_printing_sample_debug_echo.log`, `Cube_3d_printing_sample_debug_preview.log`

- [ ] **Step 1: Create the `.generated/` directory**

Run:
```bash
mkdir -p tests/data/.generated
```

Expected: no output. Confirm with `ls -la tests/data/.generated`.

- [ ] **Step 2: Untrack the tracked Cube debug outputs**

Run:
```bash
git rm --cached tests/data/Cube_3d_printing_sample_verification.html
git rm --cached -r tests/data/Cube_3d_printing_sample_visualizations/
```

Expected: `rm 'tests/data/Cube_3d_printing_sample_verification.html'` plus 14 `rm` lines for PNGs.

- [ ] **Step 3: Move all stale Cube outputs into `.generated/`**

Run:
```bash
mv tests/data/Cube_3d_printing_sample_verification.html tests/data/.generated/
mv tests/data/Cube_3d_printing_sample_verification.json tests/data/.generated/ 2>/dev/null || true
mv tests/data/Cube_3d_printing_sample_visualizations tests/data/.generated/
mv tests/data/Cube_3d_printing_sample.scad tests/data/.generated/ 2>/dev/null || true
mv tests/data/Cube_3d_printing_sample_debug.scad tests/data/.generated/ 2>/dev/null || true
mv tests/data/Cube_3d_printing_sample_debug.echo tests/data/.generated/ 2>/dev/null || true
mv tests/data/Cube_3d_printing_sample_debug_analysis.log tests/data/.generated/ 2>/dev/null || true
mv tests/data/Cube_3d_printing_sample_debug_echo.log tests/data/.generated/ 2>/dev/null || true
mv tests/data/Cube_3d_printing_sample_debug_preview.log tests/data/.generated/ 2>/dev/null || true
```

The `2>/dev/null || true` on untracked-file moves avoids failing if a file happened to already be absent locally.

- [ ] **Step 4: Verify moves landed**

Run:
```bash
ls tests/data/.generated/
ls tests/data/Cube_3d_printing_sample* 2>&1 | head -5
```

Expected: `.generated/` lists moved files. The `ls tests/data/Cube_*` command should return only the `.stl` samples (e.g., `Cube_3d_printing_sample.stl`), not any debug outputs.

- [ ] **Step 5: Verify gitignore catches `.generated/`**

Run:
```bash
git status --short tests/data/
```

Expected: no untracked entries under `tests/data/.generated/` (gitignored from Task 1). Only the `git rm --cached` deletions should show.

- [ ] **Step 6: Run smoke test**

Run:
```bash
python -m pytest tests/test_feature_fixtures.py -x
```

Expected: pass/skip matches baseline.

- [ ] **Step 7: Run a test that may touch Cube outputs**

Run:
```bash
python -m pytest tests/test_debug.py tests/test_verification.py tests/test_visualization.py -v
```

Expected: same pass/skip/fail counts as in the baseline. If any new failure references the moved Cube files, revert and diagnose — they may be regenerated fresh on test runs and the moves didn't affect anything.

- [ ] **Step 8: Commit**

```bash
git add -u
git commit -m "$(cat <<'EOF'
chore: move stale Cube_* test outputs into tests/data/.generated/

Untracks Cube_3d_printing_sample_verification.html and the 14 PNG
files under Cube_3d_printing_sample_visualizations/ (accidentally
committed generated output), then moves all stale Cube debug
artifacts into tests/data/.generated/ so real fixtures under
tests/data/ aren't cluttered. The .generated/ directory is
gitignored; local regeneration still works.
EOF
)"
```

Expected: single commit, working tree clean.

---

## Task 4: Move `memory-bank/` → `docs/memory-bank/`

**Files:**
- Move: `memory-bank/` (6 files, directory is untracked/gitignored)
- Modify: `.gitignore` (line 55: `memory-bank/` → `docs/memory-bank/`)
- Modify: `CLAUDE.md` (line 61: update markdown link)

- [ ] **Step 1: Verify source and destination**

Run:
```bash
ls memory-bank/
ls docs/
```

Expected: `memory-bank/` contains 6 markdown files; `docs/` does NOT yet contain `memory-bank`.

- [ ] **Step 2: Move the directory**

Run:
```bash
mv memory-bank docs/memory-bank
```

Expected: no output. Confirm with `ls docs/memory-bank/` showing 6 .md files, and `ls memory-bank 2>&1` returning "No such file or directory".

- [ ] **Step 3: Update `.gitignore` line 55**

Edit `.gitignore` and change the line:

From:
```
memory-bank/
```

To:
```
docs/memory-bank/
```

- [ ] **Step 4: Update `CLAUDE.md` line 61**

Edit `CLAUDE.md` and change the bullet line:

From:
```
- Memory bank (Cline-style): [memory-bank/](memory-bank/)
```

To:
```
- Memory bank (Cline-style): [docs/memory-bank/](docs/memory-bank/)
```

- [ ] **Step 5: Verify no other references to `memory-bank/`**

Run:
```bash
```

Use the Grep tool with pattern `memory-bank` (case-sensitive, no path). Ignore hits inside `docs/superpowers/specs/` and `docs/superpowers/plans/` (those are design/plan docs and describe the move). Ignore hits inside `venv/`, `.git/`, `docs/memory-bank/` (that's the moved dir itself).

Expected remaining hits: `.gitignore` (new path, from Step 3), `CLAUDE.md` (new path, from Step 4). If any unexpected references remain, update them with the same pattern.

- [ ] **Step 6: Verify gitignore works for the new location**

Run:
```bash
git status --short docs/memory-bank/
```

Expected: no output (directory is now gitignored under its new path).

- [ ] **Step 7: Run smoke test**

Run:
```bash
python -m pytest tests/test_feature_fixtures.py -x
```

Expected: pass/skip matches baseline.

- [ ] **Step 8: Commit**

```bash
git add .gitignore CLAUDE.md
git commit -m "$(cat <<'EOF'
chore: move memory-bank/ to docs/memory-bank/

Consolidates Cline-style memory bank notes under docs/. Updates
.gitignore to point at the new location and fixes the pointer in
CLAUDE.md. Directory is still gitignored, so no tracked content
moves — only the physical path.
EOF
)"
```

Expected: single commit, working tree clean.

---

## Task 5: Move `tests/debug_test_plan.md` → `docs/planning/debug_test_plan.md`

**Files:**
- Move: `tests/debug_test_plan.md` → `docs/planning/debug_test_plan.md`
- Modify: `tests/README.md` lines 103, 110

- [ ] **Step 1: Move the file with git**

Run:
```bash
git mv tests/debug_test_plan.md docs/planning/debug_test_plan.md
```

Expected: no output. Confirm with `ls docs/planning/debug_test_plan.md` and `ls tests/debug_test_plan.md 2>&1` (should error).

- [ ] **Step 2: Update `tests/README.md` line 103**

Edit `tests/README.md` and change:

From:
```
See [debug_test_plan.md](debug_test_plan.md) for detailed test plan and progress tracking.
```

To:
```
See [debug_test_plan.md](../docs/planning/debug_test_plan.md) for detailed test plan and progress tracking.
```

- [ ] **Step 3: Update `tests/README.md` line 110**

Edit `tests/README.md` and change:

From:
```
4. Update `debug_test_plan.md` with new test cases
```

To:
```
4. Update [debug_test_plan.md](../docs/planning/debug_test_plan.md) with new test cases
```

- [ ] **Step 4: Verify no other references**

Use the Grep tool with pattern `debug_test_plan` across the whole repo. Ignore hits inside `docs/superpowers/specs/`, `docs/superpowers/plans/`, `venv/`, `.git/`.

Expected remaining hits: only in `tests/README.md` (updated) and `docs/planning/debug_test_plan.md` (moved file). If any unexpected references remain, update them.

- [ ] **Step 5: Run smoke test**

Run:
```bash
python -m pytest tests/test_feature_fixtures.py -x
```

Expected: pass/skip matches baseline.

- [ ] **Step 6: Commit**

```bash
git add tests/README.md
git commit -m "$(cat <<'EOF'
chore: move debug_test_plan.md into docs/planning/

Moves the debug test plan document alongside other planning docs and
updates the two tests/README.md references to point at the new
location. No test logic touched.
EOF
)"
```

Expected: single commit, working tree clean.

---

## Task 6: Rename `scripts/stl2scad-cgal-helper.py` → `scripts/stl2scad_cgal_helper.py`

**Files:**
- Rename: `scripts/stl2scad-cgal-helper.py` → `scripts/stl2scad_cgal_helper.py`
- Modify: `stl2scad/core/cgal_backend.py:31`
- Modify: `tests/test_cgal_backend.py` (5 lines: 181, 592, 621, 657, 698)
- Modify: `README.md:82`
- Modify: `docs/planning/phase2_release_checklist.md:10`
- Modify: `docs/planning/cgal_integration_boundary.md:18, 96`

Note on scope: per the design spec, this rename requires single-line updates inside `stl2scad/core/cgal_backend.py` and `tests/test_cgal_backend.py`. These are mechanical path-string updates, not logic changes — consistent with the "rename + update callers" intent of the spec.

The `.exe` and no-extension variants (`stl2scad-cgal-helper`, `stl2scad-cgal-helper.exe`) are compiled-binary names that live outside this repo and stay as-is.

- [ ] **Step 1: Rename the file with git**

Run:
```bash
git mv scripts/stl2scad-cgal-helper.py scripts/stl2scad_cgal_helper.py
```

Expected: no output. Confirm with `ls scripts/stl2scad_cgal_helper.py` and `ls scripts/stl2scad-cgal-helper.py 2>&1` (should error).

- [ ] **Step 2: Update `stl2scad/core/cgal_backend.py` line 31**

Edit the file. In the `SEARCH_NAMES` list around lines 29–31, change ONLY the `.py` entry:

From:
```python
    "stl2scad-cgal-helper",
    "stl2scad-cgal-helper.exe",
    "stl2scad-cgal-helper.py",
```

To:
```python
    "stl2scad-cgal-helper",
    "stl2scad-cgal-helper.exe",
    "stl2scad_cgal_helper.py",
```

(Binary names on lines 29–30 keep their dashes; only the Python script name changes.)

- [ ] **Step 3: Update `tests/test_cgal_backend.py` — 5 occurrences**

Edit the file. Use a file-scoped replace of the string `"stl2scad-cgal-helper.py"` with `"stl2scad_cgal_helper.py"`. All 5 hits (lines 181, 592, 621, 657, 698) are inside `Path(__file__).resolve().parents[1] / "scripts" / "stl2scad-cgal-helper.py"` constructions — the replace is safe because the old hyphenated `.py` form appears nowhere else (binary names without `.py` extension are distinct strings and untouched).

Verify with Grep pattern `stl2scad-cgal-helper\.py` in `tests/test_cgal_backend.py` — expected: no matches.

- [ ] **Step 4: Update `README.md` line 82**

Edit `README.md` and change ONLY line 82 (the comment referencing the Python script path):

From:
```
# set STL2SCAD_CGAL_HELPER=C:\path\to\stl2scad\scripts\stl2scad-cgal-helper.py
```

To:
```
# set STL2SCAD_CGAL_HELPER=C:\path\to\stl2scad\scripts\stl2scad_cgal_helper.py
```

Line 80 (the `.exe` variant) stays unchanged — it's the compiled binary name.

- [ ] **Step 5: Update `docs/planning/phase2_release_checklist.md` line 10**

Edit and change:

From:
```
- [x] Helper prototype available for end-to-end protocol validation (`scripts/stl2scad-cgal-helper.py`)
```

To:
```
- [x] Helper prototype available for end-to-end protocol validation (`scripts/stl2scad_cgal_helper.py`)
```

- [ ] **Step 6: Update `docs/planning/cgal_integration_boundary.md`**

Two hits. Update only the `.py` ones — leave the no-extension and `.exe` binary-name mentions alone.

Edit line 18:

From:
```
   - `stl2scad-cgal-helper.py`
```

To:
```
   - `stl2scad_cgal_helper.py`
```

Edit line 96:

From:
```
1. Minimal helper prototype implemented (`scripts/stl2scad-cgal-helper.py`).
```

To:
```
1. Minimal helper prototype implemented (`scripts/stl2scad_cgal_helper.py`).
```

Lines 16 and 17 (no-extension and `.exe` binary names) stay as-is.

- [ ] **Step 7: Verify no lingering `.py` references to the old name**

Use the Grep tool with pattern `stl2scad-cgal-helper\.py`. Ignore hits inside `docs/superpowers/specs/`, `docs/superpowers/plans/`, `.git/`, `venv/`.

Expected: no matches outside the ignored directories. (The no-extension and `.exe` variants remain — those are correct.)

- [ ] **Step 8: Run targeted cgal backend tests**

Run:
```bash
python -m pytest tests/test_cgal_backend.py -v
```

Expected: same pass/skip/fail as in the baseline. If a test now fails because the helper isn't found, the path update in cgal_backend.py or test_cgal_backend.py is wrong — diagnose and fix before committing.

- [ ] **Step 9: Run full smoke test**

Run:
```bash
python -m pytest tests/test_feature_fixtures.py -x
```

Expected: pass/skip matches baseline.

- [ ] **Step 10: Commit**

```bash
git add scripts/stl2scad_cgal_helper.py stl2scad/core/cgal_backend.py tests/test_cgal_backend.py README.md docs/planning/phase2_release_checklist.md docs/planning/cgal_integration_boundary.md
git commit -m "$(cat <<'EOF'
chore: rename scripts/stl2scad-cgal-helper.py to snake_case

Python script now uses the snake_case naming convention shared by
the other scripts in scripts/. The compiled-helper binary names
(stl2scad-cgal-helper, stl2scad-cgal-helper.exe) keep their hyphens
because they're external binary names.

Updates cgal_backend.py SEARCH_NAMES, 5 references in
test_cgal_backend.py, the README env-var comment, and two planning
docs. No logic changes.
EOF
)"
```

Expected: single commit, working tree clean.

---

## Task 7: Add `docs/README.md` index

**Files:**
- Create: `docs/README.md`

- [ ] **Step 1: Write the `docs/README.md` index file**

Create `docs/README.md` with this exact content:

```markdown
# docs/

This directory holds all project documentation.

## Layout

- **[planning/](planning/)** — Active design docs, roadmaps, and checklists.
  Includes [feature_level_reconstruction.md](planning/feature_level_reconstruction.md)
  (the detector roadmap), [cgal_integration_boundary.md](planning/cgal_integration_boundary.md),
  [parametric_conversion_roadmap.md](planning/parametric_conversion_roadmap.md),
  [phase2_release_checklist.md](planning/phase2_release_checklist.md), and
  [debug_test_plan.md](planning/debug_test_plan.md).
- **[reviews/](reviews/)** — Past review artifacts (one `.docx` snapshot).
- **[memory-bank/](memory-bank/)** — Cline-style session memory notes
  (gitignored; local-only). Structure: `activeContext.md`, `progress.md`,
  `decisionLog.md`, `productContext.md`, `systemPatterns.md`,
  `accuracy_verification_plan.md`.
- **[superpowers/specs/](superpowers/specs/)** — Approved brainstorming
  design specs (one file per feature).
- **[superpowers/plans/](superpowers/plans/)** — Implementation plans
  derived from specs.

## Canonical entry points

- AI assistants: [../CLAUDE.md](../CLAUDE.md)
- Codex / generic agents: [../AGENTS.md](../AGENTS.md)
- Human contributors: [../README.md](../README.md)
```

- [ ] **Step 2: Verify the file renders as valid markdown**

Run:
```bash
cat docs/README.md | head -5
```

Expected: the file's first 5 lines including the `# docs/` heading.

- [ ] **Step 3: No test change expected — skip smoke test here**

This task only adds a new documentation file; no code paths touch it.

- [ ] **Step 4: Commit**

```bash
git add docs/README.md
git commit -m "$(cat <<'EOF'
docs: add docs/ index describing layout

New docs/README.md explains what each subdirectory under docs/ holds
(planning, reviews, memory-bank, superpowers/specs, superpowers/plans)
and points back at the canonical entry points (CLAUDE.md, AGENTS.md,
README.md).
EOF
)"
```

Expected: single commit, working tree clean.

---

## Task 8: Post-reorg full validation

**Files:**
- Create: `/tmp/post_reorg_pytest.log` (ephemeral)

- [ ] **Step 1: Full pytest run against reorganized tree**

Run:
```bash
python -m pytest tests/ -v 2>&1 | tee /tmp/post_reorg_pytest.log
```

Expected: pass/skip/fail counts exactly match `/tmp/pre_reorg_pytest.log` from Task 0. If any number differs — especially a new failure — STOP. Do not proceed. Identify the commit that caused the regression (run `git log --oneline` and bisect manually by checking out each commit and re-running tests) and revert it with `git revert <sha>`.

- [ ] **Step 2: Diff the two logs for clarity**

Run:
```bash
diff <(grep -E "^(PASSED|FAILED|SKIPPED|ERROR) " /tmp/pre_reorg_pytest.log | sort) \
     <(grep -E "^(PASSED|FAILED|SKIPPED|ERROR) " /tmp/post_reorg_pytest.log | sort)
```

Expected: no output (identical test outcomes). If output appears, inspect it — every changed line is a regression or newly-added test (the latter shouldn't happen since we didn't touch test logic).

- [ ] **Step 3: End-to-end detector smoke**

Run:
```bash
python scripts/build_feature_graph.py tests/data/Cube_3d_printing_sample.stl --output /tmp/postreorg_graph.json
```

Expected: exits 0 and writes `/tmp/postreorg_graph.json`. Confirm with `ls -la /tmp/postreorg_graph.json` (non-empty file).

- [ ] **Step 4: Renamed script smoke**

Run:
```bash
python scripts/stl2scad_cgal_helper.py --help 2>&1 | head -20
```

Expected: prints a help message OR exits cleanly. If it errors on import, the rename was incomplete — go back to Task 6 and re-check.

- [ ] **Step 5: Confirm repo-layout targets achieved**

Run:
```bash
ls docs/
ls docs/memory-bank/ 2>&1 | head -3
ls docs/planning/ | grep debug_test_plan
ls scripts/stl2scad_cgal_helper.py
ls tests/data/.generated/ 2>&1 | head -5
git ls-files .coverage chats.db .codex stl2scad.egg-info 2>&1 | head -3
```

Expected:
- `docs/` shows `README.md planning memory-bank reviews superpowers`
- `docs/memory-bank/` lists its files
- `docs/planning/` includes `debug_test_plan.md`
- `scripts/stl2scad_cgal_helper.py` exists
- `tests/data/.generated/` has the moved Cube outputs
- The `git ls-files` line prints `error: pathspec` messages — those files are no longer tracked.

- [ ] **Step 6: Confirm commit history is clean**

Run:
```bash
git log --oneline -10
```

Expected: 7 new commits from this reorg (Tasks 1–7), plus whatever was there before. Each commit should be revertable independently.

- [ ] **Step 7: No commit for this task** — this is the verification gate. If everything passes, the reorg is done.

---

## Rollback notes

If any commit causes a test regression after landing:

1. Identify the bad commit: `git log --oneline` and find the most recent reorg commit.
2. Revert it: `git revert <sha>`.
3. Run `python -m pytest tests/test_feature_fixtures.py -x` to confirm recovery.
4. Do NOT use `git reset --hard` or force-push.

## Success criteria

- All 8 tasks complete with green smoke tests.
- Final `pytest tests/ -v` output matches the pre-reorg baseline exactly (pass/skip/fail counts).
- No file has been deleted; only moved or untracked.
- Working tree clean after Task 8.
