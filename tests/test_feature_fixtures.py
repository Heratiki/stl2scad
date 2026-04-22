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
    rank_feature_fixture_candidates,
    validate_feature_fixture_spec,
    write_feature_fixture_library,
)
from stl2scad.core.feature_graph import (
    build_feature_graph_for_stl,
    emit_feature_graph_scad_preview,
)

_SIZE_TOL = 0.05
_CENTER_TOL = 0.15
_DIAMETER_TOL = 0.15
_SLOT_LENGTH_TOL = 0.2
_PATTERN_STEP_TOL = 0.15
_PATTERN_SPACING_TOL = 0.15
_POCKET_DEPTH_TOL = 0.15


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


def _assert_rectangular_cutout_dimensions(fixture, features):
    expected_cutouts = []
    if fixture["fixture_type"] == "plate":
        thickness = float(fixture["plate_size"][2])
        z_center = thickness * 0.5
        for cutout in fixture.get("rectangular_cutouts", []):
            expected_cutouts.append(
                {
                    "axis": "z",
                    "center": [cutout["center"][0], cutout["center"][1], z_center],
                    "size": [cutout["size"][0], cutout["size"][1], thickness],
                }
            )
    elif fixture["fixture_type"] == "box":
        expected_cutouts = []
        for cutout in fixture.get("cutouts", []):
            axis = _box_cutout_axis(cutout, fixture["box_size"])
            if axis is None:
                continue
            if _box_cutout_boundary_touches(cutout, fixture["box_size"]) >= 2:
                expected_cutouts.append(
                    {
                        "axis": axis,
                        "center": cutout["center"],
                        "size": cutout["size"],
                    }
                )

    cutouts = [feature for feature in features if feature.get("type") == "rectangular_cutout"]
    assert len(cutouts) == len(expected_cutouts)

    unmatched = list(cutouts)
    for expected in expected_cutouts:
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["center"], expected["center"]),
        )
        assert match is not None, f"{fixture['name']} missing expected rectangular cutout"
        assert str(match.get("axis")) == str(expected["axis"])
        assert dist(match["center"], expected["center"]) <= _CENTER_TOL
        _assert_axis_aligned_size(
            match["size"],
            expected["size"],
            fixture["name"],
            "rectangular cutout size",
        )


def _assert_rectangular_pocket_dimensions(fixture, features):
    expected_pockets = []
    if fixture["fixture_type"] == "plate":
        thickness = float(fixture["plate_size"][2])
        for pocket in fixture.get("rectangular_pockets", []):
            expected_pockets.append(
                {
                    "axis": "z",
                    "center": [
                        pocket["center"][0],
                        pocket["center"][1],
                        thickness - float(pocket["depth"]) * 0.5,
                    ],
                    "size": [pocket["size"][0], pocket["size"][1], float(pocket["depth"])],
                }
            )
    elif fixture["fixture_type"] == "box":
        for cutout in fixture.get("cutouts", []):
            axis = _box_cutout_axis(cutout, fixture["box_size"])
            if axis is None:
                continue
            if _box_cutout_boundary_touches(cutout, fixture["box_size"]) == 1:
                expected_pockets.append(
                    {
                        "axis": axis,
                        "center": cutout["center"],
                        "size": cutout["size"],
                    }
                )

    pockets = [feature for feature in features if feature.get("type") == "rectangular_pocket"]
    assert len(pockets) == len(expected_pockets)

    unmatched = list(pockets)
    for expected in expected_pockets:
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["center"], expected["center"]),
        )
        assert match is not None, f"{fixture['name']} missing expected rectangular pocket"
        assert str(match.get("axis")) == str(expected["axis"])
        assert dist(match["center"], expected["center"]) <= _CENTER_TOL
        _assert_axis_aligned_size(
            match["size"],
            expected["size"],
            fixture["name"],
            "rectangular pocket size",
        )
        _assert_close(
            match["depth"],
            expected["size"][2],
            _POCKET_DEPTH_TOL,
            f"{fixture['name']} rectangular pocket depth",
        )


