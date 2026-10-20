"""Tests for typed IR dataclasses and serialization round-trip in stl2scad.core.ir."""

import pytest

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


# Round-trip tests that build IR through the legacy feature graph moved to
# tests/legacy/test_ir_feature_graph.py (T-004).


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
