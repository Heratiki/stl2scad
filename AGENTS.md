# Agents Guide for stl2scad

This file follows the `AGENTS.md` convention used by Codex and similar agents. The canonical project guide for AI assistants is [CLAUDE.md](CLAUDE.md) — everything below is a summary; read CLAUDE.md for the full version.

## Must-know in three bullets

1. **Feature fixtures are the detector safety net.** [tests/data/feature_fixtures_manifest.json](tests/data/feature_fixtures_manifest.json) → [tests/data/feature_fixtures_scad/](tests/data/feature_fixtures_scad/) → rendered STL → detector → asserted against the manifest. Three invariants: byte-exact regeneration and roadmap coverage ([tests/test_feature_fixtures.py](tests/test_feature_fixtures.py)), and the dimensional round-trip, which T-009 retargets to the segmentation pipeline (the legacy round-trip is in `tests/legacy/`). Don't weaken any of them.
2. **The `.scad` files under `tests/data/feature_fixtures_scad/` are generated, but checked in as golden output.** Do not hand-edit them. If you change the generator in [stl2scad/core/feature_fixtures.py](stl2scad/core/feature_fixtures.py), regenerate the library and commit the updated `.scad` files in the same change.
3. **Read [docs/planning/feature_level_reconstruction.md](docs/planning/feature_level_reconstruction.md) before proposing detector or fixture changes.** The long-term goal is primitive detection with confidence-ranked parametric SCAD output — not polyhedron transcription.

4. **Segmentation is the only conversion pipeline (T-004).** Entry point [stl2scad/core/conversion.py](stl2scad/core/conversion.py), pipeline [stl2scad/core/segmentation/](stl2scad/core/segmentation/). The legacy whole-mesh detectors are archived in `stl2scad/legacy/` (tests in `tests/legacy/`, run only with `STL2SCAD_LEGACY_TESTS=1`); `--pipeline legacy` warns and exits 2. "Failure analysis" in [CLAUDE.md](CLAUDE.md) explains why they were replaced.

## Constraints

- `get_openscad_path()` (`stl2scad/core/openscad/runner.py`) requires `"OpenSCAD (Nightly)"` in the Windows path — don't remove the substring check.
- Never embed raw Windows `Path` objects in SCAD source; use `.as_posix()`.
- Never call `logging.basicConfig(force=True)` in library code.
- Use `--render`, not `--preview=throwntogether`, for headless OpenSCAD on Windows.
- Don't wrap subprocess calls in PowerShell `-EncodedCommand`.

## Feedback loop

```bash
python -m pytest tests/test_feature_fixtures.py -v
```

The three invariants fail loudly if violated — trust those signals and fix the underlying issue rather than editing assertions.
