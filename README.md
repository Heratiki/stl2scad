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
- Optional visualization and HTML verification reports
- Batch conversion and verification across directory trees

## Parametric Mode Status

Parametric recognition is currently early-stage:
- Implemented: axis-aligned box/cube recognition
- Not yet implemented: cylinder/sphere/cone and multi-primitive reconstruction
- Fallback behavior: if recognition fails, STL2SCAD emits a standard polyhedron model

## Requirements

- Python 3.7+
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

## CLI Usage

Use the module entrypoint:

```bash
python -m stl2scad --help
```

### `convert`

```bash
python -m stl2scad convert <input.stl> <output.scad> [--tolerance 1e-6] [--debug] [--parametric]
```

### `verify`

Verify against an existing SCAD:

```bash
python -m stl2scad verify <input.stl> <existing.scad> [--volume-tol 1.0] [--area-tol 2.0] [--bbox-tol 0.5] [--visualize] [--html-report]
```

Verify with temporary/generated SCAD:

```bash
python -m stl2scad verify <input.stl> [--parametric] [--visualize] [--html-report]
```

### `batch`

```bash
python -m stl2scad batch <input_dir> <output_dir> [--volume-tol 1.0] [--area-tol 2.0] [--bbox-tol 0.5] [--html-report] [--parametric]
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
```

## License

This project is licensed under the MIT License. See `LICENSE` for details.
