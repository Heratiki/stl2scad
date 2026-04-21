"""
Tests for intermediate feature graph extraction.
"""

from pathlib import Path

import numpy as np
import pytest
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
    assert len(holes) == 1
    assert holes[0]["axis"] == axis
    assert holes[0]["source_parent_type"] == "box_like_solid"
    assert 3.5 < holes[0]["diameter"] < 4.5
    assert holes[0]["confidence"] >= 0.70


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
