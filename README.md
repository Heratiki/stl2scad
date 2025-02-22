# STL to OpenSCAD Converter

A Python tool for converting STL files to OpenSCAD format with optimization and validation. Features both a GUI and command-line interface.

## Features

- Convert STL files to OpenSCAD format
- Interactive 3D preview of STL files
- Vertex deduplication and optimization
- Non-manifold edge detection
- Metadata preservation
- Both GUI and CLI interfaces

## Installation

```bash
# Install from source
git clone https://github.com/herat/stl2scad.git
cd stl2scad
pip install .
```

## Usage

### GUI Interface

Launch the graphical interface:

```bash
stl2scad-gui
```

The GUI provides:
- Interactive 3D preview
- File loading/saving
- View manipulation (rotate, center, fit)
- Color selection
- Conversion progress tracking

### Command Line Interface

Convert files directly from the command line:

```bash
stl2scad input.stl output.scad [--tolerance=1e-6]
```

Options:
- `--tolerance`: Vertex deduplication tolerance (default: 1e-6)

## Project Structure

```
stl2scad/
├── core/
│   ├── __init__.py
│   └── converter.py     # Core conversion logic
├── gui/
│   ├── __init__.py
│   └── main_window.py   # GUI implementation
├── __init__.py
├── __main__.py         # GUI entry point
└── cli.py             # Command-line interface

```

## Requirements

- Python >= 3.8
- numpy >= 2.2.3
- numpy-stl >= 3.2.0
- PyQt5 >= 5.15.11
- pyqtgraph >= 0.13.3
- typing_extensions >= 4.12.2

## License

MIT License