def _assert_linear_pattern_dimensions(fixture, features):
    explicit_patterns = fixture.get("linear_hole_patterns", [])
    expected_total = int(fixture["expected_detection"].get("linear_pattern_count", 0))
    inferred_patterns = _expected_inferred_linear_patterns(fixture)
    if expected_total == 0 and not explicit_patterns and not inferred_patterns:
        return
    patterns = [
        feature
        for feature in features
        if feature.get("type") == "linear_hole_pattern" and feature.get("axis") == "z"
    ]
    assert len(patterns) >= len(explicit_patterns) + len(inferred_patterns)

    unmatched = list(patterns)
    z_center = fixture["plate_size"][2] * 0.5
    for expected in explicit_patterns:
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

    for expected in inferred_patterns:
        expected_origin = [expected["origin"][0], expected["origin"][1], z_center]
        expected_step = [expected["step"][0], expected["step"][1], 0.0]
        match = _pop_best_match(
            unmatched,
            lambda candidate: dist(candidate["pattern_origin"], expected_origin),
        )
        assert match is not None, f"{fixture['name']} missing expected inferred linear pattern"
        assert int(match.get("pattern_count", 0)) == int(expected["count"])
        assert dist(match["pattern_origin"], expected_origin) <= _CENTER_TOL
        assert dist(match["pattern_step"], expected_step) <= _PATTERN_STEP_TOL
        _assert_close(
            match["diameter"],
            expected["diameter"],
            _DIAMETER_TOL,
            f"{fixture['name']} inferred linear pattern diameter",
        )
        expected_spacing = dist([0.0, 0.0], expected["step"])
        _assert_close(
            match["pattern_spacing"],
            expected_spacing,
            _PATTERN_SPACING_TOL,
            f"{fixture['name']} inferred linear pattern spacing",
        )


def _expected_inferred_linear_patterns(fixture):
    expected_total = int(fixture["expected_detection"].get("linear_pattern_count", 0))
    explicit_patterns = fixture.get("linear_hole_patterns", [])
    inferred_needed = max(0, expected_total - len(explicit_patterns))
    if inferred_needed == 0:
        return []

    grouped: dict[float, list[list[float]]] = {}
    for hole in fixture.get("holes", []):
        diameter = float(hole["diameter"])
        grouped.setdefault(diameter, []).append([float(value) for value in hole["center"]])

    inferred_patterns = []
    for diameter, centers in grouped.items():
        if len(centers) != 2:
            continue
        dx = abs(centers[1][0] - centers[0][0])
        dy = abs(centers[1][1] - centers[0][1])
        if dx <= 1e-9 and dy <= 1e-9:
            continue
        if dx >= dy:
            ordered = sorted(centers, key=lambda center: (center[0], center[1]))
        else:
            ordered = sorted(centers, key=lambda center: (center[1], center[0]))
        step = [ordered[1][0] - ordered[0][0], ordered[1][1] - ordered[0][1]]
        inferred_patterns.append(
            {
                "origin": ordered[0],
                "step": step,
                "count": 2,
                "diameter": float(diameter),
            }
        )

    inferred_patterns.sort(
        key=lambda pattern: (
            pattern["origin"][0],
            pattern["origin"][1],
            pattern["diameter"],
        )
    )
    return inferred_patterns[:inferred_needed]


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
    _assert_rectangular_cutout_dimensions(fixture, features)
    _assert_rectangular_pocket_dimensions(fixture, features)

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


def _box_cutout_boundary_touches(cutout, box_size):
    half_sizes = [float(value) * 0.5 for value in box_size]
    touches = 0
    for axis_index in range(3):
        half_cutout = float(cutout["size"][axis_index]) * 0.5
        center = float(cutout["center"][axis_index])
        if center - half_cutout <= -half_sizes[axis_index] + 1e-6:
            touches += 1
        if center + half_cutout >= half_sizes[axis_index] - 1e-6:
            touches += 1
    return touches


