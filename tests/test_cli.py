"""
Tests for CLI parsing and command dispatch.
"""

import argparse

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
