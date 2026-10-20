"""Regressions for the independent review of 465c778."""

from dataclasses import replace
import re

import numpy as np
import pytest

from stl2scad.core.segmentation import Feature, detect_features, emit_scad, segment_mesh
from stl2scad.core.segmentation.features import classify_profile
from stl2scad.core.segmentation.emit import render_scad, ir_to_scad
from stl2scad.core.segmentation.to_ir import features_to_ir
from stl2scad.core.segmentation.solid import mesh_hausdorff, hausdorff_to_mesh
from tests.test_segmentation_bracket import openscad_path
from tests.test_segmentation_features import RECTANGLE, L_PROFILE, U_PROFILE, T_PROFILE
from tests.test_segmentation_geometry import (
    cylinder_triangles,
    cube,
    extrusion,
    mesh_of,
    rotation,
)

FRAME = tuple(tuple(float(x) for x in row) for row in np.eye(4))


def body(points=RECTANGLE, scale=1.0):
    return Feature(
        "body_1",
        "polygon_profile_extrude",
        "additive",
        ("base",),
        FRAME,
        height=2 * scale,
        profile=classify_profile(np.asarray(points) * scale, 1e-8 * scale),
    )


@pytest.mark.parametrize("points", [RECTANGLE, U_PROFILE, T_PROFILE])
def test_fillet_constraints_only_reference_defined_profile_parameters(points):
    base = body(points)
    corner = np.asarray(base.profile.points[0])
    fillet = Feature(
        "fillet_1",
        "fillet",
        "additive",
        ("round",),
        FRAME,
        radius=0.2,
        height=2,
        position=tuple(np.r_[corner + [0.2, 0.2], 0]),
        corner=tuple(np.r_[corner, 0]),
        between=("a", "b"),
    )
    model = features_to_ir([base, fillet])
    names = {p.name for p in model.parameters}
    identifiers = set(
        re.findall(
            r"\b[a-zA-Z_]\w*\b", " ".join(c.expression for c in model.constraints)
        )
    )
    assert identifiers - {"floor", "norm", "min", "max"} <= names


def test_blind_hole_depth_uses_first_profile_exit(openscad_path):
    base = body([[0, 0], [40, 0], [40, 5], [5, 5], [5, 35], [0, 35]])
    hole = Feature(
        "blind_hole_1",
        "blind_hole",
        "subtractive",
        ("hole",),
        FRAME,
        on_face="bottom",
        radius=0.5,
        depth=3,
        position=(34, 0, 1),
        axis=(0, 1, 0),
    )
    model = features_to_ir([base, hole])
    maximum = next(p.max for p in model.parameters if p.name == "blind_hole_1_depth")
    assert 3 <= maximum < 5
    source = ir_to_scad(model)
    source = re.sub(
        r"^(blind_hole_1_depth\s*=\s*)[-\d.]+;", r"\g<1>7;", source, flags=re.M
    )
    with pytest.raises(RuntimeError, match="floor|Assertion"):
        render_scad(source)


@pytest.mark.parametrize(
    "direction,point,expected",
    [
        ((0, -1, 0), (34, 5.000001, 1), 5.000001),
        ((0, 0, -1), (34, 2, 2.000001), 2.000001),
    ],
)
def test_material_depth_ignores_numerical_entry_crossing(direction, point, expected):
    from stl2scad.core.segmentation.profile_geometry import material_depth

    profile = [[0, 0], [40, 0], [40, 5], [5, 5], [5, 35], [0, 35]]
    assert material_depth(profile, point, direction, 2) == pytest.approx(
        expected, abs=1e-9
    )


def test_blind_hole_bottom_of_l_wall_uses_full_leg_thickness(openscad_path):
    base = body([[0, 0], [40, 0], [40, 5], [5, 5], [5, 35], [0, 35]])
    hole = Feature(
        "blind_hole_1",
        "blind_hole",
        "subtractive",
        ("hole",),
        FRAME,
        on_face="bottom",
        radius=0.5,
        depth=30,
        position=(2, 0, 1),
        axis=(0, 1, 0),
    )
    model = features_to_ir([base, hole])
    maximum = next(p.max for p in model.parameters if p.name == "blind_hole_1_depth")
    assert 30 <= maximum < 35
    render_scad(ir_to_scad(model))


