"""Editable typed-IR emission, snapping, fallback, placement and provenance."""

from dataclasses import replace
import re

import numpy as np
import pytest

from stl2scad.core import ir
from stl2scad.core.segmentation import (
    detect_features,
    emit_scad,
    gate_limit_mm,
    segment_mesh,
)
from stl2scad.core.segmentation import emit as emitter
from stl2scad.core.segmentation.to_ir import features_to_ir
from tests.test_segmentation_geometry import cube, extrusion, mesh_of
from tests.test_segmentation_bracket import openscad_path, rendered


@pytest.fixture(scope="module")
def emitted(rendered):
    return {
        name: emit_scad(
            detect_features(segment_mesh(mesh)), mesh, source_file=name + ".stl"
        )
        for name, mesh in rendered.items()
    }


def test_typed_tree_contains_sketch_features_booleans_and_provenance(rendered):
    features = detect_features(segment_mesh(rendered["rotated"]))
    model = features_to_ir(features)
    assert isinstance(model.root, ir.TransformMultMatrix)
    assert isinstance(model.root.child, ir.BooleanDifference)
    assert isinstance(model.root.child.base, ir.BooleanUnion)
    positive = model.root.child.base.children
    assert [type(node) for node in positive] == [ir.ExtrudeLinear, ir.Fillet, ir.Boss]
    assert isinstance(positive[0].profile, ir.Sketch2D)
    assert isinstance(model.root.child.cuts[0], ir.HoleBlind)
    assert ir.from_dict(model.root.to_dict()) == model.root
    assert all(isinstance(p, ir.Parameter) and p.face_ids for p in model.parameters)
    assert all(isinstance(c, ir.Constraint) for c in model.constraints)
    owners = [
        face for node in (*positive, *model.root.child.cuts) for face in node.face_ids
    ]
    assert len(owners) == len(set(owners)) == 13
    parameters = {p.name: p for p in model.parameters}
    assert parameters["blind_hole_1_depth"].max < parameters["base_thickness"].value
    assert parameters["boss_1_radius"].max < 15


@pytest.mark.parametrize("variant", ["axis_aligned", "rotated"])
def test_customizer_ranges_raw_comments_and_all_faces_are_labeled(
    emitted, rendered, variant
):
    source = emitted[variant]
    assert "polyhedron(" not in source
    assert source.count("multmatrix(") == 1
    for face in segment_mesh(rendered[variant]).faces:
        assert re.search(rf"// face {face.id} \w+ \({face.kind}\)", source)
    for name in (
        "boss_1_height",
        "boss_1_radius",
        "blind_hole_1_depth",
        "fillet_1_radius",
        "base_thickness",
        "wall_thickness",
    ):
        assert re.search(
            rf"^// .*\(raw [-\d.]+\)\n{name} = [-\d.]+; // \[[-\d.:]+\]$", source, re.M
        )
    assert "blind_hole_1_depth < base_thickness" in source
    assert "base_thickness" in next(
        line for line in source.splitlines() if "cylinder(r=boss_1_radius" in line
    )
    assert f"// Source: {variant}.stl" in source
    assert "// Gate limit:" in source and "measured Hausdorff:" in source


def test_editing_host_thickness_moves_boss_and_invalid_link_stops_render(emitted):
    source = re.sub(
        r"^base_thickness = [-\d.]+;",
        "base_thickness = 8;",
        emitted["axis_aligned"],
        flags=re.M,
    )
    mesh = emitter.render_scad(source)
    # Part frame columns are (-X, Z, Y), with world origin (40,0,0).
    points = mesh.vectors.reshape(-1, 3)
    boss = points[np.linalg.norm(points[:, :2] - [25.0, 15.0], axis=1) < 6.01]
    assert boss[:, 2].max() == pytest.approx(14.0, abs=1e-5)
    invalid = re.sub(
        r"^blind_hole_1_depth = [-\d.]+;", "blind_hole_1_depth = 9;", source, flags=re.M
    )
    with pytest.raises(RuntimeError, match="render failed"):
        emitter.render_scad(invalid)


def test_whole_mesh_fallback_on_gate_failure_and_source_comment_is_safe(monkeypatch):
    mesh = mesh_of(cube())
    features = detect_features(segment_mesh(mesh))
    monkeypatch.setattr(emitter, "render_scad", lambda source: mesh)
    monkeypatch.setattr(emitter, "mesh_hausdorff", lambda a, b: 10.0)
    source = emit_scad(features, mesh, source_file="sample.stl\n*/ cube(999);")
    assert "polyhedron(" in source
    assert "failed the Hausdorff gate" in source
    assert "/* [Body] */" not in source
    assert source.startswith("// Source: sample.stl * / cube(999);\n")


