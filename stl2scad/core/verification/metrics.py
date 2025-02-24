"""
Geometric metrics for comparing STL and SCAD models.

This module provides functions for calculating and comparing geometric properties
of STL and SCAD models, such as volume, surface area, and bounding box dimensions.
"""

import numpy as np
import subprocess
import re
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, Union, List
import stl
from stl.mesh import Mesh

from ..converter import run_openscad, get_openscad_path


def calculate_stl_volume(mesh: Mesh) -> float:
    """
    Calculate the volume of an STL mesh.
    
    Args:
        mesh: The STL mesh
        
    Returns:
        float: Volume of the mesh
    """
    return float(mesh.get_mass_properties()[0])


def calculate_stl_surface_area(mesh: Mesh) -> float:
    """
    Calculate the surface area of an STL mesh.
    
    Args:
        mesh: The STL mesh
        
    Returns:
        float: Surface area of the mesh
    """
    area = 0.0
    for i in range(len(mesh.vectors)):
        triangle = mesh.vectors[i]
        # Calculate triangle area using cross product
        v1 = triangle[1] - triangle[0]
        v2 = triangle[2] - triangle[0]
        area += 0.5 * np.linalg.norm(np.cross(v1, v2))
    return float(area)


def get_stl_bounding_box(mesh: Mesh) -> Dict[str, float]:
    """
    Get the bounding box of an STL mesh.
    
    Args:
        mesh: The STL mesh
        
    Returns:
        Dict[str, float]: Dictionary with min_x, min_y, min_z, max_x, max_y, max_z, width, height, depth
    """
    # Get min and max coordinates
    min_coords = [float(x) for x in mesh.min_]
    max_coords = [float(x) for x in mesh.max_]
    
    # Calculate dimensions
    dimensions = [max_coords[i] - min_coords[i] for i in range(3)]
    
    return {
        'min_x': min_coords[0],
        'min_y': min_coords[1],
        'min_z': min_coords[2],
        'max_x': max_coords[0],
        'max_y': max_coords[1],
        'max_z': max_coords[2],
        'width': dimensions[0],
        'height': dimensions[1],
        'depth': dimensions[2]
    }


def calculate_scad_metrics(scad_file: Union[str, Path], timeout: int = 60) -> Dict[str, Any]:
    """
    Calculate volume and surface area of a SCAD model using OpenSCAD.
    
    Args:
        scad_file: Path to the SCAD file
        timeout: Timeout in seconds for OpenSCAD execution
        
    Returns:
        Dict[str, Any]: Dictionary with volume, surface_area, and bounding_box
        
    Raises:
        RuntimeError: If OpenSCAD execution fails
    """
    scad_path = Path(scad_file)
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_file}")
    
    # Get OpenSCAD path
    openscad_path = get_openscad_path()
    
    # Create temporary directory for output
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create metrics calculation SCAD file
        metrics_file = Path(temp_dir) / "metrics.scad"
        echo_file = Path(temp_dir) / "metrics.echo"
        
        with open(metrics_file, 'w') as f:
            f.write(f'include "{scad_path.absolute()}";\n')
            f.write('$fn = 100;\n')  # Set facet number for accurate calculations
            f.write('echo("VOLUME=", $fn=100, volume);\n')
            f.write('echo("AREA=", $fn=100, surface_area);\n')
            f.write('echo("BBOX_MIN=", $fn=100, bbox_min);\n')
            f.write('echo("BBOX_MAX=", $fn=100, bbox_max);\n')
        
        # Run OpenSCAD to calculate metrics
        success = run_openscad(
            "Calculate metrics",
            ["--render", "-o", str(echo_file), str(metrics_file)],
            str(Path(temp_dir) / "metrics.log"),
            openscad_path,
            timeout
        )
        
        if not success:
            raise RuntimeError(f"Failed to calculate metrics for {scad_file}")
        
        # Parse metrics from echo file
        metrics = {
            'volume': None,
            'surface_area': None,
            'bounding_box': None
        }
        
        if echo_file.exists():
            with open(echo_file, 'r') as f:
                content = f.read()
                
                # Extract volume
                volume_match = re.search(r'VOLUME=\s*([\d.e+-]+)', content)
                if volume_match:
                    metrics['volume'] = float(volume_match.group(1))
                
                # Extract surface area
                area_match = re.search(r'AREA=\s*([\d.e+-]+)', content)
                if area_match:
                    metrics['surface_area'] = float(area_match.group(1))
                
                # Extract bounding box
                bbox_min_match = re.search(r'BBOX_MIN=\s*\[([\d.e+-]+),\s*([\d.e+-]+),\s*([\d.e+-]+)\]', content)
                bbox_max_match = re.search(r'BBOX_MAX=\s*\[([\d.e+-]+),\s*([\d.e+-]+),\s*([\d.e+-]+)\]', content)
                
                if bbox_min_match and bbox_max_match:
                    min_x = float(bbox_min_match.group(1))
                    min_y = float(bbox_min_match.group(2))
                    min_z = float(bbox_min_match.group(3))
                    max_x = float(bbox_max_match.group(1))
                    max_y = float(bbox_max_match.group(2))
                    max_z = float(bbox_max_match.group(3))
                    
                    metrics['bounding_box'] = {
                        'min_x': min_x,
                        'min_y': min_y,
                        'min_z': min_z,
                        'max_x': max_x,
                        'max_y': max_y,
                        'max_z': max_z,
                        'width': max_x - min_x,
                        'height': max_y - min_y,
                        'depth': max_z - min_z
                    }
        
        return metrics