def _box_cutout_axis(cutout, box_size):
    half_sizes = [float(value) * 0.5 for value in box_size]
    labels = ("x", "y", "z")
    touched_axes = []
    for axis_index in range(3):
        half_cutout = float(cutout["size"][axis_index]) * 0.5
        center = float(cutout["center"][axis_index])
        touches_min = center - half_cutout <= -half_sizes[axis_index] + 1e-6
        touches_max = center + half_cutout >= half_sizes[axis_index] - 1e-6
        if touches_min or touches_max:
            touched_axes.append(labels[axis_index])
    if len(touched_axes) != 1:
        return None
    return touched_axes[0]


def _assert_preview_named_variables_box(fixture, preview_scad):
    assert "box_origin = [" in preview_scad
    assert "box_size = [" in preview_scad


def _assert_preview_named_variables(fixture, preview_scad):
    assert "plate_origin = [" in preview_scad
    assert "plate_size = [" in preview_scad

    if fixture.get("slots"):
        assert "slot_0_start = [" in preview_scad
        assert "slot_0_end = [" in preview_scad
        assert "slot_0_width = " in preview_scad

    if fixture.get("counterbores"):
        assert "counterbore_0_center = [" in preview_scad
        assert "counterbore_0_through_diameter = " in preview_scad
        assert "counterbore_0_bore_diameter = " in preview_scad
        assert "counterbore_0_bore_depth = " in preview_scad

    if fixture.get("rectangular_cutouts"):
        assert "rect_cutout_0_center = [" in preview_scad
        assert "rect_cutout_0_size = [" in preview_scad

    if fixture.get("rectangular_pockets"):
        assert "rect_pocket_0_center = [" in preview_scad
        assert "rect_pocket_0_size = [" in preview_scad

    if fixture.get("linear_hole_patterns") or int(
        fixture["expected_detection"].get("linear_pattern_count", 0)
    ) > 0:
        assert "hole_pattern_0_count = " in preview_scad
        assert "hole_pattern_0_origin = [" in preview_scad
        assert "hole_pattern_0_step = [" in preview_scad
        assert "hole_pattern_0_diameter = " in preview_scad

    if fixture.get("grid_hole_patterns"):
        assert "hole_grid_0_rows = " in preview_scad
        assert "hole_grid_0_cols = " in preview_scad
        assert "hole_grid_0_origin = [" in preview_scad
        assert "hole_grid_0_row_step = [" in preview_scad
        assert "hole_grid_0_col_step = [" in preview_scad
        assert "hole_grid_0_diameter = " in preview_scad

    expected_plate_holes = list(_iter_plate_fixture_holes(fixture))
    expected_pattern_holes = sum(
        int(pattern["count"]) for pattern in fixture.get("linear_hole_patterns", [])
    ) + sum(
        int(pattern["rows"]) * int(pattern["cols"])
        for pattern in fixture.get("grid_hole_patterns", [])
    )
    expected_pattern_holes += sum(
        int(pattern["count"]) for pattern in _expected_inferred_linear_patterns(fixture)
    )
    expected_standalone_holes = max(0, len(expected_plate_holes) - expected_pattern_holes)
    if expected_standalone_holes:
        assert "hole_0_center = [" in preview_scad
        assert "hole_0_diameter = " in preview_scad


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
    manifest_path = tmp_path / "feature_manifest_schema_unsupported.json"
    manifest_path.write_text(
        """
{
    "schema_version": 3,
    "fixtures": [
        {
            "name": "plate_plain",
            "fixture_type": "plate",
            "output_filename": "plate_plain.scad",
            "plate_size": [20.0, 10.0, 2.0],
            "candidates": [
                {
                    "rank": 1,
                    "name": "primary",
                    "confidence": 0.95,
                    "expected_detection": {
                        "plate_like_solid": true,
                        "box_like_solid": false,
                        "hole_count": 0,
                        "slot_count": 0,
                        "linear_pattern_count": 0,
                        "grid_pattern_count": 0,
                        "counterbore_count": 0
                    }
                }
            ]
        }
    ]
}
""".strip(),
    encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema_version"):
        load_feature_fixture_manifest(manifest_path)


def test_feature_fixture_candidates_validation():
    """Test that schema v2 fixture candidates are validated correctly."""
    # Valid fixture with multiple candidates
    valid_fixture = {
        "name": "ambiguous_box",
        "fixture_type": "box",
        "output_filename": "ambiguous.scad",
        "box_size": [20.0, 16.0, 12.0],
        "candidates": [
            {
                "rank": 1,
                "name": "hollow_box",
                "confidence": 0.85,
                "expected_detection": {
                    "plate_like_solid": False,
                    "box_like_solid": True,
                    "hole_count": 0,
                    "slot_count": 0,
                    "linear_pattern_count": 0,
                    "grid_pattern_count": 0,
                    "counterbore_count": 0,
                }
            },
            {
                "rank": 2,
                "name": "wall_plates",
                "confidence": 0.60,
                "expected_detection": {
                    "plate_like_solid": True,
                    "box_like_solid": False,
                    "hole_count": 0,
                    "slot_count": 0,
                    "linear_pattern_count": 0,
                    "grid_pattern_count": 0,
                    "counterbore_count": 0,
                }
            }
        ]
    }
    
    # Should validate successfully
    spec = validate_feature_fixture_spec(valid_fixture, schema_version=2)
    assert len(spec["candidates"]) == 2
    assert spec["candidates"][0]["rank"] == 1
    assert spec["candidates"][0]["confidence"] == 0.85
    assert spec["candidates"][1]["rank"] == 2


def test_feature_fixture_candidates_require_v2_schema():
    """Test that candidates are required in schema v2."""
    fixture_v2_missing_candidates = {
        "name": "invalid_v2",
        "fixture_type": "box",
        "output_filename": "invalid.scad",
        "box_size": [20.0, 16.0, 12.0],
    }
    
    with pytest.raises(ValueError, match="requires candidates array"):
        validate_feature_fixture_spec(fixture_v2_missing_candidates, schema_version=2)


def test_feature_fixture_candidates_invalid_confidence():
    """Test that candidate confidence must be between 0 and 1."""
    invalid_fixture = {
        "name": "invalid_confidence",
        "fixture_type": "box",
        "output_filename": "invalid.scad",
        "box_size": [20.0, 16.0, 12.0],
        "candidates": [
            {
                "rank": 1,
                "name": "primary",
                "confidence": 1.5,  # Invalid: > 1.0
                "expected_detection": {
                    "plate_like_solid": False,
                    "box_like_solid": True,
                    "hole_count": 0,
                    "slot_count": 0,
                    "linear_pattern_count": 0,
                    "grid_pattern_count": 0,
                    "counterbore_count": 0,
                }
            }
        ]
    }
    
    with pytest.raises(ValueError, match="confidence must be 0.0-1.0"):
        validate_feature_fixture_spec(invalid_fixture, schema_version=2)


def test_feature_fixture_candidates_duplicate_ranks():
    """Test that duplicate ranks are rejected."""
    invalid_fixture = {
        "name": "duplicate_ranks",
        "fixture_type": "box",
        "output_filename": "invalid.scad",
        "box_size": [20.0, 16.0, 12.0],
        "candidates": [
            {
                "rank": 1,
                "name": "first",
                "confidence": 0.85,
                "expected_detection": {
                    "plate_like_solid": False,
                    "box_like_solid": True,
                    "hole_count": 0,
                    "slot_count": 0,
                    "linear_pattern_count": 0,
                    "grid_pattern_count": 0,
                    "counterbore_count": 0,
                }
            },
            {
                "rank": 1,  # Duplicate!
                "name": "second",
                "confidence": 0.60,
                "expected_detection": {
                    "plate_like_solid": True,
                    "box_like_solid": False,
                    "hole_count": 0,
                    "slot_count": 0,
                    "linear_pattern_count": 0,
                    "grid_pattern_count": 0,
                    "counterbore_count": 0,
                }
            }
        ]
    }
    
    with pytest.raises(ValueError, match="duplicate rank"):
        validate_feature_fixture_spec(invalid_fixture, schema_version=2)


def test_feature_fixture_manifest_with_ambiguous_fixture(test_data_dir):
    """Test that the manifest includes an ambiguous fixture with multiple candidates."""
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    
    ambiguous = [f for f in fixtures if f["name"] == "box_hollow_ambiguous"]
    assert len(ambiguous) == 1, "Manifest should include box_hollow_ambiguous fixture"
    
    fixture = ambiguous[0]
    assert len(fixture["candidates"]) >= 2, "Ambiguous fixture should have multiple candidates"
    
    # Verify candidates are sorted by rank
    ranks = [c["rank"] for c in fixture["candidates"]]
    assert ranks == sorted(ranks), "Candidates must be sorted by rank"
    
    # Verify primary interpretation is most confident
    assert fixture["candidates"][0]["confidence"] >= fixture["candidates"][1]["confidence"], \
        "Primary candidate should have higher confidence than secondary"
    assert fixture["cutouts"], "Ambiguous hollow box fixture should include a real cavity cutout"
    assert fixture["cutouts"][0]["center"] == [0.0, 0.0, 0.0]


def test_feature_fixture_candidate_ranking_prefers_exact_match():
    fixture = validate_feature_fixture_spec(
        {
            "name": "ambiguous_box",
            "fixture_type": "box",
            "output_filename": "ambiguous_box.scad",
            "box_size": [24.0, 16.0, 12.0],
            "candidates": [
                {
                    "rank": 1,
                    "name": "hollow_box_via_difference",
                    "confidence": 0.85,
                    "expected_detection": {
                        "plate_like_solid": False,
                        "box_like_solid": True,
                        "hole_count": 0,
                        "slot_count": 0,
                        "linear_pattern_count": 0,
                        "grid_pattern_count": 0,
                        "counterbore_count": 0,
                    },
                },
                {
                    "rank": 2,
                    "name": "six_wall_plates_interpretation",
                    "confidence": 0.60,
                    "expected_detection": {
                        "plate_like_solid": True,
                        "box_like_solid": False,
                        "hole_count": 0,
                        "slot_count": 0,
                        "linear_pattern_count": 0,
                        "grid_pattern_count": 0,
                        "counterbore_count": 0,
                    },
                },
            ],
        },
        schema_version=2,
    )
    graph = {
        "features": [
            {"type": "box_like_solid", "confidence": 0.82},
            {"type": "axis_boundary_plane_pair", "confidence": 1.0},
        ]
    }

    rankings = rank_feature_fixture_candidates(fixture, graph)

    assert [ranking["name"] for ranking in rankings] == [
        "hollow_box_via_difference",
        "six_wall_plates_interpretation",
    ]
    assert rankings[0]["exact_match"] is True
    assert rankings[0]["candidate_confidence"] == pytest.approx(0.82)
    assert rankings[1]["exact_match"] is False
    assert rankings[1]["candidate_confidence"] == 0.0


def test_feature_fixture_manifest_schema_v2(test_data_dir):
    """Test that all fixtures in the manifest have been properly migrated to schema v2."""
    import json
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    
    assert raw_manifest["schema_version"] == 2, "Manifest should be schema version 2"
    
    for fixture in raw_manifest["fixtures"]:
        assert "candidates" in fixture, f"Fixture {fixture['name']} missing candidates array"
        assert isinstance(fixture["candidates"], list), f"Fixture {fixture['name']} candidates must be array"
        assert len(fixture["candidates"]) > 0, f"Fixture {fixture['name']} candidates must not be empty"
        
        for candidate in fixture["candidates"]:
            assert "rank" in candidate, f"Candidate in {fixture['name']} missing rank"
            assert "name" in candidate, f"Candidate in {fixture['name']} missing name"
            assert "confidence" in candidate, f"Candidate in {fixture['name']} missing confidence"
            assert "expected_detection" in candidate, f"Candidate in {fixture['name']} missing expected_detection"


def test_feature_fixture_manifest_covers_roadmap_stress_cases(test_data_dir):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)

    plate_fixtures = [fixture for fixture in fixtures if fixture["fixture_type"] == "plate"]
    negative_fixtures = [fixture for fixture in fixtures if fixture["fixture_type"] in {"sphere", "torus"}]
    fixture_types = {fixture["fixture_type"] for fixture in fixtures}

    assert {"box", "l_bracket", "sphere", "torus"}.issubset(fixture_types), \
        f"Manifest must include box, l_bracket, sphere, and torus fixtures. Found: {fixture_types}"
    assert len(negative_fixtures) >= 2, \
        f"Manifest must include at least 2 negative-class fixtures (sphere, torus). Found {len(negative_fixtures)}"
    assert any(
        fixture["fixture_type"] in {"box", "l_bracket"}
        and any(abs(float(value)) > 1e-9 for value in fixture["transform"]["rotate"])
        for fixture in fixtures
    ), "Manifest must include at least one rotated non-plate fixture"
    assert any(
        fixture["fixture_type"] == "box" and len(fixture.get("cutouts", [])) > 0
        for fixture in fixtures
    ), "Manifest must include at least one composite non-plate box fixture with cutouts"
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
        fixture["slots"]
        and fixture["linear_hole_patterns"]
        and fixture["grid_hole_patterns"]
        for fixture in plate_fixtures
    ), "Manifest must include at least one plate mixing slot + linear + grid patterns"
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
    assert any(
        float(fixture.get("edge_chamfer", 0.0)) > 0.0
        for fixture in plate_fixtures
    ), "Manifest must include at least one chamfered plate fixture"
    assert any(
        fixture.get("rectangular_cutouts")
        for fixture in plate_fixtures
    ), "Manifest must include at least one plate rectangular cutout fixture"
    assert any(
        fixture.get("rectangular_pockets")
        for fixture in plate_fixtures
    ), "Manifest must include at least one plate rectangular pocket fixture"
    assert any(
        fixture["fixture_type"] == "box" and float(fixture.get("edge_radius", 0.0)) > 0.0
        for fixture in fixtures
    ), "Manifest must include at least one rounded-edge box fixture"
    assert any(
        fixture["fixture_type"] == "box"
        and float(fixture.get("edge_radius", 0.0)) > 0.0
        and len(fixture.get("cutouts", [])) > 0
        for fixture in fixtures
    ), "Manifest must include at least one rounded-edge composite box fixture with cutouts"


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


