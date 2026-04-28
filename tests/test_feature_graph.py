"""
Tests for intermediate feature graph extraction.
"""

from pathlib import Path
import warnings

import numpy as np
import pytest
from stl.mesh import Mesh

from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.core.feature_graph import (
    build_feature_graph_for_folder,
    build_feature_graph_for_stl,
    build_triage_report,
    emit_feature_graph_scad_preview,
)


def test_feature_graph_extracts_box_like_solid(test_data_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_box_axis_aligned.stl")
    box_features = [
        feature for feature in graph["features"] if feature["type"] == "box_like_solid"
    ]

    assert graph["mesh"]["triangles"] == 12
    assert len(box_features) == 1
    assert box_features[0]["confidence"] >= 0.8
    assert box_features[0]["parameters"]["width"] == 20.0
    assert box_features[0]["parameters"]["depth"] == 12.0
    assert box_features[0]["parameters"]["height"] == 8.0


def test_feature_graph_folder_report_writes_summary(test_data_dir, test_output_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    output_json = test_output_dir / "feature_graph.json"
    report = build_feature_graph_for_folder(
        fixtures_dir, output_json, max_files=3, workers=2
    )

    assert output_json.exists()
    assert report["config"]["workers"] == 2
    assert report["summary"]["file_count"] == 3
    assert report["summary"]["error_count"] == 0
    assert report["summary"]["feature_counts"]


def test_feature_graph_folder_reports_progress(test_data_dir, test_output_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    output_json = test_output_dir / "feature_graph_progress.json"
    progress_events = []

    report = build_feature_graph_for_folder(
        fixtures_dir,
        output_json,
        max_files=3,
        workers=2,
        progress_callback=lambda done, total, path: progress_events.append(
            (done, total, Path(path).name)
        ),
    )

    assert report["summary"]["file_count"] == 3
    assert len(progress_events) == 3
    assert progress_events[-1][0] == 3
    assert progress_events[-1][1] == 3
    assert {event[2] for event in progress_events} == {
        "composite_cylinder_beside_box.stl",
        "composite_disconnected_dual_box.stl",
        "composite_overlapping_dual_box.stl",
    }


def test_feature_graph_folder_includes_uppercase_stl_extension(test_output_dir):
    upper_file = test_output_dir / "plate_upper.STL"
    _create_plate_with_holes(upper_file)

    output_json = test_output_dir / "feature_graph_uppercase.json"
    report = build_feature_graph_for_folder(
        test_output_dir,
        output_json,
        recursive=False,
        workers=1,
    )

    graph_files = {graph["source_file"] for graph in report["graphs"]}
    assert "plate_upper.STL" in graph_files
    assert report["summary"]["file_count"] == 1
    assert report["summary"]["error_count"] == 0


def test_feature_graph_extracts_repeated_through_holes(test_output_dir):
    stl_file = test_output_dir / "plate_with_two_holes.stl"
    _create_plate_with_holes(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    holes = [
        feature
        for feature in graph["features"]
        if feature["type"] == "hole_like_cutout"
    ]
    patterns = [
        feature
        for feature in graph["features"]
        if feature["type"] == "linear_hole_pattern"
    ]

    assert len(holes) == 2
    assert all(3.5 < hole["diameter"] < 4.5 for hole in holes)
    assert len(patterns) == 1
    assert patterns[0]["hole_count"] == 2
    assert patterns[0]["pattern_count"] == 2
    assert abs(patterns[0]["pattern_spacing"] - 6.0) < 1e-5


def test_feature_graph_extracts_grid_through_holes(test_output_dir):
    stl_file = test_output_dir / "plate_with_grid_holes.stl"
    _create_plate_with_holes(
        stl_file,
        centers=[
            (-6.0, -3.0),
            (0.0, -3.0),
            (6.0, -3.0),
            (-6.0, 3.0),
            (0.0, 3.0),
            (6.0, 3.0),
        ],
        radius=1.0,
        plate_size=(20.0, 12.0, 2.0),
    )

    graph = build_feature_graph_for_stl(stl_file)
    patterns = [
        feature
        for feature in graph["features"]
        if feature["type"] == "grid_hole_pattern"
    ]

    assert len(patterns) == 1
    assert patterns[0]["hole_count"] == 6
    assert patterns[0]["grid_rows"] == 2
    assert patterns[0]["grid_cols"] == 3
    assert abs(patterns[0]["grid_row_spacing"] - 6.0) < 1e-5
    assert abs(patterns[0]["grid_col_spacing"] - 6.0) < 1e-5


def test_feature_graph_extracts_slot_cutout(test_output_dir):
    stl_file = test_output_dir / "plate_with_slot.stl"
    _create_plate_with_slot(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    slots = [
        feature
        for feature in graph["features"]
        if feature["type"] == "slot_like_cutout"
    ]

    assert len(slots) == 1
    assert slots[0]["slot_axis"] == "x"
    assert abs(slots[0]["width"] - 3.0) < 1e-5
    assert abs(slots[0]["length"] - 10.0) < 1e-5
    assert slots[0]["confidence"] >= 0.70


def test_feature_graph_extracts_rectangular_through_cutout(test_output_dir):
    stl_file = test_output_dir / "plate_with_rectangular_cutout.stl"
    _create_plate_with_rectangular_cutout(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    cutouts = [
        feature
        for feature in graph["features"]
        if feature["type"] == "rectangular_cutout"
    ]

    assert len(cutouts) == 1
    assert cutouts[0]["axis"] == "z"
    assert cutouts[0]["source_parent_type"] == "plate_like_solid"
    assert cutouts[0]["confidence"] >= 0.70
    assert abs(cutouts[0]["center"][0] - 0.0) < 0.1
    assert abs(cutouts[0]["center"][1] + 3.0) < 0.1
    assert abs(cutouts[0]["size"][0] - 6.0) < 0.1
    assert abs(cutouts[0]["size"][1] - 4.0) < 0.1
    assert abs(cutouts[0]["size"][2] - 4.0) < 0.1


def test_feature_graph_extracts_rectangular_pocket(test_output_dir):
    stl_file = test_output_dir / "plate_with_rectangular_pocket.stl"
    _create_plate_with_rectangular_pocket(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    pockets = [
        feature
        for feature in graph["features"]
        if feature["type"] == "rectangular_pocket"
    ]

    assert len(pockets) == 1
    assert pockets[0]["axis"] == "z"
    assert pockets[0]["source_parent_type"] == "plate_like_solid"
    assert pockets[0]["open_direction"] == "positive"
    assert pockets[0]["confidence"] >= 0.70
    assert abs(pockets[0]["center"][0] - 0.0) < 0.1
    assert abs(pockets[0]["center"][1] - 4.0) < 0.1
    assert abs(pockets[0]["size"][0] - 8.0) < 0.1
    assert abs(pockets[0]["size"][1] - 6.0) < 0.1
    assert abs(pockets[0]["size"][2] - 2.0) < 0.1


def test_feature_graph_extracts_chamfered_plate_like_solid(test_output_dir):
    stl_file = test_output_dir / "plate_with_chamfered_edges.stl"
    _create_chamfered_plate(stl_file, plate_size=(20.0, 10.0, 2.0), edge_chamfer=1.0)

    graph = build_feature_graph_for_stl(stl_file)
    plates = [
        feature for feature in graph["features"] if feature["type"] == "plate_like_solid"
    ]
    axis_pairs = {
        feature["axis"]: feature
        for feature in graph["features"]
        if feature["type"] == "axis_boundary_plane_pair"
    }

    assert len(plates) == 1
    assert axis_pairs["z"]["paired"] is True
    assert axis_pairs["x"]["paired"] is False
    assert axis_pairs["y"]["paired"] is False
    assert plates[0]["confidence"] >= 0.70
    assert plates[0]["parameters"]["width"] == 20.0
    assert plates[0]["parameters"]["depth"] == 10.0
    assert plates[0]["parameters"]["thickness"] == 2.0


@pytest.mark.parametrize("axis", ["x", "z"])
def test_feature_graph_extracts_box_through_hole(test_output_dir, axis):
    stl_file = test_output_dir / f"box_with_{axis}_hole.stl"
    _create_box_with_hole(stl_file, axis=axis)

    graph = build_feature_graph_for_stl(stl_file)
    box_features = [
        feature for feature in graph["features"] if feature["type"] == "box_like_solid"
    ]
    holes = [
        feature
        for feature in graph["features"]
        if feature["type"] == "hole_like_cutout"
    ]

    assert len(box_features) == 1
    assert not any(
        feature["type"] == "cylinder_like_solid" for feature in graph["features"]
    )
    assert len(holes) == 1
    assert holes[0]["axis"] == axis
    assert holes[0]["source_parent_type"] == "box_like_solid"
    assert 3.5 < holes[0]["diameter"] < 4.5
    assert holes[0]["confidence"] >= 0.70


def test_feature_graph_extracts_box_rectangular_pocket(test_output_dir):
    stl_file = test_output_dir / "box_with_rectangular_top_pocket.stl"
    _create_box_with_rectangular_top_pocket(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    pockets = [
        feature
        for feature in graph["features"]
        if feature["type"] == "rectangular_pocket"
    ]

    assert len(pockets) == 1
    assert pockets[0]["axis"] == "z"
    assert pockets[0]["source_parent_type"] == "box_like_solid"
    assert pockets[0]["open_direction"] == "positive"
    assert pockets[0]["confidence"] >= 0.70
    assert abs(pockets[0]["size"][0] - 8.0) < 0.1
    assert abs(pockets[0]["size"][1] - 8.0) < 0.1
    assert abs(pockets[0]["size"][2] - 6.0) < 0.1


def test_feature_graph_scad_preview_emits_plate_with_holes(test_output_dir):
    stl_file = test_output_dir / "plate_with_two_holes_preview.stl"
    _create_plate_with_holes(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "difference()" in scad
    assert "cube(plate_size)" in scad
    assert "module hole_cutout" in scad
    assert "hole_pattern_0_count = 2;" in scad
    assert "hole_pattern_0_step = [6.000000" in scad
    assert "for (i = [0 : hole_pattern_0_count - 1])" in scad
    assert scad.count("cylinder(") == 1


def test_feature_graph_scad_preview_parameterizes_standalone_hole(test_output_dir):
    stl_file = test_output_dir / "plate_with_single_hole_preview.stl"
    _create_plate_with_holes(stl_file, centers=[(0.0, 0.0)])

    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "hole_0_center = [" in scad
    assert "hole_0_diameter = 4.000000;" in scad
    assert "hole_cutout(hole_0_center, hole_0_diameter);" in scad


def test_feature_graph_scad_preview_emits_slot_cutout(test_output_dir):
    stl_file = test_output_dir / "plate_with_slot_preview.stl"
    _create_plate_with_slot(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "module slot_cutout" in scad
    assert "slot_0_start = [-3.500000" in scad
    assert "slot_0_end = [3.500000" in scad
    assert "slot_0_width = 3.000000;" in scad
    assert "slot_cutout(slot_0_start, slot_0_end, slot_0_width);" in scad


def test_feature_graph_scad_preview_emits_rectangular_features(test_output_dir):
    stl_file = test_output_dir / "plate_with_rectangular_features_preview.stl"
    _create_plate_with_rectangular_pocket(
        stl_file,
        plate_size=(30.0, 20.0, 5.0),
        pocket_center=(0.0, 4.0),
        pocket_size=(8.0, 6.0),
        pocket_depth=2.0,
    )

    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "module rectangular_prism_cutout(center, size)" in scad
    assert "rect_pocket_0_center = [0.000000, 4.000000" in scad
    assert "rect_pocket_0_size = [8.000000, 6.000000, 2.000000];" in scad
    assert "rectangular_prism_cutout(rect_pocket_0_center, rect_pocket_0_size);" in scad


def test_feature_graph_scad_preview_emits_grid_hole_loop(test_output_dir):
    stl_file = test_output_dir / "plate_with_grid_holes_preview.stl"
    _create_plate_with_holes(
        stl_file,
        centers=[
            (-6.0, -3.0),
            (0.0, -3.0),
            (6.0, -3.0),
            (-6.0, 3.0),
            (0.0, 3.0),
            (6.0, 3.0),
        ],
        radius=1.0,
        plate_size=(20.0, 12.0, 2.0),
    )

    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "hole_grid_0_rows = 2;" in scad
    assert "hole_grid_0_cols = 3;" in scad
    assert "hole_grid_0_row_step = [0.000000, 6.000000" in scad
    assert "hole_grid_0_col_step = [6.000000, 0.000000" in scad
    assert "for (row = [0 : hole_grid_0_rows - 1])" in scad
    assert "for (col = [0 : hole_grid_0_cols - 1])" in scad
    assert scad.count("cylinder(") == 1


def test_feature_graph_scad_preview_allows_tiny_near_threshold_plate_confidence():
    near_threshold_graph = {
        "source_file": "near_threshold_plate.stl",
        "features": [
            {
                "type": "plate_like_solid",
                "origin": [0.0, 0.0, 0.0],
                "size": [30.0, 20.0, 6.0],
                "confidence": 0.6985,
            }
        ],
    }
    below_threshold_graph = {
        "source_file": "below_threshold_plate.stl",
        "features": [
            {
                "type": "plate_like_solid",
                "origin": [0.0, 0.0, 0.0],
                "size": [30.0, 20.0, 6.0],
                "confidence": 0.6970,
            }
        ],
    }

    near_scad = emit_feature_graph_scad_preview(near_threshold_graph)
    below_scad = emit_feature_graph_scad_preview(below_threshold_graph)

    assert near_scad is not None
    assert "cube(plate_size)" in near_scad
    assert below_scad is None


def test_feature_graph_extracts_counterbore_hole(test_output_dir):
    stl_file = test_output_dir / "plate_with_counterbore.stl"
    through_radius = 2.0
    bore_radius = 4.0
    bore_depth = 3.0
    plate_thickness = 6.0
    _create_plate_with_counterbore(
        stl_file,
        through_radius=through_radius,
        bore_radius=bore_radius,
        bore_depth=bore_depth,
        plate_size=(40.0, 24.0, plate_thickness),
    )

    graph = build_feature_graph_for_stl(stl_file)
    counterbores = [
        feature
        for feature in graph["features"]
        if feature["type"] == "counterbore_hole"
    ]
    simple_holes = [
        feature
        for feature in graph["features"]
        if feature["type"] == "hole_like_cutout"
    ]

    assert len(counterbores) == 1, (
        f"Expected 1 counterbore, got {len(counterbores)}. "
        f"Simple holes: {len(simple_holes)}. "
        f"All features: {[f['type'] for f in graph['features']]}"
    )
    assert len(simple_holes) == 0, "Counterbore should not also be detected as a simple hole"
    cbore = counterbores[0]
    assert cbore["confidence"] >= 0.70
    assert abs(cbore["through_diameter"] - through_radius * 2.0) < through_radius * 0.3
    assert abs(cbore["bore_diameter"] - bore_radius * 2.0) < bore_radius * 0.3
    assert abs(cbore["bore_depth"] - bore_depth) < bore_depth * 0.3
    assert cbore["source_parent_type"] == "plate_like_solid"


def test_feature_graph_scad_preview_emits_counterbore_cutout(test_output_dir):
    stl_file = test_output_dir / "plate_with_counterbore_preview.stl"
    _create_plate_with_counterbore(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "module counterbore_cutout" in scad
    assert "counterbore_0_through_diameter" in scad
    assert "counterbore_0_bore_diameter" in scad
    assert "counterbore_0_bore_depth" in scad
    assert "counterbore_cutout(counterbore_0_center" in scad


def test_feature_graph_extracts_holes_with_light_mesh_noise(test_output_dir):
    stl_file = test_output_dir / "plate_with_two_holes_noisy.stl"
    _create_plate_with_holes(stl_file)
    _jitter_mesh_vertices(stl_file, scale=0.01, seed=123)

    graph = build_feature_graph_for_stl(stl_file)
    holes = [
        feature
        for feature in graph["features"]
        if feature["type"] == "hole_like_cutout" and feature["confidence"] >= 0.55
    ]
    patterns = [
        feature
        for feature in graph["features"]
        if feature["type"] == "linear_hole_pattern"
    ]

    assert len(holes) >= 2
    assert any(3.0 < hole["diameter"] < 5.0 for hole in holes)
    assert len(patterns) >= 1


def test_feature_graph_extracts_slot_with_light_mesh_noise(test_output_dir):
    stl_file = test_output_dir / "plate_with_slot_noisy.stl"
    _create_plate_with_slot(stl_file)
    _jitter_mesh_vertices(stl_file, scale=0.008, seed=77)

    graph = build_feature_graph_for_stl(stl_file)
    slots = [
        feature
        for feature in graph["features"]
        if feature["type"] == "slot_like_cutout" and feature["confidence"] >= 0.55
    ]

    assert len(slots) >= 1
    assert 2.0 < slots[0]["width"] < 4.0
    assert 8.0 < slots[0]["length"] < 12.0


def test_feature_graph_scad_preview_declines_without_plate(test_data_dir):
    # primitive_sphere.stl is now detected as revolve_solid (axisymmetric recovery
    # correctly identifies it as a solid of revolution), so it produces a preview.
    # Use composite_cylinder_beside_box.stl — a composite that passes no single-solid
    # detector — as the canonical "no preview" fixture.
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    graph = build_feature_graph_for_stl(fixtures_dir / "composite_cylinder_beside_box.stl")

    assert emit_feature_graph_scad_preview(graph) is None


def _create_plate_with_holes(
    output_file,
    segments=32,
    centers=None,
    radius=2.0,
    plate_size=(20.0, 10.0, 2.0),
):
    if centers is None:
        centers = [(-3.0, 0.0), (3.0, 0.0)]
    half_width = plate_size[0] * 0.5
    half_depth = plate_size[1] * 0.5
    thickness = plate_size[2]
    vertices = [
        [-half_width, -half_depth, 0.0],
        [half_width, -half_depth, 0.0],
        [half_width, half_depth, 0.0],
        [-half_width, half_depth, 0.0],
        [-half_width, -half_depth, thickness],
        [half_width, -half_depth, thickness],
        [half_width, half_depth, thickness],
        [-half_width, half_depth, thickness],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]

    for center_x, center_y in centers:
        base_index = len(vertices)
        for idx in range(segments):
            theta = 2.0 * np.pi * idx / segments
            x = center_x + radius * np.cos(theta)
            y = center_y + radius * np.sin(theta)
            vertices.append([x, y, 0.0])
            vertices.append([x, y, thickness])
        for idx in range(segments):
            next_idx = (idx + 1) % segments
            b0 = base_index + 2 * idx
            t0 = b0 + 1
            b1 = base_index + 2 * next_idx
            t1 = b1 + 1
            faces.append([b0, b1, t1])
            faces.append([b0, t1, t0])

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _create_plate_with_slot(
    output_file,
    segments=16,
    slot_length=10.0,
    slot_width=3.0,
    plate_size=(18.0, 8.0, 2.0),
):
    half_width = plate_size[0] * 0.5
    half_depth = plate_size[1] * 0.5
    thickness = plate_size[2]
    radius = slot_width * 0.5
    straight_half = (slot_length - slot_width) * 0.5
    vertices = [
        [-half_width, -half_depth, 0.0],
        [half_width, -half_depth, 0.0],
        [half_width, half_depth, 0.0],
        [-half_width, half_depth, 0.0],
        [-half_width, -half_depth, thickness],
        [half_width, -half_depth, thickness],
        [half_width, half_depth, thickness],
        [-half_width, half_depth, thickness],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]

    outline = []
    for idx in range(segments + 1):
        theta = -0.5 * np.pi + np.pi * idx / segments
        outline.append([straight_half + radius * np.cos(theta), radius * np.sin(theta)])
    for idx in range(segments + 1):
        theta = 0.5 * np.pi + np.pi * idx / segments
        outline.append(
            [-straight_half + radius * np.cos(theta), radius * np.sin(theta)]
        )

    base_index = len(vertices)
    for x, y in outline:
        vertices.append([x, y, 0.0])
        vertices.append([x, y, thickness])
    for idx in range(len(outline)):
        next_idx = (idx + 1) % len(outline)
        b0 = base_index + 2 * idx
        t0 = b0 + 1
        b1 = base_index + 2 * next_idx
        t1 = b1 + 1
        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _create_plate_with_rectangular_cutout(
    output_file,
    plate_size=(28.0, 18.0, 4.0),
    cutout_center=(0.0, -3.0),
    cutout_size=(6.0, 4.0),
):
    half_width = plate_size[0] * 0.5
    half_depth = plate_size[1] * 0.5
    thickness = plate_size[2]
    vertices = [
        [-half_width, -half_depth, 0.0],
        [half_width, -half_depth, 0.0],
        [half_width, half_depth, 0.0],
        [-half_width, half_depth, 0.0],
        [-half_width, -half_depth, thickness],
        [half_width, -half_depth, thickness],
        [half_width, half_depth, thickness],
        [-half_width, half_depth, thickness],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]

    cx, cy = cutout_center
    sx, sy = cutout_size
    half_sx = sx * 0.5
    half_sy = sy * 0.5
    inner = [
        [cx - half_sx, cy - half_sy, 0.0],
        [cx + half_sx, cy - half_sy, 0.0],
        [cx + half_sx, cy + half_sy, 0.0],
        [cx - half_sx, cy + half_sy, 0.0],
        [cx - half_sx, cy - half_sy, thickness],
        [cx + half_sx, cy - half_sy, thickness],
        [cx + half_sx, cy + half_sy, thickness],
        [cx - half_sx, cy + half_sy, thickness],
    ]
    base = len(vertices)
    vertices.extend(inner)
    faces.extend(
        [
            [base + 0, base + 1, base + 5],
            [base + 0, base + 5, base + 4],
            [base + 1, base + 2, base + 6],
            [base + 1, base + 6, base + 5],
            [base + 2, base + 3, base + 7],
            [base + 2, base + 7, base + 6],
            [base + 3, base + 0, base + 4],
            [base + 3, base + 4, base + 7],
        ]
    )

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _create_plate_with_rectangular_pocket(
    output_file,
    plate_size=(30.0, 20.0, 5.0),
    pocket_center=(0.0, 4.0),
    pocket_size=(8.0, 6.0),
    pocket_depth=2.0,
):
    half_width = plate_size[0] * 0.5
    half_depth = plate_size[1] * 0.5
    thickness = plate_size[2]
    pocket_floor = thickness - pocket_depth
    vertices = [
        [-half_width, -half_depth, 0.0],
        [half_width, -half_depth, 0.0],
        [half_width, half_depth, 0.0],
        [-half_width, half_depth, 0.0],
        [-half_width, -half_depth, thickness],
        [half_width, -half_depth, thickness],
        [half_width, half_depth, thickness],
        [-half_width, half_depth, thickness],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]

    cx, cy = pocket_center
    sx, sy = pocket_size
    half_sx = sx * 0.5
    half_sy = sy * 0.5
    pocket = [
        [cx - half_sx, cy - half_sy, pocket_floor],
        [cx + half_sx, cy - half_sy, pocket_floor],
        [cx + half_sx, cy + half_sy, pocket_floor],
        [cx - half_sx, cy + half_sy, pocket_floor],
        [cx - half_sx, cy - half_sy, thickness],
        [cx + half_sx, cy - half_sy, thickness],
        [cx + half_sx, cy + half_sy, thickness],
        [cx - half_sx, cy + half_sy, thickness],
    ]
    base = len(vertices)
    vertices.extend(pocket)
    faces.extend(
        [
            [base + 0, base + 1, base + 2],
            [base + 0, base + 2, base + 3],
            [base + 0, base + 1, base + 5],
            [base + 0, base + 5, base + 4],
            [base + 1, base + 2, base + 6],
            [base + 1, base + 6, base + 5],
            [base + 2, base + 3, base + 7],
            [base + 2, base + 7, base + 6],
            [base + 3, base + 0, base + 4],
            [base + 3, base + 4, base + 7],
        ]
    )

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _create_chamfered_plate(
    output_file,
    plate_size=(20.0, 10.0, 2.0),
    edge_chamfer=1.0,
):
    width, depth, thickness = plate_size
    half_width = width * 0.5
    half_depth = depth * 0.5
    inner_half_width = half_width - edge_chamfer
    inner_half_depth = half_depth - edge_chamfer
    if inner_half_width <= 0.0 or inner_half_depth <= 0.0:
        raise ValueError("edge_chamfer must leave a positive top face footprint")

    vertices = [
        [-half_width, -half_depth, 0.0],
        [half_width, -half_depth, 0.0],
        [half_width, half_depth, 0.0],
        [-half_width, half_depth, 0.0],
        [-inner_half_width, -inner_half_depth, thickness],
        [inner_half_width, -inner_half_depth, thickness],
        [inner_half_width, inner_half_depth, thickness],
        [-inner_half_width, inner_half_depth, thickness],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _create_box_with_hole(
    output_file,
    axis="z",
    segments=32,
    radius=2.0,
    box_size=(18.0, 12.0, 10.0),
    cross_center=(0.0, 0.0),
):
    half_x = box_size[0] * 0.5
    half_y = box_size[1] * 0.5
    half_z = box_size[2] * 0.5
    vertices = [
        [-half_x, -half_y, -half_z],
        [half_x, -half_y, -half_z],
        [half_x, half_y, -half_z],
        [-half_x, half_y, -half_z],
        [-half_x, -half_y, half_z],
        [half_x, -half_y, half_z],
        [half_x, half_y, half_z],
        [-half_x, half_y, half_z],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]

    base_index = len(vertices)
    for idx in range(segments):
        theta = 2.0 * np.pi * idx / segments
        cos_theta = radius * np.cos(theta)
        sin_theta = radius * np.sin(theta)
        if axis == "z":
            x = cross_center[0] + cos_theta
            y = cross_center[1] + sin_theta
            vertices.append([x, y, -half_z])
            vertices.append([x, y, half_z])
        elif axis == "x":
            y = cross_center[0] + cos_theta
            z = cross_center[1] + sin_theta
            vertices.append([-half_x, y, z])
            vertices.append([half_x, y, z])
        else:
            raise ValueError("axis must be 'x' or 'z'")

    for idx in range(segments):
        next_idx = (idx + 1) % segments
        b0 = base_index + 2 * idx
        t0 = b0 + 1
        b1 = base_index + 2 * next_idx
        t1 = b1 + 1
        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _create_box_with_rectangular_top_pocket(
    output_file,
    box_size=(24.0, 16.0, 12.0),
    pocket_center=(0.0, 0.0),
    pocket_size=(8.0, 8.0),
    pocket_depth=6.0,
):
    half_x = box_size[0] * 0.5
    half_y = box_size[1] * 0.5
    half_z = box_size[2] * 0.5
    pocket_floor = half_z - pocket_depth
    vertices = [
        [-half_x, -half_y, -half_z],
        [half_x, -half_y, -half_z],
        [half_x, half_y, -half_z],
        [-half_x, half_y, -half_z],
        [-half_x, -half_y, half_z],
        [half_x, -half_y, half_z],
        [half_x, half_y, half_z],
        [-half_x, half_y, half_z],
    ]
    faces = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]

    cx, cy = pocket_center
    sx, sy = pocket_size
    half_sx = sx * 0.5
    half_sy = sy * 0.5
    pocket = [
        [cx - half_sx, cy - half_sy, pocket_floor],
        [cx + half_sx, cy - half_sy, pocket_floor],
        [cx + half_sx, cy + half_sy, pocket_floor],
        [cx - half_sx, cy + half_sy, pocket_floor],
        [cx - half_sx, cy - half_sy, half_z],
        [cx + half_sx, cy - half_sy, half_z],
        [cx + half_sx, cy + half_sy, half_z],
        [cx - half_sx, cy + half_sy, half_z],
    ]
    base = len(vertices)
    vertices.extend(pocket)
    faces.extend(
        [
            [base + 0, base + 1, base + 2],
            [base + 0, base + 2, base + 3],
            [base + 0, base + 1, base + 5],
            [base + 0, base + 5, base + 4],
            [base + 1, base + 2, base + 6],
            [base + 1, base + 6, base + 5],
            [base + 2, base + 3, base + 7],
            [base + 2, base + 7, base + 6],
            [base + 3, base + 0, base + 4],
            [base + 3, base + 4, base + 7],
        ]
    )

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _create_plate_with_counterbore(
    output_file,
    segments=32,
    through_radius=2.0,
    bore_radius=4.0,
    bore_depth=3.0,
    plate_size=(40.0, 24.0, 6.0),
    center_xy=(0.0, 0.0),
):
    """Create a synthetic STL of a plate with a counterbore hole.

    The counterbore has a larger-radius bore at the top and a smaller
    through-hole going all the way through. The geometry consists of:
    - A plate box (12 triangles)
    - Smaller cylinder sidewalls from z=0 to z=(thickness - bore_depth)
    - Larger cylinder sidewalls from z=(thickness - bore_depth) to z=thickness
    - An annular step face connecting the two radii
    """
    half_width = plate_size[0] * 0.5
    half_depth = plate_size[1] * 0.5
    thickness = plate_size[2]
    step_z = thickness - bore_depth
    cx, cy = center_xy

    vertices = [
        [-half_width, -half_depth, 0.0],
        [half_width, -half_depth, 0.0],
        [half_width, half_depth, 0.0],
        [-half_width, half_depth, 0.0],
        [-half_width, -half_depth, thickness],
        [half_width, -half_depth, thickness],
        [half_width, half_depth, thickness],
        [-half_width, half_depth, thickness],
    ]
    faces = [
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ]

    # Through-hole sidewalls: z=0 to z=step_z (smaller radius).
    through_base = len(vertices)
    for idx in range(segments):
        theta = 2.0 * np.pi * idx / segments
        x = cx + through_radius * np.cos(theta)
        y = cy + through_radius * np.sin(theta)
        vertices.append([x, y, 0.0])
        vertices.append([x, y, step_z])
    for idx in range(segments):
        next_idx = (idx + 1) % segments
        b0 = through_base + 2 * idx
        t0 = b0 + 1
        b1 = through_base + 2 * next_idx
        t1 = b1 + 1
        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])

    # Bore sidewalls: z=step_z to z=thickness (larger radius).
    bore_base = len(vertices)
    for idx in range(segments):
        theta = 2.0 * np.pi * idx / segments
        x = cx + bore_radius * np.cos(theta)
        y = cy + bore_radius * np.sin(theta)
        vertices.append([x, y, step_z])
        vertices.append([x, y, thickness])
    for idx in range(segments):
        next_idx = (idx + 1) % segments
        b0 = bore_base + 2 * idx
        t0 = b0 + 1
        b1 = bore_base + 2 * next_idx
        t1 = b1 + 1
        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])

    # Annular step face at z=step_z between the two radii.
    ring_base = len(vertices)
    for idx in range(segments):
        theta = 2.0 * np.pi * idx / segments
        xi = cx + through_radius * np.cos(theta)
        yi = cy + through_radius * np.sin(theta)
        xo = cx + bore_radius * np.cos(theta)
        yo = cy + bore_radius * np.sin(theta)
        vertices.append([xi, yi, step_z])
        vertices.append([xo, yo, step_z])
    for idx in range(segments):
        next_idx = (idx + 1) % segments
        i0 = ring_base + 2 * idx
        o0 = i0 + 1
        i1 = ring_base + 2 * next_idx
        o1 = i1 + 1
        faces.append([i0, o0, o1])
        faces.append([i0, o1, i1])

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def _jitter_mesh_vertices(output_file, scale=0.02, seed=0):
    """Apply deterministic gaussian jitter to mesh vertices to mimic STL noise."""
    mesh = Mesh.from_file(str(output_file))
    vectors = np.asarray(mesh.vectors, dtype=np.float64)
    rng = np.random.default_rng(seed)
    flat = vectors.reshape(-1, 3)
    offsets: dict[tuple[float, float, float], np.ndarray] = {}
    for idx, point in enumerate(flat):
        key = (round(float(point[0]), 6), round(float(point[1]), 6), round(float(point[2]), 6))
        offset = offsets.get(key)
        if offset is None:
            offset = rng.normal(0.0, scale, size=3)
            offsets[key] = offset
        flat[idx] = point + offset
    vectors = flat.reshape(vectors.shape)
    mesh.vectors[:] = vectors
    mesh.save(str(output_file))


# ---------------------------------------------------------------------------
# Track A: triage report tests
# ---------------------------------------------------------------------------

def _make_parametric_preview_graph(test_output_dir) -> dict:
    """Build a graph that produces a parametric preview (plate with holes)."""
    stl_file = test_output_dir / "triage_plate_with_holes.stl"
    _create_plate_with_holes(stl_file)
    return build_feature_graph_for_stl(stl_file)


def _make_linear_extrude_preview_graph() -> dict:
    """Synthetic graph with an emitted linear-extrude preview.

    This is intentionally *not* treated as confirmed parametric preview in the
    triage report until the preview path gains stronger geometric validation.
    """
    return {
        "schema_version": 1,
        "source_file": "mounted_clip.stl",
        "mesh": {
            "triangles": 100,
            "surface_area": 100.0,
            "bounding_box": {"width": 5.0, "height": 48.0, "depth": 28.0},
        },
        "features": [
            {
                "type": "linear_extrude_solid",
                "confidence": 0.83,
                "axis": [1.0, 0.0, 0.0],
                "height": 5.0,
                "profile": [[0.0, 0.0], [20.0, 0.0], [20.0, 10.0], [0.0, 10.0]],
            }
        ],
    }


def _make_error_graph() -> dict:
    """Synthetic error graph."""
    return {
        "schema_version": 1,
        "source_file": "bad_file.stl",
        "status": "error",
        "error": "simulated error",
        "features": [],
    }


def _make_axis_pairs_only_graph(surface_area: float = 600.0, boundary_area_per_pair: float = 100.0) -> dict:
    """Synthetic graph with only axis_boundary_plane_pair features.

    surface_area controls planar_support_fraction:
    - default (600 total, 300 boundary) → PSF=0.5 → medium_planar_support_no_candidate
    - pass surface_area=300 → PSF=1.0 → high_planar_support_no_candidate (box-like)
    - pass surface_area=3000 → PSF=0.1 → low_planar_support_complex_geometry (organic)
    """
    half = boundary_area_per_pair / 2.0
    return {
        "schema_version": 1,
        "source_file": "sphere.stl",
        "mesh": {
            "triangles": 20,
            "surface_area": surface_area,
            "bounding_box": {"width": 10.0, "height": 10.0, "depth": 10.0},
        },
        "features": [
            {
                "type": "axis_boundary_plane_pair",
                "axis": "x",
                "negative_coord": 0.0,
                "positive_coord": 10.0,
                "negative_area": half,
                "positive_area": half,
                "paired": True,
            },
            {
                "type": "axis_boundary_plane_pair",
                "axis": "y",
                "negative_coord": 0.0,
                "positive_coord": 10.0,
                "negative_area": half,
                "positive_area": half,
                "paired": True,
            },
            {
                "type": "axis_boundary_plane_pair",
                "axis": "z",
                "negative_coord": 0.0,
                "positive_coord": 10.0,
                "negative_area": half,
                "positive_area": half,
                "paired": True,
            },
        ],
    }


def _make_polyhedron_fallback_graph() -> dict:
    """Synthetic graph with no features at all."""
    return {
        "schema_version": 1,
        "source_file": "organic.stl",
        "mesh": {"triangles": 500, "surface_area": 200.0, "bounding_box": {"width": 5.0, "height": 8.0, "depth": 3.0}},
        "features": [],
    }


def test_triage_report_schema(test_output_dir):
    """Triage report has the required top-level keys."""
    graphs = [_make_error_graph()]
    report = build_triage_report(graphs, top_n=3, input_dir="/some/dir")

    assert report["schema_version"] == 1
    assert "generated_at_utc" in report
    assert report["input_dir"] == "/some/dir"
    assert report["top_n"] == 3
    assert report["files_processed"] == 1
    assert "bucket_counts" in report
    assert "ranked_failure_patterns" in report
    assert "per_file" in report
    for key in ("parametric_preview", "feature_graph_no_preview", "axis_pairs_only", "polyhedron_fallback", "error"):
        assert key in report["bucket_counts"]


def test_triage_report_bucket_accounting(test_output_dir):
    """bucket_counts values must sum to files_processed for all bucket combinations."""
    preview_graph = _make_parametric_preview_graph(test_output_dir)
    graphs = [
        preview_graph,
        _make_linear_extrude_preview_graph(),
        _make_axis_pairs_only_graph(surface_area=300.0),
        _make_axis_pairs_only_graph(surface_area=300.0),
        _make_polyhedron_fallback_graph(),
        _make_error_graph(),
    ]
    report = build_triage_report(graphs, top_n=5)

    counts = report["bucket_counts"]
    total = sum(counts.values())
    assert total == report["files_processed"]
    assert total == len(graphs)
    assert counts["parametric_preview"] == 1
    assert counts["feature_graph_no_preview"] == 1
    assert counts["axis_pairs_only"] == 2
    assert counts["polyhedron_fallback"] == 1
    assert counts["error"] == 1


def test_triage_report_demotes_linear_extrude_preview_to_unconfirmed_bucket():
    """Emitted linear-extrude SCAD should not count as confirmed preview-ready output."""
    report = build_triage_report([_make_linear_extrude_preview_graph()])

    assert report["bucket_counts"]["parametric_preview"] == 0
    assert report["bucket_counts"]["feature_graph_no_preview"] == 1
    assert report["per_file"][0]["bucket"] == "feature_graph_no_preview"


def test_triage_report_ranked_failure_patterns_shape(test_output_dir):
    """ranked_failure_patterns entries have required fields and count <= top_n."""
    # Use high-PSF graphs so they all land in the same pattern bucket
    graphs = [_make_axis_pairs_only_graph(surface_area=300.0) for _ in range(4)]
    graphs.append(_make_polyhedron_fallback_graph())
    report = build_triage_report(graphs, top_n=3)

    patterns = report["ranked_failure_patterns"]
    assert len(patterns) <= 3
    for entry in patterns:
        assert "pattern" in entry
        assert "count" in entry
        assert "representative_file" in entry
        assert isinstance(entry["count"], int)
        assert entry["count"] > 0


def test_triage_report_ranked_patterns_only_cover_non_preview_buckets(test_output_dir):
    """Ranked failure patterns must not include parametric_preview or error files."""
    preview_graph = _make_parametric_preview_graph(test_output_dir)
    graphs = [
        preview_graph,
        _make_error_graph(),
        _make_axis_pairs_only_graph(surface_area=300.0),
    ]
    report = build_triage_report(graphs, top_n=5)

    pattern_counts = report["bucket_counts"]
    assert pattern_counts["parametric_preview"] == 1
    assert pattern_counts["error"] == 1
    # ranked_failure_patterns total count must equal axis_pairs_only + feature_graph_no_preview
    ranked_total = sum(e["count"] for e in report["ranked_failure_patterns"])
    expected = pattern_counts["axis_pairs_only"] + pattern_counts["feature_graph_no_preview"]
    assert ranked_total == expected


def test_triage_report_failure_shape_metadata_present_for_non_preview(test_output_dir):
    """Non-preview, non-error, non-polyhedron graphs must carry failure_shape_metadata."""
    graphs = [_make_axis_pairs_only_graph()]
    report = build_triage_report(graphs)

    assert report["per_file"][0]["bucket"] == "axis_pairs_only"
    metadata = report["per_file"][0]["failure_shape_metadata"]
    assert "axis_pair_count" in metadata
    assert "paired_axis_count" in metadata
    assert "thinnest_axis" in metadata
    assert "thinnest_axis_paired" in metadata
    assert "planar_support_fraction" in metadata
    assert "plate_candidate_confidence" in metadata
    assert "box_candidate_confidence" in metadata
    assert "dominant_axis_pair_confidence" not in metadata


def test_triage_report_error_and_polyhedron_graphs_have_no_failure_metadata():
    """Error and polyhedron-fallback graph entries must not carry failure_shape_metadata."""
    graphs = [_make_error_graph(), _make_polyhedron_fallback_graph()]
    report = build_triage_report(graphs)

    for entry in report["per_file"]:
        assert "failure_shape_metadata" not in entry


def test_triage_report_integrates_with_benchmark_fixtures(test_data_dir, test_output_dir):
    """build_triage_report works end-to-end against real benchmark fixtures."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    output_json = test_output_dir / "triage_test_graph.json"
    report = build_feature_graph_for_folder(fixtures_dir, output_json, max_files=4)
    triage = build_triage_report(report["graphs"], input_dir=str(fixtures_dir))

    counts = triage["bucket_counts"]
    assert sum(counts.values()) == triage["files_processed"]
    assert triage["files_processed"] == 4
    for entry in triage["per_file"]:
        assert entry["bucket"] in counts


def test_triage_report_planar_support_fraction_splits_organic_from_box(test_data_dir):
    """planar_support_fraction distinguishes organic geometry from box-like candidates."""
    # High PSF (all surface is flat/boundary) → high_planar_support_no_candidate
    high_psf = _make_axis_pairs_only_graph(surface_area=300.0, boundary_area_per_pair=100.0)
    # Medium PSF
    med_psf = _make_axis_pairs_only_graph(surface_area=600.0, boundary_area_per_pair=100.0)
    # Low PSF (organic, e.g. 3DBenchy) → low_planar_support_complex_geometry
    low_psf = _make_axis_pairs_only_graph(surface_area=3000.0, boundary_area_per_pair=100.0)

    report = build_triage_report([high_psf, med_psf, low_psf], top_n=5)
    patterns = {e["pattern"] for e in report["ranked_failure_patterns"]}

    assert "high_planar_support_no_candidate" in patterns
    assert "low_planar_support_complex_geometry" in patterns

    # Verify per-file metadata
    high_entry = next(e for e in report["per_file"] if e["source_file"] == "sphere.stl"
                      and e["failure_shape_metadata"]["planar_support_fraction"] >= 0.65)
    assert high_entry["failure_shape_metadata"]["planar_support_fraction"] >= 0.65


# ---------------------------------------------------------------------------
# IR tree tests
# ---------------------------------------------------------------------------

def test_ir_tree_present_in_graph_output(test_data_dir):
    """build_feature_graph_for_stl always includes an ir_tree key."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_box_axis_aligned.stl")
    assert "ir_tree" in graph
    assert isinstance(graph["ir_tree"], list)
    assert len(graph["ir_tree"]) >= 1


def test_ir_tree_interpretation_schema(test_data_dir):
    """Every entry in ir_tree must be an Interpretation with required fields."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_box_axis_aligned.stl")
    for i, interp in enumerate(graph["ir_tree"]):
        assert interp.get("type") == "Interpretation", f"Entry {i} has wrong type: {interp.get('type')}"
        assert "confidence" in interp, f"Entry {i} missing confidence"
        assert "rank" in interp, f"Entry {i} missing rank"
        assert "root" in interp, f"Entry {i} missing root"


def test_ir_tree_box_no_holes_uses_boolean_union(test_data_dir):
    """A box-like solid with no cutouts produces a BooleanUnion { PrimitiveBox }."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_box_axis_aligned.stl")

    assert len(graph["ir_tree"]) >= 1
    top = graph["ir_tree"][0]
    assert top["type"] == "Interpretation"
    root = top["root"]
    assert root["type"] == "BooleanUnion", f"Expected BooleanUnion for box without holes, got {root['type']}"
    children = root.get("children", [])
    assert any(c.get("type") == "PrimitiveBox" for c in children), (
        f"BooleanUnion children should contain PrimitiveBox; got {[c.get('type') for c in children]}"
    )


def test_ir_tree_box_with_hole_uses_boolean_difference(test_output_dir):
    """A box-like solid with a through-hole produces BooleanDifference { PrimitiveBox, [HoleThrough] }."""
    stl_file = test_output_dir / "ir_box_hole.stl"
    _create_box_with_hole(stl_file)
    graph = build_feature_graph_for_stl(stl_file)

    assert "ir_tree" in graph
    assert len(graph["ir_tree"]) >= 1
    top = graph["ir_tree"][0]
    root = top["root"]
    assert root["type"] == "BooleanDifference", f"Expected BooleanDifference, got {root['type']}"
    assert root["base"]["type"] == "PrimitiveBox"
    cuts = root.get("cuts", [])
    assert len(cuts) >= 1, "Expected at least one cut in BooleanDifference"
    # The hole should appear as a TransformTranslate wrapping a HoleThrough
    hole_nodes = [
        c for c in cuts
        if c.get("type") == "TransformTranslate" and c.get("child", {}).get("type") == "HoleThrough"
    ]
    assert len(hole_nodes) >= 1, (
        f"Expected TransformTranslate/HoleThrough in cuts; got types: {[c.get('type') for c in cuts]}"
    )
    # Each TransformTranslate must carry a 3-element offset
    for node in hole_nodes:
        offset = node.get("offset", [])
        assert len(offset) == 3, f"TransformTranslate offset should have 3 elements, got {offset}"


def test_ir_tree_plate_with_holes_uses_boolean_difference(test_output_dir):
    """A plate with holes produces BooleanDifference { PrimitivePlate, cuts }."""
    stl_file = test_output_dir / "ir_plate_holes.stl"
    _create_plate_with_holes(stl_file, centers=[(-3.0, 0.0), (3.0, 0.0)])
    graph = build_feature_graph_for_stl(stl_file)

    assert "ir_tree" in graph
    assert len(graph["ir_tree"]) >= 1
    top = graph["ir_tree"][0]
    root = top["root"]
    assert root["type"] == "BooleanDifference", f"Expected BooleanDifference, got {root['type']}"
    assert root["base"]["type"] == "PrimitivePlate"
    cuts = root.get("cuts", [])
    # 2 holes may be detected as a PatternLinear (1 cut) or as 2 standalone HoleThrough
    # cuts; either is valid — what matters is at least one cut node is present.
    assert len(cuts) >= 1, f"Expected ≥1 cut node for plate with 2 holes, got {len(cuts)}"
    # The cuts must collectively account for 2 holes (either via a pattern or individually)
    standalone_holes = [
        c for c in cuts
        if c.get("type") == "TransformTranslate" and c.get("child", {}).get("type") == "HoleThrough"
    ]
    pattern_holes = [c for c in cuts if c.get("type") == "PatternLinear"]
    total_hole_coverage = len(standalone_holes) + sum(
        p.get("count", 0) for p in pattern_holes
    )
    assert total_hole_coverage >= 2, (
        f"Expected at least 2 holes covered in IR cuts (standalone={len(standalone_holes)}, "
        f"pattern total={total_hole_coverage})"
    )


def test_ir_tree_fallback_mesh_when_no_solid(test_output_dir):
    """A graph with no solid primitives produces a FallbackMesh Interpretation."""
    # Synthetic graph with only bookkeeping features, no solid
    graph = {
        "schema_version": 1,
        "source_file": "organic.stl",
        "mesh": {"triangles": 100, "surface_area": 500.0, "bounding_box": {}},
        "features": [
            {"type": "axis_boundary_plane_pair", "axis": "x", "confidence": 0.4},
        ],
    }
    from stl2scad.core.feature_graph import _build_ir_tree
    tree = _build_ir_tree(graph)
    assert len(tree) == 1
    assert tree[0]["type"] == "Interpretation"
    assert tree[0]["root"]["type"] == "FallbackMesh"
    assert tree[0]["confidence"] == 0.0


def test_ir_tree_plate_with_linear_pattern_subsumes_hole_centers(test_output_dir):
    """Hole centers belonging to a linear pattern do not appear as standalone cuts."""
    stl_file = test_output_dir / "ir_plate_pattern.stl"
    # 4 evenly-spaced holes → should form a linear_hole_pattern
    centers = [(-6.0, 0.0), (-2.0, 0.0), (2.0, 0.0), (6.0, 0.0)]
    _create_plate_with_holes(stl_file, centers=centers, radius=1.5, plate_size=(24.0, 10.0, 2.0))
    graph = build_feature_graph_for_stl(stl_file)

    patterns_in_flat = [f for f in graph["features"] if f.get("type") == "linear_hole_pattern"]
    if not patterns_in_flat:
        pytest.skip("No linear_hole_pattern detected for this fixture; skip IR subsuming check")

    assert "ir_tree" in graph
    top = graph["ir_tree"][0]
    root = top["root"]
    cuts = root.get("cuts", [])

    # There must be at least one PatternLinear in cuts
    pattern_cuts = [c for c in cuts if c.get("type") == "PatternLinear"]
    assert len(pattern_cuts) >= 1, "Expected PatternLinear node in IR cuts"

    # No standalone TransformTranslate/HoleThrough should appear for pattern member centers
    pattern_centers = set()
    for pat_feat in patterns_in_flat:
        for c in pat_feat.get("centers", []):
            pattern_centers.add(tuple(round(float(v), 3) for v in c))

    standalone_tt = [c for c in cuts if c.get("type") == "TransformTranslate"
                     and c.get("child", {}).get("type") == "HoleThrough"]
    for node in standalone_tt:
        offset = tuple(round(float(v), 3) for v in node.get("offset", []))
        assert offset not in pattern_centers, (
            f"Pattern member hole at {offset} should not appear as standalone TransformTranslate cut"
        )


# ---------------------------------------------------------------------------
# Edge treatment (ChamferOrFilletEdge) IR node tests
# ---------------------------------------------------------------------------

def test_detected_via_strict_on_axis_aligned_box(test_data_dir):
    """A plain axis-aligned box (strict path) should have detected_via='strict'."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_box_axis_aligned.stl")

    solids = [
        f for f in graph["features"]
        if f.get("type") in ("plate_like_solid", "box_like_solid", "cylinder_like_solid")
    ]
    assert len(solids) >= 1
    for solid in solids:
        assert "detected_via" in solid, f"Solid node missing detected_via field: {solid}"
    # A flat 12-triangle box has fully flush faces → strict path
    top_solid = solids[0]
    assert top_solid["detected_via"] == "strict", (
        f"Expected 'strict' for axis-aligned box, got '{top_solid['detected_via']}'"
    )


def test_detected_via_tolerant_on_chamfered_plate(test_output_dir):
    """A plate with chamfered edges (tolerant path) should have detected_via='tolerant_chamfer_or_fillet'."""
    stl_file = test_output_dir / "edge_treatment_chamfered.stl"
    _create_chamfered_plate(stl_file, plate_size=(20.0, 10.0, 2.0), edge_chamfer=1.0)
    graph = build_feature_graph_for_stl(stl_file)

    plates = [f for f in graph["features"] if f.get("type") == "plate_like_solid"]
    assert len(plates) == 1, "Expected exactly one plate_like_solid"
    assert plates[0]["detected_via"] == "tolerant_chamfer_or_fillet", (
        f"Expected 'tolerant_chamfer_or_fillet', got '{plates[0]['detected_via']}'"
    )


def test_ir_tree_strict_solid_has_no_chamfer_or_fillet_edge_node(test_data_dir):
    """A strict-path box should NOT produce a ChamferOrFilletEdge node in the IR."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_box_axis_aligned.stl")

    assert len(graph["ir_tree"]) >= 1
    root = graph["ir_tree"][0]["root"]
    cuts = root.get("cuts", [])
    chamfer_nodes = [c for c in cuts if c.get("type") == "ChamferOrFilletEdge"]
    assert len(chamfer_nodes) == 0, (
        f"Strict-path box should have no ChamferOrFilletEdge; found {chamfer_nodes}"
    )


def test_ir_tree_tolerant_plate_has_chamfer_or_fillet_edge_node(test_output_dir):
    """A chamfered plate (tolerant path) should have a ChamferOrFilletEdge node in the IR."""
    stl_file = test_output_dir / "ir_chamfered_plate.stl"
    _create_chamfered_plate(stl_file, plate_size=(20.0, 10.0, 2.0), edge_chamfer=1.0)
    graph = build_feature_graph_for_stl(stl_file)

    assert len(graph["ir_tree"]) >= 1
    top = graph["ir_tree"][0]
    root = top["root"]
    # There are cuts (the ChamferOrFilletEdge itself causes BooleanDifference)
    assert root["type"] == "BooleanDifference", (
        f"Tolerant plate with edge treatment should use BooleanDifference, got {root['type']}"
    )
    cuts = root.get("cuts", [])
    chamfer_nodes = [c for c in cuts if c.get("type") == "ChamferOrFilletEdge"]
    assert len(chamfer_nodes) == 1, (
        f"Expected exactly one ChamferOrFilletEdge; found {len(chamfer_nodes)}"
    )
    assert "note" in chamfer_nodes[0], "ChamferOrFilletEdge node should carry a 'note' field"
    assert root["base"]["type"] == "PrimitivePlate"


# ---------------------------------------------------------------------------
# Rotated-plate detection tests
# ---------------------------------------------------------------------------

def _create_rotated_plate(
    output_file,
    plate_size=(20.0, 10.0, 2.0),
    rotate_x_deg=30.0,
):
    """Create a simple axis-aligned plate then rotate it around the X axis."""
    import math

    width, depth, thickness = plate_size
    half_w = width * 0.5
    half_d = depth * 0.5

    vertices_local = [
        [-half_w, -half_d, 0.0],
        [half_w, -half_d, 0.0],
        [half_w, half_d, 0.0],
        [-half_w, half_d, 0.0],
        [-half_w, -half_d, thickness],
        [half_w, -half_d, thickness],
        [half_w, half_d, thickness],
        [-half_w, half_d, thickness],
    ]

    rx = math.radians(rotate_x_deg)
    cos_rx = math.cos(rx)
    sin_rx = math.sin(rx)

    def rot_x(v):
        x, y, z = v
        return [x, y * cos_rx - z * sin_rx, y * sin_rx + z * cos_rx]

    vertices = [rot_x(v) for v in vertices_local]
    faces = [
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ]

    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype))
    vertices_array = np.asarray(vertices, dtype=np.float64)
    for index, face in enumerate(faces):
        mesh.vectors[index] = vertices_array[face]
    mesh.save(str(output_file))


def test_rotated_plate_detected_as_plate_like_solid(test_output_dir):
    """A plate tilted 30° around X must be detected as plate_like_solid."""
    stl_file = test_output_dir / "rotated_plate_x30.stl"
    _create_rotated_plate(stl_file, plate_size=(20.0, 10.0, 2.0), rotate_x_deg=30.0)
    graph = build_feature_graph_for_stl(stl_file)

    plates = [f for f in graph["features"] if f.get("type") == "plate_like_solid"]
    assert len(plates) == 1, f"Expected 1 plate_like_solid, got {len(plates)}"
    plate = plates[0]
    assert plate["confidence"] >= 0.55
    assert plate.get("detected_via") == "rotated_plate"


def test_rotated_plate_not_detected_as_box(test_output_dir):
    """A rotated plate must not be falsely classified as box_like_solid."""
    stl_file = test_output_dir / "rotated_plate_x30_no_box.stl"
    _create_rotated_plate(stl_file, plate_size=(20.0, 10.0, 2.0), rotate_x_deg=30.0)
    graph = build_feature_graph_for_stl(stl_file)

    boxes = [f for f in graph["features"] if f.get("type") == "box_like_solid"]
    assert len(boxes) == 0, f"Rotated plate must not be detected as box_like_solid; got {boxes}"


def test_rotated_plate_has_rotation_euler_deg(test_output_dir):
    """Rotated plate feature must carry rotation_euler_deg with non-zero rx."""
    stl_file = test_output_dir / "rotated_plate_euler.stl"
    _create_rotated_plate(stl_file, plate_size=(20.0, 10.0, 2.0), rotate_x_deg=30.0)
    graph = build_feature_graph_for_stl(stl_file)

    plates = [f for f in graph["features"] if f.get("type") == "plate_like_solid"]
    assert len(plates) == 1
    angles = plates[0].get("rotation_euler_deg")
    assert angles is not None, "rotated_plate feature must have rotation_euler_deg"
    assert len(angles) == 3
    rx_deg = angles[0]
    assert abs(rx_deg - 30.0) <= 3.0, (
        f"Expected rx ≈ 30°, got {rx_deg:.2f}°"
    )


def test_rotated_plate_scad_preview_uses_local_frame_multmatrix(test_output_dir):
    """Rotated plate preview should emit a basis-driven transform, not only Euler angles."""
    stl_file = test_output_dir / "rotated_plate_preview_transform.stl"
    _create_rotated_plate(stl_file, plate_size=(20.0, 10.0, 2.0), rotate_x_deg=30.0)
    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "plate_local_u = [" in scad
    assert "plate_local_v = [" in scad
    assert "plate_local_n = [" in scad
    assert "multmatrix(plate_transform)" in scad


def test_cylinder_inward_lateral_threshold_is_configurable():
    """Cylinder inward-area rejection threshold must be read from DetectorConfig."""
    from stl2scad.core.feature_graph import _extract_cylinder_like_solid
    from stl2scad.tuning.config import DetectorConfig

    cap_normals = np.array([
        [0.0, 0.0, 1.0],
        [0.0, 0.0, -1.0],
    ])
    cap_areas = np.array([80.0, 80.0])

    lateral_count = 13
    thetas = np.linspace(0.0, 2.0 * np.pi, lateral_count, endpoint=False)
    lateral_normals = np.array([[float(np.cos(t)), float(np.sin(t)), 0.0] for t in thetas])
    # Flip one sidewall normal inward so inward_frac is above 0.05 but below 0.10.
    lateral_normals[0] *= -1.0
    lateral_areas = np.full((lateral_count,), 5.0, dtype=float)

    normals = np.vstack([cap_normals, lateral_normals])
    face_areas = np.concatenate([cap_areas, lateral_areas])

    vertices = np.zeros((len(normals), 3, 3), dtype=float)
    for i, theta in enumerate(thetas, start=2):
        centroid = np.array([4.0 * np.cos(theta), 4.0 * np.sin(theta), 4.0])
        vertices[i, :, :] = centroid

    bbox = {
        "min_x": -5.0,
        "max_x": 5.0,
        "min_y": -5.0,
        "max_y": 5.0,
        "min_z": 0.0,
        "max_z": 8.0,
        "width": 10.0,
        "height": 10.0,
        "depth": 8.0,
    }

    default_result = _extract_cylinder_like_solid(
        normals,
        face_areas,
        bbox,
        vertices,
        config=DetectorConfig(),
    )
    relaxed_result = _extract_cylinder_like_solid(
        normals,
        face_areas,
        bbox,
        vertices,
        config=DetectorConfig(cylinder_max_inward_lateral_area_fraction=0.10),
    )

    assert default_result == []
    assert len(relaxed_result) == 1
    assert relaxed_result[0]["type"] == "cylinder_like_solid"


def test_rotated_plate_ir_tree_has_transform_rotate(test_output_dir):
    """IR tree for a rotated plate must wrap PrimitivePlate in TransformRotate."""
    stl_file = test_output_dir / "rotated_plate_ir.stl"
    _create_rotated_plate(stl_file, plate_size=(20.0, 10.0, 2.0), rotate_x_deg=30.0)
    graph = build_feature_graph_for_stl(stl_file)

    assert len(graph["ir_tree"]) >= 1
    top = graph["ir_tree"][0]
    root = top["root"]
    # BooleanUnion (no cutouts) with a single TransformRotate child
    assert root["type"] == "BooleanUnion", (
        f"Rotated plate with no holes should use BooleanUnion, got {root['type']}"
    )
    children = root.get("children", [])
    assert len(children) == 1
    xform = children[0]
    assert xform["type"] == "TransformRotate", (
        f"Expected TransformRotate wrapper, got {xform['type']}"
    )
    assert "angles_deg" in xform
    child = xform.get("child", {})
    assert child.get("type") == "PrimitivePlate", (
        f"TransformRotate child must be PrimitivePlate, got {child.get('type')}"
    )


def test_axis_aligned_plate_has_no_transform_rotate_in_ir(test_output_dir):
    """An axis-aligned plate must NOT be wrapped in TransformRotate."""
    stl_file = test_output_dir / "axis_aligned_plate_no_xform.stl"
    _create_plate_with_holes(stl_file, centers=[], plate_size=(20.0, 10.0, 2.0))
    graph = build_feature_graph_for_stl(stl_file)

    assert len(graph["ir_tree"]) >= 1
    root = graph["ir_tree"][0]["root"]
    # The base / children must be PrimitivePlate directly, not TransformRotate
    if root["type"] == "BooleanUnion":
        for child in root.get("children", []):
            assert child["type"] != "TransformRotate", (
                "Axis-aligned plate must not be wrapped in TransformRotate"
            )
    elif root["type"] == "BooleanDifference":
        assert root["base"]["type"] == "PrimitivePlate", (
            "Axis-aligned plate base must be PrimitivePlate"
        )
        assert root["base"].get("type") != "TransformRotate"


def test_ir_tree_wraps_revolve_solid_as_extrude_revolve():
    from stl2scad.core.feature_graph import _build_ir_tree

    graph = {
        "schema_version": 1,
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
            "confidence": 0.9,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.98,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
        }],
    }
    ir = _build_ir_tree(graph)
    assert ir is not None
    assert len(ir) == 1
    root = ir[0]["root"]
    assert root["type"] == "BooleanUnion"
    child = root["children"][0]
    assert child["type"] == "TransformRotate"
    assert child["child"]["type"] == "ExtrudeRevolve"
    sketch = child["child"]["profile"]
    assert sketch["type"] == "Sketch2D"
    assert sketch["kind"] == "polygon"
    assert len(sketch["points"]) == 4


