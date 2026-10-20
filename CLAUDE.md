# AI Assistant Guide for stl2scad

This file is the canonical entry point for AI coding assistants (Claude Code, Cursor, Cline). See also [AGENTS.md](AGENTS.md) (Codex) and [.github/copilot-instructions.md](.github/copilot-instructions.md) (GitHub Copilot) — they point back here.

## Project in one paragraph

stl2scad converts STL meshes into editable OpenSCAD. The long-term goal is **primitive detection + parametric SCAD output**. Conversion goes through the segmentation pipeline only: entry point [stl2scad/core/conversion.py](stl2scad/core/conversion.py) (`convert_stl_to_scad`), pipeline in [stl2scad/core/segmentation/](stl2scad/core/segmentation/), OpenSCAD helpers in [stl2scad/core/openscad/runner.py](stl2scad/core/openscad/runner.py). The legacy whole-mesh detectors are archived in `stl2scad/legacy/` (T-003, T-004). The roadmap and current assessment is in [docs/planning/feature_level_reconstruction.md](docs/planning/feature_level_reconstruction.md) — read this before proposing detector or fixture changes.

## Failure analysis (2026-10-20) — historical (T-004)

The legacy detectors, the legacy `stl2scad()` converter, and the tuning and corpus tools now live in `stl2scad/legacy/`. Nothing outside it imports it. Their tests are in `tests/legacy/` and run only with `STL2SCAD_LEGACY_TESTS=1`. Scripts import them from `stl2scad.legacy`. The analysis below explains why they were replaced.

An outside review of the repo (code, git history, test output and artifacts) found why parametric mode stalls on real parts. Evidence: [artifacts/local_corpus_report.html](artifacts/local_corpus_report.html) shows 18 of 20 real parts (Hero Me Gen7 mounts and similar) falling back to polyhedron and 2 giving only plane pairs, although its header claims "30% preview ready"; [docs/planning/detector_autotune_results.md](docs/planning/detector_autotune_results.md) tuned 25 thresholds with Optuna for no gain and concluded "the bottleneck is algorithmic, not parametric."

**Root cause: whole-mesh classification instead of segmentation.** Each detector in [feature_graph.py](stl2scad/core/feature_graph.py) asks "is this entire mesh a plate / box / cylinder / revolve / extrude?" Real parts are compositions of features, so every detector rejects them. Composition only handles physically disconnected components.

Consequences of that design:
- **World-axis assumptions.** Detection relies on normal histograms against X/Y/Z, opposing plane pairs and bounding boxes. Rotated cases were added one by one; fillets and chamfers break the "intact side plane" checks and needed tolerant special cases.
- **Fixed detector priority with hard-coded thresholds** (confidence 0.70, containment 0.50, widened radius thresholds for float32 coordinates). The first match wins, which is how `box_x_through_hole` comes out as a cylinder ([pytest_output.txt](pytest_output.txt)). Box detection can false-positive on hollow shells.
- **No polarity / ownership step.** Nothing decides whether a feature adds or removes material, or which body it belongs to, so `difference()` output is limited to through-holes in plates. Blind holes, pockets, countersinks, bosses, ribs and fillet radii are unsolved.
- **Infrastructure before the core.** Corpus tooling, scoring, HTML reports and the auto-tuner were built before segmentation worked.
- **Synthetic success hides the gap.** The 96 fixtures pass because each is a clean single feature on world axes. `artifacts/real_world_recall_baseline.json` was never populated (0 of 2 files present).

**Keep:** the fixture round-trip loop and its three invariants (below), the negative cases (sphere, torus), the IR idea (Sketch2D, Extrude, Revolve, Boolean, Pattern nodes; [docs/planning/detector_ir.md](docs/planning/detector_ir.md)), the safe polyhedron fallback, confidence scores and diagnostics.

**Recommended new pipeline (replace the whole-mesh detectors, not tune them):**
1. Load and repair: weld vertices, work in float64, tolerances relative to part size.
2. Segment the surface: region growing on normals/curvature plus RANSAC (Efficient RANSAC / Schnabel-style) for planes, cylinders, cones, spheres and tori at any orientation.
3. Build a region adjacency graph and recover B-rep-like faces and edges; classify edges convex/concave; treat fillets as cylinder/torus strips between faces.
4. Detect features from the graph, per region: dominant directions from plane normals; slice into 2D profiles to recover extrudes and revolves; concave cylinders are holes (this gives polarity directly); stepped planar loops are pockets and bosses.
5. Emit through the IR, and validate with a Hausdorff distance to the input mesh, not only by dimension checks.

