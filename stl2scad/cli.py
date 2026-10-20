"""
Command-line interface for the STL to OpenSCAD converter.

This module provides a command-line interface for converting STL files to
OpenSCAD format and verifying conversion accuracy.
"""

import argparse
from dataclasses import dataclass
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from stl2scad.core.acceleration import get_acceleration_report
from stl2scad.core.conversion import (
    ConversionStats,
    STLValidationError,
    convert_stl_to_scad,
)
from stl2scad.core.temp_paths import temporary_directory
from stl2scad.core.verification import (
    generate_comparison_visualization,
    generate_verification_report_html,
    verify_conversion,
)


# Backend ids the archived legacy recognizers accepted. Kept so existing
# scripts that pass --recognition-backend still parse (T-004); the value is
# ignored.
LEGACY_RECOGNITION_BACKENDS = ("native", "trimesh_manifold", "cgal")

LEGACY_REMOVED_NOTE = (
    "the legacy pipeline was removed (T-004); stl2scad converts through "
    "segmentation only"
)


def _warn_deprecated(message: str) -> None:
    """Print one deprecation warning line to stderr."""
    print(f"DeprecationWarning: {message}", file=sys.stderr)


def _warn_ignored_legacy_options(args: argparse.Namespace) -> None:
    """Warn once per legacy-only option the user set; the options are ignored."""
    ignored = []
    if getattr(args, "parametric", False):
        ignored.append("--parametric")
    if getattr(args, "recognition_backend", None) is not None:
        ignored.append("--recognition-backend")
    if getattr(args, "compute_backend", None) is not None:
        ignored.append("--compute-backend")
    if getattr(args, "tolerance", None) is not None:
        ignored.append("--tolerance")
    for option in ignored:
        _warn_deprecated(
            f"{option} is deprecated and ignored: {LEGACY_REMOVED_NOTE}."
        )


def _legacy_command_removed(args: argparse.Namespace) -> int:
    """Handler for commands that only ran the archived legacy detectors."""
    _warn_deprecated(
        f"'{args.command}' is deprecated and does nothing: it only ran the "
        f"legacy feature-graph detectors, and {LEGACY_REMOVED_NOTE}. "
        "The archived code is in stl2scad/legacy/."
    )
    return 2


def _positive_float(value: str) -> float:
    """argparse type validator for strictly positive floats."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected a float, got '{value}'") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def _non_negative_float(value: str) -> float:
    """argparse type validator for non-negative floats."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected a float, got '{value}'") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be non-negative")
    return parsed


def _non_negative_int(value: str) -> int:
    """argparse type validator for non-negative integers."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected an integer, got '{value}'") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be non-negative")
    return parsed


def _unit_interval_float(value: str) -> float:
    """argparse type validator for 0.0-1.0 floats."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected a float, got '{value}'") from exc
    if parsed < 0.0 or parsed > 1.0:
        raise argparse.ArgumentTypeError("Value must be between 0.0 and 1.0")
    return parsed


def _csv_family_list(value: str) -> tuple[str, ...]:
    """argparse type validator for comma-separated inventory family names."""
    families = tuple(
        token.strip().lower() for token in value.split(",") if token.strip()
    )
    if not families:
        raise argparse.ArgumentTypeError("Expected at least one family name")
    allowed = {"plate", "box", "cylinder"}
    invalid = [family for family in families if family not in allowed]
    if invalid:
        raise argparse.ArgumentTypeError(
            "Unknown family name(s): "
            + ", ".join(invalid)
            + ". Expected any of: box, cylinder, plate"
        )
    return families