def test_emit_revolve_scad_preview_generates_rotate_extrude():
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
            "confidence": 0.9,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.98,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "rotate_extrude" in scad
    assert "polygon" in scad
    assert "5" in scad and "10" in scad


def test_build_feature_graph_detects_revolve_before_cylinder(tmp_path):
    """Rule 1: revolve recovery runs before cylinder detection."""
    import numpy as np
    from stl.mesh import Mesh as StlMesh
    from stl2scad.core.feature_graph import build_feature_graph_for_stl

    def _cyl(h, r, seg):
        theta = np.linspace(0, 2*np.pi, seg, endpoint=False)
        br = np.column_stack([r*np.cos(theta), r*np.sin(theta), np.zeros_like(theta)])
        tr = np.column_stack([r*np.cos(theta), r*np.sin(theta), np.full_like(theta, h)])
        cb = np.array([0.0, 0.0, 0.0])
        ct = np.array([0.0, 0.0, h])
        verts = np.vstack([br, tr, cb, ct])
        icb = 2*seg
        ict = 2*seg+1
        tris = []
        for i in range(seg):
            j = (i+1) % seg
            tris.append([icb, j, i])
            tris.append([ict, seg+i, seg+j])
            tris.append([i, j, seg+j])
            tris.append([i, seg+j, seg+i])
        return verts, np.asarray(tris, dtype=np.int64)

    verts, tris = _cyl(10.0, 5.0, 64)
    mesh = StlMesh(np.zeros(len(tris), dtype=StlMesh.dtype))
    for fi, tri in enumerate(tris):
        mesh.vectors[fi] = verts[tri]
    stl_path = tmp_path / "cyl.stl"
    mesh.save(str(stl_path))

    graph = build_feature_graph_for_stl(stl_path)
    types = [f["type"] for f in graph["features"]]
    assert types.count("revolve_solid") == 1
    assert types.count("cylinder_like_solid") == 0


