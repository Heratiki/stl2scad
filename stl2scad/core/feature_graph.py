"""
Feature graph prototype for editable parametric reconstruction.

The graph is an intermediate representation: it describes high-confidence
feature candidates without committing to SCAD generation yet.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy as np
from stl.mesh import Mesh

from .feature_inventory import _bbox, _normalized_normals, _triangle_areas

STL_SUFFIXES = {".stl"}


def build_feature_graph_for_stl(
    stl_file: Union[Path, str],
    root_dir: Optional[Union[Path, str]] = None,
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
    input_dir: Union[Path, str],
    output_json: Union[Path, str],
    recursive: bool = True,
    max_files: Optional[int] = None,
    workers: int = 1,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    """
    Build feature graphs for STL files in a folder and write a JSON report.
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    if not input_path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_path}")

    pattern = "**/*" if recursive else "*"
    files = sorted(
        path
        for path in input_path.glob(pattern)
        if path.is_file() and path.suffix.lower() in STL_SUFFIXES
    )
    if max_files is not None:
        files = files[:max_files]

    worker_count = max(1, int(workers))
    if worker_count == 1 or len(files) <= 1:
        graphs = []
        for idx, path in enumerate(files, 1):
            graph = _build_feature_graph_for_folder_file(path, input_path)
            graphs.append(graph)
            if progress_callback is not None:
                progress_callback(idx, len(files), str(path))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_path = {
                executor.submit(_build_feature_graph_for_folder_worker, (path, input_path)): path
                for path in files
            }
            graph_map: dict[Path, dict[str, Any]] = {}
            done_count = 0
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                graph_map[path] = future.result()
                done_count += 1
                if progress_callback is not None:
                    progress_callback(done_count, len(files), str(path))
            graphs = [graph_map[path] for path in files]

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_path),
        "config": {
            "recursive": recursive,
            "max_files": max_files,
            "workers": worker_count,
        },
        "summary": _summarize_graphs(graphs),
        "graphs": graphs,
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return report


def _build_feature_graph_for_folder_worker(args: tuple[Path, Path]) -> dict[str, Any]:
    path, input_path = args
    return _build_feature_graph_for_folder_file(path, input_path)


def _build_feature_graph_for_folder_file(
    path: Path, input_path: Path
) -> dict[str, Any]:
    try:
        return build_feature_graph_for_stl(path, root_dir=input_path)
    except Exception as exc:
        return {
            "schema_version": 1,
            "source_file": _relative_or_absolute(path, input_path),
            "status": "error",
            "error": str(exc),
            "features": [],
        }


