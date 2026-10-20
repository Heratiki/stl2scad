"""
Phase 0 tests for benchmark fixtures and performance baseline tooling.
"""

from stl.mesh import Mesh

from stl2scad.core.benchmark_fixtures import (
    REQUIRED_PHASE0_FIXTURE_NAMES,
    generate_benchmark_fixture_set,
)
from stl2scad.core.conversion import validate_stl


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
