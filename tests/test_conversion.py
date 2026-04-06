"""
Tests for STL to SCAD conversion functionality.
"""

import pytest
from stl2scad.core.converter import stl2scad, validate_stl, STLValidationError
import stl
from .utils import setup_logging, verify_debug_files
import numpy

def test_basic_conversion(sample_stl_file, test_output_dir):
    """Test basic STL to SCAD conversion without debug features."""
    log = setup_logging()
    log("\nTesting Basic STL to SCAD Conversion")
    
    output_file = test_output_dir / "test_output.scad"
    
    try:
        # Run conversion
        stats = stl2scad(str(sample_stl_file), str(output_file))
        
        # Verify output file exists
        assert output_file.exists(), "Output SCAD file not created"
        assert output_file.stat().st_size > 0, "Output SCAD file is empty"
        
        # Verify conversion statistics
        log("\nConversion Statistics:")
        log(f"Original vertices: {stats.original_vertices}")
        log(f"Deduplicated vertices: {stats.deduplicated_vertices}")
        log(f"Faces: {stats.faces}")
        
        # Verify metadata
        log("\nMetadata:")
        for key, value in stats.metadata.items():
            log(f"{key}: {value}")
            
        assert stats.deduplicated_vertices <= stats.original_vertices, "Vertex deduplication failed"
        assert stats.faces > 0, "No faces in output"
        
    except Exception as e:
        log(f"Error during conversion: {str(e)}", "ERROR")
        raise

def test_debug_conversion(sample_stl_file, test_output_dir):
    """Test STL to SCAD conversion with debug features enabled."""
    log = setup_logging()
    log("\nTesting Debug STL to SCAD Conversion")
    
    output_file = test_output_dir / "test_output.scad"
    
    try:
        # Run conversion with debug enabled
        stats = stl2scad(str(sample_stl_file), str(output_file), debug=True)
        
        # Get debug file paths
        debug_base = output_file.stem
        debug_files = {
            'scad': test_output_dir / f"{debug_base}_debug.scad",
            'json': test_output_dir / f"{debug_base}_analysis.json",
            'echo': test_output_dir / f"{debug_base}_debug.echo",
            'png': test_output_dir / f"{debug_base}_preview.png"
        }
        
        # Verify debug files
        files_status = verify_debug_files(debug_files)
        log("\nChecking debug files:")
        for name, status in files_status.items():
            log(f"{name}: {status['status']} ({status['size']:,} bytes)")
            if not status['exists'] or status['size'] == 0:
                log(f"Warning: {name} file is missing or empty", "WARNING")
        
        # Verify debug SCAD file content
        debug_scad = debug_files['scad']
        if debug_scad.exists():
            content = debug_scad.read_text()
            assert 'import' in content, "Debug SCAD missing import statement"
            assert 'translate' in content, "Debug SCAD missing translation"
            assert 'debug_info' in content, "Debug SCAD missing debug info"
        
    except Exception as e:
        log(f"Error during debug conversion: {str(e)}", "ERROR")
        raise

def test_stl_validation(sample_stl_file):
    """Test STL file validation."""
    log = setup_logging()
    log("\nTesting STL Validation")
    
    try:
        # Load and validate STL
        mesh = stl.mesh.Mesh.from_file(str(sample_stl_file))
        validate_stl(mesh)
        log("STL validation passed")
        
        # Test validation with empty mesh
        empty_mesh = stl.mesh.Mesh(numpy.array([], dtype=stl.mesh.Mesh.dtype))
        with pytest.raises(STLValidationError) as e:
            validate_stl(empty_mesh)
        assert "Empty STL file" in str(e.value)
        log("Empty mesh validation correctly failed")
        
    except Exception as e:
        log(f"Error during STL validation: {str(e)}", "ERROR")
        raise

def test_vertex_deduplication(sample_stl_file, test_output_dir):
    """Test vertex deduplication functionality."""
    log = setup_logging()
    log("\nTesting Vertex Deduplication")
    
    output_file = test_output_dir / "dedup_test.scad"
    
    # Test with different tolerances
    tolerances = [1e-6, 1e-3, 1e-9]
    for tol in tolerances:
        log(f"\nTesting with tolerance: {tol}")
        stats = stl2scad(str(sample_stl_file), str(output_file), tolerance=tol)
        reduction = 100 * (1 - stats.deduplicated_vertices/stats.original_vertices)
        log(f"Vertex reduction: {reduction:.1f}%")
        assert stats.deduplicated_vertices > 0, "No vertices after deduplication"

def test_degenerate_faces_filtered(test_output_dir):
    """Degenerate faces created by tolerance snapping should be removed."""
    log = setup_logging()
    log("\nTesting Degenerate Face Filtering")

    input_file = test_output_dir / "degenerate_input.stl"
    output_file = test_output_dir / "degenerate_output.scad"

    # Two triangles: one valid, one that collapses with tolerance=1e-3.
    mesh = stl.mesh.Mesh(numpy.zeros(2, dtype=stl.mesh.Mesh.dtype))
    mesh.vectors[0] = numpy.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0]
    ])
    mesh.vectors[1] = numpy.array([
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0001],
        [0.0, 1.0, 0.0]
    ])
    mesh.save(str(input_file))

    stats = stl2scad(str(input_file), str(output_file), tolerance=1e-3)
    assert output_file.exists(), "Output SCAD file not created"
    assert stats.faces == 1, "One degenerate face should have been filtered"
    assert stats.metadata.get("degenerate_faces_removed") == "1"

def test_invalid_tolerance_raises(sample_stl_file, test_output_dir):
    """API should reject zero/negative tolerance values."""
    output_file = test_output_dir / "invalid_tolerance.scad"
    with pytest.raises(ValueError, match="Tolerance must be positive"):
        stl2scad(str(sample_stl_file), str(output_file), tolerance=0)

def test_parametric_cube_recognition(sample_stl_file, test_output_dir):
    """Test that a pure cube STL is recognized and exported as a parametric cube()."""
    output_file = test_output_dir / "parametric_cube.scad"
    # Convert with parametric enabled
    stl2scad(str(sample_stl_file), str(output_file), parametric=True)
    
    assert output_file.exists(), "Output SCAD file not created"
    content = output_file.read_text()
    
    # It should contain cube() and translate() and NOT polyhedron()
    assert "cube([" in content, "Missing parametric cube() call"
    assert "translate([" in content, "Missing translate() call for position"
    assert "polyhedron" not in content, "Should not emit polyhedron for a basic cube"

