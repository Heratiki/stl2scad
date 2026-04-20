# Feature Fixture SCAD Library

**Do not hand-edit these files.** They are generated from [../feature_fixtures_manifest.json](../feature_fixtures_manifest.json) by [stl2scad/core/feature_fixtures.py](../../../stl2scad/core/feature_fixtures.py) and checked in as golden output for the detector-validation harness.

## What this directory is

Each `.scad` here is paired with a manifest entry that declares the geometry and the expected detector output. The test suite renders each file to STL with OpenSCAD, runs the feature graph detector on the result, and asserts that counts and dimensions match the manifest within tolerance.

The checked-in `.scad` files serve three purposes:

1. **Byte-exact regression fence** — [test_feature_fixture_manifest_matches_checked_in_scad](../../test_feature_fixtures.py) asserts the generator still produces identical output. Any unintentional drift in formatting, precision, or module emission fails loudly.
2. **Visual ground truth** — open any file in the OpenSCAD GUI to see what the detector is supposed to find for that fixture name.
3. **Reproducible STL corpus** — `openscad --render -o out.stl this_file.scad` yields a deterministic STL for detector debugging, cross-backend comparison, and benchmarking.

## How to add or change a fixture

1. Edit [../feature_fixtures_manifest.json](../feature_fixtures_manifest.json) — add a new entry or modify an existing one.
2. Run `python -m pytest tests/test_feature_fixtures.py -v`. The byte-exact test will fail with the expected new or updated output written to `tests/.tmp_output/`.
3. Copy the regenerated `.scad` files into this directory and commit them alongside the manifest change.

Never edit a `.scad` here to make a test pass. If the detector disagrees with a fixture, fix the detector or file the disagreement as a known limitation — not the fixture.

## Background

See [CLAUDE.md](../../../CLAUDE.md) for the full AI/contributor guide and [docs/planning/feature_level_reconstruction.md](../../../docs/planning/feature_level_reconstruction.md) for the roadmap.
