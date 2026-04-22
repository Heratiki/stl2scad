"""
Tests for CLI parsing and command dispatch.
"""

import argparse
import json
from pathlib import Path

from stl2scad import cli


def test_main_without_args_returns_usage_error():
    """No args should print help and return a non-success exit code."""
    assert cli.main([]) == 1


def test_convert_parser_rejects_non_positive_tolerance():
    """Convert tolerance must be strictly positive."""
    parser = cli.build_parser()
    try:
        parser.parse_args(["convert", "in.stl", "out.scad", "--tolerance", "0"])
        assert False, "Expected argparse to reject non-positive tolerance"
    except SystemExit as exc:
        assert exc.code == 2


def test_verify_parser_rejects_negative_tolerances():
    """Verify tolerances must be non-negative."""
    parser = cli.build_parser()
    try:
        parser.parse_args(["verify", "in.stl", "--volume-tol", "-1"])
        assert False, "Expected argparse to reject negative volume tolerance"
    except SystemExit as exc:
        assert exc.code == 2


def test_verify_parser_rejects_negative_sample_seed():
    """Sample seed must be non-negative when provided."""
    parser = cli.build_parser()
    try:
        parser.parse_args(["verify", "in.stl", "--sample-seed", "-1"])
        assert False, "Expected argparse to reject negative sample seed"
    except SystemExit as exc:
        assert exc.code == 2


def test_verify_parser_html_flag():
    """Verify command should parse html-report and visualize flags independently."""
    parser = cli.build_parser()
    args = parser.parse_args(["verify", "in.stl", "--html-report", "--visualize"])
    assert isinstance(args, argparse.Namespace)
    assert args.html_report is True
    assert args.visualize is True


def test_feature_inventory_parser_rejects_negative_workers():
    """Feature inventory workers must be non-negative."""
    parser = cli.build_parser()
    try:
        parser.parse_args(["feature-inventory", "input-dir", "--workers", "-1"])
        assert False, "Expected argparse to reject negative workers"
    except SystemExit as exc:
        assert exc.code == 2


def test_feature_graph_parser_accepts_scad_preview():
    """Feature graph command should accept SCAD preview path for single-file mode."""
    parser = cli.build_parser()
    args = parser.parse_args(
        ["feature-graph", "input.stl", "--scad-preview", "preview.scad"]
    )
    assert isinstance(args, argparse.Namespace)
    assert args.scad_preview == "preview.scad"


def test_feature_graph_parser_accepts_inventory_prefilter():
    """Feature graph command should accept inventory-prefilter directory options."""
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "feature-graph",
            "input-dir",
            "--inventory-prefilter",
            "--inventory-output",
            "inventory.json",
        ]
    )
    assert isinstance(args, argparse.Namespace)
    assert args.inventory_prefilter is True
    assert args.inventory_output == "inventory.json"


def test_feature_graph_from_inventory_parser_accepts_scad_preview_dir():
    """Feature-graph-from-inventory should accept SCAD preview output dir."""
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "feature-graph-from-inventory",
            "inventory.json",
            "--scad-preview-dir",
            "preview_dir",
        ]
    )
    assert isinstance(args, argparse.Namespace)
    assert args.scad_preview_dir == "preview_dir"


def test_maintainer_parser_defaults():
    """Maintainer command should parse with sensible defaults."""
    parser = cli.build_parser()
    args = parser.parse_args(["maintainer"])
    assert isinstance(args, argparse.Namespace)
    assert args.mode == "quick"
    assert args.dry_run is False
    assert args.continue_on_error is False
    assert args.skip_recognition_sweep is False
    assert args.skip_perf_baseline is False
    assert args.skip_real_world_gate is False


from unittest.mock import patch, MagicMock


@patch("stl2scad.cli.stl2scad")
def test_convert_command_execution(mock_stl2scad, test_output_dir):
    """Test convert command successfully invokes core logic."""
    # Setup mock return
    mock_stats = MagicMock()
    mock_stats.original_vertices = 100
    mock_stats.deduplicated_vertices = 50
    mock_stats.faces = 20
    mock_stats.metadata = {"volume": "10"}
    mock_stl2scad.return_value = mock_stats

    out_file = str(test_output_dir / "out.scad")
    # Execute via main
    exit_code = cli.main(
        ["convert", "dummy.stl", out_file, "--tolerance", "0.5", "--debug"]
    )

    assert exit_code == 0
    mock_stl2scad.assert_called_once_with(
        "dummy.stl",
        out_file,
        0.5,
        True,
        False,
        recognition_backend="native",
        compute_backend="auto",
    )


