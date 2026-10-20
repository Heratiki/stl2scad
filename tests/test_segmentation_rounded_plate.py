"""Independent faceted ground truth for outline arcs and through cuts."""

import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from stl.mesh import Mesh

from stl2scad.core.converter import run_openscad
from tests.test_segmentation_bracket import _rotation, openscad_path

DATA = Path(__file__).parent / "data" / "segmentation"
EXPECTED = json.loads((DATA / "rounded_plate_expected.json").read_text())
VARIANTS = {v["name"]: v for v in EXPECTED["variants"]}


def transformed_faces(variant):
    rotation = _rotation(variant["rotate_deg"])
    shift = np.asarray(variant["translate_before"])
    for face in EXPECTED["faces"]:
        face = face | variant.get("face_overrides", {}).get(face["id"], {})
        key = "normal" if face["kind"] == "plane" else "axis"
        yield face | {
            "point": rotation @ (np.asarray(face["point"]) + shift),
            key: rotation @ face[key],
        }


@pytest.fixture(scope="module")
def rendered(openscad_path, tmp_path_factory):
    directory = tmp_path_factory.mktemp("rounded_plate")
    meshes = {}
    for name, variant in VARIANTS.items():
        target = directory / f"{name}.stl"
        assert run_openscad(
            name,
            ["--render", "-o", str(target), str(DATA / variant["scad"])],
            str(directory / f"{name}.log"),
            openscad_path,
        )
        meshes[name] = Mesh.from_file(str(target))
    return meshes


def test_ground_truth_references_are_consistent():
    ids = {f["id"] for f in EXPECTED["faces"]}
    assert len(ids) == len(EXPECTED["faces"]) == 21
    assert len(EXPECTED["edges"]) == 56
    for edge in EXPECTED["edges"]:
        assert set(edge["faces"]) <= ids
    owned = [face for feature in EXPECTED["features"] for face in feature["faces"]]
    assert set(owned) == ids and len(owned) == len(ids)


@pytest.mark.parametrize("name", VARIANTS)
def test_faceted_volume_formula(rendered, name):
    variant = VARIANTS[name]
    ns = variant["tessellation"]["segments"]
    for key, r in [("corner", 5), ("notch", 4), ("slot", 3), ("hole", 2.5)]:
        assert ns[key] == (
            variant["tessellation"]["fn"] or math.ceil(max(min(30, math.pi * r), 5))
        )
    area = lambda r, n: n * r * r * math.sin(2 * math.pi / n) / 2
    # Hull translates a regular polygon over 10mm. At default N10 its actual
    # Y span is 6*sin(72deg), although its circumradius is exactly 3mm.
    span = 6 * max(math.sin(2 * math.pi * j / ns["slot"]) for j in range(ns["slot"]))
    exact = 3 * (
        2400
        - 100
        + area(5, ns["corner"])
        - area(4, ns["notch"]) / 2
        - 2 * (area(3, ns["slot"]) + 10 * span)
        - area(2.5, ns["hole"])
    )
    assert variant["volume_mm3"] == pytest.approx(exact, abs=1e-9)
    volume = rendered[name].get_mass_properties()[0]
    assert abs(volume - exact) / exact < EXPECTED["tolerances"]["volume_rel"]


@pytest.mark.parametrize("name", VARIANTS)
def test_expected_planes_have_mesh_support(rendered, name):
    mesh = rendered[name]
    normals = mesh.normals / np.linalg.norm(mesh.normals, axis=1, keepdims=True)
    centers = mesh.vectors.mean(axis=1)
    area = np.linalg.norm(np.cross(mesh.v1 - mesh.v0, mesh.v2 - mesh.v0), axis=1) / 2
    for face in transformed_faces(VARIANTS[name]):
        if face["kind"] == "plane":
            support = (normals @ face["normal"] > math.cos(math.radians(1))) & (
                abs((centers - face["point"]) @ face["normal"]) < 1e-3
            )
            assert area[support].sum() > 1, face["id"]


