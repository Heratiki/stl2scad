"""Local-only smoke test for the labeled real-world corpus."""

import json

import pytest

from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.real_world_corpus import (
    list_missing_real_world_corpus_files,
    load_real_world_corpus_manifest,
    resolve_real_world_corpus_root,
    score_real_world_corpus,
    serialize_real_world_corpus_score,
)


def test_real_world_corpus_smoke_emits_recall_artifact(test_data_dir, test_output_dir):
    manifest_path = test_data_dir / "real_world_corpus_manifest.json"
    manifest = load_real_world_corpus_manifest(manifest_path)
    corpus_root = resolve_real_world_corpus_root(manifest_path, manifest)
    missing = list_missing_real_world_corpus_files(manifest["cases"], corpus_root)
    if missing:
        pytest.skip(
            "Real-world corpus files are not present locally. "
            f"Expected under {corpus_root}. Missing: {', '.join(missing)}"
        )

    score = score_real_world_corpus(
        DetectorConfig(),
        manifest_path=manifest_path,
        corpus_root=corpus_root,
    )
    payload = serialize_real_world_corpus_score(score)
    artifact_path = test_output_dir / "real_world_recall.json"
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert score.files_present == len(manifest["cases"])
    assert score.files_missing == 0
    assert 0.0 <= score.mean_score <= 1.0
    assert 0.0 <= score.preview_ready_ratio <= 1.0
    assert artifact_path.exists()
