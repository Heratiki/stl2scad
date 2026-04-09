"""
Primitive recognition backend abstraction.

Phase 0 establishes backend routing so additional engines can be added without
changing conversion call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import logging
import math
from typing import Optional, Tuple

import numpy as np
import stl

from .cgal_backend import detect_primitive_with_cgal, is_cgal_backend_available

SUPPORTED_RECOGNITION_BACKENDS = ("native", "trimesh_manifold", "cgal")


@dataclass
class _ComponentMesh:
    vertices: np.ndarray
    faces: np.ndarray


@dataclass
class _PrimitiveCandidate:
    shape: str
    scad: str
    confidence: float


def normalize_recognition_backend(backend: Optional[str]) -> str:
    """
    Normalize a backend name/alias to a supported backend id.

    Supported ids:
    - native
    - trimesh_manifold
    - cgal
    """
    if backend is None:
        return "native"

    normalized = backend.strip().lower().replace("-", "_")
    aliases = {
        "default": "native",
        "native": "native",
        "trimesh": "trimesh_manifold",
        "manifold": "trimesh_manifold",
        "trimesh_manifold": "trimesh_manifold",
        "cgal": "cgal",
    }

    resolved = aliases.get(normalized)
    if resolved is None:
        raise ValueError(
            f"Unsupported recognition backend '{backend}'. "
            f"Supported backends: {', '.join(SUPPORTED_RECOGNITION_BACKENDS)}"
        )
    return resolved


def get_available_recognition_backends() -> list[str]:
    """Return recognition backends currently available in the environment."""
    available = ["native"]
    if _has_trimesh_manifold_dependencies():
        available.append("trimesh_manifold")
    if _has_cgal_dependencies():
        available.append("cgal")
    return available


def detect_primitive(
    mesh: stl.mesh.Mesh,
    tolerance: float = 0.01,
    backend: str = "native",
) -> Optional[str]:
    """
    Try primitive recognition using the requested backend.

    Returns an OpenSCAD snippet when a primitive is confidently recognized,
    otherwise returns None so the caller can use safe polyhedron fallback.
    """
    selected_backend = normalize_recognition_backend(backend)

    if selected_backend == "native":
        return _detect_primitive_native(mesh, tolerance)

    if selected_backend == "trimesh_manifold":
        if not _has_trimesh_manifold_dependencies():
            logging.info(
                "Recognition backend 'trimesh_manifold' requested but optional "
                "dependencies are unavailable; falling back to polyhedron output."
            )
            return None
        return _detect_primitive_trimesh_manifold(mesh, tolerance)

    if selected_backend == "cgal":
        if not _has_cgal_dependencies():
            logging.info(
                "Recognition backend 'cgal' requested but optional dependencies "
                "are unavailable; falling back to polyhedron output."
            )
            return None
        return _detect_primitive_cgal(mesh, tolerance)

    # Defensive fallback if future edits bypass validation.
    raise ValueError(f"Unhandled recognition backend '{selected_backend}'")


def _detect_primitive_native(
    mesh: stl.mesh.Mesh, tolerance: float = 0.01
) -> Optional[str]:
    """Current native primitive detector (axis-aligned box/cube)."""
    min_coords = [float(x) for x in mesh.min_]
    max_coords = [float(x) for x in mesh.max_]
    width = max_coords[0] - min_coords[0]
    height = max_coords[1] - min_coords[1]
    depth = max_coords[2] - min_coords[2]

    bbox_volume = width * height * depth
    mesh_volume = float(mesh.get_mass_properties()[0])

    if bbox_volume <= 0:
        return None

    vol_diff_ratio = abs(mesh_volume - bbox_volume) / bbox_volume
    if vol_diff_ratio > tolerance:
        return None

    return (
        f"translate([{min_coords[0]:.6f}, {min_coords[1]:.6f}, {min_coords[2]:.6f}]) "
        "{\n"
        f"    cube([{width:.6f}, {height:.6f}, {depth:.6f}]);\n"
        "}\n"
    )


def _detect_primitive_trimesh_manifold(
    mesh: stl.mesh.Mesh, tolerance: float = 0.01
) -> Optional[str]:
    """
    Phase 1 implementation:
    - preprocess and split into connected components
    - attempt primitive fitting (sphere, cone/frustum, cylinder, box)
    - emit union() for multi-component success
    """
    components = _preprocess_components(mesh)
    if not components:
        return _detect_primitive_native(mesh, tolerance)

    # Reject overlapping/nested component layouts (e.g. shell-like subtraction
    # surfaces). Current Phase 1 assembly supports only disjoint unions.
    if len(components) > 1 and _components_have_overlapping_bboxes(components):
        return None

    snippets: list[str] = []
    for component in components:
        candidate = _detect_component_primitive(component, tolerance)
        if candidate is None:
            return None
        snippets.append(candidate.scad.strip())

    if len(snippets) == 1:
        return snippets[0] + "\n"

    body = "\n".join(f"    {snippet}" for snippet in snippets)
    return "union() {\n" + body + "\n}\n"


def _detect_primitive_cgal(
    mesh: stl.mesh.Mesh, tolerance: float = 0.01
) -> Optional[str]:
    """
    Phase 2 skeleton:
    - call CGAL helper boundary when available
    - fallback to Phase 1 trimesh pipeline if CGAL backend declines detection
    """
    cgal_result = detect_primitive_with_cgal(mesh, tolerance=tolerance)
    if cgal_result and cgal_result.detected and cgal_result.scad:
        return cgal_result.scad.strip() + "\n"

    if _has_trimesh_manifold_dependencies():
        return _detect_primitive_trimesh_manifold(mesh, tolerance)

    return None


def _has_trimesh_manifold_dependencies() -> bool:
    # Phase 1 uses trimesh as the core optional dependency. manifold/manifold3d
    # remains optional for future boolean-heavy processing stages.
    return _has_module("trimesh")


def _has_cgal_dependencies() -> bool:
    """
    CGAL integration strategy is not finalized yet.

    We keep this explicit gate so Phase 2 can plug in either Python bindings or
    helper executable checks without touching call sites.
    """
    return is_cgal_backend_available()


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _preprocess_components(mesh: stl.mesh.Mesh) -> list[_ComponentMesh]:
    vertices, faces = _extract_vertices_and_faces(mesh)
    if len(faces) == 0:
        return []

    vertices, faces = _run_optional_trimesh_cleanup(vertices, faces)
    if len(faces) == 0:
        return []

    components = _split_connected_components(vertices, faces)
    components.sort(key=lambda c: len(c.faces), reverse=True)
    return components


def _extract_vertices_and_faces(
    mesh: stl.mesh.Mesh,
    dedup_tolerance: float = 1e-6,
) -> Tuple[np.ndarray, np.ndarray]:
    triangles = np.asarray(mesh.vectors, dtype=np.float64)
    if triangles.size == 0:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int32)

    flat_points = triangles.reshape(-1, 3)
    scale = 1.0 / max(dedup_tolerance, 1e-12)
    quantized = np.round(flat_points * scale).astype(np.int64)
    _, first_idx, inverse = np.unique(
        quantized, axis=0, return_index=True, return_inverse=True
    )

    vertices = flat_points[first_idx]
    faces = inverse.reshape(-1, 3).astype(np.int32)
    valid = np.array(
        [len({int(face[0]), int(face[1]), int(face[2])}) == 3 for face in faces],
        dtype=bool,
    )
    return vertices, faces[valid]


def _run_optional_trimesh_cleanup(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    try:
        import trimesh  # type: ignore
    except Exception:
        return vertices, faces

    try:
        tri = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        tri.remove_degenerate_faces()
        tri.remove_duplicate_faces()
        tri.remove_unreferenced_vertices()
        if not tri.is_watertight:
            tri.fill_holes()
        tri.fix_normals(multibody=True)

        cleaned_vertices = np.asarray(tri.vertices, dtype=np.float64)
        cleaned_faces = np.asarray(tri.faces, dtype=np.int32)
        if cleaned_vertices.size == 0 or cleaned_faces.size == 0:
            return vertices, faces
        return cleaned_vertices, cleaned_faces
    except Exception:
        logging.debug(
            "Optional trimesh cleanup failed; continuing with raw mesh data.",
            exc_info=True,
        )
        return vertices, faces


def _split_connected_components(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> list[_ComponentMesh]:
    if len(faces) == 0:
        return []

    vertex_to_faces: list[list[int]] = [[] for _ in range(len(vertices))]
    for face_idx, face in enumerate(faces):
        for vertex_idx in set(int(v) for v in face):
            vertex_to_faces[vertex_idx].append(face_idx)

    visited = np.zeros(len(faces), dtype=bool)
    components: list[_ComponentMesh] = []
    for start_face in range(len(faces)):
        if visited[start_face]:
            continue

        stack = [start_face]
        face_indices: list[int] = []
        visited[start_face] = True

        while stack:
            current = stack.pop()
            face_indices.append(current)
            for vertex_idx in faces[current]:
                for neighbor_face in vertex_to_faces[int(vertex_idx)]:
                    if not visited[neighbor_face]:
                        visited[neighbor_face] = True
                        stack.append(neighbor_face)

        component_faces = faces[np.asarray(face_indices, dtype=np.int32)]
        used_vertices = np.unique(component_faces.reshape(-1))
        remap = {int(old): new for new, old in enumerate(used_vertices)}
        remapped_faces = np.vectorize(lambda idx: remap[int(idx)])(component_faces)
        component_vertices = vertices[used_vertices]

        components.append(
            _ComponentMesh(
                vertices=np.asarray(component_vertices, dtype=np.float64),
                faces=np.asarray(remapped_faces, dtype=np.int32),
            )
        )

    return components


def _detect_component_primitive(
    component: _ComponentMesh,
    tolerance: float,
) -> Optional[_PrimitiveCandidate]:
    points = component.vertices
    if len(points) < 8:
        return None

    candidates = [
        _fit_sphere_candidate(points, tolerance),
        _fit_cone_candidate(points, tolerance),
        _fit_cylinder_candidate(points, tolerance),
        _fit_axis_aligned_box_candidate(points, component.faces, tolerance),
    ]
    valid = [candidate for candidate in candidates if candidate is not None]
    if not valid:
        return None

    valid.sort(
        key=lambda item: (item.confidence, _shape_priority(item.shape)),
        reverse=True,
    )
    best = valid[0]
    if best.confidence < 0.5:
        return None
    return best


def _fit_sphere_candidate(
    points: np.ndarray, tolerance: float
) -> Optional[_PrimitiveCandidate]:
    if len(points) < 12:
        return None

    covariance = np.cov((points - np.mean(points, axis=0)), rowvar=False)
    eigvals = np.sort(np.linalg.eigvalsh(covariance))
    if float(eigvals[-1]) <= 1e-12:
        return None
    isotropy = float(eigvals[0] / eigvals[-1])
    if isotropy < 0.5:
        return None

    a_matrix = np.column_stack((2.0 * points, np.ones(len(points))))
    b_vector = np.sum(points * points, axis=1)
    try:
        solution, *_ = np.linalg.lstsq(a_matrix, b_vector, rcond=None)
    except np.linalg.LinAlgError:
        return None

    center = solution[:3]
    radius_sq = float(np.dot(center, center) + solution[3])
    if radius_sq <= 1e-12:
        return None
    radius = math.sqrt(radius_sq)

    distances = np.linalg.norm(points - center, axis=1)
    rel_error = np.abs(distances - radius) / max(radius, 1e-9)
    err_p95 = float(np.percentile(rel_error, 95))
    err_mean = float(np.mean(rel_error))

    err_cap = max(0.04, tolerance * 4.0)
    if err_p95 > err_cap or err_mean > err_cap * 0.6:
        return None

    confidence = max(0.0, 1.0 - (err_p95 / err_cap)) * min(1.0, isotropy)
    scad = (
        f"translate([{center[0]:.6f}, {center[1]:.6f}, {center[2]:.6f}]) "
        f"sphere(r={radius:.6f}, $fn=96);"
    )
    return _PrimitiveCandidate("sphere", scad, confidence)


def _fit_cylinder_candidate(
    points: np.ndarray, tolerance: float
) -> Optional[_PrimitiveCandidate]:
    best: Optional[_PrimitiveCandidate] = None
    err_cap = max(0.08, tolerance * 8.0)

    for axis in _pca_axes(points):
        centroid, t_values, radial = _project_points_to_axis(points, axis)
        height = float(np.max(t_values) - np.min(t_values))
        radius = float(np.median(radial))
        if height <= 1e-6 or radius <= 1e-6:
            continue

        radial_rel_error = np.abs(radial - radius) / radius
        err_p95 = float(np.percentile(radial_rel_error, 95))
        corr = abs(_safe_correlation(t_values, radial))
        shape_ratio = height / (2.0 * radius)

        cap_band = max(0.04 * height, 0.05 * radius)
        near_min = float(np.mean(t_values <= (np.min(t_values) + cap_band)))
        near_max = float(np.mean(t_values >= (np.max(t_values) - cap_band)))

        if err_p95 > err_cap:
            continue
        if corr > 0.22:
            continue
        if shape_ratio < 0.4:
            continue
        if near_min < 0.01 or near_max < 0.01:
            continue

        center = centroid + axis * (
            (float(np.min(t_values)) + float(np.max(t_values))) * 0.5
        )
        primitive = f"cylinder(h={height:.6f}, r={radius:.6f}, center=true, $fn=96);"
        scad = _wrap_oriented_primitive(center, axis, primitive)
        confidence = max(0.0, 1.0 - (err_p95 / err_cap))
        candidate = _PrimitiveCandidate("cylinder", scad, confidence)
        if best is None or candidate.confidence > best.confidence:
            best = candidate

    return best


def _fit_cone_candidate(
    points: np.ndarray, tolerance: float
) -> Optional[_PrimitiveCandidate]:
    best: Optional[_PrimitiveCandidate] = None
    err_cap = max(0.12, tolerance * 10.0)

    for axis in _pca_axes(points):
        centroid, t_values, radial = _project_points_to_axis(points, axis)
        height = float(np.max(t_values) - np.min(t_values))
        if height <= 1e-6:
            continue

        try:
            slope, intercept = np.polyfit(t_values, radial, 1)
        except np.linalg.LinAlgError:
            continue

        predicted = slope * t_values + intercept
        range_scale = max(float(np.max(predicted) - np.min(predicted)), 1e-6)
        rel_error = np.abs(radial - predicted) / range_scale
        err_p95 = float(np.percentile(rel_error, 95))
        corr = abs(_safe_correlation(t_values, radial))

        t_min = float(np.min(t_values))
        t_max = float(np.max(t_values))
        radius_start = max(float(slope * t_min + intercept), 0.0)
        radius_end = max(float(slope * t_max + intercept), 0.0)
        max_radius = max(radius_start, radius_end)
        min_radius = min(radius_start, radius_end)

        if err_p95 > err_cap:
            continue
        if corr < 0.2:
            continue
        if max_radius <= 1e-6:
            continue
        if abs(radius_end - radius_start) < (0.2 * max_radius):
            continue
        if min_radius / max_radius > 0.75:
            continue

        center = centroid + axis * ((t_min + t_max) * 0.5)
        primitive = (
            f"cylinder(h={height:.6f}, r1={radius_start:.6f}, "
            f"r2={radius_end:.6f}, center=true, $fn=96);"
        )
        scad = _wrap_oriented_primitive(center, axis, primitive)
        confidence = max(0.0, 1.0 - (err_p95 / err_cap))
        candidate = _PrimitiveCandidate("cone", scad, confidence)
        if best is None or candidate.confidence > best.confidence:
            best = candidate

    return best


def _fit_axis_aligned_box_candidate(
    points: np.ndarray,
    faces: np.ndarray,
    tolerance: float,
) -> Optional[_PrimitiveCandidate]:
    min_coords = points.min(axis=0)
    max_coords = points.max(axis=0)
    dims = max_coords - min_coords
    bbox_volume = float(dims[0] * dims[1] * dims[2])
    if bbox_volume <= 1e-12:
        return None

    mesh_volume = _signed_mesh_volume(points, faces)
    if mesh_volume <= 1e-12:
        return None
    vol_diff_ratio = abs(mesh_volume - bbox_volume) / bbox_volume

    err_cap = max(0.04, tolerance * 4.0)
    if vol_diff_ratio > err_cap:
        return None

    scad = (
        f"translate([{min_coords[0]:.6f}, {min_coords[1]:.6f}, {min_coords[2]:.6f}]) "
        f"cube([{dims[0]:.6f}, {dims[1]:.6f}, {dims[2]:.6f}]);"
    )
    confidence = max(0.0, 1.0 - (vol_diff_ratio / err_cap))
    return _PrimitiveCandidate("box", scad, confidence)


def _estimate_axis_and_radial(
    points: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Retained for diagnostics/backward compatibility in tests.
    axis = _pca_axes(points)[2]
    centroid, t_values, radial = _project_points_to_axis(points, axis)
    return axis, centroid, t_values, radial


def _pca_axes(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    centered = points - np.mean(points, axis=0)
    covariance = np.cov(centered, rowvar=False)
    _, eigvecs = np.linalg.eigh(covariance)
    axes = []
    for index in range(3):
        axis = eigvecs[:, index]
        axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
        axes.append(axis)
    return (axes[0], axes[1], axes[2])


def _project_points_to_axis(
    points: np.ndarray,
    axis: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    centroid = np.mean(points, axis=0)
    centered = points - centroid
    t_values = centered @ axis
    radial_vectors = centered - np.outer(t_values, axis)
    radial = np.linalg.norm(radial_vectors, axis=1)
    return centroid, t_values, radial


def _wrap_oriented_primitive(
    center: np.ndarray,
    axis: np.ndarray,
    primitive_scad: str,
) -> str:
    axis_vec: np.ndarray = np.asarray(axis, dtype=np.float64)
    axis_norm = np.linalg.norm(axis_vec)
    if axis_norm <= 1e-12:
        axis_vec = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    else:
        axis_vec = np.asarray(axis_vec / axis_norm, dtype=np.float64)

    z_axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    dot = float(np.clip(np.dot(z_axis, axis_vec), -1.0, 1.0))

    if dot > 1.0 - 1e-9:
        transform_body = primitive_scad
    else:
        rot_axis: np.ndarray
        if dot < -1.0 + 1e-9:
            rot_axis = np.array([1.0, 0.0, 0.0], dtype=np.float64)
            angle_deg = 180.0
        else:
            rot_axis = np.asarray(np.cross(z_axis, axis_vec), dtype=np.float64)
            rot_axis = rot_axis / max(float(np.linalg.norm(rot_axis)), 1e-12)
            angle_deg = math.degrees(math.acos(dot))
        transform_body = (
            f"rotate(a={angle_deg:.6f}, v=[{rot_axis[0]:.6f}, {rot_axis[1]:.6f}, {rot_axis[2]:.6f}]) "
            "{ "
            f"{primitive_scad}"
            " }"
        )

    return (
        f"translate([{center[0]:.6f}, {center[1]:.6f}, {center[2]:.6f}]) "
        "{ "
        f"{transform_body}"
        " }"
    )


def _safe_correlation(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or len(y) < 2:
        return 0.0
    x_std = float(np.std(x))
    y_std = float(np.std(y))
    if x_std <= 1e-12 or y_std <= 1e-12:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def _signed_mesh_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    if len(faces) == 0:
        return 0.0
    tri = vertices[faces]
    v0 = tri[:, 0]
    v1 = tri[:, 1]
    v2 = tri[:, 2]
    signed = np.einsum("ij,ij->i", v0, np.cross(v1, v2)) / 6.0
    return float(abs(np.sum(signed)))


def _shape_priority(shape: str) -> int:
    # In tie cases, prefer more specific/stable parametric output for this
    # Phase 1 implementation.
    return {
        "box": 4,
        "cylinder": 3,
        "cone": 2,
        "sphere": 1,
    }.get(shape, 0)


def _components_have_overlapping_bboxes(
    components: list[_ComponentMesh],
    epsilon: float = 1e-9,
) -> bool:
    bboxes: list[Tuple[np.ndarray, np.ndarray]] = []
    for component in components:
        pts = component.vertices
        bboxes.append((pts.min(axis=0), pts.max(axis=0)))

    for i in range(len(bboxes)):
        min_a, max_a = bboxes[i]
        for j in range(i + 1, len(bboxes)):
            min_b, max_b = bboxes[j]
            overlap_dims = np.minimum(max_a, max_b) - np.maximum(min_a, min_b)
            if np.all(overlap_dims > epsilon):
                return True
    return False
