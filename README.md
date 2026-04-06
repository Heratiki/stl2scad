# STL2SCAD

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://example.com)
[![Code Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen.svg)](https://example.com)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Overview

STL2SCAD converts STL meshes into OpenSCAD (`.scad`) models.

The project supports two workflows:
- CLI-first automation (`convert`, `verify`, `batch`)
- GUI-based interactive conversion and verification

The current primary engineering goal is to expand parametric conversion coverage while preserving safe polyhedron fallback and existing verification/CLI stability.

## Current Capabilities

- STL validation and conversion to OpenSCAD polyhedron output
- Tolerance-based vertex deduplication and degenerate face filtering
- Optional parametric mode (`--parametric`) with safe fallback to polyhedron output
- Verification metrics:
  - volume difference
  - surface area difference
  - bounding-box differences
  - Hausdorff distance (sampled)
  - normal deviation (sampled)
  - conversion metadata capture in verification JSON reports (backend, primitive, diagnostics when available)
- Optional visualization and HTML verification reports
- Batch conversion and verification across directory trees

## Parametric Mode Status

Parametric recognition is currently early-stage:
- Native backend (`native`): axis-aligned box/cube recognition
- Phase 1 backend (`trimesh_manifold`, optional `trimesh` dependency):
  - connected-component preprocessing and cleanup
  - primitive candidates for sphere, cylinder, cone/frustum, and box
  - conservative disjoint multi-component union assembly
- Phase 2 backend (`cgal`, optional helper):
  - helper-executable JSON boundary and adapter path
  - `cgal` backend attempts helper detection first, then falls back to `trimesh_manifold` when available
  - backend/primitive/diagnostics metadata is emitted in SCAD headers and propagated into verification JSON reports
  - release checklist tracked in `docs/planning/phase2_release_checklist.md`
- Not yet implemented: true CGAL shape-detection internals in helper, robust confidence tuning, and full boolean-aware reconstruction
- Fallback behavior: if recognition fails, STL2SCAD emits a standard polyhedron model

## Requirements

- Python 3.8+
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

For Phase 1 parametric backend experiments (`--recognition-backend trimesh_manifold`):

```bash
pip install -e .[parametric_phase1]
```

For Phase 2 CGAL-helper experiments (`--recognition-backend cgal`):

```bash
# Point to your helper executable/script (example on Windows)
set STL2SCAD_CGAL_HELPER=C:\path\to\stl2scad-cgal-helper.exe
# or prototype script:
# set STL2SCAD_CGAL_HELPER=C:\path\to\stl2scad\scripts\stl2scad-cgal-helper.py
```

## CLI Usage

Use the module entrypoint:

```bash
python -m stl2scad --help
```

### `convert`

```bash
python -m stl2scad convert <input.stl> <output.scad> [--tolerance 1e-6] [--debug] [--parametric] [--recognition-backend native|trimesh_manifold|cgal]
```

### `verify`

Verify against an existing SCAD:

```bash
python -m stl2scad verify <input.stl> <existing.scad> [--volume-tol 1.0] [--area-tol 2.0] [--bbox-tol 0.5] [--sample-seed 123] [--visualize] [--html-report]
```

Verify with temporary/generated SCAD:

```bash
python -m stl2scad verify <input.stl> [--parametric] [--recognition-backend native|trimesh_manifold|cgal] [--sample-seed 123] [--visualize] [--html-report]
```

### `batch`

```bash
python -m stl2scad batch <input_dir> <output_dir> [--volume-tol 1.0] [--area-tol 2.0] [--bbox-tol 0.5] [--sample-seed 123] [--html-report] [--parametric] [--recognition-backend native|trimesh_manifold|cgal]
```

### CLI Exit Codes

- `0`: success
- `1`: runtime/input error
- `2`: verification completed but failed tolerance checks

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
- `Debug`: generate debug artifacts during conversion
- `Parametric`: enable primitive recognition path
- `Visualize`: generate verification visualization images
- `HTML Report`: generate verification HTML report
- `Convert Tol`: conversion tolerance control
- `Verify Tol %`: volume/surface/bounding-box verification tolerance controls

## Development

Run all tests:

```bash
pytest
```

Run commonly used focused checks:

```bash
pytest tests/test_cli.py -q
pytest tests/test_conversion.py -q -k "not debug"
pytest tests/test_conversion.py -q -k "phase1_"
```

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

## License

This project is licensed under the MIT License. See `LICENSE` for details.
