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
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Optional

import stl

CGAL_HELPER_ENV_VAR = "STL2SCAD_CGAL_HELPER"
DEFAULT_CGAL_HELPER_NAMES = (
    "stl2scad-cgal-helper",
    "stl2scad-cgal-helper.exe",
    "stl2scad-cgal-helper.py",
)


@dataclass
class CgalDetectionResult:
    detected: bool
    scad: Optional[str] = None
    primitive_type: Optional[str] = None
    confidence: Optional[float] = None
    diagnostics: Optional[dict[str, Any]] = None


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


def detect_primitive_with_cgal(
    mesh: stl.mesh.Mesh,
    tolerance: float = 0.01,
    helper_path: Optional[str] = None,
    timeout_seconds: int = 20,
) -> Optional[CgalDetectionResult]:
    """
    Detect primitive via CGAL helper boundary.

    Returns None if no helper is available or helper execution fails.
    """
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


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _build_helper_command(helper_path: str) -> list[str]:
    helper = str(helper_path)
    lower = helper.lower()
    if lower.endswith(".py"):
        return [sys.executable, helper]
    return [helper]
