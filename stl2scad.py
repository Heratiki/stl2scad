import sys
import os
import numpy as np
import stl
import logging
from typing import Tuple, List, Dict
from dataclasses import dataclass

logging.basicConfig(filename='stl2scad.log', level=logging.DEBUG)

@dataclass
class ConversionStats:
    original_vertices: int
    deduplicated_vertices: int
    faces: int
    metadata: Dict[str, str]

class STLValidationError(Exception):
    pass

def validate_stl(mesh: stl.mesh.Mesh) -> None:
    """Validate STL mesh integrity."""
    if len(mesh.points) == 0:
        raise STLValidationError("Empty STL file")
    
    # Check for non-manifold edges
    edges = {}
    for i, face in enumerate(mesh.vectors):
        for j in range(3):
            edge = tuple(sorted([
                tuple(face[j]), 
                tuple(face[(j + 1) % 3])
            ]))
            if edge in edges:
                edges[edge].append(i)
            else:
                edges[edge] = [i]
    
    non_manifold = [e for e, faces in edges.items() if len(faces) > 2]
    if non_manifold:
        raise STLValidationError(f"Non-manifold edges found: {len(non_manifold)} edges")

def find_unique_vertices(points: np.ndarray, tolerance: float = 1e-6) -> Tuple[np.ndarray, Dict[int, int]]:
    """Deduplicate vertices within given tolerance."""
    unique_vertices = []
    vertex_map = {}
    
    for i, vertex in enumerate(points):
        found = False
        for j, unique in enumerate(unique_vertices):
            if np.allclose(vertex, unique, rtol=tolerance):
                vertex_map[i] = j
                found = True
                break
        if not found:
            vertex_map[i] = len(unique_vertices)
            unique_vertices.append(vertex)
    
    return np.array(unique_vertices), vertex_map

def optimize_scad(points: np.ndarray, faces: List[List[int]]) -> Tuple[np.ndarray, List[List[int]]]:
    """Optimize SCAD output for better performance."""
    # Remove unused vertices
    used_vertices = set()
    for face in faces:
        used_vertices.update(face)
    
    vertex_map = {}
    new_points = []
    for i, vertex in enumerate(points):
        if i in used_vertices:
            vertex_map[i] = len(new_points)
            new_points.append(vertex)
    
    # Remap faces to new vertex indices
    new_faces = [[vertex_map[v] for v in face] for face in faces]
    
    return np.array(new_points), new_faces

def extract_metadata(mesh: stl.mesh.Mesh) -> Dict[str, str]:
    """Extract metadata from STL file."""
    metadata = {}
    if hasattr(mesh, 'name') and mesh.name:
        metadata['name'] = mesh.name.decode('utf-8').strip()
    metadata['volume'] = str(mesh.get_mass_properties()[0])
    metadata['bbox'] = str(tuple(zip(mesh.min_, mesh.max_)))
    return metadata

def stl2scad(input_file: str, output_file: str, tolerance: float = 1e-6) -> ConversionStats:
    """Convert STL to SCAD with improved handling and optimization."""
    logging.debug('Input file: %s', input_file)
    logging.debug('Output file: %s', output_file)

    try:
        stl_mesh = stl.mesh.Mesh.from_file(input_file)
        validate_stl(stl_mesh)
    except Exception as e:
        logging.error('Failed to load or validate STL: %s', str(e))
        raise

    # Extract metadata before processing
    metadata = extract_metadata(stl_mesh)
    original_vertex_count = len(stl_mesh.points.reshape(-1, 3))

    # Deduplicate vertices
    points = stl_mesh.points.reshape(-1, 3)
    unique_points, vertex_map = find_unique_vertices(points, tolerance)
    
    # Create faces using mapped vertices
    faces = []
    for i in range(0, len(points), 3):
        face = [vertex_map[i], vertex_map[i+1], vertex_map[i+2]]
        faces.append(face)

    # Optimize SCAD output
    final_points, final_faces = optimize_scad(unique_points, faces)

    # Write SCAD file with metadata as comments
    with open(output_file, "w") as f:
        # Write metadata as comments
        f.write("// STL to SCAD Conversion\n")
        for key, value in metadata.items():
            f.write(f"// {key}: {value}\n")
        f.write("\n")

        # Write the polyhedron
        f.write("polyhedron(\n")
        f.write("  points=[\n")
        for vertex in final_points:
            f.write(f"    [{vertex[0]:.6f}, {vertex[1]:.6f}, {vertex[2]:.6f}],\n")
        f.write("  ],\n")

        f.write("  faces=[\n")
        for face in final_faces:
            f.write(f"    [{face[0]}, {face[1]}, {face[2]}],\n")
        f.write("  ],\n")
        f.write("  convexity=10\n")  # Improved rendering
        f.write(");\n")

    return ConversionStats(
        original_vertices=original_vertex_count,
        deduplicated_vertices=len(final_points),
        faces=len(final_faces),
        metadata=metadata
    )

def usage():
    print("Usage: python3 stl2scad.py <input.stl> <output.scad>")
    print("Converts an STL file to an OpenSCAD file with optimization and validation.")
    print("Options:")
    print("  --tolerance=<float>  Vertex deduplication tolerance (default: 1e-6)")
    
def main():
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