@dataclass(frozen=True)
class MaintainerStep:
    """A single command in the maintainer pipeline."""

    name: str
    command: List[str]


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m stl2scad",
        description="Convert STL files to OpenSCAD and verify conversion accuracy.",
    )

    subparsers = parser.add_subparsers(dest="command")

    convert_parser = subparsers.add_parser(
        "convert",
        help="Convert an STL file to OpenSCAD format",
    )
    convert_parser.add_argument("input_file", help="Input STL file")
    convert_parser.add_argument("output_file", help="Output SCAD file")
    convert_parser.add_argument(
        "--pipeline",
        choices=["segmentation", "legacy"],
        default="segmentation",
        help=(
            "Conversion pipeline (default: segmentation). 'legacy' is "
            "deprecated: it prints a warning, writes nothing and exits 2"
        ),
    )
    convert_parser.add_argument(
        "--tolerance",
        type=_positive_float,
        default=None,
        help="Deprecated and ignored (legacy vertex deduplication tolerance)",
    )
    convert_parser.add_argument(
        "--debug",
        action="store_true",
        help="Print a traceback when conversion fails",
    )
    convert_parser.add_argument(
        "--parametric",
        action="store_true",
        help="Deprecated and ignored (legacy primitive recognition)",
    )
    convert_parser.add_argument(
        "--recognition-backend",
        choices=list(LEGACY_RECOGNITION_BACKENDS),
        default=None,
        help="Deprecated and ignored (legacy recognition backend)",
    )
    convert_parser.add_argument(
        "--compute-backend",
        choices=["auto", "cpu", "gpu"],
        default=None,
        help="Deprecated and ignored (legacy vertex deduplication backend)",
    )
    convert_parser.set_defaults(handler=convert_command)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify conversion accuracy for STL and SCAD models",
    )
    verify_parser.add_argument("input_file", help="Input STL file")
    verify_parser.add_argument(
        "output_file",
        nargs="?",
        default=None,
        help="Existing SCAD file to verify (optional)",
    )
    verify_parser.add_argument(
        "--volume-tol",
        type=_non_negative_float,
        default=1.0,
        help="Volume difference tolerance in percent (default: 1.0)",
    )
    verify_parser.add_argument(
        "--area-tol",
        type=_non_negative_float,
        default=2.0,
        help="Surface area difference tolerance in percent (default: 2.0)",
    )
    verify_parser.add_argument(
        "--bbox-tol",
        type=_non_negative_float,
        default=0.5,
        help="Bounding box difference tolerance in percent (default: 0.5)",
    )
    verify_parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate visualization files",
    )
    verify_parser.add_argument(
        "--html-report",
        action="store_true",
        help="Generate HTML report with visualizations",
    )
    verify_parser.add_argument(
        "--parametric",
        action="store_true",
        help="Deprecated and ignored (legacy primitive recognition)",
    )
    verify_parser.add_argument(
        "--recognition-backend",
        choices=list(LEGACY_RECOGNITION_BACKENDS),
        default=None,
        help="Deprecated and ignored (legacy recognition backend)",
    )
    verify_parser.add_argument(
        "--sample-seed",
        type=_non_negative_int,
        default=None,
        help="Seed for deterministic sampling-based verification metrics",
    )
    verify_parser.add_argument(
        "--compute-backend",
        choices=["auto", "cpu", "gpu"],
        default=None,
        help="Deprecated and ignored (legacy vertex deduplication backend)",
    )
    verify_parser.set_defaults(handler=verify_command)

    batch_parser = subparsers.add_parser(
        "batch",
        help="Batch convert and verify STL files in a directory",
    )
    batch_parser.add_argument("input_dir", help="Input directory containing STL files")
    batch_parser.add_argument("output_dir", help="Output directory for generated files")
    batch_parser.add_argument(
        "--volume-tol",
        type=_non_negative_float,
        default=1.0,
        help="Volume difference tolerance in percent (default: 1.0)",
    )
    batch_parser.add_argument(
        "--area-tol",
        type=_non_negative_float,
        default=2.0,
        help="Surface area difference tolerance in percent (default: 2.0)",
    )
    batch_parser.add_argument(
        "--bbox-tol",
        type=_non_negative_float,
        default=0.5,
        help="Bounding box difference tolerance in percent (default: 0.5)",
    )
    batch_parser.add_argument(
        "--html-report",
        action="store_true",
        help="Generate HTML reports (and visualizations) for each processed file",
    )
    batch_parser.add_argument(
        "--parametric",
        action="store_true",
        help="Deprecated and ignored (legacy primitive recognition)",
    )
    batch_parser.add_argument(
        "--recognition-backend",
        choices=list(LEGACY_RECOGNITION_BACKENDS),
        default=None,
        help="Deprecated and ignored (legacy recognition backend)",
    )
    batch_parser.add_argument(
        "--sample-seed",
        type=_non_negative_int,
        default=None,
        help="Seed for deterministic sampling-based verification metrics",
    )
    batch_parser.add_argument(
        "--compute-backend",
        choices=["auto", "cpu", "gpu"],
        default=None,
        help="Deprecated and ignored (legacy vertex deduplication backend)",
    )
    batch_parser.set_defaults(handler=batch_command)

    accel_parser = subparsers.add_parser(
        "acceleration",
        help="Inspect GPU availability and acceleration recommendations",
    )
    accel_parser.add_argument(
        "--json",
        action="store_true",
        help="Print full acceleration report as JSON",
    )
    accel_parser.set_defaults(handler=acceleration_command)

    feature_inventory_parser = subparsers.add_parser(
        "feature-inventory",
        help="Deprecated: warns and exits 2 (legacy feature inventory)",
    )
    feature_inventory_parser.add_argument(
        "input_dir",
        help="Directory containing STL files to analyze",
    )
    feature_inventory_parser.add_argument(
        "--output",
        default="artifacts/feature_inventory.json",
        help="Path to JSON inventory output file",
    )
    feature_inventory_parser.add_argument(
        "--max-files",
        type=_non_negative_int,
        default=None,
        help="Optional cap on files analyzed",
    )
    feature_inventory_parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only analyze STL files directly in input_dir",
    )
    feature_inventory_parser.add_argument(
        "--workers",
        type=_non_negative_int,
        default=0,
        help="Parallel workers for folder scans. Use 0 for auto, 1 for serial",
    )
    feature_inventory_parser.set_defaults(handler=_legacy_command_removed)

    feature_graph_parser = subparsers.add_parser(
        "feature-graph",
        help="Deprecated: warns and exits 2 (legacy feature graph)",
    )
    feature_graph_parser.add_argument(
        "input_path",
        help="Input STL file or directory to analyze",
    )
    feature_graph_parser.add_argument(
        "--output",
        default="artifacts/feature_graph.json",
        help="Path to JSON feature-graph output",
    )
    feature_graph_parser.add_argument(
        "--max-files",
        type=_non_negative_int,
        default=None,
        help="Optional cap when input_path is a directory",
    )
    feature_graph_parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only analyze STL files directly in input_path when it is a directory",
    )
    feature_graph_parser.add_argument(
        "--workers",
        type=_non_negative_int,
        default=0,
        help="Parallel workers for folder scans. Use 0 for auto, 1 for serial",
    )
    feature_graph_parser.add_argument(
        "--inventory-prefilter",
        action="store_true",
        help="For directory inputs, run feature inventory first and graph only likely mechanical candidates",
    )
    feature_graph_parser.add_argument(
        "--inventory-output",
        default=None,
        help="Optional inventory JSON output path when using --inventory-prefilter",
    )
    feature_graph_parser.add_argument(
        "--inventory-min-mechanical-score",
        type=_unit_interval_float,
        default=None,
        help="Optional minimum inventory mechanical_score required for graph selection (0.0-1.0)",
    )
    feature_graph_parser.add_argument(
        "--inventory-max-organic-score",
        type=_unit_interval_float,
        default=None,
        help="Optional maximum inventory organic_score allowed for graph selection (0.0-1.0)",
    )
    feature_graph_parser.add_argument(
        "--inventory-allow-non-mechanical-primary",
        action="store_true",
        help="Allow non-degenerate non-mechanical primary classifications if score thresholds pass",
    )
    feature_graph_parser.add_argument(
        "--inventory-min-family-confidence",
        type=_unit_interval_float,
        default=None,
        help="Optional minimum per-family confidence required for graph selection (0.0-1.0)",
    )
    feature_graph_parser.add_argument(
        "--inventory-families",
        type=_csv_family_list,
        default=(),
        help="Optional comma-separated family subset for inventory family-confidence selection (plate,box,cylinder)",
    )
    feature_graph_parser.add_argument(
        "--scad-preview",
        default=None,
        help="Optional SCAD preview output path for a single STL input",
    )
    feature_graph_parser.set_defaults(handler=_legacy_command_removed)

    feature_graph_inventory_parser = subparsers.add_parser(
        "feature-graph-from-inventory",
        help="Deprecated: warns and exits 2 (legacy feature graph)",
    )
    feature_graph_inventory_parser.add_argument(
        "inventory_json",
        help="Path to a feature inventory JSON report",
    )
    feature_graph_inventory_parser.add_argument(
        "--output",
        default="artifacts/feature_graph_from_inventory.json",
        help="Path to JSON feature-graph output",
    )
    feature_graph_inventory_parser.add_argument(
        "--workers",
        type=_non_negative_int,
        default=0,
        help="Parallel workers for graph building. Use 0 for auto, 1 for serial",
    )
    feature_graph_inventory_parser.add_argument(
        "--scad-preview-dir",
        default=None,
        help="Optional output directory for SCAD previews generated from each graph",
    )
    feature_graph_inventory_parser.add_argument(
        "--inventory-min-mechanical-score",
        type=_unit_interval_float,
        default=None,
        help="Optional minimum inventory mechanical_score required for graph selection (0.0-1.0)",
    )
    feature_graph_inventory_parser.add_argument(
        "--inventory-max-organic-score",
        type=_unit_interval_float,
        default=None,
        help="Optional maximum inventory organic_score allowed for graph selection (0.0-1.0)",
    )
    feature_graph_inventory_parser.add_argument(
        "--inventory-allow-non-mechanical-primary",
        action="store_true",
        help="Allow non-degenerate non-mechanical primary classifications if score thresholds pass",
    )
    feature_graph_inventory_parser.add_argument(
        "--inventory-min-family-confidence",
        type=_unit_interval_float,
        default=None,
        help="Optional minimum per-family confidence required for graph selection (0.0-1.0)",
    )
    feature_graph_inventory_parser.add_argument(
        "--inventory-families",
        type=_csv_family_list,
        default=(),
        help="Optional comma-separated family subset for inventory family-confidence selection (plate,box,cylinder)",
    )
    feature_graph_inventory_parser.set_defaults(handler=_legacy_command_removed)

    maintainer_parser = subparsers.add_parser(
        "maintainer",
        help="Run a chained maintainer workflow for tests, sweeps, and optional corpus analysis",
    )
    maintainer_parser.add_argument(
        "--mode",
        choices=["quick", "full"],
        default="quick",
        help="Workflow profile. quick runs fast safety checks; full adds fixture regeneration (default: quick)",
    )
    maintainer_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them",
    )
    maintainer_parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running remaining steps even if one step fails",
    )
    maintainer_parser.add_argument(
        "--skip-recognition-sweep",
        action="store_true",
        help="Skip benchmark recognition sweep",
    )
    maintainer_parser.add_argument(
        "--skip-perf-baseline",
        action="store_true",
        help="Skip performance baseline run",
    )
    maintainer_parser.add_argument(
        "--skip-real-world-gate",
        action="store_true",
        help="Skip real-world recall merge-gate scoring step",
    )
    maintainer_parser.add_argument(
        "--recognition-backends",
        default="native,trimesh_manifold,cgal",
        help="Comma-separated backends for recognition sweep (default: native,trimesh_manifold,cgal)",
    )
    maintainer_parser.add_argument(
        "--recognition-output",
        default="artifacts/recognition_sweep_maintainer.json",
        help="Output path for recognition sweep JSON",
    )
    maintainer_parser.add_argument(
        "--perf-output",
        default="artifacts/perf_baseline_maintainer.json",
        help="Output path for perf baseline JSON",
    )
    maintainer_parser.add_argument(
        "--perf-repeat",
        type=_non_negative_int,
        default=1,
        help="Repeat count for perf baseline (default: 1)",
    )
    maintainer_parser.add_argument(
        "--perf-recognition-backend",
        choices=list(LEGACY_RECOGNITION_BACKENDS),
        default="native",
        help="Recognition backend used by perf baseline (default: native)",
    )
    maintainer_parser.add_argument(
        "--real-world-manifest",
        default="tests/data/real_world_corpus_manifest.json",
        help="Manifest path for real-world recall merge-gate scoring",
    )
    maintainer_parser.add_argument(
        "--real-world-baseline",
        default="artifacts/real_world_recall_baseline.json",
        help="Baseline path for real-world recall merge-gate scoring",
    )
    maintainer_parser.add_argument(
        "--real-world-corpus-root",
        default=None,
        help="Optional corpus root override for real-world merge-gate scoring",
    )
    maintainer_parser.add_argument(
        "--real-world-output",
        default="artifacts/real_world_recall_maintainer.json",
        help="Output path for maintainer real-world recall report",
    )
    maintainer_parser.add_argument(
        "--real-world-delta-output",
        default="artifacts/real_world_recall_delta_maintainer.json",
        help="Output path for maintainer real-world recall delta report",
    )
    maintainer_parser.add_argument(
        "--stl-dir",
        default=None,
        help=(
            "Deprecated and ignored: the inventory and feature-graph steps it "
            "added ran the legacy detectors (T-004)"
        ),
    )
    maintainer_parser.add_argument(
        "--inventory-output",
        default="artifacts/feature_inventory_maintainer.json",
        help="Deprecated and ignored (was used with --stl-dir)",
    )
    maintainer_parser.add_argument(
        "--feature-graph-output",
        default="artifacts/feature_graph_maintainer.json",
        help="Deprecated and ignored (was used with --stl-dir)",
    )
    maintainer_parser.add_argument(
        "--workers",
        type=_non_negative_int,
        default=0,
        help="Deprecated and ignored (was used with --stl-dir)",
    )
    maintainer_parser.add_argument(
        "--max-files",
        type=_non_negative_int,
        default=None,
        help="Deprecated and ignored (was used with --stl-dir)",
    )
    maintainer_parser.set_defaults(handler=maintainer_command)

    return parser


