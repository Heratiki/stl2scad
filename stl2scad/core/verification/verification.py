"""
Verification system for STL to SCAD conversion accuracy.

This module provides the core functionality for verifying the accuracy of
STL to SCAD conversions by comparing geometric properties and generating
verification reports.
"""

import os
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Union, List, Tuple
from dataclasses import dataclass, field
import stl
import numpy as np

from ..converter import stl2scad
from .metrics import get_stl_metrics, calculate_scad_metrics, compare_metrics


@dataclass
class VerificationResult:
    """
    Result of a verification operation.
    
    Attributes:
        stl_file: Path to the original STL file
        scad_file: Path to the converted SCAD file
        stl_metrics: Metrics calculated from the STL file
        scad_metrics: Metrics calculated from the SCAD file
        comparison: Comparison between STL and SCAD metrics
        passed: Whether the verification passed
        tolerance: Tolerance used for verification
        report: Detailed verification report
    """
    stl_file: str
    scad_file: str
    stl_metrics: Dict[str, Any]
    scad_metrics: Dict[str, Any]
    comparison: Dict[str, Any]
    passed: bool
    tolerance: Dict[str, float]
    report: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        """Return a string representation of the verification result."""
        status = "PASSED" if self.passed else "FAILED"
        
        # Format volume comparison
        volume_str = ""
        if 'volume' in self.comparison:
            vol_comp = self.comparison['volume']
            volume_str = (
                f"Volume: STL={vol_comp['stl']:.2f}, SCAD={vol_comp['scad']:.2f}, "
                f"Diff={vol_comp['difference']:.2f} ({vol_comp['difference_percent']:.2f}%)"
            )
        
        # Format surface area comparison
        area_str = ""
        if 'surface_area' in self.comparison:
            area_comp = self.comparison['surface_area']
            area_str = (
                f"Surface Area: STL={area_comp['stl']:.2f}, SCAD={area_comp['scad']:.2f}, "
                f"Diff={area_comp['difference']:.2f} ({area_comp['difference_percent']:.2f}%)"
            )
        
        # Format bounding box comparison
        bbox_str = ""
        if 'bounding_box' in self.comparison:
            bbox_comp = self.comparison['bounding_box']
            dimensions = []
            for dim in ['width', 'height', 'depth']:
                if dim in bbox_comp:
                    dim_comp = bbox_comp[dim]
                    dimensions.append(
                        f"{dim.capitalize()}={dim_comp['difference_percent']:.2f}%"
                    )
            bbox_str = f"Bounding Box Diff: {', '.join(dimensions)}"
        
        return (
            f"Verification {status}\n"
            f"STL: {self.stl_file}\n"
            f"SCAD: {self.scad_file}\n"
            f"{volume_str}\n"
            f"{area_str}\n"
            f"{bbox_str}"
        )
    
    def to_json(self) -> str:
        """Convert the verification result to a JSON string."""
        # Create a dictionary representation
        result_dict = {
            'stl_file': str(self.stl_file),
            'scad_file': str(self.scad_file),
            'passed': self.passed,
            'tolerance': self.tolerance,
            'stl_metrics': self.stl_metrics,
            'scad_metrics': self.scad_metrics,
            'comparison': self.comparison,
            'report': self.report
        }
        
        return json.dumps(result_dict, indent=2)
    
    def save_report(self, output_file: Union[str, Path]) -> None:
        """
        Save the verification report to a file.
        
        Args:
            output_file: Path to save the report
        """
        with open(output_file, 'w') as f:
            f.write(self.to_json())


def verify_conversion(
    stl_file: Union[str, Path],
    scad_file: Optional[Union[str, Path]] = None,
    tolerance: Optional[Dict[str, float]] = None,
    debug: bool = False
) -> VerificationResult:
    """
    Verify the accuracy of an STL to SCAD conversion.
    
    Args:
        stl_file: Path to the STL file
        scad_file: Path to the SCAD file (if None, will convert STL to SCAD)
        tolerance: Dictionary of tolerance values for different metrics
        debug: Whether to enable debug mode
        
    Returns:
        VerificationResult: Result of the verification
        
    Raises:
        FileNotFoundError: If STL file not found
    """
    stl_path = Path(stl_file)
    if not stl_path.exists():
        raise FileNotFoundError(f"STL file not found: {stl_file}")
    
    # Set default tolerance values
    if tolerance is None:
        tolerance = {
            'volume': 1.0,  # 1% volume difference
            'surface_area': 2.0,  # 2% surface area difference
            'bounding_box': 0.5  # 0.5% bounding box dimension difference
        }
    
    # Convert STL to SCAD if no SCAD file provided
    if scad_file is None:
        # Create temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_scad = Path(temp_dir) / f"{stl_path.stem}.scad"
            stl2scad(str(stl_path), str(temp_scad), debug=debug)
            return verify_existing_conversion(stl_path, temp_scad, tolerance, debug)
    else:
        scad_path = Path(scad_file)
        return verify_existing_conversion(stl_path, scad_path, tolerance, debug)