def test_feature_fixture_generation_supports_transform_wrapper():
    rotated_fixture = validate_feature_fixture_spec(
        {
            "name": "plate_plain_rotated",
            "fixture_type": "plate",
            "output_filename": "plate_plain_rotated.scad",
            "plate_size": [20.0, 10.0, 2.0],
            "transform": {
                "rotate": [0.0, 0.0, 30.0],
                "translate": [0.0, 0.0, 0.0],
            },
            "expected_detection": {
                "plate_like_solid": False,
                "box_like_solid": False,
                "hole_count": 0,
                "slot_count": 0,
                "linear_pattern_count": 0,
                "grid_pattern_count": 0,
                "counterbore_count": 0,
            },
        }
    )

    scad = generate_feature_fixture_scad(rotated_fixture)

    assert "// transform: rotate=[0.000000, 0.000000, 30.000000]" in scad
    assert "rotate([0.000000, 0.000000, 30.000000]) {" in scad
    assert "difference() {" in scad


def test_feature_fixture_generation_supports_chamfered_plate():
    chamfered_fixture = validate_feature_fixture_spec(
        {
            "name": "plate_chamfered",
            "fixture_type": "plate",
            "output_filename": "plate_chamfered.scad",
            "plate_size": [20.0, 10.0, 2.0],
            "edge_chamfer": 1.0,
            "expected_detection": {
                "plate_like_solid": True,
                "box_like_solid": False,
                "hole_count": 0,
                "slot_count": 0,
                "linear_pattern_count": 0,
                "grid_pattern_count": 0,
                "counterbore_count": 0,
            },
        }
    )

    scad = generate_feature_fixture_scad(chamfered_fixture)

    assert "plate_edge_chamfer = 1.000000;" in scad
    assert "plate_top_scale = [0.900000, 0.800000];" in scad
    assert "linear_extrude(height=plate_size[2], scale=plate_top_scale)" in scad


