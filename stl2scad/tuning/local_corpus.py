"""User-local corpus manifests and scoring.

This module is intentionally separate from the checked-in real-world corpus
gate.  Local corpus manifests may reference private STL files under .local/ and
produce reproducible aggregate reports without committing those files.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable, Optional

from stl2scad.core.feature_graph import build_feature_graph_for_stl, build_triage_report
from stl2scad.core.feature_graph import emit_feature_graph_scad_preview
from stl2scad.core.feature_inventory import (
    STL_SUFFIXES,
    InventoryConfig,
    analyze_stl_file,
)
from stl2scad.core.verification import verify_existing_conversion
from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.scoring import FixtureScore, score_fixture_against_graph


LOCAL_CORPUS_SCHEMA_VERSION = 1
LOCAL_CORPUS_SCORE_SCHEMA_VERSION = 1
LOCAL_CORPUS_PREVIEW_TOLERANCE = {
    "volume": 5.0,
    "surface_area": 10.0,
    "bounding_box": 2.0,
    "hausdorff_distance": 3.0,
    "normal_deviation": 15.0,
}


def create_local_corpus_manifest(
    input_dir: Path | str,
    output_path: Path | str | None = None,
    *,
    recursive: bool = True,
    max_files: Optional[int] = None,
    detector_config: DetectorConfig = DetectorConfig(),
    progress_fn: Any = None,
) -> dict[str, Any]:
    """Create a reproducible manifest for a private local STL folder."""
    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"Input directory not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root}")

    files = _iter_stl_files(root, recursive=recursive)
    if max_files is not None:
        files = files[:max_files]

    file_iterable = files
    if progress_fn is not None:
        file_iterable = progress_fn(
            files,
            desc="Scanning STL files",
            total=len(files),
        )

    cases = []
    for path in file_iterable:
        cases.append(_build_manifest_case(path, root, detector_config=detector_config))
    corpus_root = str(root)
    if output_path is not None:
        corpus_root = _relative_or_absolute_root(
            root.resolve(),
            Path(output_path).parent.resolve(),
        )

    manifest = {
        "schema_version": LOCAL_CORPUS_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_root": corpus_root,
        "source_dir": str(root),
        "detector_config_version": 1,
        "detector_config": asdict(detector_config),
        "cases": cases,
    }

    if output_path is not None:
        _write_json(output_path, manifest)
    return manifest


def load_local_corpus_manifest(manifest_path: Path | str) -> dict[str, Any]:
    """Load and validate a local corpus manifest."""
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema_version = int(payload.get("schema_version", 0))
    if schema_version != LOCAL_CORPUS_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported local corpus manifest schema_version "
            f"'{schema_version}'. Expected {LOCAL_CORPUS_SCHEMA_VERSION}."
        )

    corpus_root = str(payload.get("corpus_root", "")).strip()
    if not corpus_root:
        raise ValueError("Local corpus manifest must define corpus_root")

    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Local corpus manifest must contain a cases list")

    normalized_cases: list[dict[str, Any]] = []
    paths_seen: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = _validate_manifest_case(raw_case, index=index)
        if case["relative_path"] in paths_seen:
            raise ValueError(
                f"Duplicate local corpus relative_path: {case['relative_path']}"
            )
        paths_seen.add(case["relative_path"])
        normalized_cases.append(case)

    return {
        "schema_version": schema_version,
        "generated_at_utc": payload.get("generated_at_utc"),
        "corpus_root": corpus_root,
        "source_dir": payload.get("source_dir"),
        "detector_config_version": int(payload.get("detector_config_version", 1)),
        "detector_config": dict(payload.get("detector_config") or {}),
        "cases": normalized_cases,
    }


def resolve_local_corpus_root(
    manifest_path: Path | str,
    manifest: dict[str, Any],
    corpus_root_override: Path | str | None = None,
) -> Path:
    """Resolve the root directory containing manifest-relative STL paths."""
    if corpus_root_override is not None:
        return Path(corpus_root_override)
    path = Path(manifest_path)
    return (path.parent / str(manifest["corpus_root"])).resolve()


def list_missing_local_corpus_files(
    cases: Iterable[dict[str, Any]],
    corpus_root: Path | str,
) -> list[str]:
    """Return missing manifest-relative STL paths."""
    root = Path(corpus_root)
    missing: list[str] = []
    for case in cases:
        rel_path = str(case["relative_path"])
        if not (root / rel_path).exists():
            missing.append(rel_path)
    return missing


def score_local_corpus(
    manifest_path: Path | str,
    *,
    corpus_root: Path | str | None = None,
    detector_config: DetectorConfig = DetectorConfig(),
    triage_top_n: int = 5,
    progress_fn: Any = None,
) -> dict[str, Any]:
    """Score a local corpus with triage buckets and optional labels."""
    manifest = load_local_corpus_manifest(manifest_path)
    root = resolve_local_corpus_root(manifest_path, manifest, corpus_root)

    graphs: list[dict[str, Any]] = []
    per_file: list[dict[str, Any]] = []
    labeled_scores: list[FixtureScore] = []
    fingerprint_mismatch_count = 0
    files_missing = 0

    cases = manifest["cases"]
    case_iterable = cases
    if progress_fn is not None:
        case_iterable = progress_fn(
            cases,
            desc="Scoring STL files",
            total=len(cases),
        )

    for case in case_iterable:
        rel_path = str(case["relative_path"])
        stl_path = root / rel_path
        if not stl_path.exists():
            files_missing += 1
            per_file.append(
                {
                    "relative_path": rel_path,
                    "sha256": str(case.get("sha256", "")),
                    "status": "missing",
                    "fingerprint_verified": False,
                }
            )
            continue

        fingerprint_verified = _fingerprint_matches_case(case, stl_path)
        if not fingerprint_verified:
            fingerprint_mismatch_count += 1

        try:
            graph = build_feature_graph_for_stl(
                stl_path,
                root_dir=root,
                config=detector_config,
            )
        except Exception as exc:
            graph = {
                "schema_version": 1,
                "source_file": rel_path,
                "status": "error",
                "error": str(exc),
                "features": [],
            }
        graphs.append(graph)

        entry: dict[str, Any] = {
            "relative_path": rel_path,
            "sha256": str(case.get("sha256", "")),
            "status": graph.get("status", "ok"),
            "fingerprint_verified": fingerprint_verified,
        }
        if graph.get("status") == "error":
            entry["error"] = str(graph.get("error", ""))
        labeled_fixture = _fixture_from_case_labels(case)
        if labeled_fixture is not None and graph.get("status") != "error":
            fixture_score = score_fixture_against_graph(labeled_fixture, graph)
            labeled_scores.append(fixture_score)
            entry["label_score"] = _serialize_fixture_score(fixture_score)
        per_file.append(entry)

    preview_validation_cache: dict[str, dict[str, Any]] = {}

    def _preview_validator(graph: dict[str, Any]) -> bool:
        source_file = str(graph.get("source_file", ""))
        if source_file in preview_validation_cache:
            return bool(preview_validation_cache[source_file].get("passed", False))

        result = _validate_preview_geometry(graph, root)
        preview_validation_cache[source_file] = result
        return bool(result.get("passed", False))

    triage = build_triage_report(
        graphs,
        top_n=triage_top_n,
        input_dir=str(root),
        preview_validator=_preview_validator,
    )

    triage_by_source = {
        str(entry.get("source_file", "")): entry for entry in triage.get("per_file", [])
    }
    for entry in per_file:
        triage_entry = triage_by_source.get(str(entry.get("relative_path", "")))
        if triage_entry is not None:
            entry["triage_bucket"] = triage_entry.get("bucket")
        preview_validation = preview_validation_cache.get(str(entry.get("relative_path", "")))
        if preview_validation is not None:
            entry["preview_validation"] = preview_validation

    labeled_summary = _summarize_labeled_scores(labeled_scores)
    preview_ready_ratio = (
        triage["bucket_counts"]["parametric_preview"] / triage["files_processed"]
        if triage["files_processed"]
        else 0.0
    )

    return {
        "schema_version": LOCAL_CORPUS_SCORE_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(Path(manifest_path)),
        "corpus_root": str(root),
        "files_total": len(manifest["cases"]),
        "files_present": len(graphs),
        "files_missing": files_missing,
        "fingerprint_mismatch_count": fingerprint_mismatch_count,
        "preview_ready_ratio": float(preview_ready_ratio),
        "triage": triage,
        "labeled_summary": labeled_summary,
        "per_file": per_file,
    }


def _validate_preview_geometry(graph: dict[str, Any], corpus_root: Path) -> dict[str, Any]:
    """Render emitted SCAD preview and verify it against the source STL."""
    scad_preview = emit_feature_graph_scad_preview(graph)
    if scad_preview is None:
        return {"attempted": False, "passed": False, "reason": "no_scad_preview"}

    source_file = str(graph.get("source_file", "")).strip()
    if not source_file:
        return {"attempted": False, "passed": False, "reason": "missing_source_file"}

    stl_path = corpus_root / source_file
    if not stl_path.exists():
        return {"attempted": False, "passed": False, "reason": "missing_source_stl"}

    try:
        with tempfile.TemporaryDirectory(prefix="preview-verify-") as temp_dir:
            temp_scad = Path(temp_dir) / f"{Path(source_file).stem}_preview.scad"
            temp_scad.write_text(scad_preview, encoding="utf-8")
            result = verify_existing_conversion(
                stl_path,
                temp_scad,
                dict(LOCAL_CORPUS_PREVIEW_TOLERANCE),
                debug=False,
                sample_seed=0,
            )
    except Exception as exc:
        return {
            "attempted": True,
            "passed": False,
            "reason": f"verification_error:{type(exc).__name__}",
            "error": str(exc),
        }

    return {
        "attempted": True,
        "passed": bool(result.passed),
        "reason": "verified" if result.passed else "metrics_out_of_tolerance",
        "comparison": result.comparison,
        "tolerance": dict(result.tolerance),
    }


def compare_local_corpus_score_to_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Compute aggregate deltas between current and baseline local scores."""
    current_counts = current.get("triage", {}).get("bucket_counts") or {}
    baseline_counts = baseline.get("triage", {}).get("bucket_counts") or {}
    buckets = sorted(set(current_counts) | set(baseline_counts))

    current_labeled = current.get("labeled_summary") or {}
    baseline_labeled = baseline.get("labeled_summary") or {}

    return {
        "schema_version": 1,
        "baseline_label": baseline.get("label", "baseline"),
        "files_present_delta": int(current.get("files_present", 0))
        - int(baseline.get("files_present", 0)),
        "fingerprint_mismatch_delta": int(current.get("fingerprint_mismatch_count", 0))
        - int(baseline.get("fingerprint_mismatch_count", 0)),
        "preview_ready_ratio_delta": float(current.get("preview_ready_ratio", 0.0))
        - float(baseline.get("preview_ready_ratio", 0.0)),
        "triage_bucket_delta": {
            bucket: int(current_counts.get(bucket, 0))
            - int(baseline_counts.get(bucket, 0))
            for bucket in buckets
        },
        "labeled_mean_score_delta": float(current_labeled.get("mean_score", 0.0))
        - float(baseline_labeled.get("mean_score", 0.0)),
    }