def verify_existing_conversion(
    stl_file: Path,
    scad_file: Path,
    tolerance: Dict[str, float],
    debug: bool = False
) -> VerificationResult:
    """
    Verify the accuracy of an existing STL to SCAD conversion.
    
    Args:
        stl_file: Path to the STL file
        scad_file: Path to the SCAD file
        tolerance: Dictionary of tolerance values for different metrics
        debug: Whether to enable debug mode
        
    Returns:
        VerificationResult: Result of the verification
    """
    # Calculate STL metrics
    stl_metrics = get_stl_metrics(stl_file)
    
    # Calculate SCAD metrics
    scad_metrics = calculate_scad_metrics(scad_file)
    
    # Compare metrics
    comparison = compare_metrics(stl_metrics, scad_metrics)
    
    # Check if verification passed
    passed = True
    
    # Check volume tolerance
    if 'volume' in comparison:
        volume_diff_percent = abs(comparison['volume']['difference_percent'])
        if volume_diff_percent > tolerance['volume']:
            passed = False
    
    # Check surface area tolerance
    if 'surface_area' in comparison:
        area_diff_percent = abs(comparison['surface_area']['difference_percent'])
        if area_diff_percent > tolerance['surface_area']:
            passed = False
    
    # Check bounding box tolerance
    if 'bounding_box' in comparison:
        for dim, values in comparison['bounding_box'].items():
            dim_diff_percent = abs(values['difference_percent'])
            if dim_diff_percent > tolerance['bounding_box']:
                passed = False
                break
    
    # Create verification result
    result = VerificationResult(
        stl_file=str(stl_file),
        scad_file=str(scad_file),
        stl_metrics=stl_metrics,
        scad_metrics=scad_metrics,
        comparison=comparison,
        passed=passed,
        tolerance=tolerance
    )
    
    # Generate detailed report
    report = {
        'verification_result': 'passed' if passed else 'failed',
        'metrics_comparison': comparison,
        'tolerance_used': tolerance,
        'failures': []
    }
    
    # Add failure details
    if 'volume' in comparison:
        volume_diff_percent = abs(comparison['volume']['difference_percent'])
        if volume_diff_percent > tolerance['volume']:
            report['failures'].append({
                'metric': 'volume',
                'difference_percent': volume_diff_percent,
                'tolerance': tolerance['volume'],
                'message': f"Volume difference ({volume_diff_percent:.2f}%) exceeds tolerance ({tolerance['volume']:.2f}%)"
            })
    
    if 'surface_area' in comparison:
        area_diff_percent = abs(comparison['surface_area']['difference_percent'])
        if area_diff_percent > tolerance['surface_area']:
            report['failures'].append({
                'metric': 'surface_area',
                'difference_percent': area_diff_percent,
                'tolerance': tolerance['surface_area'],
                'message': f"Surface area difference ({area_diff_percent:.2f}%) exceeds tolerance ({tolerance['surface_area']:.2f}%)"
            })
    
    if 'bounding_box' in comparison:
        for dim, values in comparison['bounding_box'].items():
            dim_diff_percent = abs(values['difference_percent'])
            if dim_diff_percent > tolerance['bounding_box']:
                report['failures'].append({
                    'metric': f"bounding_box_{dim}",
                    'difference_percent': dim_diff_percent,
                    'tolerance': tolerance['bounding_box'],
                    'message': f"Bounding box {dim} difference ({dim_diff_percent:.2f}%) exceeds tolerance ({tolerance['bounding_box']:.2f}%)"
                })
    
    result.report = report
    
    return result


def batch_verify(
    stl_files: List[Union[str, Path]],
    output_dir: Union[str, Path],
    tolerance: Optional[Dict[str, float]] = None,
    debug: bool = False
) -> Dict[str, VerificationResult]:
    """
    Verify multiple STL to SCAD conversions.
    
    Args:
        stl_files: List of STL file paths
        output_dir: Directory to save SCAD files and reports
        tolerance: Dictionary of tolerance values for different metrics
        debug: Whether to enable debug mode
        
    Returns:
        Dict[str, VerificationResult]: Dictionary of verification results keyed by STL file name
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True, parents=True)
    
    results = {}
    
    for stl_file in stl_files:
        stl_path = Path(stl_file)
        scad_path = output_path / f"{stl_path.stem}.scad"
        report_path = output_path / f"{stl_path.stem}_verification.json"
        
        # Convert and verify
        result = verify_conversion(stl_path, scad_path, tolerance, debug)
        
        # Save report
        result.save_report(report_path)
        
        # Store result
        results[stl_path.name] = result
    
    # Create summary report
    summary = {
        'total': len(results),
        'passed': sum(1 for r in results.values() if r.passed),
        'failed': sum(1 for r in results.values() if not r.passed),
        'results': {name: {'passed': result.passed} for name, result in results.items()}
    }
    
    with open(output_path / "verification_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    return results