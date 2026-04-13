"""
Tests for feature-level STL inventory.
"""

import json

from stl2scad import cli
from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.core.feature_inventory import (
    InventoryConfig,
    analyze_stl_file,
    analyze_stl_folder,
    build_feature_graphs_from_inventory,
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
        config=InventoryConfig(recursive=True, max_files=3, workers=2),
    )

    assert output_json.exists()
    assert report["config"]["workers"] == 2
    assert report["summary"]["file_count"] == 3
    assert report["summary"]["ok_count"] == 3
    assert report["summary"]["candidate_feature_counts"]


def test_build_feature_graphs_from_inventory_filters_mechanical_candidates(
    test_data_dir, test_output_dir
):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    inventory_report = {
        "input_dir": str(fixtures_dir),
        "files": [
            {
                "file": "primitive_box_axis_aligned.stl",
                "status": "ok",
                "classification": {"primary": "mechanical_candidate"},
            },
            {
                "file": "primitive_sphere.stl",
                "status": "ok",
                "classification": {"primary": "organic_candidate"},
            },
            {
                "file": "missing.stl",
                "status": "error",
                "classification": {"primary": "mechanical_candidate"},
            },
        ],
    }

    output_json = test_output_dir / "feature_graph_from_inventory.json"
    report = build_feature_graphs_from_inventory(
        inventory_report,
        output_json,
        workers=1,
    )

    assert output_json.exists()
    assert report["selection"]["inventory_file_count"] == 3
    assert report["selection"]["mechanical_candidate_count"] == 1
    assert report["selection"]["skipped_non_mechanical_count"] == 1
    assert report["selection"]["skipped_error_count"] == 1
    assert report["summary"]["file_count"] == 1
    assert report["summary"]["error_count"] == 0
    assert report["graphs"][0]["source_file"] == "primitive_box_axis_aligned.stl"
    feature_types = {feature["type"] for feature in report["graphs"][0]["features"]}
    assert "box_like_solid" in feature_types


def test_feature_graph_from_inventory_command_execution(test_data_dir, test_output_dir):
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    inventory_json = test_output_dir / "feature_inventory_seed.json"
    inventory_json.write_text(
        json.dumps(
            {
                "input_dir": str(fixtures_dir),
                "files": [
                    {
                        "file": "primitive_box_axis_aligned.stl",
                        "status": "ok",
                        "classification": {"primary": "mechanical_candidate"},
                    },
                    {
                        "file": "primitive_sphere.stl",
                        "status": "ok",
                        "classification": {"primary": "organic_candidate"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output_json = test_output_dir / "feature_graph_from_inventory_cli.json"

    exit_code = cli.main(
        [
            "feature-graph-from-inventory",
            str(inventory_json),
            "--output",
            str(output_json),
            "--workers",
            "1",
        ]
    )

    assert exit_code == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["selection"]["mechanical_candidate_count"] == 1
    assert report["summary"]["file_count"] == 1
