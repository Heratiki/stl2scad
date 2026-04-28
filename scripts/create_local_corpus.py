"""Create a gitignored manifest for a private local STL corpus."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.tuning.local_corpus import create_local_corpus_manifest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", help="Directory containing local STL files.")
    parser.add_argument(
        "--output",
        default=".local/local_corpus.json",
        help="Output manifest path (default: .local/local_corpus.json).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on STL files recorded in the manifest.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only include STL files directly under input_dir.",
    )
    args = parser.parse_args(argv)

    manifest = create_local_corpus_manifest(
        args.input_dir,
        output_path=args.output,
        recursive=not args.no_recursive,
        max_files=args.max_files,
    )
    print(f"Local corpus manifest written to: {args.output}")
    print(f"Cases: {len(manifest['cases'])}")
    print("Raw STL files are not copied or committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
