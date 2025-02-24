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
    compare_metrics,
    get_stl_metrics
)

from .verification import (
    VerificationResult,
    verify_conversion,
    verify_existing_conversion,
    batch_verify
)

from .visualization import (
    generate_comparison_visualization,
    generate_verification_report_html
)

__all__ = [
    # Metrics
    'calculate_stl_volume',
    'calculate_stl_surface_area',
    'calculate_scad_metrics',
    'compare_metrics',
    'get_stl_metrics',
    
    # Verification
    'VerificationResult',
    'verify_conversion',
    'verify_existing_conversion',
    'batch_verify',
    
    # Visualization
    'generate_comparison_visualization',
    'generate_verification_report_html'
]