@patch("stl2scad.cli.verify_conversion")
@patch("stl2scad.cli.stl2scad")
def test_verify_command_execution(mock_stl2scad, mock_verify, test_output_dir):
    """Test verify command constructs parameters and handles output."""
    mock_result = MagicMock()
    mock_result.passed = True
    mock_result.comparison = {}
    mock_result.tolerance = {"volume": 1.0, "surface_area": 2.0, "bounding_box": 0.5}
    mock_verify.return_value = mock_result

    exit_code = cli.main(["verify", "dummy.stl", "--volume-tol", "1.5"])
    assert exit_code == 0

    # Check that verify was called with correct constructed tolerance
    args, kwargs = mock_verify.call_args
    assert args[0] == "dummy.stl"
    assert args[2]["volume"] == 1.5
    assert kwargs["sample_seed"] is None


@patch("stl2scad.cli.verify_conversion")
@patch("stl2scad.cli.stl2scad")
def test_batch_command_execution(
    mock_stl2scad, mock_verify, test_data_dir, test_output_dir
):
    """Test batch command processes directory globs correctly."""
    mock_result = MagicMock()
    mock_result.passed = True
    mock_verify.return_value = mock_result

    exit_code = cli.main(
        ["batch", str(test_data_dir), str(test_output_dir), "--bbox-tol", "2.0"]
    )
    assert exit_code == 0
    # Should have executed for at least the sample stl in data dir
    assert mock_stl2scad.call_count > 0
    assert mock_verify.call_count > 0


@patch("stl2scad.cli.analyze_stl_folder")
def test_feature_inventory_command_execution(mock_analyze, test_output_dir):
    """Feature inventory command should invoke analysis with resolved workers."""
    mock_analyze.return_value = {
        "summary": {
            "file_count": 4,
            "ok_count": 4,
            "error_count": 0,
            "classification_counts": {"mechanical_candidate": 4},
            "candidate_feature_counts": {"mirror_symmetry": 3},
        }
    }

    output_file = str(test_output_dir / "feature_inventory.json")
    exit_code = cli.main(
        [
            "feature-inventory",
            "models",
            "--output",
            output_file,
            "--max-files",
            "4",
            "--workers",
            "2",
        ]
    )

    assert exit_code == 0
    mock_analyze.assert_called_once()
    _args, kwargs = mock_analyze.call_args
    assert kwargs["input_dir"] == Path("models")
    assert kwargs["output_json"] == Path(output_file)
    assert kwargs["config"].max_files == 4
    assert kwargs["config"].workers == 2
    assert kwargs["config"].recursive is True


@patch("stl2scad.cli.build_feature_graph_for_folder")
def test_feature_graph_directory_command_execution(mock_build_graph, test_output_dir):
    """Feature graph directory mode should route to folder builder."""
    mock_build_graph.return_value = {
        "summary": {
            "file_count": 3,
            "error_count": 0,
            "feature_counts": {"plate_like_solid": 2},
        }
    }

    output_file = str(test_output_dir / "feature_graph.json")
    exit_code = cli.main(
        [
            "feature-graph",
            str(test_output_dir),
            "--output",
            output_file,
            "--workers",
            "2",
            "--max-files",
            "3",
        ]
    )

    assert exit_code == 0
    mock_build_graph.assert_called_once()
    args, kwargs = mock_build_graph.call_args
    assert args == (test_output_dir, Path(output_file))
    assert kwargs["recursive"] is True
    assert kwargs["max_files"] == 3
    assert kwargs["workers"] == 2
    assert callable(kwargs["progress_callback"])


@patch("stl2scad.cli.analyze_stl_folder_for_feature_graphs")
def test_feature_graph_directory_command_inventory_prefilter_execution(
    mock_prefilter_graphs, test_output_dir
):
    """Feature graph directory mode should support inventory-prefilter routing."""
    mock_prefilter_graphs.return_value = {
        "inventory_summary": {"file_count": 4},
        "summary": {
            "error_count": 0,
            "feature_counts": {"plate_like_solid": 2},
        },
        "selection": {
            "filter_mode": "inventory_mechanical_candidates",
            "inventory_file_count": 4,
            "mechanical_candidate_count": 2,
            "skipped_non_mechanical_count": 2,
            "skipped_error_count": 0,
        },
    }

    output_file = str(test_output_dir / "feature_graph_prefilter.json")
    inventory_file = str(test_output_dir / "feature_inventory_prefilter.json")
    exit_code = cli.main(
        [
            "feature-graph",
            str(test_output_dir),
            "--output",
            output_file,
            "--workers",
            "2",
            "--inventory-prefilter",
            "--inventory-output",
            inventory_file,
        ]
    )

    assert exit_code == 0
    mock_prefilter_graphs.assert_called_once()
    _args, kwargs = mock_prefilter_graphs.call_args
    assert kwargs["input_dir"] == test_output_dir
    assert kwargs["output_json"] == Path(output_file)
    assert kwargs["inventory_output_json"] == Path(inventory_file)
    assert kwargs["inventory_config"].workers == 2
    assert kwargs["inventory_config"].recursive is True
    assert kwargs["graph_workers"] == 2
    assert callable(kwargs["inventory_progress_callback"])
    assert callable(kwargs["graph_progress_callback"])


