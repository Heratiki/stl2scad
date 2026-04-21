"""
Build intermediate feature graphs for STL files.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.feature_graph import (
    build_feature_graph_for_folder,
    build_feature_graph_for_stl,
    emit_feature_graph_scad_preview,
)
from stl2scad.core.feature_inventory import (
    InventoryConfig,
    analyze_stl_folder_for_feature_graphs,
)


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
    parser.add_argument(
        "--scad-preview",
        default=None,
        help="Optional SCAD preview output path for a single STL input.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel workers for directory scans. Use 0 for auto, 1 for serial.",
    )
    parser.add_argument(
        "--inventory-prefilter",
        action="store_true",
        help="For directory inputs, run inventory first and graph only likely mechanical candidates.",
    )
    parser.add_argument(
        "--inventory-output",
        default=None,
        help="Optional inventory JSON output path when using --inventory-prefilter.",
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

    input_path = Path(args.input_path)
    output_path = Path(args.output)
    if not input_path.is_dir() and (args.inventory_prefilter or args.inventory_output):
        raise ValueError(
            "--inventory-prefilter and --inventory-output require a directory input."
        )
    if input_path.is_dir():
        workers = _resolve_workers(args.workers)

        def _progress(done: int, total: int, path: str) -> None:
            print(
                f"\r[{done}/{total}] {Path(path).name}",
                end="",
                flush=True,
                file=sys.stderr,
            )
            if done == total:
                print(file=sys.stderr)

        if args.inventory_prefilter:

            def _inventory_progress(done: int, total: int, path: str) -> None:
                print(
                    f"\r[inventory {done}/{total}] {Path(path).name}",
                    end="",
                    flush=True,
                    file=sys.stderr,
                )
                if done == total:
                    print(file=sys.stderr)

            def _graph_progress(done: int, total: int, path: str) -> None:
                print(
                    f"\r[graph {done}/{total}] {Path(path).name}",
                    end="",
                    flush=True,
                    file=sys.stderr,
                )
                if done == total:
                    print(file=sys.stderr)

            report = analyze_stl_folder_for_feature_graphs(
                input_dir=input_path,
                output_json=output_path,
                inventory_config=InventoryConfig(
                    recursive=not args.no_recursive,
                    max_files=args.max_files,
                    workers=workers,
                ),
                graph_workers=workers,
                inventory_output_json=(
                    Path(args.inventory_output)
                    if args.inventory_output is not None
                    else None
                ),
                inventory_progress_callback=_inventory_progress,
                graph_progress_callback=_graph_progress,
            )
        else:
            report = build_feature_graph_for_folder(
                input_path,
                output_path,
                recursive=not args.no_recursive,
                max_files=args.max_files,
                workers=workers,
                progress_callback=_progress,
            )
        summary = report["summary"]
        print(f"Feature graph report written to: {output_path}")
        if args.inventory_prefilter:
            inventory_summary = report["inventory_summary"]
            selection = report["selection"]
            print(f"Files analyzed: {inventory_summary['file_count']}")
            print(
                f"Mechanical candidates processed: {selection['mechanical_candidate_count']}"
            )
            print(
                f"Skipped non-mechanical: {selection['skipped_non_mechanical_count']}"
            )
            if args.inventory_output:
                print(f"Inventory report written to: {args.inventory_output}")
        else:
            print(f"Files analyzed: {summary['file_count']}")
        print(f"Workers: {workers}")
        print(f"Errors: {summary['error_count']}")
        print(f"Features: {summary['feature_counts']}")
        return 0

    graph = build_feature_graph_for_stl(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"Feature graph written to: {output_path}")
    print(f"Features: {len(graph['features'])}")
    if args.scad_preview:
        scad = emit_feature_graph_scad_preview(graph)
        if scad is None:
            print(
                "SCAD preview not emitted: no high-confidence supported feature combination."
            )
        else:
            scad_path = Path(args.scad_preview)
            scad_path.parent.mkdir(parents=True, exist_ok=True)
            scad_path.write_text(scad, encoding="utf-8")
            print(f"SCAD preview written to: {scad_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