@pytest.mark.parametrize("scale", [1e-3, 1.0, 1e3])
@pytest.mark.parametrize("kind", ["boss", "blind_hole"])
def test_small_free_space_keeps_measured_parameter_in_range(kind, scale):
    base = body([[0, 0], [2, 0], [2, 1], [0, 1]], scale)
    feature = Feature(
        kind + "_1",
        kind,
        "additive" if kind == "boss" else "subtractive",
        ("curve",),
        FRAME,
        on_face="bottom",
        position=(0.5 * scale, 0, scale),
        axis=(0, -1, 0) if kind == "boss" else (0, 1, 0),
        radius=(0.495 if kind == "boss" else 0.1) * scale,
        height=0.5 * scale if kind == "boss" else None,
        depth=0.995 * scale if kind == "blind_hole" else None,
    )
    model = features_to_ir([base, feature])
    for p in model.parameters:
        assert p.min <= p.value <= p.max


def square_tube():
    outer = np.array([[0, 0], [2, 0], [2, 2], [0, 2]], float)
    inner = np.array([[0.9, 0.9], [1.1, 0.9], [1.1, 1.1], [0.9, 1.1]])
    bottom = np.column_stack((np.vstack((outer, inner)), np.zeros(8)))
    top = bottom + [0, 0, 2]
    triangles = []
    for i in range(4):
        j = (i + 1) % 4
        for ids in ([i, j, 4 + j], [i, 4 + j, 4 + i]):
            triangles.extend([bottom[ids[::-1]], top[ids]])
        triangles.extend(
            [
                [bottom[i], bottom[j], top[j]],
                [bottom[i], top[j], top[i]],
                [bottom[4 + j], bottom[4 + i], top[4 + i]],
                [bottom[4 + j], top[4 + i], top[4 + j]],
            ]
        )
    return mesh_of(triangles)


def test_hausdorff_samples_edges_in_both_directions():
    # A narrow through cut adds inner walls. Their vertices lie on the outer
    # caps, and centroids miss the middle of the wall's vertical edges.
    original = mesh_of(cube())
    tube = square_tube()
    assert mesh_hausdorff(original, tube, samples=0) == pytest.approx(0.9, abs=1e-6)
    assert mesh_hausdorff(tube, original, samples=0) == pytest.approx(0.9, abs=1e-6)


@pytest.mark.parametrize("sign", [1, -1])
def test_shallow_plane_crease_is_not_tangent(sign):
    # Two plane patches with an actual 3-degree fold, not a tessellated arc.
    theta = np.radians(3) * sign
    a, b = np.array([0.0, 0.0, 0.0]), np.array([0.0, 2.0, 0.0])
    left = np.array([-2.0, 0.0, 0.0])
    right = np.array([2 * np.cos(theta), 0, 2 * np.sin(theta)])
    result = segment_mesh(
        mesh_of(
            [
                [a, b, left],
                [b, left, left + [0, 2, 0]],
                [b, a, right],
                [b, right, right + [0, 2, 0]],
            ]
        )
    )
    assert len(result.faces) == 2
    edge = next(iter(result.graph.edges(data=True)))[2]
    assert abs(edge["signed_dihedral_deg"]) == pytest.approx(3, abs=1e-5)
    assert edge["convexity"] == (
        "convex" if edge["signed_dihedral_deg"] > 0 else "concave"
    )


