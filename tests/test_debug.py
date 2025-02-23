#!/usr/bin/env python3
"""
Test script for STL2SCAD debug features.
"""

import os
import sys
import traceback
import datetime
import psutil
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from stl2scad.core.converter import stl2scad, get_openscad_path

def test_debug_features(verbose=True, log_file="test_run.log"):
    """Test the debug features of the STL to SCAD converter."""
    def log(msg, level="INFO"):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] {level}: {msg}"
        if verbose:
            print(log_msg, flush=True)
        with open(log_file, 'a') as f:
            f.write(f"{log_msg}\n")

    # Clear previous log
    with open(log_file, 'w') as f:
        f.write("=== Starting Test ===\n")
    
    log("\n=== Testing STL2SCAD Debug Features ===")
    
    def check_openscad_processes():
        """Check for running OpenSCAD processes"""
        openscad_procs = [p for p in psutil.process_iter(['name'])
                         if p.info['name'] and 'openscad' in p.info['name'].lower()]
        if openscad_procs:
            log(f"Found {len(openscad_procs)} OpenSCAD processes running", "WARNING")
            for proc in openscad_procs:
                log(f"OpenSCAD process: PID={proc.pid}", "WARNING")
            return True
        return False
    
    # Check for OpenSCAD processes at start
    if check_openscad_processes():
        log("Warning: OpenSCAD processes found at start, they may interfere with testing", "WARNING")
    
    # Test file paths
    input_file = os.path.join("testobjects", "Cube_3d_printing_sample.stl")
    output_file = "test_output.scad"
    
    log(f"Input STL: {input_file}")
    log(f"Output SCAD: {output_file}")
    
    try:
        # First verify OpenSCAD installation
        log("\nVerifying OpenSCAD installation...")
        try:
            openscad_path = get_openscad_path()
            log(f"OpenSCAD found at: {openscad_path}")
        except Exception as e:
            log(f"Error getting OpenSCAD path: {str(e)}")
            log(f"Exception type: {type(e)}")
            raise
        
        # Run conversion with debug enabled
        log("\nRunning conversion with debug mode...")
        stats = stl2scad(input_file, output_file, debug=True)
        
        # Print conversion statistics
        log("\nConversion Statistics:")
        log(f"Original vertices: {stats.original_vertices}")
        log(f"Deduplicated vertices: {stats.deduplicated_vertices}")
        log(f"Faces: {stats.faces}")
        log("\nMetadata:")
        for key, value in stats.metadata.items():
            log(f"{key}: {value}")
            
        # Verify debug files exist
        debug_dir = os.path.dirname(output_file)
        debug_base = os.path.splitext(output_file)[0]
        debug_files = {
            'scad': f"{debug_base}_debug.scad",
            'json': f"{debug_base}_analysis.json",
            'echo': f"{debug_base}_debug.echo",
            'png': f"{debug_base}_preview.png"
        }
        
        log("\nChecking debug files:")
        all_files_exist = True
        for name, path in debug_files.items():
            exists = os.path.exists(path)
            size = os.path.getsize(path) if exists else 0
            log(f"{name}: {'[OK]' if exists else '[MISSING]'} ({size:,} bytes)")
            if not exists:
                all_files_exist = False
                log(f"Warning: {name} file was not generated at {path}")
            elif size == 0:
                all_files_exist = False
                log(f"Warning: {name} file is empty at {path}")
        
        if all_files_exist:
            log("\nTest completed successfully - all debug files generated!")
            return True
        else:
            log("\nTest completed with warnings - some debug files missing or empty")
            return False
            
    except Exception as e:
        print(f"\nError during testing: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return False

if __name__ == "__main__":
    success = test_debug_features()
    sys.exit(0 if success else 1)