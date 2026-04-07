"""
Prototype CGAL helper executable for Phase 2 integration testing.

The helper is protocol-compatible with the planned CGAL boundary. When CGAL
Python bindings are not available, it uses the local geometric region analyzer
as an explicit fallback and reports that state in diagnostics.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import stl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.recognition import (
    _components_have_overlapping_bboxes,
    _detect_component_primitive,
    _detect_primitive_native,
    _preprocess_components,
)

SUPPORTED_PRIMITIVES = ("box", "sphere", "cylinder", "cone", "composite_union")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="stl2scad CGAL helper prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)
    detect = subparsers.add_parser("detect-primitive")
    detect.add_argument("--format", default="json", choices=["json"])
    capabilities = subparsers.add_parser("capabilities")
    capabilities.add_argument("--format", default="json", choices=["json"])
    return parser


def _mesh_from_triangles(triangles: Any) -> stl.mesh.Mesh:
    arr = np.asarray(triangles, dtype=np.float64)
    if arr.ndim != 3 or arr.shape[1:] != (3, 3):
        raise ValueError("mesh.triangles must be shape [N, 3, 3]")
    mesh = stl.mesh.Mesh(np.zeros(arr.shape[0], dtype=stl.mesh.Mesh.dtype))
    mesh.vectors = arr
    return mesh


def _infer_primitive_type(scad: str) -> str:
    text = scad.lower()
    if "sphere(" in text:
        return "sphere"
    if "cylinder(" in text and "r1=" in text and "r2=" in text:
        return "cone"
    if "cylinder(" in text:
        return "cylinder"
    if "cube(" in text:
        return "box"
    if "union()" in text:
        return "composite_union"
    return "unknown"


def _emit(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()
    return 0


def _available_cgal_modules() -> list[str]:
    return [
        module_name
        for module_name in ("CGAL", "cgal")
        if importlib.util.find_spec(module_name) is not None
    ]


def _capabilities_payload() -> dict[str, Any]:
    cgal_modules = _available_cgal_modules()
    return {
        "schema_version": 1,
        "helper_mode": "prototype",
        "cgal_bindings_available": bool(cgal_modules),
        "cgal_modules": cgal_modules,
        "operations": ["detect_primitive"],
        "supported_primitives": list(SUPPORTED_PRIMITIVES),
        "engines": (
            ["cgal_shape_detection", "geometric_region_fallback"]
            if cgal_modules
            else ["geometric_region_fallback"]
        ),
        "notes": (
            "CGAL bindings detected, but helper still uses fallback until "
            "shape-detection integration is implemented."
            if cgal_modules
            else "CGAL bindings not available; helper uses geometric region fallback."
        ),
    }


def _analyze_regions(mesh: stl.mesh.Mesh, tolerance: float) -> dict[str, Any]:
    cgal_modules = _available_cgal_modules()
    diagnostics: dict[str, Any] = {
        "helper_mode": "prototype",
        "engine": "geometric_region_fallback",
        "cgal_bindings_available": bool(cgal_modules),
        "cgal_modules": cgal_modules,
        "cgal_status": (
            "bindings_detected_engine_not_implemented"
            if cgal_modules
            else "bindings_not_available"
        ),
        "triangle_count": int(len(mesh.vectors)),
    }

    components = _preprocess_components(mesh)
    diagnostics["component_count"] = len(components)
    diagnostics["components"] = [
        {
            "vertex_count": int(len(component.vertices)),
            "face_count": int(len(component.faces)),
        }
        for component in components
    ]
    if not components:
        diagnostics["reason"] = "no_components"
        return {
            "detected": False,
            "primitive_type": None,
            "confidence": None,
            "diagnostics": diagnostics,
        }

    if len(components) > 1 and _components_have_overlapping_bboxes(components):
        diagnostics["reason"] = "overlapping_component_bboxes"
        return {
            "detected": False,
            "primitive_type": None,
            "confidence": None,
            "diagnostics": diagnostics,
        }

    snippets: list[str] = []
    confidences: list[float] = []
    component_results: list[dict[str, Any]] = []
    for index, component in enumerate(components):
        candidate = _detect_component_primitive(component, tolerance)
        if candidate is None:
            component_results.append(
                {
                    "component_index": index,
                    "detected": False,
                    "primitive_type": None,
                    "confidence": None,
                }
            )
            diagnostics["component_results"] = component_results
            diagnostics["assigned_component_count"] = len(snippets)
            diagnostics["reason"] = "component_without_primitive_match"
            return {
                "detected": False,
                "primitive_type": None,
                "confidence": None,
                "diagnostics": diagnostics,
            }

        snippets.append(candidate.scad.strip())
        confidences.append(float(candidate.confidence))
        component_results.append(
            {
                "component_index": index,
                "detected": True,
                "primitive_type": candidate.shape,
                "confidence": float(candidate.confidence),
                "vertex_count": int(len(component.vertices)),
                "face_count": int(len(component.faces)),
            }
        )

    diagnostics["component_results"] = component_results
    diagnostics["assigned_component_count"] = len(snippets)
    diagnostics["assignment_coverage"] = float(len(snippets) / len(components))

    if len(snippets) == 1:
        primitive_type = component_results[0]["primitive_type"]
        scad = snippets[0]
        confidence = confidences[0]
    else:
        primitive_type = "composite_union"
        scad = "union() {\n" + "\n".join(f"    {snippet}" for snippet in snippets) + "\n}"
        confidence = min(confidences)

    return {
        "detected": True,
        "scad": scad,
        "primitive_type": primitive_type,
        "confidence": confidence,
        "diagnostics": diagnostics,
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "capabilities":
        return _emit(_capabilities_payload())

    if args.command != "detect-primitive":
        return _emit({"detected": False, "diagnostics": {"reason": "unsupported_command"}})

    try:
        request = json.loads(sys.stdin.read() or "{}")
        tolerance = float(request.get("tolerance", 0.01))
        triangles = request.get("mesh", {}).get("triangles")
        mesh = _mesh_from_triangles(triangles)
    except Exception as exc:
        return _emit(
            {
                "detected": False,
                "diagnostics": {
                    "reason": "invalid_request",
                    "error": str(exc),
                },
            }
        )

    result = _analyze_regions(mesh, tolerance)
    if result["detected"]:
        return _emit(result)

    # Native box fallback is kept separate so diagnostics show whether region
    # analysis or the legacy native path produced the result.
    scad = _detect_primitive_native(mesh, tolerance=tolerance)
    if scad:
        primitive_type = _infer_primitive_type(scad)
        diagnostics = dict(result.get("diagnostics", {}))
        diagnostics["native_fallback_used"] = True
        return _emit(
            {
                "detected": True,
                "scad": scad.strip(),
                "primitive_type": primitive_type,
                "confidence": None,
                "diagnostics": diagnostics,
            }
        )

    diagnostics = dict(result.get("diagnostics", {}))
    diagnostics["native_fallback_used"] = False
    return _emit(
        {
            "detected": False,
            "primitive_type": None,
            "confidence": None,
            "diagnostics": diagnostics,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
