"""
Tests for CLI parsing and command dispatch.
"""

import argparse
from pathlib import Path

import pytest

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


def test_feature_graph_parser_accepts_inventory_family_selection():
    """Feature graph command should accept family-confidence selection options."""
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "feature-graph",
            "input-dir",
            "--inventory-prefilter",
            "--inventory-min-family-confidence",
            "0.8",
            "--inventory-families",
            "box,cylinder",
        ]
    )
    assert isinstance(args, argparse.Namespace)
    assert args.inventory_min_family_confidence == 0.8
    assert args.inventory_families == ("box", "cylinder")


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


@patch("stl2scad.cli.verify_conversion")
@patch("stl2scad.cli.convert_stl_to_scad")
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
@patch("stl2scad.cli.convert_stl_to_scad")
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


@patch("stl2scad.cli.subprocess.run")
def test_maintainer_stl_dir_runs_no_legacy_detector_steps(mock_run, capsys):
    """--stl-dir no longer adds feature-inventory / feature-graph steps (T-004)."""
    mock_run.return_value = MagicMock(returncode=0)

    exit_code = cli.main(
        [
            "maintainer",
            "--skip-recognition-sweep",
            "--skip-perf-baseline",
            "--stl-dir",
            "some/stls",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DeprecationWarning: --stl-dir is deprecated and ignored" in captured.err
    commands = [call.args[0] for call in mock_run.call_args_list]
    assert len(commands) == 4
    for command in commands:
        assert "feature-inventory" not in command
        assert "feature-graph" not in command
        assert "some/stls" not in command


def test_segmentation_cli_writes_emitter_output_and_supports_shorthand(
    tmp_path, monkeypatch
):
    from tests.test_segmentation_geometry import cube, mesh_of
    from stl2scad.core import segmentation

    source = tmp_path / "input.stl"
    target = tmp_path / "output.scad"
    mesh_of(cube()).save(str(source))
    calls = []

    def emit(features, mesh, *, source_file):
        calls.append((features, len(mesh.vectors), source_file))
        return "// gated segmentation output\ncube(2);\n"

    monkeypatch.setattr(segmentation, "emit_scad", emit)
    assert cli.main([str(source), str(target), "--pipeline", "segmentation"]) == 0
    assert target.read_text() == "// gated segmentation output\ncube(2);\n"
    assert calls == [(None, 12, str(source))]


# --- T-004: segmentation is the only conversion pipeline -------------------

_EMITTED = "// gated segmentation output\ncube(2);\n"


def _cube_stl(directory, name="input.stl"):
    from tests.test_segmentation_geometry import cube, mesh_of

    path = directory / name
    mesh_of(cube()).save(str(path))
    return path


def _record_emit(monkeypatch):
    from stl2scad.core import segmentation

    calls = []

    def emit(features, mesh, *, source_file):
        calls.append((features, len(mesh.vectors), source_file))
        return _EMITTED

    monkeypatch.setattr(segmentation, "emit_scad", emit)
    return calls


def test_convert_defaults_to_segmentation_pipeline(tmp_path, monkeypatch, capsys):
    args = cli.build_parser().parse_args(["convert", "in.stl", "out.scad"])
    assert args.pipeline == "segmentation"
    source = _cube_stl(tmp_path)
    target = tmp_path / "output.scad"
    calls = _record_emit(monkeypatch)

    assert cli.main(["convert", str(source), str(target)]) == 0

    assert calls == [(None, 12, str(source))]
    assert target.read_text() == _EMITTED
    captured = capsys.readouterr()
    assert "Pipeline: segmentation" in captured.out
    assert "DeprecationWarning" not in captured.err


def test_convert_pipeline_legacy_warns_writes_nothing_exits_2(
    tmp_path, monkeypatch, capsys
):
    source = _cube_stl(tmp_path)
    target = tmp_path / "output.scad"
    calls = _record_emit(monkeypatch)

    exit_code = cli.main(["convert", "--pipeline", "legacy", str(source), str(target)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "DeprecationWarning" in captured.err
    assert "--pipeline legacy is deprecated" in captured.err
    assert "DeprecationWarning" not in captured.out
    assert not target.exists()
    assert calls == []


def test_convert_legacy_flags_warn_and_are_ignored(tmp_path, monkeypatch, capsys):
    source = _cube_stl(tmp_path)
    target = tmp_path / "output.scad"
    calls = _record_emit(monkeypatch)

    exit_code = cli.main(
        [
            "convert",
            str(source),
            str(target),
            "--parametric",
            "--recognition-backend",
            "cgal",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DeprecationWarning: --parametric is deprecated and ignored" in captured.err
    assert (
        "DeprecationWarning: --recognition-backend is deprecated and ignored"
        in captured.err
    )
    # Ignored: the conversion is the plain segmentation conversion.
    assert calls == [(None, 12, str(source))]
    assert target.read_text() == _EMITTED


@pytest.mark.parametrize(
    "command",
    ["feature-graph", "feature-graph-from-inventory", "feature-inventory"],
)
def test_legacy_detector_commands_warn_and_exit_2(
    command, tmp_path, monkeypatch, capsys
):
    source = _cube_stl(tmp_path)
    output_json = tmp_path / "report.json"
    preview = tmp_path / "preview.scad"
    inventory = tmp_path / "inventory.json"
    inventory.write_text("{}", encoding="utf-8")
    calls = _record_emit(monkeypatch)
    argv = {
        "feature-graph": [
            "feature-graph",
            str(source),
            "--output",
            str(output_json),
            "--scad-preview",
            str(preview),
        ],
        "feature-graph-from-inventory": [
            "feature-graph-from-inventory",
            str(inventory),
            "--output",
            str(output_json),
        ],
        "feature-inventory": [
            "feature-inventory",
            str(tmp_path),
            "--output",
            str(output_json),
        ],
    }[command]

    exit_code = cli.main(argv)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "DeprecationWarning" in captured.err
    assert f"'{command}' is deprecated and does nothing" in captured.err
    assert not output_json.exists()
    assert not preview.exists()
    assert calls == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["input.stl", "inventory.json"]


def test_verify_and_batch_convert_through_segmentation(tmp_path, monkeypatch):
    stl_dir = tmp_path / "stls"
    stl_dir.mkdir()
    source = _cube_stl(stl_dir, "part.stl")
    out_dir = tmp_path / "out"
    calls = _record_emit(monkeypatch)
    verified = []

    def fake_verify(stl_file, scad_file, tolerance, **kwargs):
        verified.append(Path(scad_file).read_text())
        result = MagicMock()
        result.passed = True
        result.comparison = {}
        result.tolerance = tolerance
        return result

    monkeypatch.setattr(cli, "verify_conversion", fake_verify)

    assert cli.main(["verify", str(source)]) == 0
    assert calls == [(None, 12, str(source))]
    assert verified == [_EMITTED]

    assert cli.main(["batch", str(stl_dir), str(out_dir)]) == 0
    assert calls[1:] == [(None, 12, str(source))]
    assert (out_dir / "part.scad").read_text() == _EMITTED
    assert verified[1:] == [_EMITTED]
