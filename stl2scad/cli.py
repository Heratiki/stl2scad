"""
Command-line interface for the STL to OpenSCAD converter.
"""

import sys
from stl2scad.core.converter import stl2scad

def usage():
    """Display usage information."""
    print("Usage: python3 -m stl2scad <input.stl> <output.scad>")
    print("Converts an STL file to an OpenSCAD file with optimization and validation.")
    print("Options:")
    print("  --tolerance=<float>  Vertex deduplication tolerance (default: 1e-6)")
    
def main():
    """Main entry point for the command-line interface."""
    if len(sys.argv) < 3:
        usage()
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    tolerance = 1e-6

    # Parse optional arguments
    for arg in sys.argv[3:]:
        if arg.startswith('--tolerance='):
            tolerance = float(arg.split('=')[1])
    
    try:
        stats = stl2scad(input_file, output_file, tolerance)
        print(f"Conversion successful:")
        print(f"  Original vertices: {stats.original_vertices}")
        print(f"  Optimized vertices: {stats.deduplicated_vertices}")
        print(f"  Faces: {stats.faces}")
        print(f"  Vertex reduction: {100 * (1 - stats.deduplicated_vertices/stats.original_vertices):.1f}%")
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