def _tolerance_from_args(args: argparse.Namespace) -> Dict[str, float]:
    """Construct a tolerance dictionary from parsed args."""
    return {
        "volume": args.volume_tol,
        "surface_area": args.area_tol,
        "bounding_box": args.bbox_tol,
    }


def print_stats(stats: ConversionStats) -> None:
    """
    Print conversion statistics.

    Args:
        stats: Statistics from the conversion process
    """
    reduction = 100 * (1 - stats.deduplicated_vertices / stats.original_vertices)
    print("\nConversion successful:")
    print(f"  Original vertices: {stats.original_vertices:,}")
    print(f"  Optimized vertices: {stats.deduplicated_vertices:,}")
    print(f"  Faces: {stats.faces:,}")
    print(f"  Vertex reduction: {reduction:.1f}%")

    if stats.metadata:
        print("\nModel information:")
        for key, value in stats.metadata.items():
            print(f"  {key}: {value}")


def print_verification_result(result: Any) -> None:
    """
    Print verification result.

    Args:
        result: Verification result object
    """
    status = "PASSED" if result.passed else "FAILED"
    print(f"\nVerification {status}")

    if "volume" in result.comparison:
        vol = result.comparison["volume"]
        print("\nVolume Comparison:")
        print(f"  STL: {vol['stl']:.2f} mm³")
        print(f"  SCAD: {vol['scad']:.2f} mm³")
        print(
            f"  Difference: {vol['difference']:.2f} mm³ ({vol['difference_percent']:.2f}%)"
        )
        if abs(vol["difference_percent"]) > result.tolerance["volume"]:
            print(f"  Status: FAILED (exceeds {result.tolerance['volume']}% tolerance)")
        else:
            print(f"  Status: PASSED (within {result.tolerance['volume']}% tolerance)")

    if "surface_area" in result.comparison:
        area = result.comparison["surface_area"]
        print("\nSurface Area Comparison:")
        print(f"  STL: {area['stl']:.2f} mm²")
        print(f"  SCAD: {area['scad']:.2f} mm²")
        print(
            f"  Difference: {area['difference']:.2f} mm² ({area['difference_percent']:.2f}%)"
        )
        if abs(area["difference_percent"]) > result.tolerance["surface_area"]:
            print(
                f"  Status: FAILED (exceeds {result.tolerance['surface_area']}% tolerance)"
            )
        else:
            print(
                f"  Status: PASSED (within {result.tolerance['surface_area']}% tolerance)"
            )

    if "bounding_box" in result.comparison:
        bbox = result.comparison["bounding_box"]
        print("\nBounding Box Comparison:")
        for dim in ["width", "height", "depth"]:
            if dim in bbox:
                dim_data = bbox[dim]
                print(f"  {dim.capitalize()}:")
                print(f"    STL: {dim_data['stl']:.2f} mm")
                print(f"    SCAD: {dim_data['scad']:.2f} mm")
                print(
                    f"    Difference: {dim_data['difference']:.2f} mm ({dim_data['difference_percent']:.2f}%)"
                )
                if (
                    abs(dim_data["difference_percent"])
                    > result.tolerance["bounding_box"]
                ):
                    print(
                        f"    Status: FAILED (exceeds {result.tolerance['bounding_box']}% tolerance)"
                    )
                else:
                    print(
                        f"    Status: PASSED (within {result.tolerance['bounding_box']}% tolerance)"
                    )


