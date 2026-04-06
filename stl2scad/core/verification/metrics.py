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
    v1 = mesh.vectors[:, 1] - mesh.vectors[:, 0]
    v2 = mesh.vectors[:, 2] - mesh.vectors[:, 0]
    area = 0.5 * np.sum(np.linalg.norm(np.cross(v1, v2), axis=1))
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


def sample_mesh_points(mesh: Mesh, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Uniformly sample points and their normals from an STL mesh.
    
    Args:
        mesh: The STL mesh
        num_samples: Number of points to sample
        
    Returns:
        Tuple[np.ndarray, np.ndarray]: Arrays of sampled points and their corresponding normals
    """
    # Calculate areas of all triangles
    v0 = mesh.vectors[:, 0]
    v1 = mesh.vectors[:, 1]
    v2 = mesh.vectors[:, 2]
    
    # Cross product magnitude is twice the area
    cross_prod = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross_prod, axis=1)
    
    total_area = np.sum(areas)
    if total_area == 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
        
    probabilities = areas / total_area
    
    # Choose triangles based on area
    triangle_indices = np.random.choice(len(mesh.vectors), size=num_samples, p=probabilities)
    sampled_triangles = mesh.vectors[triangle_indices]
    sampled_normals = mesh.normals[triangle_indices]
    
    # Normalize normals to handle any unnormalized normals in the mesh
    norms = np.linalg.norm(sampled_normals, axis=1, keepdims=True)
    norms[norms == 0] = 1.0 # avoid division by zero
    sampled_normals = sampled_normals / norms
    
    # Generate random barycentric coordinates
    u = np.random.rand(num_samples, 1)
    v = np.random.rand(num_samples, 1)
    
    # Adjust to keep within the triangle
    mask = u + v > 1
    u[mask] = 1 - u[mask]
    v[mask] = 1 - v[mask]
    w = 1 - u - v
    
    # Calculate uniform points inside chosen triangles
    A = sampled_triangles[:, 0]
    B = sampled_triangles[:, 1]
    C = sampled_triangles[:, 2]
    
    points = u * A + v * B + w * C
    
    return points, sampled_normals


def calculate_hausdorff_distance(points1: np.ndarray, points2: np.ndarray) -> float:
    """
    Calculate Hausdorff distance between two sets of points using broadcasting.
    
    Args:
        points1: First array of points (N, 3)
        points2: Second array of points (M, 3)
        
    Returns:
        float: Hausdorff distance
    """
    if len(points1) == 0 or len(points2) == 0:
        return 0.0
    
    # Calculate pairwise distances (N, M)
    # Using squared distance first to save computation
    diff = points1[:, np.newaxis, :] - points2[np.newaxis, :, :]
    dist_sq = np.sum(diff ** 2, axis=-1)
    
    # For each point in points1, find the minimum distance to points2
    min_dist_sq_1 = np.min(dist_sq, axis=1)
    
    # For each point in points2, find the minimum distance to points1
    min_dist_sq_2 = np.min(dist_sq, axis=0)
    
    # The Hausdorff distance is the maximum of these minimums
    hausdorff_sq = max(np.max(min_dist_sq_1), np.max(min_dist_sq_2))
    
    return float(np.sqrt(hausdorff_sq))


def compare_normal_vectors(points1: np.ndarray, normals1: np.ndarray, 
                         points2: np.ndarray, normals2: np.ndarray) -> float:
    """
    Compare normal deviations between two surfaces.
    For each point in points1, finds nearest point in points2 and measures angle between normals.
    
    Returns:
        float: Maximum normal deviation in degrees (95th percentile to ignore outliers).
    """
    if len(points1) == 0 or len(points2) == 0:
        return 0.0
        
    # Find nearest neighbors from points1 to points2
    diff = points1[:, np.newaxis, :] - points2[np.newaxis, :, :]
    dist_sq = np.sum(diff ** 2, axis=-1)
    nearest_idx = np.argmin(dist_sq, axis=1)
    
    nearest_normals = normals2[nearest_idx]
    
    # Calculate angles between normals1 and nearest_normals via dot product
    dot_products = np.sum(normals1 * nearest_normals, axis=1)
    dot_products = np.clip(dot_products, -1.0, 1.0)
    
    angles_rad = np.arccos(dot_products)
    angles_deg = np.degrees(angles_rad)
    
    # Return the 95th percentile of errors to be robust against a few outliers
    return float(np.percentile(angles_deg, 95))


def calculate_scad_metrics(scad_file: Union[str, Path], timeout: int = 120) -> Dict[str, Any]:
    """
    Calculate volume and surface area of a SCAD model using OpenSCAD via STL export.
    
    Args:
        scad_file: Path to the SCAD file
        timeout: Timeout in seconds for OpenSCAD execution
        
    Returns:
        Dict[str, Any]: Dictionary with volume, surface_area, bounding_box, and mesh
        
    Raises:
        RuntimeError: If OpenSCAD execution fails
    """
    scad_path = Path(scad_file)
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_file}")
    
    # Get OpenSCAD path
    openscad_path = get_openscad_path()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_stl = Path(temp_dir) / "rendered.stl"
        log_file = Path(temp_dir) / "render.log"
        
        args = ["-o", str(temp_stl), str(scad_path)]
        
        # Run OpenSCAD to calculate metrics
        success = run_openscad(
            "Export SCAD to STL for metrics",
            args,
            str(log_file),
            openscad_path,
            timeout
        )

        if not success or not temp_stl.exists():
            error_msg = "OpenSCAD rendering failed."
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as lf:
                    error_msg += " Log output:\n" + lf.read()
            raise RuntimeError(f"Failed to calculate SCAD metrics: {error_msg}")

        try:
            rendered_mesh = stl.mesh.Mesh.from_file(str(temp_stl))
            
            volume = calculate_stl_volume(rendered_mesh)
            surface_area = calculate_stl_surface_area(rendered_mesh)
            bounding_box = get_stl_bounding_box(rendered_mesh)
            
            return {
                'volume': volume,
                'surface_area': surface_area,
                'bounding_box': bounding_box,
                'mesh': rendered_mesh
            }
        except Exception as e:
            raise RuntimeError(f"Failed to calculate SCAD metrics after rendering: {str(e)}")


def compare_metrics(stl_metrics: Dict[str, Any], scad_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare metrics between STL and SCAD models.
    
    Args:
        stl_metrics: Metrics from STL model
        scad_metrics: Metrics from SCAD model
        
    Returns:
        Dict[str, Any]: Comparison results with differences and percentages
    """
    results: Dict[str, Any] = {}
    
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

    # Calculate point-based metrics if both meshes are available
    if 'mesh' in stl_metrics and 'mesh' in scad_metrics and stl_metrics['mesh'] is not None and scad_metrics['mesh'] is not None:
        stl_mesh = stl_metrics['mesh']
        scad_mesh = scad_metrics['mesh']
        
        num_samples = 1000
        stl_points, stl_normals = sample_mesh_points(stl_mesh, num_samples)
        scad_points, scad_normals = sample_mesh_points(scad_mesh, num_samples)
        
        hausdorff = calculate_hausdorff_distance(stl_points, scad_points)
        normal_dev = compare_normal_vectors(stl_points, stl_normals, scad_points, scad_normals)
        
        # Compute relative bounding box diagonal for percentage calculation of Hausdorff
        # using STL mesh bounding box
        stl_bbox = stl_metrics['bounding_box']
        diagonal = np.sqrt(stl_bbox['width']**2 + stl_bbox['height']**2 + stl_bbox['depth']**2)
        hausdorff_pct = (hausdorff / diagonal * 100) if diagonal > 0 else 0.0
        
        results['hausdorff_distance'] = {
            'value': hausdorff,
            'difference_percent': hausdorff_pct
        }
        
        results['normal_deviation'] = {
            'value': normal_dev,
            'difference_percent': normal_dev  # In degrees, acts as its own percentage/delta conceptually
        }

    return results


def get_stl_metrics(stl_file: Union[str, Path]) -> Dict[str, Any]:
    """
    Calculate all metrics for an STL file.
    
    Args:
        stl_file: Path to the STL file
        
    Returns:
        Dict[str, Any]: Dictionary with volume, surface_area, bounding_box, and mesh
        
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
        'bounding_box': bounding_box,
        'mesh': mesh
    }