"""
Generate benchmark STL fixtures used by Phase 0 and later parametric work.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.benchmark_fixtures import generate_benchmark_fixture_set


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate STL benchmark fixtures for stl2scad."
    )
    parser.add_argument(
        "--output-dir",
        default="tests/data/benchmark_fixtures",
        help="Directory where fixture STL files and manifest.json are written.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Do not overwrite existing fixture files.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    manifest = generate_benchmark_fixture_set(
        Path(args.output_dir),
        overwrite=not args.no_overwrite,
    )
    print(f"Generated {len(manifest.get('fixtures', []))} benchmark fixtures.")
    print(f"Manifest: {Path(args.output_dir) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
