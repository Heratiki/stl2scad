"""
Tests for visualization and analysis features.
"""

import pytest
import json
from pathlib import Path
from stl2scad.core.converter import get_openscad_path, run_openscad
from .utils import setup_logging, verify_debug_files

def test_preview_generation(sample_stl_file, test_output_dir):
    """Test generation of preview images."""
    log = setup_logging()
    log("\nTesting Preview Generation")
    
    openscad_path = get_openscad_path()
    output_file = test_output_dir / "preview_test.scad"
    
    # Write test SCAD file that imports the STL
    output_file.write_text(f'''
    // Preview test
    import("{sample_stl_file}");
    ''')
    
    # Test different preview options
    preview_configs = [
        {
            'name': 'basic',
            'args': ['--preview=throwntogether']
        },
        {
            'name': 'detailed',
            'args': ['--render']
        },
        {
            'name': 'debug',
            'args': [
                '--preview=throwntogether',
                '--view=axes,edges,scales',
                '--autocenter',
                '--viewall'
            ]
        }
    ]
    
    for config in preview_configs:
        log(f"\nTesting {config['name']} preview")
        output_png = test_output_dir / f"preview_{config['name']}.png"
        
        args = config['args'] + [
            '-o', str(output_png),
            str(output_file)
        ]
        
        result = run_openscad(
            f"{config['name']} preview",
            args,
            str(test_output_dir / f"{config['name']}_preview.log"),
            openscad_path
        )
        
        if result:
            log(f"{config['name']} preview generated successfully")
            assert output_png.exists(), f"{config['name']} PNG not created"
            assert output_png.stat().st_size > 0, f"{config['name']} PNG is empty"
        else:
            log(f"Warning: {config['name']} preview generation failed", "WARNING")

def test_analysis_generation(sample_stl_file, test_output_dir):
    """Test generation of analysis data."""
    log = setup_logging()
    log("\nTesting Analysis Generation")
    
    openscad_path = get_openscad_path()
    output_file = test_output_dir / "analysis_test.scad"
    
    # Write test SCAD file
    output_file.write_text(f'''
    // Analysis test
    import("{sample_stl_file}");
    echo("Starting analysis...");
    ''')
    
    # Test different analysis options
    analysis_configs = [
        {
            'name': 'basic',
            'args': ['--render']
        },
        {
            'name': 'detailed',
            'args': [
                '--render',
                '--summary=all'
            ]
        }
    ]
    
    for config in analysis_configs:
        log(f"\nTesting {config['name']} analysis")
        output_json = test_output_dir / f"analysis_{config['name']}.json"
        
        args = config['args'] + [
            '--export-format', 'json',
            '-o', str(output_json),
            str(output_file)
        ]
        
        result = run_openscad(
            f"{config['name']} analysis",
            args,
            str(test_output_dir / f"{config['name']}_analysis.log"),
            openscad_path
        )
        
        if result:
            log(f"{config['name']} analysis generated successfully")
            assert output_json.exists(), f"{config['name']} JSON not created"
            assert output_json.stat().st_size > 0, f"{config['name']} JSON is empty"
            
            # Verify JSON content
            try:
                with open(output_json) as f:
                    data = json.load(f)
                log(f"Successfully parsed {config['name']} JSON")
            except json.JSONDecodeError as e:
                log(f"Error parsing {config['name']} JSON: {e}", "ERROR")
                raise
        else:
            log(f"Warning: {config['name']} analysis generation failed", "WARNING")

def test_measurement_tools(test_output_dir):
    """Test measurement tool generation."""
    log = setup_logging()
    log("\nTesting Measurement Tools")
    
    output_file = test_output_dir / "measurement_test.scad"
    
    # Write test SCAD file with measurement tools
    output_file.write_text('''
    // Measurement tools test
    module show_bbox(points) {
        min_point = [min([for (p = points) p[0]]), min([for (p = points) p[1]]), min([for (p = points) p[2]])];
        max_point = [max([for (p = points) p[0]]), max([for (p = points) p[1]]), max([for (p = points) p[2]])];
        translate(min_point)
            %cube(max_point - min_point);
    }
    
    module dimension_line(start, end, offset=5) {
        vector = end - start;
        length = norm(vector);
        translate(start)
            rotate([0, 0, atan2(vector[1], vector[0])])
                union() {
                    cylinder(h=length, r=0.5, center=false);
                    translate([0, offset, 0])
                        text(str(length), size=5);
                }
    }
    
    // Test object
    cube(20);
    
    // Show measurements
    points = [[0,0,0], [20,0,0], [20,20,0], [0,20,0]];
    show_bbox(points);
    dimension_line([0,0,0], [20,0,0]);
    ''')
    
    # Generate preview with measurements
    openscad_path = get_openscad_path()
    output_png = test_output_dir / "measurement_preview.png"
    
    result = run_openscad(
        "Measurement preview",
        [
            '--preview=throwntogether',
            '--view=axes',
            '--autocenter',
            '--viewall',
            '-o', str(output_png),
            str(output_file)
        ],
        str(test_output_dir / "measurement.log"),
        openscad_path
    )
    
    if result:
        log("Measurement preview generated successfully")
        assert output_png.exists(), "Measurement PNG not created"
        assert output_png.stat().st_size > 0, "Measurement PNG is empty"
    else:
        log("Warning: Measurement preview generation failed", "WARNING")