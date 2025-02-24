"""
STL to SCAD accuracy verification system.

This package provides tools for verifying the geometric accuracy of STL to SCAD conversions.
It includes metrics for comparing volumes, surface areas, and other geometric properties,
as well as visualization tools for identifying differences between the original and converted models.
"""

from .metrics import (
    calculate_stl_volume,
    calculate_stl_surface_area,
    calculate_scad_metrics,
    compare_metrics
)

from .verification import (
    VerificationResult,
    verify_conversion
)

__all__ = [
    'calculate_stl_volume',
    'calculate_stl_surface_area',
    'calculate_scad_metrics',
    'compare_metrics',
    'VerificationResult',
    'verify_conversion'
]