"""
Analyze arbitrary STL folders for feature-level reconstruction signals.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.feature_inventory import InventoryConfig, analyze_stl_folder


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze STL files for feature-level parametric reconstruction signals."
    )
    parser.add_argument("input_dir", help="Directory containing STL files to analyze.")
    parser.add_argument(
        "--output",
        default="artifacts/feature_inventory.json",
        help="Path to JSON inventory output file.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on files analyzed, useful for first-pass sampling.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only analyze STL files directly in input_dir.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel workers for folder scans. Use 0 for auto, 1 for serial.",
    )
    return parser


def _resolve_workers(value: int) -> int:
    if value < 0:
        raise ValueError("--workers must be >= 0")
    if value == 0:
        return max(1, min(os.cpu_count() or 1, 32))
    return value


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    workers = _resolve_workers(args.workers)

    report = analyze_stl_folder(
        input_dir=Path(args.input_dir),
        output_json=Path(args.output),
        config=InventoryConfig(
            recursive=not args.no_recursive,
            max_files=args.max_files,
            workers=workers,
        ),
    )

    summary = report["summary"]
    print(f"Feature inventory written to: {args.output}")
    print(f"Files analyzed: {summary['file_count']}")
    print(f"Workers: {workers}")
    print(f"OK: {summary['ok_count']}")
    print(f"Errors: {summary['error_count']}")
    print(f"Classifications: {summary['classification_counts']}")
    print(f"Candidate features: {summary['candidate_feature_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