def emit_feature_graph_scad_preview(graph: dict[str, Any]) -> Optional[str]:
    """
    Emit conservative SCAD preview for supported feature graph patterns.

        Currently supported:
        - one plate_like_solid
        - optional hole_like_cutout, counterbore_hole, and slot_like_cutout
            features along the plate thickness axis
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
    slots = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "slot_like_cutout"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    counterbores = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "counterbore_hole"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    origin = [float(value) for value in plate["origin"]]
    size = [float(value) for value in plate["size"]]
    thickness_axis_index = int(np.argmin(size))
    thickness_axis = ("x", "y", "z")[thickness_axis_index]
    supported_patterns = _supported_hole_patterns(graph, thickness_axis)
    linear_pattern_names: dict[int, str] = {}
    grid_pattern_names: dict[int, str] = {}

    lines = [
        "// Feature graph SCAD preview",
        f"// source_file: {graph.get('source_file', '')}",
        "// generated from conservative plate/hole feature candidates",
        "",
        f"plate_origin = {_scad_vector(origin)};",
        f"plate_size = {_scad_vector(size)};",
    ]
    if holes or slots or counterbores:
        for pattern_index, pattern in enumerate(supported_patterns):
            if pattern.get(
                "type"
            ) == "linear_hole_pattern" and _has_linear_pattern_fields(pattern):
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
            elif pattern.get(
                "type"
            ) == "grid_hole_pattern" and _has_grid_pattern_fields(pattern):
                pattern_name = f"hole_grid_{len(grid_pattern_names)}"
                grid_pattern_names[pattern_index] = pattern_name
                origin = [float(value) for value in pattern["grid_origin"]]
                row_step = [float(value) for value in pattern["grid_row_step"]]
                col_step = [float(value) for value in pattern["grid_col_step"]]
                lines.extend(
                    [
                        f"{pattern_name}_rows = {int(pattern['grid_rows'])};",
                        f"{pattern_name}_cols = {int(pattern['grid_cols'])};",
                        f"{pattern_name}_origin = {_scad_vector(origin)};",
                        f"{pattern_name}_row_step = {_scad_vector(row_step)};",
                        f"{pattern_name}_col_step = {_scad_vector(col_step)};",
                        f"{pattern_name}_diameter = {float(pattern['diameter']):.6f};",
                    ]
                )
        for slot_index, slot in enumerate(slots):
            if slot.get("axis") != thickness_axis:
                continue
            lines.extend(
                [
                    f"slot_{slot_index}_start = {_scad_vector([float(value) for value in slot['start']])};",
                    f"slot_{slot_index}_end = {_scad_vector([float(value) for value in slot['end']])};",
                    f"slot_{slot_index}_width = {float(slot['width']):.6f};",
                ]
            )
        for cbore_index, counterbore in enumerate(counterbores):
            if counterbore.get("axis") != thickness_axis:
                continue
            lines.extend(
                [
                    f"counterbore_{cbore_index}_center = {_scad_vector([float(value) for value in counterbore['center']])};",
                    f"counterbore_{cbore_index}_through_diameter = {float(counterbore['through_diameter']):.6f};",
                    f"counterbore_{cbore_index}_bore_diameter = {float(counterbore['bore_diameter']):.6f};",
                    f"counterbore_{cbore_index}_bore_depth = {float(counterbore['bore_depth']):.6f};",
                ]
            )
        lines.extend(
            [
                "",
                "module hole_cutout(center, diameter) {",
                *_hole_cutout_module_body(
                    size[thickness_axis_index] + 0.2, thickness_axis
                ),
                "}",
            ]
        )
        if counterbores:
            lines.extend(
                [
                    "",
                    "module counterbore_cutout(center, through_diameter, bore_diameter, bore_depth) {",
                    "  hole_cutout(center, through_diameter);",
                    *_counterbore_bore_module_body(
                        size[thickness_axis_index] + 0.2,
                        thickness_axis,
                    ),
                    "}",
                ]
            )
        if slots:
            lines.extend(
                [
                    "",
                    "module slot_cutout(start, end, width) {",
                    "  hull() {",
                    "    hole_cutout(start, width);",
                    "    hole_cutout(end, width);",
                    "  }",
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
        linear_name: Optional[str] = linear_pattern_names.get(pattern_index)
        if linear_name is not None:
            lines.append(f"  for (i = [0 : {linear_name}_count - 1]) {{")
            lines.append(
                f"    hole_cutout({_scad_named_linear_point_expression(linear_name, 'i')}, {linear_name}_diameter);"
            )
            lines.append("  }")
        elif pattern_index in grid_pattern_names:
            grid_name = grid_pattern_names[pattern_index]
            lines.append(f"  for (row = [0 : {grid_name}_rows - 1]) {{")
            lines.append(f"    for (col = [0 : {grid_name}_cols - 1]) {{")
            lines.append(
                f"      hole_cutout({_scad_named_grid_point_expression(grid_name)}, {grid_name}_diameter);"
            )
            lines.append("    }")
            lines.append("  }")
        else:
            center_list = (
                "[" + ", ".join(_scad_vector(center) for center in centers) + "]"
            )
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

    for slot_index, slot in enumerate(slots):
        if slot.get("axis") != thickness_axis:
            continue
        lines.append(
            f"  slot_cutout(slot_{slot_index}_start, slot_{slot_index}_end, slot_{slot_index}_width);"
        )

    for cbore_index, counterbore in enumerate(counterbores):
        if counterbore.get("axis") != thickness_axis:
            continue
        lines.append(
            "  counterbore_cutout("
            f"counterbore_{cbore_index}_center, "
            f"counterbore_{cbore_index}_through_diameter, "
            f"counterbore_{cbore_index}_bore_diameter, "
            f"counterbore_{cbore_index}_bore_depth"
            ");"
        )

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
    thin_ratio = (
        min(nonzero_dims) / max(nonzero_dims) if len(nonzero_dims) == 3 else 0.0
    )
    paired_axes = sum(1 for feature in plane_features if feature["paired"])

    features: list[dict[str, Any]] = plane_features
    if paired_axes >= 2 and confidence >= 0.55 and thin_ratio <= 0.18:
        features.append(
            {
                "type": "plate_like_solid",
                "confidence": float(confidence),
                "origin": [
                    float(bbox["min_x"]),
                    float(bbox["min_y"]),
                    float(bbox["min_z"]),
                ],
                "size": [
                    dimensions["width"],
                    dimensions["depth"],
                    dimensions["height"],
                ],
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
                "origin": [
                    float(bbox["min_x"]),
                    float(bbox["min_y"]),
                    float(bbox["min_z"]),
                ],
                "size": [
                    dimensions["width"],
                    dimensions["depth"],
                    dimensions["height"],
                ],
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


def _scad_named_grid_point_expression(pattern_name: str) -> str:
    parts = [
        (
            f"{pattern_name}_origin[{axis}] + row * {pattern_name}_row_step[{axis}] "
            f"+ col * {pattern_name}_col_step[{axis}]"
        )
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


def _has_grid_pattern_fields(pattern: dict[str, Any]) -> bool:
    return (
        isinstance(pattern.get("grid_origin"), list)
        and isinstance(pattern.get("grid_row_step"), list)
        and isinstance(pattern.get("grid_col_step"), list)
        and "grid_rows" in pattern
        and "grid_cols" in pattern
    )


def _hole_key(center: list[float]) -> tuple[float, float, float]:
    rounded = [round(float(value), 4) for value in center]
    return (rounded[0], rounded[1], rounded[2])


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


def _counterbore_bore_module_body(
    depth: float,
    axis: str,
) -> list[str]:
    if axis == "z":
        return [
            "  translate([center[0], center[1], center[2] + "
            f"{depth * 0.5:.6f} - bore_depth])",
            "    cylinder(h=bore_depth + 0.1, d=bore_diameter, $fn=64);",
        ]
    elif axis == "x":
        return [
            "  translate([center[0] + "
            f"{depth * 0.5:.6f} - bore_depth, center[1], center[2]])",
            "    rotate(a=90, v=[0, 1, 0])",
            "      cylinder(h=bore_depth + 0.1, d=bore_diameter, $fn=64);",
        ]
    elif axis == "y":
        return [
            "  translate([center[0], center[1] + "
            f"{depth * 0.5:.6f} - bore_depth, center[2]])",
            "    rotate(a=90, v=[1, 0, 0])",
            "      cylinder(h=bore_depth + 0.1, d=bore_diameter, $fn=64);",
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
    axis_labels = ("x", "y", "z")
    face_centers = np.mean(vectors, axis=1)
    features: list[dict[str, Any]] = []

    for target in _candidate_cutout_axes(existing_features):
        cutout_axis_index = int(target["axis_index"])
        cutout_depth = float(target["depth"])
        if cutout_depth <= 1e-9:
            continue

        plane_axes = [index for index in range(3) if index != cutout_axis_index]
        axis_vector = np.zeros(3, dtype=np.float64)
        axis_vector[cutout_axis_index] = 1.0
        span_min = float(bbox[f"min_{axis_labels[cutout_axis_index]}"])
        span_max = float(bbox[f"max_{axis_labels[cutout_axis_index]}"])
        sidewall_mask = np.abs(normals @ axis_vector) <= (1.0 - normal_axis_threshold)
        # Keep only cutout-region faces away from the outer boundary planes on
        # the two perpendicular axes. This avoids merging hole sidewalls with
        # the parent solid's outer side faces into one giant component.
        interior_plane_mask = np.ones(len(vectors), dtype=bool)
        for axis in plane_axes:
            axis_min = float(bbox[f"min_{axis_labels[axis]}"])
            axis_max = float(bbox[f"max_{axis_labels[axis]}"])
            axis_span = max(axis_max - axis_min, 1e-9)
            boundary_margin = axis_span * 0.05
            interior_plane_mask &= (
                (face_centers[:, axis] > axis_min + boundary_margin)
                & (face_centers[:, axis] < axis_max - boundary_margin)
            )
        interior_mask = (
            face_centers[:, cutout_axis_index] > span_min + cutout_depth * 0.05
        ) & (face_centers[:, cutout_axis_index] < span_max - cutout_depth * 0.05)
        candidate_faces = np.where((sidewall_mask | interior_mask) & interior_plane_mask)[0]
        if len(candidate_faces) == 0:
            continue

        components = _connected_face_components(vectors, candidate_faces)
        min_radius = max(min(target["size"][axis] for axis in plane_axes) * 0.005, 0.05)
        max_radius = max(target["size"][axis] for axis in plane_axes) * 0.45
        for component_index, face_indices in enumerate(components):
            if len(face_indices) < 8:
                continue
            component_vertices = vectors[face_indices].reshape(-1, 3)
            coords_2d = component_vertices[:, plane_axes]
            height_values = component_vertices[:, cutout_axis_index]
            height_span = float(np.max(height_values) - np.min(height_values))
            if height_span < cutout_depth * 0.65:
                continue

            # Counterbores are stepped holes and often fail a single-circle fit,
            # so try this path before the simple-hole fallback.
            cbore = _try_counterbore_fit(
                component_vertices,
                cutout_axis_index,
                plane_axes,
                cutout_depth,
                span_min,
                span_max,
            )
            if (
                cbore is not None
                and cbore["confidence"] >= 0.70
                and min_radius <= cbore["bore_radius"] <= max_radius
                and min_radius <= cbore["through_radius"] <= max_radius
                and not _center_near_outer_boundary(
                    cbore["center_2d"], bbox, plane_axes, cbore["bore_radius"]
                )
            ):
                center = [0.0, 0.0, 0.0]
                center[plane_axes[0]] = float(cbore["center_2d"][0])
                center[plane_axes[1]] = float(cbore["center_2d"][1])
                center[cutout_axis_index] = (span_min + span_max) * 0.5
                features.append(
                    {
                        "type": "counterbore_hole",
                        "confidence": float(cbore["confidence"]),
                        "axis": axis_labels[cutout_axis_index],
                        "center": center,
                        "through_diameter": float(cbore["through_radius"] * 2.0),
                        "bore_diameter": float(cbore["bore_radius"] * 2.0),
                        "bore_depth": float(cbore["bore_depth"]),
                        "through_depth": float(cbore["through_depth"]),
                        "total_depth": float(cbore["total_depth"]),
                        "component_faces": int(len(face_indices)),
                        "radial_error_ratio": float(cbore["radial_error_ratio"]),
                        "angular_coverage": float(cbore["angular_coverage"]),
                        "source_component_index": component_index,
                        "source_parent_type": target["parent_type"],
                        "note": (
                            "Candidate counterbore hole cutout in a "
                            f"{target['parent_type'].replace('_', '-')}"
                        ),
                    }
                )
                continue

            fit = _fit_circle_2d(coords_2d)
            if fit is not None:
                center_2d, radius, radial_error_ratio, angular_coverage = fit
                if (
                    min_radius <= radius <= max_radius
                    and radial_error_ratio <= 0.08
                    and angular_coverage >= 0.70
                    and not _center_near_outer_boundary(center_2d, bbox, plane_axes, radius)
                ):
                    center = [0.0, 0.0, 0.0]
                    center[plane_axes[0]] = float(center_2d[0])
                    center[plane_axes[1]] = float(center_2d[1])
                    center[cutout_axis_index] = (span_min + span_max) * 0.5
                    confidence = max(
                        0.0,
                        min(1.0, (1.0 - radial_error_ratio / 0.08) * angular_coverage),
                    )
                    features.append(
                        {
                            "type": "hole_like_cutout",
                            "confidence": float(confidence),
                            "axis": axis_labels[cutout_axis_index],
                            "center": center,
                            "diameter": float(radius * 2.0),
                            "depth": float(height_span),
                            "component_faces": int(len(face_indices)),
                            "radial_error_ratio": float(radial_error_ratio),
                            "angular_coverage": float(angular_coverage),
                            "source_component_index": component_index,
                            "source_parent_type": target["parent_type"],
                            "note": (
                                "Candidate circular through-hole cutout in a "
                                f"{target['parent_type'].replace('_', '-')}"
                            ),
                        }
                    )
                    continue

            slot_fit = _fit_axis_aligned_slot_2d(coords_2d)
            if slot_fit is None:
                continue
            (
                center_2d,
                start_2d,
                end_2d,
                width,
                length,
                slot_error_ratio,
                slot_axis_index,
            ) = slot_fit
            radius = width * 0.5
            if radius < min_radius or radius > max_radius:
                continue
            if _slot_near_outer_boundary(start_2d, end_2d, radius, bbox, plane_axes):
                continue

            center = [0.0, 0.0, 0.0]
            start = [0.0, 0.0, 0.0]
            end = [0.0, 0.0, 0.0]
            center[plane_axes[0]] = float(center_2d[0])
            center[plane_axes[1]] = float(center_2d[1])
            start[plane_axes[0]] = float(start_2d[0])
            start[plane_axes[1]] = float(start_2d[1])
            end[plane_axes[0]] = float(end_2d[0])
            end[plane_axes[1]] = float(end_2d[1])
            for vector in (center, start, end):
                vector[cutout_axis_index] = (span_min + span_max) * 0.5
            confidence = max(0.0, min(1.0, 1.0 - slot_error_ratio / 0.12))
            features.append(
                {
                    "type": "slot_like_cutout",
                    "confidence": float(confidence),
                    "axis": axis_labels[cutout_axis_index],
                    "center": center,
                    "start": start,
                    "end": end,
                    "width": float(width),
                    "length": float(length),
                    "depth": float(height_span),
                    "component_faces": int(len(face_indices)),
                    "slot_error_ratio": float(slot_error_ratio),
                    "slot_axis": axis_labels[plane_axes[slot_axis_index]],
                    "source_component_index": component_index,
                    "source_parent_type": target["parent_type"],
                    "note": (
                        "Candidate rounded slot through-cutout in a "
                        f"{target['parent_type'].replace('_', '-')}"
                    ),
                }
            )
    return features


def _candidate_cutout_axes(
    existing_features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for feature in existing_features:
        feature_type = feature.get("type")
        if feature_type == "plate_like_solid":
            size = [float(value) for value in feature["size"]]
            axis_index = int(np.argmin(size))
            candidates.append(
                {
                    "parent_type": "plate_like_solid",
                    "axis_index": axis_index,
                    "depth": float(size[axis_index]),
                    "size": size,
                }
            )
        elif feature_type == "box_like_solid":
            size = [float(value) for value in feature["size"]]
            for axis_index, depth in enumerate(size):
                candidates.append(
                    {
                        "parent_type": "box_like_solid",
                        "axis_index": axis_index,
                        "depth": float(depth),
                        "size": size,
                    }
                )

    return candidates


def _extract_repeated_hole_patterns(
    features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    holes = [
        feature for feature in features if feature.get("type") == "hole_like_cutout"
    ]
    patterns: list[dict[str, Any]] = []
    if len(holes) < 2:
        return patterns

    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for hole in holes:
        diameter = float(hole["diameter"])
        # Group diameters with a modest tolerance to absorb mesh noise.
        key = (str(hole["axis"]), int(round(diameter * 100.0)))
        groups.setdefault(key, []).append(hole)

    for (axis, diameter_key), group in groups.items():
        if len(group) < 2:
            continue
        centers = np.asarray([hole["center"] for hole in group], dtype=np.float64)
        varying_axes = [
            index for index in range(3) if index != {"x": 0, "y": 1, "z": 2}[axis]
        ]
        unique_counts = [
            len(np.unique(np.round(centers[:, axis_index], 4)))
            for axis_index in varying_axes
        ]
        pattern_type = (
            "grid_hole_pattern"
            if len(group) >= 4 and min(unique_counts) >= 2
            else "linear_hole_pattern"
        )
        pattern = {
            "type": pattern_type,
            "confidence": float(min(float(hole["confidence"]) for hole in group)),
            "axis": axis,
            "hole_count": int(len(group)),
            "diameter": float(diameter_key / 100.0),
            "centers": [[float(value) for value in hole["center"]] for hole in group],
            "note": "Candidate repeated hole pattern for future SCAD loop emission.",
        }
        if pattern_type == "linear_hole_pattern":
            pattern.update(_linear_hole_pattern_metadata(centers, varying_axes))
        else:
            pattern.update(_grid_hole_pattern_metadata(centers, axis, varying_axes))
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
    regularity_error = float(
        np.max(np.linalg.norm(ordered_centers - expected, axis=1)) / spacing
    )
    if regularity_error > 0.08:
        return {}

    return {
        "pattern_origin": [float(value) for value in ordered_centers[0]],
        "pattern_step": [float(value) for value in step],
        "pattern_count": int(count),
        "pattern_spacing": spacing,
        "pattern_axis": ("x", "y", "z")[active_axis],
        "regularity_error": regularity_error,
    }


def _grid_hole_pattern_metadata(
    centers: np.ndarray,
    axis: str,
    varying_axes: list[int],
) -> dict[str, Any]:
    if len(centers) < 4 or len(varying_axes) != 2:
        return {}

    rounded = np.round(centers[:, varying_axes], 4)
    row_values = np.sort(np.unique(rounded[:, 1]))
    col_values = np.sort(np.unique(rounded[:, 0]))
    rows = len(row_values)
    cols = len(col_values)
    if rows < 2 or cols < 2 or rows * cols != len(centers):
        return {}

    axis_index = {"x": 0, "y": 1, "z": 2}[axis]
    center_by_key: dict[tuple[float, float], np.ndarray] = {}
    for center in centers:
        key = (
            round(float(center[varying_axes[0]]), 4),
            round(float(center[varying_axes[1]]), 4),
        )
        center_by_key[key] = center

    ordered_centers: list[np.ndarray] = []
    for row_value in row_values:
        for col_value in col_values:
            center = center_by_key.get((float(col_value), float(row_value)))
            if center is None:
                return {}
            ordered_centers.append(center)

    origin = np.array(ordered_centers[0], dtype=np.float64)
    row_step = np.zeros(3, dtype=np.float64)
    col_step = np.zeros(3, dtype=np.float64)
    row_step[varying_axes[1]] = float(row_values[1] - row_values[0])
    col_step[varying_axes[0]] = float(col_values[1] - col_values[0])
    origin[axis_index] = float(np.mean(centers[:, axis_index]))

    expected: list[np.ndarray] = []
    for row_index in range(rows):
        for col_index in range(cols):
            expected.append(origin + row_index * row_step + col_index * col_step)
    expected_array = np.asarray(expected, dtype=np.float64)
    ordered_array = np.asarray(ordered_centers, dtype=np.float64)
    min_spacing = max(
        min(
            abs(float(row_step[varying_axes[1]])), abs(float(col_step[varying_axes[0]]))
        ),
        1e-9,
    )
    regularity_error = float(
        np.max(np.linalg.norm(ordered_array - expected_array, axis=1)) / min_spacing
    )
    if regularity_error > 0.08:
        return {}

    return {
        "grid_origin": [float(value) for value in origin],
        "grid_row_step": [float(value) for value in row_step],
        "grid_col_step": [float(value) for value in col_step],
        "grid_rows": int(rows),
        "grid_cols": int(cols),
        "grid_row_spacing": abs(float(row_step[varying_axes[1]])),
        "grid_col_spacing": abs(float(col_step[varying_axes[0]])),
        "grid_row_axis": ("x", "y", "z")[varying_axes[1]],
        "grid_col_axis": ("x", "y", "z")[varying_axes[0]],
        "regularity_error": regularity_error,
    }


def _try_counterbore_fit(
    component_vertices: np.ndarray,
    cutout_axis_index: int,
    plane_axes: list[int],
    height_span: float,
    span_min: float,
    span_max: float,
) -> Optional[dict[str, Any]]:
    """Try to detect a counterbore (stepped hole) in a connected component.

    Splits vertices by height along the cutout axis, looking for two
    concentric circles of different radii at different height segments.
    Returns a dict with counterbore parameters if found, or None.
    """
    height_values = component_vertices[:, cutout_axis_index]
    h_min = float(np.min(height_values))
    h_max = float(np.max(height_values))
    h_span = h_max - h_min
    if h_span < height_span * 0.5:
        return None

    # Fit circles on thin top/bottom slices first. This is more robust than
    # histogram gap splitting for meshes with quantized Z levels.
    slice_thickness = max(h_span * 0.20, 1e-9)
    lower_mask = height_values <= (h_min + slice_thickness)
    upper_mask = height_values >= (h_max - slice_thickness)

    lower_pts = component_vertices[lower_mask][:, plane_axes]
    upper_pts = component_vertices[upper_mask][:, plane_axes]
    if len(lower_pts) < 8 or len(upper_pts) < 8:
        return None

    lower_fit = _fit_circle_2d(lower_pts)
    upper_fit = _fit_circle_2d(upper_pts)
    if lower_fit is None or upper_fit is None:
        return None

    lower_center, lower_radius, lower_error, lower_coverage = lower_fit
    upper_center, upper_radius, upper_error, upper_coverage = upper_fit

    # Both fits must be reasonable.
    if lower_error > 0.12 or upper_error > 0.12:
        return None
    if lower_coverage < 0.60 or upper_coverage < 0.60:
        return None

    # Centers must be concentric.
    larger_radius = max(lower_radius, upper_radius)
    center_distance = float(np.linalg.norm(lower_center - upper_center))
    if center_distance > larger_radius * 0.10:
        return None

    # Radii must differ by at least 20%.
    smaller_radius = min(lower_radius, upper_radius)
    if smaller_radius <= 0:
        return None
    radius_ratio = larger_radius / smaller_radius
    if radius_ratio < 1.20:
        return None

    # Determine which radius is bore vs through-hole.
    if upper_radius > lower_radius:
        bore_radius = upper_radius
        through_radius = lower_radius
        bore_error = upper_error
        through_error = lower_error
        bore_coverage = upper_coverage
        through_coverage = lower_coverage
    else:
        bore_radius = lower_radius
        through_radius = upper_radius
        bore_error = lower_error
        through_error = upper_error
        bore_coverage = lower_coverage
        through_coverage = upper_coverage

    # Use a shared center estimate and classify vertices by nearest radius.
    center_2d = (lower_center + upper_center) * 0.5
    radii = np.linalg.norm(component_vertices[:, plane_axes] - center_2d, axis=1)
    to_bore = np.abs(radii - bore_radius)
    to_through = np.abs(radii - through_radius)
    bore_membership = to_bore <= to_through
    through_membership = ~bore_membership
    if np.count_nonzero(bore_membership) < 16 or np.count_nonzero(through_membership) < 16:
        return None

    bore_segment_heights = height_values[bore_membership]
    through_segment_heights = height_values[through_membership]
    bore_depth = float(np.max(bore_segment_heights) - np.min(bore_segment_heights))
    through_depth = float(np.max(through_segment_heights) - np.min(through_segment_heights))
    total_depth = float(h_max - h_min)

    if (
        bore_depth < total_depth * 0.10
        or through_depth < total_depth * 0.10
        or bore_depth > total_depth * 0.95
        or through_depth > total_depth * 0.95
    ):
        return None

    # Larger-radius bore should touch only one outer boundary plane.
    edge_tolerance = total_depth * 0.08
    bore_touches_min = np.min(bore_segment_heights) <= h_min + edge_tolerance
    bore_touches_max = np.max(bore_segment_heights) >= h_max - edge_tolerance
    if bore_touches_min == bore_touches_max:
        return None

    worst_error = max(bore_error, through_error)
    worst_coverage = min(bore_coverage, through_coverage)
    confidence = max(
        0.0,
        min(1.0, (1.0 - worst_error / 0.10) * worst_coverage),
    )

    return {
        "center_2d": center_2d,
        "through_radius": float(through_radius),
        "bore_radius": float(bore_radius),
        "bore_depth": float(bore_depth),
        "through_depth": float(through_depth),
        "total_depth": float(total_depth),
        "radial_error_ratio": float(worst_error),
        "angular_coverage": float(worst_coverage),
        "confidence": float(confidence),
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


def _fit_circle_2d(
    points: np.ndarray,
) -> Optional[tuple[np.ndarray, float, float, float]]:
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
    radial_error_ratio = float(
        np.percentile(np.abs(distances - radius), 90) / max(radius, 1e-9)
    )
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    bins = np.unique(np.floor(((angles + np.pi) / (2.0 * np.pi)) * 24.0).astype(int))
    angular_coverage = float(min(len(bins), 24) / 24.0)
    return center, radius, radial_error_ratio, angular_coverage


def _fit_axis_aligned_slot_2d(
    points: np.ndarray,
) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, int]]:
    if len(points) < 16:
        return None

    mins = np.min(points, axis=0)
    maxs = np.max(points, axis=0)
    spans = maxs - mins
    long_axis = int(np.argmax(spans))
    short_axis = 1 - long_axis
    length = float(spans[long_axis])
    width = float(spans[short_axis])
    if width <= 1e-9 or length / width < 1.40:
        return None

    radius = width * 0.5
    center = (mins + maxs) * 0.5
    straight_length = length - width
    if straight_length <= radius * 0.25:
        return None

    start = center.copy()
    end = center.copy()
    start[long_axis] -= straight_length * 0.5
    end[long_axis] += straight_length * 0.5

    segment = end - start
    segment_length_sq = float(np.dot(segment, segment))
    if segment_length_sq <= 1e-12:
        return None
    projections = np.clip(((points - start) @ segment) / segment_length_sq, 0.0, 1.0)
    closest = start + projections[:, None] * segment
    distances = np.linalg.norm(points - closest, axis=1)
    slot_error_ratio = float(
        np.percentile(np.abs(distances - radius), 90) / max(radius, 1e-9)
    )
    if slot_error_ratio > 0.16:
        return None

    # Require evidence for both caps and both straight sides to avoid treating noise as a slot.
    long_coords = points[:, long_axis]
    short_coords = points[:, short_axis]
    cap_tolerance = radius * 0.25
    side_tolerance = radius * 0.25
    has_start_cap = bool(np.any(long_coords <= start[long_axis] + cap_tolerance))
    has_end_cap = bool(np.any(long_coords >= end[long_axis] - cap_tolerance))
    middle_mask = (long_coords >= start[long_axis] - cap_tolerance) & (
        long_coords <= end[long_axis] + cap_tolerance
    )
    has_negative_side = bool(
        np.any(
            middle_mask & (short_coords <= center[short_axis] - radius + side_tolerance)
        )
    )
    has_positive_side = bool(
        np.any(
            middle_mask & (short_coords >= center[short_axis] + radius - side_tolerance)
        )
    )
    if not (has_start_cap and has_end_cap and has_negative_side and has_positive_side):
        return None

    return center, start, end, width, length, slot_error_ratio, long_axis


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


def _slot_near_outer_boundary(
    start_2d: np.ndarray,
    end_2d: np.ndarray,
    radius: float,
    bbox: dict[str, float],
    plane_axes: list[int],
) -> bool:
    labels = ("x", "y", "z")
    for local_axis, axis_index in enumerate(plane_axes):
        min_coord = float(bbox[f"min_{labels[axis_index]}"])
        max_coord = float(bbox[f"max_{labels[axis_index]}"])
        feature_min = (
            min(float(start_2d[local_axis]), float(end_2d[local_axis])) - radius
        )
        feature_max = (
            max(float(start_2d[local_axis]), float(end_2d[local_axis])) + radius
        )
        if feature_min <= min_coord + radius * 0.1:
            return True
        if feature_max >= max_coord - radius * 0.1:
            return True
    return False


def _relative_or_absolute(path: Path, root_dir: Optional[Union[Path, str]]) -> str:
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
