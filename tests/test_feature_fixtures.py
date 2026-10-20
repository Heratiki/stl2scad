"""
Tests for manifest-driven OpenSCAD feature fixtures.
"""

import pytest

from stl2scad.core.feature_fixtures import (
    generate_feature_fixture_scad,
    iter_expected_feature_counts,
    load_feature_fixture_manifest,
    rank_feature_fixture_candidates,
    validate_feature_fixture_spec,
    write_feature_fixture_library,
)


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

    assert {"box", "l_bracket", "sphere", "torus", "revolve", "non_revolve"}.issubset(fixture_types), \
        f"Manifest must include box, l_bracket, sphere, torus, revolve, and non_revolve fixtures. Found: {fixture_types}"
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


def test_fixture_type_revolve_accepts_profile_spec():
    from stl2scad.core.feature_fixtures import validate_feature_fixture_spec

    spec = {
        "name": "revolve_test",
        "fixture_type": "revolve",
        "output_filename": "revolve_test.scad",
        "profile": [[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]],
        "axis": "z",
        "expected_detection": {
            "revolve_solid": True,
            "plate_like_solid": False,
            "box_like_solid": False,
            "cylinder_like_solid": False,
            "hole_count": 0, "slot_count": 0,
            "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
        },
    }
    result = validate_feature_fixture_spec(spec, schema_version=1)
    assert result["fixture_type"] == "revolve"
    assert len(result["profile"]) == 4


def test_fixture_type_non_revolve_accepts_rejection_gate():
    from stl2scad.core.feature_fixtures import validate_feature_fixture_spec

    spec = {
        "name": "non_revolve_test",
        "fixture_type": "non_revolve",
        "output_filename": "non_revolve_test.scad",
        "shape": "cube",
        "size": [10.0, 10.0, 10.0],
        "expected_rejection_gate": "cross_slice_consistency",
        "expected_detection": {
            "revolve_solid": False,
            "plate_like_solid": False,
            "box_like_solid": True,
            "hole_count": 0, "slot_count": 0,
            "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
        },
    }
    result = validate_feature_fixture_spec(spec, schema_version=1)
    assert result["fixture_type"] == "non_revolve"
    assert result["expected_rejection_gate"] == "cross_slice_consistency"


def test_generate_revolve_fixture_scad_contains_rotate_extrude():
    from stl2scad.core.feature_fixtures import generate_feature_fixture_scad

    fixture = {
        "name": "revolve_test",
        "fixture_type": "revolve",
        "output_filename": "revolve_test.scad",
        "profile": [[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]],
        "axis": "z",
        "expected_detection": {
            "revolve_solid": True, "plate_like_solid": False, "box_like_solid": False,
            "hole_count": 0, "slot_count": 0,
            "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
        },
    }
    scad = generate_feature_fixture_scad(fixture)
    assert "rotate_extrude" in scad
    assert "polygon" in scad
    assert "5" in scad and "10" in scad


def test_generate_non_revolve_cube_scad_contains_cube():
    from stl2scad.core.feature_fixtures import generate_feature_fixture_scad

    fixture = {
        "name": "non_revolve_cube",
        "fixture_type": "non_revolve",
        "output_filename": "non_revolve_cube.scad",
        "shape": "cube",
        "size": [10.0, 10.0, 10.0],
        "expected_detection": {
            "revolve_solid": False, "box_like_solid": True, "plate_like_solid": False,
            "hole_count": 0, "slot_count": 0,
            "linear_pattern_count": 0, "grid_pattern_count": 0, "counterbore_count": 0
        },
    }
    scad = generate_feature_fixture_scad(fixture)
    assert "cube" in scad
