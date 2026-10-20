"""
stl2scad - Convert STL files to OpenSCAD format with optimization and validation.

convert_stl_to_scad() converts through the segmentation pipeline (T-004). The
legacy stl2scad() function is archived under stl2scad/legacy/ (converter.py).
"""

from stl2scad.core.conversion import (
    ConversionStats,
    STLValidationError,
    convert_stl_to_scad,
)

__version__ = "0.1.0"
__all__ = ["convert_stl_to_scad", "ConversionStats", "STLValidationError"]
