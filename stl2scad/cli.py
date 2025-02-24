"""
Command-line interface for the STL to OpenSCAD converter.

This module provides a command-line interface for converting STL files to OpenSCAD format
and verifying the accuracy of conversions. It supports options for controlling the conversion
process, debugging output, and verification parameters.
"""

import sys
import os
import json
from pathlib import Path
from typing import NoReturn, List, Optional, Dict, Any, Union
from stl2scad.core.converter import stl2scad, ConversionStats, STLValidationError
from stl2scad.core.verification import (
    verify_conversion,
    batch_verify,
    generate_comparison_visualization,
    generate_verification_report_html
)

def usage() -> NoReturn:
    """
    Display usage information and exit.
    
    This function prints the command usage information to stdout and exits
    with status code 1 to indicate improper usage.
    
    Returns:
        NoReturn: This function never returns as it calls sys.exit()
    """
    print("Usage: python3 -m stl2scad <command> [options] <arguments>")
    print("\nCommands:")
    print("  convert <input.stl> <output.scad>  Convert an STL file to OpenSCAD format")
    print("  verify <input.stl> [<output.scad>] Verify conversion accuracy")
    print("  batch <input_dir> <output_dir>     Batch convert and verify multiple files")
    print("\nConvert Options:")
    print("  --tolerance=<float>  Vertex deduplication tolerance (default: 1e-6)")
    print("  --debug              Enable debug mode (renders SCAD to PNG)")
    print("\nVerify Options:")
    print("  --volume-tol=<float>   Volume difference tolerance in percent (default: 1.0)")
    print("  --area-tol=<float>     Surface area difference tolerance in percent (default: 2.0)")
    print("  --bbox-tol=<float>     Bounding box difference tolerance in percent (default: 0.5)")
    print("  --visualize            Generate visualization files")
    print("  --html-report          Generate HTML report with visualizations")
    print("\nExamples:")
    print("  python3 -m stl2scad convert input.stl output.scad --tolerance=0.001")
    print("  python3 -m stl2scad verify input.stl output.scad --volume-tol=2.0 --visualize")
    print("  python3 -m stl2scad batch ./stl_files ./output --html-report")
    sys.exit(1)
    
def parse_convert_args(argv: List[str]) -> tuple[str, str, float, bool]:
    """
    Parse command line arguments for the convert command.
    
    Args:
        argv: List of command line arguments
        
    Returns:
        tuple: (input_file, output_file, tolerance, debug)
        
    Raises:
        ValueError: If tolerance value is invalid
    """
    if len(argv) < 3:
        usage()
    
    input_file = argv[1]
    output_file = argv[2]
    tolerance: float = 1e-6
    debug: bool = False

    # Parse optional arguments
    for arg in argv[3:]:
        if arg.startswith('--tolerance='):
            try:
                tolerance = float(arg.split('=')[1])
                if tolerance <= 0:
                    raise ValueError("Tolerance must be positive")
            except ValueError as e:
                print(f"Error: Invalid tolerance value - {str(e)}", file=sys.stderr)
                sys.exit(1)
        elif arg == '--debug':
            debug = True
        else:
            print(f"Warning: Ignoring unknown argument: {arg}", file=sys.stderr)
    
    return input_file, output_file, tolerance, debug

