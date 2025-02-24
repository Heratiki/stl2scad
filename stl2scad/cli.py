"""
Command-line interface for the STL to OpenSCAD converter.

This module provides a command-line interface for converting STL files to OpenSCAD format.
It supports options for controlling the conversion process and debugging output.
"""

import sys
from typing import NoReturn, List, Optional
from stl2scad.core.converter import stl2scad, ConversionStats, STLValidationError

def usage() -> NoReturn:
    """
    Display usage information and exit.
    
    This function prints the command usage information to stdout and exits
    with status code 1 to indicate improper usage.
    
    Returns:
        NoReturn: This function never returns as it calls sys.exit()
    """
    print("Usage: python3 -m stl2scad <input.stl> <output.scad>")
    print("Converts an STL file to an OpenSCAD file with optimization and validation.")
    print("\nOptions:")
    print("  --tolerance=<float>  Vertex deduplication tolerance (default: 1e-6)")
    print("  --debug             Enable debug mode (renders SCAD to PNG)")
    sys.exit(1)
    
def parse_args(argv: List[str]) -> tuple[str, str, float, bool]:
    """
    Parse command line arguments.
    
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

def main() -> int:
    """
    Main entry point for the command-line interface.
    
    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    try:
        input_file, output_file, tolerance, debug = parse_args(sys.argv)
        
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

if __name__ == "__main__":
    sys.exit(main())
