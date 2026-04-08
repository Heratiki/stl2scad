"""
Tests for STL to SCAD conversion functionality.
"""

import pytest
from stl2scad.core.converter import stl2scad, validate_stl, STLValidationError
from stl2scad.core.benchmark_fixtures import ensure_benchmark_fixtures
from stl2scad.core import recognition as recognition_module
import stl
from .utils import setup_logging, verify_debug_files
import numpy


def test_basic_conversion(sample_stl_file, test_output_dir):
    """Test basic STL to SCAD conversion without debug features."""
    log = setup_logging()
    log("\nTesting Basic STL to SCAD Conversion")

    output_file = test_output_dir / "test_output.scad"

    try:
        # Run conversion
        stats = stl2scad(str(sample_stl_file), str(output_file))

        # Verify output file exists
        assert output_file.exists(), "Output SCAD file not created"
        assert output_file.stat().st_size > 0, "Output SCAD file is empty"

        # Verify conversion statistics
        log("\nConversion Statistics:")
        log(f"Original vertices: {stats.original_vertices}")
        log(f"Deduplicated vertices: {stats.deduplicated_vertices}")
        log(f"Faces: {stats.faces}")

        # Verify metadata
        log("\nMetadata:")
        for key, value in stats.metadata.items():
            log(f"{key}: {value}")

        assert (
            stats.deduplicated_vertices <= stats.original_vertices
        ), "Vertex deduplication failed"
        assert stats.faces > 0, "No faces in output"

    except Exception as e:
        log(f"Error during conversion: {str(e)}", "ERROR")
        raise


def test_debug_conversion(sample_stl_file, test_output_dir):
    """Test STL to SCAD conversion with debug features enabled."""
    log = setup_logging()
    log("\nTesting Debug STL to SCAD Conversion")

    output_file = test_output_dir / "test_output.scad"

    try:
        # Run conversion with debug enabled
        stats = stl2scad(str(sample_stl_file), str(output_file), debug=True)

        # Get debug file paths
        debug_base = output_file.stem
        debug_files = {
            "scad": test_output_dir / f"{debug_base}_debug.scad",
            "json": test_output_dir / f"{debug_base}_analysis.json",
            "echo": test_output_dir / f"{debug_base}_debug.echo",
            "png": test_output_dir / f"{debug_base}_preview.png",
        }

        # Verify debug files
        files_status = verify_debug_files(debug_files)
        log("\nChecking debug files:")
        for name, status in files_status.items():
            log(f"{name}: {status['status']} ({status['size']:,} bytes)")
            if not status["exists"] or status["size"] == 0:
                log(f"Warning: {name} file is missing or empty", "WARNING")

        # Verify debug SCAD file content
        debug_scad = debug_files["scad"]
        if debug_scad.exists():
            content = debug_scad.read_text()
            assert "import" in content, "Debug SCAD missing import statement"
            assert "translate" in content, "Debug SCAD missing translation"
            assert "debug_info" in content, "Debug SCAD missing debug info"

    except Exception as e:
        log(f"Error during debug conversion: {str(e)}", "ERROR")
        raise


def test_stl_validation(sample_stl_file):
    """Test STL file validation."""
    log = setup_logging()
    log("\nTesting STL Validation")

    try:
        # Load and validate STL
        mesh = stl.mesh.Mesh.from_file(str(sample_stl_file))
        validate_stl(mesh)
        log("STL validation passed")

        # Test validation with empty mesh
        empty_mesh = stl.mesh.Mesh(numpy.array([], dtype=stl.mesh.Mesh.dtype))
        with pytest.raises(STLValidationError) as e:
            validate_stl(empty_mesh)
        assert "Empty STL file" in str(e.value)
        log("Empty mesh validation correctly failed")

    except Exception as e:
        log(f"Error during STL validation: {str(e)}", "ERROR")
        raise


