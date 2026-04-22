"""Real-world corpus manifest loading and recall scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Optional

from stl.mesh import Mesh

from stl2scad.core.feature_inventory import _bbox
from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.scoring import FixtureScore, score_fixture


@dataclass(frozen=True)
class RealWorldCaseScore:
    name: str
    relative_path: str
    fixture_score: FixtureScore
    preview_emitted: bool
    fingerprint_verified: bool
    present: bool = True


@dataclass(frozen=True)
class RealWorldCorpusScore:
    manifest_path: str
    corpus_root: str
    files_present: int
    files_missing: int
    mean_score: float
    preview_ready_ratio: float
    feature_family_recall: dict[str, float] = field(default_factory=dict)
    per_case: list[RealWorldCaseScore] = field(default_factory=list)


def load_real_world_corpus_manifest(
    manifest_path: Path | str,
) -> dict[str, Any]:
    """Load and validate the real-world corpus manifest."""
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema_version = int(payload.get("schema_version", 0))
    if schema_version != 1:
        raise ValueError(
            f"Unsupported real-world corpus manifest schema_version '{schema_version}'. Expected 1."
        )

    corpus_root = str(payload.get("corpus_root", "")).strip()
    if not corpus_root:
        raise ValueError("Real-world corpus manifest must define corpus_root")

    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Real-world corpus manifest must contain a non-empty cases list")

    names_seen: set[str] = set()
    normalized_cases: list[dict[str, Any]] = []
    for index, raw_case in enumerate(cases):
        case = _validate_real_world_case(raw_case, index=index)
        if case["name"] in names_seen:
            raise ValueError(f"Duplicate real-world corpus case name: {case['name']}")
        names_seen.add(case["name"])
        normalized_cases.append(case)

    return {
        "schema_version": schema_version,
        "corpus_root": corpus_root,
        "cases": normalized_cases,
    }


def resolve_real_world_corpus_root(
    manifest_path: Path | str,
    manifest: dict[str, Any],
    corpus_root_override: Path | str | None = None,
) -> Path:
    """Resolve the corpus root either from override or the manifest."""
    if corpus_root_override is not None:
        return Path(corpus_root_override)
    path = Path(manifest_path)
    return (path.parent / str(manifest["corpus_root"])).resolve()


def list_missing_real_world_corpus_files(
    cases: Iterable[dict[str, Any]],
    corpus_root: Path | str,
) -> list[str]:
    """Return the list of missing relative paths from the corpus root."""
    root = Path(corpus_root)
    missing: list[str] = []
    for case in cases:
        rel_path = str(case["relative_path"])
        if not (root / rel_path).exists():
            missing.append(rel_path)
    return missing


def compute_stl_fingerprint(stl_path: Path | str) -> dict[str, Any]:
    """Compute sha256 and bounding box for an STL file."""
    path = Path(stl_path)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    mesh = Mesh.from_file(str(path))
    bbox = _bbox(mesh.vectors.reshape(-1, 3))
    return {"sha256": sha256, "bounds": bbox}


def fingerprint_matches_case(case: dict[str, Any], stl_path: Path | str) -> bool:
    """Check a case fingerprint against a local STL file when metadata is present."""
    expected_fingerprint = case.get("fingerprint") or {}
    expected_sha = str(expected_fingerprint.get("sha256", "")).strip()
    expected_bounds = expected_fingerprint.get("bounds")
    if not expected_sha and not expected_bounds:
        return True

    actual = compute_stl_fingerprint(stl_path)
    if expected_sha and actual["sha256"] != expected_sha:
        return False
    if expected_bounds:
        for key, expected_value in expected_bounds.items():
            if abs(float(actual["bounds"].get(key, 0.0)) - float(expected_value)) > 1e-6:
                return False
    return True


def score_real_world_corpus(
    config: DetectorConfig,
    manifest_path: Path | str,
    corpus_root: Path | str | None = None,
) -> RealWorldCorpusScore:
    """Score a real-world STL corpus against authored expectations."""
    manifest = load_real_world_corpus_manifest(manifest_path)
    root = resolve_real_world_corpus_root(manifest_path, manifest, corpus_root)
    case_scores: list[RealWorldCaseScore] = []
    family_hits: dict[str, int] = {}
    family_totals: dict[str, int] = {}
    missing_count = 0

    for case in manifest["cases"]:
        stl_path = root / str(case["relative_path"])
        if not stl_path.exists():
            missing_count += 1
            continue

        fixture_score = score_fixture(config, case, stl_path)
        detail_expected = fixture_score.detail.get("expected", {})
        detail_actual = fixture_score.detail.get("actual", {})
        preview_emitted = bool(_is_preview_ready(case, detail_expected, detail_actual))
        fingerprint_verified = fingerprint_matches_case(case, stl_path)
        case_scores.append(
            RealWorldCaseScore(
                name=str(case["name"]),
                relative_path=str(case["relative_path"]),
                fixture_score=fixture_score,
                preview_emitted=preview_emitted,
                fingerprint_verified=fingerprint_verified,
            )
        )

        for family, expected_count in detail_expected.items():
            if int(expected_count) <= 0:
                continue
            family_totals[family] = family_totals.get(family, 0) + int(expected_count)
            family_hits[family] = family_hits.get(family, 0) + min(
                int(expected_count),
                int(detail_actual.get(family, 0)),
            )

    files_present = len(case_scores)
    preview_count = sum(1 for score in case_scores if score.preview_emitted)
    mean_score = (
        sum(score.fixture_score.total for score in case_scores) / files_present
        if files_present
        else 0.0
    )
    preview_ready_ratio = preview_count / files_present if files_present else 0.0
    feature_family_recall = {
        family: family_hits[family] / total
        for family, total in sorted(family_totals.items())
        if total > 0
    }
    return RealWorldCorpusScore(
        manifest_path=str(Path(manifest_path)),
        corpus_root=str(root),
        files_present=files_present,
        files_missing=missing_count,
        mean_score=float(mean_score),
        preview_ready_ratio=float(preview_ready_ratio),
        feature_family_recall=feature_family_recall,
        per_case=case_scores,
    )


def serialize_real_world_corpus_score(score: RealWorldCorpusScore) -> dict[str, Any]:
    """Convert a corpus score to JSON-serializable form."""
    return {
        "schema_version": 1,
        "manifest_path": score.manifest_path,
        "corpus_root": score.corpus_root,
        "files_present": score.files_present,
        "files_missing": score.files_missing,
        "mean_score": score.mean_score,
        "preview_ready_ratio": score.preview_ready_ratio,
        "feature_family_recall": score.feature_family_recall,
        "per_case": [
            {
                "name": case.name,
                "relative_path": case.relative_path,
                "count_score": case.fixture_score.count_score,
                "dimension_score": case.fixture_score.dimension_score,
                "total": case.fixture_score.total,
                "preview_emitted": case.preview_emitted,
                "fingerprint_verified": case.fingerprint_verified,
            }
            for case in score.per_case
        ],
    }


def compare_real_world_score_to_baseline(
    current: RealWorldCorpusScore,
    baseline_payload: dict[str, Any],
) -> dict[str, Any]:
    """Compute delta between a current corpus score and a committed baseline."""
    baseline_by_family = baseline_payload.get("feature_family_recall") or {}
    current_by_family = current.feature_family_recall
    families = sorted(set(baseline_by_family) | set(current_by_family))
    return {
        "schema_version": 1,
        "baseline_label": baseline_payload.get("label", "baseline"),
        "files_present_delta": int(current.files_present) - int(baseline_payload.get("files_present", 0)),
        "mean_score_delta": float(current.mean_score) - float(baseline_payload.get("mean_score", 0.0)),
        "preview_ready_ratio_delta": float(current.preview_ready_ratio)
        - float(baseline_payload.get("preview_ready_ratio", 0.0)),
        "feature_family_recall_delta": {
            family: float(current_by_family.get(family, 0.0))
            - float(baseline_by_family.get(family, 0.0))
            for family in families
        },
    }


def _validate_real_world_case(raw_case: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw_case, dict):
        raise ValueError(f"Real-world corpus cases[{index}] must be an object")
    name = str(raw_case.get("name", "")).strip()
    if not name:
        raise ValueError(f"Real-world corpus cases[{index}].name is required")
    relative_path = str(raw_case.get("relative_path", "")).strip()
    if not relative_path:
        raise ValueError(f"Real-world corpus cases[{index}].relative_path is required")
    fixture_type = str(raw_case.get("fixture_type", "")).strip()
    if fixture_type not in {"plate", "box", "l_bracket", "sphere", "torus"}:
        raise ValueError(
            f"Real-world corpus case '{name}' fixture_type must reuse a supported fixture type"
        )
    source = str(raw_case.get("source", "")).strip()
    license_name = str(raw_case.get("license", "")).strip()
    if not source or not license_name:
        raise ValueError(
            f"Real-world corpus case '{name}' must define source and license provenance"
        )
    expected_detection = raw_case.get("expected_detection")
    if not isinstance(expected_detection, dict):
        raise ValueError(
            f"Real-world corpus case '{name}' must define expected_detection"
        )

    normalized = dict(raw_case)
    normalized["name"] = name
    normalized["relative_path"] = relative_path
    normalized["fixture_type"] = fixture_type
    normalized["source"] = source
    normalized["license"] = license_name
    normalized.setdefault("description", "")
    normalized.setdefault("holes", [])
    normalized.setdefault("slots", [])
    normalized.setdefault("counterbores", [])
    normalized.setdefault("rectangular_cutouts", [])
    normalized.setdefault("rectangular_pockets", [])
    normalized.setdefault("linear_hole_patterns", [])
    normalized.setdefault("grid_hole_patterns", [])
    normalized.setdefault("fingerprint", {})
    return normalized


def _is_preview_ready(
    case: dict[str, Any],
    expected_counts: dict[str, Any],
    actual_counts: dict[str, Any],
) -> bool:
    base_key = "plate_like_solid" if case["fixture_type"] == "plate" else "box_like_solid"
    if int(expected_counts.get(base_key, 0)) <= 0:
        return False
    return int(actual_counts.get(base_key, 0)) >= int(expected_counts.get(base_key, 0))
