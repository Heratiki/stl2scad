"""
Analyze arbitrary STL folders for feature-level reconstruction signals.
"""

from __future__ import annotations

import argparse
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
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    report = analyze_stl_folder(
        input_dir=Path(args.input_dir),
        output_json=Path(args.output),
        config=InventoryConfig(
            recursive=not args.no_recursive,
            max_files=args.max_files,
        ),
    )

    summary = report["summary"]
    print(f"Feature inventory written to: {args.output}")
    print(f"Files analyzed: {summary['file_count']}")
    print(f"OK: {summary['ok_count']}")
    print(f"Errors: {summary['error_count']}")
    print(f"Classifications: {summary['classification_counts']}")
    print(f"Candidate features: {summary['candidate_feature_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