def test_feature_fixture_generation_supports_rounded_box():
    rounded_fixture = validate_feature_fixture_spec(
        {
            "name": "box_rounded_edges",
            "fixture_type": "box",
            "output_filename": "box_rounded_edges.scad",
            "box_size": [24.0, 16.0, 12.0],
            "edge_radius": 2.0,
            "expected_detection": {
                "plate_like_solid": False,
                "box_like_solid": True,
                "hole_count": 0,
                "slot_count": 0,
                "linear_pattern_count": 0,
                "grid_pattern_count": 0,
                "counterbore_count": 0,
            },
        }
    )

    scad = generate_feature_fixture_scad(rounded_fixture)

    assert "edge_radius = 2.000000;" in scad
    assert "inner_box_size = [20.000000, 12.000000, 8.000000];" in scad
    assert "module rounded_box(size, r) {" in scad
    assert "minkowski()" in scad
    assert "rounded_box(inner_box_size, edge_radius);" in scad


def test_feature_fixture_generation_supports_rectangular_plate_features():
    plate_fixture = validate_feature_fixture_spec(
        {
            "name": "plate_rect_features",
            "fixture_type": "plate",
            "output_filename": "plate_rect_features.scad",
            "plate_size": [30.0, 20.0, 4.0],
            "rectangular_cutouts": [
                {"center": [0.0, -4.0], "size": [6.0, 4.0]},
            ],
            "rectangular_pockets": [
                {"center": [0.0, 5.0], "size": [8.0, 6.0], "depth": 1.5},
            ],
            "expected_detection": {
                "plate_like_solid": True,
                "box_like_solid": False,
                "hole_count": 0,
                "slot_count": 0,
                "rectangular_cutout_count": 1,
                "rectangular_pocket_count": 1,
                "linear_pattern_count": 0,
                "grid_pattern_count": 0,
                "counterbore_count": 0,
            },
        }
    )

    scad = generate_feature_fixture_scad(plate_fixture)

    assert "module rectangular_through_cutout(center, size_xy, plate_thickness)" in scad
    assert "module rectangular_top_pocket(center, size_xy, pocket_depth, plate_thickness)" in scad
    assert "rectangular_through_cutout([0.000000, -4.000000, 0.000000], [6.000000, 4.000000], 4.000000);" in scad
    assert "rectangular_top_pocket([0.000000, 5.000000, 0.000000], [8.000000, 6.000000], 1.500000, 4.000000);" in scad


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


