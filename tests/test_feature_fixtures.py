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


def _iter_plate_fixture_holes(fixture):
    for hole in fixture.get("holes", []):
        yield hole["center"], float(hole["diameter"])

    for pattern in fixture.get("linear_hole_patterns", []):
        origin_x, origin_y = pattern["origin"]
        step_x, step_y = pattern["step"]
        diameter = float(pattern["diameter"])
        for item_index in range(int(pattern["count"])):
            yield [origin_x + step_x * item_index, origin_y + step_y * item_index], diameter

    for pattern in fixture.get("grid_hole_patterns", []):
        origin_x, origin_y = pattern["origin"]
        row_step_x, row_step_y = pattern["row_step"]
        col_step_x, col_step_y = pattern["col_step"]
        diameter = float(pattern["diameter"])
        for row in range(int(pattern["rows"])):
            for col in range(int(pattern["cols"])):
                yield [
                    origin_x + row_step_x * row + col_step_x * col,
                    origin_y + row_step_y * row + col_step_y * col,
                ], diameter


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


def test_feature_fixture_validation_rejects_invalid_counterbore_geometry():
    invalid_fixture = {
        "name": "invalid_plate_counterbore",
        "fixture_type": "plate",
        "output_filename": "invalid_plate_counterbore.scad",
        "plate_size": [30.0, 20.0, 6.0],
        "counterbores": [
            {
                "center": [0.0, 0.0],
                "through_diameter": 4.0,
                "bore_diameter": 3.0,
                "bore_depth": 2.0,
            }
        ],
        "expected_detection": {
            "plate_like_solid": True,
            "hole_count": 0,
            "slot_count": 0,
            "linear_pattern_count": 0,
            "grid_pattern_count": 0,
            "counterbore_count": 1,
        },
    }

    with pytest.raises(ValueError, match="bore_diameter must be larger than through_diameter"):
        validate_feature_fixture_spec(invalid_fixture)


def test_feature_fixture_manifest_covers_roadmap_stress_cases(test_data_dir):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)

    plate_fixtures = [fixture for fixture in fixtures if fixture["fixture_type"] == "plate"]
    fixture_types = {fixture["fixture_type"] for fixture in fixtures}

    assert {"box", "l_bracket"}.issubset(fixture_types)
    assert any(
        fixture["slots"]
        and (
            fixture["holes"]
            or fixture["linear_hole_patterns"]
            or fixture["grid_hole_patterns"]
        )
        for fixture in plate_fixtures
    )
    assert any(
        max(fixture["plate_size"][:2]) / min(fixture["plate_size"][:2]) >= 4.0
        and fixture["explicit_hole_count"] >= 3
        for fixture in plate_fixtures
    )
    assert any(
        min(diameter for _center, diameter in _iter_plate_fixture_holes(fixture)) <= 1.2
        for fixture in plate_fixtures
        if fixture["explicit_hole_count"] > 0
    )
    assert any(
        max(diameter for _center, diameter in _iter_plate_fixture_holes(fixture)) >= 8.0
        for fixture in plate_fixtures
        if fixture["explicit_hole_count"] > 0
    )
    assert any(
        min(
            fixture["plate_size"][0] * 0.5 - abs(center[0]) - diameter * 0.5,
            fixture["plate_size"][1] * 0.5 - abs(center[1]) - diameter * 0.5,
        )
        <= 0.5
        for fixture in plate_fixtures
        for center, diameter in _iter_plate_fixture_holes(fixture)
    )


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