Before more tuning or reporting work, make one real composite part (a bracket with a boss, a blind hole and a fillet) round-trip through steps 1–4.

## Segmentation pipeline status (2026-10-20)

The recommended pipeline exists in [stl2scad/core/segmentation/](stl2scad/core/segmentation/). It is the default and only conversion path: `stl2scad in.stl out.scad`. `--pipeline legacy` prints a deprecation warning on stderr, writes nothing and exits 2. `--parametric`, `--recognition-backend`, `--compute-backend` and `--tolerance` warn and are ignored. `feature-graph`, `feature-graph-from-inventory` and `feature-inventory` warn and exit 2. verify, batch and the GUI convert through segmentation. An invalid STL (non-manifold edges, no usable faces) raises `STLValidationError` before segmentation, and the CLI exits 1. Requires Python ≥3.10, `networkx` and `trimesh`. Spec, output decisions and known limits: [docs/planning/segmentation_composite_bracket.md](docs/planning/segmentation_composite_bracket.md).

- Output is labeled, adjustable SCAD: Customizer groups and ranges, `<kind>_<index>_<dim>` parameters relative to host faces, `assert()` links, face provenance comments, one part-frame `multmatrix()`.
- The gate is all or nothing. If the Hausdorff distance is more than max(0.05 mm, 0.1 % of the bbox diagonal), the output is a polyhedron.
- Snapping moves a value by 0.001 mm or less. It removes float noise and keeps design values.
- Ground truth: `tests/data/segmentation/` (composite bracket and rounded plate, each axis-aligned, rotated and coarse). Tests: `tests/test_segmentation_*.py`.
- Real parts: `memo_stencil6` converts within 0.00001 mm. The legacy preview of the same part is 6.2 mm away. `memo_cartridge` and `memo_power_button` fall back, because convex 3D edge rounds are not supported yet. See [docs/planning/segmentation_real_parts.md](docs/planning/segmentation_real_parts.md).
- `.gitignore` ignores `*.json` and most `.scad`. A new data file needs a `!` rule. Check with `git status -uall`.

## Feature Fixtures — the detector-validation harness (READ FIRST)

[tests/data/feature_fixtures_manifest.json](tests/data/feature_fixtures_manifest.json) + [tests/data/feature_fixtures_scad/](tests/data/feature_fixtures_scad/) + [stl2scad/core/feature_fixtures.py](stl2scad/core/feature_fixtures.py) + [tests/test_feature_fixtures.py](tests/test_feature_fixtures.py) form a closed-loop ground-truth system: **manifest → generated SCAD → rendered STL → detector → asserted against the manifest**. This is the primary safety net for detector work.

Invariants 1 and 3 are in `tests/test_feature_fixtures.py`. Invariant 2 runs through the segmentation pipeline in `tests/test_segmentation_fixtures.py` (T-009); its expectations are in `tests/data/segmentation/fixture_expectations.json`. The old legacy detection round-trip is in `tests/legacy/test_feature_fixtures_round_trip.py` (skipped by default).

### Three invariants you must not break

1. **Byte-exact regeneration** ([test_feature_fixture_manifest_matches_checked_in_scad](tests/test_feature_fixtures.py)) — regenerating fixtures from the manifest must equal the checked-in `.scad` files byte-for-byte. If you change the generator, regenerate the library and commit the updated `.scad` files in the same change; do not edit `.scad` files by hand.
2. **Segmentation round-trip** ([tests/test_segmentation_fixtures.py](tests/test_segmentation_fixtures.py), T-009) — every fixture either converts parametric with Hausdorff within the gate and matching hole, slot and counterbore counts, or falls back with its exact expected reason and is listed by name as a `known_gap` in [fixture_expectations.json](tests/data/segmentation/fixture_expectations.json). A known gap that starts converting parametric fails the test (move it to `parametric`). Never weaken a count or reason assertion. A fixture that regresses from parametric to fallback is a defect: fix it, or move it to the known-gap list only with a ticket that names it. Fixtures over about 30 s carry the `slow` marker; `tests/conftest.py` deselects them when no `-m` is given (the harness passes `-o addopts=""`), and `-m slow` runs them (about 13 min). A meta test checks the parametric counts against the manifest.
3. **Roadmap coverage** ([test_feature_fixture_manifest_covers_roadmap_stress_cases](tests/test_feature_fixtures.py)) — the manifest must always contain at least one fixture per stress category (mixed, high-aspect, small/large diameter, near-boundary ≤0.5 mm, plus box and l_bracket types). Never shrink the manifest below this bar.

