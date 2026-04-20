"""
Tests for manifest-driven OpenSCAD feature fixtures.
"""

import os
from math import dist, isclose
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

_SIZE_TOL = 0.05
_CENTER_TOL = 0.15
_DIAMETER_TOL = 0.15
_SLOT_LENGTH_TOL = 0.2
_PATTERN_STEP_TOL = 0.15
_PATTERN_SPACING_TOL = 0.15


def _pop_best_match(candidates, score):
    if not candidates:
        return None
    best_index = min(range(len(candidates)), key=lambda index: score(candidates[index]))
    return candidates.pop(best_index)


def _assert_close(actual, expected, tol, label):
    assert isclose(float(actual), float(expected), abs_tol=tol), (
        f"{label} expected {expected:.6f}, got {float(actual):.6f}"
    )


def _assert_axis_aligned_size(actual_size, expected_size, fixture_name, label):
    assert len(actual_size) == 3
    for axis_name, actual, expected in zip(("x", "y", "z"), actual_size, expected_size):
        _assert_close(actual, expected, _SIZE_TOL, f"{fixture_name} {label} {axis_name}")


def _assert_plate_dimensions(fixture, features):
    plates = [
        feature
        for feature in features
        if feature.get("type") == "plate_like_solid" and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    expected_plate = bool(fixture["expected_detection"].get("plate_like_solid", False))
    if not expected_plate:
        assert not plates
        return

    assert plates, f"{fixture['name']} expected a plate_like_solid feature"
    best = max(plates, key=lambda item: float(item.get("confidence", 0.0)))
    _assert_axis_aligned_size(best["size"], fixture["plate_size"], fixture["name"], "plate size")


def _assert_box_dimensions(fixture, features):
    boxes = [
        feature
        for feature in features
        if feature.get("type") == "box_like_solid" and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    expected_box = bool(fixture["expected_detection"].get("box_like_solid", False))
    if not expected_box:
        assert not boxes
        return

    assert boxes, f"{fixture['name']} expected a box_like_solid feature"
    best = max(boxes, key=lambda item: float(item.get("confidence", 0.0)))
    _assert_axis_aligned_size(best["size"], fixture["box_size"], fixture["name"], "box size")


def _assert_plate_hole_dimensions(fixture, features):
    expected_holes = list(_iter_plate_fixture_holes(fixture))
    holes = [
        feature
        for feature in features
        if feature.get("type") == "hole_like_cutout" and feature.get("axis") == "z"
    ]
    assert len(holes) == len(expected_holes)

    unmatched = list(holes)
    for expected_center, expected_diameter in expected_holes:
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["center"][:2], expected_center),
        )
        assert match is not None, f"{fixture['name']} missing expected plate hole"
        center_error = dist(match["center"][:2], expected_center)
        assert center_error <= _CENTER_TOL, (
            f"{fixture['name']} hole center mismatch: expected {expected_center}, got {match['center'][:2]}"
        )
        _assert_close(
            match["diameter"],
            expected_diameter,
            _DIAMETER_TOL,
            f"{fixture['name']} hole diameter",
        )


def _assert_box_hole_dimensions(fixture, features):
    expected_holes = fixture.get("holes", [])
    holes = [feature for feature in features if feature.get("type") == "hole_like_cutout"]
    assert len(holes) == len(expected_holes)

    unmatched = list(holes)
    for expected in expected_holes:
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["center"], expected["center"]),
        )
        assert match is not None, f"{fixture['name']} missing expected box hole"
        assert str(match.get("axis")) == str(expected["axis"])
        assert dist(match["center"], expected["center"]) <= _CENTER_TOL
        _assert_close(
            match["diameter"],
            expected["diameter"],
            _DIAMETER_TOL,
            f"{fixture['name']} hole diameter",
        )


def _assert_slot_dimensions(fixture, features):
    expected_slots = fixture.get("slots", [])
    slots = [
        feature
        for feature in features
        if feature.get("type") == "slot_like_cutout" and feature.get("axis") == "z"
    ]
    assert len(slots) == len(expected_slots)

    unmatched = list(slots)
    for expected in expected_slots:
        expected_start = expected["start"]
        expected_end = expected["end"]
        match = _pop_best_match(
            unmatched,
            lambda candidate: min(
                dist(candidate["start"][:2], expected_start)
                + dist(candidate["end"][:2], expected_end),
                dist(candidate["start"][:2], expected_end)
                + dist(candidate["end"][:2], expected_start),
            ),
        )
        assert match is not None, f"{fixture['name']} missing expected slot"

        direct_error = dist(match["start"][:2], expected_start) + dist(
            match["end"][:2], expected_end
        )
        swapped_error = dist(match["start"][:2], expected_end) + dist(
            match["end"][:2], expected_start
        )
        assert min(direct_error, swapped_error) <= _CENTER_TOL * 2.0

        _assert_close(
            match["width"],
            expected["width"],
            _DIAMETER_TOL,
            f"{fixture['name']} slot width",
        )
        expected_length = dist(expected_start, expected_end) + float(expected["width"])
        _assert_close(
            match["length"],
            expected_length,
            _SLOT_LENGTH_TOL,
            f"{fixture['name']} slot length",
        )


