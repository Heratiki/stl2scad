"""
Tests for intermediate feature graph extraction.
"""

import numpy as np
from stl.mesh import Mesh

from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.core.feature_graph import (
    build_feature_graph_for_folder,
    build_feature_graph_for_stl,
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
    report = build_feature_graph_for_folder(fixtures_dir, output_json, max_files=3, workers=2)

    assert output_json.exists()
    assert report["config"]["workers"] == 2
    assert report["summary"]["file_count"] == 3
    assert report["summary"]["error_count"] == 0
    assert report["summary"]["feature_counts"]


def test_feature_graph_extracts_repeated_through_holes(test_output_dir):
    stl_file = test_output_dir / "plate_with_two_holes.stl"
    _create_plate_with_holes(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    holes = [feature for feature in graph["features"] if feature["type"] == "hole_like_cutout"]
    patterns = [
        feature for feature in graph["features"] if feature["type"] == "linear_hole_pattern"
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
        feature for feature in graph["features"] if feature["type"] == "grid_hole_pattern"
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
    slots = [feature for feature in graph["features"] if feature["type"] == "slot_like_cutout"]

    assert len(slots) == 1
    assert slots[0]["slot_axis"] == "x"
    assert abs(slots[0]["width"] - 3.0) < 1e-5
    assert abs(slots[0]["length"] - 10.0) < 1e-5
    assert slots[0]["confidence"] >= 0.70


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


def test_feature_graph_scad_preview_declines_without_plate(test_data_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_sphere.stl")

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
        outline.append([-straight_half + radius * np.cos(theta), radius * np.sin(theta)])

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
