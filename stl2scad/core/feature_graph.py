"""
Feature graph prototype for editable parametric reconstruction.

The graph is an intermediate representation: it describes high-confidence
feature candidates without committing to SCAD generation yet.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
from stl.mesh import Mesh

from .feature_inventory import _bbox, _normalized_normals, _triangle_areas


def build_feature_graph_for_stl(
    stl_file: Path | str,
    root_dir: Optional[Path | str] = None,
    normal_axis_threshold: float = 0.96,
    boundary_tolerance_ratio: float = 0.01,
) -> dict[str, Any]:
    """
    Build a conservative feature graph for one STL file.
    """
    path = Path(stl_file)
    mesh = Mesh.from_file(str(path))
    vectors = np.asarray(mesh.vectors, dtype=np.float64)
    points = vectors.reshape(-1, 3)
    normals = _normalized_normals(np.asarray(mesh.normals, dtype=np.float64))
    face_areas = _triangle_areas(vectors)
    bbox = _bbox(points)
    features = _extract_axis_aligned_box_features(
        vectors,
        normals,
        face_areas,
        bbox,
        normal_axis_threshold=normal_axis_threshold,
        boundary_tolerance_ratio=boundary_tolerance_ratio,
    )
    features.extend(
        _extract_axis_aligned_through_holes(
            vectors,
            normals,
            face_areas,
            bbox,
            features,
            normal_axis_threshold=normal_axis_threshold,
        )
    )
    features.extend(_extract_repeated_hole_patterns(features))

    return {
        "schema_version": 1,
        "source_file": _relative_or_absolute(path, root_dir),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mesh": {
            "triangles": int(len(vectors)),
            "bounding_box": bbox,
        },
        "features": features,
    }


def build_feature_graph_for_folder(
    input_dir: Path | str,
    output_json: Path | str,
    recursive: bool = True,
    max_files: Optional[int] = None,
) -> dict[str, Any]:
    """
    Build feature graphs for STL files in a folder and write a JSON report.
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    if not input_path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_path}")

    pattern = "**/*.stl" if recursive else "*.stl"
    files = sorted(path for path in input_path.glob(pattern) if path.is_file())
    if max_files is not None:
        files = files[:max_files]

    graphs: list[dict[str, Any]] = []
    for path in files:
        try:
            graphs.append(build_feature_graph_for_stl(path, root_dir=input_path))
        except Exception as exc:
            graphs.append(
                {
                    "schema_version": 1,
                    "source_file": _relative_or_absolute(path, input_path),
                    "status": "error",
                    "error": str(exc),
                    "features": [],
                }
            )

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_path),
        "summary": _summarize_graphs(graphs),
        "graphs": graphs,
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return report