def parse_verify_args(argv: List[str]) -> tuple[str, Optional[str], Dict[str, float], bool, bool]:
    """
    Parse command line arguments for the verify command.
    
    Args:
        argv: List of command line arguments
        
    Returns:
        tuple: (input_file, output_file, tolerance_dict, visualize, html_report)
        
    Raises:
        ValueError: If tolerance values are invalid
    """
    if len(argv) < 2:
        usage()
    
    input_file = argv[1]
    output_file = argv[2] if len(argv) > 2 and not argv[2].startswith('--') else None
    
    # Default tolerance values
    tolerance = {
        'volume': 1.0,  # 1% volume difference
        'surface_area': 2.0,  # 2% surface area difference
        'bounding_box': 0.5  # 0.5% bounding box dimension difference
    }
    
    visualize = False
    html_report = False
    
    # Parse optional arguments
    args_to_check = argv[2:] if output_file is None else argv[3:]
    for arg in args_to_check:
        if arg.startswith('--volume-tol='):
            try:
                tolerance['volume'] = float(arg.split('=')[1])
                if tolerance['volume'] < 0:
                    raise ValueError("Volume tolerance must be non-negative")
            except ValueError as e:
                print(f"Error: Invalid volume tolerance - {str(e)}", file=sys.stderr)
                sys.exit(1)
        elif arg.startswith('--area-tol='):
            try:
                tolerance['surface_area'] = float(arg.split('=')[1])
                if tolerance['surface_area'] < 0:
                    raise ValueError("Surface area tolerance must be non-negative")
            except ValueError as e:
                print(f"Error: Invalid surface area tolerance - {str(e)}", file=sys.stderr)
                sys.exit(1)
        elif arg.startswith('--bbox-tol='):
            try:
                tolerance['bounding_box'] = float(arg.split('=')[1])
                if tolerance['bounding_box'] < 0:
                    raise ValueError("Bounding box tolerance must be non-negative")
            except ValueError as e:
                print(f"Error: Invalid bounding box tolerance - {str(e)}", file=sys.stderr)
                sys.exit(1)
        elif arg == '--visualize':
            visualize = True
        elif arg == '--html-report':
            html_report = True
            visualize = True  # HTML report requires visualizations
        else:
            print(f"Warning: Ignoring unknown argument: {arg}", file=sys.stderr)
    
    return input_file, output_file, tolerance, visualize, html_report

def parse_batch_args(argv: List[str]) -> tuple[str, str, Dict[str, float], bool]:
    """
    Parse command line arguments for the batch command.
    
    Args:
        argv: List of command line arguments
        
    Returns:
        tuple: (input_dir, output_dir, tolerance_dict, html_report)
        
    Raises:
        ValueError: If tolerance values are invalid
    """
    if len(argv) < 3:
        usage()
    
    input_dir = argv[1]
    output_dir = argv[2]
    
    # Default tolerance values
    tolerance = {
        'volume': 1.0,
        'surface_area': 2.0,
        'bounding_box': 0.5
    }
    
    html_report = False
    
    # Parse optional arguments
    for arg in argv[3:]:
        if arg.startswith('--volume-tol='):
            try:
                tolerance['volume'] = float(arg.split('=')[1])
                if tolerance['volume'] < 0:
                    raise ValueError("Volume tolerance must be non-negative")
            except ValueError as e:
                print(f"Error: Invalid volume tolerance - {str(e)}", file=sys.stderr)
                sys.exit(1)
        elif arg.startswith('--area-tol='):
            try:
                tolerance['surface_area'] = float(arg.split('=')[1])
                if tolerance['surface_area'] < 0:
                    raise ValueError("Surface area tolerance must be non-negative")
            except ValueError as e:
                print(f"Error: Invalid surface area tolerance - {str(e)}", file=sys.stderr)
                sys.exit(1)
        elif arg.startswith('--bbox-tol='):
            try:
                tolerance['bounding_box'] = float(arg.split('=')[1])
                if tolerance['bounding_box'] < 0:
                    raise ValueError("Bounding box tolerance must be non-negative")
            except ValueError as e:
                print(f"Error: Invalid bounding box tolerance - {str(e)}", file=sys.stderr)
                sys.exit(1)
        elif arg == '--html-report':
            html_report = True
        else:
            print(f"Warning: Ignoring unknown argument: {arg}", file=sys.stderr)
    
    return input_dir, output_dir, tolerance, html_report

def print_stats(stats: ConversionStats) -> None:
    """
    Print conversion statistics.
    
    Args:
        stats: Statistics from the conversion process
    """
    reduction = 100 * (1 - stats.deduplicated_vertices/stats.original_vertices)
    print("\nConversion successful:")
    print(f"  Original vertices: {stats.original_vertices:,}")
    print(f"  Optimized vertices: {stats.deduplicated_vertices:,}")
    print(f"  Faces: {stats.faces:,}")
    print(f"  Vertex reduction: {reduction:.1f}%")
    
    if stats.metadata:
        print("\nModel information:")
        for key, value in stats.metadata.items():
            print(f"  {key}: {value}")