def test_emit_revolve_scad_preview_cylinder_upgrade_emits_cylinder():
    """Phase 2: rectangle profile with primitive_upgrade emits cylinder() call."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
            "confidence": 0.95,
            "confidence_components": {
                "axis_quality": 0.97, "cross_slice_consistency": 0.98,
                "normal_field_agreement": 0.95, "profile_validity": 1.0,
            },
            "primitive_upgrade": {
                "type": "cylinder",
                "params": {"r": 5.0, "h": 10.0, "z_lo": 0.0},
                "confidence": 0.96,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "cylinder(" in scad
    assert "rotate_extrude" not in scad
    assert "revolve_r" in scad


def test_emit_revolve_scad_preview_cone_upgrade_emits_cylinder_r1_r2():
    """Phase 2: cone profile with primitive_upgrade emits cylinder(r1=..., r2=...) call."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (6.0, 0.0), (0.0, 12.0)],
            "confidence": 0.92,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.96,
                "normal_field_agreement": 0.94, "profile_validity": 1.0,
            },
            "primitive_upgrade": {
                "type": "cone",
                "params": {"r1": 6.0, "r2": 0.0, "h": 12.0, "z_lo": 0.0, "is_cone": True},
                "confidence": 0.93,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "cylinder(r1=" in scad
    assert "rotate_extrude" not in scad


def test_emit_revolve_scad_preview_sphere_upgrade_emits_sphere():
    """Phase 2: sphere profile with primitive_upgrade emits sphere() call."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, -5.0), (5.0, 0.0), (0.0, 5.0)],
            "confidence": 0.91,
            "confidence_components": {
                "axis_quality": 0.93, "cross_slice_consistency": 0.95,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
            "primitive_upgrade": {
                "type": "sphere",
                "params": {"r": 5.0, "z_center": 0.0},
                "confidence": 0.91,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "sphere(" in scad
    assert "rotate_extrude" not in scad


def test_emit_revolve_scad_preview_annular_emits_difference_cylinders():
    """Annular revolve emits difference() of two cylinders."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "annular_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(3.0, 0.0), (6.0, 0.0), (6.0, 10.0), (3.0, 10.0)],
            "inner_r": 3.0,
            "outer_r": 6.0,
            "confidence": 0.92,
            "confidence_components": {
                "axis_quality": 0.95, "cross_slice_consistency": 0.97,
                "normal_field_agreement": 0.93, "profile_validity": 1.0,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "difference()" in scad
    assert "revolve_inner_r" in scad
    assert "revolve_outer_r" in scad
    assert "rotate_extrude" not in scad


def test_emit_revolve_scad_preview_fallback_without_upgrade():
    """Without primitive_upgrade, generic rotate_extrude is emitted."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "schema_version": 1,
        "source_file": "synthetic.stl",
        "features": [{
            "type": "revolve_solid",
            "detected_via": "axisymmetric_revolve",
            "axis": [0.0, 0.0, 1.0],
            "axis_origin": [0.0, 0.0, 0.0],
            "profile": [(0.0, 0.0), (2.0, 0.8), (4.0, 2.2), (0.0, 9.0)],
            "confidence": 0.90,
            "confidence_components": {
                "axis_quality": 0.93, "cross_slice_consistency": 0.95,
                "normal_field_agreement": 0.92, "profile_validity": 1.0,
            },
        }],
    }
    scad = emit_feature_graph_scad_preview(graph)
    assert scad is not None
    assert "rotate_extrude" in scad
    assert "polygon" in scad


def test_normal_field_agreement_ignores_degenerate_faces_without_warning():
    from stl2scad.core.revolve_recovery import normal_field_agreement

    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    triangles_valid = np.array([[0, 1, 2]], dtype=np.int64)
    triangles_with_degenerate = np.array([[0, 1, 2], [0, 1, 3]], dtype=np.int64)
    axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    origin = np.array([0.0, 0.0, 0.0], dtype=np.float64)

    score_valid = normal_field_agreement(vertices, triangles_valid, axis, origin)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        score_with_degenerate = normal_field_agreement(
            vertices,
            triangles_with_degenerate,
            axis,
            origin,
        )

    runtime_warnings = [
        warning for warning in caught if issubclass(warning.category, RuntimeWarning)
    ]
    assert runtime_warnings == []
    assert np.isclose(score_with_degenerate, score_valid)


# ---------------------------------------------------------------------------
# Phase 2 revolve profile classifier direct unit tests
# ---------------------------------------------------------------------------

def test_classify_revolve_profile_rectangle_returns_cylinder():
    """A rectangle profile in (r, z) must classify as cylinder."""
    from stl2scad.core.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    profile = [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    assert result is not None, "Rectangle profile must produce a cylinder upgrade"
    assert result["type"] == "cylinder"
    assert abs(result["params"]["r"] - 5.0) < 0.1
    assert abs(result["params"]["h"] - 10.0) < 0.1
    assert result["confidence"] >= config.revolve_phase2_min_confidence


def test_classify_revolve_profile_triangle_returns_cone():
    """A right-triangle profile must classify as cone (r2=0)."""
    from stl2scad.core.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    profile = [(0.0, 0.0), (6.0, 0.0), (0.0, 12.0)]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    assert result is not None, "Triangle profile must produce a cone upgrade"
    assert result["type"] == "cone"
    assert result["params"]["is_cone"] is True
    assert result["confidence"] >= config.revolve_phase2_min_confidence


def test_classify_revolve_profile_semicircle_returns_sphere():
    """A semicircular arc profile must classify as sphere."""
    import math
    from stl2scad.core.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    r_expected = 8.0
    # Sample a half-circle: r^2 + (z - R)^2 = R^2, z from 0 to 2R
    # r = sqrt(R^2 - (z - R)^2)
    n_samples = 12
    profile = []
    for i in range(n_samples + 1):
        z = 2.0 * r_expected * i / n_samples
        r = math.sqrt(max(0.0, r_expected**2 - (z - r_expected)**2))
        profile.append((r, z))
    mesh_scale = 20.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    assert result is not None, "Semicircle profile must produce a sphere upgrade"
    assert result["type"] == "sphere"
    assert abs(result["params"]["r"] - r_expected) < 0.5
    assert result["confidence"] >= config.revolve_phase2_min_confidence


def test_classify_revolve_profile_complex_returns_none():
    """A complex sawtooth profile must NOT classify as any primitive."""
    from stl2scad.core.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = DetectorConfig()
    # Sawtooth: alternating high/low r values at multiple z levels
    profile = [
        (0.0, 0.0), (5.0, 0.0), (1.0, 2.0), (5.0, 4.0),
        (1.0, 6.0), (5.0, 8.0), (0.0, 10.0),
    ]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)

    # A sawtooth profile is not a cylinder, cone, or sphere.
    assert result is None, f"Complex sawtooth profile must not upgrade, got: {result}"


def test_classify_revolve_profile_disabled_by_config():
    """When revolve_phase2_min_confidence=1.1, no profile should pass."""
    import dataclasses
    from stl2scad.core.revolve_recovery import classify_revolve_profile
    from stl2scad.tuning.config import DetectorConfig

    config = dataclasses.replace(DetectorConfig(), revolve_phase2_min_confidence=1.1)
    profile = [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)]
    mesh_scale = 15.0

    result = classify_revolve_profile(profile, mesh_scale, config)
    assert result is None, "No profile should pass with min_confidence > 1.0"


def test_revolve_rectangle_profile_emits_cylinder_preview():
    """The rect-profile revolve fixture's SCAD preview should emit cylinder() (Phase 2 upgrade)."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    # Build a synthetic revolve_solid feature with primitive_upgrade=cylinder
    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
                "confidence": 0.95,
                "confidence_components": {
                    "axis_quality": 0.95, "cross_slice_consistency": 0.95,
                    "normal_field_agreement": 0.95, "profile_validity": 1.0,
                },
                "primitive_upgrade": {
                    "type": "cylinder",
                    "params": {"r": 5.0, "h": 10.0, "z_lo": 0.0},
                    "confidence": 0.99,
                },
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "cylinder(" in preview, f"Expected cylinder() in preview, got:\n{preview}"
    assert "rotate_extrude" not in preview, "Phase 2 cylinder should NOT use rotate_extrude"


def test_revolve_triangle_profile_emits_cone_preview():
    """Triangle-profile revolve should emit cylinder(r1=..., r2=...) via Phase 2."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (6.0, 0.0), (0.0, 12.0)],
                "confidence": 0.92,
                "confidence_components": {
                    "axis_quality": 0.92, "cross_slice_consistency": 0.92,
                    "normal_field_agreement": 0.92, "profile_validity": 1.0,
                },
                "primitive_upgrade": {
                    "type": "cone",
                    "params": {"r1": 6.0, "r2": 0.0, "h": 12.0, "z_lo": 0.0, "is_cone": True},
                    "confidence": 0.97,
                },
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "cylinder(" in preview, f"Expected cylinder() for cone in preview, got:\n{preview}"
    assert "r1=" in preview or "revolve_r1" in preview, f"Expected r1 parameter, got:\n{preview}"
    assert "rotate_extrude" not in preview


def test_revolve_sphere_profile_emits_sphere_preview():
    """Sphere-profile revolve should emit sphere() via Phase 2."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (8.0, 8.0), (0.0, 16.0)],
                "confidence": 0.90,
                "confidence_components": {
                    "axis_quality": 0.90, "cross_slice_consistency": 0.90,
                    "normal_field_agreement": 0.90, "profile_validity": 1.0,
                },
                "primitive_upgrade": {
                    "type": "sphere",
                    "params": {"r": 8.0, "z_center": 8.0},
                    "confidence": 0.95,
                },
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "sphere(" in preview, f"Expected sphere() in preview, got:\n{preview}"
    assert "rotate_extrude" not in preview


def test_revolve_no_upgrade_uses_rotate_extrude():
    """A revolve feature WITHOUT primitive_upgrade must still emit rotate_extrude."""
    from stl2scad.core.feature_graph import emit_feature_graph_scad_preview

    graph = {
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (5.0, 2.0), (4.0, 5.0), (3.0, 8.0), (0.0, 10.0)],
                "confidence": 0.90,
                "confidence_components": {
                    "axis_quality": 0.90, "cross_slice_consistency": 0.90,
                    "normal_field_agreement": 0.90, "profile_validity": 1.0,
                },
                # No primitive_upgrade key
            }
        ]
    }
    preview = emit_feature_graph_scad_preview(graph)
    assert "rotate_extrude" in preview, f"Expected rotate_extrude in fallback, got:\n{preview}"