### How to use the fixture library

- **As a detector-development aid**: open any `.scad` file in OpenSCAD GUI for visual ground truth, or render individually with `openscad --render -o x.stl tests/data/feature_fixtures_scad/file.scad` to step-debug a single case without pytest.
- **As a regression fence**: the checked-in `.scad` files are golden output. Diff them in PRs to see exactly what a manifest or generator change produced.
- **As a template**: copy the closest existing fixture when authoring a new case; reverse-engineer the manifest entry from the SCAD structure.
- **As cross-backend verification**: feed the same fixture STLs through each mesh backend (native / trimesh_manifold / cgal) and compare feature-graph output.
- **As a benchmarking corpus**: fixed, reproducible shapes for timing the detector.

### Adding a new fixture — the workflow

1. Add an entry to [feature_fixtures_manifest.json](tests/data/feature_fixtures_manifest.json) with `name`, `fixture_type` (`plate` / `box` / `l_bracket`), geometry, and `expected_detection` counts.
2. Run the tests — the manifest-matches-checked-in test will fail with the expected new `.scad` file. Copy it from `tests/.tmp_output/` into `tests/data/feature_fixtures_scad/` and commit it.
3. Do **not** weaken the stress-case assertions or the round-trip dimensional check to get a new fixture to pass — if the detector disagrees, that's the signal to fix the detector (or file it as a known limitation).

## Conventions and constraints worth knowing

- `get_openscad_path()` (in `stl2scad/core/openscad/runner.py`) enforces `"OpenSCAD (Nightly)"` in the Windows path string. Don't remove this substring check; it guards against the installed stable OpenSCAD lacking features the codebase relies on.
- Never embed raw Windows `Path` objects in OpenSCAD source. Use `.as_posix()` so OpenSCAD's parser doesn't choke on backslashes.
- Never call `logging.basicConfig(force=True)` inside library functions — it overrides pytest's log capture. Only the CLI entry point may configure logging.
- `--preview=throwntogether` fails headlessly on Windows; use `--render` in tests and headless code paths.
- Don't wrap subprocess calls in PowerShell `-EncodedCommand`; `subprocess.run` with a list handles paths with spaces natively.
- When editing the feature-fixture generator, re-run `python -m pytest tests/test_feature_fixtures.py` and commit any regenerated `.scad` files alongside the generator change.

## Key commands

```bash
# Feature-fixture test slice (fastest detector feedback loop)
python -m pytest tests/test_feature_fixtures.py -v

# Convert one file (segmentation pipeline)
stl2scad input.stl output.scad

# The scripts below run the ARCHIVED legacy detectors (stl2scad.legacy); for history only
# Build a feature graph for one file (with SCAD preview)
python scripts/build_feature_graph.py input.stl --output artifacts/graph.json --scad-preview artifacts/preview.scad

# Inventory a directory of STLs
python scripts/analyze_feature_inventory.py "path/to/stls" --output artifacts/inventory.json --workers 0

# Run inventory-prefiltered graph extraction in one step
python scripts/build_feature_graph.py "path/to/stls" --output artifacts/feature_graph.json --inventory-prefilter --inventory-output artifacts/inventory.json --workers 0
```

## Where to look next

- Roadmap and priorities: [docs/planning/feature_level_reconstruction.md](docs/planning/feature_level_reconstruction.md)
- Memory bank (Cline-style): [docs/memory-bank/](docs/memory-bank/)
- Conversion entry point: [stl2scad/core/conversion.py](stl2scad/core/conversion.py); archived legacy converter: `stl2scad/legacy/converter.py`

## Lanes and Subagents (set up 2026-10-20)

Work in this repo goes through lanes. The main session is the
**orchestrator**: it plans, writes briefs, routes, verifies, merges and
reports. It edits only orchestration material itself: `CLAUDE.md`,
`.claude/agents/*.md`, `.claude/skills/**`, `docs/agents/**`, memory and the
handoff (`docs/HANDOFF.md`). The method: `~/.claude/multi-lane-orchestration.md`.

### Agents

The general agents live in `~/.claude/agents/`; a file of the same name in
this repo's `.claude/agents/` wins.

