"""
Performance baseline runner for STL-to-SCAD conversion.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import tempfile
import time
from typing import Any, Dict, List, Sequence, Union

import psutil
from stl.mesh import Mesh

from .benchmark_fixtures import ensure_benchmark_fixtures
from .converter import stl2scad


def run_conversion_perf_baseline(
    fixtures_dir: Union[Path, str],
    output_json: Union[Path, str],
    repeat: int = 3,
    categories: Sequence[str] = ("performance",),
    parametric_modes: Sequence[bool] = (False, True),
    recognition_backend: str = "native",
) -> Dict[str, Any]:
    """
    Run conversion performance baseline and write JSON report.
    """
    if repeat <= 0:
        raise ValueError("repeat must be a positive integer")

    fixtures_path = Path(fixtures_dir)
    out_path = Path(output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = ensure_benchmark_fixtures(fixtures_path)
    selected_fixtures = _select_fixtures(manifest, categories)
    if not selected_fixtures:
        raise ValueError(f"No fixtures matched categories: {', '.join(categories)}")

    process = psutil.Process(os.getpid())
    results: List[Dict[str, Any]] = []
    for fixture in selected_fixtures:
        fixture_path = fixtures_path / fixture["file"]
        mesh = Mesh.from_file(str(fixture_path))
        triangle_count = int(len(mesh.vectors))
        for parametric in parametric_modes:
            bench = _benchmark_one(
                fixture_path=fixture_path,
                repeat=repeat,
                parametric=parametric,
                recognition_backend=recognition_backend,
                process=process,
            )
            results.append(
                {
                    "fixture_name": fixture["name"],
                    "fixture_file": fixture["file"],
                    "category": fixture["category"],
                    "triangles": triangle_count,
                    "parametric": parametric,
                    "recognition_backend": recognition_backend,
                    **bench,
                }
            )

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
        "config": {
            "fixtures_dir": str(fixtures_path),
            "repeat": repeat,
            "categories": list(categories),
            "parametric_modes": list(parametric_modes),
            "recognition_backend": recognition_backend,
        },
        "results": results,
        "summary": _summarize_results(results),
    }

    with open(out_path, "w", encoding="utf-8") as out_file:
        json.dump(report, out_file, indent=2)

    return report


def _select_fixtures(
    manifest: Dict[str, Any], categories: Sequence[str]
) -> List[Dict[str, Any]]:
    category_set = {c.strip().lower() for c in categories if c.strip()}
    fixtures = manifest.get("fixtures", [])
    return [
        fixture
        for fixture in fixtures
        if str(fixture.get("category", "")).lower() in category_set
    ]


def _benchmark_one(
    fixture_path: Path,
    repeat: int,
    parametric: bool,
    recognition_backend: str,
    process: psutil.Process,
) -> Dict[str, Any]:
    elapsed_seconds: List[float] = []
    output_sizes: List[int] = []
    rss_before = int(process.memory_info().rss)
    rss_max = rss_before

    for run_idx in range(repeat):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / f"{fixture_path.stem}_{run_idx}.scad"
            started = time.perf_counter()
            stl2scad(
                str(fixture_path),
                str(output_path),
                parametric=parametric,
                recognition_backend=recognition_backend,
            )
            elapsed = time.perf_counter() - started
            elapsed_seconds.append(elapsed)
            output_sizes.append(
                output_path.stat().st_size if output_path.exists() else 0
            )

        rss_now = int(process.memory_info().rss)
        if rss_now > rss_max:
            rss_max = rss_now

    return {
        "elapsed_mean_seconds": float(statistics.mean(elapsed_seconds)),
        "elapsed_min_seconds": float(min(elapsed_seconds)),
        "elapsed_max_seconds": float(max(elapsed_seconds)),
        "elapsed_stdev_seconds": float(statistics.pstdev(elapsed_seconds)),
        "output_size_mean_bytes": float(statistics.mean(output_sizes)),
        "process_rss_start_bytes": rss_before,
        "process_rss_peak_bytes": rss_max,
        "raw_elapsed_seconds": [float(v) for v in elapsed_seconds],
    }


def _summarize_results(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {}

    all_means = [float(r["elapsed_mean_seconds"]) for r in results]
    parametric_means = [
        float(r["elapsed_mean_seconds"]) for r in results if bool(r["parametric"])
    ]
    poly_means = [
        float(r["elapsed_mean_seconds"]) for r in results if not bool(r["parametric"])
    ]

    summary: Dict[str, Any] = {
        "result_count": len(results),
        "overall_elapsed_mean_seconds": float(statistics.mean(all_means)),
    }
    if poly_means:
        summary["polyhedron_elapsed_mean_seconds"] = float(statistics.mean(poly_means))
    if parametric_means:
        summary["parametric_elapsed_mean_seconds"] = float(
            statistics.mean(parametric_means)
        )
    return summary
