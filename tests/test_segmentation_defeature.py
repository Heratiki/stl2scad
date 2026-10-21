"""Task 3: remove only supported 3D treatments, preserving analytic provenance."""

from dataclasses import FrozenInstanceError

import numpy as np
import pytest
from stl.mesh import Mesh

from stl2scad.core.openscad.runner import run_openscad
from stl2scad.core.segmentation import segment_mesh
from stl2scad.core.segmentation.defeature import Defeatured, EdgeTreatment, defeature
from tests.test_segmentation_bracket import _rotation, openscad_path
from tests.test_segmentation_rounded_plate import (
    VARIANTS as ROUND_VARIANTS,
    rendered as rounded_meshes,
)
from tests.test_segmentation_treatments_truth import (
    PARTS,
    rendered as treatment_meshes,
    variant_for,
)

TREATMENTS = [
    (name, variant["name"])
    for name in ["chamfered_block", "edge_round_block", "clipped_arc_plate"]
    for variant in PARTS[name]["variants"]
]


def _match(result, part, variant_name):
    variant = variant_for(part, variant_name)
    rotation = _rotation(variant["rotate_deg"])
    shift = np.asarray(variant["translate_before"])
    matched = {}
    for expected in part["faces"]:
        key = "normal" if expected["kind"] == "plane" else "axis"
        target = expected | {
            "point": rotation @ (np.asarray(expected["point"]) + shift),
            key: rotation @ expected[key],
        }
        candidates = [
            f
            for f in result.faces
            if f.kind == expected["kind"]
            and f.id not in {m.id for m in matched.values()}
        ]
        best = min(candidates, key=lambda f: f.distance_to(target))
        assert best.matches(target, part["tolerances"]), expected["id"]
        matched[expected["id"]] = best
    return matched


@pytest.mark.parametrize("name,variant_name", TREATMENTS)
def test_chamfers_and_rounds_are_removed(treatment_meshes, name, variant_name):
    part = PARTS[name]
    original = segment_mesh(treatment_meshes[name, variant_name])
    matched = _match(original, part, variant_name)
    original_nodes = dict(original.graph.nodes(data="face"))
    original_edges = set(original.graph.edges)
    output = defeature(original)
    assert isinstance(output, Defeatured)
    assert output.rejected == ()
    expected = [f for f in part["features"] if f["kind"] in {"chamfer", "edge_round"}]
    assert len(output.treatments) == len(expected)
    by_id = {t.id: t for t in output.treatments}
    assert set(by_id) == {e["id"] for e in expected}
    rotation = _rotation(variant_for(part, variant_name)["rotate_deg"])
    shift = np.asarray(variant_for(part, variant_name)["translate_before"])
    for e in expected:
        treatment = by_id[e["id"]]
        assert isinstance(treatment, EdgeTreatment)
        assert treatment.kind == e["kind"]
        assert treatment.face_id == matched[e["faces"][0]].id
        assert set(treatment.hosts) == {matched[i].id for i in e["hosts"]}
        size = next(iter(e["dimensions"].values()))
        assert treatment.size == pytest.approx(size, rel=0.02)
        direction = rotation @ e["edge_direction"]
        assert abs(np.dot(treatment.edge_direction, direction)) > 1 - 1e-10
        point = rotation @ (np.asarray(e["edge_point"]) + shift)
        assert (
            np.linalg.norm(
                np.cross(np.asarray(treatment.edge_point) - point, direction)
            )
            < 0.05
        )
        if treatment.kind == "edge_round":
            curved = matched[e["faces"][0]].params
            assert (
                treatment.segments
                == variant_for(part, variant_name)["tessellation"]["fn"]
            )
            assert treatment.radial_reference is not None
            assert (
                abs(np.dot(treatment.radial_reference, treatment.edge_direction))
                < 1e-12
            )
            np.testing.assert_allclose(
                treatment.radial_reference, curved.radial_reference, atol=1e-6
            )
        else:
            assert treatment.segments is None and treatment.radial_reference is None
        with pytest.raises(FrozenInstanceError):
            treatment.size = 99
    removed = {t.face_id for t in output.treatments}
    assert {f.id for f in output.result.faces} == {
        f.id for f in original.faces
    } - removed
    assert set(output.result.graph) == {f.id for f in output.result.faces}
    assert output.result.mesh is original.mesh
    assert output.result.graph is not original.graph
    assert set(original.graph.edges) == original_edges
    assert dict(original.graph.nodes(data="face")) == original_nodes
    for face in output.result.faces:
        assert output.result.graph.nodes[face.id]["face"] is face
        assert face.triangle_indices is next(
            f.triangle_indices for f in original.faces if f.id == face.id
        )
    assert abs(output.axis @ (rotation @ [0, 0, 1])) > 1 - 1e-10
    with pytest.raises(FrozenInstanceError):
        output.axis = (1, 0, 0)
    # Idempotence: an already-defeatured result must not manufacture treatments.
    assert defeature(output.result).treatments == ()


def test_asymmetric_chamfer_is_rejected_by_name(treatment_meshes):
    original = segment_mesh(
        treatment_meshes["asymmetric_chamfer_block", "axis_aligned"]
    )
    part = PARTS["asymmetric_chamfer_block"]
    matched = _match(original, part, "axis_aligned")
    output = defeature(original)
    assert output.treatments == ()
    assert output.rejected == (
        (matched["asymmetric_chamfer"].id, "asymmetric chamfer"),
    )
    assert {f.id for f in output.result.faces} == {f.id for f in original.faces}