def test_feature_fixture_preview_round_trip_detection(test_data_dir, test_output_dir):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, test_output_dir)

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for feature preview round-trip checks: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    for fixture in fixtures:
        if fixture["fixture_type"] not in ("plate", "box"):
            continue

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
        graph = build_feature_graph_for_stl(stl_path)
        preview_scad = emit_feature_graph_scad_preview(graph)

        expects_plate = fixture["expected_detection"].get("plate_like_solid", False)
        expects_box = fixture["expected_detection"].get("box_like_solid", False)

        if not expects_plate and not expects_box:
            assert preview_scad is None
            continue

        assert preview_scad is not None, f"{fixture['name']} expected a SCAD preview"
        if expects_plate:
            _assert_preview_named_variables(fixture, preview_scad)
        else:
            _assert_preview_named_variables_box(fixture, preview_scad)

        preview_path = test_output_dir / f"{fixture['name']}.preview.scad"
        preview_stl_path = test_output_dir / f"{fixture['name']}.preview.stl"
        preview_log_path = test_output_dir / f"{fixture['name']}.preview.log"
        preview_path.write_text(preview_scad, encoding="utf-8")

        preview_success = run_openscad(
            f"{fixture['name']}_preview",
            ["--render", "-o", str(preview_stl_path), str(preview_path)],
            str(preview_log_path),
            openscad_path,
        )

        assert preview_success, f"OpenSCAD preview render failed for {fixture['name']}"
        preview_graph = build_feature_graph_for_stl(preview_stl_path)

        feature_counts: dict[str, int] = {}
        for feature in preview_graph["features"]:
            feature_type = feature["type"]
            feature_counts[feature_type] = feature_counts.get(feature_type, 0) + 1

        if expects_plate:
            for feature_type, expected_count in iter_expected_feature_counts(fixture).items():
                assert (
                    feature_counts.get(feature_type, 0) == expected_count
                ), f"{fixture['name']} preview expected {expected_count} {feature_type} entries, got {feature_counts.get(feature_type, 0)}"
            _assert_fixture_dimensions(fixture, preview_graph["features"])
        else:
            # Box preview only guarantees the base shape; only check box_like_solid count.
            assert feature_counts.get("box_like_solid", 0) == 1, (
                f"{fixture['name']} box preview expected 1 box_like_solid, got {feature_counts.get('box_like_solid', 0)}"
            )


