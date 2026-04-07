"""
Tests for intermediate feature graph extraction.
"""

from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.core.feature_graph import (
    build_feature_graph_for_folder,
    build_feature_graph_for_stl,
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
