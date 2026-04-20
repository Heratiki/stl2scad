# Copilot Instructions for stl2scad

See [CLAUDE.md](../CLAUDE.md) for the full AI guide. This file is the short version Copilot surfaces inline.

## What this project is

stl2scad converts STL meshes into editable OpenSCAD. The long-term goal is primitive detection and parametric SCAD output (cube / cylinder / sphere with named variables), not polyhedron transcription. The primary active work is in [stl2scad/core/feature_graph.py](../stl2scad/core/feature_graph.py), [stl2scad/core/feature_fixtures.py](../stl2scad/core/feature_fixtures.py), and [stl2scad/core/feature_inventory.py](../stl2scad/core/feature_inventory.py).

## Feature fixtures are the detector validation harness

[tests/data/feature_fixtures_manifest.json](../tests/data/feature_fixtures_manifest.json) plus the checked-in `.scad` files under [tests/data/feature_fixtures_scad/](../tests/data/feature_fixtures_scad/) are the ground-truth corpus. The round-trip test renders them to STL, runs the detector, and asserts counts and dimensions match. Three invariants must never be broken:

1. Regenerating `.scad` from the manifest must match the checked-in files byte-for-byte.
2. The dimensional round-trip must pass for every fixture (and hard-fails in CI when OpenSCAD is missing).
3. The manifest must always cover the roadmap stress categories (mixed features, high-aspect plates, small/large diameters, near-boundary holes, box and l_bracket types).

## Conventions

- `.scad` fixtures are **generated**, not hand-edited. Change the manifest or the generator, then regenerate.
- `get_openscad_path()` requires `"OpenSCAD (Nightly)"` in the Windows path string; keep the check.
- Use `Path.as_posix()` when embedding paths in SCAD source.
- Library code must not call `logging.basicConfig(force=True)`.
- Use `--render`, not `--preview=throwntogether`, for headless rendering on Windows.

## First command to run when touching detector or fixture code

```bash
python -m pytest tests/test_feature_fixtures.py -v
```
