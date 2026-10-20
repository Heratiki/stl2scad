"""IR round-trip tests built through the legacy feature graph.

Moved from tests/test_ir.py by T-004; the pure IR tests stay there.
"""

from pathlib import Path
import pytest

from stl2scad.legacy.feature_graph import (
    _build_ir_tree,
    _ir_cutout_node,
    _ir_pattern_node,
    _ir_revolve_node,
    build_feature_graph_for_stl,
    emit_node,
)
from stl2scad.core.ir import (
    BooleanDifference,
    BooleanUnion,
    Boss,
    ChamferOrFilletEdge,
    Constraint,
    ExtrudeLinear,
    ExtrudeRevolve,
    FallbackMesh,
    Fillet,
    HoleBlind,
    HoleCounterbore,
    HoleThrough,
    Interpretation,
    IRNode,
    Parameter,
    PatternGrid,
    PatternLinear,
    PrimitiveBox,
    PrimitiveCylinder,
    PrimitivePlate,
    RectangularCutout,
    RectangularPocket,
    Sketch2D,
    Slot,
    TransformMultMatrix,
    TransformRotate,
    TransformTranslate,
    from_dict,
)
from tests.legacy.test_feature_graph import (
    _create_box_with_hole,
    _create_chamfered_plate,
    _create_plate_with_holes,
    ensure_benchmark_fixtures,
)


# ---------------------------------------------------------------------------
# Real dict round-trip tests using fixture STLs
# ---------------------------------------------------------------------------


