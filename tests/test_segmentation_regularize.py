"""Direction constraints and extrusion-axis selection, independent of step 4 wiring."""

from itertools import combinations

import networkx as nx
import numpy as np
import pytest

from stl2scad.core.segmentation import detect_features, hausdorff_to_mesh, segment_mesh
from stl2scad.core.segmentation.models import Cylinder, Face, Plane, SegmentationResult
from stl2scad.core.segmentation.repair import repair_mesh
from stl2scad.core.segmentation.regularize import extrusion_axis, regularize
from tests.test_segmentation_bracket import (
    VARIANTS,
    _rotation,
    openscad_path,
    rendered as bracket_meshes,
)
from tests.test_segmentation_geometry import mesh_of
from tests.test_segmentation_treatments_truth import (
    CASES,
    PARTS,
    rendered as treatment_meshes,
    variant_for,
)


def _plane_result(directions, areas=None):
    """Disconnected one-triangle planes, with a discarded source triangle first."""
    areas = [1] * len(directions) if areas is None else areas
    triangles = [np.zeros((3, 3))]
    faces = []
    for i, (normal, area) in enumerate(zip(directions, areas), 1):
        normal = np.asarray(normal, dtype=float)
        normal /= np.linalg.norm(normal)
        u = np.cross(normal, np.eye(3)[np.argmin(abs(normal))])
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)
        origin = np.array([2 * i, 3 * i, 7 * i], dtype=float)
        points = np.array([origin, origin + u * 2 * area, origin + v])
        triangles.append(points)
        faces.append(
            Face(
                f"F{i}", "plane", (i,), Plane(tuple(normal), tuple(points.mean(axis=0)))
            )
        )
    graph = nx.Graph()
    graph.add_nodes_from((f.id, {"face": f}) for f in faces)
    return SegmentationResult(faces, graph, repair_mesh(mesh_of(triangles)))


@pytest.mark.parametrize("variant_name", VARIANTS)
def test_regularize_makes_bracket_directions_exact(bracket_meshes, variant_name):
    mesh = bracket_meshes[variant_name]
    before = segment_mesh(mesh)
    after = regularize(before)
    assert after.graph is before.graph and after.mesh is before.mesh
    assert [f.id for f in after.faces] == [f.id for f in before.faces]
    for old, new in zip(before.faces, after.faces):
        assert new.triangle_indices is old.triangle_indices
        assert new.kind == old.kind and new.convexity == old.convexity
    normals = [np.asarray(f.params.normal) for f in after.faces if f.kind == "plane"]
    for a, b in combinations(normals, 2):
        angle = np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b)), a @ b))
        assert min(abs(angle - target) for target in [0, 90, 180]) < 1e-9
    assert hausdorff_to_mesh(detect_features(after), mesh) < 0.05


def test_regularize_leaves_distinct_directions():
    normal = _rotation([0, 2, 0]) @ [0, 0, 1]
    before = _plane_result([[0, 0, 1], normal])
    after = regularize(before)
    for a, b in zip(before.faces, after.faces):
        np.testing.assert_allclose(a.params.normal, b.params.normal, rtol=0, atol=1e-12)


def test_regularize_weights_area_aligns_opposites_and_refits_offsets():
    normal = _rotation([0, 0.2, 0]) @ [0, 0, 1]
    before = _plane_result([[0, 0, 1], -normal], [4, 1])
    after = regularize(before)
    weights = before.mesh.areas
    expected = weights[0] * np.array([0, 0, 1]) + weights[1] * normal
    expected /= np.linalg.norm(expected)
    for i, face in enumerate(after.faces):
        np.testing.assert_allclose(
            face.params.normal, expected * (1 if i == 0 else -1), atol=1e-14
        )
        points = before.mesh.vertices[before.mesh.triangles[i]]
        assert face.params.offset == pytest.approx(
            points.mean(axis=0) @ face.params.normal, abs=1e-12
        )
    np.testing.assert_array_equal(before.faces[0].params.normal, [0, 0, 1])