def test_feature_fixture_ambiguous_candidate_round_trip_ranking(
    test_data_dir,
    test_output_dir,
):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    fixture = next(
        item for item in fixtures if item["name"] == "box_hollow_ambiguous"
    )
    write_feature_fixture_library(manifest_path, test_output_dir)

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for ambiguous fixture checks: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    scad_path = test_output_dir / fixture["output_filename"]
    stl_path = test_output_dir / f"{Path(fixture['output_filename']).stem}.stl"
    log_path = test_output_dir / f"{fixture['name']}.candidate.log"

    success = run_openscad(
        fixture["name"],
        ["--render", "-o", str(stl_path), str(scad_path)],
        str(log_path),
        openscad_path,
    )

    assert success, f"OpenSCAD render failed for {fixture['name']}"
    graph = build_feature_graph_for_stl(stl_path)
    rankings = rank_feature_fixture_candidates(fixture, graph)

    assert rankings[0]["name"] == fixture["candidates"][0]["name"]
    assert rankings[0]["exact_match"] is True
    assert rankings[0]["candidate_confidence"] >= 0.70
    assert rankings[1]["name"] == fixture["candidates"][1]["name"]
    assert rankings[1]["exact_match"] is False


def test_feature_fixture_negative_class_detection(test_data_dir, test_output_dir):
    """Validate that negative-class fixtures (sphere, torus) don't produce mechanical features."""
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, test_output_dir)

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for negative fixture checks: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    negative_fixtures = [
        fixture
        for fixture in fixtures
        if fixture["fixture_type"] in {"sphere", "torus"}
    ]
    assert negative_fixtures, "No negative-class fixtures found in manifest"

    for fixture in negative_fixtures:
        scad_path = test_output_dir / fixture["output_filename"]
        stl_path = test_output_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = test_output_dir / f"{fixture['name']}.negative.log"

        success = run_openscad(
            fixture["name"],
            ["--render", "-o", str(stl_path), str(scad_path)],
            str(log_path),
            openscad_path,
        )

        assert success, f"OpenSCAD render failed for {fixture['name']}"
        graph = build_feature_graph_for_stl(stl_path)

        high_confidence_features = [
            feature
            for feature in graph["features"]
            if float(feature.get("confidence", 0.0)) >= 0.70
            and feature["type"] in {"plate_like_solid", "box_like_solid"}
        ]

        assert (
            not high_confidence_features
        ), f"{fixture['name']} should not produce high-confidence plate/box features, but got {[f['type'] for f in high_confidence_features]}"
