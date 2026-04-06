"""
Phase 0 tests for benchmark fixtures and performance baseline tooling.
"""

from stl.mesh import Mesh

from stl2scad.core.benchmark_fixtures import (
    REQUIRED_PHASE0_FIXTURE_NAMES,
    generate_benchmark_fixture_set,
)
from stl2scad.core.converter import validate_stl
from stl2scad.core.perf_baseline import run_conversion_perf_baseline


def test_generate_benchmark_fixture_set_contains_required_phase0_items(test_output_dir):
    fixtures_dir = test_output_dir / "benchmark_fixtures"
    manifest = generate_benchmark_fixture_set(fixtures_dir, overwrite=True)

    names = {fixture["name"] for fixture in manifest["fixtures"]}
    assert set(REQUIRED_PHASE0_FIXTURE_NAMES).issubset(names)

    manifest_path = fixtures_dir / "manifest.json"
    assert manifest_path.exists()

    for fixture in manifest["fixtures"]:
        fixture_path = fixtures_dir / fixture["file"]
        assert fixture_path.exists()
        assert fixture_path.stat().st_size > 0


def test_generated_benchmark_fixtures_are_valid_stl_meshes(test_output_dir):
    fixtures_dir = test_output_dir / "benchmark_fixtures"
    manifest = generate_benchmark_fixture_set(fixtures_dir, overwrite=True)

    for fixture in manifest["fixtures"]:
        fixture_path = fixtures_dir / fixture["file"]
        mesh = Mesh.from_file(str(fixture_path))
        validate_stl(mesh, tolerance=1e-6)
        assert len(mesh.vectors) > 0


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
