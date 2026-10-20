"""Fast section recovery tests, independent of the rounded-plate renderer."""

import dataclasses
import json

import numpy as np
import pytest

from stl2scad.core import ir
from stl2scad.core.segmentation import detect_features, segment_mesh
from stl2scad.core.segmentation.features import Feature, Profile, ProfileSegment
from stl2scad.core.segmentation.sections import arc_points, profile_points
from stl2scad.core.segmentation.to_ir import features_to_ir
from tests.test_segmentation_geometry import extrusion, mesh_of, rotation


@pytest.mark.parametrize("n", [8, 16, 64])
@pytest.mark.parametrize("rotated", [False, True])
def test_recovers_convex_outline_arcs_in_intrinsic_frame(n, rotated):
    points = []
    for center, start in [((17, 3), -90), ((17, 9), 0), ((3, 9), 90), ((3, 3), 180)]:
        angles = np.radians(np.linspace(start, start + 90, n // 4 + 1))
        points.extend(
            np.array(center) + 3 * np.column_stack((np.cos(angles), np.sin(angles)))
        )
    profile = np.asarray(points)
    triangles = extrusion(
        profile, np.array([[0, i, i + 1] for i in range(1, len(profile) - 1)]), 2
    )
    if rotated:
        triangles = triangles @ rotation().T + [19, -7, 6]
    result = segment_mesh(mesh_of(triangles))
    features = detect_features(result)
    assert len(features) == 1
    body = features[0]
    assert body.kind == "rounded_rectangle_profile_extrude"
    assert body.height == pytest.approx(2, abs=1e-5)
    assert dict(body.profile.dimensions)["plate_length"] == pytest.approx(20, abs=1e-5)
    assert dict(body.profile.dimensions)["plate_width"] == pytest.approx(12, abs=1e-5)
    arcs = [s for s in body.profile.segments if s.kind == "arc"]
    assert len(arcs) == 4
    assert all(
        s.radius == pytest.approx(3, abs=1e-5)
        and s.segments == n
        and s.convexity == "convex"
        for s in arcs
    )
    frame = np.asarray(body.part_frame)
    fitted = profile_points(body.profile) @ frame[:3, :2].T + frame[:3, 3]
    # Every reconstructed section vertex has actual mesh support.
    original = np.unique(triangles.reshape(-1, 3), axis=0)
    assert (
        np.linalg.norm(fitted[:, None] - original[None, :], axis=2).min(axis=1).max()
        < 2e-4
    )
    assert len(body.face_ids) == len(result.faces) == 10
    with pytest.raises(dataclasses.FrozenInstanceError):
        arcs[0].radius = 10
    model = features_to_ir(features)
    assert isinstance(model.root.child.base.profile, ir.SketchPath2D)
    encoded = json.loads(json.dumps(model.root.to_dict()))
    assert ir.from_dict(encoded).to_dict() == encoded
    # The point-only sketch representation remains byte-for-byte compatible.
    assert ir.Sketch2D(points=((0.0, 0.0),)).to_dict() == {
        "type": "Sketch2D",
        "kind": "polygon",
        "points": [[0.0, 0.0]],
    }


def test_clockwise_concave_arc_clips_odd_polygon_chord():
    arc = ProfileSegment(
        "arc",
        (4, 0),
        (-4, 0),
        ("F7",),
        center=(0, 0),
        radius=4,
        start_deg=0,
        sweep_deg=-180,
        segments=13,
        phase_deg=0,
        convexity="concave",
    )
    points = arc_points(arc)
    assert len(points) == 8
    assert points[0] == pytest.approx([4, 0], abs=1e-12)
    assert points[-1] == pytest.approx([-4 * np.cos(np.pi / 13), 0], abs=1e-12)
    assert (points[1:-1, 1] < 0).all()
    assert np.linalg.norm(points[1:-1], axis=1) == pytest.approx(np.full(6, 4))
    area = (
        abs(
            np.sum(
                points[:, 0] * np.roll(points[:, 1], -1)
                - points[:, 1] * np.roll(points[:, 0], -1)
            )
        )
        / 2
    )
    assert area == pytest.approx(13 * 16 * np.sin(2 * np.pi / 13) / 4)


def test_arc_sampling_preserves_phase_and_changes_resolution():
    arc = ProfileSegment(
        "arc",
        (0, 0),
        (0, 0),
        ("F1",),
        center=(2, 7),
        radius=3,
        start_deg=17,
        sweep_deg=102,
        segments=16,
        phase_deg=4,
    )
    coarse = arc_points(arc)
    smooth = arc_points(dataclasses.replace(arc, segments=64))
    assert len(smooth) > len(coarse)
    angles = np.degrees(np.arctan2(coarse[1:-1, 1] - 7, coarse[1:-1, 0] - 2))
    np.testing.assert_allclose(
        (angles - 4) / 22.5, np.round((angles - 4) / 22.5), atol=1e-12
    )
    assert np.linalg.norm(smooth[0] - [2, 7]) > np.linalg.norm(coarse[0] - [2, 7])


def test_path_ir_rejects_nonsegment_nodes():
    with pytest.raises(ValueError, match="line or arc"):
        ir.from_dict(
            {
                "type": "SketchPath2D",
                "segments": [{"type": "Boss", "radius": 3, "height": 2}],
            }
        )


def test_generic_segment_list_shares_line_joints_and_keeps_typed_arcs():
    points = ((0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (8.0, 10.0), (0.0, 10.0))
    segments = tuple(
        ProfileSegment("line", a, b, (f"F{i}",))
        for i, (a, b) in enumerate(zip(points, points[1:] + points[:1]))
        if i != 2
    )
    arc = ProfileSegment(
        "arc",
        points[2],
        points[3],
        ("F2",),
        center=(8.0, 8.0),
        radius=2,
        start_deg=0,
        sweep_deg=90,
        segments=16,
        convexity="convex",
    )
    segments = segments[:2] + (arc,) + segments[2:]
    body = Feature(
        "body_1",
        "arc_profile_extrude",
        "additive",
        tuple(f"F{i}" for i in range(7)),
        tuple(tuple(v) for v in np.eye(4)),
        height=2,
        profile=Profile("arc", points, (("width", 10.0), ("height", 10.0)), segments),
    )
    model = features_to_ir([body])
    lines = [b for b in model.bindings if isinstance(b.node, ir.SketchLine2D)]
    assert lines[0].points[1] == lines[1].points[0]
    assert lines[-1].points[1] == lines[0].points[0]
    names = {p.name for p in model.parameters}
    assert "plate_length" not in names and "plate_width" not in names
    assert {"arc_1_radius", "arc_1_x", "arc_1_y", "segment_1_start_x"} <= names
    from stl2scad.core.segmentation.emit import ir_to_scad

    source = ir_to_scad(model)
    assert "_arc(" in source and "segment_1_start_x" in source
