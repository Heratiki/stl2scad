"""Score the feature-graph detector against a cached Thingi10K batch.

Produces a score JSON artifact and optionally a delta report against a
committed baseline.  Exit code 2 when a baseline regression is detected.

Example
-------
python scripts/score_thingi10k_batch.py \\
    --manifest tests/data/thingi10k_batch_001_manifest.json \\
    --cache .local/thingi10k \\
    --output artifacts/thingi10k_batch_001_score.json \\
    --baseline artifacts/thingi10k_batch_001_baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.thingi10k import (
    compare_thingi10k_score_to_baseline,
    list_missing_thingi10k_files,
    load_thingi10k_batch_manifest,
    score_thingi10k_batch,
)
from stl2scad.tuning.progress import corpus_progress

_EXIT_REGRESSION = 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="tests/data/thingi10k_batch_001_manifest.json",
        help="Path to the committed batch manifest.",
    )
    parser.add_argument(
        "--cache",
        default=".local/thingi10k",
        help="Root directory for the local STL cache.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/thingi10k_batch_001_score.json",
        help="Output path for the current score JSON.",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Path to a committed baseline score JSON to compare against.",
    )
    parser.add_argument(
        "--delta-output",
        default=None,
        help="Output path for the delta report when --baseline is supplied.",
    )
    parser.add_argument(
        "--merge-gate",
        action="store_true",
        help="Exit with code 2 when a regression against the baseline is detected.",
    )
    parser.add_argument(
        "--require-all-present",
        action="store_true",
        help="Fail with exit code 1 if any STL is missing from the cache.",
    )
    args = parser.parse_args(argv)

    manifest = load_thingi10k_batch_manifest(args.manifest)

    missing = list_missing_thingi10k_files(manifest, args.cache)
    if missing:
        print(
            f"Warning: {len(missing)} STL(s) missing from cache. "
            "Run materialize_thingi10k_batch.py first.",
            file=sys.stderr,
        )
        if args.require_all_present:
            return 1

    config = DetectorConfig()
    print(
        f"Scoring batch '{manifest.get('batch_id')}' "
        f"({len(manifest['entries'])} entries, {len(missing)} missing)..."
    )

    score = score_thingi10k_batch(
        manifest,
        args.cache,
        config=config,
        progress_fn=corpus_progress,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(score, indent=2), encoding="utf-8")
    print(f"\nScore written to: {output_path}")
    _print_score_summary(score)

    if args.baseline is None:
        return 0

    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(
            f"Baseline not found at {baseline_path}; skipping delta.",
            file=sys.stderr,
        )
        return 0

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    delta = compare_thingi10k_score_to_baseline(score, baseline)

    if args.delta_output:
        delta_path = Path(args.delta_output)
        delta_path.parent.mkdir(parents=True, exist_ok=True)
        delta_path.write_text(json.dumps(delta, indent=2), encoding="utf-8")
        print(f"Delta report written to: {delta_path}")

    _print_delta_summary(delta)

    if args.merge_gate and delta.get("regression"):
        print(
            "\nMerge gate FAILED: preview_ready_ratio regressed by "
            f"{delta['delta_preview_ready_ratio']:.4f} "
            f"(threshold: -0.02).",
            file=sys.stderr,
        )
        return _EXIT_REGRESSION

    return 0


def _print_score_summary(score: dict) -> None:
    print(
        f"  n_ok={score.get('n_ok', 0)}"
        f"  preview_ready={score.get('preview_ready_count', 0)}"
        f"  preview_ready_ratio={score.get('preview_ready_ratio', 0.0):.4f}"
    )
    buckets = score.get("bucket_counts", {})
    if buckets:
        print("  Bucket counts:")
        for bucket, count in sorted(buckets.items(), key=lambda x: -x[1]):
            print(f"    {bucket}: {count}")


def _print_delta_summary(delta: dict) -> None:
    direction = "▲" if delta["delta_preview_ready_ratio"] >= 0 else "▼"
    print(
        f"\nBaseline delta: {direction}{abs(delta['delta_preview_ready_ratio']):.4f} "
        f"(baseline={delta['baseline_preview_ready_ratio']:.4f} → "
        f"current={delta['current_preview_ready_ratio']:.4f})"
    )
    bucket_deltas = delta.get("bucket_deltas", {})
    if any(v != 0 for v in bucket_deltas.values()):
        print("  Bucket changes:")
        for bucket, change in sorted(bucket_deltas.items()):
            if change != 0:
                sign = "+" if change > 0 else ""
                print(f"    {bucket}: {sign}{change}")
    if delta.get("regression"):
        print("  ** REGRESSION DETECTED **")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