@pytest.mark.parametrize("name", VARIANTS)
def test_recovers_faces_and_edges(rendered, name):
    from stl2scad.core.segmentation import segment_mesh

    result = segment_mesh(rendered[name])
    assert len(result.faces) == len(EXPECTED["faces"])
    matched = {}
    # Greedy one-to-one matching with section-centroid tie breaking for the
    # two disconnected but coplanar north-side regions.
    for expected in transformed_faces(VARIANTS[name]):
        candidates = [
            f
            for f in result.faces
            if f.kind == expected["kind"]
            and f.id not in {v.id for v in matched.values()}
        ]
        candidates.sort(
            key=lambda f: np.linalg.norm(np.asarray(f.params.point) - expected["point"])
        )
        face = min(candidates, key=lambda f: round(f.distance_to(expected), 4))
        assert face.matches(expected, EXPECTED["tolerances"]), expected["id"]
        matched[expected["id"]] = face
    for edge in VARIANTS[name].get("edges", EXPECTED["edges"]):
        assert (
            result.edge_convexity(*(matched[i] for i in edge["faces"]))
            == edge["convexity"]
        ), edge


@pytest.mark.parametrize("name", VARIANTS)
def test_features_and_hausdorff(rendered, name):
    from stl2scad.core.segmentation import (
        segment_mesh,
        detect_features,
        hausdorff_to_mesh,
    )

    features = detect_features(segment_mesh(rendered[name]))
    assert len(features) == 4
    by_id = {f.id: f for f in features}
    assert len(by_id) == len(features) and set(by_id) == {
        f["id"] for f in EXPECTED["features"]
    }
    assert len({i for f in features for i in f.face_ids}) == 21
    assert sum(len(f.face_ids) for f in features) == 21
    for expected in EXPECTED["features"]:
        feature = by_id[expected["id"]]
        assert (
            feature.kind == expected["kind"]
            and feature.polarity == expected["polarity"]
        )
        for dim in ["radius", "height", "width", "length", "depth"]:
            if dim in expected:
                assert getattr(feature, dim) == pytest.approx(expected[dim], abs=0.01)
        if "position" in expected:
            frame = np.asarray(feature.part_frame)
            variant = VARIANTS[name]
            rotation = _rotation(variant["rotate_deg"])
            world = frame[:3, :3] @ feature.position + frame[:3, 3]
            local = world @ rotation - variant["translate_before"]
            np.testing.assert_allclose(local[:2], expected["position"][:2], atol=0.01)
            assert min(abs(local[2]), abs(local[2] - 3)) < 0.01
            axis = (frame[:3, :3] @ feature.axis) @ rotation
            assert abs(axis[2]) > np.cos(
                np.radians(EXPECTED["tolerances"]["cylinder_axis_deg"])
            )
            end = local + axis * feature.depth
            np.testing.assert_allclose(end[:2], expected["position"][:2], atol=0.01)
            assert abs(end[2] - (3 - local[2])) < 0.01
            if "angle_deg" in expected:
                angle = np.radians(feature.angle_deg)
                direction = (
                    frame[:3, :3] @ [np.cos(angle), np.sin(angle), 0]
                ) @ rotation
                target = np.radians(expected["angle_deg"])
                assert abs(direction @ [np.cos(target), np.sin(target), 0]) > np.cos(
                    np.radians(1)
                )
    body = by_id["body_1"]
    assert dict(body.profile.dimensions)["plate_length"] == pytest.approx(60, abs=0.01)
    assert dict(body.profile.dimensions)["plate_width"] == pytest.approx(40, abs=0.01)
    arcs = [s for s in body.profile.segments if s.kind == "arc"]
    assert len(arcs) == 5
    assert sorted(s.convexity for s in arcs) == ["concave"] + ["convex"] * 4
    assert sorted(round(s.radius) for s in arcs) == [4, 5, 5, 5, 5]
    assert hausdorff_to_mesh(features, rendered[name]) < EXPECTED["hausdorff_max_mm"]