def test_regularize_orthogonalizes_dominant_clusters_largest_first():
    directions = [
        [0, 0, 1],
        _rotation([0, 0.2, 0]) @ [1, 0, 0],
        _rotation([0.2, 0, 0]) @ [0, 1, 0],
    ]
    before = _plane_result(directions, [10, 3, 1])
    after = regularize(before)
    np.testing.assert_allclose(after.faces[0].params.normal, [0, 0, 1], atol=1e-15)
    normals = np.array([f.params.normal for f in after.faces])
    np.testing.assert_allclose(normals @ normals.T, np.eye(3), rtol=0, atol=1e-14)


@pytest.mark.parametrize("rotated", [False, True])
def test_regularize_refits_cylinder_vertices_with_fixed_axis(rotated):
    rotation = _rotation([23, 7, -18]) if rotated else np.eye(3)
    axis = rotation @ [0, 0, 1]
    reference = rotation @ [1, 0, 0]
    center = np.array([7.0, -2.0, 3.0]) + rotation @ [4.0, 2.0, 0.0]
    angles = np.arange(16) * 2 * np.pi / 16
    ring = 3 * np.column_stack([np.cos(angles), np.sin(angles), np.zeros(16)])
    lower = ring @ rotation.T + center
    upper = lower + 4 * axis
    triangles = []
    for i in range(16):
        j = (i + 1) % 16
        triangles.extend(
            [[lower[i], lower[j], upper[j]], [lower[i], upper[j], upper[i]]]
        )
    repaired = repair_mesh(mesh_of(triangles))
    model = Cylinder(
        tuple(axis),
        tuple(center - axis * (center @ axis) + 0.4 * reference),
        2.5,
        16,
        tuple(reference),
    )
    face = Face("C", "cylinder", tuple(range(32)), model, "convex")
    before = SegmentationResult([face], nx.Graph(), repaired)
    after = regularize(before)
    fitted = after.faces[0].params
    np.testing.assert_allclose(fitted.axis, axis, atol=1e-14)
    np.testing.assert_allclose(fitted.point, center - axis * (center @ axis), atol=1e-6)
    assert fitted.radius == pytest.approx(3, abs=1e-6)
    assert fitted.segments == 16
    np.testing.assert_allclose(fitted.radial_reference, reference, atol=1e-14)
    assert abs(np.dot(fitted.point, fitted.axis)) < 1e-12
    assert before.faces[0].params.radius == 2.5


def test_extrusion_axis_uses_cap_area_to_break_equal_support():
    rotation = _rotation([23, 7, -18])
    result = _plane_result(np.eye(3) @ rotation.T, [1, 20, 100])
    assert abs(extrusion_axis(result) @ rotation[:, 2]) > 1 - 1e-14


def test_extrusion_axis_maximizes_support_before_cap_tiebreak():
    # X explains all four planes. Z has much larger caps, but cannot explain
    # the diagonal plane, so the specified primary score requires X.
    result = _plane_result(
        [[0, 0, 1], [0, 1, 0], [0, 1, 1], [1, 0, 0]], [100, 20, 10, 1]
    )
    assert abs(extrusion_axis(result) @ [1, 0, 0]) > 1 - 1e-14


def test_extrusion_axis_explains_treatment_adjacent_to_cap_and_side():
    result = _plane_result(
        [[0, 0, 1], [0, 1, 0], [0, 1, 1], [1, 0, 0]], [100, 20, 10, 1]
    )
    result.graph.add_edges_from([("F3", "F1"), ("F3", "F2")])
    assert abs(extrusion_axis(result) @ [0, 0, 1]) > 1 - 1e-14


@pytest.mark.parametrize("oblique_area,expected", [(1, [0, 0, 1]), (2, [1, 0, 0])])
def test_extrusion_axis_breaks_one_percent_ties_with_cap_area(oblique_area, expected):
    result = _plane_result(
        [[0, 0, 1], [0, 1, 0], [0, 1, 1], [1, 0, 0]], [100, 20, oblique_area, 1]
    )
    assert abs(extrusion_axis(result) @ expected) > 1 - 1e-14