def test_cylinder_support_keeps_opposite_normal_polarities_separate():
    from stl2scad.core.segmentation.pipeline import (
        _cylinder_support,
        SegmentationConfig,
    )
    from stl2scad.core.segmentation.models import Cylinder

    triangles = cylinder_triangles(sections=32)[60:]
    centers = triangles.mean(axis=1)
    normals = centers.copy()
    normals[:, 2] = 0
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    # The same geometric support cannot vote simultaneously for both walls.
    points = np.concatenate((triangles, triangles))
    directions = np.concatenate((normals, -normals))
    support = _cylinder_support(
        Cylinder((0, 0, 1), (0, 0, 0), 2),
        points,
        directions,
        SegmentationConfig(),
        1e-5,
    )
    assert support[: len(normals)].all() != support[len(normals) :].all()


@pytest.mark.parametrize("inner", [1.5, 1.99997])
def test_tube_has_separate_convex_and_concave_cylinder_faces(inner):
    n = 64
    angles = np.arange(n) * 2 * np.pi / n
    outer = 2 * np.column_stack((np.cos(angles), np.sin(angles)))
    inside = inner / 2 * outer
    bottom = np.column_stack((np.vstack((outer, inside)), np.zeros(2 * n)))
    top = bottom + [0, 0, 5]
    triangles = []
    for i in range(n):
        j = (i + 1) % n
        for ids in ([i, j, n + j], [i, n + j, n + i]):
            triangles.extend([bottom[ids[::-1]], top[ids]])
        triangles.extend(
            [
                [bottom[i], bottom[j], top[j]],
                [bottom[i], top[j], top[i]],
                [bottom[n + j], bottom[n + i], top[n + i]],
                [bottom[n + j], top[n + i], top[n + j]],
            ]
        )
    result = segment_mesh(mesh_of(triangles))
    curves = [f for f in result.faces if f.kind == "cylinder"]
    assert len(curves) == 2
    by_polarity = {f.convexity: f for f in curves}
    assert by_polarity["convex"].params.radius == pytest.approx(2, abs=1e-6)
    assert by_polarity["concave"].params.radius == pytest.approx(inner, abs=1e-6)
    assert not set(curves[0].triangle_indices) & set(curves[1].triangle_indices)


@pytest.mark.parametrize("turned", [False, True])
def test_standalone_pin_is_recovered_and_emitted(openscad_path, turned):
    triangles = cylinder_triangles()
    if turned:
        triangles = triangles @ rotation().T + [3, -7, 2]
    mesh = mesh_of(triangles)
    features = detect_features(segment_mesh(mesh))
    assert len(features) == 1 and features[0].polarity == "additive"
    assert features[0].radius == pytest.approx(2, abs=1e-5)
    assert features[0].height == pytest.approx(5, abs=1e-5)
    frame = np.asarray(features[0].part_frame)
    expected_axis = rotation() @ [0, 0, 1] if turned else np.array([0, 0, 1])
    assert abs((frame[:3, :3] @ features[0].axis) @ expected_axis) > 1 - 1e-8
    assert hausdorff_to_mesh(features, mesh) < 0.001
    assert "polyhedron(" not in emit_scad(features, mesh)


@pytest.mark.parametrize("axis", ["x", "y", "z", "oblique"])
@pytest.mark.parametrize("turned", [False, True])
def test_through_holes_on_any_body_face(openscad_path, axis, turned):
    cutter = {
        "x": "translate([-1,15,20]) rotate([0,90,0]) cylinder(r=1,h=8);",
        "y": "translate([2.5,-1,20]) rotate([-90,0,0]) cylinder(r=1,h=32);",
        "z": "translate([25,15,-1]) cylinder(r=1,h=8);",
        "oblique": "translate([-1,15,19.8]) rotate([0,78.690067526,0]) cylinder(r=1,h=9);",
    }[axis]
    source = (
        "$fn=32; difference(){union(){cube([40,30,5]);cube([5,30,35]);}" + cutter + "}"
    )
    mesh = render_scad(source)
    if turned:
        mesh = mesh_of(mesh.vectors @ rotation().T + [3, -7, 2])
    features = detect_features(segment_mesh(mesh))
    holes = [f for f in features if f.kind == "through_hole"]
    assert len(holes) == 1 and holes[0].polarity == "subtractive"
    assert holes[0].radius == pytest.approx(1, abs=1e-4)
    point, direction = {
        "x": ([0, 15, 20], [1, 0, 0]),
        "y": ([2.5, 0, 20], [0, 1, 0]),
        "z": ([25, 15, 0], [0, 0, 1]),
        "oblique": ([0, 15, 20], [1, 0, 0.2]),
    }[axis]
    direction = np.asarray(direction, dtype=float)
    direction /= np.linalg.norm(direction)
    if turned:
        point = rotation() @ point + [3, -7, 2]
        direction = rotation() @ direction
    frame = np.asarray(holes[0].part_frame)
    found_point = frame[:3, :3] @ holes[0].position + frame[:3, 3]
    found_axis = frame[:3, :3] @ holes[0].axis
    assert np.linalg.norm(np.cross(found_point - point, direction)) < 1e-4
    assert abs(found_axis @ direction) > 1 - 1e-8
    assert hausdorff_to_mesh(features, mesh) < 0.01
    assert "polyhedron(" not in emit_scad(features, mesh)