def emit_feature_graph_scad_preview(graph: dict[str, Any]) -> Optional[str]:
    """
    Emit conservative SCAD preview for supported feature graph patterns.

    Currently supported:
    - one plate_like_solid
    - optional hole_like_cutout features along the plate thickness axis
    """
    plate = _best_feature(graph, "plate_like_solid")
    if plate is None or float(plate.get("confidence", 0.0)) < 0.70:
        return None

    holes = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "hole_like_cutout"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    origin = [float(value) for value in plate["origin"]]
    size = [float(value) for value in plate["size"]]
    thickness_axis_index = int(np.argmin(size))
    thickness_axis = ("x", "y", "z")[thickness_axis_index]
    supported_patterns = _supported_hole_patterns(graph, thickness_axis)
    linear_pattern_names: dict[int, str] = {}

    lines = [
        "// Feature graph SCAD preview",
        f"// source_file: {graph.get('source_file', '')}",
        "// generated from conservative plate/hole feature candidates",
        "",
        f"plate_origin = {_scad_vector(origin)};",
        f"plate_size = {_scad_vector(size)};",
    ]
    if holes:
        for pattern_index, pattern in enumerate(supported_patterns):
            if pattern.get("type") != "linear_hole_pattern" or not _has_linear_pattern_fields(pattern):
                continue
            pattern_name = f"hole_pattern_{len(linear_pattern_names)}"
            linear_pattern_names[pattern_index] = pattern_name
            origin = [float(value) for value in pattern["pattern_origin"]]
            step = [float(value) for value in pattern["pattern_step"]]
            lines.extend(
                [
                    f"{pattern_name}_count = {int(pattern['pattern_count'])};",
                    f"{pattern_name}_origin = {_scad_vector(origin)};",
                    f"{pattern_name}_step = {_scad_vector(step)};",
                    f"{pattern_name}_diameter = {float(pattern['diameter']):.6f};",
                ]
            )
        lines.extend(
            [
                "",
                "module hole_cutout(center, diameter) {",
                *_hole_cutout_module_body(size[thickness_axis_index] + 0.2, thickness_axis),
                "}",
            ]
        )
    lines.extend(
        [
            "",
            "difference() {",
            "  translate(plate_origin) cube(plate_size);",
        ]
    )

    emitted_hole_keys: set[tuple[float, float, float]] = set()
    for pattern_index, pattern in enumerate(supported_patterns):
        diameter = float(pattern["diameter"])
        centers = [[float(value) for value in center] for center in pattern["centers"]]
        pattern_name = linear_pattern_names.get(pattern_index)
        if pattern_name is not None:
            lines.append(f"  for (i = [0 : {pattern_name}_count - 1]) {{")
            lines.append(
                f"    hole_cutout({_scad_named_linear_point_expression(pattern_name, 'i')}, {pattern_name}_diameter);"
            )
            lines.append("  }")
        else:
            center_list = "[" + ", ".join(_scad_vector(center) for center in centers) + "]"
            lines.append(f"  for (hole_center = {center_list}) {{")
            lines.append(f"    hole_cutout(hole_center, {diameter:.6f});")
            lines.append("  }")
        emitted_hole_keys.update(_hole_key(center) for center in centers)

    for hole in holes:
        if hole.get("axis") != thickness_axis:
            continue
        center = [float(value) for value in hole["center"]]
        if _hole_key(center) in emitted_hole_keys:
            continue
        diameter = float(hole["diameter"])
        lines.append(f"  hole_cutout({_scad_vector(center)}, {diameter:.6f});")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _extract_axis_aligned_box_features(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    normal_axis_threshold: float,
    boundary_tolerance_ratio: float,
) -> list[dict[str, Any]]:
    if len(vectors) == 0:
        return []

    total_area = float(np.sum(face_areas))
    if total_area <= 1e-12:
        return []

    face_centers = np.mean(vectors, axis=1)
    diagonal = max(float(bbox.get("diagonal", 0.0)), 1e-9)
    boundary_tolerance = max(diagonal * boundary_tolerance_ratio, 1e-6)
    axis_pairs = {
        "x": (0, np.array([1.0, 0.0, 0.0]), bbox["min_x"], bbox["max_x"]),
        "y": (1, np.array([0.0, 1.0, 0.0]), bbox["min_y"], bbox["max_y"]),
        "z": (2, np.array([0.0, 0.0, 1.0]), bbox["min_z"], bbox["max_z"]),
    }

    supporting_area = 0.0
    plane_features: list[dict[str, Any]] = []
    for axis_name, (axis_index, axis, min_coord, max_coord) in axis_pairs.items():
        negative_mask = (normals @ -axis >= normal_axis_threshold) & (
            np.abs(face_centers[:, axis_index] - min_coord) <= boundary_tolerance
        )
        positive_mask = (normals @ axis >= normal_axis_threshold) & (
            np.abs(face_centers[:, axis_index] - max_coord) <= boundary_tolerance
        )
        negative_area = float(np.sum(face_areas[negative_mask]))
        positive_area = float(np.sum(face_areas[positive_mask]))
        supporting_area += negative_area + positive_area
        plane_features.append(
            {
                "type": "axis_boundary_plane_pair",
                "axis": axis_name,
                "negative_coord": float(min_coord),
                "positive_coord": float(max_coord),
                "negative_area": negative_area,
                "positive_area": positive_area,
                "paired": bool(negative_area > 0.0 and positive_area > 0.0),
            }
        )

    confidence = min(supporting_area / total_area, 1.0)
    dimensions = {
        "width": float(bbox["width"]),
        "depth": float(bbox["height"]),
        "height": float(bbox["depth"]),
    }
    nonzero_dims = [value for value in dimensions.values() if value > 1e-9]
    thin_ratio = min(nonzero_dims) / max(nonzero_dims) if len(nonzero_dims) == 3 else 0.0
    paired_axes = sum(1 for feature in plane_features if feature["paired"])

    features: list[dict[str, Any]] = plane_features
    if paired_axes >= 2 and confidence >= 0.55 and thin_ratio <= 0.18:
        features.append(
            {
                "type": "plate_like_solid",
                "confidence": float(confidence),
                "origin": [float(bbox["min_x"]), float(bbox["min_y"]), float(bbox["min_z"])],
                "size": [dimensions["width"], dimensions["depth"], dimensions["height"]],
                "parameters": {
                    "width": dimensions["width"],
                    "depth": dimensions["depth"],
                    "thickness": min(nonzero_dims) if nonzero_dims else 0.0,
                },
                "note": "Candidate for an editable plate or slab feature.",
            }
        )
    elif paired_axes == 3 and confidence >= 0.80:
        features.append(
            {
                "type": "box_like_solid",
                "confidence": float(confidence),
                "origin": [float(bbox["min_x"]), float(bbox["min_y"]), float(bbox["min_z"])],
                "size": [dimensions["width"], dimensions["depth"], dimensions["height"]],
                "parameters": {
                    "width": dimensions["width"],
                    "depth": dimensions["depth"],
                    "height": dimensions["height"],
                },
                "note": "Candidate for a cube()/translate() parametric base feature.",
            }
        )
    return features


