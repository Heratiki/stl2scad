"""
Tests for manifest-driven OpenSCAD feature fixtures.
"""

from pathlib import Path

import pytest

from stl2scad.core.converter import get_openscad_path, run_openscad
from stl2scad.core.feature_fixtures import (
    generate_feature_fixture_scad,
    iter_expected_feature_counts,
    load_feature_fixture_manifest,
    validate_feature_fixture_spec,
    write_feature_fixture_library,
)
from stl2scad.core.feature_graph import build_feature_graph_for_stl


def test_feature_fixture_manifest_matches_checked_in_scad(test_data_dir, test_output_dir):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    checked_in_dir = test_data_dir / "feature_fixtures_scad"

    fixtures = load_feature_fixture_manifest(manifest_path)
    written = write_feature_fixture_library(manifest_path, test_output_dir)

    assert len(written) == len(fixtures)
    for fixture in fixtures:
        generated = generate_feature_fixture_scad(fixture)
        checked_in = (checked_in_dir / fixture["output_filename"]).read_text(
            encoding="utf-8"
        )
        regenerated = (test_output_dir / fixture["output_filename"]).read_text(
            encoding="utf-8"
        )
        assert generated == checked_in
        assert regenerated == checked_in


def test_feature_fixture_validation_rejects_out_of_bounds_hole():
    invalid_fixture = {
        "name": "invalid_plate_hole",
        "fixture_type": "plate",
        "output_filename": "invalid_plate_hole.scad",
        "plate_size": [20.0, 10.0, 2.0],
        "holes": [{"center": [9.1, 0.0], "diameter": 4.0}],
        "expected_detection": {
            "plate_like_solid": True,
            "hole_count": 1,
            "slot_count": 0,
            "linear_pattern_count": 0,
            "grid_pattern_count": 0,
        },
    }

    with pytest.raises(ValueError, match="extends beyond the plate width"):
        validate_feature_fixture_spec(invalid_fixture)


def test_feature_fixture_generation_supports_box_and_l_bracket():
    box_fixture = validate_feature_fixture_spec(
        {
            "name": "box_plain",
            "fixture_type": "box",
            "output_filename": "box_plain.scad",
            "box_size": [18.0, 12.0, 10.0],
            "expected_detection": {
                "plate_like_solid": False,
                "box_like_solid": True,
                "hole_count": 0,
                "slot_count": 0,
                "linear_pattern_count": 0,
                "grid_pattern_count": 0,
            },
        }
    )
    bracket_fixture = validate_feature_fixture_spec(
        {
            "name": "l_bracket_plain",
            "fixture_type": "l_bracket",
            "output_filename": "l_bracket_plain.scad",
            "bracket_size": [24.0, 12.0, 20.0],
            "leg_thickness": 4.0,
            "expected_detection": {
                "plate_like_solid": False,
                "box_like_solid": False,
                "hole_count": 0,
                "slot_count": 0,
                "linear_pattern_count": 0,
                "grid_pattern_count": 0,
            },
        }
    )

    box_scad = generate_feature_fixture_scad(box_fixture)
    bracket_scad = generate_feature_fixture_scad(bracket_fixture)

    assert "fixture_type: box" in box_scad
    assert "difference()" in box_scad
    assert "cube(box_size)" in box_scad
    assert iter_expected_feature_counts(box_fixture)["box_like_solid"] == 1

    assert "fixture_type: l_bracket" in bracket_scad
    assert "union()" in bracket_scad
    assert "leg_thickness = 4.000000;" in bracket_scad
    assert iter_expected_feature_counts(bracket_fixture)["box_like_solid"] == 0


def test_feature_fixture_round_trip_detection(test_data_dir, test_output_dir):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, test_output_dir)

    openscad_path = get_openscad_path()
    if not openscad_path:
        pytest.skip("OpenSCAD not available")

    for fixture in fixtures:
        scad_path = test_output_dir / fixture["output_filename"]
        stl_path = test_output_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = test_output_dir / f"{fixture['name']}.log"

        success = run_openscad(
            fixture["name"],
            ["--render", "-o", str(stl_path), str(scad_path)],
            str(log_path),
            openscad_path,
        )

        assert success, f"OpenSCAD render failed for {fixture['name']}"
        assert stl_path.exists()

        graph = build_feature_graph_for_stl(stl_path)
        feature_counts: dict[str, int] = {}
        for feature in graph["features"]:
            feature_type = feature["type"]
            feature_counts[feature_type] = feature_counts.get(feature_type, 0) + 1

        for feature_type, expected_count in iter_expected_feature_counts(fixture).items():
            assert (
                feature_counts.get(feature_type, 0) == expected_count
            ), f"{fixture['name']} expected {expected_count} {feature_type} entries, got {feature_counts.get(feature_type, 0)}"
