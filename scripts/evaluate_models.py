"""Evaluate STL models with conversion and verification metrics.

This script is intended for repeatable model benchmarking in local development.
It runs conversion in polyhedron and/or parametric mode, verifies generated
SCAD output against source STL, and writes machine-readable JSON/CSV reports.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any

import stl

from stl2scad.core.converter import stl2scad
from stl2scad.core.verification.verification import verify_existing_conversion


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate STL models and emit structured conversion metrics."
    )
    parser.add_argument(
        "--models-dir",
        default="models",
        help="Directory containing STL files to evaluate.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/reports/model_eval",
        help="Directory where generated SCAD and reports are written.",
    )
    parser.add_argument(
        "--backend",
        default="trimesh_manifold",
        choices=["native", "trimesh_manifold", "cgal"],
        help="Recognition backend used for parametric mode.",
    )
    parser.add_argument(
        "--compute-backend",
        default="cpu",
        choices=["auto", "cpu", "gpu"],
        help="Compute backend for conversion runs (default: cpu for stable benchmarking).",
    )
    parser.add_argument(
        "--modes",
        default="poly,parametric",
        help="Comma-separated modes: poly,parametric",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=123,
        help="Seed for deterministic sampling metrics.",
    )
    parser.add_argument(
        "--volume-tol",
        type=float,
        default=1.0,
        help="Volume tolerance percent.",
    )
    parser.add_argument(
        "--area-tol",
        type=float,
        default=2.0,
        help="Surface area tolerance percent.",
    )
    parser.add_argument(
        "--bbox-tol",
        type=float,
        default=2.0,
        help="Bounding-box tolerance percent.",
    )
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        default=1_000_000_000,
        help="Maximum total bytes allowed under output-dir during this run (default: 1GB).",
    )
    parser.add_argument(
        "--max-scad-bytes-per-file",
        type=int,
        default=100_000_000,
        help="Maximum allowed SCAD size per generated file (default: 100MB).",
    )
    parser.add_argument(
        "--min-free-bytes",
        type=int,
        default=2_000_000_000,
        help="Minimum free disk bytes required before and during run (default: 2GB).",
    )
    parser.add_argument(
        "--cleanup-generated-scad",
        action="store_true",
        help="Delete generated .scad files after metrics are collected to reduce disk usage.",
    )
    return parser


def _parse_modes(raw_modes: str) -> list[str]:
    modes = [m.strip().lower() for m in raw_modes.split(",") if m.strip()]
    valid = {"poly", "parametric"}
    invalid = [m for m in modes if m not in valid]
    if invalid:
        raise ValueError(f"Unsupported mode(s): {invalid}. Allowed: poly,parametric")
    if not modes:
        raise ValueError("At least one mode must be selected")
    return modes


def _detect_output_type(scad_path: Path) -> str:
    text = scad_path.read_text(encoding="utf-8", errors="ignore")
    if "polyhedron(" in text:
        return "polyhedron"
    if "union()" in text:
        return "union"
    if any(token in text for token in ("cube(", "sphere(", "cylinder(")):
        return "primitive"
    return "unknown"


def _fallback_reason(mode: str, output_type: str, metadata: dict[str, str]) -> str:
    if mode != "parametric":
        return ""
    if output_type != "polyhedron":
        return ""

    reason = metadata.get("recognition_fallback_reason", "").strip()
    if reason:
        return reason
    return "polyhedron_fallback"


def _load_triangles(stl_path: Path) -> int:
    mesh = stl.mesh.Mesh.from_file(str(stl_path))
    return int(len(mesh.vectors))


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _free_bytes(path: Path) -> int:
    usage = os.statvfs(str(path))
    return int(usage.f_bavail * usage.f_frsize)


def _git_state(repo_root: Path) -> dict[str, Any]:
    commit = "unknown"
    dirty = None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            commit = proc.stdout.strip()
    except Exception:
        pass

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if proc.returncode == 0:
            dirty = bool(proc.stdout.strip())
    except Exception:
        pass

    return {
        "git_commit": commit,
        "git_dirty": dirty,
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    models_dir = Path(args.models_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if _free_bytes(output_dir) < args.min_free_bytes:
        raise RuntimeError(
            "Insufficient free disk space before evaluation run. "
            f"Need >= {args.min_free_bytes} bytes free."
        )

    modes = _parse_modes(args.modes)
    stl_files = sorted(models_dir.glob("*.stl"))
    if not stl_files:
        raise FileNotFoundError(f"No STL files found in: {models_dir}")

    tol = {
        "volume": args.volume_tol,
        "surface_area": args.area_tol,
        "bounding_box": args.bbox_tol,
    }

    results: list[dict[str, Any]] = []
    output_bytes_before = _dir_size_bytes(output_dir)
    output_budget_exceeded = False
    for stl_path in stl_files:
        tri_count = _load_triangles(stl_path)
        for mode in modes:
            if output_budget_exceeded:
                break
            is_parametric = mode == "parametric"
            mode_suffix = "parametric" if is_parametric else "poly"
            scad_path = output_dir / f"{stl_path.stem}.{mode_suffix}.scad"

            row: dict[str, Any] = {
                "model": stl_path.name,
                "mode": mode,
                "backend": args.backend if is_parametric else "none",
                "triangles": tri_count,
                "scad_output": str(scad_path),
            }

            try:
                if _free_bytes(output_dir) < args.min_free_bytes:
                    raise RuntimeError(
                        "free_space_below_threshold: "
                        f"min_free_bytes={args.min_free_bytes}"
                    )

                t0 = perf_counter()
                stats = stl2scad(
                    str(stl_path),
                    str(scad_path),
                    parametric=is_parametric,
                    recognition_backend=args.backend,
                    compute_backend=args.compute_backend,
                )
                elapsed = perf_counter() - t0

                scad_size = scad_path.stat().st_size
                if scad_size > args.max_scad_bytes_per_file:
                    raise RuntimeError(
                        "scad_file_too_large: "
                        f"{scad_size} > {args.max_scad_bytes_per_file}"
                    )

                current_output_bytes = _dir_size_bytes(output_dir)
                if current_output_bytes - output_bytes_before > args.max_output_bytes:
                    output_budget_exceeded = True
                    raise RuntimeError(
                        "output_budget_exceeded: "
                        f"{current_output_bytes - output_bytes_before} > {args.max_output_bytes}"
                    )

                verification = verify_existing_conversion(
                    stl_path,
                    scad_path,
                    tolerance=tol,
                    sample_seed=args.sample_seed,
                )
                output_type = _detect_output_type(scad_path)

                row.update(
                    {
                        "elapsed_seconds": round(elapsed, 6),
                        "faces": stats.faces,
                        "original_vertices": stats.original_vertices,
                        "deduplicated_vertices": stats.deduplicated_vertices,
                        "verify_pass": verification.passed,
                        "volume_diff_percent": abs(
                            verification.comparison.get("volume", {}).get(
                                "difference_percent", 0.0
                            )
                        ),
                        "surface_area_diff_percent": abs(
                            verification.comparison.get("surface_area", {}).get(
                                "difference_percent", 0.0
                            )
                        ),
                        "output_type": output_type,
                        "used_fallback": is_parametric and output_type == "polyhedron",
                        "fallback_reason": _fallback_reason(
                            mode, output_type, stats.metadata
                        ),
                        "recognition_attempted": stats.metadata.get(
                            "recognition_attempted", ""
                        ),
                        "recognition_backend_used": stats.metadata.get(
                            "recognition_backend_used", ""
                        ),
                        "scad_size_bytes": scad_size,
                        "error": "",
                    }
                )

                if args.cleanup_generated_scad and scad_path.exists():
                    scad_path.unlink()
            except Exception as exc:  # pragma: no cover - operational reporting path
                row.update(
                    {
                        "elapsed_seconds": None,
                        "faces": None,
                        "original_vertices": None,
                        "deduplicated_vertices": None,
                        "verify_pass": None,
                        "volume_diff_percent": None,
                        "surface_area_diff_percent": None,
                        "output_type": "error",
                        "used_fallback": None,
                        "fallback_reason": "",
                        "recognition_attempted": "",
                        "recognition_backend_used": "",
                        "scad_size_bytes": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

            results.append(row)
        if output_budget_exceeded:
            break

    summary = {
        "models_dir": str(models_dir),
        "output_dir": str(output_dir),
        "backend": args.backend,
        "compute_backend": args.compute_backend,
        "modes": modes,
        "max_output_bytes": args.max_output_bytes,
        "max_scad_bytes_per_file": args.max_scad_bytes_per_file,
        "min_free_bytes": args.min_free_bytes,
        "cleanup_generated_scad": bool(args.cleanup_generated_scad),
        **_git_state(repo_root),
        "count_total": len(results),
        "count_errors": sum(1 for r in results if r.get("error")),
        "count_verify_pass": sum(1 for r in results if r.get("verify_pass") is True),
        "count_parametric_fallback": sum(
            1 for r in results if r.get("used_fallback") is True
        ),
        "output_bytes_before": output_bytes_before,
        "output_bytes_after": _dir_size_bytes(output_dir),
    }

    json_path = output_dir / "model_eval_report.json"
    json_path.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2),
        encoding="utf-8",
    )

    csv_path = output_dir / "model_eval_report.csv"
    fieldnames = [
        "model",
        "mode",
        "backend",
        "triangles",
        "elapsed_seconds",
        "faces",
        "original_vertices",
        "deduplicated_vertices",
        "verify_pass",
        "volume_diff_percent",
        "surface_area_diff_percent",
        "output_type",
        "used_fallback",
        "fallback_reason",
        "recognition_attempted",
        "recognition_backend_used",
        "scad_size_bytes",
        "scad_output",
        "error",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k) for k in fieldnames})

    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote CSV report: {csv_path}")
    print(
        "Summary: "
        f"total={summary['count_total']} "
        f"errors={summary['count_errors']} "
        f"verify_pass={summary['count_verify_pass']} "
        f"parametric_fallback={summary['count_parametric_fallback']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())