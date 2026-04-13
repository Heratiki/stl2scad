"""
Feature-level STL inventory for parametric reconstruction planning.

This module intentionally does not generate SCAD. It summarizes broad geometry
signals from arbitrary STL files so reconstruction work can be guided by real
user models instead of only primitive fixtures.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Union

import numpy as np
from stl.mesh import Mesh

STL_SUFFIXES = {".stl"}
_AXES = {
    "+x": np.array([1.0, 0.0, 0.0], dtype=np.float64),
    "-x": np.array([-1.0, 0.0, 0.0], dtype=np.float64),
    "+y": np.array([0.0, 1.0, 0.0], dtype=np.float64),
    "-y": np.array([0.0, -1.0, 0.0], dtype=np.float64),
    "+z": np.array([0.0, 0.0, 1.0], dtype=np.float64),
    "-z": np.array([0.0, 0.0, -1.0], dtype=np.float64),
}


@dataclass(frozen=True)
class InventoryConfig:
    recursive: bool = True
    max_files: Optional[int] = None
    workers: int = 1
    symmetry_tolerance: float = 1e-4
    normal_axis_threshold: float = 0.96
    spacing_tolerance: float = 1e-4


def analyze_stl_folder(
    input_dir: Union[Path, str],
    output_json: Union[Path, str],
    config: InventoryConfig = InventoryConfig(),
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    """
    Analyze STL files in a folder and write a JSON inventory report.

    ``progress_callback``, when provided, is called after each file completes
    with ``(completed_count, total_count, file_path_str)``.
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    if not input_path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_path}")

    files = list(_iter_stl_files(input_path, recursive=config.recursive))
    if config.max_files is not None:
        files = files[: config.max_files]

    total = len(files)
    worker_count = max(1, int(config.workers))
    if worker_count == 1 or total <= 1:
        results = []
        for idx, path in enumerate(files, 1):
            result = analyze_stl_file(path, root_dir=input_path, config=config)
            results.append(result)
            if progress_callback is not None:
                progress_callback(idx, total, str(path))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_path = {
                executor.submit(
                    _analyze_stl_file_worker, (path, input_path, config)
                ): path
                for path in files
            }
            result_map: dict[Path, dict[str, Any]] = {}
            done_count = 0
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                result_map[path] = future.result()
                done_count += 1
                if progress_callback is not None:
                    progress_callback(done_count, total, str(path))
            results = [result_map[path] for path in files]
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_path),
        "config": {
            "recursive": config.recursive,
            "max_files": config.max_files,
            "workers": worker_count,
            "symmetry_tolerance": config.symmetry_tolerance,
            "normal_axis_threshold": config.normal_axis_threshold,
            "spacing_tolerance": config.spacing_tolerance,
        },
        "summary": _summarize_results(results),
        "files": results,
    }

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return report


def build_feature_graphs_from_inventory(
    inventory: Union[dict[str, Any], Path, str],
    output_json: Union[Path, str],
    workers: int = 1,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    """
    Build feature graphs only for files classified as mechanical candidates.

    ``inventory`` may be a previously loaded inventory-report dictionary or a path
    to an inventory JSON file produced by ``analyze_stl_folder``.
    """
    inventory_report = _load_inventory_report(inventory)
    input_dir_value = inventory_report.get("input_dir")
    input_dir = Path(input_dir_value) if input_dir_value else None
    inventory_files = inventory_report.get("files")
    if not isinstance(inventory_files, list):
        raise ValueError("Inventory report must contain a files list")

    selected_entries = [
        result
        for result in inventory_files
        if result.get("status") == "ok"
        and result.get("classification", {}).get("primary") == "mechanical_candidate"
    ]
    resolved_files = [
        _resolve_inventory_entry_path(entry, input_dir) for entry in selected_entries
    ]
    worker_count = max(1, int(workers))

    if worker_count == 1 or len(resolved_files) <= 1:
        graphs = []
        for idx, path in enumerate(resolved_files, 1):
            graph = _build_feature_graph_from_inventory_file(path, input_dir)
            graphs.append(graph)
            if progress_callback is not None:
                progress_callback(idx, len(resolved_files), str(path))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_path = {
                executor.submit(
                    _build_feature_graph_from_inventory_worker,
                    (path, input_dir),
                ): path
                for path in resolved_files
            }
            graph_map: dict[Path, dict[str, Any]] = {}
            done_count = 0
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                graph_map[path] = future.result()
                done_count += 1
                if progress_callback is not None:
                    progress_callback(done_count, len(resolved_files), str(path))
            graphs = [graph_map[path] for path in resolved_files]

    skipped_non_mechanical_count = sum(
        1
        for result in inventory_files
        if result.get("status") == "ok"
        and result.get("classification", {}).get("primary") != "mechanical_candidate"
    )
    skipped_error_count = sum(
        1 for result in inventory_files if result.get("status") != "ok"
    )
    source_inventory = str(inventory) if isinstance(inventory, (str, Path)) else None

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inventory_source": source_inventory,
        "input_dir": str(input_dir) if input_dir is not None else None,
        "config": {
            "workers": worker_count,
        },
        "selection": {
            "inventory_file_count": len(inventory_files),
            "mechanical_candidate_count": len(selected_entries),
            "skipped_non_mechanical_count": skipped_non_mechanical_count,
            "skipped_error_count": skipped_error_count,
        },
        "summary": _summarize_graphs(graphs),
        "graphs": graphs,
    }

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return report