def test_wrong_cylinder_segment_count_fails_the_emission_gate(
    openscad_path, monkeypatch
):
    from stl2scad.core.segmentation import solid

    # Do not rely on random samples landing next to the worst vertical edge.
    # Centroids give ~0.04918mm; edge midpoints give ~0.05024mm, across the gate.
    monkeypatch.setattr(
        solid, "sample_mesh_points", lambda *_: (np.empty((0, 3)), None)
    )
    mesh = render_scad(
        "$fn=64; difference(){cube([4,4,3]);translate([2,2,-1]) cylinder(r=.66,h=5);}"
    )
    features = detect_features(segment_mesh(mesh))
    wrong = [
        replace(f, segments=8) if f.kind == "through_hole" else f for f in features
    ]
    assert hausdorff_to_mesh(wrong, mesh) > 0.05
    assert "Full mesh fallback" in emit_scad(wrong, mesh)


@pytest.mark.parametrize("mutation", ["position", "axis", "duplicate"])
def test_bracket_ground_truth_rejects_wrong_feature_pose(
    openscad_path, monkeypatch, mutation
):
    import stl2scad.core.segmentation as api
    from tests import test_segmentation_bracket as harness

    # Exercise the harness itself, while isolating its direct geometry checks
    # from the separate reconstruction metric.
    from pathlib import Path

    source = (
        Path(harness.DATA_DIR) / harness.VARIANTS["axis_aligned"]["scad"]
    ).read_text()
    actual = render_scad(source)
    features = detect_features(segment_mesh(actual))
    boss = next(f for f in features if f.id == "boss_1")
    changed = (
        replace(boss, position=tuple(np.asarray(boss.position) + [1, 0, 0]))
        if mutation == "position"
        else replace(boss, axis=(1, 0, 0))
    )
    candidates = (
        features + [replace(boss, id="boss_2")]
        if mutation == "duplicate"
        else [changed if f.id == boss.id else f for f in features]
    )
    monkeypatch.setattr(api, "detect_features", lambda _: candidates)
    monkeypatch.setattr(api, "hausdorff_to_mesh", lambda *_: 0.0)
    with pytest.raises(AssertionError):
        harness.test_features_recovered_with_polarity_and_hausdorff(
            {"axis_aligned": actual}, "axis_aligned"
        )


def test_rounded_plate_ground_truth_rejects_wrong_hole_axis(openscad_path, monkeypatch):
    import stl2scad.core.segmentation as api
    from tests import test_segmentation_rounded_plate as harness

    mesh = render_scad((harness.DATA / "rounded_plate.scad").read_text())
    features = detect_features(segment_mesh(mesh))
    wrong = [replace(f, axis=(1, 0, 0)) if f.id == "hole_1" else f for f in features]
    monkeypatch.setattr(api, "detect_features", lambda _: wrong)
    monkeypatch.setattr(api, "hausdorff_to_mesh", lambda *_: 0.0)
    with pytest.raises(AssertionError):
        harness.test_features_and_hausdorff({"axis_aligned": mesh}, "axis_aligned")
