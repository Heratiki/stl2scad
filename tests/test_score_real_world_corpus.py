"""Tests for scripts/score_real_world_corpus.py merge-gate behavior."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from stl2scad.tuning.real_world_corpus import RealWorldCorpusScore


def _build_stub_score(tmp_path: Path) -> RealWorldCorpusScore:
    return RealWorldCorpusScore(
        manifest_path="tests/data/real_world_corpus_manifest.json",
        corpus_root=str(tmp_path / "real_world_stls"),
        files_present=1,
        files_missing=0,
        mean_score=0.9,
        preview_ready_ratio=1.0,
        feature_family_recall={"plate_like_solid": 1.0},
        per_case=[],
    )


def test_merge_gate_fails_when_corpus_files_missing(monkeypatch, capsys, tmp_path):
    module = importlib.import_module("scripts.score_real_world_corpus")

    monkeypatch.setattr(
        module,
        "load_real_world_corpus_manifest",
        lambda _manifest_path: {"cases": [{"relative_path": "missing.stl"}]},
    )
    monkeypatch.setattr(
        module,
        "resolve_real_world_corpus_root",
        lambda _manifest_path, _manifest, _override: tmp_path / "real_world_stls",
    )
    monkeypatch.setattr(
        module,
        "list_missing_real_world_corpus_files",
        lambda _cases, _root: ["missing.stl"],
    )

    exit_code = module.main(["--merge-gate"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "merge gate failed" in captured.err.lower()


def test_merge_gate_fails_when_baseline_missing(monkeypatch, capsys, tmp_path):
    module = importlib.import_module("scripts.score_real_world_corpus")

    monkeypatch.setattr(
        module,
        "load_real_world_corpus_manifest",
        lambda _manifest_path: {"cases": [{"relative_path": "present.stl"}]},
    )
    monkeypatch.setattr(
        module,
        "resolve_real_world_corpus_root",
        lambda _manifest_path, _manifest, _override: tmp_path / "real_world_stls",
    )
    monkeypatch.setattr(
        module,
        "list_missing_real_world_corpus_files",
        lambda _cases, _root: [],
    )
    monkeypatch.setattr(
        module,
        "score_real_world_corpus",
        lambda _config, manifest_path, corpus_root: _build_stub_score(tmp_path),
    )

    output_path = tmp_path / "real_world_recall.json"
    baseline_path = tmp_path / "baseline_missing.json"
    exit_code = module.main(
        [
            "--merge-gate",
            "--output",
            str(output_path),
            "--baseline",
            str(baseline_path),
        ]
    )

    assert exit_code == 2
    assert output_path.exists()
    captured = capsys.readouterr()
    assert "baseline artifact missing" in captured.err.lower()


def test_merge_gate_writes_delta_when_baseline_present(monkeypatch, tmp_path):
    module = importlib.import_module("scripts.score_real_world_corpus")

    monkeypatch.setattr(
        module,
        "load_real_world_corpus_manifest",
        lambda _manifest_path: {"cases": [{"relative_path": "present.stl"}]},
    )
    monkeypatch.setattr(
        module,
        "resolve_real_world_corpus_root",
        lambda _manifest_path, _manifest, _override: tmp_path / "real_world_stls",
    )
    monkeypatch.setattr(
        module,
        "list_missing_real_world_corpus_files",
        lambda _cases, _root: [],
    )
    monkeypatch.setattr(
        module,
        "score_real_world_corpus",
        lambda _config, manifest_path, corpus_root: _build_stub_score(tmp_path),
    )
    monkeypatch.setattr(
        module,
        "compare_real_world_score_to_baseline",
        lambda _current, _baseline: {"schema_version": 1, "mean_score_delta": 0.1},
    )

    output_path = tmp_path / "real_world_recall.json"
    baseline_path = tmp_path / "real_world_recall_baseline.json"
    baseline_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    delta_path = tmp_path / "real_world_recall_delta.json"

    exit_code = module.main(
        [
            "--merge-gate",
            "--output",
            str(output_path),
            "--baseline",
            str(baseline_path),
            "--delta-output",
            str(delta_path),
        ]
    )

    assert exit_code == 0
    assert output_path.exists()
    assert delta_path.exists()
