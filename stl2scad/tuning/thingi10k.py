"""Thingi10K public batch management.

Downloads metadata from the Thingi10K/Thingi10K HuggingFace dataset,
selects deterministic 100-file batches filtered by license and mesh quality,
and provides caching/scoring utilities.

Requires: huggingface_hub>=0.20  (install via requirements-tuning.txt)
STL byte downloads use requests (already a core dependency).
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# ── Dataset constants ─────────────────────────────────────────────────────────
THINGI10K_HF_REPO = "Thingi10K/Thingi10K"
THINGI10K_HF_METADATA = "metadata/input_summary.csv"
THINGI10K_STL_PREFIX = "raw_meshes/"
THINGI10K_BATCH_SCHEMA_VERSION = 1

# Licenses safe for public reproducibility (from planning/feature_level_reconstruction.md).
ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "Creative Commons - Public Domain Dedication",
        "Public Domain",
        "BSD License",
    }
)


# ── Metadata loading ──────────────────────────────────────────────────────────

def load_thingi10k_metadata(
    hf_token: Optional[str] = None,
    metadata_cache_dir: Optional[Path | str] = None,
    *,
    manifold_only: bool = True,
) -> list[dict[str, str]]:
    """Download and parse input_summary.csv from the Thingi10K HuggingFace repo.

    Parameters
    ----------
    hf_token:
        Optional HuggingFace token for higher rate limits.
    metadata_cache_dir:
        Directory to cache the downloaded CSV (avoids re-downloading).
    manifold_only:
        When True (default), only rows where Closed, Edge manifold, and
        Vertex manifold are all TRUE are returned.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise ImportError(
            "huggingface_hub is required for Thingi10K batch tooling. "
            "Install with: pip install 'huggingface_hub>=0.20'"
        )

    kwargs: dict[str, Any] = {"repo_type": "dataset"}
    if hf_token:
        kwargs["token"] = hf_token
    if metadata_cache_dir is not None:
        kwargs["local_dir"] = str(metadata_cache_dir)

    csv_path = hf_hub_download(THINGI10K_HF_REPO, THINGI10K_HF_METADATA, **kwargs)

    rows: list[dict[str, str]] = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if manifold_only and not _is_manifold_clean(row):
                continue
            rows.append(dict(row))
    return rows


def _is_manifold_clean(row: dict[str, str]) -> bool:
    return (
        row.get("Closed", "").strip().upper() == "TRUE"
        and row.get("Edge manifold", "").strip().upper() == "TRUE"
        and row.get("Vertex manifold", "").strip().upper() == "TRUE"
    )


# ── Batch selection ───────────────────────────────────────────────────────────

def select_thingi10k_batch(
    metadata_rows: list[dict[str, str]],
    *,
    allowed_licenses: Iterable[str] = ALLOWED_LICENSES,
    limit: int = 100,
    seed: int = 1,
) -> list[dict[str, str]]:
    """Select a deterministic subset of metadata rows filtered by license.

    The same seed + allowed_licenses + limit always produces the same entries,
    so the resulting manifest can be committed and reproduced by anyone.
    """
    license_set = set(allowed_licenses)
    eligible = [r for r in metadata_rows if r.get("License", "") in license_set]
    if not eligible:
        raise ValueError(
            f"No eligible entries found for licenses: {sorted(license_set)}. "
            f"Scanned {len(metadata_rows)} manifold-clean rows."
        )
    rng = random.Random(seed)
    return rng.sample(eligible, min(limit, len(eligible)))


# ── Manifest build / load ─────────────────────────────────────────────────────

def build_thingi10k_batch_manifest(
    selected_rows: list[dict[str, str]],
    *,
    batch_id: str,
    seed: int,
    limit: int,
    allowed_licenses: Iterable[str] = ALLOWED_LICENSES,
    hf_repo_revision: str = "main",
) -> dict[str, Any]:
    """Build a committed manifest dict from selected metadata rows.

    sha256 and file_size_bytes are left empty; they are populated by
    materialize_thingi10k_batch() once the STL files are downloaded.
    """
    entries = []
    for row in selected_rows:
        file_id = str(row["ID"]).strip()
        entries.append(
            {
                "file_id": file_id,
                "thing_id": str(row.get("Thing ID", "")).strip(),
                "license": str(row.get("License", "")).strip(),
                "thingiverse_url": str(row.get("Link", "")).strip(),
                "hf_path": f"{THINGI10K_STL_PREFIX}{file_id}.stl",
                "sha256": "",
                "file_size_bytes": 0,
            }
        )
    return {
        "schema_version": THINGI10K_BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "limit": limit,
        "allowed_licenses": sorted(set(allowed_licenses)),
        "hf_repo": THINGI10K_HF_REPO,
        "hf_repo_revision": hf_repo_revision,
        "entries": entries,
    }