def print_verification_result(result: Any) -> None:
    """
    Print verification result.
    
    Args:
        result: Verification result object
    """
    status = "PASSED" if result.passed else "FAILED"
    print(f"\nVerification {status}")
    
    # Print volume comparison
    if 'volume' in result.comparison:
        vol = result.comparison['volume']
        print("\nVolume Comparison:")
        print(f"  STL: {vol['stl']:.2f} mm³")
        print(f"  SCAD: {vol['scad']:.2f} mm³")
        print(f"  Difference: {vol['difference']:.2f} mm³ ({vol['difference_percent']:.2f}%)")
        if abs(vol['difference_percent']) > result.tolerance['volume']:
            print(f"  Status: FAILED (exceeds {result.tolerance['volume']}% tolerance)")
        else:
            print(f"  Status: PASSED (within {result.tolerance['volume']}% tolerance)")
    
    # Print surface area comparison
    if 'surface_area' in result.comparison:
        area = result.comparison['surface_area']
        print("\nSurface Area Comparison:")
        print(f"  STL: {area['stl']:.2f} mm²")
        print(f"  SCAD: {area['scad']:.2f} mm²")
        print(f"  Difference: {area['difference']:.2f} mm² ({area['difference_percent']:.2f}%)")
        if abs(area['difference_percent']) > result.tolerance['surface_area']:
            print(f"  Status: FAILED (exceeds {result.tolerance['surface_area']}% tolerance)")
        else:
            print(f"  Status: PASSED (within {result.tolerance['surface_area']}% tolerance)")
    
    # Print bounding box comparison
    if 'bounding_box' in result.comparison:
        bbox = result.comparison['bounding_box']
        print("\nBounding Box Comparison:")
        for dim in ['width', 'height', 'depth']:
            if dim in bbox:
                dim_data = bbox[dim]
                print(f"  {dim.capitalize()}:")
                print(f"    STL: {dim_data['stl']:.2f} mm")
                print(f"    SCAD: {dim_data['scad']:.2f} mm")
                print(f"    Difference: {dim_data['difference']:.2f} mm ({dim_data['difference_percent']:.2f}%)")
                if abs(dim_data['difference_percent']) > result.tolerance['bounding_box']:
                    print(f"    Status: FAILED (exceeds {result.tolerance['bounding_box']}% tolerance)")
                else:
                    print(f"    Status: PASSED (within {result.tolerance['bounding_box']}% tolerance)")

