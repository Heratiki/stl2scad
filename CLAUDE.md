# AI Assistant Guide for stl2scad

This file is the canonical entry point for AI coding assistants (Claude Code, Cursor, Cline). See also [AGENTS.md](AGENTS.md) (Codex) and [.github/copilot-instructions.md](.github/copilot-instructions.md) (GitHub Copilot) — they point back here.

## Project in one paragraph

stl2scad converts STL meshes into editable OpenSCAD. Today's output is primarily polyhedron; the long-term goal is **primitive detection + parametric SCAD output** with confidence-scored multi-interpretation ranking. Core conversion lives in [stl2scad/core/converter.py](stl2scad/core/converter.py); the detector pipeline lives in [stl2scad/core/feature_graph.py](stl2scad/core/feature_graph.py) and [stl2scad/core/feature_inventory.py](stl2scad/core/feature_inventory.py). The roadmap and current assessment is in [docs/planning/feature_level_reconstruction.md](docs/planning/feature_level_reconstruction.md) — read this before proposing detector or fixture changes.

## Failure analysis (2026-10-20) — read before new detector work

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

The recommended pipeline exists in [stl2scad/core/segmentation/](stl2scad/core/segmentation/). Use it with `stl2scad in.stl out.scad --pipeline segmentation`. The default is still `legacy`. Spec, output decisions and known limits: [docs/planning/segmentation_composite_bracket.md](docs/planning/segmentation_composite_bracket.md).

- Output is labeled, adjustable SCAD: Customizer groups and ranges, `<kind>_<index>_<dim>` parameters relative to host faces, `assert()` links, face provenance comments, one part-frame `multmatrix()`.
- The gate is all or nothing. If the Hausdorff distance is more than max(0.05 mm, 0.1 % of the bbox diagonal), the output is a polyhedron.
- Snapping moves a value by 0.001 mm or less. It removes float noise and keeps design values.
- Ground truth: `tests/data/segmentation/` (composite bracket and rounded plate, each axis-aligned, rotated and coarse). Tests: `tests/test_segmentation_*.py`.
- Real parts: `memo_stencil6` converts within 0.00001 mm. The legacy preview of the same part is 6.2 mm away. `memo_cartridge` and `memo_power_button` fall back, because convex 3D edge rounds are not supported yet. See [docs/planning/segmentation_real_parts.md](docs/planning/segmentation_real_parts.md).
- `.gitignore` ignores `*.json` and most `.scad`. A new data file needs a `!` rule. Check with `git status -uall`.

## Feature Fixtures — the detector-validation harness (READ FIRST)

[tests/data/feature_fixtures_manifest.json](tests/data/feature_fixtures_manifest.json) + [tests/data/feature_fixtures_scad/](tests/data/feature_fixtures_scad/) + [stl2scad/core/feature_fixtures.py](stl2scad/core/feature_fixtures.py) + [tests/test_feature_fixtures.py](tests/test_feature_fixtures.py) form a closed-loop ground-truth system: **manifest → generated SCAD → rendered STL → feature graph → asserted against the manifest**. This is the primary safety net for detector work.

### Three invariants you must not break

1. **Byte-exact regeneration** ([test_feature_fixture_manifest_matches_checked_in_scad](tests/test_feature_fixtures.py)) — regenerating fixtures from the manifest must equal the checked-in `.scad` files byte-for-byte. If you change the generator, regenerate the library and commit the updated `.scad` files in the same change; do not edit `.scad` files by hand.
2. **Dimensional round-trip** ([test_feature_fixture_round_trip_detection](tests/test_feature_fixtures.py)) — the detector must find the right count AND dimensions (within tolerance) for every fixture. Fails hard in CI when `OpenSCAD` is missing.
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

- `get_openscad_path()` enforces `"OpenSCAD (Nightly)"` in the Windows path string. Don't remove this substring check; it guards against the installed stable OpenSCAD lacking features the codebase relies on.
- Never embed raw Windows `Path` objects in OpenSCAD source. Use `.as_posix()` so OpenSCAD's parser doesn't choke on backslashes.
- Never call `logging.basicConfig(force=True)` inside library functions — it overrides pytest's log capture. Only the CLI entry point may configure logging.
- `--preview=throwntogether` fails headlessly on Windows; use `--render` in tests and headless code paths.
- Don't wrap subprocess calls in PowerShell `-EncodedCommand`; `subprocess.run` with a list handles paths with spaces natively.
- When editing the feature-fixture generator, re-run `python -m pytest tests/test_feature_fixtures.py` and commit any regenerated `.scad` files alongside the generator change.

## Key commands

```bash
# Feature-fixture test slice (fastest detector feedback loop)
python -m pytest tests/test_feature_fixtures.py -v

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
- Core converter entry point: [stl2scad/core/converter.py](stl2scad/core/converter.py)