def load_thingi10k_batch_manifest(manifest_path: Path | str) -> dict[str, Any]:
    """Load and validate a committed Thingi10K batch manifest."""
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema_version = int(payload.get("schema_version", 0))
    if schema_version != THINGI10K_BATCH_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported thingi10k batch schema_version '{schema_version}'. "
            f"Expected {THINGI10K_BATCH_SCHEMA_VERSION}."
        )
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError(
            "Thingi10K batch manifest must contain a non-empty 'entries' list."
        )
    ids_seen: set[str] = set()
    for i, entry in enumerate(entries):
        fid = str(entry.get("file_id", "")).strip()
        if not fid:
            raise ValueError(f"Entry {i} is missing 'file_id'.")
        if fid in ids_seen:
            raise ValueError(f"Duplicate file_id in batch manifest: {fid}")
        ids_seen.add(fid)
    return payload


def resolve_thingi10k_cache(
    manifest: dict[str, Any],
    cache_root: Path | str,
) -> Path:
    """Return the batch-specific subdirectory inside the cache root."""
    batch_id = str(manifest.get("batch_id", "unknown"))
    return Path(cache_root) / batch_id


def list_missing_thingi10k_files(
    manifest: dict[str, Any],
    cache_root: Path | str,
) -> list[str]:
    """Return file_ids whose STL has not yet been cached."""
    cache_dir = resolve_thingi10k_cache(manifest, cache_root)
    missing: list[str] = []
    for entry in manifest.get("entries", []):
        fid = str(entry["file_id"])
        if not (cache_dir / f"{fid}.stl").exists():
            missing.append(fid)
    return missing


# ── Materialization ───────────────────────────────────────────────────────────