def _resolve_workers(value: int) -> int:
    """Resolve worker counts, allowing 0 to mean auto."""
    if value < 0:
        raise ValueError("--workers must be >= 0")
    if value == 0:
        return max(1, min(os.cpu_count() or 1, 32))
    return value


def _format_command(command: List[str]) -> str:
    """Render a subprocess command for terminal output."""
    return " ".join(shlex.quote(part) for part in command)


def _repo_root() -> Path:
    """Resolve the repository root from this module path."""
    return Path(__file__).resolve().parents[1]


def _build_maintainer_steps(args: argparse.Namespace) -> List[MaintainerStep]:
    """Create a list of commands for the requested maintainer profile."""
    python_exe = sys.executable
    steps: List[MaintainerStep] = []

    if args.mode == "full":
        steps.append(
            MaintainerStep(
                name="Regenerate feature fixtures",
                command=[python_exe, "scripts/generate_feature_fixtures.py"],
            )
        )

    steps.extend(
        [
            MaintainerStep(
                name="Fixture round-trip safety test",
                command=[python_exe, "-m", "pytest", "tests/test_feature_fixtures.py", "-v"],
            ),
            MaintainerStep(
                name="Feature detector tests",
                command=[
                    python_exe,
                    "-m",
                    "pytest",
                    # Moved by T-004; skipped unless STL2SCAD_LEGACY_TESTS=1.
                    "tests/legacy/test_feature_graph.py",
                    "tests/legacy/test_feature_inventory.py",
                    "-q",
                ],
            ),
            MaintainerStep(
                name="CLI regression tests",
                command=[python_exe, "-m", "pytest", "tests/test_cli.py", "-q"],
            ),
        ]
    )

    if not args.skip_recognition_sweep:
        steps.append(
            MaintainerStep(
                name="Recognition sweep",
                command=[
                    python_exe,
                    "scripts/run_recognition_sweep.py",
                    "--fixtures-dir",
                    "tests/data/benchmark_fixtures",
                    "--output",
                    args.recognition_output,
                    "--backends",
                    args.recognition_backends,
                ],
            )
        )

    if not args.skip_perf_baseline:
        steps.append(
            MaintainerStep(
                name="Performance baseline",
                command=[
                    python_exe,
                    "scripts/run_perf_baseline.py",
                    "--fixtures-dir",
                    "tests/data/benchmark_fixtures",
                    "--output",
                    args.perf_output,
                    "--repeat",
                    str(args.perf_repeat),
                    "--recognition-backend",
                    args.perf_recognition_backend,
                ],
            )
        )

    if not args.skip_real_world_gate:
        merge_gate_command = [
            python_exe,
            "scripts/score_real_world_corpus.py",
            "--manifest",
            args.real_world_manifest,
            "--baseline",
            args.real_world_baseline,
            "--output",
            args.real_world_output,
            "--delta-output",
            args.real_world_delta_output,
            "--merge-gate",
        ]
        if args.real_world_corpus_root:
            merge_gate_command.extend(["--corpus-root", args.real_world_corpus_root])
        steps.append(
            MaintainerStep(
                name="Real-world recall merge-gate",
                command=merge_gate_command,
            )
        )

    return steps


