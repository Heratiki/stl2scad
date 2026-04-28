"""Score a user-local STL corpus manifest and optionally compare to a baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.tuning.local_corpus import (
    compare_local_corpus_score_to_baseline,
    score_local_corpus,
)
from stl2scad.tuning.progress import corpus_progress


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=".local/local_corpus.json",
        help="Path to local corpus manifest.",
    )
    parser.add_argument(
        "--corpus-root",
        default=None,
        help="Optional override for the manifest-relative corpus root.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/local_corpus_score.json",
        help="Output JSON path for the current score.",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Optional prior score JSON to compare against.",
    )
    parser.add_argument(
        "--delta-output",
        default="artifacts/local_corpus_delta.json",
        help="Output JSON path for baseline delta when --baseline is supplied.",
    )
    parser.add_argument(
        "--triage-top-n",
        type=int,
        default=5,
        help="Number of ranked failure patterns to retain.",
    )
    parser.add_argument(
        "--html-report",
        action="store_true",
        help="Generate a self-contained HTML report after scoring.",
    )
    parser.add_argument(
        "--html-output",
        default="artifacts/local_corpus_report.html",
        help="Output HTML path when --html-report is supplied.",
    )
    parser.add_argument(
        "--thumb-cache",
        default="artifacts/thumbs",
        help="Directory for cached STL thumbnail PNGs.",
    )
    args = parser.parse_args(argv)

    score = score_local_corpus(
        args.manifest,
        corpus_root=args.corpus_root,
        triage_top_n=args.triage_top_n,
        progress_fn=corpus_progress,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(score, indent=2), encoding="utf-8")

    counts = score["triage"]["bucket_counts"]
    print(f"Local corpus score written to: {output_path}")
    print(f"Files present: {score['files_present']}")
    print(f"Files missing: {score['files_missing']}")
    print(f"Fingerprint mismatches: {score['fingerprint_mismatch_count']}")
    print(
        "Buckets: "
        f"parametric_preview={counts['parametric_preview']} "
        f"feature_graph_no_preview={counts['feature_graph_no_preview']} "
        f"axis_pairs_only={counts['axis_pairs_only']} "
        f"polyhedron_fallback={counts['polyhedron_fallback']} "
        f"error={counts['error']}"
    )

    if args.baseline is not None:
        baseline_path = Path(args.baseline)
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        delta = compare_local_corpus_score_to_baseline(score, baseline)
        delta_path = Path(args.delta_output)
        delta_path.parent.mkdir(parents=True, exist_ok=True)
        delta_path.write_text(json.dumps(delta, indent=2), encoding="utf-8")
        print(f"Local corpus delta written to: {delta_path}")

    if args.html_report:
        from stl2scad.tuning.html_report import generate_html_report

        report_path = generate_html_report(
            output_path,
            args.html_output,
            thumb_cache_dir=args.thumb_cache,
        )
        print(f"Local corpus HTML report written to: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
