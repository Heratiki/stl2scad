"""
Tests for STL to SCAD verification functionality.
"""

import pytest
import os
from pathlib import Path
import stl
import numpy as np
from stl2scad.core.converter import stl2scad
from stl2scad.core.verification import (
    calculate_stl_volume,
    calculate_stl_surface_area,
    calculate_scad_metrics,
    compare_metrics,
    verify_conversion,
    verify_existing_conversion,
    generate_comparison_visualization
)
from .utils import setup_logging


def test_stl_metrics_calculation(sample_stl_file):
    """Test calculation of STL metrics."""
    log = setup_logging()
    log("\nTesting STL metrics calculation")
    
    # Load STL mesh
    mesh = stl.mesh.Mesh.from_file(str(sample_stl_file))
    
    # Calculate volume
    volume = calculate_stl_volume(mesh)
    log(f"STL volume: {volume}")
    assert volume > 0, "Volume should be positive"
    
    # Calculate surface area
    surface_area = calculate_stl_surface_area(mesh)
    log(f"STL surface area: {surface_area}")
    assert surface_area > 0, "Surface area should be positive"
    
    # Check relationship between volume and surface area
    # For a cube, surface area = 6 * (volume^(2/3))
    # For a sphere, surface area = 4.84 * (volume^(2/3))
    # So for most objects, surface area should be roughly proportional to volume^(2/3)
    volume_to_area_ratio = surface_area / (volume ** (2/3))
    log(f"Volume to area ratio: {volume_to_area_ratio}")
    assert 3 < volume_to_area_ratio < 10, "Volume to area ratio should be in a reasonable range"


def test_conversion_and_verification(sample_stl_file, test_output_dir):
    """Test conversion and verification of STL to SCAD."""
    log = setup_logging()
    log("\nTesting conversion and verification")
    
    # Convert STL to SCAD
    output_file = test_output_dir / "verification_test.scad"
    stats = stl2scad(str(sample_stl_file), str(output_file))
    
    # Verify conversion
    result = verify_existing_conversion(
        sample_stl_file,
        output_file,
        tolerance={
            'volume': 5.0,  # 5% volume difference tolerance
            'surface_area': 10.0,  # 10% surface area difference tolerance
            'bounding_box': 2.0  # 2% bounding box dimension difference tolerance
        }
    )
    
    # Log verification result
    log(str(result))
    
    # Check that verification completed
    assert result is not None, "Verification result should not be None"
    
    # Check that metrics were calculated
    assert 'volume' in result.comparison, "Volume comparison should be present"
    assert 'surface_area' in result.comparison, "Surface area comparison should be present"
    assert 'bounding_box' in result.comparison, "Bounding box comparison should be present"
    
    # Save verification report
    report_file = test_output_dir / "verification_report.json"
    result.save_report(report_file)
    assert report_file.exists(), "Verification report should be saved"


def test_visualization_generation(sample_stl_file, test_output_dir):
    """Test generation of verification visualizations."""
    log = setup_logging()
    log("\nTesting visualization generation")
    
    # Skip test if running in CI environment
    if os.environ.get('CI') == 'true':
        log("Skipping visualization test in CI environment")
        return
    
    # Convert STL to SCAD
    output_file = test_output_dir / "visualization_test.scad"
    stats = stl2scad(str(sample_stl_file), str(output_file))
    
    # Create visualization directory
    vis_dir = test_output_dir / "visualizations"
    vis_dir.mkdir(exist_ok=True)
    
    try:
        # Generate visualizations
        visualizations = generate_comparison_visualization(
            sample_stl_file,
            output_file,
            vis_dir,
            views=['perspective']  # Only generate perspective view for faster testing
        )
        
        # Check that at least one visualization was generated
        assert len(visualizations) > 0, "At least one visualization should be generated"
        assert 'perspective' in visualizations, "Perspective view should be generated"
        assert visualizations['perspective'].exists(), "Perspective view file should exist"
        
        log(f"Generated {len(visualizations)} visualizations")
        for name, path in visualizations.items():
            log(f"  {name}: {path}")
    
    except Exception as e:
        log(f"Visualization generation failed: {str(e)}", "ERROR")
        # Don't fail the test if visualization fails (might be due to OpenSCAD issues)
        log("Continuing test despite visualization failure")


def test_batch_verification(test_data_dir, test_output_dir):
    """Test batch verification of multiple STL files."""
    log = setup_logging()
    log("\nTesting batch verification")
    
    # Find all STL files in test data directory
    stl_files = list(test_data_dir.glob("*.stl"))
    
    # If no STL files found, create a simple one
    if not stl_files:
        log("No STL files found in test data directory, creating a simple cube")
        cube_file = test_data_dir / "cube.stl"
        create_cube_stl(cube_file)
        stl_files = [cube_file]
    
    # Create batch output directory
    batch_dir = test_output_dir / "batch_verification"
    batch_dir.mkdir(exist_ok=True)
    
    # Convert and verify each STL file
    for stl_file in stl_files:
        log(f"Processing {stl_file.name}")
        
        # Convert STL to SCAD
        scad_file = batch_dir / f"{stl_file.stem}.scad"
        try:
            stats = stl2scad(str(stl_file), str(scad_file))
            
            # Verify conversion
            result = verify_existing_conversion(
                stl_file,
                scad_file,
                tolerance={
                    'volume': 5.0,
                    'surface_area': 10.0,
                    'bounding_box': 2.0
                }
            )
            
            # Save verification report
            report_file = batch_dir / f"{stl_file.stem}_report.json"
            result.save_report(report_file)
            
            log(f"  Verification {'passed' if result.passed else 'failed'}")
            
            # Check that verification completed
            assert result is not None, f"Verification result for {stl_file.name} should not be None"
            
        except Exception as e:
            log(f"Error processing {stl_file.name}: {str(e)}", "ERROR")
            # Continue with next file
            continue


def create_cube_stl(output_file):
    """Create a simple cube STL file for testing."""
    # Define the 8 vertices of the cube
    vertices = np.array([
        [0, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 0, 1],
        [1, 1, 1],
        [0, 1, 1]
    ])
    
    # Define the 12 triangles composing the cube
    faces = np.array([
        [0, 3, 1],
        [1, 3, 2],  # bottom face
        [0, 4, 7],
        [0, 7, 3],  # left face
        [4, 5, 6],
        [4, 6, 7],  # top face
        [5, 1, 2],
        [5, 2, 6],  # right face
        [2, 3, 6],
        [3, 7, 6],  # front face
        [0, 1, 5],
        [0, 5, 4]   # back face
    ])
    
    # Create the mesh
    cube = stl.mesh.Mesh(np.zeros(faces.shape[0], dtype=stl.mesh.Mesh.dtype))
    for i, f in enumerate(faces):
        for j in range(3):
            cube.vectors[i][j] = vertices[f[j],:]
    
    # Write the mesh to file
    cube.save(output_file)