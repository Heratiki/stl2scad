"""
Generate OpenSCAD ground-truth feature fixtures from a manifest.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.feature_fixtures import write_feature_fixture_library


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate manifest-driven OpenSCAD feature fixtures."
    )
    parser.add_argument(
        "--manifest",
        default="tests/data/feature_fixtures_manifest.json",
        help="Path to the feature fixture manifest JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="tests/data/feature_fixtures_scad",
        help="Directory where generated SCAD fixtures will be written.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    written = write_feature_fixture_library(args.manifest, args.output_dir)
    print(f"Wrote {len(written)} feature fixtures to {args.output_dir}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
