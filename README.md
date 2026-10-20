# STL2SCAD

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://example.com)
[![Code Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen.svg)](https://example.com)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Overview

STL2SCAD converts STL meshes into OpenSCAD (`.scad`) models.

The project supports two workflows:
- CLI-first automation (`convert`, `verify`, `batch`)
- GUI-based interactive conversion and verification

Conversion runs through the segmentation pipeline (`stl2scad/core/segmentation/`):
it segments the surface, recovers features, and writes labeled, adjustable SCAD
when the result passes a Hausdorff gate against the input mesh; otherwise it
writes the whole mesh as a polyhedron. The older whole-mesh detector pipeline
("legacy") is deprecated and archived in `stl2scad/legacy/` (T-004).

## Current Capabilities

- STL to OpenSCAD conversion through segmentation, with whole-mesh polyhedron fallback
- Deprecated and ignored: `--parametric`, `--recognition-backend`, `--compute-backend`, `--tolerance`
- Verification metrics:
  - volume difference
  - surface area difference
  - bounding-box differences
  - Hausdorff distance (sampled)
  - normal deviation (sampled)
  - conversion metadata capture in verification JSON reports (backend, primitive, diagnostics when available)
- Optional visualization and HTML verification reports
- Batch conversion and verification across directory trees

## Legacy Parametric Mode (deprecated, archived)

The legacy recognizers below are archived in `stl2scad/legacy/` and no longer
run from the CLI or GUI; `--parametric` and `--recognition-backend` are accepted,
print a deprecation warning, and are ignored. The archived description:
- Native backend (`native`): axis-aligned box/cube recognition
- Phase 1 backend (`trimesh_manifold`, optional `trimesh` dependency):
  - connected-component preprocessing and cleanup
  - primitive candidates for sphere, cylinder, cone/frustum, and box
  - conservative disjoint multi-component union assembly
- Phase 2 backend (`cgal`, optional helper):
  - helper-executable JSON boundary and adapter path
  - `cgal` backend attempts direct Python-binding detection first, then helper detection, then falls back to `trimesh_manifold` when available
  - backend/primitive/diagnostics metadata is emitted in SCAD headers and propagated into verification JSON reports
  - release checklist tracked in `docs/planning/phase2_release_checklist.md`
- Not yet implemented: true CGAL shape-detection internals in helper, robust confidence tuning, and full boolean-aware reconstruction
- Fallback behavior: if recognition fails, STL2SCAD emits a standard polyhedron model

## Requirements

- Python 3.10+
- Dependencies from `requirements.txt`
- OpenSCAD (Nightly recommended for debug/verification rendering workflows)

## Installation

```bash
git clone https://github.com/yourusername/stl2scad.git
cd stl2scad
pip install -r requirements.txt
```

For development:

```bash
pip install -r requirements-dev.txt
```

For Phase 1 legacy backend experiments (archived; scripts under `scripts/` only):

```bash
pip install -e .[parametric_phase1]
```

For Phase 2 legacy CGAL-helper experiments (archived; scripts under `scripts/` only):

```bash
pip install -e .[parametric_phase2]

# Point to your helper executable/script (example on Windows)
set STL2SCAD_CGAL_HELPER=C:\path\to\stl2scad-cgal-helper.exe
# or prototype script:
# set STL2SCAD_CGAL_HELPER=C:\path\to\stl2scad\scripts\stl2scad_cgal_helper.py
```

The direct Python binding path currently accepts high-coverage sphere,
cylinder, and cone/frustum detections and falls back for shapes where the SWIG
wrapper does not expose enough extent data for safe SCAD emission.

## CLI Usage

Use the module entrypoint:

```bash
python -m stl2scad --help
```

### `convert`

```bash
python -m stl2scad convert <input.stl> <output.scad> [--pipeline segmentation] [--debug]
# shorthand
python -m stl2scad <input.stl> <output.scad>
```

`--pipeline` defaults to `segmentation`. `--pipeline legacy` is deprecated: it
prints a warning on stderr, writes nothing, and exits `2`. `--parametric`,
`--recognition-backend`, `--compute-backend` and `--tolerance` are deprecated:
they are accepted, print a warning, and are ignored. `--debug` prints a
traceback when conversion fails.

### `verify`

Verify against an existing SCAD:

```bash
python -m stl2scad verify <input.stl> <existing.scad> [--volume-tol 1.0] [--area-tol 2.0] [--bbox-tol 0.5] [--sample-seed 123] [--visualize] [--html-report]
```

Verify with temporary/generated SCAD:

```bash
python -m stl2scad verify <input.stl> [--sample-seed 123] [--visualize] [--html-report]
```

The generated SCAD comes from the segmentation pipeline.

### `batch`

```bash
python -m stl2scad batch <input_dir> <output_dir> [--volume-tol 1.0] [--area-tol 2.0] [--bbox-tol 0.5] [--sample-seed 123] [--html-report]
```

### Deprecated: `feature-inventory`, `feature-graph`, `feature-graph-from-inventory`

These commands only ran the legacy feature-graph detectors. They still parse
their options, but print a deprecation warning on stderr, do no work, and exit
`2`. The archived code is in `stl2scad/legacy/`.

### CLI Exit Codes

- `0`: success
- `1`: runtime/input error
- `2`: verification completed but failed tolerance checks, or a deprecated legacy command/pipeline was requested

## GUI Usage

Launch GUI mode:

```bash
python -m stl2scad --gui
```

No-argument launch also opens the GUI:

```bash
python -m stl2scad
```

### GUI Controls (Current)

- `Open STL File`: load STL and preview mesh
- `Set SCAD Output`: choose output `.scad` path
- `Convert to SCAD`: run conversion with current options
- `Verify Conversion`: run verification workflow
- `Use Existing SCAD`: verify STL against a selected existing SCAD instead of regenerating
- `Select Verify SCAD`: choose the SCAD file used when `Use Existing SCAD` is enabled
- `Debug`: kept for compatibility; segmentation conversion writes no debug artifacts
- `Parametric`, `Backend`, `Compute`, `Tolerance`: deprecated legacy options, shown disabled; conversion always uses segmentation
- `Deterministic sampling`: fix the verification sampling seed for reproducible Hausdorff and normal-deviation metrics
- `Visualize`: generate verification visualization images
- `HTML Report`: generate verification HTML report
- `Diagnostics`: inspect recognition backend choice, confidence, primitive type, raw diagnostics, and fallback reasons after conversion or verification
- `Verify Tol %`: volume/surface/bounding-box verification tolerance controls

When `Use Existing SCAD` is enabled, verification uses the selected SCAD file directly; otherwise the GUI regenerates SCAD from the STL through segmentation.

The `FEATURE TOOLS`, `LOCAL CORPUS` and `REAL-WORLD CORPUS` panels ran the legacy detectors; they are shown disabled and marked deprecated.
The diagnostics panel reads metadata from generated SCAD headers and from verification reports when available, so existing SCAD files without conversion metadata may show limited diagnostics.

## Development

Run all tests:

```bash
pytest
```

Run commonly used focused checks:

```bash
pytest tests/test_cli.py -q
pytest tests/test_segmentation_bracket.py -q

# Legacy pipeline tests live in tests/legacy/ and are skipped unless enabled:
STL2SCAD_LEGACY_TESTS=1 pytest tests/legacy -q
```

Scripts under `scripts/` that ran the legacy detectors (recognition sweep, perf
baseline, corpus scoring, detector tuning, feature-graph builders) now import
the archived modules from `stl2scad.legacy`.

Run the chained maintainer workflow (single command for common checks):

```bash
# Quick profile: fixture/feature/CLI tests + recognition sweep + perf baseline
python -m stl2scad maintainer

# Full profile: includes fixture regeneration before checks
python -m stl2scad maintainer --mode full

# Skip Track C real-world merge-gate for exploratory local runs only
python -m stl2scad maintainer --skip-real-world-gate

# Dry-run: print the command chain without executing
python -m stl2scad maintainer --dry-run
```

`--stl-dir` (and `--inventory-output`, `--feature-graph-output`, `--workers`,
`--max-files`) are deprecated and ignored: the inventory and feature-graph steps
they added ran the legacy detectors (T-004).

By default, `maintainer` includes a Track C real-world recall merge-gate step via
`scripts/score_real_world_corpus.py --merge-gate`, which requires corpus files and
baseline-delta reporting.

Generate/update benchmark fixtures (Phase 0 baseline set):

```bash
python scripts/generate_benchmark_fixtures.py --output-dir tests/data/benchmark_fixtures
```

Run conversion performance baseline on representative mesh sizes:

```bash
python scripts/run_perf_baseline.py --fixtures-dir tests/data/benchmark_fixtures --output artifacts/perf_baseline.json --repeat 3
```

Run Phase 1 backend baseline (polyhedron + parametric modes with `trimesh_manifold`):

```bash
python scripts/run_perf_baseline.py --fixtures-dir tests/data/benchmark_fixtures --output artifacts/perf_phase1_trimesh.json --repeat 3 --recognition-backend trimesh_manifold
```

Run recognition coverage sweep and emit a JSON artifact:

```bash
python scripts/run_recognition_sweep.py --fixtures-dir tests/data/benchmark_fixtures --output artifacts/recognition_sweep.json --backends native,trimesh_manifold,cgal
```

Score the labeled real-world corpus when local STL files are available:

```bash
python scripts/score_real_world_corpus.py --manifest tests/data/real_world_corpus_manifest.json --baseline artifacts/real_world_recall_baseline.json --merge-gate
```

The committed manifest and baseline define the reporting contract; the smoke test
skips cleanly when the local corpus files are absent.

`--merge-gate` exits with code `2` if corpus files are missing or baseline delta
reporting cannot be produced. `scripts/tune_detector.py` enforces the same gate by
default; use `--allow-missing-real-world-gate` only for exploratory local runs.

The detector roadmap also defines a planned user-local corpus loop,
deterministic Thingi10K batch loop, and future in-memory improvement engine.
The local loop lets users benchmark private STL folders without committing or
linking the models; the Thingi10K loop is for public 100-file batches selected
by license and seed; the in-memory loop is intended to retain only
review-relevant artifacts and produce review-ready patches. See
[docs/planning/feature_level_reconstruction.md](docs/planning/feature_level_reconstruction.md)
for the planned scripts and schema expectations.

Create and score a private local corpus manifest:

```bash
python scripts/create_local_corpus.py "D:\3D Files\FDM" --output .local/fdm_corpus.json
python scripts/score_local_corpus.py --manifest .local/fdm_corpus.json --output artifacts/fdm_score.json
python scripts/score_local_corpus.py --manifest .local/fdm_corpus.json --baseline artifacts/fdm_score.json --delta-output artifacts/fdm_delta.json
```

The `.local/` directory is gitignored. The manifest records relative file
paths, sha256, file size, bounds, detector config version/config, optional
labels, and notes; the score report records triage buckets, fingerprint drift,
and optional labeled recall when labels are present.

Use gating thresholds for CI regression checks (multi-feature, not single-fixture):

```bash
python scripts/run_recognition_sweep.py --fixtures-dir tests/data/benchmark_fixtures --fixture-categories primitive --backends trimesh_manifold,cgal --min-detection-rate 0.75 --require-primitives box,sphere,cylinder,cone --max-errors 0
```

When optional backend dependencies are missing, the sweep report and gate output
explicitly include `backend_unavailable` so environment/setup failures are not
mistaken for recognition-regression data.

Use additional hard-sample globs in the same run:

```bash
python scripts/run_recognition_sweep.py --fixtures-dir tests/data --extra-glob "*sample*.stl" --extra-glob "*sample*.STL" --backends cgal --output artifacts/recognition_sweep_samples.json
```

Generate manifest-driven OpenSCAD feature fixtures used for ground-truth
detector evaluation:

```bash
python scripts/generate_feature_fixtures.py
```

## License

This project is licensed under the MIT License. See `LICENSE` for details.
