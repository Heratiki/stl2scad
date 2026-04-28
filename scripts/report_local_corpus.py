"""Generate a standalone HTML report for a user-local corpus score JSON."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.tuning.html_report import generate_html_report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--score",
        default="artifacts/local_corpus_score.json",
        help="Path to local corpus score JSON.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/local_corpus_report.html",
        help="Output HTML path.",
    )
    parser.add_argument(
        "--thumb-cache",
        default="artifacts/thumbs",
        help="Directory for cached STL thumbnail PNGs.",
    )
    args = parser.parse_args(argv)

    if not Path(args.score).exists():
        parser.error(f"Score JSON not found: {args.score}")

    output = generate_html_report(
        args.score,
        args.output,
        thumb_cache_dir=args.thumb_cache,
    )
    print(f"Local corpus HTML report written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
