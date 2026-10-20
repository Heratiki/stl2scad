"""
Legacy feature-graph round-trip tests over the feature fixtures.

Moved from tests/test_feature_fixtures.py by T-004. The byte-exact
regeneration and roadmap-coverage tests stay there; the segmentation
retarget of the round-trip is T-009.
"""

import contextlib
import os
from math import dist, isclose
from pathlib import Path

import pytest

from stl2scad.core.openscad.runner import get_openscad_path, run_openscad
from stl2scad.core.feature_fixtures import (
    generate_feature_fixture_scad,
    iter_expected_feature_counts,
    load_feature_fixture_manifest,
    rank_feature_fixture_candidates,
    validate_feature_fixture_spec,
    write_feature_fixture_library,
)
from stl2scad.legacy.feature_graph import (
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

# T-003: the whole-mesh revolve detector is archived behind
# DetectorConfig.enable_revolve_detection (default False). Fixtures of type
# "revolve" are no longer detected by default, so they are expected failures.
# Non-revolve fixtures whose detection changed are listed here by name.
_REVOLVE_ARCHIVED_REASON = "revolve detector archived (T-003)"
_REVOLVE_ARCHIVED_NON_REVOLVE_FIXTURES: frozenset = frozenset(
    {
        # Expect a revolve_solid entry that is no longer produced.
        "cylinder_plain",
        "cylinder_short_disk",
        "cylinder_x_axis",
        "cylinder_y_axis",
        "cylinder_narrow_tall",
        # With revolve off nothing suppresses the box check: got a box_like_solid.
        "cylinder_large_diameter",
        # With revolve off nothing suppresses linear-extrude: got a linear_extrude_solid.
        "prism_octagon",
    }
)


def _is_revolve_archived_fixture(fixture) -> bool:
    return (
        fixture["fixture_type"] == "revolve"
        or fixture["name"] in _REVOLVE_ARCHIVED_NON_REVOLVE_FIXTURES
    )


@contextlib.contextmanager
def _xfail_if_revolve_archived(fixture, archived_failures):
    """Per-fixture xfail(strict=False) inside a fixture loop.

    A failing archived fixture is recorded and the loop continues, so passing
    fixtures stay checked. An archived fixture that passes is not an error
    (strict=False semantics).
    """
    if not _is_revolve_archived_fixture(fixture):
        yield
        return
    try:
        yield
    except AssertionError as exc:
        archived_failures.append(f"{fixture['name']}: {exc}")


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
    if best.get("detected_via") != "rotated_plate":
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
    expected_size = fixture.get("box_size", fixture.get("size"))
    assert expected_size is not None, f"{fixture['name']} expected box dimensions in fixture"
    if best.get("detected_via") == "rotated_box":
        actual_sorted = sorted(float(v) for v in best["size"])
        expected_sorted = sorted(float(v) for v in expected_size)
        for i, (actual, expected) in enumerate(zip(actual_sorted, expected_sorted)):
            _assert_close(actual, expected, _SIZE_TOL, f"{fixture['name']} box size dim {i}")
    else:
        _assert_axis_aligned_size(best["size"], expected_size, fixture["name"], "box size")


def _assert_plate_hole_dimensions(fixture, features):
    expected_holes = list(_iter_plate_fixture_holes(fixture))
    # For rotated plates, holes are tagged axis="local_n" in the local plate-normal frame.
    # Compare local_center[:2] (u, v) against fixture-specified centers.
    is_rotated = any(
        f.get("type") == "plate_like_solid" and f.get("detected_via") == "rotated_plate"
        for f in features
        if float(f.get("confidence", 0.0)) >= 0.70
    )
    if is_rotated:
        holes = [
            feature
            for feature in features
            if feature.get("type") == "hole_like_cutout"
            and feature.get("detected_via") == "rotated_plate_local_frame"
        ]
        assert len(holes) == len(expected_holes)
        unmatched = list(holes)
        half_u = float(fixture["plate_size"][0]) * 0.5
        half_v = float(fixture["plate_size"][1]) * 0.5
        for expected_center, expected_diameter in expected_holes:
            expected_local_center = [
                float(expected_center[0]) + half_u,
                float(expected_center[1]) + half_v,
            ]
            match = _pop_best_match(
                unmatched,
                lambda candidate: dist(candidate["local_center"][:2], expected_local_center),
            )
            assert match is not None, f"{fixture['name']} missing expected rotated-plate hole"
            center_error = dist(match["local_center"][:2], expected_local_center)
            assert center_error <= _CENTER_TOL, (
                f"{fixture['name']} rotated hole local-center mismatch: "
                f"expected {expected_local_center}, got {match['local_center'][:2]}"
            )
            _assert_close(
                match["diameter"],
                expected_diameter,
                _DIAMETER_TOL,
                f"{fixture['name']} hole diameter",
            )
        return

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
    is_rotated = any(
        f.get("type") == "box_like_solid" and f.get("detected_via") == "rotated_box"
        for f in features
        if float(f.get("confidence", 0.0)) >= 0.70
    )
    if is_rotated:
        holes = [
            feature
            for feature in features
            if feature.get("type") == "hole_like_cutout"
            and feature.get("detected_via") == "rotated_box_local_frame"
        ]
        assert len(holes) == len(expected_holes)

        unmatched = list(holes)
        for expected in expected_holes:
            match = _pop_best_match(
                unmatched,
                lambda candidate: abs(
                    float(candidate.get("diameter", 0.0)) - float(expected["diameter"])
                ),
            )
            assert match is not None, f"{fixture['name']} missing expected rotated-box hole"
            assert str(match.get("axis")) == "local_n"
            assert "local_center" in match
            _assert_close(
                match["diameter"],
                expected["diameter"],
                _DIAMETER_TOL,
                f"{fixture['name']} hole diameter",
            )
        return

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

    # For rotated plates, slots are tagged detected_via="rotated_plate_local_frame".
    # Compare local_start/local_end[:2] against fixture-specified start/end.
    is_rotated = any(
        f.get("type") == "plate_like_solid" and f.get("detected_via") == "rotated_plate"
        for f in features
        if float(f.get("confidence", 0.0)) >= 0.70
    )
    if is_rotated:
        slots = [
            feature
            for feature in features
            if feature.get("type") == "slot_like_cutout"
            and feature.get("detected_via") == "rotated_plate_local_frame"
        ]
        assert len(slots) == len(expected_slots), (
            f"{fixture['name']} expected {len(expected_slots)} rotated-plate slots, "
            f"got {len(slots)}"
        )
        if not expected_slots:
            return
        half_u = float(fixture["plate_size"][0]) * 0.5
        half_v = float(fixture["plate_size"][1]) * 0.5
        unmatched = list(slots)
        for expected in expected_slots:
            expected_local_start = [
                float(expected["start"][0]) + half_u,
                float(expected["start"][1]) + half_v,
            ]
            expected_local_end = [
                float(expected["end"][0]) + half_u,
                float(expected["end"][1]) + half_v,
            ]
            match = _pop_best_match(
                unmatched,
                lambda candidate: min(
                    dist(candidate["local_start"][:2], expected_local_start)
                    + dist(candidate["local_end"][:2], expected_local_end),
                    dist(candidate["local_start"][:2], expected_local_end)
                    + dist(candidate["local_end"][:2], expected_local_start),
                ),
            )
            assert match is not None, f"{fixture['name']} missing expected rotated-plate slot"
            direct_error = dist(match["local_start"][:2], expected_local_start) + dist(
                match["local_end"][:2], expected_local_end
            )
            swapped_error = dist(match["local_start"][:2], expected_local_end) + dist(
                match["local_end"][:2], expected_local_start
            )
            assert min(direct_error, swapped_error) <= _CENTER_TOL * 2.0, (
                f"{fixture['name']} rotated-plate slot local position mismatch"
            )
            _assert_close(
                match["width"],
                expected["width"],
                _DIAMETER_TOL,
                f"{fixture['name']} slot width",
            )
        return

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

    # For rotated plates, patterns carry axis="local_n" instead of "z".
    # Just verify the count; detailed geometry checks are deferred.
    is_rotated = any(
        f.get("type") == "plate_like_solid" and f.get("detected_via") == "rotated_plate"
        for f in features
        if float(f.get("confidence", 0.0)) >= 0.70
    )
    if is_rotated:
        rotated_patterns = [
            feature
            for feature in features
            if feature.get("type") == "linear_hole_pattern"
            and feature.get("detected_via") == "rotated_plate_local_frame"
        ]
        total_needed = len(explicit_patterns) + len(inferred_patterns)
        assert len(rotated_patterns) >= total_needed, (
            f"{fixture['name']} expected {total_needed} rotated-plate linear patterns, "
            f"got {len(rotated_patterns)}"
        )
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
        if len(centers) < 2:
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
        if len(ordered) > 2:
            if any(
                abs((ordered[index][0] - ordered[index - 1][0]) - step[0]) > 1e-6
                or abs((ordered[index][1] - ordered[index - 1][1]) - step[1]) > 1e-6
                for index in range(2, len(ordered))
            ):
                continue
        inferred_patterns.append(
            {
                "origin": ordered[0],
                "step": step,
                "count": len(ordered),
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


def _assert_linear_extrude_dimensions(fixture, features):
    expected_le = bool(fixture["expected_detection"].get("linear_extrude_solid", False))
    le_features = [
        f for f in features
        if f.get("type") == "linear_extrude_solid"
        and float(f.get("confidence", 0.0)) >= 0.70
    ]
    if not expected_le:
        assert not le_features, (
            f"{fixture['name']} did not expect linear_extrude_solid but got {len(le_features)}"
        )
        return
    assert le_features, f"{fixture['name']} expected linear_extrude_solid but none found"
    best = max(le_features, key=lambda f: float(f.get("confidence", 0.0)))
    if "height" in fixture:
        _assert_close(
            float(best["height"]),
            float(fixture["height"]),
            _SIZE_TOL,
            f"{fixture['name']} linear extrude height",
        )


def _assert_fixture_dimensions(fixture, features):
    if fixture["fixture_type"] == "non_revolve":
        return
    if fixture["fixture_type"] == "revolve":
        revolves = [
            feature
            for feature in features
            if feature.get("type") == "revolve_solid"
            and float(feature.get("confidence", 0.0)) >= 0.70
        ]
        assert len(revolves) == 1
        detected = revolves[0]
        expected_profile = fixture["profile"]
        expected_min_r = min(float(point[0]) for point in expected_profile)
        expected_max_r = max(float(point[0]) for point in expected_profile)
        detected_max_r = max(float(point[0]) for point in detected["profile"])
        assert abs(detected_max_r - expected_max_r) / expected_max_r < 0.05

        # Annular revolves are allowed in Phase 1.6 and carry explicit inner/outer radii.
        if expected_min_r > 1e-6:
            assert detected.get("detected_via") == "annular_revolve"
            detected_inner = float(detected.get("inner_r", min(float(p[0]) for p in detected["profile"])))
            detected_outer = float(detected.get("outer_r", detected_max_r))
            assert abs(detected_inner - expected_min_r) / max(expected_min_r, 1e-6) < 0.20
            assert abs(detected_outer - expected_max_r) / max(expected_max_r, 1e-6) < 0.05
            return

        assert abs(len(detected["profile"]) - len(expected_profile)) <= max(
            2,
            len(expected_profile) // 4,
        )
        return

    _assert_plate_dimensions(fixture, features)
    _assert_box_dimensions(fixture, features)
    _assert_linear_extrude_dimensions(fixture, features)
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

    # Rotated-plate slots are emitted with local-frame variables; the standard
    # slot_0_* names are only present for axis-aligned plate previews.
    _has_rotation_for_slots = bool(
        fixture.get("transform")
        and any(
            abs(v) > 1e-6
            for v in fixture.get("transform", {}).get("rotate", [0.0, 0.0, 0.0])
        )
    )
    if fixture.get("slots") and not _has_rotation_for_slots:
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

    # Rotated-plate fixtures detect patterns in local-frame; the SCAD emitter
    # does not yet emit hole_pattern_* variables for those.  Only check the
    # pattern preview variables for axis-aligned (non-rotated) plate fixtures.
    _has_rotation = bool(
        fixture.get("transform")
        and any(
            abs(v) > 1e-6
            for v in fixture.get("transform", {}).get("rotate", [0.0, 0.0, 0.0])
        )
    )
    if not _has_rotation and (
        fixture.get("linear_hole_patterns")
        or int(fixture["expected_detection"].get("linear_pattern_count", 0)) > 0
    ):
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
        # Rotated-plate local-frame previews use hole_local_* variable names.
        if "hole_local_0_center = [" in preview_scad:
            assert "hole_local_0_diameter = " in preview_scad
        else:
            assert "hole_0_center = [" in preview_scad
            assert "hole_0_diameter = " in preview_scad


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

    archived_failures: list[str] = []
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

        with _xfail_if_revolve_archived(fixture, archived_failures):
            for feature_type, expected_count in iter_expected_feature_counts(fixture).items():
                assert (
                    feature_counts.get(feature_type, 0) == expected_count
                ), f"{fixture['name']} expected {expected_count} {feature_type} entries, got {feature_counts.get(feature_type, 0)}"

            _assert_fixture_dimensions(fixture, graph["features"])

    if archived_failures:
        pytest.xfail(f"{_REVOLVE_ARCHIVED_REASON}: " + "; ".join(archived_failures))


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


@pytest.mark.xfail(strict=False, reason=_REVOLVE_ARCHIVED_REASON)
def test_revolve_fixture_exposes_confidence_components(test_data_dir, test_output_dir):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, test_output_dir)

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for revolve fixture checks: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    revolve_fixtures = [fixture for fixture in fixtures if fixture["fixture_type"] == "revolve"]
    assert revolve_fixtures
    for fixture in revolve_fixtures:
        scad_path = test_output_dir / fixture["output_filename"]
        stl_path = test_output_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = test_output_dir / f"{fixture['name']}.revolve.log"
        assert run_openscad(
            fixture["name"],
            ["--render", "-o", str(stl_path), str(scad_path)],
            str(log_path),
            openscad_path,
        )
        graph = build_feature_graph_for_stl(stl_path)
        revolve = next(
            (feature for feature in graph["features"] if feature["type"] == "revolve_solid"),
            None,
        )
        assert revolve is not None, f"{fixture['name']} expected revolve_solid"
        components = revolve["confidence_components"]
        for key in (
            "axis_quality",
            "cross_slice_consistency",
            "normal_field_agreement",
            "profile_validity",
        ):
            assert key in components
            assert 0.0 <= float(components[key]) <= 1.0


@pytest.mark.xfail(strict=False, reason=_REVOLVE_ARCHIVED_REASON)
def test_revolve_fixture_preview_round_trip(test_data_dir, test_output_dir):
    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, test_output_dir)

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for revolve preview checks: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    for fixture in fixtures:
        if fixture["fixture_type"] != "revolve":
            continue
        scad_path = test_output_dir / fixture["output_filename"]
        stl_path = test_output_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = test_output_dir / f"{fixture['name']}.log"
        assert run_openscad(
            fixture["name"],
            ["--render", "-o", str(stl_path), str(scad_path)],
            str(log_path),
            openscad_path,
        )

        graph = build_feature_graph_for_stl(stl_path)
        preview = emit_feature_graph_scad_preview(graph)
        assert preview is not None, f"{fixture['name']} expected a preview"
        # Phase 2 may upgrade revolve previews to native primitives.
        assert any(token in preview for token in ("rotate_extrude", "cylinder(", "sphere(", "difference()"))

        preview_scad = test_output_dir / f"{fixture['name']}.preview.scad"
        preview_stl = test_output_dir / f"{fixture['name']}.preview.stl"
        preview_log = test_output_dir / f"{fixture['name']}.preview.log"
        preview_scad.write_text(preview, encoding="utf-8")
        assert run_openscad(
            f"{fixture['name']}_preview",
            ["--render", "-o", str(preview_stl), str(preview_scad)],
            str(preview_log),
            openscad_path,
        )
        preview_graph = build_feature_graph_for_stl(preview_stl)
        assert any(
            feature["type"] in {"revolve_solid", "cylinder_like_solid"}
            for feature in preview_graph["features"]
        )


@pytest.mark.xfail(strict=False, reason=_REVOLVE_ARCHIVED_REASON)
def test_revolve_fixture_phase2_primitive_upgrade(test_data_dir, test_output_dir):
    """Phase 2 acceptance: revolve fixtures with phase2_expected_primitive must produce
    a matching primitive_upgrade in the feature graph and emit the corresponding
    native SCAD primitive (cylinder / cone cylinder(r1=...) / sphere)."""
    import json

    manifest_path = test_data_dir / "feature_fixtures_manifest.json"
    raw_fixtures = json.loads(manifest_path.read_text(encoding="utf-8"))["fixtures"]
    phase2_fixtures = [f for f in raw_fixtures if f.get("phase2_expected_primitive")]
    assert phase2_fixtures, "No fixtures with phase2_expected_primitive found in manifest"

    write_feature_fixture_library(manifest_path, test_output_dir)

    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for Phase 2 revolve checks: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")

    # Token that must appear in the preview SCAD for each primitive kind.
    _primitive_tokens = {
        "cylinder": "cylinder(r=",
        "cone": "cylinder(r1=",
        "sphere": "sphere(",
    }

    for raw_fixture in phase2_fixtures:
        name = raw_fixture["name"]
        expected_primitive = raw_fixture["phase2_expected_primitive"]
        assert expected_primitive in _primitive_tokens, (
            f"{name}: unknown phase2_expected_primitive '{expected_primitive}'"
        )

        scad_path = test_output_dir / raw_fixture["output_filename"]
        stl_path = test_output_dir / f"{Path(raw_fixture['output_filename']).stem}.stl"
        log_path = test_output_dir / f"{name}.phase2.log"

        assert run_openscad(
            name,
            ["--render", "-o", str(stl_path), str(scad_path)],
            str(log_path),
            openscad_path,
        ), f"OpenSCAD render failed for {name}"

        graph = build_feature_graph_for_stl(stl_path)
        revolve = next(
            (f for f in graph["features"] if f["type"] == "revolve_solid"),
            None,
        )
        assert revolve is not None, f"{name}: expected revolve_solid in feature graph"

        upgrade = revolve.get("primitive_upgrade")
        assert upgrade is not None, (
            f"{name}: revolve_solid has no primitive_upgrade; Phase 2 classification failed"
        )
        assert upgrade["type"] == expected_primitive, (
            f"{name}: expected primitive_upgrade.type='{expected_primitive}', "
            f"got '{upgrade['type']}'"
        )

        preview = emit_feature_graph_scad_preview(graph)
        assert preview is not None, f"{name}: SCAD preview is None"
        token = _primitive_tokens[expected_primitive]
        assert token in preview, (
            f"{name}: expected '{token}' in SCAD preview for {expected_primitive} upgrade; "
            f"preview starts with:\n{preview[:400]}"
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
