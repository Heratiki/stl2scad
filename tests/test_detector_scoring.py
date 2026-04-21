"""Tests for the tuning scoring function."""

from pathlib import Path

import pytest

from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.scoring import (
    FixtureScore,
    ManifestScore,
    score_fixture,
    score_manifest,
)
from stl2scad.core.feature_fixtures import load_feature_fixture_manifest, write_feature_fixture_library
from stl2scad.core.converter import get_openscad_path, run_openscad


@pytest.fixture(scope="module")
def rendered_fixture_dir(tmp_path_factory):
    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError:
        pytest.skip("OpenSCAD not available")
    out_dir = tmp_path_factory.mktemp("scoring_fixtures")
    manifest_path = Path("tests/data/feature_fixtures_manifest.json")
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, out_dir)
    for fixture in fixtures:
        scad_path = out_dir / fixture["output_filename"]
        stl_path = out_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = out_dir / f"{fixture['name']}.log"
        assert run_openscad(fixture["name"], ["--render", "-o", str(stl_path), str(scad_path)], str(log_path), openscad_path)
    return out_dir, fixtures


def test_score_fixture_perfect_on_default_config_plate_plain(rendered_fixture_dir):
    out_dir, fixtures = rendered_fixture_dir
    fixture = next(f for f in fixtures if f["name"] == "plate_plain")
    stl_path = out_dir / f"{Path(fixture['output_filename']).stem}.stl"
    score = score_fixture(DetectorConfig(), fixture, stl_path)
    assert isinstance(score, FixtureScore)
    assert score.count_score == pytest.approx(1.0)
    assert score.dimension_score >= 0.9
    assert score.total >= 0.95


def test_score_fixture_penalizes_missing_holes():
    # With a ridiculous angular_coverage_min, the detector finds no holes.
    fixture = {
        "name": "synthetic",
        "fixture_type": "plate",
        "plate_size": [20.0, 10.0, 2.0],
        "expected_detection": {"plate_like_solid": True, "box_like_solid": False, "hole_count": 2, "slot_count": 0,
                                "linear_pattern_count": 0, "grid_pattern_count": 0,
                                "counterbore_count": 0, "rectangular_cutout_count": 0,
                                "rectangular_pocket_count": 0},
    }
    # Feed a fake graph directly via a test-only entry point (see impl).
    from stl2scad.tuning.scoring import score_fixture_against_graph
    graph = {"features": [{"type": "plate_like_solid", "confidence": 0.95,
                            "size": [20.0, 10.0, 2.0], "origin": [0, 0, 0]}]}
    score = score_fixture_against_graph(fixture, graph)
    assert 0.0 < score.count_score < 1.0  # plate right, holes wrong
    assert score.total < 1.0


def test_score_manifest_aggregates(rendered_fixture_dir):
    out_dir, fixtures = rendered_fixture_dir
    result = score_manifest(DetectorConfig(), fixtures, out_dir)
    assert isinstance(result, ManifestScore)
    assert 0.0 <= result.mean <= 1.0
    assert len(result.per_fixture) == len(fixtures)
    # On the default config the mean should be high — the manifest was
    # curated to work with today's detector.
    assert result.mean >= 0.90
