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


def test_verify_parser_html_flag():
    """Verify command should parse html-report and visualize flags independently."""
    parser = cli.build_parser()
    args = parser.parse_args(["verify", "in.stl", "--html-report", "--visualize"])
    assert isinstance(args, argparse.Namespace)
    assert args.html_report is True
    assert args.visualize is True
