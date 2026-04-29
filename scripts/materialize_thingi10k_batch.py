"""Download and cache Thingi10K STL files for a committed batch manifest.

STL files are cached to a gitignored local directory (default: .local/thingi10k).
The manifest is updated in-place with sha256 and file_size_bytes when files are
newly downloaded.

Example
-------
python scripts/materialize_thingi10k_batch.py \\
    --manifest tests/data/thingi10k_batch_001_manifest.json \\
    --cache .local/thingi10k
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
    list_missing_thingi10k_files,
    load_thingi10k_batch_manifest,
    materialize_thingi10k_batch,
)
from stl2scad.tuning.progress import corpus_progress


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
        help="Root directory for the local STL cache (default: .local/thingi10k).",
    )
    parser.add_argument(
        "--hf-token",
        default=os.environ.get("HF_TOKEN"),
        help="HuggingFace token (or set HF_TOKEN env var) for higher rate limits.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if a local file already exists.",
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        default=True,
        help=(
            "Write updated sha256/file_size_bytes back to the manifest file "
            "(default: True)."
        ),
    )
    parser.add_argument(
        "--no-update-manifest",
        dest="update_manifest",
        action="store_false",
        help="Do not modify the manifest file after downloading.",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    manifest = load_thingi10k_batch_manifest(manifest_path)

    missing = list_missing_thingi10k_files(manifest, args.cache)
    n_total = len(manifest["entries"])
    print(
        f"Batch: {manifest.get('batch_id')}  |  "
        f"Total entries: {n_total}  |  "
        f"Already cached: {n_total - len(missing)}  |  "
        f"To download: {len(missing)}"
    )
    if not missing:
        print("All STLs already cached — nothing to download.")
        return 0

    result = materialize_thingi10k_batch(
        manifest,
        args.cache,
        hf_token=args.hf_token,
        progress_fn=corpus_progress,
        force=args.force,
    )

    print(
        f"\nDownload complete:"
        f"  downloaded={result['downloaded']}"
        f"  skipped={result['skipped']}"
        f"  failed={result['failed']}"
    )
    print(f"  Cache dir: {result['cache_dir']}")

    failed_entries = [e for e in result["per_entry"] if e["status"] == "failed"]
    if failed_entries:
        print(f"\nFailed downloads ({len(failed_entries)}):")
        for e in failed_entries[:10]:
            print(f"  file_id={e['file_id']}: {e.get('error', '?')}")
        if len(failed_entries) > 10:
            print(f"  ... and {len(failed_entries) - 10} more")

    if args.update_manifest and result["downloaded"] > 0:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"\nManifest updated with sha256/file_size_bytes: {manifest_path}")
        print("  Commit the updated manifest if sha256 values should be recorded.")

    return 1 if result["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