def materialize_thingi10k_batch(
    manifest: dict[str, Any],
    cache_root: Path | str,
    *,
    hf_token: Optional[str] = None,
    progress_fn: Optional[Callable] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Download STLs from HuggingFace into a local cache directory.

    Updates manifest entries in-place with sha256 and file_size_bytes once
    files are successfully downloaded.  Returns a result summary dict.

    The local cache layout is: ``{cache_root}/{batch_id}/{file_id}.stl``
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise ImportError(
            "huggingface_hub is required. Install with: pip install 'huggingface_hub>=0.20'"
        )

    hf_repo = str(manifest.get("hf_repo", THINGI10K_HF_REPO))
    hf_revision = str(manifest.get("hf_repo_revision", "main"))
    cache_dir = resolve_thingi10k_cache(manifest, cache_root)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # hf_hub_download caches in a HF-managed layout under local_dir; we copy
    # files into a flat per-batch layout so scripts can predict exact paths.
    hf_local_dir = cache_dir / ".hf_cache"
    hf_local_dir.mkdir(parents=True, exist_ok=True)

    entries = manifest.get("entries", [])
    iterable: Any = entries
    if progress_fn is not None:
        iterable = progress_fn(entries, desc="Downloading STLs", total=len(entries))

    downloaded = 0
    skipped = 0
    failed = 0
    per_entry: list[dict[str, Any]] = []

    for entry in iterable:
        file_id = str(entry["file_id"])
        hf_path = str(entry["hf_path"])
        local_path = cache_dir / f"{file_id}.stl"

        if local_path.exists() and not force:
            recorded_sha = str(entry.get("sha256", "")).strip()
            if recorded_sha:
                actual_sha = _sha256_file(local_path)
                if actual_sha == recorded_sha:
                    skipped += 1
                    per_entry.append({"file_id": file_id, "status": "cached"})
                    continue
                # sha mismatch — re-download
            else:
                skipped += 1
                per_entry.append({"file_id": file_id, "status": "cached"})
                continue

        try:
            dl_kwargs: dict[str, Any] = {
                "repo_type": "dataset",
                "revision": hf_revision,
                "local_dir": str(hf_local_dir),
            }
            if hf_token:
                dl_kwargs["token"] = hf_token

            dl_path = Path(hf_hub_download(hf_repo, hf_path, **dl_kwargs))
            if dl_path.resolve() != local_path.resolve():
                shutil.copy2(dl_path, local_path)

            sha = _sha256_file(local_path)
            size = local_path.stat().st_size
            # Update manifest entry in-place so caller can persist updated manifest
            entry["sha256"] = sha
            entry["file_size_bytes"] = size
            downloaded += 1
            per_entry.append(
                {"file_id": file_id, "status": "downloaded", "sha256": sha, "size": size}
            )
        except Exception as exc:
            failed += 1
            per_entry.append({"file_id": file_id, "status": "failed", "error": str(exc)})

    return {
        "batch_id": manifest.get("batch_id"),
        "cache_dir": str(cache_dir),
        "total": len(entries),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "per_entry": per_entry,
    }


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_thingi10k_batch(
    manifest: dict[str, Any],
    cache_root: Path | str,
    *,
    config: Any = None,
    progress_fn: Optional[Callable] = None,
) -> dict[str, Any]:
    """Run the feature-graph detector on every cached STL and aggregate results.

    Returns a score dict that can be committed as a baseline artifact.
    """
    from stl2scad.core.feature_graph import build_feature_graph_for_stl, build_triage_report
    from stl2scad.tuning.config import DetectorConfig

    if config is None:
        config = DetectorConfig()

    cache_dir = resolve_thingi10k_cache(manifest, cache_root)
    entries = manifest.get("entries", [])
    iterable: Any = entries
    if progress_fn is not None:
        iterable = progress_fn(entries, desc="Scoring STLs", total=len(entries))

    per_file_results: list[dict[str, Any]] = []
    graphs: list[dict[str, Any]] = []

    for entry in iterable:
        file_id = str(entry["file_id"])
        local_path = cache_dir / f"{file_id}.stl"
        if not local_path.exists():
            per_file_results.append({"file_id": file_id, "status": "missing"})
            continue
        try:
            graph = build_feature_graph_for_stl(local_path, config=config)
            preview = graph.get("scad_preview") or ""
            has_preview = bool(preview and len(preview.strip()) > 20)
            bucket = _classify_graph_bucket(graph)
            per_file_results.append(
                {
                    "file_id": file_id,
                    "status": "ok",
                    "bucket": bucket,
                    "preview_ready": has_preview,
                    "feature_count": len(graph.get("features", [])),
                    "top_confidence": _top_confidence(graph),
                }
            )
            graphs.append(graph)
        except Exception as exc:
            per_file_results.append(
                {"file_id": file_id, "status": "error", "error": str(exc)}
            )

    ok_results = [r for r in per_file_results if r["status"] == "ok"]
    preview_ready = [r for r in ok_results if r.get("preview_ready")]
    bucket_counts: dict[str, int] = {}
    for r in ok_results:
        b = str(r.get("bucket", "unknown"))
        bucket_counts[b] = bucket_counts.get(b, 0) + 1

    triage = build_triage_report(graphs) if graphs else {}

    return {
        "schema_version": 1,
        "batch_id": manifest.get("batch_id"),
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_entries": len(entries),
        "n_present": len(ok_results) + sum(1 for r in per_file_results if r["status"] == "error"),
        "n_ok": len(ok_results),
        "preview_ready_count": len(preview_ready),
        "preview_ready_ratio": len(preview_ready) / len(ok_results) if ok_results else 0.0,
        "bucket_counts": bucket_counts,
        "triage_summary": triage,
        "per_file": per_file_results,
    }


def compare_thingi10k_score_to_baseline(
    score: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Produce a delta report between a current score and a baseline.

    A regression is flagged when preview_ready_ratio drops more than 2%.
    """
    current_ratio = float(score.get("preview_ready_ratio", 0.0))
    baseline_ratio = float(baseline.get("preview_ready_ratio", 0.0))
    delta_ratio = current_ratio - baseline_ratio

    current_buckets: dict[str, int] = score.get("bucket_counts", {})
    baseline_buckets: dict[str, int] = baseline.get("bucket_counts", {})
    all_buckets = set(current_buckets) | set(baseline_buckets)
    bucket_deltas = {
        b: current_buckets.get(b, 0) - baseline_buckets.get(b, 0)
        for b in sorted(all_buckets)
    }

    return {
        "baseline_preview_ready_ratio": baseline_ratio,
        "current_preview_ready_ratio": current_ratio,
        "delta_preview_ready_ratio": round(delta_ratio, 6),
        "regression": delta_ratio < -0.02,
        "bucket_deltas": bucket_deltas,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _classify_graph_bucket(graph: dict[str, Any]) -> str:
    """Map a feature graph to a triage bucket name."""
    if graph.get("scad_preview"):
        preview = str(graph["scad_preview"]).strip()
        if len(preview) > 20:
            return "parametric_preview"
    features = graph.get("features", [])
    types = {f.get("type") for f in features}
    for ftype in (
        "plate_like_solid",
        "box_like_solid",
        "cylinder_like_solid",
        "revolve_solid",
        "linear_extrude_solid",
    ):
        if ftype in types:
            return "feature_detected_no_preview"
    if any(f.get("type") == "axis_boundary_plane_pair" for f in features):
        return "axis_boundary_only"
    return "no_features"


def _top_confidence(graph: dict[str, Any]) -> float:
    features = graph.get("features", [])
    return max((float(f.get("confidence", 0.0)) for f in features), default=0.0)
