# AI Assistant Guide for stl2scad

This file is the canonical entry point for AI coding assistants (Claude Code, Cursor, Cline). See also [AGENTS.md](AGENTS.md) (Codex) and [.github/copilot-instructions.md](.github/copilot-instructions.md) (GitHub Copilot) — they point back here.

## Project in one paragraph

stl2scad converts STL meshes into editable OpenSCAD. Today's output is primarily polyhedron; the long-term goal is **primitive detection + parametric SCAD output** with confidence-scored multi-interpretation ranking. Core conversion lives in [stl2scad/core/converter.py](stl2scad/core/converter.py); the detector pipeline lives in [stl2scad/core/feature_graph.py](stl2scad/core/feature_graph.py) and [stl2scad/core/feature_inventory.py](stl2scad/core/feature_inventory.py). The roadmap and current assessment is in [docs/planning/feature_level_reconstruction.md](docs/planning/feature_level_reconstruction.md) — read this before proposing detector or fixture changes.

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
