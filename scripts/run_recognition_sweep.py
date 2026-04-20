"""
Run recognition sweeps across fixture sets and enforce regression gates.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.core.recognition_sweep import (
    SweepGateConfig,
    discover_fixtures,
    evaluate_sweep_gates,
    run_recognition_sweep,
    write_sweep_report,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run recognition backend coverage sweeps and gate regressions."
    )
    parser.add_argument(
        "--fixtures-dir",
        default="tests/data/benchmark_fixtures",
        help="Fixture directory (manifest-based when manifest.json exists).",
    )
    parser.add_argument(
        "--output",
        default="artifacts/recognition_sweep.json",
        help="Path to JSON report output.",
    )
    parser.add_argument(
        "--backends",
        default="native,trimesh_manifold,cgal",
        help="Comma-separated recognition backends to evaluate.",
    )
    parser.add_argument(
        "--fixture-names",
        default="",
        help="Comma-separated fixture names from manifest to include.",
    )
    parser.add_argument(
        "--fixture-categories",
        default="",
        help="Comma-separated manifest categories to include.",
    )
    parser.add_argument(
        "--fixture-tags",
        default="",
        help="Comma-separated manifest tags; include fixture when any tag matches.",
    )
    parser.add_argument(
        "--extra-glob",
        action="append",
        default=[],
        help="Additional glob pattern under fixtures-dir (repeatable).",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.01,
        help="Recognition tolerance passed to backend detectors.",
    )

    parser.add_argument(
        "--min-detection-rate",
        type=float,
        default=None,
        help="Gate: minimum detection rate required for each backend (0..1).",
    )
    parser.add_argument(
        "--require-primitives",
        default="",
        help="Gate: comma-separated primitive families each backend must detect at least once.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=0,
        help="Gate: maximum allowed execution errors per backend.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when no fixtures are discovered.",
    )
    return parser


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.tolerance <= 0:
        raise ValueError("--tolerance must be > 0")
    if args.min_detection_rate is not None and not (0.0 <= args.min_detection_rate <= 1.0):
        raise ValueError("--min-detection-rate must be between 0 and 1")
    if args.max_errors < 0:
        raise ValueError("--max-errors must be >= 0")

    fixtures = discover_fixtures(
        fixtures_dir=Path(args.fixtures_dir),
        fixture_names=_split_csv(args.fixture_names),
        categories=_split_csv(args.fixture_categories),
        tags=_split_csv(args.fixture_tags),
        extra_globs=args.extra_glob,
    )

    if not fixtures:
        message = "No fixtures discovered for recognition sweep."
        if args.strict:
            raise RuntimeError(message)
        print(message)
        report = {
            "schema_version": 1,
            "summary": {
                "total_rows": 0,
                "backends": [],
                "by_backend": {},
            },
            "results": [],
        }
        write_sweep_report(report, Path(args.output))
        print(f"Recognition sweep report written to: {args.output}")
        return 0

    backends = _split_csv(args.backends)
    if not backends:
        raise ValueError("At least one backend must be provided via --backends")

    report = run_recognition_sweep(
        fixtures=fixtures,
        backends=backends,
        tolerance=args.tolerance,
    )
    write_sweep_report(report, Path(args.output))

    gate = SweepGateConfig(
        min_detection_rate=args.min_detection_rate,
        required_primitives=_split_csv(args.require_primitives),
        max_errors=args.max_errors,
    )
    failures = evaluate_sweep_gates(report, gate)

    print(f"Recognition sweep report written to: {args.output}")
    summary = report.get("summary", {}).get("by_backend", {})
    for backend in sorted(summary.keys()):
        info = summary[backend]
        print(
            f"- {backend}: detected {info['detected']}/{info['total']} "
            f"({info['detection_rate']:.3f}), errors={info['error_count']}"
        )

    if failures:
        print("Gate failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 2

    print("All recognition sweep gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
