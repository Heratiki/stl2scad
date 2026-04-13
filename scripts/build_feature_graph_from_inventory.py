"""
Build feature graphs for mechanical candidates from a feature inventory report.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.feature_inventory import build_feature_graphs_from_inventory


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build feature graphs for mechanical candidates from an inventory report."
    )
    parser.add_argument(
        "inventory_json",
        help="Path to a feature inventory JSON file.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/feature_graph_from_inventory.json",
        help="Path to JSON feature-graph output.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel workers for graph building. Use 0 for auto, 1 for serial.",
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

    report = build_feature_graphs_from_inventory(
        inventory=Path(args.inventory_json),
        output_json=Path(args.output),
        workers=workers,
    )

    summary = report["summary"]
    selection = report["selection"]
    print(f"Feature graph report written to: {args.output}")
    print(f"Mechanical candidates processed: {selection['mechanical_candidate_count']}")
    print(f"Workers: {workers}")
    print(f"Errors: {summary['error_count']}")
    print(f"Features: {summary['feature_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
