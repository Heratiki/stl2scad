"""Rank no-preview triage files by proximity to SCAD preview confidence gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PREVIEW_SOLID_CONFIDENCE_THRESHOLD = 0.70


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _best_confidence(metadata: dict[str, Any]) -> tuple[str, float | None]:
    plate = metadata.get("plate_candidate_confidence")
    box = metadata.get("box_candidate_confidence")
    if plate is not None:
        return "plate_like_solid", float(plate)
    if box is not None:
        return "box_like_solid", float(box)
    solid_confidences = metadata.get("solid_candidate_confidences") or {}
    if solid_confidences:
        best_type, best_confidence = max(
            solid_confidences.items(),
            key=lambda item: float(item[1]),
        )
        return str(best_type), float(best_confidence)
    return "none", None


def rank_candidates(
    triage_path: Path,
    top: int,
    bucket: str,
    min_confidence: float,
    max_margin: float,
) -> int:
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
    per_file = triage.get("per_file") or []

    rows: list[dict[str, Any]] = []
    for entry in per_file:
        if entry.get("bucket") != bucket:
            continue
        metadata = entry.get("failure_shape_metadata") or {}
        source_file = entry.get("source_file")
        candidate_type, confidence = _best_confidence(metadata)
        if confidence is None or confidence < min_confidence:
            continue
        margin = confidence - PREVIEW_SOLID_CONFIDENCE_THRESHOLD
        if margin > max_margin:
            continue
        rows.append(
            {
                "source_file": source_file,
                "candidate_type": candidate_type,
                "confidence": confidence,
                "margin_to_threshold": margin,
                "planar_support_fraction": metadata.get("planar_support_fraction"),
                "axis_pair_count": metadata.get("axis_pair_count"),
                "paired_axis_count": metadata.get("paired_axis_count"),
            }
        )

    rows.sort(
        key=lambda r: (
            abs(float(r["margin_to_threshold"])),
            -float(r["confidence"]),
            -float(r.get("planar_support_fraction") or 0.0),
        )
    )

    print(f"Triage file: {triage_path}")
    print(f"Input dir: {triage.get('input_dir', '-')}")
    print(f"Bucket filter: {bucket}")
    print(f"Confidence threshold: {PREVIEW_SOLID_CONFIDENCE_THRESHOLD:.2f}")
    print(f"Min candidate confidence: {min_confidence:.2f}")
    print(f"Max allowed margin to threshold: {max_margin:.4f}")
    print(f"Matched candidates: {len(rows)}")

    headers = [
        "source_file",
        "candidate_type",
        "confidence",
        "margin_to_threshold",
        "planar_support_fraction",
        "axis_pair_count",
        "paired_axis_count",
    ]
    print("\n" + " | ".join(headers))
    print("-|-".join("-" * len(h) for h in headers))
    for row in rows[:top]:
        print(
            " | ".join(
                [
                    _fmt(row["source_file"]),
                    _fmt(row["candidate_type"]),
                    _fmt(row["confidence"]),
                    _fmt(row["margin_to_threshold"]),
                    _fmt(row["planar_support_fraction"]),
                    _fmt(row["axis_pair_count"]),
                    _fmt(row["paired_axis_count"]),
                ]
            )
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "triage_json",
        nargs="?",
        default="artifacts/feature_graph_triage.json",
        help="Path to triage JSON file (default: artifacts/feature_graph_triage.json)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of rows to print (default: 10)",
    )
    parser.add_argument(
        "--bucket",
        default="feature_graph_no_preview",
        choices=["feature_graph_no_preview", "axis_pairs_only"],
        help="Bucket to scan for candidates (default: feature_graph_no_preview)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.50,
        help="Minimum candidate confidence to include (default: 0.50)",
    )
    parser.add_argument(
        "--max-margin",
        type=float,
        default=0.0,
        help=(
            "Maximum margin to threshold to include. "
            "Use 0.0 to include only below-threshold candidates; "
            "use >0 to include slight over-threshold candidates."
        ),
    )
    args = parser.parse_args()

    triage_path = Path(args.triage_json)
    if not triage_path.exists():
        raise FileNotFoundError(f"Triage JSON not found: {triage_path}")
    if args.top <= 0:
        raise ValueError("--top must be > 0")

    return rank_candidates(
        triage_path=triage_path,
        top=args.top,
        bucket=args.bucket,
        min_confidence=args.min_confidence,
        max_margin=args.max_margin,
    )


if __name__ == "__main__":
    raise SystemExit(main())