def test_vertex_deduplication(sample_stl_file, test_output_dir):
    """Test vertex deduplication functionality."""
    log = setup_logging()
    log("\nTesting Vertex Deduplication")

    output_file = test_output_dir / "dedup_test.scad"

    # Test with different tolerances
    tolerances = [1e-6, 1e-3, 1e-9]
    for tol in tolerances:
        log(f"\nTesting with tolerance: {tol}")
        stats = stl2scad(str(sample_stl_file), str(output_file), tolerance=tol)
        reduction = 100 * (1 - stats.deduplicated_vertices / stats.original_vertices)
        log(f"Vertex reduction: {reduction:.1f}%")
        assert stats.deduplicated_vertices > 0, "No vertices after deduplication"


def test_degenerate_faces_filtered(test_output_dir):
    """Degenerate faces created by tolerance snapping should be removed."""
    log = setup_logging()
    log("\nTesting Degenerate Face Filtering")

    input_file = test_output_dir / "degenerate_input.stl"
    output_file = test_output_dir / "degenerate_output.scad"

    # Two triangles: one valid, one that collapses with tolerance=1e-3.
    mesh = stl.mesh.Mesh(numpy.zeros(2, dtype=stl.mesh.Mesh.dtype))
    mesh.vectors[0] = numpy.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    mesh.vectors[1] = numpy.array(
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0001], [0.0, 1.0, 0.0]]
    )
    mesh.save(str(input_file))

    stats = stl2scad(str(input_file), str(output_file), tolerance=1e-3)
    assert output_file.exists(), "Output SCAD file not created"
    assert stats.faces == 1, "One degenerate face should have been filtered"
    assert stats.metadata.get("degenerate_faces_removed") == "1"


def test_invalid_tolerance_raises(sample_stl_file, test_output_dir):
    """API should reject zero/negative tolerance values."""
    output_file = test_output_dir / "invalid_tolerance.scad"
    with pytest.raises(ValueError, match="Tolerance must be positive"):
        stl2scad(str(sample_stl_file), str(output_file), tolerance=0)


def test_parametric_cube_recognition(sample_stl_file, test_output_dir):
    """Test that a pure cube STL is recognized and exported as a parametric cube()."""
    output_file = test_output_dir / "parametric_cube.scad"
    # Convert with parametric enabled
    stl2scad(str(sample_stl_file), str(output_file), parametric=True)

    assert output_file.exists(), "Output SCAD file not created"
    content = output_file.read_text()

    # It should contain cube() and translate() and NOT polyhedron()
    assert "cube([" in content, "Missing parametric cube() call"
    assert "translate([" in content, "Missing translate() call for position"
    assert "polyhedron" not in content, "Should not emit polyhedron for a basic cube"


def test_parametric_cube_recognition_backend_alias(sample_stl_file, test_output_dir):
    """`default` backend alias should resolve to native backend behavior."""
    output_file = test_output_dir / "parametric_cube_default_backend.scad"
    stl2scad(
        str(sample_stl_file),
        str(output_file),
        parametric=True,
        recognition_backend="default",
    )

    content = output_file.read_text()
    assert (
        "cube([" in content
    ), "Missing parametric cube() call for default backend alias"
    assert "polyhedron" not in content, "Should not emit polyhedron for a detected cube"


def test_invalid_recognition_backend_raises(sample_stl_file, test_output_dir):
    """Unsupported backend ids should fail fast in parametric mode."""
    output_file = test_output_dir / "invalid_backend.scad"
    with pytest.raises(ValueError, match="Unsupported recognition backend"):
        stl2scad(
            str(sample_stl_file),
            str(output_file),
            parametric=True,
            recognition_backend="does_not_exist",
        )


def test_phase1_trimesh_backend_recognizes_sphere_fixture(test_data_dir, monkeypatch):
    """Phase 1 backend should classify sphere fixture as sphere()."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    mesh = stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_sphere.stl"))

    monkeypatch.setattr(
        recognition_module,
        "_has_trimesh_manifold_dependencies",
        lambda: True,
    )

    scad = recognition_module.detect_primitive(
        mesh,
        backend="trimesh_manifold",
    )
    assert scad is not None
    assert "sphere(" in scad


def test_phase1_trimesh_backend_recognizes_rotated_cylinder_fixture(
    test_data_dir, monkeypatch
):
    """Phase 1 backend should classify rotated cylinder and emit transform + cylinder()."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    mesh = stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_cylinder_rotated.stl"))

    monkeypatch.setattr(
        recognition_module,
        "_has_trimesh_manifold_dependencies",
        lambda: True,
    )

    scad = recognition_module.detect_primitive(
        mesh,
        backend="trimesh_manifold",
    )
    assert scad is not None
    assert "cylinder(" in scad
    assert "rotate(" in scad


