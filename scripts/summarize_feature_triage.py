"""Summarize a feature-graph triage JSON report with actionable fixture candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


Metadata = dict[str, Any]
TriageRow = dict[str, Any]


def _metadata(row: TriageRow) -> Metadata:
    return row.get("failure_shape_metadata") or {}


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _print_rows(title: str, rows: list[TriageRow], limit: int) -> None:
    print(f"\n{title} (top {min(limit, len(rows))}/{len(rows)}):")
    if not rows:
        print("  (none)")
        return
    headers = [
        "source_file",
        "bucket",
        "planar_support_fraction",
        "axis_pair_count",
        "paired_axis_count",
        "thinnest_axis",
    ]
    print("  " + " | ".join(headers))
    print("  " + "-|-".join("-" * len(h) for h in headers))
    for row in rows[:limit]:
        meta = _metadata(row)
        print(
            "  "
            + " | ".join(
                [
                    _fmt(row.get("source_file")),
                    _fmt(row.get("bucket")),
                    _fmt(meta.get("planar_support_fraction")),
                    _fmt(meta.get("axis_pair_count")),
                    _fmt(meta.get("paired_axis_count")),
                    _fmt(meta.get("thinnest_axis")),
                ]
            )
        )


def _sorted_axis_only(rows: list[TriageRow]) -> list[TriageRow]:
    return sorted(
        [r for r in rows if r.get("bucket") == "axis_pairs_only"],
        key=lambda r: (_metadata(r).get("planar_support_fraction", -1.0)),
        reverse=True,
    )


def _sorted_partial_pair(rows: list[TriageRow]) -> list[TriageRow]:
    candidates = [
        r
        for r in rows
        if r.get("bucket") == "axis_pairs_only"
        and _metadata(r).get("paired_axis_count", 0)
        < _metadata(r).get("axis_pair_count", 0)
    ]
    return sorted(
        candidates,
        key=lambda r: (
            _metadata(r).get("axis_pair_count", 0)
            - _metadata(r).get("paired_axis_count", 0),
            _metadata(r).get("planar_support_fraction", 0.0),
        ),
        reverse=True,
    )


def summarize(path: Path, top_n: int) -> int:
    triage = json.loads(path.read_text(encoding="utf-8"))
    per_file: list[TriageRow] = triage.get("per_file") or []

    print(f"Triage file: {path}")
    print(f"Input dir: {triage.get('input_dir', '-')}")
    print(f"Generated: {triage.get('generated_at_utc', '-')}")
    print(f"Files processed: {triage.get('files_processed', '-')}")

    counts = triage.get("bucket_counts") or {}
    print("Bucket counts:")
    for key in [
        "parametric_preview",
        "feature_graph_no_preview",
        "axis_pairs_only",
        "polyhedron_fallback",
        "error",
    ]:
        print(f"  {key}: {counts.get(key, 0)}")

    patterns = triage.get("ranked_failure_patterns") or []
    print("\nRanked failure patterns:")
    if patterns:
        for item in patterns:
            print(
                "  "
                f"[{item.get('count', 0)}] {item.get('pattern', '-')} "
                f"(example: {item.get('representative_file', '-')})"
            )
    else:
        print("  (none)")

    feature_no_preview = [r for r in per_file if r.get("bucket") == "feature_graph_no_preview"]
    _print_rows("feature_graph_no_preview", feature_no_preview, top_n)
    _print_rows(
        "axis_pairs_only by planar_support_fraction",
        _sorted_axis_only(per_file),
        top_n,
    )
    _print_rows(
        "axis_pairs_only with partial axis pairing",
        _sorted_partial_pair(per_file),
        top_n,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "triage_json",
        nargs="?",
        default="artifacts/feature_graph_triage.json",
        help="Path to triage JSON (default: artifacts/feature_graph_triage.json)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of rows to show per section (default: 10)",
    )
    args = parser.parse_args()

    path = Path(args.triage_json)
    if not path.exists():
        raise FileNotFoundError(f"Triage JSON not found: {path}")
    if args.top <= 0:
        raise ValueError("--top must be > 0")

    return summarize(path, top_n=args.top)


if __name__ == "__main__":
    raise SystemExit(main())