def test_extrusion_axis_candidates_are_plane_normal_directions():
    rotation = _rotation([23, 7, -18])
    result = _plane_result(np.array([[1, 0, 0], [1, 1, 0]]) @ rotation.T)
    # The revised rule considers plane-normal directions, so the common
    # perpendicular is not a candidate when no plane normal supplies it.
    axis = extrusion_axis(result)
    assert max(abs(axis @ f.params.normal) for f in result.faces) > 1 - 1e-14


@pytest.mark.parametrize("convexity", ["convex", "concave"])
def test_extrusion_axis_explains_full_circle_and_its_oblique_end_caps(convexity):
    body = _plane_result(np.eye(3), [1, 20, 100])
    triangles = [np.zeros((3, 3)), *body.mesh.vertices[body.mesh.triangles]]
    rotation = _rotation([23, 32, -18])
    axis, u = rotation[:, 2], rotation[:, 0]
    center = np.array([40.0, 50.0, 60.0])
    angles = np.arange(16) * 2 * np.pi / 16
    bottom = (
        center
        + 5
        * np.column_stack((np.cos(angles), np.sin(angles), np.zeros(16)))
        @ rotation.T
    )
    top = bottom + 4 * axis
    sides, lower, upper = [], [], []
    for i in range(16):
        j = (i + 1) % 16
        sides.extend([[bottom[i], bottom[j], top[j]], [bottom[i], top[j], top[i]]])
        lower.append([center, bottom[j], bottom[i]])
        upper.append([center + 4 * axis, top[i], top[j]])
    faces = list(body.faces)
    for name, points, params in [
        (
            "round",
            sides,
            Cylinder(
                tuple(axis), tuple(center - axis * (center @ axis)), 5, 16, tuple(u)
            ),
        ),
        ("lower", lower, Plane(tuple(-axis), tuple(center))),
        ("upper", upper, Plane(tuple(axis), tuple(center + 4 * axis))),
    ]:
        start = len(triangles)
        triangles.extend(points)
        faces.append(
            Face(
                name,
                "cylinder" if name == "round" else "plane",
                tuple(range(start, len(triangles))),
                params,
                convexity if name == "round" else None,
            )
        )
    graph = body.graph.copy()
    graph.add_nodes_from((f.id, {"face": f}) for f in faces)
    graph.add_edges_from([("round", "lower"), ("round", "upper")], convexity="convex")
    result = SegmentationResult(faces, graph, repair_mesh(mesh_of(triangles)))
    # The round's normal direction has more cap area than Z. Exempting only
    # its wall would select it; its oblique end caps must be exempt as well.
    assert abs(extrusion_axis(result) @ [0, 0, 1]) > 1 - 1e-14


@pytest.mark.parametrize("variant_name", ["axis_aligned", "rotated"])
def test_extrusion_axis_follows_bracket_l_profile(bracket_meshes, variant_name):
    result = regularize(segment_mesh(bracket_meshes[variant_name]))
    fillet = next(
        f
        for f in result.faces
        if f.kind == "cylinder" and f.convexity == "concave" and f.params.radius > 2.9
    )
    expected = _rotation(VARIANTS[variant_name]["rotate_deg"]) @ [0, 1, 0]
    assert abs(np.dot(fillet.params.axis, expected)) > 1 - 1e-12
    assert abs(np.dot(extrusion_axis(result), fillet.params.axis)) > 1 - 1e-12


@pytest.mark.parametrize("name,variant_name", CASES)
def test_extrusion_axis_of_treatment_parts(treatment_meshes, name, variant_name):
    result = regularize(segment_mesh(treatment_meshes[name, variant_name]))
    actual = extrusion_axis(result)
    variant = variant_for(PARTS[name], variant_name)
    expected = _rotation(variant["rotate_deg"]) @ [0, 0, 1]
    assert np.linalg.norm(actual) == pytest.approx(1, abs=1e-14)
    assert abs(np.dot(actual, expected)) > np.cos(np.radians(1e-3))