def _analyze_stl_file_worker(
    args: tuple[Path, Path, InventoryConfig],
) -> dict[str, Any]:
    path, root_dir, config = args
    return analyze_stl_file(path, root_dir=root_dir, config=config)


def _build_feature_graph_from_inventory_worker(
    args: tuple[Path, Optional[Path]],
) -> dict[str, Any]:
    path, root_dir = args
    return _build_feature_graph_from_inventory_file(path, root_dir)


def _build_feature_graph_from_inventory_file(
    path: Path,
    root_dir: Optional[Path],
) -> dict[str, Any]:
    from .feature_graph import build_feature_graph_for_stl

    try:
        return build_feature_graph_for_stl(path, root_dir=root_dir)
    except Exception as exc:
        return {
            "schema_version": 1,
            "source_file": _relative_or_absolute(path, root_dir),
            "status": "error",
            "error": str(exc),
            "features": [],
        }


def analyze_stl_file(
    stl_file: Union[Path, str],
    root_dir: Optional[Union[Path, str]] = None,
    config: InventoryConfig = InventoryConfig(),
) -> dict[str, Any]:
    """
    Analyze one STL file and return geometry/feature signals.
    """
    path = Path(stl_file)
    payload: dict[str, Any] = {
        "file": _relative_or_absolute(path, root_dir),
        "status": "ok",
    }
    try:
        mesh = Mesh.from_file(str(path))
        vectors = np.asarray(mesh.vectors, dtype=np.float64)
        points = vectors.reshape(-1, 3)
        unique_points = _unique_points(points, tolerance=config.symmetry_tolerance)
        normals = _normalized_normals(np.asarray(mesh.normals, dtype=np.float64))
        face_areas = _triangle_areas(vectors)
        bbox = _bbox(unique_points)
        volume, _cog, _inertia = mesh.get_mass_properties()
        surface_area = float(np.sum(face_areas))
    except Exception as exc:
        payload["status"] = "error"
        payload["error"] = str(exc)
        return payload

    payload.update(
        {
            "triangles": int(len(vectors)),
            "unique_vertices": int(len(unique_points)),
            "bounding_box": bbox,
            "volume": float(volume),
            "surface_area": surface_area,
            "normal_axis_profile": _normal_axis_profile(
                normals,
                face_areas,
                threshold=config.normal_axis_threshold,
            ),
            "symmetry": _symmetry_scores(
                unique_points, bbox, config.symmetry_tolerance
            ),
            "coordinate_spacing": _coordinate_spacing_signals(
                unique_points,
                tolerance=config.spacing_tolerance,
            ),
        }
    )
    payload["classification"] = _classify_inventory(payload)
    payload["candidate_features"] = _candidate_features(payload)
    return payload


def _iter_stl_files(input_dir: Path, recursive: bool) -> Iterable[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in input_dir.glob(pattern)
        if path.is_file() and path.suffix.lower() in STL_SUFFIXES
    )


def _relative_or_absolute(path: Path, root_dir: Optional[Union[Path, str]]) -> str:
    if root_dir is None:
        return str(path)
    try:
        return str(path.relative_to(Path(root_dir)))
    except ValueError:
        return str(path)


