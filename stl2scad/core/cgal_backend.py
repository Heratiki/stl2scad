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
from typing import Any, Optional

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
_MIN_CGAL_PYTHON_COVERAGE = 0.85


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
                supported_primitives=["sphere"],
                engines=["cgal_python_bindings"],
                raw={
                    "schema_version": 1,
                    "helper_mode": None,
                    "cgal_bindings_available": True,
                    "operations": ["detect_primitive"],
                    "supported_primitives": ["sphere"],
                    "engines": ["cgal_python_bindings"],
                    "notes": (
                        "Direct Python binding path accepts high-coverage "
                        "sphere detections; other shapes fall back."
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
            probability=0.05,
            planes=True,
            cones=True,
            cylinders=True,
            spheres=True,
            tori=False,
        )
    except Exception:
        logging.debug("CGAL Python shape detection failed.", exc_info=True)
        return None

    parsed = [_parse_cgal_shape_description(str(shape), len(points)) for shape in shapes]
    parsed = [shape for shape in parsed if shape is not None]
    diagnostics: dict[str, Any] = {
        "engine": "cgal_python_bindings",
        "cgal_bindings_available": True,
        "triangle_count": int(len(mesh.vectors)),
        "sample_point_count": int(len(points)),
        "epsilon": float(epsilon),
        "cluster_epsilon": float(cluster_epsilon),
        "shapes": parsed,
    }
    if not parsed:
        diagnostics["reason"] = "no_shapes_detected"
        return CgalDetectionResult(detected=False, diagnostics=diagnostics)

    parsed.sort(key=lambda item: float(item["coverage"]), reverse=True)
    best = parsed[0]
    if best["primitive_type"] not in {"sphere", "cylinder"}:
        diagnostics["reason"] = "unsupported_best_shape"
        return CgalDetectionResult(
            detected=False,
            primitive_type=str(best["primitive_type"]),
            confidence=float(best["coverage"]),
            diagnostics=diagnostics,
        )
    if float(best["coverage"]) < _MIN_CGAL_PYTHON_COVERAGE:
        diagnostics["reason"] = "low_shape_coverage"
        return CgalDetectionResult(
            detected=False,
            primitive_type=str(best["primitive_type"]),
            confidence=float(best["coverage"]),
            diagnostics=diagnostics,
        )

    scad = _shape_description_to_scad(best)
    if scad is None:
        diagnostics["reason"] = "shape_to_scad_failed"
        return CgalDetectionResult(
            detected=False,
            primitive_type=str(best["primitive_type"]),
            confidence=float(best["coverage"]),
            diagnostics=diagnostics,
        )

    return CgalDetectionResult(
        detected=True,
        scad=scad,
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
        center = shape["center"]
        axis = shape["axis"]
        radius = shape["radius"]
        # CGAL's shape description does not include finite extent in this SWIG
        # wrapper, so direct cylinder SCAD is only safe after extent support.
        _ = center, axis, radius
        return None

    return None


def _float_tuple(values: Any) -> tuple[float, ...]:
    return tuple(float(value) for value in values)


def _normalize_tuple(values: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        return (0.0, 0.0, 1.0)
    return tuple(value / norm for value in values)


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
