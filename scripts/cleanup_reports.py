"""Prune JSON/CSV report artifacts to limit disk usage and stale data.

Usage examples:
  python scripts/cleanup_reports.py --dry-run
  python scripts/cleanup_reports.py --apply --max-age-days 14 --max-total-bytes 500000000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import Any


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cleanup stale/old report files under artifacts/reports."
    )
    parser.add_argument(
        "--reports-dir",
        default="artifacts/reports",
        help="Directory containing report artifacts.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=30,
        help="Delete report files older than this many days (default: 30).",
    )
    parser.add_argument(
        "--max-total-bytes",
        type=int,
        default=1_000_000_000,
        help="Target maximum total size for report files after pruning (default: 1GB).",
    )
    parser.add_argument(
        "--extensions",
        default=".json,.csv",
        help="Comma-separated file extensions to manage (default: .json,.csv).",
    )
    parser.add_argument(
        "--delete-stale-commit",
        action="store_true",
        help="Delete JSON reports whose summary.git_commit differs from current git commit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting files.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions (if omitted, behaves like dry-run).",
    )
    return parser


def _current_commit(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def _read_summary_commit(path: Path) -> str:
    if path.suffix.lower() != ".json":
        return ""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        summary = data.get("summary", {}) if isinstance(data, dict) else {}
        commit = summary.get("git_commit", "") if isinstance(summary, dict) else ""
        return str(commit)
    except Exception:
        return ""


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    if not reports_dir.exists():
        raise FileNotFoundError(f"reports directory not found: {reports_dir}")

    extensions = {e.strip().lower() for e in args.extensions.split(",") if e.strip()}
    files = [
        p
        for p in reports_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in extensions
    ]

    now = time.time()
    max_age_seconds = max(0, int(args.max_age_days)) * 24 * 3600
    repo_root = Path(__file__).resolve().parents[1]
    commit_now = _current_commit(repo_root)

    to_delete: list[Path] = []
    reasons: dict[Path, str] = {}

    # Age/commit based pruning candidates
    for path in files:
        age_seconds = now - path.stat().st_mtime
        if age_seconds > max_age_seconds:
            to_delete.append(path)
            reasons[path] = f"older_than_{args.max_age_days}d"
            continue

        if args.delete_stale_commit:
            file_commit = _read_summary_commit(path)
            if file_commit and commit_now != "unknown" and file_commit != commit_now:
                to_delete.append(path)
                reasons[path] = "stale_git_commit"

    # Size-budget pruning (oldest first), excluding already-selected
    kept = [p for p in files if p not in to_delete]
    total_bytes = sum(p.stat().st_size for p in kept)
    if total_bytes > args.max_total_bytes:
        kept_sorted = sorted(kept, key=lambda p: p.stat().st_mtime)
        for path in kept_sorted:
            if total_bytes <= args.max_total_bytes:
                break
            to_delete.append(path)
            reasons[path] = reasons.get(path, "size_budget")
            total_bytes -= path.stat().st_size

    delete_unique = sorted(set(to_delete), key=lambda p: str(p))
    bytes_to_delete = sum(p.stat().st_size for p in delete_unique if p.exists())

    mode = "APPLY" if args.apply and not args.dry_run else "DRY-RUN"
    print(f"Cleanup mode: {mode}")
    print(f"Reports dir: {reports_dir}")
    print(f"Current git commit: {commit_now}")
    print(f"Candidate files: {len(files)}")
    print(f"Planned deletions: {len(delete_unique)}")
    print(f"Bytes to delete: {bytes_to_delete}")

    for path in delete_unique[:100]:
        print(f"  {path}: {reasons.get(path, '')}")
    if len(delete_unique) > 100:
        print(f"  ... and {len(delete_unique) - 100} more")

    if args.apply and not args.dry_run:
        deleted = 0
        for path in delete_unique:
            if not path.exists():
                continue
            path.unlink()
            deleted += 1
        print(f"Deleted files: {deleted}")
    else:
        print("No files deleted (dry-run).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
