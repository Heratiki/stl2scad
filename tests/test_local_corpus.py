"""Tests for the user-local corpus scoring loop."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.tuning.local_corpus import (
    compare_local_corpus_score_to_baseline,
    create_local_corpus_manifest,
    list_missing_local_corpus_files,
    load_local_corpus_manifest,
    resolve_local_corpus_root,
    score_local_corpus,
)


def _copy_fixture_corpus(test_data_dir: Path, tmp_path: Path) -> Path:
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    shutil.copy2(fixtures_dir / "primitive_box_axis_aligned.stl", corpus_dir)
    shutil.copy2(fixtures_dir / "primitive_sphere.stl", corpus_dir)
    return corpus_dir


def test_create_local_corpus_manifest_records_private_file_metadata(
    test_data_dir,
    tmp_path,
):
    corpus_dir = _copy_fixture_corpus(test_data_dir, tmp_path)
    manifest_path = tmp_path / ".local" / "local_corpus.json"

    manifest = create_local_corpus_manifest(
        corpus_dir,
        output_path=manifest_path,
        recursive=False,
    )
    loaded = load_local_corpus_manifest(manifest_path)

    assert manifest_path.exists()
    assert loaded["schema_version"] == 1
    assert loaded["detector_config_version"] == 1
    assert len(manifest["cases"]) == 2
    case = manifest["cases"][0]
    assert case["relative_path"].endswith(".stl")
    assert len(case["sha256"]) == 64
    assert case["size_bytes"] > 0
    assert "width" in case["bounds"]
    assert case["labels"] == {}


def test_score_local_corpus_emits_triage_for_unlabeled_cases(test_data_dir, tmp_path):
    corpus_dir = _copy_fixture_corpus(test_data_dir, tmp_path)
    manifest_path = tmp_path / ".local" / "local_corpus.json"
    create_local_corpus_manifest(corpus_dir, output_path=manifest_path, recursive=False)

    score = score_local_corpus(manifest_path)

    assert score["files_total"] == 2
    assert score["files_present"] == 2
    assert score["files_missing"] == 0
    assert score["fingerprint_mismatch_count"] == 0
    assert score["triage"]["files_processed"] == 2
    assert sum(score["triage"]["bucket_counts"].values()) == 2
    assert score["labeled_summary"]["labeled_case_count"] == 0


def test_score_local_corpus_scores_optional_labels(test_data_dir, tmp_path):
    corpus_dir = _copy_fixture_corpus(test_data_dir, tmp_path)
    manifest_path = tmp_path / ".local" / "local_corpus.json"
    manifest = create_local_corpus_manifest(
        corpus_dir,
        output_path=manifest_path,
        recursive=False,
    )
    for case in manifest["cases"]:
        if case["relative_path"] == "primitive_box_axis_aligned.stl":
            case["labels"] = {
                "fixture_type": "box",
                "box_size": [20.0, 12.0, 8.0],
                "expected_detection": {"box_like_solid": True},
            }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    score = score_local_corpus(manifest_path)

    assert score["labeled_summary"]["labeled_case_count"] == 1
    assert score["labeled_summary"]["mean_score"] > 0.9
    assert score["per_file"][0].get("label_score") or score["per_file"][1].get(
        "label_score"
    )


def test_local_corpus_root_resolution_and_missing_files(tmp_path):
    manifest_path = tmp_path / ".local" / "local_corpus.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_root": "../corpus",
                "cases": [{"relative_path": "missing.stl"}],
            }
        ),
        encoding="utf-8",
    )
    manifest = load_local_corpus_manifest(manifest_path)

    root = resolve_local_corpus_root(manifest_path, manifest)
    missing = list_missing_local_corpus_files(manifest["cases"], root)

    assert root == (manifest_path.parent / "../corpus").resolve()
    assert missing == ["missing.stl"]


def test_compare_local_corpus_score_to_baseline_computes_deltas():
    current = {
        "files_present": 2,
        "fingerprint_mismatch_count": 1,
        "preview_ready_ratio": 0.5,
        "triage": {
            "bucket_counts": {
                "parametric_preview": 1,
                "feature_graph_no_preview": 1,
            }
        },
        "labeled_summary": {"mean_score": 0.75},
    }
    baseline = {
        "label": "seed",
        "files_present": 1,
        "fingerprint_mismatch_count": 0,
        "preview_ready_ratio": 0.0,
        "triage": {"bucket_counts": {"feature_graph_no_preview": 1}},
        "labeled_summary": {"mean_score": 0.50},
    }

    delta = compare_local_corpus_score_to_baseline(current, baseline)

    assert delta["files_present_delta"] == 1
    assert delta["fingerprint_mismatch_delta"] == 1
    assert delta["preview_ready_ratio_delta"] == pytest.approx(0.5)
    assert delta["triage_bucket_delta"]["parametric_preview"] == 1
    assert delta["triage_bucket_delta"]["feature_graph_no_preview"] == 0
    assert delta["labeled_mean_score_delta"] == pytest.approx(0.25)