| Agent | Model | Does | Never does |
|---|---|---|---|
| `lane-dev` | Sonnet (Opus on the call for a ticket with design inside) | Builds one ticket in its own worktree; runs the static gates; sets its ticket to `landed` | Runs the test harness; pushes; merges |
| `ticket-writer` | Sonnet, low | Writes `docs/tickets/T-NNN-*.md`, its test stub, ADR text when asked | Invents a ruling; edits code |
| `lane-verifier` | Sonnet, low | Checks one lane branch against main and its ticket; PASS or FAIL | Edits, merges or commits |
| `suite-verifier` | Sonnet, low | The only agent that runs the test harness; faithful counts and causes | Fixes a failure; re-runs to make it pass |

Every Agent call names `model`. A new or changed agent file loads only after
the session reloads its agents; until then, launch `general-purpose` with the
file's text in the brief.

### Rules

- **unlazy in every lane.** Each lane loads `unlazy`, writes
  `.unlazy/<lane>/GATES.md` (one gate per acceptance criterion and ruling)
  before it works, and reports only at ALL MET or explicit ABANDONs. The
  Stop/SubagentStop hook in `.claude/settings.local.json` holds a lane with
  unmet gates; lane-verifier re-runs the ledger.
- **One worktree per code lane, disjoint paths.** `isolation: "worktree"` on
  the Agent call, or `scripts/lane-worktree.sh add <name>` for a codex/agy lane.
  Never install dependencies inside a worktree. The main tree belongs to the
  orchestrator. Every brief lists the paths the lane owns; concurrent lanes
  own disjoint paths; a shared file changes in wave order.
- **Design questions go to the maintainer** (AskUserQuestion, 1-2 per round,
  recommended option first), never to a lane. With the maintainer away,
  decisions go in `docs/agents/decisions-YYYY-MM-DD.md` with a revert note.
- **Tickets:** `docs/agents/ticket-format.md`; the linter is `ticket_lint`
  below. Queue: `docs/agents/work-ledger.md`. Models:
  `docs/agents/model-register.md`. External lanes: docs/agents/external-lanes.md.

### The rhythm of a wave

1. Tickets with recorded rulings; the ticket linter passes.
2. One `lane-dev` per ticket, in parallel, in the background.
3. As each returns: `lane-verifier` on its branch (and an adversarial review
   by a different strong model on a risky merge), `git merge --no-ff`, the
   `gates` at HEAD, then `suite-verifier` with a FULL run. Main is frozen
   during the run. A failure goes to a fix lane.
4. Commit when a lane lands. Never push without the maintainer, and only with
   a green full run at the HEAD you push. `/ship` pushes and deploys.
5. `/session-start` begins a session; `/session-close` ends one.

## Orchestration settings

The global skills and agents (`session-start`, `session-close`, `ship`,
`lane-dev`, `lane-verifier`, `suite-verifier`, `ticket-writer`) read this
block. Keep the keys; write `none` for what does not apply. `{tests}` in a
command is replaced by a space-separated test list; `{worktree}` by a lane
worktree path.

```yaml
gates:                       # static gates, run by every lane, by lane-verifier and on main after a merge
  - .venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist
  - node scripts/check-tickets.mjs
ticket_lint: node scripts/check-tickets.mjs
test_paths: tests/test_*.py           # globs of test files (lane-verifier's test-only-fix check)
test_full: 'flock /tmp/stl2scad-pytest.lock env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -n auto -q -o addopts="" -p no:logging'             # the full suite; only suite-verifier or the orchestrator runs it
test_scoped: 'flock /tmp/stl2scad-pytest.lock env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -n auto -q -o addopts="" -p no:logging {tests}'         # e.g. "npm test -- {tests}"; none if the runner has no scoped mode
test_scoped_list: none  # command that prints the tests a lane touched; none
test_lock: /tmp/stl2scad-pytest.lock             # lock file the harness holds; none
test_log: none               # file where runs are stamped; none
test_logs: the pytest output (stdout/stderr of the run)             # where suite-verifier reads causes (log path or "docker logs <name>"); none
deploy: none                   # command; none = /ship stops after the push
deploy_precheck: none # e.g. "players online" query; ask the maintainer if it reports users; none
deploy_verify: none     # prints the deployed commit; must equal HEAD; none
rig_check: openscad --version             # extra session-start commands (servers, containers); none
handoff: docs/HANDOFF.md
worktree_links: .venv   # dirs symlinked from main into every lane worktree
tmux_session: none       # only for tmux window lanes; none when lanes run through the lanes tool
external_lanes: codex, agy   # codex, agy | codex | agy | none
codex_start: none         # tmux window lanes only; else none
agy_start: none             # tmux window lanes only; else none
max_lanes: claude=5 codex=1 agy=1 test=1
```
