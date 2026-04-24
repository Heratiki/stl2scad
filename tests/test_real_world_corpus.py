"""Tests for real-world corpus manifest loading and scoring helpers."""

import json

import pytest

from stl2scad.tuning.real_world_corpus import (
    compare_real_world_score_to_baseline,
    list_missing_real_world_corpus_files,
    load_real_world_corpus_manifest,
    resolve_real_world_corpus_root,
    serialize_real_world_corpus_score,
)
from stl2scad.tuning.scoring import FixtureScore
from stl2scad.tuning.real_world_corpus import RealWorldCaseScore, RealWorldCorpusScore


def test_load_real_world_corpus_manifest_validates_schema(test_data_dir):
    manifest = load_real_world_corpus_manifest(
        test_data_dir / "real_world_corpus_manifest.json"
    )

    assert manifest["schema_version"] == 1
    assert manifest["corpus_root"] == "real_world_stls"
    assert len(manifest["cases"]) == 2
    assert manifest["cases"][0]["source"] == "local_self_authored"


def test_load_real_world_corpus_manifest_rejects_missing_provenance(tmp_path):
    manifest_path = tmp_path / "invalid_real_world_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_root": "real_world_stls",
                "cases": [
                    {
                        "name": "bad_case",
                        "relative_path": "bad_case.stl",
                        "fixture_type": "plate",
                        "plate_size": [10.0, 10.0, 2.0],
                        "expected_detection": {"plate_like_solid": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    try:
        load_real_world_corpus_manifest(manifest_path)
    except ValueError as exc:
        assert "source and license provenance" in str(exc)
    else:
        raise AssertionError("Expected invalid real-world manifest to raise ValueError")


def test_resolve_real_world_corpus_root_uses_manifest_relative_path(test_data_dir):
    manifest_path = test_data_dir / "real_world_corpus_manifest.json"
    manifest = load_real_world_corpus_manifest(manifest_path)

    resolved = resolve_real_world_corpus_root(manifest_path, manifest)

    assert resolved == (test_data_dir / "real_world_stls").resolve()


def test_list_missing_real_world_corpus_files_reports_absent_cases(test_data_dir, tmp_path):
    manifest = load_real_world_corpus_manifest(
        test_data_dir / "real_world_corpus_manifest.json"
    )

    missing = list_missing_real_world_corpus_files(manifest["cases"], tmp_path)

    assert missing == ["drill_guide_plate.stl", "x_carriage_spacer_block.stl"]


def test_compare_real_world_score_to_baseline_computes_deltas():
    score = RealWorldCorpusScore(
        manifest_path="tests/data/real_world_corpus_manifest.json",
        corpus_root="tests/data/real_world_stls",
        files_present=2,
        files_missing=0,
        mean_score=0.85,
        preview_ready_ratio=0.5,
        feature_family_recall={"box_like_solid": 1.0, "hole_like_cutout": 0.75},
        per_case=[
            RealWorldCaseScore(
                name="case_a",
                relative_path="a.stl",
                fixture_score=FixtureScore(
                    name="case_a",
                    count_score=1.0,
                    dimension_score=0.9,
                    total=0.96,
                    detail={},
                ),
                preview_emitted=True,
                fingerprint_verified=True,
            )
        ],
    )
    baseline = {
        "label": "seed",
        "files_present": 1,
        "mean_score": 0.80,
        "preview_ready_ratio": 0.25,
        "feature_family_recall": {"hole_like_cutout": 0.5},
    }

    delta = compare_real_world_score_to_baseline(score, baseline)

    assert delta["files_present_delta"] == 1
    assert delta["mean_score_delta"] == pytest.approx(0.05)
    assert delta["preview_ready_ratio_delta"] == pytest.approx(0.25)
    assert delta["feature_family_recall_delta"]["hole_like_cutout"] == pytest.approx(0.25)
    assert delta["feature_family_recall_delta"]["box_like_solid"] == pytest.approx(1.0)


def test_serialize_real_world_corpus_score_preserves_case_summary():
    score = RealWorldCorpusScore(
        manifest_path="manifest.json",
        corpus_root="corpus",
        files_present=1,
        files_missing=0,
        mean_score=0.9,
        preview_ready_ratio=1.0,
        feature_family_recall={"plate_like_solid": 1.0},
        per_case=[
            RealWorldCaseScore(
                name="plate_case",
                relative_path="plate.stl",
                fixture_score=FixtureScore(
                    name="plate_case",
                    count_score=1.0,
                    dimension_score=0.8,
                    total=0.92,
                    detail={},
                ),
                preview_emitted=True,
                fingerprint_verified=False,
            )
        ],
    )

    payload = serialize_real_world_corpus_score(score)

    assert payload["files_present"] == 1
    assert payload["feature_family_recall"]["plate_like_solid"] == 1.0
    assert payload["per_case"][0]["name"] == "plate_case"
    assert payload["per_case"][0]["fingerprint_verified"] is False
