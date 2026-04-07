"""
Build intermediate feature graphs for STL files.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.feature_graph import build_feature_graph_for_folder, build_feature_graph_for_stl


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build STL feature graph JSON.")
    parser.add_argument("input_path", help="STL file or directory to analyze.")
    parser.add_argument(
        "--output",
        default="artifacts/feature_graph.json",
        help="Path to JSON feature-graph output.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap when input_path is a directory.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only analyze STL files directly in input_path when it is a directory.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output)
    if input_path.is_dir():
        report = build_feature_graph_for_folder(
            input_path,
            output_path,
            recursive=not args.no_recursive,
            max_files=args.max_files,
        )
        summary = report["summary"]
        print(f"Feature graph report written to: {output_path}")
        print(f"Files analyzed: {summary['file_count']}")
        print(f"Errors: {summary['error_count']}")
        print(f"Features: {summary['feature_counts']}")
        return 0

    graph = build_feature_graph_for_stl(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(__import__("json").dumps(graph, indent=2), encoding="utf-8")
    print(f"Feature graph written to: {output_path}")
    print(f"Features: {len(graph['features'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