def _iter_stl_files(root: Path, *, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in STL_SUFFIXES
    )


def _build_manifest_case(
    path: Path,
    root: Path,
    *,
    detector_config: DetectorConfig,
) -> dict[str, Any]:
    rel_path = path.relative_to(root).as_posix()
    inventory = analyze_stl_file(
        path,
        root_dir=root,
        config=InventoryConfig(
            normal_axis_threshold=detector_config.normal_axis_threshold
        ),
    )
    fingerprint = _compute_file_fingerprint(path)
    return {
        "relative_path": rel_path,
        "sha256": fingerprint["sha256"],
        "size_bytes": fingerprint["size_bytes"],
        "bounds": inventory.get("bounding_box", {}),
        "inventory_classification": inventory.get("classification", {}),
        "labels": {},
        "notes": "",
    }


def _compute_file_fingerprint(path: Path) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": int(path.stat().st_size),
    }


def _fingerprint_matches_case(case: dict[str, Any], path: Path) -> bool:
    actual = _compute_file_fingerprint(path)
    expected_sha = str(case.get("sha256", "")).strip()
    expected_size = int(case.get("size_bytes", -1))
    if expected_sha and actual["sha256"] != expected_sha:
        return False
    if expected_size >= 0 and actual["size_bytes"] != expected_size:
        return False
    return True


