"""Composition truth and byte-exact regression fence captured from the parent."""

from collections import Counter
from dataclasses import replace
import hashlib
from pathlib import Path

import numpy as np
import pytest
import trimesh

from stl.mesh import Mesh

from tests.render_cache import cached_render
from stl2scad.core.segmentation import segment_mesh
from stl2scad.core.segmentation.compose import compose_features
from stl2scad.core.segmentation.features import detect_features
from stl2scad.core.segmentation.emit import emit_scad
from stl2scad.core.segmentation.remainder import (
    FREE_FORM_LIMIT,
    free_form_share,
    remainder_regions,
)
from tests.test_segmentation_bracket import (
    openscad_path,
    _rotation,
    rendered as bracket_meshes,
    VARIANTS as BRACKET_VARIANTS,
)
from tests.test_segmentation_rounded_plate import (
    rendered as rounded_meshes,
)
from tests.test_segmentation_treatments_truth import (
    PARTS,
    CASES,
    rendered as treatment_meshes,
)

# SHA-256 recorded at parent commit 509962966217744f0c733941134428d053d804bd,
# before changing features.py; only the // Source: line is removed.
PARENT_SHA256 = {
    "composite_bracket/axis_aligned": "03ce324c81ea13c90a4416825c5ab946f3dfc531047f4f67f405da10df84570f",
    "composite_bracket/rotated": "e7b451b48e15c755baa810e277e8b7139517932390f5d21ce5bb0780667a689c",
    "composite_bracket/fn16_rotated": "dd4a624e772f372cff3ac5b1216afcfc2dd328181e0f6b4c9a06da14d92381d8",
    "composite_bracket/default_res": "31bf8fb1fa2de5a8821c9880a5991386dc2dda0c3400b93e6f9dbdc4571d4c01",
    "rounded_plate/axis_aligned": "f749517499581bdb6a65c18cac53e990392b8313a726cf1701b7dfdfabdc1d45",
    "rounded_plate/rotated": "7065d3512d87a225d72f8d25211bec37885e340ae1130cef9e6d8f724beb8a2d",
    "rounded_plate/default_res": "a37e68ce0c77807cad781a759d7d2a9ce459e2be170d5571ee83b81bc5c02e7e",
}


@pytest.fixture(scope="module")
def treatment_results(treatment_meshes):
    class Results(dict):
        def __missing__(self, key):
            result = self[key] = segment_mesh(treatment_meshes[key])
            return result

    return Results()


@pytest.fixture(scope="module")
def composed(treatment_results):
    class Composed(dict):
        def __missing__(self, key):
            features = self[key] = tuple(compose_features(treatment_results[key]))
            return features

    return Composed()