def _best_feature(graph: dict[str, Any], feature_type: str) -> Optional[dict[str, Any]]:
    candidates = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == feature_type
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda feature: float(feature.get("confidence", 0.0)))


def _scad_vector(values: list[float]) -> str:
    return "[" + ", ".join(f"{value:.6f}" for value in values) + "]"


def _scad_named_linear_point_expression(pattern_name: str, index_name: str) -> str:
    parts = [
        f"{pattern_name}_origin[{axis}] + {index_name} * {pattern_name}_step[{axis}]"
        for axis in range(3)
    ]
    return "[" + ", ".join(parts) + "]"


def _supported_hole_patterns(
    graph: dict[str, Any],
    axis: str,
) -> list[dict[str, Any]]:
    return [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") in {"linear_hole_pattern", "grid_hole_pattern"}
        and feature.get("axis") == axis
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]


def _has_linear_pattern_fields(pattern: dict[str, Any]) -> bool:
    return (
        isinstance(pattern.get("pattern_origin"), list)
        and isinstance(pattern.get("pattern_step"), list)
        and "pattern_count" in pattern
    )


def _hole_key(center: list[float]) -> tuple[float, float, float]:
    return tuple(round(float(value), 4) for value in center)


def _hole_cutout_module_body(
    depth: float,
    axis: str,
) -> list[str]:
    if axis == "z":
        return [
            f"  translate([center[0], center[1], center[2] - {depth * 0.5:.6f}])",
            f"    cylinder(h={depth:.6f}, d=diameter, $fn=64);",
        ]
    elif axis == "x":
        return [
            f"  translate([center[0] - {depth * 0.5:.6f}, center[1], center[2]])",
            "    rotate(a=90, v=[0, 1, 0])",
            f"      cylinder(h={depth:.6f}, d=diameter, $fn=64);",
        ]
    elif axis == "y":
        return [
            f"  translate([center[0], center[1] - {depth * 0.5:.6f}, center[2]])",
            "    rotate(a=90, v=[1, 0, 0])",
            f"      cylinder(h={depth:.6f}, d=diameter, $fn=64);",
        ]
    return ["  // unsupported hole axis"]


