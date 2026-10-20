"""Independent slab levels, section geometry, winding and provenance checks."""

from dataclasses import FrozenInstanceError, replace

import networkx as nx
import numpy as np
import pytest

from stl2scad.core.openscad.runner import run_openscad
from stl2scad.core.segmentation import segment_mesh
from stl2scad.core.segmentation.defeature import Defeatured, defeature
from stl2scad.core.segmentation.models import Face, Plane, SegmentationResult
from stl2scad.core.segmentation.profile_geometry import boundary_distance
from stl2scad.core.segmentation.repair import repair_mesh
from stl2scad.core.segmentation.sections import profile_points
from stl2scad.core.segmentation.slabs import Slab, slab_levels, slab_profiles
from tests.test_segmentation_bracket import _rotation, openscad_path
from tests.test_segmentation_geometry import extrusion, mesh_of
from tests.test_segmentation_rounded_plate import (
    VARIANTS as ROUND_VARIANTS,
    rendered as rounded_meshes,
)
from tests.test_segmentation_treatments_truth import PARTS, rendered as treatment_meshes


VARIANTS = [v["name"] for v in PARTS["stepped_bar"]["variants"]]


def _frame(part, name):
    variant = next(v for v in PARTS[part]["variants"] if v["name"] == name)
    frame = np.eye(4)
    frame[:3, :3] = _rotation(variant["rotate_deg"])
    frame[:3, 3] = frame[:3, :3] @ variant["translate_before"]
    return frame


def _area(profile):
    points = profile_points(profile)
    return (
        np.sum(
            points[:, 0] * np.roll(points[:, 1], -1)
            - points[:, 1] * np.roll(points[:, 0], -1)
        )
        / 2
    )


def _assert_ownership(slabs, result):
    owned = [f for slab in slabs for f in slab.face_ids]
    assert len(owned) == len(set(owned))
    assert set(owned) == {f.id for f in result.faces}
    for slab in slabs:
        references = {
            f
            for loop in slab.loops
            for segment in loop.segments
            for f in segment.face_ids
        }
        assert references <= set(owned)
        assert set(slab.point_face_ids) <= references


@pytest.mark.parametrize("name", VARIANTS)
def test_stepped_bar_levels_and_loops(treatment_meshes, name):
    original = segment_mesh(treatment_meshes["stepped_bar", name])
    result = defeature(original)
    frame = _frame("stepped_bar", name)
    np.testing.assert_allclose(slab_levels(result, frame), [0, 2, 10], atol=0.01)
    slabs = slab_profiles(result, frame)
    assert [s.index for s in slabs] == [1, 2]
    np.testing.assert_allclose(
        [(s.bottom, s.top) for s in slabs], [[0, 2], [2, 10]], atol=0.01
    )
    assert [len(s.loops) for s in slabs] == [1, 2]
    assert _area(slabs[0].loops[0]) == pytest.approx(180, abs=1e-3)
    np.testing.assert_allclose(
        np.ptp(profile_points(slabs[0].loops[0]), axis=0), [30, 6], atol=1e-3
    )
    upper = sorted(slabs[1].loops, key=lambda p: profile_points(p)[:, 0].mean())
    for loop, radius, centers, sweep in [
        (upper[0], 0.5, [[4.5, 3], [19.5, 3]], 180),
        (upper[1], 1, [[29, 1], [29, 5]], 90),
    ]:
        assert _area(loop) > 0
        arcs = [s for s in loop.segments if s.kind == "arc"]
        assert len(arcs) == 2
        np.testing.assert_allclose(
            sorted((s.center for s in arcs), key=lambda c: tuple(np.round(c, 3))),
            sorted(centers),
            atol=1e-3,
        )
        for arc in arcs:
            assert arc.radius == pytest.approx(radius, rel=0.02)
            assert abs(arc.sweep_deg) == pytest.approx(sweep, abs=1e-3)
            assert arc.segments == (16 if name == "fn16_rotated" else 64)
            face = next(f for f in result.result.faces if f.id == arc.face_ids[0])
            reference = np.asarray(face.params.radial_reference) @ frame[:3, :3]
            expected = np.degrees(np.arctan2(reference[1], reference[0]))
            assert abs((arc.phase_deg - expected + 180) % 360 - 180) < 1e-5
    _assert_ownership(slabs, result.result)
    assert all(not s.point_face_ids for s in slabs)
    with pytest.raises(FrozenInstanceError):
        slabs[0].index = 7
    assert slabs == slab_profiles(result, frame)


