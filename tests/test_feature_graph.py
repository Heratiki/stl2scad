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
    report = build_feature_graph_for_folder(fixtures_dir, output_json, max_files=3)

    assert output_json.exists()
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


def test_feature_graph_scad_preview_emits_plate_with_holes(test_output_dir):
    stl_file = test_output_dir / "plate_with_two_holes_preview.stl"
    _create_plate_with_holes(stl_file)

    graph = build_feature_graph_for_stl(stl_file)
    scad = emit_feature_graph_scad_preview(graph)

    assert scad is not None
    assert "difference()" in scad
    assert "cube(plate_size)" in scad
    assert scad.count("cylinder(") == 2


def test_feature_graph_scad_preview_declines_without_plate(test_data_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_sphere.stl")

    assert emit_feature_graph_scad_preview(graph) is None


def _create_plate_with_holes(output_file, segments=32):
    vertices = [
        [-10.0, -5.0, 0.0],
        [10.0, -5.0, 0.0],
        [10.0, 5.0, 0.0],
        [-10.0, 5.0, 0.0],
        [-10.0, -5.0, 2.0],
        [10.0, -5.0, 2.0],
        [10.0, 5.0, 2.0],
        [-10.0, 5.0, 2.0],
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

    for center_x in (-3.0, 3.0):
        base_index = len(vertices)
        for idx in range(segments):
            theta = 2.0 * np.pi * idx / segments
            x = center_x + 2.0 * np.cos(theta)
            y = 2.0 * np.sin(theta)
            vertices.append([x, y, 0.0])
            vertices.append([x, y, 2.0])
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
