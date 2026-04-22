"""Summarize a single-file feature graph JSON artifact."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


Feature = dict[str, Any]
PREVIEW_SOLID_CONFIDENCE_THRESHOLD = 0.70
PREVIEW_SOLID_CONFIDENCE_EPSILON = 0.002


def _fmt_float(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return str(value)


def _best_candidate(features: list[Feature], feature_type: str) -> Feature | None:
    matches = [f for f in features if f.get("type") == feature_type]
    if not matches:
        return None
    return max(matches, key=lambda f: float(f.get("confidence", 0.0)))


def _print_preview_gate_diagnostics(graph: dict[str, Any], features: list[Feature]) -> None:
    plate = _best_candidate(features, "plate_like_solid")
    box = _best_candidate(features, "box_like_solid")

    plate_conf = float(plate.get("confidence", 0.0)) if plate else None
    box_conf = float(box.get("confidence", 0.0)) if box else None

    chosen_type = "none"
    chosen_conf: float | None = None
    if plate_conf is not None:
        chosen_type = "plate_like_solid"
        chosen_conf = plate_conf
    elif box_conf is not None:
        chosen_type = "box_like_solid"
        chosen_conf = box_conf

    threshold = PREVIEW_SOLID_CONFIDENCE_THRESHOLD
    epsilon = PREVIEW_SOLID_CONFIDENCE_EPSILON
    pass_primary_gate = bool(chosen_conf is not None and chosen_conf + epsilon >= threshold)
    margin = (chosen_conf - threshold) if chosen_conf is not None else None

    print("Preview gate diagnostics:")
    print(f"  threshold={threshold:.2f}")
    print(f"  epsilon={epsilon:.4f}")
    print(f"  best_plate_confidence={_fmt_float(plate_conf)}")
    print(f"  best_box_confidence={_fmt_float(box_conf)}")
    print(f"  chosen_candidate={chosen_type}")
    print(f"  chosen_confidence={_fmt_float(chosen_conf)}")
    print(f"  margin_to_threshold={_fmt_float(margin)}")
    print(f"  pass_primary_solid_gate={pass_primary_gate}")

    # Confirm final preview decision with production emitter logic.
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    preview_emitted = emit_feature_graph_scad_preview(graph) is not None
    print(f"  preview_emitted={preview_emitted}")


def summarize(path: Path, diagnose_preview_gate: bool = False) -> int:
    graph = json.loads(path.read_text(encoding="utf-8"))
    source_file = graph.get("source_file", "-")
    features: list[Feature] = graph.get("features") or []
    feature_counts = Counter(f.get("type", "unknown") for f in features)
    mesh = graph.get("mesh") or {}
    bbox = mesh.get("bounding_box") or {}

    print(f"Feature graph: {path}")
    print(f"Source STL: {source_file}")
    print(f"Generated: {graph.get('generated_at_utc', '-')}")
    print(f"Triangles: {mesh.get('triangles', '-')}")
    print(f"Surface area: {_fmt_float(mesh.get('surface_area'))}")
    print(
        "Bounding box (W x H x D): "
        f"{_fmt_float(bbox.get('width'))} x "
        f"{_fmt_float(bbox.get('height'))} x "
        f"{_fmt_float(bbox.get('depth'))}"
    )

    print(f"Feature count: {len(features)}")
    if feature_counts:
        print("Feature types:")
        for feature_type, count in sorted(feature_counts.items()):
            print(f"  {feature_type}: {count}")
    else:
        print("Feature types: (none)")

    axis_pairs = [f for f in features if f.get("type") == "axis_boundary_plane_pair"]
    if axis_pairs:
        print("Axis boundary plane pairs:")
        for pair in axis_pairs:
            axis = pair.get("axis", "-")
            neg = _fmt_float(pair.get("negative_area"))
            pos = _fmt_float(pair.get("positive_area"))
            paired = pair.get("paired", False)
            print(f"  axis={axis} paired={paired} area_neg={neg} area_pos={pos}")

    candidates = [
        f
        for f in features
        if f.get("type") in {"plate_like_solid", "box_like_solid"}
    ]
    if candidates:
        print("Solid candidates:")
        for candidate in candidates:
            ctype = candidate.get("type", "-")
            conf = _fmt_float(candidate.get("confidence"))
            print(f"  type={ctype} confidence={conf}")

    if diagnose_preview_gate:
        _print_preview_gate_diagnostics(graph, features)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "feature_graph_json",
        help="Path to single-file feature graph JSON",
    )
    parser.add_argument(
        "--diagnose-preview-gate",
        action="store_true",
        help="Print pass/fail diagnostics for the SCAD preview confidence gate.",
    )
    args = parser.parse_args()

    path = Path(args.feature_graph_json)
    if not path.exists():
        raise FileNotFoundError(f"Feature graph JSON not found: {path}")

    return summarize(path, diagnose_preview_gate=args.diagnose_preview_gate)


if __name__ == "__main__":
    raise SystemExit(main())