def _closed(feature):
    triangles = np.asarray(feature.remainder_triangles)
    assert triangles.ndim == 3 and triangles.shape[1:] == (3, 3)
    solid = trimesh.Trimesh(
        vertices=triangles.reshape(-1, 3),
        faces=np.arange(triangles.size // 3).reshape(-1, 3),
        process=True,
    )
    assert solid.is_watertight
    assert solid.is_winding_consistent
    assert solid.volume > 0
    return solid


@pytest.mark.parametrize("key", PARENT_SHA256)
def test_old_path_parts_keep_their_output(bracket_meshes, rounded_meshes, key):
    part, name = key.split("/")
    mesh = (bracket_meshes if part == "composite_bracket" else rounded_meshes)[name]
    source = emit_scad(None, mesh)
    assert "Full mesh fallback:" not in source
    text = (
        "\n".join(
            line for line in source.splitlines() if not line.startswith("// Source:")
        )
        + "\n"
    )
    assert hashlib.sha256(text.encode()).hexdigest() == PARENT_SHA256[key]


@pytest.mark.parametrize("name,variant", CASES)
def test_compose_feature_kinds(treatment_results, composed, name, variant):
    result = treatment_results[name, variant]
    if name == "dome_plate_large":
        with pytest.raises(ValueError, match="exceeds 10 %"):
            compose_features(result)
        return
    features = composed[name, variant]
    expected = PARTS[name]["features"]
    assert Counter(f.kind for f in features) == Counter(f["kind"] for f in expected)
    assert {f.id for f in features} == {f["id"] for f in expected}
    by_id = {f.id: f for f in features}
    owned = [fid for feature in features for fid in feature.face_ids]
    assert len(set(owned)) == len(owned)
    assert set(owned) == {f.id for f in result.faces}
    for truth in expected:
        feature = by_id[truth["id"]]
        assert feature.polarity == truth["polarity"]
        assert np.linalg.det(np.asarray(feature.part_frame)[:3, :3]) == pytest.approx(1)
        assert feature.face_ids
        if feature.kind == "slab":
            assert feature.height == pytest.approx(
                truth["dimensions"]["top"] - truth["dimensions"]["bottom"], abs=0.01
            )
            assert feature.position[2] == pytest.approx(
                truth["dimensions"]["bottom"], abs=0.01
            )
            assert len(feature.loops) == truth.get("loops", 1)
            if "profile_kind" in truth:
                assert feature.profile.kind == truth["profile_kind"]
                if truth["profile_kind"] == "rounded_rectangle":
                    arcs = [
                        edge for edge in feature.profile.segments if edge.kind == "arc"
                    ]
                    assert len(arcs) == 4
                    assert all(
                        abs(edge.sweep_deg) == pytest.approx(90, abs=0.001)
                        for edge in arcs
                    )
        for dim in ("radius", "width"):
            if dim in truth["dimensions"]:
                assert getattr(feature, dim) == pytest.approx(
                    truth["dimensions"][dim], rel=0.02
                )
        if feature.kind in ("chamfer", "edge_round"):
            variant_data = next(
                v for v in PARTS[name]["variants"] if v["name"] == variant
            )
            rotation = _rotation(variant_data["rotate_deg"])
            expected_axis = rotation @ truth["edge_direction"]
            matrix = np.asarray(feature.part_frame)
            axis = matrix[:3, :3] @ feature.axis
            point = matrix[:3, :3] @ feature.position + matrix[:3, 3]
            expected_point = rotation @ (
                np.asarray(truth["edge_point"]) + variant_data["translate_before"]
            )
            assert abs(np.dot(axis, expected_axis)) > np.cos(np.radians(1))
            assert (
                np.linalg.norm(np.cross(point - expected_point, expected_axis)) < 0.05
            )
        if feature.kind == "remainder":
            _closed(feature)


def test_dome_is_one_additive_remainder(treatment_meshes, treatment_results, composed):
    mesh = treatment_meshes["dome_plate", "axis_aligned"]
    result = treatment_results["dome_plate", "axis_aligned"]
    features = composed["dome_plate", "axis_aligned"]
    regions = [f for f in features if f.kind == "remainder"]
    assert len(regions) == 1 and regions[0].polarity == "additive"
    assert 0 < free_form_share(result, regions) < FREE_FORM_LIMIT == 0.10
    solid = _closed(regions[0])
    assert solid.volume == pytest.approx(
        mesh.get_mass_properties()[0] - 60 * 40 * 4, rel=0.001
    )
    assert 4 - 0.001 < solid.bounds[0, 2] < 4
    assert all(f.reason for f in regions)
    body = next(f for f in features if f.kind == "slab")
    assert body.position[2] == pytest.approx(0, abs=1e-5)
    assert body.height == pytest.approx(4, abs=1e-5)
    assert Counter(f.kind for f in detect_features(result)) == {
        "slab": 1,
        "remainder": 1,
    }


def test_large_dome_exceeds_limit(treatment_results):
    result = treatment_results["dome_plate_large", "axis_aligned"]
    with pytest.raises(ValueError, match=r"free-form share .* exceeds 10 %"):
        compose_features(result)
    with pytest.raises(ValueError, match=r"free-form share .* exceeds 10 %"):
        detect_features(result)


def test_asymmetric_chamfer_becomes_named_remainder(treatment_results):
    result = treatment_results["asymmetric_chamfer_block", "axis_aligned"]
    features = compose_features(result)
    (region,) = [f for f in features if f.kind == "remainder"]
    assert region.reason == "asymmetric chamfer"
    assert region.polarity == "subtractive"
    assert _closed(region).volume == pytest.approx(60 * 2 * 4 / 2, rel=0.001)
    assert not any(f.kind == "chamfer" for f in features)


def test_free_form_share_uses_source_area_not_closure(treatment_results, composed):
    result = treatment_results["dome_plate", "axis_aligned"]
    features = composed["dome_plate", "axis_aligned"]
    regions = [f for f in features if f.kind == "remainder"]
    ids = {fid for f in regions for fid in f.face_ids}
    sources = {t for f in result.faces if f.id in ids for t in f.triangle_indices}
    exact = (
        result.mesh.areas[np.isin(result.mesh.source_indices, list(sources))].sum()
        / result.mesh.areas.sum()
    )
    assert free_form_share(result, regions + regions) == pytest.approx(exact, abs=1e-12)
    assert remainder_regions(result, {f.id for f in result.faces}, np.eye(4)) == []


@pytest.mark.parametrize("name", BRACKET_VARIANTS)
def test_compose_reuses_secondary_feature_topology(bracket_meshes, name):
    result = segment_mesh(bracket_meshes[name])
    features = compose_features(result)
    assert Counter(f.kind for f in features) == Counter(
        {"slab": 1, "boss": 1, "blind_hole": 1, "fillet": 1}
    )
    by_id = {f.id: f for f in features}
    assert by_id["boss_1"].radius == pytest.approx(6, rel=0.02)
    assert by_id["boss_1"].height == pytest.approx(6, abs=0.01)
    assert by_id["blind_hole_1"].depth == pytest.approx(3, abs=0.01)
    assert by_id["fillet_1"].radius == pytest.approx(3, rel=0.02)


def test_dispatch_returns_composed_treatments(treatment_results):
    result = treatment_results["edge_round_block", "axis_aligned"]
    assert {f.kind for f in detect_features(result)} == {
        "slab",
        "edge_round",
        "chamfer",
    }


def test_treatment_body_keeps_cross_axis_through_hole(openscad_path, tmp_path):
    source, target = tmp_path / "cross_cut.scad", tmp_path / "cross_cut.stl"
    fixture = Path(__file__).parent / "data" / "segmentation" / "chamfered_block.scad"
    source.write_text(
        f"use <{fixture.resolve().as_posix()}>\n$fn=16; difference(){{ chamfered_block(); translate([-1,20,4]) rotate([0,90,0]) cylinder(r=1.5,h=62); }}"
    )
    assert cached_render(
        "cross-axis hole",
        ["--render"],
        source,
        target,
        str(target.with_suffix(".log")),
        openscad_path,
    )
    result = segment_mesh(Mesh.from_file(str(target)))
    features = compose_features(result)
    assert Counter(f.kind for f in features) == Counter(
        {"slab": 1, "chamfer": 2, "through_hole": 1}
    )
    hole = next(f for f in features if f.kind == "through_hole")
    assert hole.radius == pytest.approx(1.5, rel=0.02)
    assert hole.depth == pytest.approx(60, abs=0.01)
    frame = np.asarray(hole.part_frame)
    point = frame[:3, :3] @ hole.position + frame[:3, 3]
    axis = frame[:3, :3] @ hole.axis
    np.testing.assert_allclose(point[1:], [20, 4], atol=0.01)
    assert abs(axis @ [1, 0, 0]) > 0.999999
    owned = [fid for f in features for fid in f.face_ids]
    assert len(owned) == len(set(owned))
    assert set(owned) == {f.id for f in result.faces}


def test_remainder_closure_keeps_float64_under_large_translation(
    treatment_results, composed
):
    result = treatment_results["dome_plate", "axis_aligned"]
    features = composed["dome_plate", "axis_aligned"]
    regions = [f for f in features if f.kind == "remainder"]
    explained = {f.id for f in result.faces} - set(regions[0].face_ids)
    shift = np.array([1_000_000.0, -2_000_000.0, 3_000_000.0])
    faces = [
        replace(
            f, params=replace(f.params, point=tuple(np.asarray(f.params.point) + shift))
        )
        for f in result.faces
    ]
    graph = result.graph.copy()
    for f in faces:
        graph.nodes[f.id]["face"] = f
    moved = replace(
        result,
        faces=faces,
        graph=graph,
        mesh=replace(result.mesh, vertices=result.mesh.vertices + shift),
    )
    frame = np.asarray(regions[0].part_frame).copy()
    frame[:3, 3] += shift
    moved_regions = remainder_regions(moved, explained, frame)
    assert len(moved_regions) == 1
    before, after = (
        np.asarray(regions[0].remainder_triangles),
        np.asarray(moved_regions[0].remainder_triangles) - shift,
    )
    np.testing.assert_allclose(after, before, atol=1e-7, rtol=0)
    assert _closed(moved_regions[0]).volume == pytest.approx(
        _closed(regions[0]).volume, rel=1e-7
    )


def test_dispatch_keeps_multi_height_profile_arcs(treatment_results):
    result = treatment_results["stepped_bar", "axis_aligned"]
    features = detect_features(result)
    assert Counter(f.kind for f in features) == {"slab": 2}
    assert [len(f.loops) for f in features] == [1, 2]
