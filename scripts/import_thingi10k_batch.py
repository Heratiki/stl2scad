"""Import a deterministic Thingi10K batch and write a committed manifest.

Downloads only the metadata CSV (< 2 MB); the actual STL files are NOT
downloaded by this script.  Use materialize_thingi10k_batch.py to fetch them.

Example
-------
python scripts/import_thingi10k_batch.py \\
    --batch-id batch_001 --seed 1 --limit 100 \\
    --output tests/data/thingi10k_batch_001_manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.tuning.thingi10k import (
    ALLOWED_LICENSES,
    build_thingi10k_batch_manifest,
    load_thingi10k_metadata,
    select_thingi10k_batch,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-id",
        default="batch_001",
        help="Short identifier embedded in the manifest (e.g. batch_001).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Random seed for deterministic selection (default: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of STL entries to select (default: 100).",
    )
    parser.add_argument(
        "--licenses",
        default=",".join(sorted(ALLOWED_LICENSES)),
        help=(
            "Comma-separated license strings to include. "
            f"Default: {','.join(sorted(ALLOWED_LICENSES))}"
        ),
    )
    parser.add_argument(
        "--output",
        default="tests/data/thingi10k_batch_001_manifest.json",
        help="Output manifest path (default: tests/data/thingi10k_batch_001_manifest.json).",
    )
    parser.add_argument(
        "--metadata-cache",
        default=".local/thingi10k_meta",
        help="Directory to cache the downloaded metadata CSV.",
    )
    parser.add_argument(
        "--hf-token",
        default=os.environ.get("HF_TOKEN"),
        help="HuggingFace token (or set HF_TOKEN env var) for higher rate limits.",
    )
    parser.add_argument(
        "--manifold-only",
        action="store_true",
        default=True,
        help="Only include manifold-clean STLs (default: True).",
    )
    parser.add_argument(
        "--include-non-manifold",
        dest="manifold_only",
        action="store_false",
        help="Include non-manifold STLs (overrides --manifold-only).",
    )
    args = parser.parse_args(argv)

    allowed = [lic.strip() for lic in args.licenses.split(",") if lic.strip()]
    print(f"Loading Thingi10K metadata (manifold_only={args.manifold_only})...")
    rows = load_thingi10k_metadata(
        hf_token=args.hf_token,
        metadata_cache_dir=args.metadata_cache,
        manifold_only=args.manifold_only,
    )
    print(f"  Manifold-clean rows available: {len(rows)}")

    selected = select_thingi10k_batch(
        rows,
        allowed_licenses=allowed,
        limit=args.limit,
        seed=args.seed,
    )
    print(f"  Selected {len(selected)} entries (seed={args.seed}, limit={args.limit}).")

    manifest = build_thingi10k_batch_manifest(
        selected,
        batch_id=args.batch_id,
        seed=args.seed,
        limit=args.limit,
        allowed_licenses=allowed,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written to: {output_path}")
    print(f"  Entries: {len(manifest['entries'])}")
    print(f"  sha256/file_size fields are empty — run materialize_thingi10k_batch.py to populate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