def convert_command(argv: List[str]) -> int:
    """
    Execute the convert command.
    
    Args:
        argv: Command line arguments
        
    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    try:
        input_file, output_file, tolerance, debug = parse_convert_args(argv)
        
        print(f"Converting {input_file} to {output_file}")
        print(f"Using tolerance: {tolerance}")
        if debug:
            print("Debug mode enabled")
        
        stats = stl2scad(input_file, output_file, tolerance, debug)
        print_stats(stats)
        return 0
        
    except FileNotFoundError as e:
        print(f"Error: File not found - {str(e)}", file=sys.stderr)
        return 1
    except STLValidationError as e:
        print(f"Error: Invalid STL file - {str(e)}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"Error: Permission denied - {str(e)}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        if debug:
            import traceback
            traceback.print_exc()
        return 1

def verify_command(argv: List[str]) -> int:
    """
    Execute the verify command.
    
    Args:
        argv: Command line arguments
        
    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    try:
        input_file, output_file, tolerance, visualize, html_report = parse_verify_args(argv)
        
        print(f"Verifying conversion of {input_file}")
        if output_file:
            print(f"Using existing SCAD file: {output_file}")
        else:
            print("Will generate temporary SCAD file")
        
        print("Tolerance settings:")
        print(f"  Volume: {tolerance['volume']}%")
        print(f"  Surface area: {tolerance['surface_area']}%")
        print(f"  Bounding box: {tolerance['bounding_box']}%")
        
        if visualize:
            print("Visualization enabled")
        if html_report:
            print("HTML report enabled")
        
        # Verify conversion
        result = verify_conversion(input_file, output_file, tolerance, debug=False)
        print_verification_result(result)
        
        # Save verification report
        report_dir = Path(output_file).parent if output_file else Path(input_file).parent
        report_base = Path(input_file).stem
        report_file = report_dir / f"{report_base}_verification.json"
        result.save_report(report_file)
        print(f"\nVerification report saved to: {report_file}")
        
        # Generate visualizations if requested
        if visualize:
            vis_dir = report_dir / f"{report_base}_visualizations"
            vis_dir.mkdir(exist_ok=True, parents=True)
            
            print(f"\nGenerating visualizations in: {vis_dir}")
            scad_file = output_file if output_file else result.scad_file
            visualizations = generate_comparison_visualization(
                input_file,
                scad_file,
                vis_dir
            )
            
            print(f"Generated {len(visualizations)} visualization files")
            
            # Generate HTML report if requested
            if html_report:
                html_file = report_dir / f"{report_base}_verification.html"
                generate_verification_report_html(
                    vars(result),
                    visualizations,
                    html_file
                )
                print(f"\nHTML report saved to: {html_file}")
        
        return 0 if result.passed else 2  # Return 2 for verification failure
        
    except FileNotFoundError as e:
        print(f"Error: File not found - {str(e)}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

def batch_command(argv: List[str]) -> int:
    """
    Execute the batch command.
    
    Args:
        argv: Command line arguments
        
    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    try:
        input_dir, output_dir, tolerance, html_report = parse_batch_args(argv)
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        if not input_path.exists() or not input_path.is_dir():
            print(f"Error: Input directory not found: {input_dir}", file=sys.stderr)
            return 1
        
        # Create output directory if it doesn't exist
        output_path.mkdir(exist_ok=True, parents=True)
        
        # Find all STL files in input directory
        stl_files = list(input_path.glob("**/*.stl"))
        
        if not stl_files:
            print(f"Error: No STL files found in {input_dir}", file=sys.stderr)
            return 1
        
        print(f"Found {len(stl_files)} STL files in {input_dir}")
        print(f"Output directory: {output_dir}")
        print("Tolerance settings:")
        print(f"  Volume: {tolerance['volume']}%")
        print(f"  Surface area: {tolerance['surface_area']}%")
        print(f"  Bounding box: {tolerance['bounding_box']}%")
        
        if html_report:
            print("HTML reports will be generated")
        
        # Process each STL file
        results = {}
        for stl_file in stl_files:
            # Determine output path (preserving directory structure)
            rel_path = stl_file.relative_to(input_path)
            scad_file = output_path / rel_path.with_suffix('.scad')
            report_file = output_path / rel_path.with_suffix('.verification.json')
            
            # Create parent directories if needed
            scad_file.parent.mkdir(exist_ok=True, parents=True)
            
            print(f"\nProcessing: {stl_file}")
            print(f"Output: {scad_file}")
            
            try:
                # Convert STL to SCAD
                stats = stl2scad(str(stl_file), str(scad_file))
                
                # Verify conversion
                result = verify_conversion(stl_file, scad_file, tolerance, debug=False)
                result.save_report(report_file)
                
                # Generate visualizations if HTML report is enabled
                if html_report:
                    vis_dir = output_path / rel_path.with_suffix('.visualizations')
                    vis_dir.mkdir(exist_ok=True, parents=True)
                    
                    visualizations = generate_comparison_visualization(
                        stl_file,
                        scad_file,
                        vis_dir
                    )
                    
                    # Generate HTML report
                    html_file = output_path / rel_path.with_suffix('.verification.html')
                    generate_verification_report_html(
                        vars(result),
                        visualizations,
                        html_file
                    )
                
                # Store result
                results[str(rel_path)] = {
                    'passed': result.passed,
                    'report': str(report_file)
                }
                
                # Print brief result
                status = "PASSED" if result.passed else "FAILED"
                print(f"Verification: {status}")
                
            except Exception as e:
                print(f"Error processing {stl_file}: {str(e)}", file=sys.stderr)
                results[str(rel_path)] = {
                    'passed': False,
                    'error': str(e)
                }
        
        # Create summary report
        summary = {
            'total': len(results),
            'passed': sum(1 for r in results.values() if r.get('passed', False)),
            'failed': sum(1 for r in results.values() if not r.get('passed', False)),
            'results': results
        }
        
        summary_file = output_path / "batch_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\nBatch processing complete:")
        print(f"  Total files: {summary['total']}")
        print(f"  Passed: {summary['passed']}")
        print(f"  Failed: {summary['failed']}")
        print(f"Summary report saved to: {summary_file}")
        
        return 0 if summary['failed'] == 0 else 2  # Return 2 if any verification failed
        
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

def main() -> int:
    """
    Main entry point for the command-line interface.
    
    Returns:
        int: Exit code (0 for success, 1 for error, 2 for verification failure)
    """
    if len(sys.argv) < 2:
        usage()
    
    command = sys.argv[1]
    
    if command == 'convert':
        return convert_command(sys.argv[2:])
    elif command == 'verify':
        return verify_command(sys.argv[2:])
    elif command == 'batch':
        return batch_command(sys.argv[2:])
    else:
        print(f"Error: Unknown command: {command}", file=sys.stderr)
        usage()

if __name__ == "__main__":
    sys.exit(main())