def _fixture_from_case_labels(case: dict[str, Any]) -> dict[str, Any] | None:
    labels = case.get("labels") or {}
    if not isinstance(labels, dict):
        return None
    if "fixture_type" not in labels or "expected_detection" not in labels:
        return None

    fixture = dict(labels)
    fixture["name"] = str(labels.get("name") or case["relative_path"])
    fixture.setdefault("holes", [])
    fixture.setdefault("slots", [])
    fixture.setdefault("counterbores", [])
    fixture.setdefault("rectangular_cutouts", [])
    fixture.setdefault("rectangular_pockets", [])
    fixture.setdefault("linear_hole_patterns", [])
    fixture.setdefault("grid_hole_patterns", [])
    return fixture


def _summarize_labeled_scores(scores: list[FixtureScore]) -> dict[str, Any]:
    if not scores:
        return {
            "labeled_case_count": 0,
            "mean_score": 0.0,
            "mean_count_score": 0.0,
            "mean_dimension_score": 0.0,
            "feature_family_recall": {},
        }

    family_hits: dict[str, int] = {}
    family_totals: dict[str, int] = {}
    for score in scores:
        expected = score.detail.get("expected", {})
        actual = score.detail.get("actual", {})
        for family, expected_count in expected.items():
            if int(expected_count) <= 0:
                continue
            family_totals[family] = family_totals.get(family, 0) + int(expected_count)
            family_hits[family] = family_hits.get(family, 0) + min(
                int(expected_count),
                int(actual.get(family, 0)),
            )

    return {
        "labeled_case_count": len(scores),
        "mean_score": sum(score.total for score in scores) / len(scores),
        "mean_count_score": sum(score.count_score for score in scores) / len(scores),
        "mean_dimension_score": sum(score.dimension_score for score in scores)
        / len(scores),
        "feature_family_recall": {
            family: family_hits[family] / total
            for family, total in sorted(family_totals.items())
            if total > 0
        },
    }


def _serialize_fixture_score(score: FixtureScore) -> dict[str, Any]:
    return {
        "name": score.name,
        "count_score": score.count_score,
        "dimension_score": score.dimension_score,
        "total": score.total,
        "detail": score.detail,
    }


def _validate_manifest_case(raw_case: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw_case, dict):
        raise ValueError(f"Local corpus cases[{index}] must be an object")
    relative_path = str(raw_case.get("relative_path", "")).strip()
    if not relative_path:
        raise ValueError(f"Local corpus cases[{index}].relative_path is required")
    normalized = dict(raw_case)
    normalized["relative_path"] = relative_path
    normalized["sha256"] = str(raw_case.get("sha256", "")).strip()
    normalized["size_bytes"] = int(raw_case.get("size_bytes", -1))
    normalized.setdefault("bounds", {})
    normalized.setdefault("inventory_classification", {})
    normalized.setdefault("labels", {})
    normalized.setdefault("notes", "")
    return normalized


def _write_json(path: Path | str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _relative_or_absolute_root(root: Path, base: Path) -> str:
    try:
        return root.relative_to(base).as_posix()
    except ValueError:
        return str(root)
