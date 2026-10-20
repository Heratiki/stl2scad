"""Fast, renderer-independent checks for segmentation steps 1–3."""

import dataclasses

import numpy as np
import pytest
from stl.mesh import Mesh

from stl2scad.core.segmentation import Cylinder, Face, Plane, segment_mesh
from stl2scad.core.segmentation.fitting import fit_cylinder, fit_plane
from stl2scad.core.segmentation.repair import _weld, repair_mesh


def mesh_of(triangles):
    mesh = Mesh(np.zeros(len(triangles), dtype=Mesh.dtype))
    mesh.vectors[:] = triangles
    return mesh


def extrusion(profile, cap, height=1.5):
    """Extrude a CCW polygon with supplied cap triangulation; no triangulator."""
    bottom = np.column_stack((profile, np.zeros(len(profile))))
    top = bottom + [0, 0, height]
    triangles = [bottom[t[::-1]] for t in cap] + [top[t] for t in cap]
    for a in range(len(profile)):
        b = (a + 1) % len(profile)
        triangles.extend(([bottom[a], bottom[b], top[b]], [bottom[a], top[b], top[a]]))
    return np.asarray(triangles)


def cube():
    return extrusion(
        np.array([[0, 0], [2, 0], [2, 2], [0, 2]]), np.array([[0, 1, 2], [0, 2, 3]]), 2
    )


def rotation():
    # An arbitrary proper rotation independent of the bracket's rotation.
    axis = np.array([1.0, -3.0, 2.0])
    axis /= np.linalg.norm(axis)
    cross = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    angle = 0.83
    return np.eye(3) + np.sin(angle) * cross + (1 - np.cos(angle)) * cross @ cross


@pytest.mark.parametrize("scale", [1e-3, 1.0, 1e3])
def test_welds_duplicated_cube_and_preserves_source_triangles(scale):
    triangles = cube() * scale
    # STL has independent vertex copies. Perturb one across a hash-cell border.
    triangles[0, 0] += [1e-8 * scale, 0, 0]
    original = mesh_of(triangles)
    before = original.vectors.copy()
    repaired = repair_mesh(original)
    assert repaired.vertices.shape == (8, 3)
    assert repaired.vertices.dtype == np.float64
    assert not repaired.vertices.flags.writeable
    assert len(repaired.shared_edges) == 18
    assert all(len(neighbors) == 3 for neighbors in repaired.adjacency)
    np.testing.assert_array_equal(repaired.source_indices, np.arange(12))
    np.testing.assert_array_equal(original.vectors, before)
    result = segment_mesh(original)
    assert len(result.faces) == 6
    assert result.graph.number_of_edges() == 12
    assert all(
        edge["convexity"] == "convex" for _, _, edge in result.graph.edges(data=True)
    )


def test_spatial_weld_checks_neighbor_cells_and_transitive_pairs():
    vertices, labels = _weld(
        np.array([[0.0, 0, 0], [0.99, 0, 0], [1.01, 0, 0], [1.9, 0, 0]]), 0.95
    )
    assert labels[1] == labels[2] == labels[3]
    assert labels[0] != labels[1]
    assert len(vertices) == 2


def test_repair_drops_degenerate_duplicates_without_renumbering_provenance():
    triangles = cube()
    triangles = np.concatenate(([np.zeros((3, 3))], triangles, triangles[[0]]))
    repaired = repair_mesh(mesh_of(triangles))
    np.testing.assert_array_equal(repaired.source_indices, np.arange(1, 13))
    result = segment_mesh(mesh_of(triangles))
    assert sorted(i for face in result.faces for i in face.triangle_indices) == list(
        range(1, 13)
    )


