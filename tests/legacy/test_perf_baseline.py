"""
Legacy conversion perf-baseline test, moved from
tests/test_phase0_benchmarks.py by T-004 (the benchmark fixture tests stay
there).
"""

from stl.mesh import Mesh

from stl2scad.core.benchmark_fixtures import (
    REQUIRED_PHASE0_FIXTURE_NAMES,
    generate_benchmark_fixture_set,
)
from stl2scad.core.conversion import validate_stl
from stl2scad.legacy.perf_baseline import run_conversion_perf_baseline


def test_perf_baseline_runner_writes_report(test_output_dir):
    fixtures_dir = test_output_dir / "benchmark_fixtures"
    generate_benchmark_fixture_set(fixtures_dir, overwrite=True)

    report_path = test_output_dir / "perf_baseline.json"
    report = run_conversion_perf_baseline(
        fixtures_dir=fixtures_dir,
        output_json=report_path,
        repeat=1,
        categories=("performance",),
        parametric_modes=(False,),
        recognition_backend="native",
    )

    assert report_path.exists()
    assert "results" in report
    assert len(report["results"]) > 0
    for row in report["results"]:
        assert row["elapsed_mean_seconds"] >= 0.0
