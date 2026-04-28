"""Tests for local corpus progress and HTML reporting."""

from __future__ import annotations

import builtins
import hashlib
import json

from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.tuning import html_report
from stl2scad.tuning.html_report import generate_html_report, generate_thumbnail
from stl2scad.tuning.progress import corpus_progress


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png"


def test_corpus_progress_falls_back_when_tqdm_is_unavailable(monkeypatch, capsys):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "tqdm":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert list(corpus_progress([1, 2, 3], desc="Scanning", total=3)) == [1, 2, 3]
    assert "Scanning:" in capsys.readouterr().out


def test_generate_thumbnail_uses_cache_and_populates_miss(
    test_data_dir,
    tmp_path,
    monkeypatch,
):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    stl_path = fixtures_dir / "primitive_box_axis_aligned.stl"
    sha256 = hashlib.sha256(stl_path.read_bytes()).hexdigest()
    cache_dir = tmp_path / "thumbs"
    cache_dir.mkdir()
    cache_path = cache_dir / f"{sha256[:12]}.png"
    cache_path.write_bytes(PNG_BYTES)

    def fail_render(*_args, **_kwargs):
        raise AssertionError("cache hit should not render")

    monkeypatch.setattr(html_report, "_render_thumbnail_png", fail_render)
    assert generate_thumbnail(stl_path, sha256, cache_dir).startswith(
        "data:image/png;base64,"
    )

    cache_path.unlink()

    def fake_render(_stl_path, output_path):
        output_path.write_bytes(PNG_BYTES)

    monkeypatch.setattr(html_report, "_render_thumbnail_png", fake_render)
    uri = generate_thumbnail(stl_path, sha256, cache_dir)

    assert cache_path.exists()
    assert uri.startswith("data:image/png;base64,")


def test_generate_html_report_contains_badges_and_thumbnail(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    stl_path = corpus_dir / "part.stl"
    stl_path.write_bytes(b"dummy stl")
    sha256 = hashlib.sha256(stl_path.read_bytes()).hexdigest()
    thumb_cache = tmp_path / "thumbs"
    thumb_cache.mkdir()
    (thumb_cache / f"{sha256[:12]}.png").write_bytes(PNG_BYTES)

    score_path = tmp_path / "score.json"
    score_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": "2026-04-28T00:00:00+00:00",
                "corpus_root": str(corpus_dir),
                "files_total": 1,
                "files_present": 1,
                "files_missing": 0,
                "preview_ready_ratio": 1.0,
                "triage": {
                    "bucket_counts": {
                        "parametric_preview": 1,
                        "axis_pairs_only": 0,
                        "feature_graph_no_preview": 0,
                        "polyhedron_fallback": 0,
                        "error": 0,
                    },
                    "per_file": [
                        {
                            "source_file": "part.stl",
                            "bucket": "parametric_preview",
                        }
                    ],
                },
                "per_file": [
                    {
                        "relative_path": "part.stl",
                        "sha256": sha256,
                        "status": "ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output = generate_html_report(
        score_path,
        tmp_path / "report.html",
        thumb_cache_dir=thumb_cache,
        show_progress=False,
    )
    html = output.read_text(encoding="utf-8")

    assert output.exists()
    assert "parametric_preview" in html
    assert "polyhedron_fallback" in html
    assert "parametric preview" in html
    assert "<img" in html
