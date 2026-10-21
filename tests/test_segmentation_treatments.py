"""Rendered contracts for editable slabs, treatments and fixed hybrid regions."""

import json
import re

import pytest
from stl.mesh import Mesh

from stl2scad.core.openscad.runner import run_openscad
from tests.render_cache import cached_render
from stl2scad.core.segmentation.emit import emit_scad, render_scad, gate_limit_mm
from stl2scad.core.segmentation.solid import mesh_hausdorff, hausdorff_to_mesh
from stl2scad.core.segmentation.features import detect_features
from stl2scad.core.segmentation import segment_mesh
from tests.test_segmentation_bracket import openscad_path, rendered as bracket_meshes
from tests.test_segmentation_treatments_truth import (
    PARTS,
    CASES,
    DATA,
    variant_for,
    rendered as treatment_meshes,
)

SUPPORTED = [
    (n, v)
    for n, v in CASES
    if n in {"chamfered_block", "edge_round_block", "clipped_arc_plate", "stepped_bar"}
]


@pytest.fixture(scope="module")
def emitted(treatment_meshes):
    class Sources(dict):
        def __missing__(self, key):
            self[key] = source = emit_scad(None, treatment_meshes[key])
            return source

    return Sources()


@pytest.mark.parametrize("name,variant", SUPPORTED)
def test_emitted_treatment_parts_pass_gate(emitted, treatment_meshes, name, variant):
    source = emitted[name, variant]
    assert "polyhedron(" not in source, source[:1500]
    mesh = treatment_meshes[name, variant]
    assert mesh_hausdorff(render_scad(source), mesh) < gate_limit_mm(mesh)
    # The independent measured-solid backend must consume these features too.
    assert hausdorff_to_mesh(detect_features(segment_mesh(mesh)), mesh) < gate_limit_mm(
        mesh
    )


@pytest.mark.parametrize("name,variant", SUPPORTED)
def test_customizer_parameters(emitted, openscad_path, tmp_path, name, variant):
    scad, target = tmp_path / "model.scad", tmp_path / "params.json"
    scad.write_text(emitted[name, variant])
    assert run_openscad(
        name,
        ["--export-format=param", "-o", str(target), str(scad)],
        str(tmp_path / "params.log"),
        openscad_path,
    )
    params = {p["name"]: p for p in json.loads(target.read_text())["parameters"]}
    for parameter, value in PARTS[name]["parameters"].items():
        assert {"min", "step", "max", "caption"} <= params[parameter].keys()
        assert params[parameter]["caption"]
        assert params[parameter]["initial"] == pytest.approx(value, abs=0.001)


@pytest.mark.parametrize("name,variant", SUPPORTED)
def test_slider_edit_matches_ground_truth(
    emitted, treatment_meshes, openscad_path, tmp_path, name, variant
):
    parameter, value = {
        "chamfered_block": ("chamfer_1_width", 3),
        "edge_round_block": ("edge_round_1_radius", 4),
        "clipped_arc_plate": ("chamfer_1_width", 3),
        "stepped_bar": ("step_1_height", 3),
    }[name]
    source, count = re.subn(
        rf"(?m)^{parameter} = [^;]+;", f"{parameter} = {value};", emitted[name, variant]
    )
    assert count == 1
    target = tmp_path / "truth.stl"
    assert cached_render(
        name,
        ["--render", "-D", f"{parameter}={value}"],
        DATA / variant_for(PARTS[name], variant)["scad"],
        target,
        str(tmp_path / "truth.log"),
        openscad_path,
    )
    assert mesh_hausdorff(
        render_scad(source), Mesh.from_file(str(target))
    ) < gate_limit_mm(treatment_meshes[name, variant])


@pytest.mark.parametrize(
    "name,parameter,value",
    [
        ("edge_round_block", "edge_round_1_radius", 25),
        ("chamfered_block", "chamfer_1_width", 9),
    ],
)
def test_treatment_limits_stop_render(emitted, name, parameter, value):
    source, count = re.subn(
        rf"(?m)^{parameter} = [^;]+;",
        f"{parameter} = {value};",
        emitted[name, "axis_aligned"],
    )
    assert count == 1
    with pytest.raises(RuntimeError, match="[Aa]ssert"):
        render_scad(source)


@pytest.mark.parametrize("name,variant", SUPPORTED)
def test_supported_treatments_never_become_remainder(emitted, name, variant):
    source = emitted[name, variant]
    assert "Full mesh fallback:" not in source
    assert "Free-form region" not in source