def maintainer_command(args: argparse.Namespace) -> int:
    """Execute the chained maintainer workflow."""
    if getattr(args, "stl_dir", None):
        _warn_deprecated(
            "--stl-dir is deprecated and ignored: its feature-inventory and "
            f"feature-graph steps ran the legacy detectors, and {LEGACY_REMOVED_NOTE}."
        )
    try:
        if args.perf_repeat < 1:
            raise ValueError("--perf-repeat must be >= 1")

        steps = _build_maintainer_steps(args)
        if not steps:
            print("No maintainer steps selected.")
            return 0

        repo_root = _repo_root()
        failures: List[tuple[str, int]] = []

        print(f"Maintainer workflow mode: {args.mode}")
        print(f"Repository root: {repo_root}")
        print(f"Steps: {len(steps)}")

        for index, step in enumerate(steps, start=1):
            print(f"\n[{index}/{len(steps)}] {step.name}")
            print(f"$ {_format_command(step.command)}")

            if args.dry_run:
                continue

            result = subprocess.run(step.command, cwd=repo_root)
            if result.returncode != 0:
                failures.append((step.name, int(result.returncode)))
                print(
                    f"Step failed ({step.name}) with exit code {result.returncode}.",
                    file=sys.stderr,
                )
                if not args.continue_on_error:
                    break

        if failures:
            print("\nMaintainer workflow completed with failures:", file=sys.stderr)
            for name, code in failures:
                print(f"  - {name}: exit code {code}", file=sys.stderr)
            return 1

        if args.dry_run:
            print("\nDry run complete: no commands were executed.")
        else:
            print("\nMaintainer workflow completed successfully.")
        return 0
    except Exception as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        return 1