def _extract_axis_aligned_through_holes(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    existing_features: list[dict[str, Any]],
    normal_axis_threshold: float,
) -> list[dict[str, Any]]:
    plate_features = [
        feature
        for feature in existing_features
        if feature.get("type") == "plate_like_solid"
    ]
    if not plate_features:
        return []

    plate = plate_features[0]
    size = [float(value) for value in plate["size"]]
    thickness_axis_index = int(np.argmin(size))
    thickness = size[thickness_axis_index]
    if thickness <= 1e-9:
        return []

    axis_labels = ("x", "y", "z")
    plane_axes = [index for index in range(3) if index != thickness_axis_index]
    axis_vector = np.zeros(3, dtype=np.float64)
    axis_vector[thickness_axis_index] = 1.0

    face_centers = np.mean(vectors, axis=1)
    # Cylindrical through-hole walls are roughly perpendicular to plate thickness.
    sidewall_mask = np.abs(normals @ axis_vector) <= (1.0 - normal_axis_threshold)
    span_min = float(bbox[f"min_{axis_labels[thickness_axis_index]}"])
    span_max = float(bbox[f"max_{axis_labels[thickness_axis_index]}"])
    interior_mask = (face_centers[:, thickness_axis_index] > span_min + thickness * 0.05) & (
        face_centers[:, thickness_axis_index] < span_max - thickness * 0.05
    )
    candidate_faces = np.where(sidewall_mask | interior_mask)[0]
    if len(candidate_faces) == 0:
        return []

    components = _connected_face_components(vectors, candidate_faces)
    features: list[dict[str, Any]] = []
    min_radius = max(min(size[axis] for axis in plane_axes) * 0.005, 0.05)
    max_radius = max(size[axis] for axis in plane_axes) * 0.45
    for component_index, face_indices in enumerate(components):
        if len(face_indices) < 8:
            continue
        component_vertices = vectors[face_indices].reshape(-1, 3)
        coords_2d = component_vertices[:, plane_axes]
        height_values = component_vertices[:, thickness_axis_index]
        height_span = float(np.max(height_values) - np.min(height_values))
        if height_span < thickness * 0.65:
            continue

        fit = _fit_circle_2d(coords_2d)
        if fit is None:
            continue
        center_2d, radius, radial_error_ratio, angular_coverage = fit
        if radius < min_radius or radius > max_radius:
            continue
        if radial_error_ratio > 0.08 or angular_coverage < 0.70:
            continue
        if _center_near_outer_boundary(center_2d, bbox, plane_axes, radius):
            continue

        center = [0.0, 0.0, 0.0]
        center[plane_axes[0]] = float(center_2d[0])
        center[plane_axes[1]] = float(center_2d[1])
        center[thickness_axis_index] = (span_min + span_max) * 0.5
        confidence = max(0.0, min(1.0, (1.0 - radial_error_ratio / 0.08) * angular_coverage))
        features.append(
            {
                "type": "hole_like_cutout",
                "confidence": float(confidence),
                "axis": axis_labels[thickness_axis_index],
                "center": center,
                "diameter": float(radius * 2.0),
                "depth": float(height_span),
                "component_faces": int(len(face_indices)),
                "radial_error_ratio": float(radial_error_ratio),
                "angular_coverage": float(angular_coverage),
                "source_component_index": component_index,
                "note": "Candidate circular through-hole cutout in a plate-like solid.",
            }
        )
    return features


