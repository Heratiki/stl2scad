"""
CGAL backend adapter (Phase 2 skeleton).

Current integration boundary:
- optional external helper executable
- JSON request/response over stdin/stdout
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Optional, Union

import numpy as np
import stl

CGAL_HELPER_ENV_VAR = "STL2SCAD_CGAL_HELPER"
DEFAULT_CGAL_HELPER_NAMES = (
    "stl2scad-cgal-helper",
    "stl2scad-cgal-helper.exe",
    "stl2scad-cgal-helper.py",
)
_FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_VECTOR_RE = rf"\(\s*({_FLOAT_RE})\s*,\s*({_FLOAT_RE})\s*,\s*({_FLOAT_RE})\s*\)"
_SPHERE_RE = re.compile(
    rf"Type:\s*sphere\s+center:\s*{_VECTOR_RE}\s+radius:\s*({_FLOAT_RE})\s+#Pts:\s*(\d+)"
)
_CYLINDER_RE = re.compile(
    rf"Type:\s*cylinder\s+center:\s*{_VECTOR_RE}\s+axis:\s*{_VECTOR_RE}\s+radius:\s*({_FLOAT_RE})\s+#Pts:\s*(\d+)"
)
_CONE_RE = re.compile(
    rf"Type:\s*cone\s+apex:\s*{_VECTOR_RE}\s+axis:\s*{_VECTOR_RE}\s+angle:\s*({_FLOAT_RE})\s+#Pts:\s*(\d+)"
)
_MIN_CGAL_PYTHON_COVERAGE = 0.85
_MIN_CGAL_MULTI_COMPONENT_COVERAGE = 0.20
_MIN_CGAL_MULTI_TOTAL_COVERAGE = 0.85
_MAX_CGAL_MULTI_COMPONENTS = 6


@dataclass
class CgalDetectionResult:
    detected: bool
    scad: Optional[str] = None
    primitive_type: Optional[str] = None
    confidence: Optional[float] = None
    diagnostics: Optional[dict[str, Any]] = None


@dataclass
class CgalBackendCapabilities:
    helper_mode: Optional[str]
    cgal_bindings_available: bool
    operations: list[str]
    supported_primitives: list[str]
    engines: list[str]
    raw: dict[str, Any]


def has_cgal_python_bindings() -> bool:
    return _has_module("CGAL") or _has_module("cgal")


def resolve_cgal_helper_path(explicit_path: Optional[str] = None) -> Optional[str]:
    """
    Resolve helper executable path from explicit arg, env var, or PATH search.
    """
    candidates: list[Optional[str]] = [
        explicit_path,
        os.getenv(CGAL_HELPER_ENV_VAR),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if path.exists() and path.is_file():
            return str(path)

    for helper_name in DEFAULT_CGAL_HELPER_NAMES:
        found = shutil.which(helper_name)
        if found:
            return found
    return None


def is_cgal_backend_available() -> bool:
    return has_cgal_python_bindings() or (resolve_cgal_helper_path() is not None)


def get_cgal_backend_capabilities(
    helper_path: Optional[str] = None,
    timeout_seconds: int = 20,
) -> Optional[CgalBackendCapabilities]:
    """
    Query helper capabilities for diagnostics and release checks.

    Returns None if no helper is available or the helper does not implement the
    capabilities command.
    """
    resolved_helper = resolve_cgal_helper_path(helper_path)
    if not resolved_helper:
        if has_cgal_python_bindings():
            return CgalBackendCapabilities(
                helper_mode=None,
                cgal_bindings_available=True,
                operations=["detect_primitive"],
                supported_primitives=["sphere", "cylinder", "cone", "composite_union"],
                engines=["cgal_python_bindings"],
                raw={
                    "schema_version": 1,
                    "helper_mode": None,
                    "cgal_bindings_available": True,
                    "operations": ["detect_primitive"],
                    "supported_primitives": [
                        "sphere",
                        "cylinder",
                        "cone",
                        "composite_union",
                    ],
                    "engines": ["cgal_python_bindings"],
                    "notes": (
                        "Direct Python binding path accepts high-coverage "
                        "sphere/cylinder/cone detections and conservative non-overlapping "
                        "multi-shape unions; other shapes fall back."
                    ),
                },
            )
        return None

    try:
        command = _build_helper_command(resolved_helper)
        command.extend(["capabilities", "--format", "json"])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception:
        logging.debug("CGAL helper capability query failed.", exc_info=True)
        return None

    if result.returncode != 0:
        logging.info(
            "CGAL helper capability query returned non-zero exit code (%s): %s",
            result.returncode,
            (result.stderr or "").strip(),
        )
        return None

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        logging.info("CGAL helper capability query produced non-JSON output.")
        return None

    return CgalBackendCapabilities(
        helper_mode=(
            data.get("helper_mode")
            if isinstance(data.get("helper_mode"), str)
            else None
        ),
        cgal_bindings_available=bool(data.get("cgal_bindings_available", False)),
        operations=_string_list(data.get("operations")),
        supported_primitives=_string_list(data.get("supported_primitives")),
        engines=_string_list(data.get("engines")),
        raw=data,
    )


def detect_primitive_with_cgal(
    mesh: stl.mesh.Mesh,
    tolerance: float = 0.01,
    helper_path: Optional[str] = None,
    timeout_seconds: int = 20,
) -> Optional[CgalDetectionResult]:
    """
    Detect primitive via CGAL Python bindings or the helper boundary.

    Returns None if no helper is available or helper execution fails.
    """
    cgal_python_result = _detect_primitive_with_cgal_python_bindings(
        mesh,
        tolerance=tolerance,
    )
    if cgal_python_result is not None:
        return cgal_python_result

    resolved_helper = resolve_cgal_helper_path(helper_path)
    if not resolved_helper:
        return None

    request_payload = {
        "operation": "detect_primitive",
        "tolerance": float(tolerance),
        "mesh": {
            "triangles": mesh.vectors.tolist(),
        },
    }

    try:
        command = _build_helper_command(resolved_helper)
        command.extend(["detect-primitive", "--format", "json"])
        result = subprocess.run(
            command,
            input=json.dumps(request_payload),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception:
        logging.debug("CGAL helper execution failed.", exc_info=True)
        return None

    if result.returncode != 0:
        logging.info(
            "CGAL helper returned non-zero exit code (%s): %s",
            result.returncode,
            (result.stderr or "").strip(),
        )
        return None

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        logging.info("CGAL helper produced non-JSON output.")
        return None

    detected = bool(data.get("detected", False))
    scad = data.get("scad")
    primitive_type = data.get("primitive_type")
    confidence_raw = data.get("confidence")
    confidence: Optional[float] = None
    if confidence_raw is not None:
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = None

    diagnostics = data.get("diagnostics")
    if diagnostics is not None and not isinstance(diagnostics, dict):
        diagnostics = {"raw": diagnostics}

    if detected and isinstance(scad, str) and scad.strip():
        return CgalDetectionResult(
            detected=True,
            scad=scad,
            primitive_type=primitive_type if isinstance(primitive_type, str) else None,
            confidence=confidence,
            diagnostics=diagnostics,
        )

    return CgalDetectionResult(
        detected=False,
        primitive_type=primitive_type if isinstance(primitive_type, str) else None,
        confidence=confidence,
        diagnostics=diagnostics,
    )


def _split_mesh_into_components(
    mesh: stl.mesh.Mesh,
    vertex_tolerance: float = 1e-4,
) -> list[stl.mesh.Mesh]:
    """Split a mesh into vertex-connected components via Union-Find.

    Two triangles are in the same component if they share a vertex (within
    ``vertex_tolerance``).  Completely disjoint sub-meshes (e.g. a sphere and
    a translated cylinder merged into one STL) are split into separate entries.
    Returns a list of sub-meshes ordered by descending triangle count.
    """
    vectors = np.asarray(mesh.vectors, dtype=np.float64)
    n = len(vectors)
    if n == 0:
        return []

    scale = 1.0 / max(vertex_tolerance, 1e-12)
    vertex_to_tris: dict[tuple, list[int]] = {}
    for i, tri in enumerate(vectors):
        for v in tri:
            key = (
                int(round(float(v[0]) * scale)),
                int(round(float(v[1]) * scale)),
                int(round(float(v[2]) * scale)),
            )
            vertex_to_tris.setdefault(key, []).append(i)

    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for tri_list in vertex_to_tris.values():
        root = _find(tri_list[0])
        for j in range(1, len(tri_list)):
            r = _find(tri_list[j])
            if r != root:
                parent[r] = root

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_find(i), []).append(i)

    if len(groups) <= 1:
        return [mesh]

    result: list[stl.mesh.Mesh] = []
    for tri_indices in sorted(groups.values(), key=len, reverse=True):
        idx = np.array(tri_indices, dtype=np.intp)
        sub = stl.mesh.Mesh(np.zeros(len(idx), dtype=stl.mesh.Mesh.dtype))
        sub.vectors = vectors[idx]
        if hasattr(sub, "update_normals"):
            sub.update_normals()
        result.append(sub)
    return result


def _cgal_ransac_best_shape_for_component(
    mesh: stl.mesh.Mesh,
    tolerance: float,
    cgal_kernel: Any,
    cgal_point_set: Any,
    cgal_shape_detection: Any,
) -> Optional[dict[str, Any]]:
    """Run RANSAC on a single mesh component and return the best detected shape.

    ``min_points`` is based only on this component's point count so smaller
    components (e.g. a cylinder beside a much larger sphere) are not excluded.
    """
    points, normals = _mesh_triangle_centroids_and_normals(mesh)
    if len(points) < 10:
        return None

    point_set = cgal_point_set.Point_set_3()
    normal_map = point_set.add_normal_map()
    for point, normal in zip(points, normals):
        index = point_set.insert(
            cgal_kernel.Point_3(float(point[0]), float(point[1]), float(point[2]))
        )
        normal_map.set(
            index,
            cgal_kernel.Vector_3(float(normal[0]), float(normal[1]), float(normal[2])),
        )

    shape_map = point_set.add_int_map("shape", -1)
    bbox_diag = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    epsilon = max(float(tolerance) * max(bbox_diag, 1.0), bbox_diag * 0.02, 0.01)
    cluster_epsilon = max(epsilon * 2.0, 0.01)

    # Run a few deterministic-ish retries because CGAL RANSAC can be
    # probabilistic and small components are sensitive to sampling.
    for min_points_ratio in (0.05, 0.03, 0.02):
        for probability in (0.01, 0.05):
            try:
                shapes = cgal_shape_detection.efficient_RANSAC(
                    point_set,
                    shape_map,
                    min_points=max(10, int(len(points) * min_points_ratio)),
                    epsilon=epsilon,
                    cluster_epsilon=cluster_epsilon,
                    normal_threshold=0.75,
                    probability=probability,
                    planes=True,
                    cones=True,
                    cylinders=True,
                    spheres=True,
                    tori=False,
                )
            except Exception:
                logging.debug("CGAL RANSAC failed for component.", exc_info=True)
                continue

            parsed = [
                _enrich_shape_geometry_from_points(
                    _parse_cgal_shape_description(str(shape), len(points)),
                    points,
                )
                for shape in shapes
            ]
            good = [
                s
                for s in parsed
                if s is not None
                and s.get("primitive_type") in {"sphere", "cylinder", "cone"}
            ]
            if good:
                return max(good, key=lambda s: float(s.get("coverage", 0.0)))
    return None


def _detect_primitive_with_cgal_python_bindings(
    mesh: stl.mesh.Mesh,
    tolerance: float,
) -> Optional[CgalDetectionResult]:
    if not has_cgal_python_bindings():
        return None

    try:
        from CGAL import CGAL_Kernel as cgal_kernel
        from CGAL import CGAL_Point_set_3 as cgal_point_set
        from CGAL import CGAL_Shape_detection as cgal_shape_detection
    except Exception:
        logging.debug("CGAL Python binding import failed.", exc_info=True)
        return None

    # --- per-component path for disconnected meshes ---
    # When the mesh contains N geometrically separate bodies (e.g. a sphere and
    # a translated cylinder), running RANSAC on the merged point cloud lets the
    # dominant primitive absorb enough points to cross the single-shape coverage
    # threshold before the smaller primitive is detected.  Splitting first and
    # running RANSAC per component avoids that collapse.
    components = _split_mesh_into_components(mesh)
    if len(components) >= 2:
        component_shapes: list[dict[str, Any]] = []
        for comp in components[: _MAX_CGAL_MULTI_COMPONENTS]:
            best = _cgal_ransac_best_shape_for_component(
                comp, tolerance, cgal_kernel, cgal_point_set, cgal_shape_detection
            )
            if best is not None:
                component_shapes.append(best)
        if len(component_shapes) >= 2:
            multi_scad, multi_confidence, multi_shapes, multi_reason = (
                _try_assemble_multi_shape_union(component_shapes)
            )
            all_points, _ = _mesh_triangle_centroids_and_normals(mesh)
            comp_diagnostics: dict[str, Any] = {
                "engine": "cgal_python_bindings",
                "cgal_bindings_available": True,
                "triangle_count": int(len(mesh.vectors)),
                "sample_point_count": int(len(all_points)),
                "component_count": len(components),
                "multi_shape_attempted": True,
                "shapes": component_shapes,
            }
            if multi_shapes is not None:
                comp_diagnostics["multi_shape_selected_count"] = len(multi_shapes)
                comp_diagnostics["multi_shape_selected"] = multi_shapes
            if multi_reason:
                comp_diagnostics["multi_shape_reason"] = multi_reason
            if multi_scad is not None:
                return CgalDetectionResult(
                    detected=True,
                    scad=multi_scad,
                    primitive_type="composite_union",
                    confidence=multi_confidence,
                    diagnostics=comp_diagnostics,
                )

    # --- full-mesh RANSAC fallback (existing logic) ---
    points, normals = _mesh_triangle_centroids_and_normals(mesh)
    if len(points) < 10:
        return None

    point_set = cgal_point_set.Point_set_3()
    normal_map = point_set.add_normal_map()
    for point, normal in zip(points, normals):
        index = point_set.insert(
            cgal_kernel.Point_3(float(point[0]), float(point[1]), float(point[2]))
        )
        normal_map.set(
            index,
            cgal_kernel.Vector_3(float(normal[0]), float(normal[1]), float(normal[2])),
        )

    shape_map = point_set.add_int_map("shape", -1)
    bbox_diag = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    epsilon = max(float(tolerance) * max(bbox_diag, 1.0), bbox_diag * 0.02, 0.01)
    cluster_epsilon = max(epsilon * 2.0, 0.01)

    try:
        shapes = cgal_shape_detection.efficient_RANSAC(
            point_set,
            shape_map,
            min_points=max(10, int(len(points) * 0.1)),
            epsilon=epsilon,
            cluster_epsilon=cluster_epsilon,
            normal_threshold=0.75,
            probability=0.01,
            planes=True,
            cones=True,
            cylinders=True,
            spheres=True,
            tori=False,
        )
    except Exception:
        logging.debug("CGAL Python shape detection failed.", exc_info=True)
        return None

    parsed = [
        _enrich_shape_geometry_from_points(
            _parse_cgal_shape_description(str(shape), len(points)),
            points,
        )
        for shape in shapes
    ]
    parsed_shapes: list[dict[str, Any]] = [
        shape for shape in parsed if shape is not None
    ]
    diagnostics: dict[str, Any] = {
        "engine": "cgal_python_bindings",
        "cgal_bindings_available": True,
        "triangle_count": int(len(mesh.vectors)),
        "sample_point_count": int(len(points)),
        "epsilon": float(epsilon),
        "cluster_epsilon": float(cluster_epsilon),
        "shapes": parsed_shapes,
    }
    if not parsed_shapes:
        diagnostics["reason"] = "no_shapes_detected"
        return CgalDetectionResult(detected=False, diagnostics=diagnostics)

    parsed_shapes.sort(key=lambda item: float(item["coverage"]), reverse=True)
    best = parsed_shapes[0]
    if best["primitive_type"] not in {"sphere", "cylinder", "cone"}:
        diagnostics["reason"] = "unsupported_best_shape"
        return CgalDetectionResult(
            detected=False,
            primitive_type=str(best["primitive_type"]),
            confidence=float(best["coverage"]),
            diagnostics=diagnostics,
        )

    # When multiple shapes each meet the per-component threshold, prefer the
    # composite_union path so a sphere + cylinder mesh is not collapsed to just
    # the sphere (which alone can exceed the single-shape coverage threshold).
    multi_candidates = [
        shape
        for shape in parsed_shapes
        if shape.get("primitive_type") in {"sphere", "cylinder", "cone"}
        and float(shape.get("coverage", 0.0)) >= _MIN_CGAL_MULTI_COMPONENT_COVERAGE
    ]
    if len(multi_candidates) >= 2:
        multi_scad, multi_confidence, multi_shapes, multi_reason = (
            _try_assemble_multi_shape_union(parsed_shapes)
        )
        diagnostics["multi_shape_attempted"] = True
        if multi_shapes is not None:
            diagnostics["multi_shape_selected_count"] = len(multi_shapes)
            diagnostics["multi_shape_selected"] = multi_shapes
        if multi_reason:
            diagnostics["multi_shape_reason"] = multi_reason
        if multi_scad is not None:
            return CgalDetectionResult(
                detected=True,
                scad=multi_scad,
                primitive_type="composite_union",
                confidence=multi_confidence,
                diagnostics=diagnostics,
            )

    if float(best["coverage"]) >= _MIN_CGAL_PYTHON_COVERAGE:
        scad = _shape_description_to_scad(best)
        if scad is not None:
            return CgalDetectionResult(
                detected=True,
                scad=scad,
                primitive_type=str(best["primitive_type"]),
                confidence=float(best["coverage"]),
                diagnostics=diagnostics,
            )
        diagnostics["single_shape_scad_failed"] = True

    if not diagnostics.get("multi_shape_attempted"):
        multi_scad, multi_confidence, multi_shapes, multi_reason = (
            _try_assemble_multi_shape_union(parsed_shapes)
        )
        diagnostics["multi_shape_attempted"] = True
        if multi_shapes is not None:
            diagnostics["multi_shape_selected_count"] = len(multi_shapes)
            diagnostics["multi_shape_selected"] = multi_shapes
        if multi_reason:
            diagnostics["multi_shape_reason"] = multi_reason
        if multi_scad is not None:
            return CgalDetectionResult(
                detected=True,
                scad=multi_scad,
                primitive_type="composite_union",
                confidence=multi_confidence,
                diagnostics=diagnostics,
            )

    diagnostics["reason"] = (
        diagnostics.get("multi_shape_reason") or "low_shape_coverage"
    )
    return CgalDetectionResult(
        detected=False,
        primitive_type=str(best["primitive_type"]),
        confidence=float(best["coverage"]),
        diagnostics=diagnostics,
    )


def _mesh_triangle_centroids_and_normals(
    mesh: stl.mesh.Mesh,
) -> tuple[np.ndarray, np.ndarray]:
    points = np.mean(np.asarray(mesh.vectors, dtype=np.float64), axis=1)
    normals = np.asarray(mesh.normals, dtype=np.float64)
    lengths = np.linalg.norm(normals, axis=1)
    safe = lengths > 1e-12
    normalized = np.zeros_like(normals)
    normalized[safe] = normals[safe] / lengths[safe, None]
    normalized[~safe] = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    return points, normalized


def _parse_cgal_shape_description(
    description: str,
    total_points: int,
) -> Optional[dict[str, Any]]:
    sphere = _SPHERE_RE.search(description)
    if sphere:
        center = _float_tuple(sphere.groups()[0:3])
        radius = float(sphere.group(4))
        point_count = int(sphere.group(5))
        return {
            "primitive_type": "sphere",
            "center": center,
            "radius": radius,
            "point_count": point_count,
            "coverage": point_count / max(total_points, 1),
            "raw": description,
        }

    cylinder = _CYLINDER_RE.search(description)
    if cylinder:
        groups = cylinder.groups()
        center = _float_tuple(groups[0:3])
        axis = _normalize_tuple(_float_tuple(groups[3:6]))
        radius = float(groups[6])
        point_count = int(groups[7])
        return {
            "primitive_type": "cylinder",
            "center": center,
            "axis": axis,
            "radius": radius,
            "point_count": point_count,
            "coverage": point_count / max(total_points, 1),
            "raw": description,
        }

    cone = _CONE_RE.search(description)
    if cone:
        groups = cone.groups()
        apex = _float_tuple(groups[0:3])
        axis = _normalize_tuple(_float_tuple(groups[3:6]))
        angle = float(groups[6])
        point_count = int(groups[7])
        return {
            "primitive_type": "cone",
            "apex": apex,
            "axis": axis,
            "angle": angle,
            "point_count": point_count,
            "coverage": point_count / max(total_points, 1),
            "raw": description,
        }

    return None


def _shape_description_to_scad(shape: dict[str, Any]) -> Optional[str]:
    primitive_type = shape["primitive_type"]
    if primitive_type == "sphere":
        center = shape["center"]
        radius = shape["radius"]
        return (
            f"translate([{center[0]:.6f}, {center[1]:.6f}, {center[2]:.6f}]) "
            f"sphere(r={radius:.6f}, $fn=96);"
        )

    if primitive_type == "cylinder":
        axis = shape["axis"]
        radius = shape["radius"]
        center = shape.get("finite_center")
        height = shape.get("height")
        if center is None or height is None:
            return None
        if float(height) <= 1e-6:
            return None
        primitive = f"cylinder(h={float(height):.6f}, r={float(radius):.6f}, center=true, $fn=96);"
        return _wrap_oriented_primitive(
            np.asarray(center, dtype=np.float64), axis, primitive
        )

    if primitive_type == "cone":
        axis = shape["axis"]
        center = shape.get("finite_center")
        height = shape.get("height")
        radius_start = shape.get("radius_start")
        radius_end = shape.get("radius_end")
        if center is None or height is None or radius_start is None or radius_end is None:
            return None
        if float(height) <= 1e-6:
            return None
        if max(float(radius_start), float(radius_end)) <= 1e-6:
            return None
        primitive = (
            f"cylinder(h={float(height):.6f}, r1={float(radius_start):.6f}, "
            f"r2={float(radius_end):.6f}, center=true, $fn=96);"
        )
        return _wrap_oriented_primitive(
            np.asarray(center, dtype=np.float64), axis, primitive
        )

    return None


def _try_assemble_multi_shape_union(
    parsed_shapes: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[float], Optional[list[dict[str, Any]]], Optional[str]]:
    supported: list[dict[str, Any]] = []
    for shape in parsed_shapes:
        primitive_type = shape.get("primitive_type")
        if primitive_type not in {"sphere", "cylinder", "cone"}:
            continue
        if float(shape.get("coverage", 0.0)) < _MIN_CGAL_MULTI_COMPONENT_COVERAGE:
            continue
        supported.append(shape)

    if len(supported) < 2:
        return None, None, None, "insufficient_multi_shape_components"

    if len(supported) > _MAX_CGAL_MULTI_COMPONENTS:
        return None, None, None, "too_many_multi_shape_components"

    coverage_sum = float(sum(float(shape.get("coverage", 0.0)) for shape in supported))
    if coverage_sum < _MIN_CGAL_MULTI_TOTAL_COVERAGE:
        return None, None, None, "low_multi_shape_coverage"

    shaped_entries: list[tuple[tuple[np.ndarray, np.ndarray], dict[str, Any], str]] = []
    for shape in supported:
        bbox = _shape_axis_aligned_bbox(shape)
        if bbox is None:
            return None, None, None, "multi_shape_bbox_unavailable"
        snippet = _shape_description_to_scad(shape)
        if snippet is None:
            return None, None, None, "multi_shape_component_scad_failed"
        shaped_entries.append((bbox, shape, snippet.strip()))

    for i in range(len(shaped_entries)):
        for j in range(i + 1, len(shaped_entries)):
            if _bboxes_overlap(shaped_entries[i][0], shaped_entries[j][0]):
                return None, None, None, "overlapping_component_bboxes"

    shaped_entries.sort(key=lambda item: tuple(float(v) for v in item[0][0]))
    snippets = [entry[2] for entry in shaped_entries]
    selected_shapes = [dict(entry[1]) for entry in shaped_entries]
    union_scad = "union() {\n" + "\n".join(f"    {snippet}" for snippet in snippets) + "\n}"
    return union_scad, min(1.0, coverage_sum), selected_shapes, None


def _shape_axis_aligned_bbox(
    shape: dict[str, Any],
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    primitive_type = shape.get("primitive_type")
    if primitive_type == "sphere":
        center = np.asarray(shape.get("center"), dtype=np.float64)
        radius = float(shape.get("radius", 0.0))
        if center.shape != (3,) or radius <= 1e-9:
            return None
        half = np.array([radius, radius, radius], dtype=np.float64)
        return center - half, center + half

    if primitive_type not in {"cylinder", "cone"}:
        return None

    center = np.asarray(shape.get("finite_center"), dtype=np.float64)
    axis = np.asarray(shape.get("axis"), dtype=np.float64)
    height = float(shape.get("height", 0.0))
    if center.shape != (3,) or axis.shape != (3,) or height <= 1e-9:
        return None

    axis_norm = float(np.linalg.norm(axis))
    if axis_norm <= 1e-12:
        return None
    axis = np.asarray(axis / axis_norm, dtype=np.float64)

    if primitive_type == "cylinder":
        radial = float(shape.get("radius", 0.0))
    else:
        radial = max(
            float(shape.get("radius_start", 0.0)),
            float(shape.get("radius_end", 0.0)),
        )
    if radial <= 1e-9:
        return None

    half_h = 0.5 * height
    perp = np.sqrt(np.clip(1.0 - np.square(axis), 0.0, 1.0))
    half_extents = np.abs(axis) * half_h + perp * radial
    return center - half_extents, center + half_extents


def _bboxes_overlap(
    bbox_a: tuple[np.ndarray, np.ndarray],
    bbox_b: tuple[np.ndarray, np.ndarray],
    eps: float = 1e-9,
) -> bool:
    min_a, max_a = bbox_a
    min_b, max_b = bbox_b
    overlap = np.minimum(max_a, max_b) - np.maximum(min_a, min_b)
    return bool(np.all(overlap > eps))


def _enrich_shape_geometry_from_points(
    shape: Optional[dict[str, Any]],
    points: np.ndarray,
) -> Optional[dict[str, Any]]:
    if shape is None:
        return None
    primitive_type = shape.get("primitive_type")
    if primitive_type == "cylinder":
        center = np.asarray(shape.get("center"), dtype=np.float64)
        axis_vec: np.ndarray = np.asarray(shape.get("axis"), dtype=np.float64)
        radius = float(shape.get("radius", 0.0))

        if center.shape != (3,) or axis_vec.shape != (3,) or radius <= 1e-6:
            return shape

        axis_norm = float(np.linalg.norm(axis_vec))
        if axis_norm <= 1e-12:
            return shape
        axis_vec = np.asarray(axis_vec / axis_norm, dtype=np.float64)

        relative = points - center
        t_values = relative @ axis_vec
        if len(t_values) == 0:
            return shape

        if len(t_values) >= 50:
            t_min = float(np.percentile(t_values, 2.0))
            t_max = float(np.percentile(t_values, 98.0))
        else:
            t_min = float(np.min(t_values))
            t_max = float(np.max(t_values))

        height = t_max - t_min
        if height <= 1e-6:
            return shape

        finite_center = center + axis_vec * ((t_min + t_max) * 0.5)
        enriched = dict(shape)
        enriched["axis"] = _normalize_tuple(tuple(float(value) for value in axis_vec))
        enriched["finite_center"] = tuple(float(value) for value in finite_center)
        enriched["height"] = float(height)
        enriched["axis_min"] = t_min
        enriched["axis_max"] = t_max
        enriched["estimated_from_sample_points"] = True
        return enriched

    if primitive_type != "cone":
        return shape

    apex = np.asarray(shape.get("apex"), dtype=np.float64)
    axis_vec = np.asarray(shape.get("axis"), dtype=np.float64)
    angle_raw = shape.get("angle")

    if apex.shape != (3,) or axis_vec.shape != (3,) or angle_raw is None:
        return shape

    axis_norm = float(np.linalg.norm(axis_vec))
    if axis_norm <= 1e-12:
        return shape
    axis_vec = np.asarray(axis_vec / axis_norm, dtype=np.float64)

    try:
        angle = float(angle_raw)
    except (TypeError, ValueError):
        return shape

    angle_radians = angle
    if angle_radians > (math.pi / 2.0) and angle_radians <= 180.0:
        angle_radians = math.radians(angle_radians)

    tan_angle = math.tan(angle_radians)
    if not math.isfinite(tan_angle) or tan_angle <= 1e-9:
        return shape

    relative = points - apex
    t_values = relative @ axis_vec
    if len(t_values) == 0:
        return shape

    if len(t_values) >= 50:
        t_min = float(np.percentile(t_values, 2.0))
        t_max = float(np.percentile(t_values, 98.0))
    else:
        t_min = float(np.min(t_values))
        t_max = float(np.max(t_values))

    height = abs(t_max - t_min)
    if height <= 1e-6:
        return shape

    radius_start = abs(tan_angle * t_min)
    radius_end = abs(tan_angle * t_max)
    finite_center = apex + axis_vec * ((t_min + t_max) * 0.5)

    enriched = dict(shape)
    enriched["axis"] = _normalize_tuple(tuple(float(value) for value in axis_vec))
    enriched["finite_center"] = tuple(float(value) for value in finite_center)
    enriched["height"] = float(height)
    enriched["axis_min"] = t_min
    enriched["axis_max"] = t_max
    enriched["radius_start"] = float(radius_start)
    enriched["radius_end"] = float(radius_end)
    enriched["estimated_from_sample_points"] = True
    return enriched


def _float_tuple(values: Any) -> tuple[float, ...]:
    return tuple(float(value) for value in values)


def _normalize_tuple(values: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        return (0.0, 0.0, 1.0)
    return tuple(value / norm for value in values)


def _wrap_oriented_primitive(
    center: np.ndarray,
    axis: Union[tuple[float, ...], np.ndarray],
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


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _build_helper_command(helper_path: str) -> list[str]:
    helper = str(helper_path)
    lower = helper.lower()
    if lower.endswith(".py"):
        return [sys.executable, helper]
    return [helper]
