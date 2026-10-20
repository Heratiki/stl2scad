"""
STL to SCAD conversion entry point (segmentation pipeline).

T-004 made segmentation the only live conversion path. The CLI (convert,
verify, batch), the GUI and verification all convert through
convert_stl_to_scad(). The legacy whole-mesh pipeline is archived in
stl2scad/legacy/ and is not reachable from here.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Union

import numpy as np
import stl

FALLBACK_MARKER = "// Full mesh fallback:"


@dataclass
class ConversionStats:
    """Statistics about the conversion process."""

    original_vertices: int
    deduplicated_vertices: int
    faces: int
    metadata: Dict[str, str]


class STLValidationError(Exception):
    """Raised when STL file validation fails."""

    pass


def validate_stl(mesh: stl.mesh.Mesh, tolerance: float = 1e-6) -> None:
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
        if len(set(tuple(p) for p in face)) < 3:
            continue
        for j in range(3):
            edge: Tuple[Tuple[int, int, int], Tuple[int, int, int]] = tuple(  # type: ignore[assignment]
                sorted([tuple(face[j]), tuple(face[(j + 1) % 3])])
            )
            if edge in edges:
                edges[edge].append(i)
            else:
                edges[edge] = [i]

    non_manifold = [e for e, faces in edges.items() if len(faces) > 2]
    if non_manifold:
        raise STLValidationError(f"Non-manifold edges found: {len(non_manifold)} edges")


def _fallback_reason(source: str) -> str:
    for line in source.splitlines():
        if line.startswith(FALLBACK_MARKER):
            return line[len(FALLBACK_MARKER):].strip()
    return ""


def convert_stl_to_scad(
    input_file: Union[str, Path], output_file: Union[str, Path]
) -> ConversionStats:
    """Convert one STL file to SCAD through the segmentation pipeline.

    The segmentation emitter either writes a parametric model that passed its
    Hausdorff gate or the whole input mesh as a polyhedron; it never raises
    for unsupported geometry. The output file holds exactly the emitter's text.

    Args:
        input_file: Path to the input STL file
        output_file: Path to the output SCAD file

    Returns:
        ConversionStats: triangle/vertex counts and the pipeline outcome

    Raises:
        STLValidationError: If the STL file holds no triangles
        FileNotFoundError: If the input file does not exist
    """
    # Imported here so callers can patch stl2scad.core.segmentation.emit_scad
    # and so importing this module does not pull in the segmentation stack.
    from stl2scad.core import segmentation

    input_name = str(input_file)
    if not Path(input_name).exists():
        raise FileNotFoundError(input_name)
    mesh = stl.mesh.Mesh.from_file(input_name)
    if len(mesh.vectors) == 0:
        raise STLValidationError("Empty STL file")

    source = segmentation.emit_scad(None, mesh, source_file=input_name)
    Path(output_file).write_text(source)

    vertices = mesh.vectors.reshape(-1, 3)
    unique_vertices = int(np.unique(vertices, axis=0).shape[0])
    reason = _fallback_reason(source)
    metadata: Dict[str, str] = {
        "pipeline": "segmentation",
        "segmentation_output": "polyhedron_fallback" if reason else "parametric",
    }
    if reason:
        metadata["segmentation_fallback_reason"] = reason
    logging.debug("Segmentation conversion of %s: %s", input_name, metadata)
    return ConversionStats(
        original_vertices=int(vertices.shape[0]),
        deduplicated_vertices=unique_vertices,
        faces=int(len(mesh.vectors)),
        metadata=metadata,
    )