def acceleration_command(args: argparse.Namespace) -> int:
    """Inspect hardware acceleration support and recommendations."""
    report = get_acceleration_report()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("Acceleration Report")
    print(f"  GPU detected: {report.get('gpu_detected')}")
    print(f"  GPU compute ready: {report.get('gpu_compute_ready')}")
    print(f"  GPU compute library: {report.get('gpu_compute_backend')}")
    print(f"  Compute reason: {report.get('gpu_compute_reason')}")

    devices = report.get("devices", [])
    if devices:
        print("  Devices:")
        for device in devices:
            name = device.get("name", "unknown")
            vendor = device.get("vendor", "unknown")
            mem = device.get("memory_total", "")
            line = f"    - {vendor}: {name}"
            if mem:
                line += f" ({mem})"
            print(line)

    recs = report.get("recommendations", [])
    if recs:
        print("  Recommendations:")
        for rec in recs:
            print(f"    - {rec}")
    return 0


def convert_command(args: argparse.Namespace) -> int:
    """
    Execute the convert command.

    Args:
        args: Parsed command-line arguments for convert

    Returns:
        int: Exit code (0 for success, 1 for error, 2 for the removed
        legacy pipeline)
    """
    if getattr(args, "pipeline", "segmentation") == "legacy":
        # Checked before any work so nothing is written (T-004).
        _warn_deprecated(
            f"--pipeline legacy is deprecated: {LEGACY_REMOVED_NOTE}. "
            "Nothing was written. Use the default --pipeline segmentation."
        )
        return 2
    _warn_ignored_legacy_options(args)
    try:
        print(f"Converting {args.input_file} to {args.output_file}")
        if args.debug:
            print("Debug mode enabled")
        stats = convert_stl_to_scad(args.input_file, args.output_file)
        print("Pipeline: segmentation")
        print_stats(stats)
        return 0

    except FileNotFoundError as exc:
        print(f"Error: File not found - {str(exc)}", file=sys.stderr)
        return 1
    except STLValidationError as exc:
        print(f"Error: Invalid STL file - {str(exc)}", file=sys.stderr)
        return 1
    except PermissionError as exc:
        print(f"Error: Permission denied - {str(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        if args.debug:
            import traceback

            traceback.print_exc()
        return 1


def verify_command(args: argparse.Namespace) -> int:
    """
    Execute the verify command.

    Args:
        args: Parsed command-line arguments for verify

    Returns:
        int: Exit code (0 for success, 1 for error, 2 for verification failure)
    """
    temp_dir_context = None
    _warn_ignored_legacy_options(args)
    try:
        tolerance = _tolerance_from_args(args)
        visualize = bool(args.visualize or args.html_report)

        print(f"Verifying conversion of {args.input_file}")
        if args.output_file:
            print(f"Using existing SCAD file: {args.output_file}")
            scad_file_to_use = args.output_file
        else:
            print("Will generate temporary SCAD file")
            temp_dir_context = temporary_directory(prefix="verify")
            temp_dir = temp_dir_context.__enter__()
            scad_file_to_use = str(
                temp_dir / f"{Path(args.input_file).stem}.scad"
            )
            convert_stl_to_scad(args.input_file, scad_file_to_use)

        print("Tolerance settings:")
        print(f"  Volume: {tolerance['volume']}%")
        print(f"  Surface area: {tolerance['surface_area']}%")
        print(f"  Bounding box: {tolerance['bounding_box']}%")
        if args.sample_seed is not None:
            print(f"  Sample seed: {args.sample_seed}")

        if visualize:
            print("Visualization enabled")
        if args.html_report:
            print("HTML report enabled")

        result = verify_conversion(
            args.input_file,
            scad_file_to_use,
            tolerance,
            debug=False,
            sample_seed=args.sample_seed,
        )
        print_verification_result(result)

        report_dir = (
            Path(args.output_file).parent
            if args.output_file
            else Path(args.input_file).parent
        )
        report_base = Path(args.input_file).stem
        report_file = report_dir / f"{report_base}_verification.json"
        result.save_report(report_file)
        print(f"\nVerification report saved to: {report_file}")

        if visualize:
            vis_dir = report_dir / f"{report_base}_visualizations"
            vis_dir.mkdir(exist_ok=True, parents=True)

            print(f"\nGenerating visualizations in: {vis_dir}")
            visualizations = generate_comparison_visualization(
                args.input_file,
                scad_file_to_use,
                vis_dir,
            )
            print(f"Generated {len(visualizations)} visualization files")

            if args.html_report:
                html_file = report_dir / f"{report_base}_verification.html"
                generate_verification_report_html(
                    vars(result), visualizations, html_file
                )
                print(f"\nHTML report saved to: {html_file}")

        return 0 if result.passed else 2

    except FileNotFoundError as exc:
        print(f"Error: File not found - {str(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        if temp_dir_context is not None:
            temp_dir_context.__exit__(None, None, None)


def batch_command(args: argparse.Namespace) -> int:
    """
    Execute the batch command.

    Args:
        args: Parsed command-line arguments for batch

    Returns:
        int: Exit code (0 for success, 1 for error, 2 for verification failures)
    """
    _warn_ignored_legacy_options(args)
    try:
        tolerance = _tolerance_from_args(args)
        input_path = Path(args.input_dir)
        output_path = Path(args.output_dir)

        if not input_path.exists() or not input_path.is_dir():
            print(
                f"Error: Input directory not found: {args.input_dir}", file=sys.stderr
            )
            return 1

        output_path.mkdir(exist_ok=True, parents=True)
        stl_files = list(input_path.glob("**/*.stl"))
        if not stl_files:
            print(f"Error: No STL files found in {args.input_dir}", file=sys.stderr)
            return 1

        print(f"Found {len(stl_files)} STL files in {args.input_dir}")
        print(f"Output directory: {args.output_dir}")
        print("Tolerance settings:")
        print(f"  Volume: {tolerance['volume']}%")
        print(f"  Surface area: {tolerance['surface_area']}%")
        print(f"  Bounding box: {tolerance['bounding_box']}%")
        if args.sample_seed is not None:
            print(f"  Sample seed: {args.sample_seed}")

        if args.html_report:
            print("HTML reports will be generated")

        results: Dict[str, Dict[str, Any]] = {}
        for stl_file in stl_files:
            rel_path = stl_file.relative_to(input_path)
            scad_file = output_path / rel_path.with_suffix(".scad")
            report_file = output_path / rel_path.with_suffix(".verification.json")
            scad_file.parent.mkdir(exist_ok=True, parents=True)

            print(f"\nProcessing: {stl_file}")
            print(f"Output: {scad_file}")

            try:
                convert_stl_to_scad(str(stl_file), str(scad_file))
                result = verify_conversion(
                    stl_file,
                    scad_file,
                    tolerance,
                    debug=False,
                    sample_seed=args.sample_seed,
                )
                result.save_report(report_file)

                if args.html_report:
                    vis_dir = output_path / rel_path.with_suffix(".visualizations")
                    vis_dir.mkdir(exist_ok=True, parents=True)
                    visualizations = generate_comparison_visualization(
                        stl_file,
                        scad_file,
                        vis_dir,
                    )
                    html_file = output_path / rel_path.with_suffix(".verification.html")
                    generate_verification_report_html(
                        vars(result), visualizations, html_file
                    )

                results[str(rel_path)] = {
                    "passed": result.passed,
                    "report": str(report_file),
                }

                status = "PASSED" if result.passed else "FAILED"
                print(f"Verification: {status}")

            except Exception as exc:
                print(f"Error processing {stl_file}: {str(exc)}", file=sys.stderr)
                results[str(rel_path)] = {
                    "passed": False,
                    "error": str(exc),
                }

        summary = {
            "total": len(results),
            "passed": sum(1 for r in results.values() if r.get("passed", False)),
            "failed": sum(1 for r in results.values() if not r.get("passed", False)),
            "results": results,
        }

        summary_file = output_path / "batch_summary.json"
        with open(summary_file, "w", encoding="utf-8") as summary_handle:
            json.dump(summary, summary_handle, indent=2)

        print("\nBatch processing complete:")
        print(f"  Total files: {summary['total']}")
        print(f"  Passed: {summary['passed']}")
        print(f"  Failed: {summary['failed']}")
        print(f"Summary report saved to: {summary_file}")

        return 0 if summary["failed"] == 0 else 2

    except Exception as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main entry point for the command-line interface.

    Args:
        argv: Optional argument list (defaults to sys.argv[1:])

    Returns:
        int: Exit code
    """
    parser = build_parser()
    args_list = sys.argv[1:] if argv is None else argv

    # Also accept `stl2scad input.stl output.scad --pipeline segmentation`.
    if args_list and args_list[0].lower().endswith(".stl"):
        args_list = ["convert", *args_list]

    if not args_list:
        parser.print_help()
        return 1

    try:
        parsed = parser.parse_args(args_list)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1

    handler = getattr(parsed, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return int(handler(parsed))


if __name__ == "__main__":
    sys.exit(main())
