"""Tests for typed IR dataclasses and serialization round-trip in stl2scad.core.ir."""

from pathlib import Path
import pytest

from stl2scad.core.feature_graph import (
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
from tests.test_feature_graph import (
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


def test_new_node_transform_mult_matrix() -> None:
    """Test TransformMultMatrix 4x4 matrix placement dataclass."""
    # Default identity
    t_def = TransformMultMatrix()
    assert len(t_def.matrix) == 4
    assert t_def.matrix[0][0] == 1.0

    # Custom matrix and child
    mat = (
        (1.0, 0.0, 0.0, 10.0),
        (0.0, 0.866, -0.5, 20.0),
        (0.0, 0.5, 0.866, 30.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    child = PrimitiveBox(size=(10.0, 20.0, 5.0))
    t_custom = TransformMultMatrix(
        matrix=mat, child=child, face_ids=("f_bracket_base",)
    )
    d = t_custom.to_dict()
    assert d["type"] == "TransformMultMatrix"
    assert d["matrix"] == [list(row) for row in mat]
    assert d["face_ids"] == ["f_bracket_base"]
    assert d["child"]["type"] == "PrimitiveBox"

    # Round trip
    rebuilt = from_dict(d)
    assert isinstance(rebuilt, TransformMultMatrix)
    assert rebuilt.matrix == mat
    assert rebuilt.face_ids == ("f_bracket_base",)
    assert rebuilt.to_dict() == d
    assert rebuilt == t_custom


def test_new_node_boss() -> None:
    """Test Boss structural feature dataclass."""
    b = Boss(
        height=6.0,
        radius=4.0,
        center=(10.0, 15.0, 2.0),
        axis=(0.0, 0.0, 1.0),
        host_face_id="face_top",
        face_ids=("face_boss_cylinder", "face_boss_cap"),
    )
    assert b.diameter == 8.0
    d = b.to_dict()
    assert d["type"] == "Boss"
    assert d["height"] == 6.0
    assert d["radius"] == 4.0
    assert d["diameter"] == 8.0
    assert d["center"] == [10.0, 15.0, 2.0]
    assert d["axis"] == [0.0, 0.0, 1.0]
    assert d["host_face_id"] == "face_top"
    assert d["face_ids"] == ["face_boss_cylinder", "face_boss_cap"]

    rebuilt = from_dict(d)
    assert isinstance(rebuilt, Boss)
    assert rebuilt == b
    assert rebuilt.to_dict() == d


def test_new_node_hole_blind() -> None:
    """Test HoleBlind depth-limited hole dataclass."""
    hb = HoleBlind(
        depth=8.0,
        diameter=5.0,
        center=(0.0, 0.0, 10.0),
        axis=(0.0, 0.0, -1.0),
        host_face_id="face_boss_cap",
        face_ids=("face_blind_wall", "face_blind_bottom"),
    )
    assert hb.radius == 2.5
    d = hb.to_dict()
    assert d["type"] == "HoleBlind"
    assert d["depth"] == 8.0
    assert d["diameter"] == 5.0
    assert d["radius"] == 2.5
    assert d["center"] == [0.0, 0.0, 10.0]
    assert d["host_face_id"] == "face_boss_cap"
    assert d["face_ids"] == ["face_blind_wall", "face_blind_bottom"]

    rebuilt = from_dict(d)
    assert isinstance(rebuilt, HoleBlind)
    assert rebuilt == hb
    assert rebuilt.to_dict() == d


def test_new_node_fillet() -> None:
    """Test Fillet edge treatment between two host face ids."""
    # Constructed with face1_id and face2_id
    f1 = Fillet(radius=2.5, face1_id="face_top", face2_id="face_boss_cylinder")
    assert f1.face_ids == ("face_top", "face_boss_cylinder")
    assert f1.face_id_a == "face_top"
    assert f1.face_id_b == "face_boss_cylinder"

    d1 = f1.to_dict()
    assert d1["type"] == "Fillet"
    assert d1["radius"] == 2.5
    assert d1["face1_id"] == "face_top"
    assert d1["face2_id"] == "face_boss_cylinder"
    assert d1["face_ids"] == ["face_top", "face_boss_cylinder"]

    rebuilt1 = from_dict(d1)
    assert isinstance(rebuilt1, Fillet)
    assert rebuilt1 == f1
    assert rebuilt1.to_dict() == d1

    # Constructed with face_ids tuple
    f2 = Fillet(radius=1.0, face_ids=("f_left", "f_right"))
    assert f2.face1_id == "f_left"
    assert f2.face2_id == "f_right"
    assert f2.to_dict() == from_dict(f2.to_dict()).to_dict()


def test_new_node_parameter() -> None:
    """Test Parameter customizer variable metadata dataclass."""
    param = Parameter(
        name="boss_1_height",
        value=6.0,
        raw_value=5.987,
        min=1.0,
        step=0.5,
        max=12.0,
        group="Boss Dimensions",
        description="Height of primary mounting boss in mm",
        face_ids=("face_boss_cylinder",),
    )
    d = param.to_dict()
    assert d["type"] == "Parameter"
    assert d["name"] == "boss_1_height"
    assert d["value"] == 6.0
    assert d["raw_value"] == 5.987
    assert d["min"] == 1.0
    assert d["step"] == 0.5
    assert d["max"] == 12.0
    assert d["group"] == "Boss Dimensions"
    assert d["description"] == "Height of primary mounting boss in mm"
    assert d["face_ids"] == ["face_boss_cylinder"]

    rebuilt = from_dict(d)
    assert isinstance(rebuilt, Parameter)
    assert rebuilt == param
    assert rebuilt.to_dict() == d


def test_new_node_constraint() -> None:
    """Test Constraint assert expression dataclass."""
    con = Constraint(
        expression="blind_hole_1_depth < base_thickness",
        message="Blind hole depth must not exceed base plate thickness",
        face_ids=("face_base_bottom", "face_blind_bottom"),
    )
    d = con.to_dict()
    assert d["type"] == "Constraint"
    assert d["expression"] == "blind_hole_1_depth < base_thickness"
    assert d["message"] == "Blind hole depth must not exceed base plate thickness"
    assert d["face_ids"] == ["face_base_bottom", "face_blind_bottom"]

    rebuilt = from_dict(d)
    assert isinstance(rebuilt, Constraint)
    assert rebuilt == con
    assert rebuilt.to_dict() == d


# ---------------------------------------------------------------------------
# Provenance face_ids & Error Handling Tests
# ---------------------------------------------------------------------------


def test_face_ids_provenance_on_nodes() -> None:
    """Verify face_ids provenance is supported on nodes and preserved when populated."""
    nodes = [
        Interpretation(root=FallbackMesh(face_ids=("f0",)), face_ids=("f0", "f1")),
        FallbackMesh(face_ids=("f0",)),
        BooleanUnion(children=(), face_ids=("f1",)),
        BooleanDifference(base=FallbackMesh(), cuts=(), face_ids=("f2",)),
        Sketch2D(points=((0.0, 0.0), (1.0, 1.0)), face_ids=("f3",)),
        ExtrudeLinear(height=5.0, face_ids=("f4",)),
        ExtrudeRevolve(face_ids=("f5",)),
        TransformTranslate(offset=(1.0, 2.0, 3.0), face_ids=("f6",)),
        TransformRotate(angles_deg=(0.0, 90.0, 0.0), face_ids=("f7",)),
        TransformMultMatrix(face_ids=("f8",)),
        PatternLinear(count=2, face_ids=("f9",)),
        PatternGrid(rows=2, cols=2, face_ids=("f10",)),
        HoleThrough(diameter=3.0, face_ids=("f11",)),
        HoleBlind(depth=4.0, diameter=2.0, face_ids=("f12",)),
        HoleCounterbore(through_diameter=3.0, face_ids=("f13",)),
        Slot(width=2.0, face_ids=("f14",)),
        RectangularCutout(size=(1.0, 1.0, 1.0), face_ids=("f15",)),
        RectangularPocket(size=(2.0, 2.0, 2.0), face_ids=("f16",)),
        ChamferOrFilletEdge(size=1.0, face_ids=("f17",)),
        Fillet(radius=1.5, face_ids=("f18", "f19")),
        Boss(height=4.0, radius=2.0, face_ids=("f20",)),
        PrimitivePlate(size=(10.0, 10.0, 2.0), face_ids=("f21",)),
        PrimitiveBox(size=(10.0, 10.0, 10.0), face_ids=("f22",)),
        PrimitiveCylinder(radius=5.0, height=10.0, face_ids=("f23",)),
        Parameter(name="p", value=1.0, face_ids=("f24",)),
        Constraint(expression="a > 0", face_ids=("f25",)),
    ]
    for n in nodes:
        d = n.to_dict()
        assert "face_ids" in d, f"Missing face_ids in {n.__class__.__name__}.to_dict()"
        assert d["face_ids"] == list(n.face_ids)
        rebuilt = from_dict(d)
        assert rebuilt.face_ids == n.face_ids


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


def test_from_dict_validation_and_errors() -> None:
    """Verify from_dict error reporting and idempotent IRNode pass-through."""
    # Idempotent pass-through
    node = FallbackMesh()
    assert from_dict(node) is node

    # Non-dict / non-IRNode error
    with pytest.raises(TypeError, match="Expected dict or IRNode"):
        from_dict("not_a_dict")  # type: ignore[arg-type]

    # Missing type field
    with pytest.raises(ValueError, match="Missing 'type' field"):
        from_dict({"no_type": 123})

    # Unknown type
    with pytest.raises(ValueError, match="Unknown IR node type"):
        from_dict({"type": "CompletelyUnknownNodeType"})
