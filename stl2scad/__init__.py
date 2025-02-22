"""
stl2scad - Convert STL files to OpenSCAD format with optimization and validation.
"""

from stl2scad.core.converter import stl2scad, ConversionStats, STLValidationError

__version__ = "0.1.0"
__all__ = ["stl2scad", "ConversionStats", "STLValidationError"]
