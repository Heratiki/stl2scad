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
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from stl2scad.core.converter import ConversionStats, STLValidationError, stl2scad
from stl2scad.core.acceleration import get_acceleration_report
from stl2scad.core.feature_graph import (
    build_feature_graph_for_folder,
    build_feature_graph_for_stl,
    emit_feature_graph_scad_preview,
)
from stl2scad.core.feature_inventory import (
    InventoryConfig,
    InventorySelectionConfig,
    analyze_stl_folder,
    analyze_stl_folder_for_feature_graphs,
    build_feature_graphs_from_inventory,
)
from stl2scad.core.recognition import SUPPORTED_RECOGNITION_BACKENDS
from stl2scad.core.verification import (
    generate_comparison_visualization,
    generate_verification_report_html,
    verify_conversion,
)


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
        "--tolerance",
        type=_positive_float,
        default=1e-6,
        help="Vertex deduplication tolerance (default: 1e-6)",
    )
    convert_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (renders SCAD diagnostic artifacts)",
    )
    convert_parser.add_argument(
        "--parametric",
        action="store_true",
        help="Try to detect and write primitives instead of a flat polyhedron",
    )
    convert_parser.add_argument(
        "--recognition-backend",
        choices=list(SUPPORTED_RECOGNITION_BACKENDS),
        default="native",
        help="Recognition backend for parametric mode (default: native)",
    )
    convert_parser.add_argument(
        "--compute-backend",
        choices=["auto", "cpu", "gpu"],
        default="auto",
        help="Compute backend for heavy array ops (default: auto)",
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
        help="Try to detect and write primitives instead of a flat polyhedron during verification conversion",
    )
    verify_parser.add_argument(
        "--recognition-backend",
        choices=list(SUPPORTED_RECOGNITION_BACKENDS),
        default="native",
        help="Recognition backend for parametric conversion (default: native)",
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
        default="auto",
        help="Compute backend for conversion step when SCAD must be generated (default: auto)",
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
        help="Try to detect and write primitives instead of a flat polyhedron during batch conversion",
    )
    batch_parser.add_argument(
        "--recognition-backend",
        choices=list(SUPPORTED_RECOGNITION_BACKENDS),
        default="native",
        help="Recognition backend for parametric conversion (default: native)",
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
        default="auto",
        help="Compute backend for conversion step (default: auto)",
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
        help="Analyze STL folders for feature-level reconstruction signals",
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
    feature_inventory_parser.set_defaults(handler=feature_inventory_command)

    feature_graph_parser = subparsers.add_parser(
        "feature-graph",
        help="Build conservative feature graphs for STL files or folders",
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
        "--scad-preview",
        default=None,
        help="Optional SCAD preview output path for a single STL input",
    )
    feature_graph_parser.set_defaults(handler=feature_graph_command)

    feature_graph_inventory_parser = subparsers.add_parser(
        "feature-graph-from-inventory",
        help="Build feature graphs only for mechanical candidates from an inventory report",
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
    feature_graph_inventory_parser.set_defaults(
        handler=feature_graph_from_inventory_command
    )

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
        choices=list(SUPPORTED_RECOGNITION_BACKENDS),
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
        help="Optional STL directory for inventory + inventory-prefiltered feature graph",
    )
    maintainer_parser.add_argument(
        "--inventory-output",
        default="artifacts/feature_inventory_maintainer.json",
        help="Output path for optional inventory JSON",
    )
    maintainer_parser.add_argument(
        "--feature-graph-output",
        default="artifacts/feature_graph_maintainer.json",
        help="Output path for optional feature-graph JSON",
    )
    maintainer_parser.add_argument(
        "--workers",
        type=_non_negative_int,
        default=0,
        help="Workers for optional STL inventory/graph steps. Use 0 for auto",
    )
    maintainer_parser.add_argument(
        "--max-files",
        type=_non_negative_int,
        default=None,
        help="Optional cap for STL files in optional inventory/graph steps",
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
                    "tests/test_feature_graph.py",
                    "tests/test_feature_inventory.py",
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

    if args.stl_dir:
        steps.append(
            MaintainerStep(
                name="Corpus feature inventory",
                command=[
                    python_exe,
                    "-m",
                    "stl2scad",
                    "feature-inventory",
                    args.stl_dir,
                    "--output",
                    args.inventory_output,
                    "--workers",
                    str(args.workers),
                ],
            )
        )
        graph_command = [
            python_exe,
            "-m",
            "stl2scad",
            "feature-graph",
            args.stl_dir,
            "--output",
            args.feature_graph_output,
            "--workers",
            str(args.workers),
            "--inventory-prefilter",
            "--inventory-output",
            args.inventory_output,
        ]
        if args.max_files is not None:
            graph_command.extend(["--max-files", str(args.max_files)])
        steps.append(
            MaintainerStep(
                name="Corpus feature graph (inventory-prefilter)",
                command=graph_command,
            )
        )

    return steps


def maintainer_command(args: argparse.Namespace) -> int:
    """Execute the chained maintainer workflow."""
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


def feature_inventory_command(args: argparse.Namespace) -> int:
    """Execute the feature-inventory command."""
    try:
        workers = _resolve_workers(args.workers)

        def _progress(done: int, total: int, path: str) -> None:
            print(
                f"\r[{done}/{total}] {Path(path).name}",
                end="",
                flush=True,
                file=sys.stderr,
            )
            if done == total:
                print(file=sys.stderr)

        report = analyze_stl_folder(
            input_dir=Path(args.input_dir),
            output_json=Path(args.output),
            config=InventoryConfig(
                recursive=not args.no_recursive,
                max_files=args.max_files,
                workers=workers,
            ),
            progress_callback=_progress,
        )
        summary = report["summary"]
        print(f"Feature inventory written to: {args.output}")
        print(f"Files analyzed: {summary['file_count']}")
        print(f"Workers: {workers}")
        print(f"OK: {summary['ok_count']}")
        print(f"Errors: {summary['error_count']}")
        print(f"Classifications: {summary['classification_counts']}")
        print(f"Candidate features: {summary['candidate_feature_counts']}")
        return 0
    except FileNotFoundError as exc:
        print(f"Error: File not found - {str(exc)}", file=sys.stderr)
        return 1
    except NotADirectoryError as exc:
        print(f"Error: Not a directory - {str(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        return 1


def feature_graph_command(args: argparse.Namespace) -> int:
    """Execute the feature-graph command."""
    try:
        input_path = Path(args.input_path)
        output_path = Path(args.output)
        has_inventory_selection_filters = any(
            (
                args.inventory_min_mechanical_score is not None,
                args.inventory_max_organic_score is not None,
                args.inventory_allow_non_mechanical_primary,
            )
        )

        if not input_path.is_dir() and (
            args.inventory_prefilter or args.inventory_output or has_inventory_selection_filters
        ):
            raise ValueError(
                "--inventory-prefilter, --inventory-output, and --inventory-* selection options require a directory input"
            )
        if has_inventory_selection_filters and not args.inventory_prefilter:
            raise ValueError(
                "--inventory-* selection options require --inventory-prefilter"
            )

        if input_path.is_dir():
            workers = _resolve_workers(args.workers)

            def _progress(done: int, total: int, path: str) -> None:
                print(
                    f"\r[{done}/{total}] {Path(path).name}",
                    end="",
                    flush=True,
                    file=sys.stderr,
                )
                if done == total:
                    print(file=sys.stderr)

            if args.inventory_prefilter:

                def _inventory_progress(done: int, total: int, path: str) -> None:
                    print(
                        f"\r[inventory {done}/{total}] {Path(path).name}",
                        end="",
                        flush=True,
                        file=sys.stderr,
                    )
                    if done == total:
                        print(file=sys.stderr)

                def _graph_progress(done: int, total: int, path: str) -> None:
                    print(
                        f"\r[graph {done}/{total}] {Path(path).name}",
                        end="",
                        flush=True,
                        file=sys.stderr,
                    )
                    if done == total:
                        print(file=sys.stderr)

                report = analyze_stl_folder_for_feature_graphs(
                    input_dir=input_path,
                    output_json=output_path,
                    inventory_config=InventoryConfig(
                        recursive=not args.no_recursive,
                        max_files=args.max_files,
                        workers=workers,
                    ),
                    graph_workers=workers,
                    selection_config=InventorySelectionConfig(
                        require_primary_mechanical=(
                            not args.inventory_allow_non_mechanical_primary
                        ),
                        min_mechanical_score=args.inventory_min_mechanical_score,
                        max_organic_score=args.inventory_max_organic_score,
                    ),
                    inventory_output_json=(
                        Path(args.inventory_output)
                        if args.inventory_output is not None
                        else None
                    ),
                    inventory_progress_callback=_inventory_progress,
                    graph_progress_callback=_graph_progress,
                )
            else:
                report = build_feature_graph_for_folder(
                    input_path,
                    output_path,
                    recursive=not args.no_recursive,
                    max_files=args.max_files,
                    workers=workers,
                    progress_callback=_progress,
                )
            summary = report["summary"]
            print(f"Feature graph report written to: {output_path}")
            if args.inventory_prefilter:
                inventory_summary = report["inventory_summary"]
                selection = report["selection"]
                print(f"Files analyzed: {inventory_summary['file_count']}")
                print(
                    "Mechanical candidates processed: "
                    f"{selection['mechanical_candidate_count']}"
                )
                print(
                    "Skipped non-mechanical: "
                    f"{selection['skipped_non_mechanical_count']}"
                )
                if selection.get("skipped_below_score_count", 0) > 0:
                    print(
                        "Skipped below score threshold: "
                        f"{selection['skipped_below_score_count']}"
                    )
                if selection.get("selected_non_mechanical_primary_count", 0) > 0:
                    print(
                        "Selected non-mechanical primary: "
                        f"{selection['selected_non_mechanical_primary_count']}"
                    )
                if args.inventory_output:
                    print(f"Inventory report written to: {args.inventory_output}")
            else:
                print(f"Files analyzed: {summary['file_count']}")
            print(f"Workers: {workers}")
            print(f"Errors: {summary['error_count']}")
            print(f"Features: {summary['feature_counts']}")
            return 0

        graph = build_feature_graph_for_stl(input_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as output_handle:
            json.dump(graph, output_handle, indent=2)
        print(f"Feature graph written to: {output_path}")
        print(f"Features: {len(graph['features'])}")

        if args.scad_preview:
            scad = emit_feature_graph_scad_preview(graph)
            if scad is None:
                print(
                    "SCAD preview not emitted: no high-confidence supported feature combination."
                )
            else:
                scad_path = Path(args.scad_preview)
                scad_path.parent.mkdir(parents=True, exist_ok=True)
                with open(scad_path, "w", encoding="utf-8") as scad_handle:
                    scad_handle.write(scad)
                print(f"SCAD preview written to: {scad_path}")
        return 0
    except FileNotFoundError as exc:
        print(f"Error: File not found - {str(exc)}", file=sys.stderr)
        return 1
    except NotADirectoryError as exc:
        print(f"Error: Not a directory - {str(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        return 1


def feature_graph_from_inventory_command(args: argparse.Namespace) -> int:
    """Execute the feature-graph-from-inventory command."""
    try:
        workers = _resolve_workers(args.workers)

        def _progress(done: int, total: int, path: str) -> None:
            print(
                f"\r[{done}/{total}] {Path(path).name}",
                end="",
                flush=True,
                file=sys.stderr,
            )
            if done == total:
                print(file=sys.stderr)

        report = build_feature_graphs_from_inventory(
            inventory=Path(args.inventory_json),
            output_json=Path(args.output),
            workers=workers,
            selection_config=InventorySelectionConfig(
                require_primary_mechanical=(
                    not args.inventory_allow_non_mechanical_primary
                ),
                min_mechanical_score=args.inventory_min_mechanical_score,
                max_organic_score=args.inventory_max_organic_score,
            ),
            progress_callback=_progress,
        )
        summary = report["summary"]
        selection = report["selection"]
        print(f"Feature graph report written to: {args.output}")
        print(
            "Mechanical candidates processed: "
            f"{selection['mechanical_candidate_count']}"
        )
        if selection.get("skipped_below_score_count", 0) > 0:
            print(
                "Skipped below score threshold: "
                f"{selection['skipped_below_score_count']}"
            )
        if selection.get("selected_non_mechanical_primary_count", 0) > 0:
            print(
                "Selected non-mechanical primary: "
                f"{selection['selected_non_mechanical_primary_count']}"
            )
        print(f"Workers: {workers}")
        print(f"Errors: {summary['error_count']}")
        print(f"Features: {summary['feature_counts']}")

        if args.scad_preview_dir:
            preview_root = Path(args.scad_preview_dir)
            preview_root.mkdir(parents=True, exist_ok=True)
            emitted_count = 0
            skipped_count = 0
            for graph in report.get("graphs", []):
                if graph.get("status") == "error":
                    skipped_count += 1
                    continue
                scad = emit_feature_graph_scad_preview(graph)
                if scad is None:
                    skipped_count += 1
                    continue

                source_file = str(graph.get("source_file", "graph.stl"))
                relative_source = Path(source_file)
                output_path = preview_root / relative_source.with_suffix(".preview.scad")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write(scad)
                emitted_count += 1

            print(f"SCAD previews emitted: {emitted_count}")
            print(f"SCAD previews skipped: {skipped_count}")

        return 0
    except FileNotFoundError as exc:
        print(f"Error: File not found - {str(exc)}", file=sys.stderr)
        return 1
    except NotADirectoryError as exc:
        print(f"Error: Not a directory - {str(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        return 1


def convert_command(args: argparse.Namespace) -> int:
    """
    Execute the convert command.

    Args:
        args: Parsed command-line arguments for convert

    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    try:
        print(f"Converting {args.input_file} to {args.output_file}")
        print(f"Using tolerance: {args.tolerance}")
        if args.debug:
            print("Debug mode enabled")
        if args.parametric:
            print("Parametric primitive recognition enabled")
            print(f"Recognition backend: {args.recognition_backend}")

        stats = stl2scad(
            args.input_file,
            args.output_file,
            args.tolerance,
            args.debug,
            getattr(args, "parametric", False),
            recognition_backend=getattr(args, "recognition_backend", "native"),
            compute_backend=getattr(args, "compute_backend", "auto"),
        )
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
    temp_dir_obj: Optional[tempfile.TemporaryDirectory[str]] = None
    try:
        tolerance = _tolerance_from_args(args)
        visualize = bool(args.visualize or args.html_report)

        print(f"Verifying conversion of {args.input_file}")
        if args.output_file:
            print(f"Using existing SCAD file: {args.output_file}")
            scad_file_to_use = args.output_file
        else:
            print("Will generate temporary SCAD file")
            temp_dir_obj = tempfile.TemporaryDirectory()
            scad_file_to_use = str(
                Path(temp_dir_obj.name) / f"{Path(args.input_file).stem}.scad"
            )
            stl2scad(
                args.input_file,
                scad_file_to_use,
                parametric=getattr(args, "parametric", False),
                recognition_backend=getattr(args, "recognition_backend", "native"),
                compute_backend=getattr(args, "compute_backend", "auto"),
            )

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
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()


def batch_command(args: argparse.Namespace) -> int:
    """
    Execute the batch command.

    Args:
        args: Parsed command-line arguments for batch

    Returns:
        int: Exit code (0 for success, 1 for error, 2 for verification failures)
    """
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
                stl2scad(
                    str(stl_file),
                    str(scad_file),
                    parametric=getattr(args, "parametric", False),
                    recognition_backend=getattr(args, "recognition_backend", "native"),
                    compute_backend=getattr(args, "compute_backend", "auto"),
                )
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
