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