def _load_inventory_report(
    inventory: Union[dict[str, Any], Path, str],
) -> dict[str, Any]:
    if isinstance(inventory, dict):
        return inventory
    path = Path(inventory)
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_inventory_entry_path(
    entry: dict[str, Any],
    input_dir: Optional[Path],
) -> Path:
    file_value = entry.get("file")
    if not isinstance(file_value, str) or not file_value:
        raise ValueError("Inventory entries must contain a non-empty file path")
    path = Path(file_value)
    if path.is_absolute() or input_dir is None:
        return path
    return input_dir / path


def _unique_points(points: np.ndarray, tolerance: float) -> np.ndarray:
    if len(points) == 0:
        return np.zeros((0, 3), dtype=np.float64)
    scale = 1.0 / max(float(tolerance), 1e-12)
    quantized = np.round(points * scale).astype(np.int64)
    _unique_quantized, first_indices = np.unique(quantized, axis=0, return_index=True)
    return points[np.sort(first_indices)]


def _normalized_normals(normals: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(normals, axis=1)
    safe = lengths > 1e-12
    normalized = np.zeros_like(normals, dtype=np.float64)
    normalized[safe] = normals[safe] / lengths[safe, None]
    return normalized


def _triangle_areas(vectors: np.ndarray) -> np.ndarray:
    if len(vectors) == 0:
        return np.zeros(0, dtype=np.float64)
    edges_a = vectors[:, 1] - vectors[:, 0]
    edges_b = vectors[:, 2] - vectors[:, 0]
    return 0.5 * np.linalg.norm(np.cross(edges_a, edges_b), axis=1)


def _bbox(points: np.ndarray) -> dict[str, float]:
    if len(points) == 0:
        return {
            "min_x": 0.0,
            "min_y": 0.0,
            "min_z": 0.0,
            "max_x": 0.0,
            "max_y": 0.0,
            "max_z": 0.0,
            "width": 0.0,
            "height": 0.0,
            "depth": 0.0,
            "diagonal": 0.0,
        }
    min_coords = points.min(axis=0)
    max_coords = points.max(axis=0)
    dims = max_coords - min_coords
    return {
        "min_x": float(min_coords[0]),
        "min_y": float(min_coords[1]),
        "min_z": float(min_coords[2]),
        "max_x": float(max_coords[0]),
        "max_y": float(max_coords[1]),
        "max_z": float(max_coords[2]),
        "width": float(dims[0]),
        "height": float(dims[1]),
        "depth": float(dims[2]),
        "diagonal": float(np.linalg.norm(dims)),
    }


def _normal_axis_profile(
    normals: np.ndarray,
    face_areas: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    total_area = float(np.sum(face_areas))
    if total_area <= 1e-12 or len(normals) == 0:
        return {"axis_area_ratio": 0.0, "clusters": {}}

    clusters: dict[str, Any] = {}
    axis_area = 0.0
    for label, axis in _AXES.items():
        mask = normals @ axis >= threshold
        area = float(np.sum(face_areas[mask]))
        axis_area += area
        clusters[label] = {
            "face_count": int(np.count_nonzero(mask)),
            "area": area,
            "area_ratio": float(area / total_area),
        }

    return {
        "axis_area_ratio": float(min(axis_area / total_area, 1.0)),
        "clusters": clusters,
    }


def _symmetry_scores(
    points: np.ndarray,
    bbox: dict[str, float],
    tolerance: float,
) -> dict[str, float]:
    if len(points) == 0:
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    scale = 1.0 / max(float(tolerance), bbox.get("diagonal", 0.0) * 1e-5, 1e-9)
    quantized = {tuple(row) for row in np.round(points * scale).astype(np.int64)}
    centers = np.array(
        [
            (bbox["min_x"] + bbox["max_x"]) * 0.5,
            (bbox["min_y"] + bbox["max_y"]) * 0.5,
            (bbox["min_z"] + bbox["max_z"]) * 0.5,
        ],
        dtype=np.float64,
    )

    scores: dict[str, float] = {}
    for axis_index, axis_name in enumerate(("x", "y", "z")):
        mirrored = points.copy()
        mirrored[:, axis_index] = 2.0 * centers[axis_index] - mirrored[:, axis_index]
        mirrored_quantized = np.round(mirrored * scale).astype(np.int64)
        matches = sum(tuple(row) in quantized for row in mirrored_quantized)
        scores[axis_name] = float(matches / max(len(points), 1))
    return scores


def _coordinate_spacing_signals(
    points: np.ndarray,
    tolerance: float,
) -> dict[str, Any]:
    signals: dict[str, Any] = {}
    for axis_index, axis_name in enumerate(("x", "y", "z")):
        values = np.unique(np.round(points[:, axis_index] / tolerance) * tolerance)
        diffs = np.diff(np.sort(values))
        diffs = diffs[diffs > tolerance * 2.0]
        if len(diffs) == 0:
            signals[axis_name] = {"level_count": int(len(values)), "regular": False}
            continue
        median = float(np.median(diffs))
        regularity = float(
            np.mean(np.abs(diffs - median) <= max(tolerance * 10.0, median * 0.03))
        )
        plausible_parametric_levels = 3 <= len(values) <= 256
        signals[axis_name] = {
            "level_count": int(len(values)),
            "median_spacing": median,
            "regularity": regularity,
            "regular": bool(
                plausible_parametric_levels and len(diffs) >= 2 and regularity >= 0.8
            ),
        }
    return signals


def _classify_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    bbox = payload["bounding_box"]
    normal_profile = payload["normal_axis_profile"]
    axis_ratio = float(normal_profile["axis_area_ratio"])
    triangle_count = int(payload["triangles"])
    symmetry = payload["symmetry"]
    regular_axes = [
        axis
        for axis, data in payload["coordinate_spacing"].items()
        if bool(data.get("regular"))
    ]

    mechanical_score = 0.0
    mechanical_score += min(axis_ratio, 1.0) * 0.45
    mechanical_score += min(sum(symmetry.values()) / 3.0, 1.0) * 0.25
    mechanical_score += min(len(regular_axes) / 3.0, 1.0) * 0.20
    if triangle_count < 10000:
        mechanical_score += 0.10

    organic_score = 0.0
    organic_score += max(0.0, 1.0 - axis_ratio) * 0.55
    if triangle_count > 10000:
        organic_score += 0.25
    if max(symmetry.values(), default=0.0) < 0.5:
        organic_score += 0.20

    nonzero_dims = sum(
        1 for dim in ("width", "height", "depth") if float(bbox.get(dim, 0.0)) > 1e-9
    )
    primary = (
        "mechanical_candidate"
        if mechanical_score >= organic_score
        else "organic_candidate"
    )
    if nonzero_dims < 3:
        primary = "degenerate_or_flat_candidate"

    return {
        "primary": primary,
        "mechanical_score": float(min(mechanical_score, 1.0)),
        "organic_score": float(min(organic_score, 1.0)),
        "regular_axes": regular_axes,
    }


def _candidate_features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    normal_profile = payload["normal_axis_profile"]
    if normal_profile["axis_area_ratio"] >= 0.55:
        features.append(
            {
                "type": "dominant_axis_aligned_planes",
                "confidence": float(normal_profile["axis_area_ratio"]),
                "note": "Potential plates, boxes, slots, tabs, or orthogonal cutouts.",
            }
        )

    symmetry = payload["symmetry"]
    for axis, score in symmetry.items():
        if score >= 0.85:
            features.append(
                {
                    "type": "mirror_symmetry",
                    "axis": axis,
                    "confidence": float(score),
                    "note": "Candidate for symmetric parametric module generation.",
                }
            )

    for axis, data in payload["coordinate_spacing"].items():
        if data.get("regular"):
            features.append(
                {
                    "type": "regular_coordinate_spacing",
                    "axis": axis,
                    "confidence": float(data.get("regularity", 0.0)),
                    "median_spacing": data.get("median_spacing"),
                    "note": "Candidate repeated-grid or array dimension.",
                }
            )

    if not features:
        features.append(
            {
                "type": "freeform_or_unclassified",
                "confidence": 0.0,
                "note": "No strong generic editable feature signal found yet.",
            }
        )
    return features


def _summarize_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ok = [result for result in results if result.get("status") == "ok"]
    errors = [result for result in results if result.get("status") != "ok"]
    classifications: dict[str, int] = {}
    feature_counts: dict[str, int] = {}
    for result in ok:
        primary = result.get("classification", {}).get("primary", "unknown")
        classifications[primary] = classifications.get(primary, 0) + 1
        for feature in result.get("candidate_features", []):
            feature_type = str(feature.get("type", "unknown"))
            feature_counts[feature_type] = feature_counts.get(feature_type, 0) + 1

    return {
        "file_count": len(results),
        "ok_count": len(ok),
        "error_count": len(errors),
        "classification_counts": classifications,
        "candidate_feature_counts": feature_counts,
    }


def _summarize_graphs(graphs: Sequence[dict[str, Any]]) -> dict[str, Any]:
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