def _assert_counterbore_dimensions(fixture, features):
    expected_counterbores = fixture.get("counterbores", [])
    counterbores = [
        feature
        for feature in features
        if feature.get("type") == "counterbore_hole" and feature.get("axis") == "z"
    ]
    assert len(counterbores) == len(expected_counterbores)

    unmatched = list(counterbores)
    for expected in expected_counterbores:
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["center"][:2], expected["center"]),
        )
        assert match is not None, f"{fixture['name']} missing expected counterbore"
        assert dist(match["center"][:2], expected["center"]) <= _CENTER_TOL
        _assert_close(
            match["through_diameter"],
            expected["through_diameter"],
            _DIAMETER_TOL,
            f"{fixture['name']} counterbore through_diameter",
        )
        _assert_close(
            match["bore_diameter"],
            expected["bore_diameter"],
            _DIAMETER_TOL,
            f"{fixture['name']} counterbore bore_diameter",
        )
        _assert_close(
            match["bore_depth"],
            expected["bore_depth"],
            _DIAMETER_TOL,
            f"{fixture['name']} counterbore bore_depth",
        )


def _assert_linear_pattern_dimensions(fixture, features):
    expected_patterns = fixture.get("linear_hole_patterns", [])
    if not expected_patterns:
        return
    patterns = [
        feature
        for feature in features
        if feature.get("type") == "linear_hole_pattern" and feature.get("axis") == "z"
    ]
    assert len(patterns) >= len(expected_patterns)

    unmatched = list(patterns)
    z_center = fixture["plate_size"][2] * 0.5
    for expected in expected_patterns:
        expected_origin = [expected["origin"][0], expected["origin"][1], z_center]
        expected_step = [expected["step"][0], expected["step"][1], 0.0]
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["pattern_origin"], expected_origin),
        )
        assert match is not None, f"{fixture['name']} missing expected linear pattern"
        assert int(match.get("pattern_count", 0)) == int(expected["count"])
        assert dist(match["pattern_origin"], expected_origin) <= _CENTER_TOL
        assert dist(match["pattern_step"], expected_step) <= _PATTERN_STEP_TOL
        _assert_close(
            match["diameter"],
            expected["diameter"],
            _DIAMETER_TOL,
            f"{fixture['name']} linear pattern diameter",
        )
        expected_spacing = dist([0.0, 0.0], expected["step"])
        _assert_close(
            match["pattern_spacing"],
            expected_spacing,
            _PATTERN_SPACING_TOL,
            f"{fixture['name']} linear pattern spacing",
        )


def _assert_grid_pattern_dimensions(fixture, features):
    expected_patterns = fixture.get("grid_hole_patterns", [])
    if not expected_patterns:
        return
    patterns = [
        feature
        for feature in features
        if feature.get("type") == "grid_hole_pattern" and feature.get("axis") == "z"
    ]
    assert len(patterns) >= len(expected_patterns)

    unmatched = list(patterns)
    z_center = fixture["plate_size"][2] * 0.5
    for expected in expected_patterns:
        expected_origin = [expected["origin"][0], expected["origin"][1], z_center]
        expected_row_step = [expected["row_step"][0], expected["row_step"][1], 0.0]
        expected_col_step = [expected["col_step"][0], expected["col_step"][1], 0.0]
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["grid_origin"], expected_origin),
        )
        assert match is not None, f"{fixture['name']} missing expected grid pattern"
        assert int(match.get("grid_rows", 0)) == int(expected["rows"])
        assert int(match.get("grid_cols", 0)) == int(expected["cols"])
        assert dist(match["grid_origin"], expected_origin) <= _CENTER_TOL
        assert dist(match["grid_row_step"], expected_row_step) <= _PATTERN_STEP_TOL
        assert dist(match["grid_col_step"], expected_col_step) <= _PATTERN_STEP_TOL
        _assert_close(
            match["diameter"],
            expected["diameter"],
            _DIAMETER_TOL,
            f"{fixture['name']} grid pattern diameter",
        )


def _assert_fixture_dimensions(fixture, features):
    _assert_plate_dimensions(fixture, features)
    _assert_box_dimensions(fixture, features)

    fixture_type = fixture["fixture_type"]
    if fixture_type == "plate":
        _assert_plate_hole_dimensions(fixture, features)
        _assert_slot_dimensions(fixture, features)
        _assert_counterbore_dimensions(fixture, features)
        _assert_linear_pattern_dimensions(fixture, features)
        _assert_grid_pattern_dimensions(fixture, features)
    elif fixture_type == "box":
        _assert_box_hole_dimensions(fixture, features)


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


def test_feature_fixture_manifest_rejects_unknown_schema_version(tmp_path):
    manifest_path = tmp_path / "feature_manifest_schema_mismatch.json"
    manifest_path.write_text(
        """
{
    "schema_version": 2,
    "fixtures": [
        {
            "name": "plate_plain",
            "fixture_type": "plate",
            "output_filename": "plate_plain.scad",
            "plate_size": [20.0, 10.0, 2.0],
            "expected_detection": {
                "plate_like_solid": true,
                "hole_count": 0,
                "slot_count": 0,
                "linear_pattern_count": 0,
                "grid_pattern_count": 0,
                "counterbore_count": 0
            }
        }
    ]
}
""".strip(),
    encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema_version"):
        load_feature_fixture_manifest(manifest_path)


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

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for feature round-trip checks: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

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

        _assert_fixture_dimensions(fixture, graph["features"])