def test_phase1_trimesh_backend_recognizes_cone_fixture(test_data_dir, monkeypatch):
    """Phase 1 backend should classify cone fixture as tapered cylinder()."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    mesh = stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_cone.stl"))

    monkeypatch.setattr(
        recognition_module,
        "_has_trimesh_manifold_dependencies",
        lambda: True,
    )

    scad = recognition_module.detect_primitive(
        mesh,
        backend="trimesh_manifold",
    )
    assert scad is not None
    assert "cylinder(" in scad
    assert "r1=" in scad and "r2=" in scad


def test_phase1_trimesh_backend_prefers_box_for_box_fixture(test_data_dir, monkeypatch):
    """Box fixture should resolve to cube() instead of a cylinder tie-break."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    mesh = stl.mesh.Mesh.from_file(str(fixtures_dir / "primitive_box_axis_aligned.stl"))

    monkeypatch.setattr(
        recognition_module,
        "_has_trimesh_manifold_dependencies",
        lambda: True,
    )

    scad = recognition_module.detect_primitive(mesh, backend="trimesh_manifold")
    assert scad is not None
    assert "cube(" in scad
    assert "cylinder(" not in scad


def test_phase1_trimesh_backend_multicomponent_union_for_disconnected_boxes(
    test_data_dir, monkeypatch
):
    """Disjoint multi-component fixture should emit union() with per-component primitives."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    mesh = stl.mesh.Mesh.from_file(
        str(fixtures_dir / "composite_disconnected_dual_box.stl")
    )

    monkeypatch.setattr(
        recognition_module,
        "_has_trimesh_manifold_dependencies",
        lambda: True,
    )

    scad = recognition_module.detect_primitive(mesh, backend="trimesh_manifold")
    assert scad is not None
    assert "union()" in scad
    assert scad.count("cube(") >= 2


def test_phase1_trimesh_backend_fallback_for_subtraction_shell(
    test_data_dir, monkeypatch
):
    """Nested/overlapping component shells should fallback to polyhedron path."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    mesh = stl.mesh.Mesh.from_file(
        str(fixtures_dir / "composite_subtraction_shell.stl")
    )

    monkeypatch.setattr(
        recognition_module,
        "_has_trimesh_manifold_dependencies",
        lambda: True,
    )

    scad = recognition_module.detect_primitive(mesh, backend="trimesh_manifold")
    assert scad is None


def test_phase1_trimesh_backend_fallback_for_stanford_bunny(test_data_dir, monkeypatch):
    """Non-primitive organic mesh should fallback (no primitive candidate)."""
    mesh = stl.mesh.Mesh.from_file(str(test_data_dir / "Stanford_Bunny_sample.stl"))

    monkeypatch.setattr(
        recognition_module,
        "_has_trimesh_manifold_dependencies",
        lambda: True,
    )

    scad = recognition_module.detect_primitive(mesh, backend="trimesh_manifold")
    assert scad is None


def test_phase1_converter_fallback_emits_polyhedron_for_subtraction_shell(
    test_data_dir, test_output_dir
):
    """Converter should keep safe polyhedron fallback when backend cannot safely reconstruct."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)

    input_file = fixtures_dir / "composite_subtraction_shell.stl"
    output_file = test_output_dir / "subtraction_shell_parametric.scad"
    stl2scad(
        str(input_file),
        str(output_file),
        parametric=True,
        recognition_backend="trimesh_manifold",
    )

    content = output_file.read_text()
    assert "polyhedron(" in content
    assert "union()" not in content