def test_roundtrip_benchmark_fixture_axis_aligned_box(test_data_dir: Path) -> None:
    """Test round-trip on real IR dicts from primitive_box_axis_aligned.stl."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    graph = build_feature_graph_for_stl(fixtures_dir / "primitive_box_axis_aligned.stl")

    assert "ir_tree" in graph
    for interp_dict in graph["ir_tree"]:
        interp = from_dict(interp_dict)
        assert isinstance(interp, Interpretation)
        assert isinstance(interp.root, BooleanUnion)
        assert interp.to_dict() == interp_dict


def test_roundtrip_benchmark_fixture_cylinder(test_data_dir: Path) -> None:
    """Test round-trip on real IR dicts from primitive_cylinder_axis_aligned.stl."""
    fixtures_dir = test_data_dir / "benchmark_fixtures"
    ensure_benchmark_fixtures(fixtures_dir)
    graph = build_feature_graph_for_stl(
        fixtures_dir / "primitive_cylinder_axis_aligned.stl"
    )

    assert "ir_tree" in graph
    for interp_dict in graph["ir_tree"]:
        interp = from_dict(interp_dict)
        assert isinstance(interp, Interpretation)
        assert interp.to_dict() == interp_dict


def test_roundtrip_box_with_hole(test_output_dir: Path) -> None:
    """Test round-trip on real BooleanDifference with TransformTranslate/HoleThrough."""
    stl_file = test_output_dir / "ir_box_hole.stl"
    _create_box_with_hole(stl_file)
    graph = build_feature_graph_for_stl(stl_file)

    assert "ir_tree" in graph
    for interp_dict in graph["ir_tree"]:
        interp = from_dict(interp_dict)
        assert isinstance(interp, Interpretation)
        assert isinstance(interp.root, BooleanDifference)
        assert isinstance(interp.root.base, PrimitiveBox)
        assert len(interp.root.cuts) >= 1
        cut0 = interp.root.cuts[0]
        assert isinstance(cut0, TransformTranslate)
        assert isinstance(cut0.child, HoleThrough)
        assert interp.to_dict() == interp_dict


def test_roundtrip_plate_with_holes_pattern(test_output_dir: Path) -> None:
    """Test round-trip on real BooleanDifference with PatternLinear."""
    stl_file = test_output_dir / "ir_plate_holes.stl"
    _create_plate_with_holes(stl_file, centers=[(-3.0, 0.0), (3.0, 0.0)])
    graph = build_feature_graph_for_stl(stl_file)

    assert "ir_tree" in graph
    for interp_dict in graph["ir_tree"]:
        interp = from_dict(interp_dict)
        assert isinstance(interp, Interpretation)
        assert isinstance(interp.root, BooleanDifference)
        assert isinstance(interp.root.base, PrimitivePlate)
        assert interp.to_dict() == interp_dict


def test_roundtrip_chamfered_plate_edge_treatment(test_output_dir: Path) -> None:
    """Test round-trip on real ChamferOrFilletEdge node."""
    stl_file = test_output_dir / "ir_chamfered_plate.stl"
    _create_chamfered_plate(stl_file, plate_size=(20.0, 10.0, 2.0), edge_chamfer=1.0)
    graph = build_feature_graph_for_stl(stl_file)

    assert "ir_tree" in graph
    for interp_dict in graph["ir_tree"]:
        interp = from_dict(interp_dict)
        assert isinstance(interp, Interpretation)
        assert isinstance(interp.root, BooleanDifference)
        has_edge_node = any(
            isinstance(c, ChamferOrFilletEdge) for c in interp.root.cuts
        )
        assert has_edge_node
        assert interp.to_dict() == interp_dict


# ---------------------------------------------------------------------------
# Real dict round-trip tests using existing feature builders
# ---------------------------------------------------------------------------


def test_roundtrip_revolve_solid() -> None:
    """Test round-trip on revolve solid IR tree (ExtrudeRevolve + Sketch2D)."""
    graph = {
        "schema_version": 1,
        "features": [
            {
                "type": "revolve_solid",
                "detected_via": "axisymmetric_revolve",
                "axis": [0.0, 0.0, 1.0],
                "axis_origin": [0.0, 0.0, 0.0],
                "profile": [(0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)],
                "confidence": 0.95,
                "confidence_components": {
                    "axis_quality": 0.95,
                    "cross_slice_consistency": 0.98,
                },
            }
        ],
    }
    ir_trees = _build_ir_tree(graph)
    assert len(ir_trees) == 1
    interp_dict = ir_trees[0]

    interp = from_dict(interp_dict)
    assert isinstance(interp, Interpretation)
    assert isinstance(interp.root, BooleanUnion)
    rot_node = interp.root.children[0]
    assert isinstance(rot_node, TransformRotate)
    assert isinstance(rot_node.child, ExtrudeRevolve)
    assert isinstance(rot_node.child.profile, Sketch2D)
    assert interp.to_dict() == interp_dict


def test_roundtrip_linear_extrude_solid() -> None:
    """Test round-trip on linear extrude IR tree (ExtrudeLinear + Sketch2D)."""
    graph = {
        "schema_version": 1,
        "features": [
            {
                "type": "linear_extrude_solid",
                "confidence": 0.88,
                "axis": [0.0, 0.0, 1.0],
                "height": 12.0,
                "profile": [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]],
            }
        ],
    }
    ir_trees = _build_ir_tree(graph)
    assert len(ir_trees) == 1
    interp_dict = ir_trees[0]

    interp = from_dict(interp_dict)
    assert isinstance(interp, Interpretation)
    assert isinstance(interp.root, BooleanUnion)
    extrude = interp.root.children[0]
    assert isinstance(extrude, ExtrudeLinear)
    assert isinstance(extrude.profile, Sketch2D)
    assert interp.to_dict() == interp_dict


def test_roundtrip_fallback_mesh() -> None:
    """Test round-trip on FallbackMesh when no solid primitives are detected."""
    graph = {"schema_version": 1, "features": []}
    ir_trees = _build_ir_tree(graph)
    assert len(ir_trees) == 1
    interp_dict = ir_trees[0]

    interp = from_dict(interp_dict)
    assert isinstance(interp, Interpretation)
    assert isinstance(interp.root, FallbackMesh)
    assert interp.to_dict() == interp_dict


def test_roundtrip_pattern_grid_builder() -> None:
    """Test round-trip on PatternGrid dict produced by _ir_pattern_node."""
    pat_feat = {
        "type": "grid_hole_pattern",
        "grid_origin": [1.0, 2.0, 3.0],
        "grid_row_step": [5.0, 0.0, 0.0],
        "grid_col_step": [0.0, 5.0, 0.0],
        "grid_rows": 3,
        "grid_cols": 4,
        "diameter": 2.5,
        "axis": "z",
    }
    grid_dict = _ir_pattern_node(pat_feat)
    node = from_dict(grid_dict)
    assert isinstance(node, PatternGrid)
    assert isinstance(node.child, HoleThrough)
    assert node.rows == 3
    assert node.cols == 4
    assert node.diameter == 2.5
    assert node.to_dict() == grid_dict


def test_roundtrip_cutout_slot_and_counterbore() -> None:
    """Test round-trip on Slot and HoleCounterbore via _ir_cutout_node."""
    slot_feat = {
        "type": "slot_like_cutout",
        "center": [10.0, 20.0, 0.0],
        "start": [5.0, 20.0, 0.0],
        "end": [15.0, 20.0, 0.0],
        "width": 3.0,
        "axis": "z",
        "confidence": 0.9,
    }
    slot_dict = _ir_cutout_node(slot_feat)
    slot_node = from_dict(slot_dict)
    assert isinstance(slot_node, TransformTranslate)
    assert isinstance(slot_node.child, Slot)
    assert slot_node.to_dict() == slot_dict

    cbore_feat = {
        "type": "counterbore_hole",
        "center": [0.0, 0.0, 5.0],
        "through_diameter": 4.0,
        "bore_diameter": 8.0,
        "bore_depth": 2.5,
        "axis": "z",
        "confidence": 0.95,
    }
    cbore_dict = _ir_cutout_node(cbore_feat)
    cbore_node = from_dict(cbore_dict)
    assert isinstance(cbore_node, TransformTranslate)
    assert isinstance(cbore_node.child, HoleCounterbore)
    assert cbore_node.to_dict() == cbore_dict


def test_roundtrip_cutout_rectangular_prism_and_pocket() -> None:
    """Test round-trip on RectangularCutout and RectangularPocket via _ir_cutout_node."""
    cutout_feat = {
        "type": "rectangular_cutout",
        "center": [0.0, 0.0, 0.0],
        "size": [10.0, 5.0, 2.0],
        "confidence": 0.9,
    }
    cutout_dict = _ir_cutout_node(cutout_feat)
    node1 = from_dict(cutout_dict)
    assert isinstance(node1, TransformTranslate)
    assert isinstance(node1.child, RectangularCutout)
    assert node1.to_dict() == cutout_dict

    pocket_feat = {
        "type": "rectangular_pocket",
        "center": [2.0, 4.0, 1.0],
        "size": [6.0, 6.0, 3.0],
        "confidence": 0.85,
    }
    pocket_dict = _ir_cutout_node(pocket_feat)
    node2 = from_dict(pocket_dict)
    assert isinstance(node2, TransformTranslate)
    assert isinstance(node2.child, RectangularPocket)
    assert node2.to_dict() == pocket_dict


# ---------------------------------------------------------------------------
# New Node Types Tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Provenance face_ids & Error Handling Tests
# ---------------------------------------------------------------------------


def test_scad_emission_parity_after_ir_roundtrip(test_output_dir: Path) -> None:
    """Verify that SCAD emitted from round-tripped IR matches original SCAD bit-for-bit."""
    stl_file = test_output_dir / "parity_box_hole.stl"
    _create_box_with_hole(stl_file)
    graph = build_feature_graph_for_stl(stl_file)
    orig_root = graph["ir_tree"][0]["root"]

    scad_orig = emit_node(orig_root, graph)
    assert scad_orig is not None

    roundtripped = from_dict(orig_root).to_dict()
    scad_new = emit_node(roundtripped, graph)
    assert scad_new is not None

    assert scad_orig == scad_new