@patch("stl2scad.cli.emit_feature_graph_scad_preview")
@patch("stl2scad.cli.build_feature_graph_for_stl")
def test_feature_graph_file_command_writes_json_and_preview(
    mock_build_graph, mock_emit_scad, test_output_dir
):
    """Feature graph single-file mode should write JSON and optional SCAD preview."""
    input_file = test_output_dir / "input.stl"
    input_file.write_text("solid test", encoding="utf-8")
    output_file = test_output_dir / "feature_graph.json"
    preview_file = test_output_dir / "preview.scad"

    mock_build_graph.return_value = {
        "source_file": str(input_file),
        "features": [{"type": "plate_like_solid"}],
    }
    mock_emit_scad.return_value = "difference() {}"

    exit_code = cli.main(
        [
            "feature-graph",
            str(input_file),
            "--output",
            str(output_file),
            "--scad-preview",
            str(preview_file),
        ]
    )

    assert exit_code == 0
    mock_build_graph.assert_called_once_with(input_file)
    mock_emit_scad.assert_called_once()
    assert json.loads(output_file.read_text(encoding="utf-8"))["features"][0]["type"] == (
        "plate_like_solid"
    )
    assert preview_file.read_text(encoding="utf-8") == "difference() {}"


@patch("stl2scad.cli.emit_feature_graph_scad_preview")
@patch("stl2scad.cli.build_feature_graphs_from_inventory")
def test_feature_graph_from_inventory_writes_scad_previews(
    mock_build_graphs, mock_emit_scad, test_output_dir
):
    """Inventory graph command should emit per-file SCAD previews when requested."""
    output_file = test_output_dir / "graphs_from_inventory.json"
    preview_dir = test_output_dir / "preview"

    mock_build_graphs.return_value = {
        "summary": {"error_count": 0, "feature_counts": {"plate_like_solid": 1}},
        "selection": {
            "inventory_file_count": 2,
            "mechanical_candidate_count": 2,
            "skipped_non_mechanical_count": 0,
            "skipped_error_count": 0,
        },
        "graphs": [
            {"source_file": "parts/plate_a.stl", "features": [{"type": "plate_like_solid"}]},
            {"source_file": "parts/plate_b.stl", "features": [{"type": "plate_like_solid"}]},
        ],
    }
    mock_emit_scad.side_effect = ["difference() {}", None]

    exit_code = cli.main(
        [
            "feature-graph-from-inventory",
            "inventory.json",
            "--output",
            str(output_file),
            "--workers",
            "2",
            "--scad-preview-dir",
            str(preview_dir),
        ]
    )

    assert exit_code == 0
    mock_build_graphs.assert_called_once()
    assert (preview_dir / "parts" / "plate_a.preview.scad").read_text(
        encoding="utf-8"
    ) == "difference() {}"
    assert not (preview_dir / "parts" / "plate_b.preview.scad").exists()


@patch("stl2scad.cli.subprocess.run")
def test_maintainer_command_runs_expected_step_prefix(mock_run):
    """Maintainer quick mode should chain commands through subprocess."""
    mock_run.return_value = MagicMock(returncode=0)

    exit_code = cli.main(
        [
            "maintainer",
            "--skip-recognition-sweep",
            "--skip-perf-baseline",
        ]
    )

    assert exit_code == 0
    # Fixture, feature detector, CLI tests, and Track C merge-gate run in quick mode.
    assert mock_run.call_count == 4
    first_call_cmd = mock_run.call_args_list[0].args[0]
    assert first_call_cmd[1:] == ["-m", "pytest", "tests/test_feature_fixtures.py", "-v"]
    last_call_cmd = mock_run.call_args_list[-1].args[0]
    assert last_call_cmd[1] == "scripts/score_real_world_corpus.py"
    assert "--merge-gate" in last_call_cmd