@pytest.mark.parametrize("name", VARIANTS)
def test_emitted_scad_and_local_slot_edit(rendered, name, openscad_path, tmp_path):
    from stl2scad.core.segmentation import emit_scad, gate_limit_mm
    from stl2scad.core.segmentation.solid import mesh_hausdorff

    variant = VARIANTS[name]
    source = emit_scad(None, rendered[name])
    assert "polyhedron(" not in source, source[:600]

    def render(text, stem):
        path, target = tmp_path / f"{stem}.scad", tmp_path / f"{stem}.stl"
        path.write_text(text)
        assert run_openscad(
            stem,
            ["--render", "-o", str(target), str(path)],
            str(tmp_path / f"{stem}.log"),
            openscad_path,
        )
        return Mesh.from_file(str(target))

    original = render(source, "emitted")
    params_path = tmp_path / "params.json"
    assert run_openscad(
        "params",
        [
            "--export-format=param",
            "-o",
            str(params_path),
            str(tmp_path / "emitted.scad"),
        ],
        str(tmp_path / "params.log"),
        openscad_path,
    )
    params = {p["name"]: p for p in json.loads(params_path.read_text())["parameters"]}
    for parameter in [
        "plate_length",
        "plate_width",
        "plate_thickness",
        "corner_1_radius",
        "slot_1_width",
        "slot_1_length",
        "slot_1_angle",
        "slot_2_angle",
        "hole_1_diameter",
    ]:
        assert {"min", "step", "max", "caption"} <= params[parameter].keys(), parameter
    assert abs(params["slot_2_angle"]["initial"]) == pytest.approx(30, abs=0.01)
    assert (
        "/* [Resolution] */" in source and "assert(" in source and "// face F" in source
    )
    assert mesh_hausdorff(original, rendered[name]) < gate_limit_mm(rendered[name])
    edited = render(
        re.sub(r"^(slot_1_length\s*=\s*)[-\d.]+;", r"\g<1>20;", source, flags=re.M),
        "edited",
    )
    a, b = original.vectors.reshape(-1, 3), edited.vectors.reshape(-1, 3)
    # Compare surfaces: a different triangulation of the cap is not an edit.
    from stl2scad.core.segmentation.solid import _closest_points

    changed = np.concatenate(
        [
            p[np.linalg.norm(p - _closest_points(p, t), axis=1) > 0.01]
            for p, t in [(a, edited.vectors), (b, original.vectors)]
        ]
    )
    assert len(changed)
    local = changed @ _rotation(variant["rotate_deg"]) - variant["translate_before"]
    assert ((abs(local[:, 0] - 18) < 10.1) & (abs(local[:, 1] - 14) < 3.1)).all(), local


def test_invalid_through_cut_edits_are_stopped(rendered, openscad_path, tmp_path):
    from stl2scad.core.segmentation import emit_scad

    source = emit_scad(None, rendered["axis_aligned"])
    slot_1 = {
        dim: float(re.search(rf"^slot_1_{dim}\s*=\s*([-\d.]+);", source, re.M)[1])
        for dim in ("x", "y", "angle")
    }
    for stem, updates, message in [
        ("outside", {"slot_1_x": 0}, "slot_1 must stay inside the outline"),
        (
            "overlap",
            {f"slot_2_{dim}": value for dim, value in slot_1.items()},
            "slot_2 must not overlap slot_1",
        ),
    ]:
        edited = source
        for name, value in updates.items():
            edited = re.sub(
                rf"^({name}\s*=\s*)[-\d.]+;", rf"\g<1>{value};", edited, flags=re.M
            )
        scad, target, log = (
            tmp_path / f"{stem}.scad",
            tmp_path / f"{stem}.stl",
            tmp_path / f"{stem}.log",
        )
        scad.write_text(edited)
        run_openscad(
            stem, ["--render", "-o", str(target), str(scad)], str(log), openscad_path
        )
        assert not target.exists()
        assert message in log.read_text()