def _extract_repeated_hole_patterns(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    holes = [feature for feature in features if feature.get("type") == "hole_like_cutout"]
    patterns: list[dict[str, Any]] = []
    if len(holes) < 2:
        return patterns

    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for hole in holes:
        diameter = float(hole["diameter"])
        key = (str(hole["axis"]), int(round(diameter * 1000.0)))
        groups.setdefault(key, []).append(hole)

    for (axis, diameter_key), group in groups.items():
        if len(group) < 2:
            continue
        centers = np.asarray([hole["center"] for hole in group], dtype=np.float64)
        varying_axes = [
            index
            for index in range(3)
            if index != {"x": 0, "y": 1, "z": 2}[axis]
        ]
        unique_counts = [
            len(np.unique(np.round(centers[:, axis_index], 4)))
            for axis_index in varying_axes
        ]
        pattern_type = "grid_hole_pattern" if min(unique_counts) >= 2 else "linear_hole_pattern"
        pattern = {
            "type": pattern_type,
            "confidence": float(min(float(hole["confidence"]) for hole in group)),
            "axis": axis,
            "hole_count": int(len(group)),
            "diameter": float(diameter_key / 1000.0),
            "centers": [[float(value) for value in hole["center"]] for hole in group],
            "note": "Candidate repeated hole pattern for future SCAD loop emission.",
        }
        if pattern_type == "linear_hole_pattern":
            pattern.update(_linear_hole_pattern_metadata(centers, varying_axes))
        patterns.append(pattern)
    return patterns


def _linear_hole_pattern_metadata(
    centers: np.ndarray,
    varying_axes: list[int],
) -> dict[str, Any]:
    if len(centers) < 2:
        return {}

    axis_spans = np.ptp(centers[:, varying_axes], axis=0)
    active_axis = varying_axes[int(np.argmax(axis_spans))]
    ordered_centers = centers[np.argsort(centers[:, active_axis])]
    count = len(ordered_centers)
    step = (ordered_centers[-1] - ordered_centers[0]) / float(count - 1)
    spacing = float(np.linalg.norm(step))
    if spacing <= 1e-9:
        return {}

    expected = ordered_centers[0] + np.arange(count, dtype=np.float64)[:, None] * step
    regularity_error = float(np.max(np.linalg.norm(ordered_centers - expected, axis=1)) / spacing)
    if regularity_error > 0.05:
        return {}

    return {
        "pattern_origin": [float(value) for value in ordered_centers[0]],
        "pattern_step": [float(value) for value in step],
        "pattern_count": int(count),
        "pattern_spacing": spacing,
        "pattern_axis": ("x", "y", "z")[active_axis],
        "regularity_error": regularity_error,
    }


def _connected_face_components(
    vectors: np.ndarray,
    face_indices: np.ndarray,
    tolerance: float = 1e-5,
) -> list[np.ndarray]:
    if len(face_indices) == 0:
        return []

    scale = 1.0 / tolerance
    vertex_to_faces: dict[tuple[int, int, int], list[int]] = {}
    for local_index, face_index in enumerate(face_indices):
        for vertex in vectors[face_index]:
            key = tuple(np.round(vertex * scale).astype(np.int64))
            vertex_to_faces.setdefault(key, []).append(local_index)

    adjacency: list[set[int]] = [set() for _ in face_indices]
    for local_faces in vertex_to_faces.values():
        for local_index in local_faces:
            adjacency[local_index].update(local_faces)

    seen: set[int] = set()
    components: list[np.ndarray] = []
    for start in range(len(face_indices)):
        if start in seen:
            continue
        stack = [start]
        component: list[int] = []
        seen.add(start)
        while stack:
            current = stack.pop()
            component.append(int(face_indices[current]))
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(np.asarray(component, dtype=np.int64))
    return components


def _fit_circle_2d(points: np.ndarray) -> Optional[tuple[np.ndarray, float, float, float]]:
    if len(points) < 8:
        return None
    matrix = np.column_stack((2.0 * points, np.ones(len(points))))
    vector = np.sum(points * points, axis=1)
    try:
        solution, *_ = np.linalg.lstsq(matrix, vector, rcond=None)
    except np.linalg.LinAlgError:
        return None

    center = solution[:2]
    radius_sq = float(np.dot(center, center) + solution[2])
    if radius_sq <= 1e-12:
        return None
    radius = float(np.sqrt(radius_sq))
    distances = np.linalg.norm(points - center, axis=1)
    radial_error_ratio = float(np.percentile(np.abs(distances - radius), 95) / max(radius, 1e-9))
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    bins = np.unique(np.floor(((angles + np.pi) / (2.0 * np.pi)) * 24.0).astype(int))
    angular_coverage = float(min(len(bins), 24) / 24.0)
    return center, radius, radial_error_ratio, angular_coverage


def _center_near_outer_boundary(
    center_2d: np.ndarray,
    bbox: dict[str, float],
    plane_axes: list[int],
    radius: float,
) -> bool:
    labels = ("x", "y", "z")
    for value, axis_index in zip(center_2d, plane_axes):
        min_coord = float(bbox[f"min_{labels[axis_index]}"])
        max_coord = float(bbox[f"max_{labels[axis_index]}"])
        if value - radius <= min_coord + radius * 0.1:
            return True
        if value + radius >= max_coord - radius * 0.1:
            return True
    return False


def _relative_or_absolute(path: Path, root_dir: Optional[Path | str]) -> str:
    if root_dir is None:
        return str(path)
    try:
        return str(path.relative_to(Path(root_dir)))
    except ValueError:
        return str(path)


def _summarize_graphs(graphs: list[dict[str, Any]]) -> dict[str, Any]:
    feature_counts: dict[str, int] = {}
    error_count = 0
    for graph in graphs:
        if graph.get("status") == "error":
            error_count += 1
        for feature in graph.get("features", []):
            feature_type = str(feature.get("type", "unknown"))
            feature_counts[feature_type] = feature_counts.get(feature_type, 0) + 1
    return {
        "file_count": len(graphs),
        "error_count": error_count,
        "feature_counts": feature_counts,
    }
