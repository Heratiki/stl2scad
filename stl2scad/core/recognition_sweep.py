"""
Recognition sweep utilities for backend coverage and regression gating.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Optional

import stl

from .benchmark_fixtures import load_benchmark_manifest
from .recognition import detect_primitive_with_diagnostics


@dataclass(frozen=True)
class SweepGateConfig:
    min_detection_rate: Optional[float] = None
    required_primitives: tuple[str, ...] = ()
    max_errors: int = 0


def discover_fixtures(
    fixtures_dir: Path,
    fixture_names: Optional[Iterable[str]] = None,
    categories: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
    extra_globs: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    """Discover fixture entries from manifest plus optional glob paths."""
    fixtures_root = Path(fixtures_dir)
    selected_names = {name.strip() for name in (fixture_names or []) if name.strip()}
    selected_categories = {
        category.strip() for category in (categories or []) if category.strip()
    }
    selected_tags = {tag.strip() for tag in (tags or []) if tag.strip()}

    entries: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    manifest_path = fixtures_root / "manifest.json"
    if manifest_path.exists():
        manifest = load_benchmark_manifest(fixtures_root)
        for item in manifest.get("fixtures", []):
            if not isinstance(item, dict):
                continue
            fixture_name = str(item.get("name", "")).strip()
            if selected_names and fixture_name not in selected_names:
                continue

            fixture_category = str(item.get("category", "")).strip()
            if selected_categories and fixture_category not in selected_categories:
                continue

            fixture_tags = {
                str(tag).strip()
                for tag in (item.get("tags") or [])
                if str(tag).strip()
            }
            if selected_tags and not selected_tags.intersection(fixture_tags):
                continue

            rel_file = item.get("file")
            if not isinstance(rel_file, str) or not rel_file.strip():
                continue
            fixture_path = (fixtures_root / rel_file).resolve()
            if not fixture_path.exists() or fixture_path.suffix.lower() != ".stl":
                continue
            if fixture_path in seen_paths:
                continue
            seen_paths.add(fixture_path)
            entries.append(
                {
                    "name": fixture_name or fixture_path.stem,
                    "path": str(fixture_path),
                    "category": fixture_category,
                    "tags": sorted(fixture_tags),
                    "source": "manifest",
                }
            )

    for pattern in (extra_globs or []):
        glob_pattern = pattern.strip()
        if not glob_pattern:
            continue
        for candidate in fixtures_root.rglob(glob_pattern):
            if not candidate.is_file() or candidate.suffix.lower() != ".stl":
                continue
            resolved = candidate.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            entries.append(
                {
                    "name": candidate.stem,
                    "path": str(resolved),
                    "category": "extra",
                    "tags": [],
                    "source": "glob",
                }
            )

    entries.sort(key=lambda item: (str(item.get("category", "")), item["name"]))
    return entries


def run_recognition_sweep(
    fixtures: Iterable[dict[str, Any]],
    backends: Iterable[str],
    tolerance: float,
) -> dict[str, Any]:
    """Run recognition across fixture/backend matrix and build a report."""
    results: list[dict[str, Any]] = []
    for backend in backends:
        backend_id = backend.strip()
        if not backend_id:
            continue
        for fixture in fixtures:
            fixture_name = str(fixture.get("name") or Path(str(fixture["path"])).stem)
            fixture_path = Path(str(fixture["path"]))
            row: dict[str, Any] = {
                "fixture": fixture_name,
                "path": str(fixture_path),
                "category": str(fixture.get("category", "")),
                "backend": backend_id,
                "detected": False,
                "primitive_type": None,
                "reason": None,
                "error": None,
            }
            try:
                mesh = stl.mesh.Mesh.from_file(str(fixture_path))
                primitive_scad, reason = detect_primitive_with_diagnostics(
                    mesh,
                    tolerance=tolerance,
                    backend=backend_id,
                )
                primitive_type = _infer_primitive_type(primitive_scad)
                row["detected"] = primitive_scad is not None
                row["primitive_type"] = primitive_type
                row["reason"] = "" if primitive_scad is not None else (reason or "unknown")
            except Exception as exc:  # pragma: no cover - defensive guard
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["reason"] = "error"
            results.append(row)

    summary = _build_summary(results)
    return {
        "schema_version": 1,
        "summary": summary,
        "results": results,
    }


def evaluate_sweep_gates(
    report: dict[str, Any],
    gate: SweepGateConfig,
) -> list[str]:
    """Return a list of gate failure messages."""
    failures: list[str] = []
    by_backend = report.get("summary", {}).get("by_backend", {})
    if not isinstance(by_backend, dict):
        return ["Report summary missing by_backend section."]

    for backend, info in sorted(by_backend.items()):
        if not isinstance(info, dict):
            failures.append(f"Backend '{backend}' summary is invalid.")
            continue

        fallback_reason_counts = info.get("fallback_reason_counts", {})
        if not isinstance(fallback_reason_counts, dict):
            fallback_reason_counts = {}
        backend_unavailable_count = int(
            fallback_reason_counts.get("backend_unavailable", 0)
        )
        if backend_unavailable_count > 0 and (
            gate.min_detection_rate is not None or gate.required_primitives
        ):
            failures.append(
                f"Backend '{backend}' reported backend_unavailable for "
                f"{backend_unavailable_count} fixture(s); install optional "
                "dependencies before enforcing detection-rate/primitive gates."
            )

        if gate.min_detection_rate is not None:
            rate = float(info.get("detection_rate", 0.0))
            if rate + 1e-12 < gate.min_detection_rate:
                failures.append(
                    f"Backend '{backend}' detection_rate {rate:.4f} < required {gate.min_detection_rate:.4f}."
                )

        if gate.max_errors is not None:
            errors = int(info.get("error_count", 0))
            if errors > gate.max_errors:
                failures.append(
                    f"Backend '{backend}' error_count {errors} exceeds max {gate.max_errors}."
                )

        if gate.required_primitives:
            detected_primitives = set(info.get("detected_primitives", []))
            for primitive in gate.required_primitives:
                if primitive not in detected_primitives:
                    failures.append(
                        f"Backend '{backend}' missing required primitive '{primitive}' in detected results."
                    )

    return failures


def write_sweep_report(report: dict[str, Any], output_path: Path) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def _infer_primitive_type(scad: Optional[str]) -> Optional[str]:
    if not scad:
        return None
    text = scad.lower()
    if "union()" in text:
        return "composite_union"
    if "sphere(" in text:
        return "sphere"
    if "cylinder(" in text and "r1=" in text and "r2=" in text:
        return "cone"
    if "cylinder(" in text:
        return "cylinder"
    if "cube(" in text:
        return "box"
    return "unknown"


def _build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_backend_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_backend_rows[str(row.get("backend", "unknown"))].append(row)

    by_backend: dict[str, dict[str, Any]] = {}
    for backend, rows in sorted(by_backend_rows.items()):
        total = len(rows)
        detected_rows = [row for row in rows if bool(row.get("detected"))]
        detected = len(detected_rows)
        error_count = sum(1 for row in rows if row.get("error"))
        primitive_counts = Counter(
            (row.get("primitive_type") or "none") for row in detected_rows
        )
        reason_counts = Counter(
            str(row.get("reason") or "")
            for row in rows
            if not bool(row.get("detected"))
        )
        by_backend[backend] = {
            "total": total,
            "detected": detected,
            "detection_rate": (float(detected) / float(total)) if total else 0.0,
            "error_count": error_count,
            "detected_primitives": sorted(
                primitive
                for primitive in primitive_counts.keys()
                if primitive not in {"none", "unknown"}
            ),
            "primitive_counts": dict(sorted(primitive_counts.items())),
            "fallback_reason_counts": {
                reason: count
                for reason, count in sorted(reason_counts.items())
                if reason
            },
        }

    return {
        "total_rows": len(results),
        "backends": sorted(by_backend.keys()),
        "by_backend": by_backend,
    }
