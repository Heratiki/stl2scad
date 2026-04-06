"""
Run conversion performance baselines against benchmark fixtures.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.perf_baseline import run_conversion_perf_baseline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run STL-to-SCAD conversion performance baseline."
    )
    parser.add_argument(
        "--fixtures-dir",
        default="tests/data/benchmark_fixtures",
        help="Benchmark fixture directory containing manifest.json.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/perf_baseline.json",
        help="Path to JSON baseline output file.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Number of repeated runs per fixture/mode (default: 3).",
    )
    parser.add_argument(
        "--categories",
        default="performance",
        help="Comma-separated fixture categories (default: performance).",
    )
    parser.add_argument(
        "--recognition-backend",
        default="native",
        choices=["native", "trimesh_manifold", "cgal"],
        help="Recognition backend used when parametric mode is benchmarked.",
    )
    parser.add_argument(
        "--parametric-only",
        action="store_true",
        help="Only benchmark parametric mode.",
    )
    parser.add_argument(
        "--polyhedron-only",
        action="store_true",
        help="Only benchmark default polyhedron mode.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.parametric_only and args.polyhedron_only:
        raise ValueError("--parametric-only and --polyhedron-only are mutually exclusive")

    if args.parametric_only:
        modes = (True,)
    elif args.polyhedron_only:
        modes = (False,)
    else:
        modes = (False, True)

    categories: List[str] = [c.strip() for c in args.categories.split(",") if c.strip()]
    report = run_conversion_perf_baseline(
        fixtures_dir=Path(args.fixtures_dir),
        output_json=Path(args.output),
        repeat=args.repeat,
        categories=tuple(categories),
        parametric_modes=modes,
        recognition_backend=args.recognition_backend,
    )

    print(f"Performance baseline written to: {args.output}")
    print(f"Results: {len(report.get('results', []))}")
    print(f"Overall mean: {report.get('summary', {}).get('overall_elapsed_mean_seconds', 0.0):.6f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
