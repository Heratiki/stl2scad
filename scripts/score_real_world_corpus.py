"""Score a labeled real-world STL corpus and compare against a baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.real_world_corpus import (
    compare_real_world_score_to_baseline,
    list_missing_real_world_corpus_files,
    load_real_world_corpus_manifest,
    resolve_real_world_corpus_root,
    score_real_world_corpus,
    serialize_real_world_corpus_score,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default="tests/data/real_world_corpus_manifest.json",
        help="Path to the real-world corpus manifest.",
    )
    parser.add_argument(
        "--corpus-root",
        default=None,
        help="Optional override for the corpus root directory.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/real_world_recall.json",
        help="Output JSON path for the current recall score.",
    )
    parser.add_argument(
        "--baseline",
        default="artifacts/real_world_recall_baseline.json",
        help="Committed baseline artifact to compare against.",
    )
    parser.add_argument(
        "--delta-output",
        default="artifacts/real_world_recall_delta.json",
        help="Output JSON path for the baseline delta report.",
    )
    args = parser.parse_args(argv)

    manifest = load_real_world_corpus_manifest(args.manifest)
    corpus_root = resolve_real_world_corpus_root(
        args.manifest,
        manifest,
        args.corpus_root,
    )
    missing = list_missing_real_world_corpus_files(manifest["cases"], corpus_root)
    if missing:
        print(
            "Real-world corpus files missing; skipping score run. "
            f"Missing {len(missing)} files under {corpus_root}",
            file=sys.stderr,
        )
        return 0

    score = score_real_world_corpus(
        DetectorConfig(),
        manifest_path=args.manifest,
        corpus_root=corpus_root,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(serialize_real_world_corpus_score(score), indent=2),
        encoding="utf-8",
    )
    print(f"Real-world recall written to: {output_path}")
    print(f"Files present: {score.files_present}")
    print(f"Mean score: {score.mean_score:.4f}")
    print(f"Preview-ready ratio: {score.preview_ready_ratio:.4f}")
    print(f"Feature-family recall: {score.feature_family_recall}")

    baseline_path = Path(args.baseline)
    if baseline_path.exists():
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        delta = compare_real_world_score_to_baseline(score, baseline_payload)
        delta_path = Path(args.delta_output)
        delta_path.parent.mkdir(parents=True, exist_ok=True)
        delta_path.write_text(json.dumps(delta, indent=2), encoding="utf-8")
        print(f"Real-world recall delta written to: {delta_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