def test_detection_exception_and_render_exception_fall_back(monkeypatch):
    mesh = mesh_of(cube())
    from stl2scad.core.segmentation import features as feature_module

    def broken(*args):
        raise ValueError("unsupported topology")

    monkeypatch.setattr(feature_module, "detect_features", broken)
    assert "unsupported topology" in emit_scad(None, mesh)
    # Explicit features still exercise the gate's render failure boundary.
    features = detect_features(segment_mesh(mesh))
    monkeypatch.setattr(emitter, "render_scad", broken)
    source = emit_scad(features, mesh)
    assert "polyhedron(" in source
    assert "measured Hausdorff: inf" in source


def test_fallback_polyhedron_renders_the_entire_mesh(openscad_path):
    mesh = mesh_of(cube())
    source = emitter.fallback_scad(mesh, "unit test")
    rebuilt = emitter.render_scad(source)
    assert emitter.mesh_hausdorff(rebuilt, mesh, samples=32) < 1e-6


def test_snapping_keeps_design_value_that_gate_would_allow_to_move(monkeypatch):
    triangles = cube()
    triangles[:, :, 0] *= 1.13
    mesh = mesh_of(triangles)
    features = detect_features(segment_mesh(mesh))
    model = features_to_ir(features)
    parameter = next(p for p in model.parameters if abs(p.value - 2.26) < 1e-5)

    def render(source):
        match = re.search(rf"^{parameter.name} = ([-\d.]+);", source, re.M)
        return float(match[1])

    monkeypatch.setattr(emitter, "render_scad", render)
    monkeypatch.setattr(
        emitter, "mesh_hausdorff", lambda value, mesh: abs(value - parameter.raw_value)
    )
    source = emit_scad(features, mesh)
    # The gate (0.05 mm) would accept 2.3, but a 0.04 mm shift is a design
    # change, not float noise, so the value stays 2.26.
    assert f"{parameter.name} = 2.3;" not in source
    assert re.search(rf"^{parameter.name} = 2\.26\d*;", source, re.M)
    raw = re.search(rf"^// .*\(raw ([-\d.]+)\)\n{parameter.name} = ", source, re.M)
    assert float(raw[1]) == pytest.approx(parameter.raw_value, abs=1e-10)


def test_rectangle_u_t_and_unknown_profiles_emit_named_dimensions_or_points():
    from tests.test_segmentation_features import U_PROFILE, T_PROFILE

    shapes = [
        (
            np.array([[0, 0], [4, 0], [4, 3], [0, 3]]),
            [[0, 1, 2], [0, 2, 3]],
            "base_thickness",
        ),
        (
            np.array(U_PROFILE),
            [[0, 1, 4], [0, 4, 5], [1, 2, 3], [1, 3, 4], [0, 5, 6], [0, 6, 7]],
            "web_thickness",
        ),
        (
            np.array(T_PROFILE),
            [[1, 2, 3], [1, 3, 4], [7, 0, 1], [7, 1, 4], [7, 4, 5], [7, 5, 6]],
            "stem_width",
        ),
        (np.array([[0, 0], [4, 0], [2, 3]]), [[0, 1, 2]], "profile_1_p0_x"),
    ]
    for points, cap, name in shapes:
        features = detect_features(
            segment_mesh(mesh_of(extrusion(points, np.asarray(cap), 2.0)))
        )
        source = emitter.ir_to_scad(features_to_ir(features))
        assert f"{name} = " in source
        assert "// P0 = " in source
        assert "polygon(points=" in source


def test_gate_limit_scales_with_extent():
    assert gate_limit_mm(mesh_of(cube())) == 0.05
    mesh = mesh_of(cube() * 100)
    assert gate_limit_mm(mesh) == pytest.approx(0.001 * np.linalg.norm([200, 200, 200]))


def test_snapping_removes_float_noise_but_keeps_design_values():
    from stl2scad.core.segmentation.emit import _snap

    assert _snap(5.0000021, 1.0) == 5.0
    assert _snap(74.5999972, 0.1) == pytest.approx(74.6)
    assert _snap(51.0999993, 1.0) == 51.0999993  # 0.1 mm is a design value, not noise
    assert _snap(51.0999993, 0.1) == pytest.approx(51.1)
