"""
Tests for OpenSCAD command execution and version checking.
"""

import pytest
from pathlib import Path
from stl2scad.core.converter import get_openscad_path, run_openscad
from .utils import setup_logging, check_openscad_processes

def test_openscad_version():
    """Test OpenSCAD version detection."""
    log = setup_logging()
    log("\nTesting OpenSCAD Version Detection")
    
    # Check for existing OpenSCAD processes
    if check_openscad_processes():
        log("Warning: OpenSCAD processes found at start", "WARNING")
    
    try:
        openscad_path = get_openscad_path()
        log(f"OpenSCAD found at: {openscad_path}")
        assert openscad_path is not None
        assert "OpenSCAD (Nightly)" in openscad_path
    except Exception as e:
        log(f"Error getting OpenSCAD path: {str(e)}", "ERROR")
        log(f"Exception type: {type(e)}", "ERROR")
        raise

def test_openscad_commands(test_output_dir):
    """Test basic OpenSCAD commands."""
    log = setup_logging()
    log("\nTesting OpenSCAD Commands")
    
    openscad_path = get_openscad_path()
    test_file = test_output_dir / "test.scad"
    
    # Write a simple test SCAD file
    test_file.write_text('cube(10);')
    
    # Test basic render command
    log("Testing render command")
    result = run_openscad(
        "Basic render",
        ["--render", "-o", str(test_file.with_suffix('.stl')), str(test_file)],
        str(test_output_dir / "render.log"),
        openscad_path
    )
    assert result, "Basic render failed"
    
    # Test preview command
    log("Testing preview command")
    result = run_openscad(
        "Preview",
        ["--preview=throwntogether", "-o", str(test_file.with_suffix('.png')), str(test_file)],
        str(test_output_dir / "preview.log"),
        openscad_path
    )
    assert result, "Preview generation failed"

def test_openscad_with_spaces(test_output_dir):
    """Test OpenSCAD commands with spaces in paths."""
    log = setup_logging()
    log("\nTesting OpenSCAD with Spaces in Paths")
    
    openscad_path = get_openscad_path()
    test_dir = test_output_dir / "test with spaces"
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "test file.scad"
    
    # Write a simple test SCAD file
    test_file.write_text('cube(10);')
    
    # Test command with spaces in paths
    result = run_openscad(
        "Space test",
        ["--render", "-o", str(test_file.with_suffix('.stl')), str(test_file)],
        str(test_dir / "render.log"),
        openscad_path
    )
    assert result, "Command with spaces failed"

def test_openscad_debug_args(test_output_dir):
    """Test OpenSCAD debug arguments."""
    log = setup_logging()
    log("\nTesting OpenSCAD Debug Arguments")
    
    openscad_path = get_openscad_path()
    test_file = test_output_dir / "debug_test.scad"
    
    # Write a test SCAD file
    test_file.write_text('''
    cube(10);
    echo("Debug test");
    ''')
    
    # Test various debug arguments
    debug_args = [
        "--backend=Manifold",
        "--view=axes,edges,scales",
        "--autocenter",
        "--viewall",
        "--colorscheme=Tomorrow_Night",
        "-o", str(test_file.with_suffix('.png')),
        str(test_file)
    ]
    
    result = run_openscad(
        "Debug arguments",
        debug_args,
        str(test_output_dir / "debug.log"),
        openscad_path
    )
    assert result, "Debug arguments test failed"