def test_repairs_inconsistent_winding_and_ignores_stored_stl_normals():
    triangles = cube()
    triangles[[0, 2, 5, 9]] = triangles[[0, 2, 5, 9], ::-1]
    mesh = mesh_of(triangles)
    mesh.normals[:] = 0
    result = segment_mesh(mesh)
    center = np.array([1.0, 1.0, 1.0])
    assert len(result.faces) == 6
    for face in result.faces:
        assert np.dot(np.array(face.params.point) - center, face.params.normal) > 0
    assert all(
        edge["convexity"] == "convex" for _, _, edge in result.graph.edges(data=True)
    )


@pytest.mark.parametrize(
    "invalid", [np.empty((0, 3, 3)), np.zeros((1, 3, 3)), np.full((1, 3, 3), np.nan)]
)
def test_rejects_empty_collapsed_or_nonfinite_mesh(invalid):
    with pytest.raises(ValueError):
        repair_mesh(mesh_of(invalid))


def test_rejects_nonmanifold_edges():
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]])
    with pytest.raises(ValueError, match="manifold"):
        repair_mesh(mesh_of(points[[[0, 1, 2], [1, 0, 3], [0, 1, 4]]]))


def test_plane_fit_obeys_outward_normals_at_arbitrary_orientation():
    rng = np.random.default_rng(7)
    rot = rotation()
    points = np.column_stack(
        (rng.uniform(-4, 4, (60, 2)), np.full(60, 3.0))
    ) @ rot.T + [12, 3, -2]
    outward = rot @ np.array([0.0, 0.0, -1.0])
    plane = fit_plane(points, np.tile(outward, (len(points), 1)))
    np.testing.assert_allclose(plane.normal, outward, atol=1e-12)
    assert np.max(np.abs(points @ plane.normal - plane.offset)) < 1e-12


@pytest.mark.parametrize("concave", [False, True])
def test_cylinder_fit_handles_partial_arc_any_orientation_and_normal_polarity(concave):
    rot = rotation()
    theta = np.linspace(0.1, 1.5, 40)
    radial = np.column_stack((np.cos(theta), np.sin(theta), np.zeros(len(theta))))
    local = 3 * radial + np.column_stack(
        (np.zeros((len(theta), 2)), np.linspace(-2, 5, len(theta)))
    )
    points = local @ rot.T + [4, -2, 9]
    normals = radial @ rot.T * (-1 if concave else 1)
    model = fit_cylinder(points, normals)
    axis = rot @ [0, 0, 1]
    assert abs(np.dot(model.axis, axis)) == pytest.approx(1.0)
    assert model.radius == pytest.approx(3.0, abs=1e-11)
    assert np.linalg.norm(np.cross(np.array(model.point) - [4, -2, 9], axis)) < 1e-10


def test_degenerate_primitive_support_is_rejected():
    points = np.array([[0.0, 0, 0], [1, 0, 0], [2, 0, 0]])
    with pytest.raises(ValueError, match="collinear"):
        fit_plane(points, np.tile([0, 0, 1], (3, 1)))
    with pytest.raises(ValueError, match="spread"):
        fit_cylinder(points, np.tile([0, 1, 0], (3, 1)))


@pytest.mark.parametrize("rotated", [False, True])
def test_l_shape_signed_dihedrals_find_concave_corner(rotated):
    triangles = extrusion(
        np.array([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]]),
        np.array([[0, 1, 3], [1, 2, 3], [0, 3, 5], [3, 4, 5]]),
    )
    if rotated:
        triangles = triangles @ rotation().T + [2, 4, -3]
    result = segment_mesh(mesh_of(triangles))
    assert len(result.faces) == 8
    assert result.graph.number_of_edges() == 18
    concave = [
        (a, b)
        for a, b, data in result.graph.edges(data=True)
        if data["convexity"] == "concave"
    ]
    assert len(concave) == 1
    by_id = {f.id: f for f in result.faces}
    a, b = (by_id[key] for key in concave[0])
    assert result.edge_convexity(a, b) == result.edge_convexity(b, a) == "concave"
    for _, _, data in result.graph.edges(data=True):
        assert data["mesh_edges"] and data["triangle_pairs"]
    # Nodes that share no edge must not acquire an inferred adjacency.
    a, b = next(
        (a, b)
        for a in result.faces
        for b in result.faces
        if a != b and not result.graph.has_edge(a.id, b.id)
    )
    with pytest.raises(KeyError):
        result.edge_convexity(a, b)


