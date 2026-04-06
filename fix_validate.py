import sys
import re
import numpy as np

file_path = "stl2scad/core/converter.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

pattern = re.compile(r'def validate_stl\(mesh: stl\.mesh\.Mesh\) -> None:.*?def find_unique_vertices', re.DOTALL)

replacement = '''def validate_stl(mesh: stl.mesh.Mesh, tolerance: float = 1e-6) -> None:
    """
    Validate STL mesh integrity.

    Args:
        mesh: The STL mesh to validate
        tolerance: Grid cell size for vertex snapping

    Raises:
        STLValidationError: If validation fails
    """
    if len(mesh.points) == 0:
        raise STLValidationError("Empty STL file")

    # Check for non-manifold edges using integer grids to avoid float fragility
    scale = 1.0 / tolerance
    quantized_vectors = np.round(mesh.vectors * scale).astype(np.int64)

    edges: Dict[Tuple[Tuple[int, int, int], Tuple[int, int, int]], List[int]] = {}
    for i, face in enumerate(quantized_vectors):
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

def find_unique_vertices'''

new_content, count = pattern.subn(replacement, content)
if count > 0:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("SUCCESS")
else:
    print("NOT FOUND")
