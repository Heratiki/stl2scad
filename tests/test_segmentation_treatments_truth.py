"""Independent faceted geometry for plan 1, task 1; no detector imports.

Let A(r,n)=n*r*r*sin(2*pi/n)/2 be a regular polygon's area.
All circular fixtures use n divisible by four, with a vertex at angle zero.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from stl.mesh import Mesh

from stl2scad.core.openscad.runner import run_openscad
from tests.test_segmentation_bracket import _rotation, openscad_path

DATA = Path(__file__).parent / "data" / "segmentation"
EXPECTED = json.loads((DATA / "treatments_expected.json").read_text())
PARTS = {p["name"]: p for p in EXPECTED["parts"]}
CASES = [(p["name"], v["name"]) for p in PARTS.values() for v in p["variants"]]
MULTI_VARIANT_PARTS = {
    "chamfered_block",
    "edge_round_block",
    "clipped_arc_plate",
    "stepped_bar",
}
SINGLE_VARIANT_PARTS = {"dome_plate", "dome_plate_large", "asymmetric_chamfer_block"}
EDIT = {
    "chamfered_block": ("chamfer_1_width", 3),
    "edge_round_block": ("edge_round_1_radius", 4),
    "clipped_arc_plate": ("chamfer_1_width", 2.5),
    "stepped_bar": ("step_1_height", 3),
    "dome_plate": ("dome_1_c", 4),
    "dome_plate_large": ("dome_1_c", 11),
    "asymmetric_chamfer_block": ("front_setback", 3),
}


def polygon_area(radius, n):
    return n * radius**2 * math.sin(2 * math.pi / n) / 2


def clipped_corner_moment(radius, n, width):
    """Integral (width-y)*s(y) dy over a faceted front quarter circle.

    Quarter vertices are (s_j,y_j)=(r*sin(a_j),r*(1-cos(a_j))).
    On a chord, s(y_j+t)=s_j+m*t. Its integral to t=b-y_j is
    s_j*((w-y_j)*t-t²/2)+m*((w-y_j)*t²/2-t³/3).
    This finite sum is closed form, including the last clipped chord.
    """
    total = 0.0
    for j in range(n // 4):
        a, b = 2 * math.pi * j / n, 2 * math.pi * (j + 1) / n
        y0, y1 = radius * (1 - math.cos(a)), radius * (1 - math.cos(b))
        if y0 >= width:
            break
        s0, s1 = radius * math.sin(a), radius * math.sin(b)
        t = min(y1, width) - y0
        slope = (s1 - s0) / (y1 - y0)
        total += s0 * ((width - y0) * t - t * t / 2) + slope * (
            (width - y0) * t * t / 2 - t**3 / 3
        )
    return total


def faceted_volume(part, variant, overrides=None):
    values = part["design"] | (overrides or {})
    n = variant["tessellation"]["fn"]
    length, width = values["body_length"], values["body_width"]
    name = part["name"]
    if name == "chamfered_block":
        # Two triangular prisms: L*W*H-L*(w1²+w2²)/2.
        return length * (
            width * values["body_height"]
            - (values["chamfer_1_width"] ** 2 + values["chamfer_2_width"] ** 2) / 2
        )
    if name == "edge_round_block":
        # Round removes a square minus a faceted quarter disk; the back
        # chamfer removes an independent triangular prism.
        r, w = values["edge_round_1_radius"], values["chamfer_1_width"]
        return length * (
            width * values["body_height"] - r * r + polygon_area(r, n) / 4 - w * w / 2
        )
    if name == "clipped_arc_plate":
        # Rounded rectangle: L*W-4r²+A(r,n). The chamfer removes
        # (L-2r)*w²/2 + 2*integral_0^w (w-y)*s(y)dy, not L*w²/2:
        # its two ends are clipped by the front corner polygons.
        radii = [values[f"corner_{i}_radius"] for i in range(1, 5)]
        assert len(set(radii)) == 1, "This closed form uses equal corner radii"
        r, w = radii[0], values["chamfer_1_width"]
        return (
            values["body_height"] * (length * width - 4 * r * r + polygon_area(r, n))
            - (length - 2 * r) * w * w / 2
            - 2 * clipped_corner_moment(r, n, w)
        )
    if name == "stepped_bar":
        # Lower slab is the full bar. Above it: head area W²-2r²+A(r,n)/2
        # plus stadium area (end-start-2q)*2q+A(q,n), with a 4 mm gap.
        # At the design values: V=360+8*(34+A(1,n)/2+15+A(0.5,n)).
        r, q = values["corner_1_radius"], values["corner_3_radius"]
        head = values["head_length"] * width - 2 * r * r + polygon_area(r, n) / 2
        rib = (values["rib_end"] - values["rib_start"] - 2 * q) * 2 * q + polygon_area(
            q, n
        )
        return length * width * values["step_1_height"] + (
            values["step_2_height"] - values["step_1_height"]
        ) * (head + rib)
    if name == "asymmetric_chamfer_block":
        # Triangular prism with unequal legs: L*W*H-L*top*front/2.
        return length * (
            width * values["body_height"]
            - values["top_setback"] * values["front_setback"] / 2
        )
    assert name in {"dome_plate", "dome_plate_large"}
    return None


def variant_for(part, name):
    return next(v for v in part["variants"] if v["name"] == name)


@pytest.fixture(scope="module")
def rendered(openscad_path, tmp_path_factory):
    directory = tmp_path_factory.mktemp("treatments_truth")
    meshes = {}
    for name, variant_name in CASES:
        variant = variant_for(PARTS[name], variant_name)
        target = directory / f"{name}_{variant_name}.stl"
        assert run_openscad(
            name,
            ["--render", "-o", str(target), str(DATA / variant["scad"])],
            str(target.with_suffix(".log")),
            openscad_path,
        )
        meshes[name, variant_name] = Mesh.from_file(str(target))
    return meshes


@pytest.mark.parametrize("name,variant_name", CASES)
def test_ground_truth_references_are_consistent(name, variant_name):
    assert set(PARTS) == MULTI_VARIANT_PARTS | SINGLE_VARIANT_PARTS
    part = PARTS[name]
    expected_variants = (
        {"axis_aligned", "rotated", "fn16_rotated"}
        if name in MULTI_VARIANT_PARTS
        else {"axis_aligned"}
    )
    assert {v["name"] for v in part["variants"]} == expected_variants
    assert len(part["variants"]) == len(expected_variants)
    assert part["tolerances"] == {
        "plane_normal_deg": 1.0,
        "plane_offset_mm": 0.05,
        "cylinder_axis_deg": 1.0,
        "cylinder_radius_rel": 0.02,
        "volume_rel": 0.001,
    }
    ids = [f["id"] for f in part["faces"]]
    assert ids and len(ids) == len(set(ids))
    for face in part["faces"]:
        assert len(face["point"]) == 3
        key = "normal" if face["kind"] == "plane" else "axis"
        assert np.linalg.norm(face[key]) == pytest.approx(1, abs=1e-12)
        if face["kind"] == "cylinder":
            assert face["radius"] > 0 and face["convexity"] in {"convex", "concave"}
    pairs = [tuple(sorted(e["faces"])) for e in part["edges"]]
    assert len(pairs) == len(set(pairs))
    for edge in part["edges"]:
        assert len(set(edge["faces"])) == 2 and set(edge["faces"]) <= set(ids)
        assert edge["convexity"] in {"convex", "concave", "tangent"}
    owned = [i for f in part["features"] for i in f["faces"]]
    assert len(owned) == len(set(owned)) and set(owned) == set(ids)
    features = [f["id"] for f in part["features"]]
    assert len(features) == len(set(features))
    for feature in part["features"]:
        assert set(feature.get("hosts", [])) <= set(ids)
        assert set(feature.get("support_faces", [])) <= set(ids)
    variant = variant_for(part, variant_name)
    assert (DATA / variant["scad"]).exists()
    assert variant["tessellation"]["fn"] == (
        16 if variant_name == "fn16_rotated" else 64
    )
    assert variant["rotate_deg"] == (
        [0, 0, 0] if variant_name == "axis_aligned" else [17, 31, 9]
    )
    for parameter, value in part["parameters"].items():
        assert part["design"][parameter] == value


@pytest.mark.parametrize("name,variant_name", CASES)
def test_faceted_volume_formula(rendered, name, variant_name):
    part = PARTS[name]
    variant = variant_for(part, variant_name)
    exact = faceted_volume(part, variant)
    volume = rendered[name, variant_name].get_mass_properties()[0]
    if exact is None:
        assert variant["volume_mm3"] is None
        assert (
            volume
            > part["design"]["body_length"]
            * part["design"]["body_width"]
            * part["design"]["body_height"]
        )
    else:
        assert variant["volume_mm3"] == pytest.approx(exact, rel=0, abs=1e-9)
        assert abs(volume - exact) / exact < part["tolerances"]["volume_rel"]


@pytest.mark.parametrize("name,variant_name", CASES)
def test_design_variables_can_be_overridden(
    rendered, openscad_path, tmp_path, name, variant_name
):
    """An override must reach the module, including through a use<> wrapper."""
    part = PARTS[name]
    variant = variant_for(part, variant_name)
    parameter, value = EDIT[name]
    target = tmp_path / "edited.stl"
    assert run_openscad(
        name,
        [
            "--render",
            "-D",
            f"{parameter}={value}",
            "-o",
            str(target),
            str(DATA / variant["scad"]),
        ],
        str(target.with_suffix(".log")),
        openscad_path,
    )
    volume = Mesh.from_file(str(target)).get_mass_properties()[0]
    original = rendered[name, variant_name].get_mass_properties()[0]
    exact = faceted_volume(part, variant, {parameter: value})
    if exact is None:
        # Scaling just the dome height scales its volume above the unchanged plate.
        plate = (
            part["design"]["body_length"]
            * part["design"]["body_width"]
            * part["design"]["body_height"]
        )
        exact = plate + (original - plate) * value / part["design"][parameter]
    assert abs(volume - exact) / exact < part["tolerances"]["volume_rel"]
    assert abs(volume - original) / original > part["tolerances"]["volume_rel"]


@pytest.mark.parametrize("name,variant_name", CASES)
def test_expected_planes_have_mesh_support(rendered, name, variant_name):
    part = PARTS[name]
    variant = variant_for(part, variant_name)
    mesh = rendered[name, variant_name]
    rotation, shift = _rotation(variant["rotate_deg"]), np.asarray(
        variant["translate_before"]
    )
    triangles = mesh.vectors.astype(float) @ rotation - shift
    centers = triangles.mean(axis=1)
    cross = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )
    areas = np.linalg.norm(cross, axis=1) / 2
    normals = cross / (2 * areas[:, None])
    cos_tol = math.cos(math.radians(part["tolerances"]["plane_normal_deg"]))
    for face in part["faces"]:
        if face["kind"] != "plane":
            continue
        normal = np.asarray(face["normal"])
        support = (normals @ normal > cos_tol) & (
            abs((centers - face["point"]) @ normal) < 1e-3
        )
        if "bounds" in face:
            low, high = np.asarray(face["bounds"])
            support &= ((centers >= low - 1e-4) & (centers <= high + 1e-4)).all(axis=1)
        # The two head-corner ledges on the stepped bar are only ~0.22 mm²;
        # their explicit small bounds distinguish them from the larger base top.
        assert areas[support].sum() > face.get("support_area_min_mm2", 1.0), (
            name,
            variant_name,
            face["id"],
        )


@pytest.mark.parametrize("variant_name", ["axis_aligned", "rotated", "fn16_rotated"])
def test_stepped_bar_rib_is_free_at_both_ends(rendered, variant_name):
    part = PARTS["stepped_bar"]
    assert part["design"]["rib_start"] == 4
    assert part["design"]["rib_end"] == 20
    assert "singular_contacts" not in part
    faces = {f["id"]: f for f in part["faces"]}
    assert faces["corner_4"]["point"] == [19.5, 3, 0]
    assert faces["rib_top"]["bounds"][1][0] == 20
    upper_slab = next(f for f in part["features"] if f["id"] == "slab_2")
    assert upper_slab["dimensions"]["rib_end"] == 20
    variant = variant_for(part, variant_name)
    vertices = rendered["stepped_bar", variant_name].vectors.astype(float)
    vertices = vertices @ _rotation(variant["rotate_deg"]) - variant["translate_before"]
    # Above the base, the two disjoint upper profiles have a 4 mm air gap.
    vertices = vertices.reshape(-1, 3)
    upper = vertices[vertices[:, 2] > part["design"]["step_1_height"] + 1e-3]
    head_start = part["design"]["body_length"] - part["design"]["head_length"]
    rib = upper[upper[:, 0] < head_start - 1e-3]
    head = upper[upper[:, 0] >= head_start - 1e-3]
    assert rib[:, 0].min() == pytest.approx(4, abs=1e-4)
    assert rib[:, 0].max() == pytest.approx(20, abs=1e-4)
    assert head[:, 0].min() - rib[:, 0].max() == pytest.approx(4, abs=1e-4)
