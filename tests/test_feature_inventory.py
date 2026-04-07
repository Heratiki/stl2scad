"""
Tests for feature-level STL inventory.
"""

from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.core.feature_inventory import (
    InventoryConfig,
    analyze_stl_file,
    analyze_stl_folder,
)


def test_analyze_stl_file_detects_box_feature_signals(test_data_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    result = analyze_stl_file(fixtures_dir / "primitive_box_axis_aligned.stl")

    assert result["status"] == "ok"
    assert result["triangles"] == 12
    assert result["classification"]["primary"] == "mechanical_candidate"
    feature_types = {feature["type"] for feature in result["candidate_features"]}
    assert "dominant_axis_aligned_planes" in feature_types
    assert "mirror_symmetry" in feature_types


def test_analyze_stl_folder_writes_inventory_report(test_data_dir, test_output_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    output_json = test_output_dir / "feature_inventory.json"
    report = analyze_stl_folder(
        fixtures_dir,
        output_json,
        config=InventoryConfig(recursive=True, max_files=3),
    )

    assert output_json.exists()
    assert report["summary"]["file_count"] == 3
    assert report["summary"]["ok_count"] == 3
    assert report["summary"]["candidate_feature_counts"]
