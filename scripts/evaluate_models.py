"""Evaluate STL models with conversion and verification metrics.

This script is intended for repeatable model benchmarking in local development.
It runs conversion in polyhedron and/or parametric mode, verifies generated
SCAD output against source STL, and writes machine-readable JSON/CSV reports.
"""

from __future__ import annotations

import argparse
import csv
import json
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


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

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
    for stl_path in stl_files:
        tri_count = _load_triangles(stl_path)
        for mode in modes:
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
                t0 = perf_counter()
                stats = stl2scad(
                    str(stl_path),
                    str(scad_path),
                    parametric=is_parametric,
                    recognition_backend=args.backend,
                )
                elapsed = perf_counter() - t0

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
                        "scad_size_bytes": scad_path.stat().st_size,
                        "error": "",
                    }
                )
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

    summary = {
        "models_dir": str(models_dir),
        "output_dir": str(output_dir),
        "backend": args.backend,
        "modes": modes,
        "count_total": len(results),
        "count_errors": sum(1 for r in results if r.get("error")),
        "count_verify_pass": sum(1 for r in results if r.get("verify_pass") is True),
        "count_parametric_fallback": sum(
            1 for r in results if r.get("used_fallback") is True
        ),
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