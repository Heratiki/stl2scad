"""
Prototype CGAL helper executable for Phase 2 integration testing.

This is a protocol-compatible placeholder that currently reuses internal
recognition heuristics. It allows end-to-end validation of the helper boundary
while the real CGAL implementation is developed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import stl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.recognition import _detect_primitive_native, _detect_primitive_trimesh_manifold


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="stl2scad CGAL helper prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)
    detect = subparsers.add_parser("detect-primitive")
    detect.add_argument("--format", default="json", choices=["json"])
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


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
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

    # Prototype behavior: run Phase 1 detection logic as a stand-in until real
    # CGAL helper logic is implemented.
    scad = _detect_primitive_trimesh_manifold(mesh, tolerance=tolerance)
    if scad is None:
        scad = _detect_primitive_native(mesh, tolerance=tolerance)

    if scad:
        primitive_type = _infer_primitive_type(scad)
        return _emit(
            {
                "detected": True,
                "scad": scad.strip(),
                "primitive_type": primitive_type,
                "confidence": None,
                "diagnostics": {
                    "helper_mode": "prototype",
                    "engine": "phase1_heuristics",
                },
            }
        )

    return _emit(
        {
            "detected": False,
            "primitive_type": None,
            "confidence": None,
            "diagnostics": {
                "helper_mode": "prototype",
                "reason": "no_match",
            },
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())