@pytest.mark.parametrize("name", VARIANTS)
def test_clipped_arc_plate_profile(treatment_meshes, name):
    result = defeature(segment_mesh(treatment_meshes["clipped_arc_plate", name]))
    assert len(result.treatments) == 1
    frame = _frame("clipped_arc_plate", name)
    slabs = slab_profiles(result, frame)
    assert len(slabs) == 1 and len(slabs[0].loops) == 1
    np.testing.assert_allclose([slabs[0].bottom, slabs[0].top], [0, 10], atol=0.01)
    loop = slabs[0].loops[0]
    arcs = [s for s in loop.segments if s.kind == "arc"]
    assert len(arcs) == 4 and all(s.radius == pytest.approx(3, rel=0.02) for s in arcs)
    n = 16 if name == "fn16_rotated" else 64
    expected = np.vstack(
        [
            np.array(center)
            + 3
            * np.column_stack((np.cos(np.radians(angles)), np.sin(np.radians(angles))))
            for center, start in [
                ([3, 3], 180),
                ([37, 3], 270),
                ([37, 17], 0),
                ([3, 17], 90),
            ]
            for angles in [np.linspace(start, start + 90, n // 4 + 1)]
        ]
    )
    assert boundary_distance(profile_points(loop), expected) < 0.001
    assert _area(loop) > 0
    assert not slabs[0].point_face_ids
    _assert_ownership(slabs, result.result)


def _ellipse_region(rotation, shift):
    # Exact hand-labeled surface regions: 3x8 quarter-ellipse, straight walls,
    # and two caps. The slab consumer is given the unmodeled wall as a mesh
    # region, without asking the current plane/cylinder detector to fit it.
    angles = np.linspace(np.pi, 1.5 * np.pi, 65)
    curve = [3, 8] + np.column_stack((3 * np.cos(angles), 8 * np.sin(angles)))
    profile = np.vstack((curve, [[12, 0], [12, 16], [0, 16]]))
    n = len(profile)
    cap = np.array([[0, i, i + 1] for i in range(1, n - 1)])
    triangles = extrusion(profile, cap, height=3) @ rotation.T + shift
    mesh = repair_mesh(mesh_of(triangles))
    cap_count = n - 2
    faces = [
        Face(
            "bottom",
            "plane",
            tuple(range(cap_count)),
            Plane(tuple(rotation @ [0, 0, -1]), tuple(shift)),
        ),
        Face(
            "top",
            "plane",
            tuple(range(cap_count, 2 * cap_count)),
            Plane(tuple(rotation @ [0, 0, 1]), tuple(shift + rotation @ [0, 0, 3])),
        ),
        Face(
            "ellipse_wall",
            "mesh",
            tuple(range(2 * cap_count, 2 * cap_count + 128)),
            None,
        ),
    ]
    for i in range(64, n):
        start = 2 * cap_count + 2 * i
        a, b = profile[i], profile[(i + 1) % n]
        edge = b - a
        normal = np.r_[edge[1], -edge[0], 0.0] / np.linalg.norm(edge)
        point = np.r_[a, 0.0]
        faces.append(
            Face(
                f"side_{i}",
                "plane",
                (start, start + 1),
                Plane(tuple(rotation @ normal), tuple(rotation @ point + shift)),
            )
        )
    owner = {source: f.id for f in faces for source in f.triangle_indices}
    graph = nx.Graph()
    graph.add_nodes_from((f.id, {"face": f}) for f in faces)
    for edge in mesh.shared_edges:
        a, b = [owner[int(mesh.source_indices[t])] for t in edge.triangles]
        if a != b:
            if not graph.has_edge(a, b):
                graph.add_edge(a, b, convexity="convex", mesh_edges=[])
            graph[a][b]["mesh_edges"].append(edge.vertices)
    return Defeatured(
        SegmentationResult(faces, graph, mesh), tuple(rotation @ [0, 0, 1]), (), ()
    )


@pytest.mark.parametrize("rotated", [False, True])
def test_point_face_ids_for_non_analytic_side(rotated):
    rotation = _rotation([17, 31, 9]) if rotated else np.eye(3)
    shift = np.array([8.0, -12.0, 5.0])
    result = _ellipse_region(rotation, shift)
    frame = np.eye(4)
    frame[:3, :3], frame[:3, 3] = rotation, shift
    slabs = slab_profiles(result, frame)
    assert len(slabs) == 1 and len(slabs[0].loops) == 1
    assert slabs[0].point_face_ids == ("ellipse_wall",)
    angles = np.linspace(np.pi, 1.5 * np.pi, 1025)
    truth = np.vstack(
        (
            [3, 8] + np.column_stack((3 * np.cos(angles), 8 * np.sin(angles))),
            [[12, 0], [12, 16], [0, 16]],
        )
    )
    assert boundary_distance(profile_points(slabs[0].loops[0]), truth) < 0.001
    assert _area(slabs[0].loops[0]) > 0
    _assert_ownership(slabs, result.result)


@pytest.mark.parametrize("name", ROUND_VARIANTS)
def test_outer_and_hole_loops_have_opposite_winding(rounded_meshes, name):
    result = defeature(segment_mesh(rounded_meshes[name]))
    variant = ROUND_VARIANTS[name]
    frame = np.eye(4)
    frame[:3, :3] = _rotation(variant["rotate_deg"])
    frame[:3, 3] = frame[:3, :3] @ variant["translate_before"]
    slabs = slab_profiles(result, frame)
    assert len(slabs) == 1 and len(slabs[0].loops) == 4
    areas = sorted(_area(loop) for loop in slabs[0].loops)
    assert all(a < 0 for a in areas[:3]) and areas[3] > 0
    _assert_ownership(slabs, result.result)


def test_equal_adjacent_sections_merge(openscad_path, tmp_path):
    source, target = tmp_path / "small_step.scad", tmp_path / "small_step.stl"
    source.write_text(
        "union(){cube([10,8,1.5]);translate([0.0001,0,1.5])cube([9.9998,8,1.5]);}"
    )
    assert run_openscad(
        "equal sections",
        ["--render", "-o", str(target), str(source)],
        str(target.with_suffix(".log")),
        openscad_path,
    )
    from stl.mesh import Mesh

    result = defeature(segment_mesh(Mesh.from_file(str(target))))
    frame = np.eye(4)
    assert len(slab_levels(result, frame)) == 3
    slabs = slab_profiles(result, frame)
    assert len(slabs) == 1
    np.testing.assert_allclose([slabs[0].bottom, slabs[0].top], [0, 3], atol=0.001)
    _assert_ownership(slabs, result.result)


def test_merged_sections_keep_all_side_provenance(openscad_path, tmp_path):
    source, target = tmp_path / "merged.scad", tmp_path / "merged.stl"
    source.write_text(
        "union(){cube([10,8,1.5]);translate([0.0001,0,1.5])cube([9.9998,8,1.5]);}"
    )
    assert run_openscad(
        "merged provenance",
        ["--render", "-o", str(target), str(source)],
        str(target.with_suffix(".log")),
        openscad_path,
    )
    from stl.mesh import Mesh

    result = defeature(segment_mesh(Mesh.from_file(str(target))))
    slabs = slab_profiles(result, np.eye(4))
    assert len(slabs) == 1
    references = {
        fid
        for loop in slabs[0].loops
        for segment in loop.segments
        for fid in segment.face_ids
    }
    sides = {
        f.id
        for f in result.result.faces
        if isinstance(f.params, Plane) and abs(f.params.normal[2]) < 1e-6
    }
    assert references == sides


def test_open_cylinder_strip_cannot_become_a_full_circle(treatment_meshes):
    result = defeature(
        segment_mesh(treatment_meshes["clipped_arc_plate", "axis_aligned"])
    )
    arc = next(f for f in result.result.faces if f.kind == "cylinder")
    faces = [
        f
        for f in result.result.faces
        if f.id == arc.id
        or (isinstance(f.params, Plane) and abs(f.params.normal[2]) > 0.999)
    ]
    graph = result.result.graph.subgraph([f.id for f in faces]).copy()
    incomplete = replace(
        result, result=replace(result.result, faces=faces, graph=graph)
    )
    with pytest.raises(ValueError, match="closed"):
        slab_profiles(incomplete, np.eye(4))


def test_faces_outside_cap_levels_remain_unowned():
    # Slab ownership is an explained-face set, not a claim to the entire part.
    # A separate opaque closed region above the caps belongs to the later
    # remainder stage; it must not prevent recovering the plate below it.
    result = _ellipse_region(np.eye(3), np.zeros(3))
    mesh = result.result.mesh
    a, b, c, d = np.array([[20, 0, 5], [21, 0, 5], [20, 1, 5], [20, 0, 6]], dtype=float)
    tetra = np.array([[a, c, b], [a, b, d], [a, d, c], [b, c, d]])
    triangles = np.concatenate((mesh.vertices[mesh.triangles], tetra))
    extra = Face(
        "opaque_above", "mesh", tuple(range(len(mesh.triangles), len(triangles))), None
    )
    graph = result.result.graph.copy()
    graph.add_node(extra.id, face=extra)
    complete = replace(
        result,
        result=replace(
            result.result,
            mesh=repair_mesh(mesh_of(triangles)),
            faces=result.result.faces + [extra],
            graph=graph,
        ),
    )
    slabs = slab_profiles(complete, np.eye(4))
    assert len(slabs) == 1
    np.testing.assert_allclose([slabs[0].bottom, slabs[0].top], [0, 3], atol=1e-8)
    assert "opaque_above" not in slabs[0].face_ids
    assert set(slabs[0].face_ids) == {f.id for f in result.result.faces}