def test_dome_plate_is_hybrid(emitted, treatment_meshes):
    source = emitted["dome_plate", "axis_aligned"]
    assert "Full mesh fallback:" not in source
    assert source.count("polyhedron(") == 1
    assert source.index("union()") < source.index("polyhedron(")
    assert re.search(
        r"// Free-form region remainder_1: faces F.*area .* mm2, reason ", source
    )
    share = float(re.search(r"// Free-form share: (\S+) % \(limit 10 %\)", source)[1])
    assert 0 < share < 10
    assert re.search(r"(?m)^plate_thickness = ", source)
    mesh = treatment_meshes["dome_plate", "axis_aligned"]
    assert mesh_hausdorff(render_scad(source), mesh) < gate_limit_mm(mesh)


def test_large_dome_falls_back(emitted):
    source = emitted["dome_plate_large", "axis_aligned"]
    assert "Full mesh fallback: free-form share " in source
    assert "exceeds 10 %" in source
    assert source.count("polyhedron(") == 1
    assert "linear_extrude(" not in source


def test_asymmetric_chamfer_is_reported(emitted, treatment_meshes):
    source = emitted["asymmetric_chamfer_block", "axis_aligned"]
    assert "Full mesh fallback:" not in source
    assert "chamfer_1_width" not in source
    assert "Free-form region" in source and "reason asymmetric chamfer" in source
    mesh = treatment_meshes["asymmetric_chamfer_block", "axis_aligned"]
    assert mesh_hausdorff(render_scad(source), mesh) < gate_limit_mm(mesh)


@pytest.mark.parametrize("variant", ["axis_aligned", "rotated", "fn16_rotated"])
def test_composed_secondary_features_render(bracket_meshes, variant):
    from stl2scad.core.segmentation.compose import compose_features

    mesh = bracket_meshes[variant]
    features = compose_features(segment_mesh(mesh))
    source = emit_scad(features, mesh)
    assert "Full mesh fallback:" not in source
    assert mesh_hausdorff(render_scad(source), mesh) < gate_limit_mm(mesh)
    assert hausdorff_to_mesh(features, mesh) < gate_limit_mm(mesh)


def test_inner_stadium_remains_editable(openscad_path, tmp_path):
    from stl2scad.core.segmentation.to_ir import features_to_ir
    from stl2scad.core.segmentation.emit import ir_to_scad

    fixture = DATA.parent / "feature_fixtures_scad" / "plate_counterbore_and_slot.scad"
    target = tmp_path / "counterbore.stl"
    assert cached_render(
        "counterbore",
        ["--render"],
        fixture,
        target,
        str(tmp_path / "truth.log"),
        openscad_path,
    )
    mesh = Mesh.from_file(str(target))
    model = features_to_ir(detect_features(segment_mesh(mesh)))
    source = ir_to_scad(model)
    assert source.count("/* [Slot 1] */") == 1
    assert source.count("/* [Through Hole 1] */") == 1
    assert source.count("/* [Blind Hole 1] */") == 1
    assert re.search(r"(?m)^slot_1_width = ", source)
    assert re.search(r"(?m)^slot_1_length = ", source)
    assert mesh_hausdorff(render_scad(source), mesh) < gate_limit_mm(mesh)


@pytest.mark.parametrize(
    "name", ["chamfered_block", "edge_round_block", "clipped_arc_plate"]
)
def test_treatments_follow_host_length(
    emitted, treatment_meshes, openscad_path, tmp_path, name
):
    value = PARTS[name]["design"]["body_length"] + 10
    source, count = re.subn(
        r"(?m)^plate_length = [^;]+;",
        f"plate_length = {value};",
        emitted[name, "axis_aligned"],
    )
    assert count == 1
    target = tmp_path / "longer.stl"
    assert cached_render(
        name,
        ["--render", "-D", f"body_length={value}"],
        DATA / variant_for(PARTS[name], "axis_aligned")["scad"],
        target,
        str(tmp_path / "longer.log"),
        openscad_path,
    )
    truth = Mesh.from_file(str(target))
    # Length edits grow from the recovered part-frame origin. A -X frame
    # anchors the original right end; the independent fixture grows along +X.
    features = detect_features(segment_mesh(treatment_meshes[name, "axis_aligned"]))
    x_direction = features[0].part_frame[0][0]
    assert abs(x_direction) == pytest.approx(1, abs=1e-7)
    if x_direction < 0:
        truth.vectors[:, :, 0] -= value - PARTS[name]["design"]["body_length"]
    assert mesh_hausdorff(render_scad(source), truth) < gate_limit_mm(
        treatment_meshes[name, "axis_aligned"]
    )