def test_face_comparison_distinguishes_parallel_planes_and_shifted_axes():
    tol = dict(
        plane_normal_deg=1,
        plane_offset_mm=0.05,
        cylinder_axis_deg=1,
        cylinder_radius_rel=0.02,
    )
    face = Face("F0", "plane", (0,), Plane((0, 0, 1), (0, 0, 3)))
    expected = dict(kind="plane", point=[0, 0, 3], normal=[0, 0, 1])
    assert face.matches(expected, tol)
    assert not face.matches(dict(expected, point=[0, 0, 4]), tol)
    assert not face.matches(dict(expected, normal=[0, 0, -1]), tol)
    cylinder = Face(
        "F1", "cylinder", (1,), Cylinder((0, 0, 1), (4, 2, 0), 3), "concave"
    )
    expected = dict(
        kind="cylinder",
        point=[4, 2, 10],
        axis=[0, 0, -1],
        radius=3,
        convexity="concave",
    )
    assert cylinder.matches(expected, tol)
    assert not cylinder.matches(dict(expected, point=[5, 2, 10]), tol)
    assert not cylinder.matches(dict(expected, convexity="convex"), tol)
    assert face.distance_to(expected) == float("inf")
    with pytest.raises(dataclasses.FrozenInstanceError):
        face.id = "other"


def test_face_ids_and_triangle_ownership_are_deterministic():
    mesh = mesh_of(cube())
    a, b = segment_mesh(mesh), segment_mesh(mesh)
    assert a.faces == b.faces
    assert [f.id for f in a.faces] == [f"F{i}" for i in range(6)]
    ownership = [i for f in a.faces for i in f.triangle_indices]
    assert len(ownership) == len(set(ownership)) == 12


def cylinder_triangles(radius=2.0, height=5.0, sections=32):
    theta = np.arange(sections) * 2 * np.pi / sections
    profile = radius * np.column_stack((np.cos(theta), np.sin(theta)))
    cap = np.array([[0, i, i + 1] for i in range(1, sections - 1)])
    return extrusion(profile, cap, height)


@pytest.mark.parametrize("scale", [1e-3, 1.0, 1e3])
def test_pipeline_cylinder_at_arbitrary_orientation_and_scale(scale):
    triangles = cylinder_triangles()
    rot = rotation()
    mesh = mesh_of((triangles @ rot.T + [1, -3, 2]) * scale)
    result = segment_mesh(mesh)
    assert len(result.faces) == 3
    (curved,) = [face for face in result.faces if face.kind == "cylinder"]
    expected = dict(
        kind="cylinder",
        axis=rot @ [0, 0, 1],
        point=np.array([1, -3, 2]) * scale,
        radius=2 * scale,
        convexity="convex",
    )
    assert curved.matches(
        expected,
        dict(
            cylinder_axis_deg=0.01,
            cylinder_radius_rel=1e-5,
            plane_offset_mm=1e-4 * scale,
        ),
    )
    assert result.graph.number_of_edges() == 2
    assert all(
        data["convexity"] == "convex" for _, _, data in result.graph.edges(data=True)
    )
    again = segment_mesh(mesh)
    assert result.faces == again.faces
    assert sorted(i for f in result.faces for i in f.triangle_indices) == list(
        range(len(mesh))
    )


def test_disconnected_coaxial_regions_keep_separate_faces():
    first = cylinder_triangles(height=2.0)
    second = first + [0, 0, 4]
    result = segment_mesh(mesh_of(np.concatenate((first, second))))
    assert len(result.faces) == 6
    cylinders = [face for face in result.faces if face.kind == "cylinder"]
    assert len(cylinders) == 2
    assert not result.graph.has_edge(cylinders[0].id, cylinders[1].id)
