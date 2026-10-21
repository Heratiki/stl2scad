"""T-016: the test render cache (OpenSCAD is replaced by a counting fake)."""

import os
from pathlib import Path

import pytest

from tests import render_cache


@pytest.fixture
def cache(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    monkeypatch.setenv("STL2SCAD_RENDER_CACHE", str(directory))
    monkeypatch.delenv("STL2SCAD_RENDER_CACHE_LOG", raising=False)
    monkeypatch.setattr(render_cache, "_openscad_version", lambda path: "fake 1")
    calls = []

    def fake_run(description, args, log_file, openscad_path=None, timeout=30):
        calls.append(args)
        scad = Path(args[-1]).read_text()
        Path(args[args.index("-o") + 1]).write_text("solid " + scad)
        return True

    monkeypatch.setattr(render_cache, "run_openscad", fake_run)
    monkeypatch.setattr(render_cache, "RENDER_COUNT", 0)
    return directory, calls


def _render(tmp_path, text, out="a.stl", args=("--render",)):
    scad = tmp_path / "in.scad"
    scad.write_text(text)
    stl = tmp_path / out
    ok = render_cache.cached_render(
        "t", list(args), scad, stl, tmp_path / "t.log", "fake"
    )
    return ok, stl


def test_render_cache_hit_skips_render(cache, tmp_path):
    _, calls = cache
    _, first = _render(tmp_path, "cube(1);", "a.stl")
    _, second = _render(tmp_path, "cube(1);", "b.stl")
    assert render_cache.RENDER_COUNT == 1 and len(calls) == 1
    assert first.read_bytes() == second.read_bytes()


def test_render_cache_miss_on_changed_scad(cache, tmp_path):
    _render(tmp_path, "cube(1);")
    _render(tmp_path, "cube(2);")
    assert render_cache.RENDER_COUNT == 2
    _render(tmp_path, "cube(2);", args=("--render", "-D", "a=1"))
    assert render_cache.RENDER_COUNT == 3


def test_render_cache_off_switch(cache, tmp_path, monkeypatch):
    directory, _ = cache
    monkeypatch.setenv("STL2SCAD_RENDER_CACHE", "off")
    _render(tmp_path, "cube(1);")
    _render(tmp_path, "cube(1);")
    assert render_cache.RENDER_COUNT == 2
    assert not directory.exists()


def test_render_cache_atomic_write(cache, tmp_path, monkeypatch):
    directory, calls = cache
    directory.mkdir()
    (directory / "stale.tmp").write_text("partial")
    replaced = []
    real_replace = os.replace
    monkeypatch.setattr(
        render_cache.os, "replace", lambda s, d: (replaced.append(d), real_replace(s, d))
    )
    _render(tmp_path, "cube(1);")
    assert len(replaced) == 1 and str(replaced[0]).endswith(".stl")
    assert (directory / "stale.tmp").read_text() == "partial"
    _render(tmp_path, "cube(1);")
    assert render_cache.RENDER_COUNT == 1
    # a failed render stores nothing
    monkeypatch.setattr(render_cache, "run_openscad", lambda *a, **k: False)
    before = sorted(p.name for p in directory.iterdir())
    ok, _ = _render(tmp_path, "cube(99);")
    assert not ok
    assert sorted(p.name for p in directory.iterdir()) == before
