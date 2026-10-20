"""Step 4: profile classification, graph polarity, frame invariance and validation."""

from dataclasses import FrozenInstanceError, replace

import networkx as nx
import numpy as np
import pytest

from stl2scad.core.segmentation import (
    Cylinder,
    Face,
    Feature,
    Plane,
    SegmentationResult,
    detect_features,
    hausdorff_to_mesh,
    segment_mesh,
)
from stl2scad.core.segmentation.features import _cylinder_features, classify_profile
from stl2scad.core.segmentation.solid import mesh_hausdorff, reconstruct_mesh
from tests.test_segmentation_geometry import cube, extrusion, mesh_of, rotation

# Reuse the existing bracket renderer fixtures for the CSG regression checks.
from tests.test_segmentation_bracket import openscad_path, rendered, VARIANTS, _rotation


RECTANGLE = [[0, 0], [4, 0], [4, 3], [0, 3]]
L_PROFILE = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 3], [0, 3]]
U_PROFILE = [[0, 0], [4, 0], [4, 4], [3, 4], [3, 1], [1, 1], [1, 4], [0, 4]]
T_PROFILE = [[0, 3], [1, 3], [1, 0], [3, 0], [3, 3], [4, 3], [4, 4], [0, 4]]


@pytest.mark.parametrize(
    "points, kind, dimensions",
    [
        (RECTANGLE, "rectangle", dict(width=4, height=3)),
        (L_PROFILE, "l", dict(width=4, height=3, wall_thickness=1, base_thickness=1)),
        (
            U_PROFILE,
            "u",
            dict(
                width=4,
                height=4,
                web_thickness=1,
                slot_width=2,
                slot_depth=3,
                arm_1_thickness=1,
                arm_2_thickness=1,
            ),
        ),
        (
            T_PROFILE,
            "t",
            dict(width=4, height=4, flange_thickness=1, stem_width=2, stem_height=3),
        ),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_profiles_have_named_dimensions_and_canonical_labels(
    points, kind, dimensions, reverse
):
    original = classify_profile(points)
    points = np.asarray(points)[::-1] if reverse else np.roll(points, 2, axis=0)
    profile = classify_profile(points)
    assert profile == original
    assert profile.kind == kind
    assert dict(profile.dimensions) == pytest.approx(dimensions)
    assert [name for name, _ in profile.labeled_points] == [
        f"P{i}" for i in range(len(points))
    ]
    with pytest.raises(FrozenInstanceError):
        profile.kind = "other"


def test_profile_removes_triangulation_points_and_keeps_unknown_polygon():
    rectangle = classify_profile([[0, 0], [2, 0], [4, 0], [4, 3], [0, 3]])
    assert rectangle == classify_profile(RECTANGLE)
    triangle = classify_profile([[0, 0], [4, 0], [2, 3]])
    assert triangle.kind == "polygon"
    assert len(triangle.labeled_points) == 3


def test_equal_corner_count_does_not_confuse_z_section_with_t_or_u():
    zigzag = classify_profile(
        [[0, 0], [3, 0], [3, 1], [2, 1], [2, 3], [0, 3], [0, 2], [1, 2]]
    )
    assert zigzag.kind == "polygon"


@pytest.mark.parametrize("transformed", [False, True])
def test_body_slice_recovers_l_shape_with_a_proper_part_frame(transformed):
    triangles = extrusion(
        np.array(L_PROFILE), np.array([[0, 1, 3], [1, 2, 3], [0, 3, 5], [3, 4, 5]]), 2.0
    )
    rot, shift = (
        (rotation(), np.array([7.0, -4.0, 13.0]))
        if transformed
        else (np.eye(3), np.zeros(3))
    )
    triangles = triangles @ rot.T + shift
    result = segment_mesh(mesh_of(triangles))
    (body,) = detect_features(result)
    assert body.kind == "l_profile_extrude"
    assert body.polarity == "additive"
    assert body.height == pytest.approx(2.0)
    assert len(body.profile.points) == 6
    assert set(body.face_ids) == {f.id for f in result.faces}
    frame = np.asarray(body.part_frame)
    np.testing.assert_allclose(frame[:3, :3].T @ frame[:3, :3], np.eye(3), atol=1e-12)
    assert np.linalg.det(frame[:3, :3]) == pytest.approx(1.0)
    local = (triangles.reshape(-1, 3) - frame[:3, 3]) @ frame[:3, :3]
    assert local[:, 2].min() == pytest.approx(0.0, abs=1e-5)
    assert local[:, 2].max() == pytest.approx(2.0, abs=1e-5)
    with pytest.raises(FrozenInstanceError):
        body.height = 8


def test_cube_is_a_rectangle_extrude_and_missing_support_fails_explicitly():
    result = segment_mesh(mesh_of(cube()))
    (body,) = detect_features(result)
    assert body.kind == "rectangle_profile_extrude"
    assert body.height == pytest.approx(2.0)
    with pytest.raises(ValueError, match="indexed"):
        detect_features(SegmentationResult(result.faces, result.graph))


def topology(*, kind, transformed=False):
    """A minimal region graph isolates topology/polarity from mesh fitting."""
    inward = kind in ("blind_hole", "fillet")
    side = Face(
        "side",
        "cylinder",
        (0,),
        Cylinder((0.0, 0.0, 1.0), (2.0, 3.0, 0.0), 2.0),
        "concave" if inward else "convex",
    )
    if kind == "fillet":
        planes = [
            Face("host", "plane", (1,), Plane((1.0, 0.0, 0.0), (0.0, 0.0, 0.0))),
            Face("end", "plane", (2,), Plane((0.0, 1.0, 0.0), (0.0, 1.0, 0.0))),
        ]
        signs = ["tangent", "tangent"]
    else:
        planes = [
            Face("host", "plane", (1,), Plane((0.0, 0.0, 1.0), (0.0, 0.0, 5.0))),
            Face(
                "end",
                "plane",
                (2,),
                Plane((0.0, 0.0, 1.0), (0.0, 0.0, 2.0 if inward else 11.0)),
            ),
        ]
        signs = ["convex", "concave"] if inward else ["concave", "convex"]
    if transformed:
        rot, shift = rotation(), np.array([8.0, -9.0, 4.0])
        cylinder = side.params
        side = replace(
            side,
            params=Cylinder(
                tuple(rot @ cylinder.axis),
                tuple(rot @ cylinder.point + shift),
                cylinder.radius,
            ),
        )
        planes = [
            replace(
                f,
                params=Plane(
                    tuple(rot @ f.params.normal), tuple(rot @ f.params.point + shift)
                ),
            )
            for f in planes
        ]
    faces = [side, *planes]
    graph = nx.Graph()
    graph.add_nodes_from((face.id, {"face": face}) for face in faces)
    for plane, sign in zip(planes, signs):
        graph.add_edge(side.id, plane.id, convexity=sign)
    return SegmentationResult(faces, graph)


@pytest.mark.parametrize(
    "kind, length", [("boss", 6.0), ("blind_hole", 3.0), ("fillet", None)]
)
@pytest.mark.parametrize("transformed", [False, True])
def test_graph_topology_gives_feature_polarity_and_host(kind, length, transformed):
    result = topology(kind=kind, transformed=transformed)
    (item,) = _cylinder_features(result)
    assert item["kind"] == kind
    if length is not None:
        assert item["length"] == pytest.approx(length)
        assert item["host"].id == "host"
        assert item["end"].id == "end"
    else:
        assert {face.id for face in item["between"]} == {"host", "end"}


def test_ambiguous_caps_and_wrong_side_caps_are_rejected():
    result = topology(kind="blind_hole")
    result.graph["side"]["end"]["convexity"] = "convex"
    with pytest.raises(ValueError, match="Unsupported cylinder topology"):
        _cylinder_features(result)
    result = topology(kind="boss")
    end = replace(result.faces[-1], params=Plane((0.0, 0.0, 1.0), (0.0, 0.0, 4.0)))
    result.faces[-1] = end
    result.graph.nodes[end.id]["face"] = end
    with pytest.raises(ValueError, match="wrong side"):
        _cylinder_features(result)


def test_surface_distance_is_deterministic_and_detects_a_translation():
    original = mesh_of(cube())
    assert mesh_hausdorff(original, original, samples=32) < 1e-12
    shifted = mesh_of(cube() + [0.2, 0.0, 0.0])
    first = mesh_hausdorff(original, shifted, samples=64)
    assert first == mesh_hausdorff(original, shifted, samples=64)
    assert first == pytest.approx(0.2, abs=1e-6)


def test_feature_solid_is_built_from_parameters_and_a_changed_dimension_fails(
    monkeypatch,
):
    # Use a tiny Python solid backend here, so this unit test needs no OpenSCAD.
    # The bracket target separately exercises the real OpenSCAD CSG backend.
    original = mesh_of(cube())
    (body,) = detect_features(segment_mesh(original))
    from stl2scad.core.segmentation import solid

    def render(features):
        (feature,) = features
        points = np.asarray(feature.profile.points)
        assert len(points) == 4
        local = extrusion(points, np.array([[0, 1, 2], [0, 2, 3]]), feature.height)
        frame = np.asarray(feature.part_frame)
        return mesh_of(local @ frame[:3, :3].T + frame[:3, 3])

    monkeypatch.setattr(solid, "reconstruct_mesh", render)
    assert hausdorff_to_mesh([body], original) < 1e-6
    assert hausdorff_to_mesh([replace(body, height=3.0)], original) > 0.9


def test_empty_geometry_cannot_pass_hausdorff_or_feature_reconstruction():
    with pytest.raises(ValueError, match="empty feature"):
        reconstruct_mesh([])
    with pytest.raises(ValueError, match="nonempty"):
        mesh_hausdorff(mesh_of(np.empty((0, 3, 3))), mesh_of(cube()))


def test_bracket_features_partition_faces_and_frames_follow_the_part(rendered):
    results = {name: segment_mesh(mesh) for name, mesh in rendered.items()}
    features = {name: detect_features(result) for name, result in results.items()}
    for name, recovered in features.items():
        owners = [face_id for f in recovered for face_id in f.face_ids]
        assert len(owners) == len(set(owners)) == 13
        assert set(owners) == {f.id for f in results[name].faces}
        frame = np.asarray(recovered[0].part_frame)
        for feature in recovered:
            assert feature.part_frame == recovered[0].part_frame
            if feature.on_face:
                host = results[name].graph.nodes[feature.on_face]["face"]
                point = frame[:3, :3] @ feature.position + frame[:3, 3]
                assert np.dot(point, host.params.normal) == pytest.approx(
                    host.params.offset, abs=1e-5
                )
    transform = np.eye(4)
    transform[:3, :3] = _rotation(VARIANTS["rotated"]["rotate_deg"])
    transform[:3, 3] = transform[:3, :3] @ VARIANTS["rotated"]["translate_before"]
    np.testing.assert_allclose(
        features["rotated"][0].part_frame,
        transform @ np.asarray(features["axis_aligned"][0].part_frame),
        atol=3e-6,
    )
    for a, b in zip(features["axis_aligned"], features["rotated"]):
        np.testing.assert_allclose(a.position, b.position, atol=3e-6)
        np.testing.assert_allclose(a.axis, b.axis, atol=1e-6)


def test_real_reconstruction_rejects_missing_fillet_and_an_oversized_boss(rendered):
    mesh = rendered["rotated"]
    features = detect_features(segment_mesh(mesh))
    missing_fillet = [f for f in features if f.kind != "fillet"]
    assert hausdorff_to_mesh(missing_fillet, mesh) > 0.8
    taller = [
        replace(f, height=f.height + 3) if f.kind == "boss" else f for f in features
    ]
    assert hausdorff_to_mesh(taller, mesh) > 2.9


@pytest.mark.parametrize(
    "profile, cap, kind",
    [
        (
            U_PROFILE,
            [[0, 1, 4], [0, 4, 5], [1, 2, 3], [1, 3, 4], [0, 5, 6], [0, 6, 7]],
            "u_profile_extrude",
        ),
        (
            T_PROFILE,
            [[1, 2, 3], [1, 3, 4], [7, 0, 1], [7, 1, 4], [7, 4, 5], [7, 5, 6]],
            "t_profile_extrude",
        ),
    ],
)
@pytest.mark.parametrize("rotated", [False, True])
def test_u_and_t_sections_are_recovered_from_mesh_caps(profile, cap, kind, rotated):
    triangles = extrusion(np.asarray(profile), np.asarray(cap), 2.0)
    if rotated:
        triangles = triangles @ rotation().T + [3, -8, 2]
    (body,) = detect_features(segment_mesh(mesh_of(triangles)))
    assert body.kind == kind
    assert len(body.profile.points) == 8
    assert body.height == pytest.approx(2.0)