def compare_metrics(stl_metrics: Dict[str, Any], scad_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare metrics between STL and SCAD models.
    
    Args:
        stl_metrics: Metrics from STL model
        scad_metrics: Metrics from SCAD model
        
    Returns:
        Dict[str, Any]: Comparison results with differences and percentages
    """
    results = {}
    
    # Compare volume
    if 'volume' in stl_metrics and 'volume' in scad_metrics and stl_metrics['volume'] is not None and scad_metrics['volume'] is not None:
        stl_volume = stl_metrics['volume']
        scad_volume = scad_metrics['volume']
        volume_diff = scad_volume - stl_volume
        volume_diff_percent = (volume_diff / stl_volume) * 100 if stl_volume != 0 else float('inf')
        
        results['volume'] = {
            'stl': stl_volume,
            'scad': scad_volume,
            'difference': volume_diff,
            'difference_percent': volume_diff_percent
        }
    
    # Compare surface area
    if 'surface_area' in stl_metrics and 'surface_area' in scad_metrics and stl_metrics['surface_area'] is not None and scad_metrics['surface_area'] is not None:
        stl_area = stl_metrics['surface_area']
        scad_area = scad_metrics['surface_area']
        area_diff = scad_area - stl_area
        area_diff_percent = (area_diff / stl_area) * 100 if stl_area != 0 else float('inf')
        
        results['surface_area'] = {
            'stl': stl_area,
            'scad': scad_area,
            'difference': area_diff,
            'difference_percent': area_diff_percent
        }
    
    # Compare bounding box
    if 'bounding_box' in stl_metrics and 'bounding_box' in scad_metrics and stl_metrics['bounding_box'] is not None and scad_metrics['bounding_box'] is not None:
        stl_bbox = stl_metrics['bounding_box']
        scad_bbox = scad_metrics['bounding_box']
        
        bbox_results = {}
        for dimension in ['width', 'height', 'depth']:
            if dimension in stl_bbox and dimension in scad_bbox:
                stl_dim = stl_bbox[dimension]
                scad_dim = scad_bbox[dimension]
                dim_diff = scad_dim - stl_dim
                dim_diff_percent = (dim_diff / stl_dim) * 100 if stl_dim != 0 else float('inf')
                
                bbox_results[dimension] = {
                    'stl': stl_dim,
                    'scad': scad_dim,
                    'difference': dim_diff,
                    'difference_percent': dim_diff_percent
                }
        
        results['bounding_box'] = bbox_results
    
    return results


def get_stl_metrics(stl_file: Union[str, Path]) -> Dict[str, Any]:
    """
    Calculate all metrics for an STL file.
    
    Args:
        stl_file: Path to the STL file
        
    Returns:
        Dict[str, Any]: Dictionary with volume, surface_area, and bounding_box
        
    Raises:
        FileNotFoundError: If STL file not found
    """
    stl_path = Path(stl_file)
    if not stl_path.exists():
        raise FileNotFoundError(f"STL file not found: {stl_file}")
    
    # Load STL mesh
    mesh = stl.mesh.Mesh.from_file(str(stl_path))
    
    # Calculate metrics
    volume = calculate_stl_volume(mesh)
    surface_area = calculate_stl_surface_area(mesh)
    bounding_box = get_stl_bounding_box(mesh)
    
    return {
        'volume': volume,
        'surface_area': surface_area,
        'bounding_box': bounding_box
    }