@pytest.mark.parametrize("variant_name", ROUND_VARIANTS)
def test_profile_arcs_are_not_treatments(
    rounded_meshes, treatment_meshes, variant_name
):
    original = segment_mesh(rounded_meshes[variant_name])
    output = defeature(original)
    assert output.treatments == () and output.rejected == ()
    assert {f.id for f in output.result.faces} == {f.id for f in original.faces}
    # Clipped profile arcs and both semicircular rib ends stay in the graph.
    for name in ["clipped_arc_plate", "stepped_bar"]:
        for variant in PARTS[name]["variants"]:
            before = segment_mesh(treatment_meshes[name, variant["name"]])
            after = defeature(before)
            curved = {f.id for f in before.faces if f.kind == "cylinder"}
            assert curved <= {f.id for f in after.result.faces}
            assert not any(t.face_id in curved for t in after.treatments)


@pytest.mark.parametrize("rotate_deg", [[0, 0, 0], [17, 31, 9]])
def test_oblique_edge_is_not_a_treatment(openscad_path, tmp_path, rotate_deg):
    # Only a short front-right edge is 20 degrees off the dominant X/Y frame.
    # Rotating the complete part must not turn that edge into a supported one.
    source = tmp_path / "oblique.scad"
    source.write_text(
        f"rotate({rotate_deg}) translate([-30,-20,-4]) "
        + """
        difference() {
            linear_extrude(height=8)
                polygon([[0,0],[40,0],[60,20*tan(20)],[60,40],[0,40]]);
            multmatrix([
                [-sin(20),0,cos(20),40-100*cos(20)],
                [ cos(20),0,sin(20),-100*sin(20)],
                [0,-1,0,8], [0,0,0,1]])
                // Extend outside the solid to avoid coincident cutter walls.
                linear_extrude(height=220) polygon([[-1,-1],[3,-1],[-1,3]]);
        }
    """
    )
    target = tmp_path / "oblique.stl"
    assert run_openscad(
        "oblique truth",
        ["--render", "-o", str(target), str(source)],
        str(target.with_suffix(".log")),
        openscad_path,
    )
    original = segment_mesh(Mesh.from_file(str(target)))
    rotation = _rotation(rotate_deg)
    angle = np.radians(20)
    side = np.array([np.sin(angle), -np.cos(angle), 0])
    normal = (side + [0, 0, 1]) / np.sqrt(2)
    point = np.array([40.0, 0.0, 8.0]) - 2 * side
    expected = {
        "kind": "plane",
        "normal": rotation @ normal,
        "point": rotation @ (point - [30, 20, 4]),
    }
    chamfer = min(
        (f for f in original.faces if f.kind == "plane"),
        key=lambda f: f.distance_to(expected),
    )
    assert chamfer.matches(expected, PARTS["chamfered_block"]["tolerances"])
    output = defeature(original)
    assert output.treatments == ()
    assert output.rejected == ((chamfer.id, "oblique edge"),)
    assert {f.id for f in output.result.faces} == {f.id for f in original.faces}


@pytest.mark.parametrize("wall_angle", [0, 60])
def test_chamfer_on_hexagonal_prism_wall_is_found(openscad_path, tmp_path, wall_angle):
    from tests.test_segmentation_treatments_truth import EXPECTED

    truth = EXPECTED["hexagonal_prism"]
    r, h, c = truth["radius"], truth["height"], truth["chamfer_width"]
    a = r * np.cos(np.pi / 6)
    source = tmp_path / f"hex_{wall_angle}.scad"
    source.write_text(
        f"""
        difference() {{
            rotate([0, 0, 30]) cylinder(r={r}, h={h}, $fn=6);
            rotate([0, 0, {wall_angle}]) rotate([90, 0, 0]) translate([0, 0, -30])
                linear_extrude(60)
                    polygon([[{a - c}, {h}], [{a + 1}, {h}], [{a + 1}, {h - c - 1}]]);
        }}
        """
    )
    target = tmp_path / f"hex_{wall_angle}.stl"
    assert run_openscad(
        f"hex_{wall_angle} truth",
        ["--render", "-o", str(target), str(source)],
        str(target.with_suffix(".log")),
        openscad_path,
    )
    mesh = Mesh.from_file(str(target))
    original = segment_mesh(mesh)
    output = defeature(original)
    assert len(output.treatments) == 1
    treatment = output.treatments[0]
    assert treatment.id == "chamfer_1"
    assert treatment.kind == "chamfer"
    assert treatment.size == pytest.approx(c, abs=1e-3)
    assert not any(reason == "oblique edge" for _, reason in output.rejected)


def test_genuinely_oblique_edge_still_rejected(openscad_path, tmp_path):
    # A chamfer whose cutter is tilted along the edge (genuinely slanted,
    # not along the intersection line of its host cap and host side).
    source = tmp_path / "slanted_chamfer.scad"
    source.write_text(
        """
        difference() {
            cube([60, 40, 10]);
            translate([30, 0, 10])
                rotate([0, 20, 0])
                rotate([45, 0, 0])
                translate([-50, -5, -5])
                cube([100, 10, 10]);
        }
        """
    )
    target = tmp_path / "slanted_chamfer.stl"
    assert run_openscad(
        "slanted truth",
        ["--render", "-o", str(target), str(source)],
        str(target.with_suffix(".log")),
        openscad_path,
    )
    mesh = Mesh.from_file(str(target))
    original = segment_mesh(mesh)
    output = defeature(original)
    assert output.treatments == ()
    assert any(reason == "oblique edge" for _, reason in output.rejected)
