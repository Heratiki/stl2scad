"""
Tests for recognition sweep reporting and regression gates.
"""

from pathlib import Path

from stl2scad.core.benchmark_fixtures import generate_benchmark_fixture_set
from stl2scad.core.recognition_sweep import (
    SweepGateConfig,
    _infer_primitive_type,
    discover_fixtures,
    evaluate_sweep_gates,
    run_recognition_sweep,
)


def test_discover_fixtures_filters_manifest_entries(test_output_dir):
    fixtures_dir = test_output_dir / "benchmark_fixtures"
    generate_benchmark_fixture_set(fixtures_dir, overwrite=True)

    fixtures = discover_fixtures(
        fixtures_dir=fixtures_dir,
        categories=("primitive",),
        fixture_names=("primitive_box_axis_aligned", "primitive_sphere"),
    )

    names = {item["name"] for item in fixtures}
    assert names == {"primitive_box_axis_aligned", "primitive_sphere"}
    for item in fixtures:
        assert item["category"] == "primitive"
        assert Path(item["path"]).suffix.lower() == ".stl"


def test_run_recognition_sweep_reports_native_detection_for_box(test_output_dir):
    fixtures_dir = test_output_dir / "benchmark_fixtures"
    generate_benchmark_fixture_set(fixtures_dir, overwrite=True)

    fixtures = discover_fixtures(
        fixtures_dir=fixtures_dir,
        fixture_names=("primitive_box_axis_aligned",),
    )
    report = run_recognition_sweep(
        fixtures=fixtures,
        backends=("native",),
        tolerance=0.01,
    )

    summary = report["summary"]["by_backend"]["native"]
    assert summary["total"] == 1
    assert summary["detected"] == 1
    assert summary["detection_rate"] == 1.0
    assert "box" in summary["detected_primitives"]


def test_evaluate_sweep_gates_reports_failures_for_missing_primitive(test_output_dir):
    fixtures_dir = test_output_dir / "benchmark_fixtures"
    generate_benchmark_fixture_set(fixtures_dir, overwrite=True)

    fixtures = discover_fixtures(
        fixtures_dir=fixtures_dir,
        fixture_names=("primitive_sphere",),
    )
    report = run_recognition_sweep(
        fixtures=fixtures,
        backends=("native",),
        tolerance=0.01,
    )

    failures = evaluate_sweep_gates(
        report,
        SweepGateConfig(min_detection_rate=1.0, required_primitives=("sphere",)),
    )
    assert len(failures) >= 1
    assert any("detection_rate" in failure for failure in failures)
    assert any("missing required primitive" in failure for failure in failures)


def test_infer_primitive_type_detects_composite_union_before_cube():
    scad = (
        "union() {\n"
        "    translate([0, 0, 0]) cube([1, 1, 1]);\n"
        "    translate([2, 0, 0]) cube([1, 1, 1]);\n"
        "}\n"
    )
    assert _infer_primitive_type(scad) == "composite_union"


def test_evaluate_sweep_gates_flags_backend_unavailable_data():
    report = {
        "summary": {
            "by_backend": {
                "trimesh_manifold": {
                    "total": 2,
                    "detected": 0,
                    "detection_rate": 0.0,
                    "error_count": 0,
                    "detected_primitives": [],
                    "primitive_counts": {},
                    "fallback_reason_counts": {"backend_unavailable": 2},
                }
            }
        }
    }

    failures = evaluate_sweep_gates(
        report,
        SweepGateConfig(min_detection_rate=0.5, required_primitives=("sphere",)),
    )
    assert any("backend_unavailable" in failure for failure in failures)
