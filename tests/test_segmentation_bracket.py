"""Composite bracket harness for the segmentation pipeline.

Ground truth: tests/data/segmentation/composite_bracket_expected.json.
Spec: docs/planning/segmentation_composite_bracket.md.

The harness tests check that the hand-written SCAD and the expected JSON agree.
The segmentation tests are the target for CLAUDE.md pipeline steps 1-4 and are
strict xfails until stl2scad.core.segmentation exists.
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest
from stl.mesh import Mesh

from stl2scad.core.converter import get_openscad_path, run_openscad

DATA_DIR = Path(__file__).parent / "data" / "segmentation"
EXPECTED = json.loads((DATA_DIR / "composite_bracket_expected.json").read_text())
VARIANTS = {v["name"]: v for v in EXPECTED["variants"]}


def _rotation(rotate_deg):
    """OpenSCAD rotate([a, b, c]) == Rz(c) @ Ry(b) @ Rx(a)."""
    a, b, c = (math.radians(x) for x in rotate_deg)
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return rz @ ry @ rx


def transformed_faces(variant):
    """Expected faces mapped into the variant's world frame."""
    rot = _rotation(variant["rotate_deg"])
    shift = np.asarray(variant["translate_before"], dtype=float)
    faces = []
    for face in EXPECTED["faces"]:
        out = dict(face)
        out["point"] = (rot @ (np.asarray(face["point"], dtype=float) + shift)).tolist()
        key = "normal" if face["kind"] == "plane" else "axis"
        out[key] = (rot @ np.asarray(face[key], dtype=float)).tolist()
        faces.append(out)
    return faces


@pytest.fixture(scope="module")
def openscad_path():
    try:
        return get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for the segmentation harness: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")


@pytest.fixture(scope="module")
def rendered(openscad_path, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("segmentation_bracket")
    meshes = {}
    for name, variant in VARIANTS.items():
        stl_path = out_dir / f"{name}.stl"
        assert run_openscad(
            f"composite_bracket_{name}",
            ["--render", "-o", str(stl_path), str(DATA_DIR / variant["scad"])],
            str(out_dir / f"{name}.log"),
            openscad_path,
        ), f"OpenSCAD render failed for {variant['scad']}"
        meshes[name] = Mesh.from_file(str(stl_path))
    return meshes


def test_ground_truth_references_are_consistent():
    face_ids = [face["id"] for face in EXPECTED["faces"]]
    assert len(face_ids) == len(set(face_ids)) == 13
    for edge in EXPECTED["edges"]:
        assert set(edge["faces"]) <= set(face_ids), edge
        assert edge["convexity"] in {"convex", "concave", "tangent"}
    for feature in EXPECTED["features"]:
        assert set(feature["faces"]) <= set(face_ids), feature
        assert feature["polarity"] in {"additive", "subtractive"}


@pytest.mark.parametrize("variant_name", list(VARIANTS))
def test_rendered_volume_matches_ground_truth(rendered, variant_name):
    volume, _, _ = rendered[variant_name].get_mass_properties()
    expected = EXPECTED["volume_mm3"]
    assert abs(volume - expected) / expected < EXPECTED["tolerances"]["volume_rel"]


@pytest.mark.parametrize("variant_name", list(VARIANTS))
def test_every_expected_plane_has_mesh_support(rendered, variant_name):
    """Each expected plane, after the variant transform, carries triangles of the mesh."""
    mesh = rendered[variant_name]
    normals = mesh.normals / np.linalg.norm(mesh.normals, axis=1, keepdims=True)
    centroids = mesh.vectors.mean(axis=1)
    areas = 0.5 * np.linalg.norm(np.cross(mesh.v1 - mesh.v0, mesh.v2 - mesh.v0), axis=1)
    cos_tol = math.cos(math.radians(EXPECTED["tolerances"]["plane_normal_deg"]))
    for face in transformed_faces(VARIANTS[variant_name]):
        if face["kind"] != "plane":
            continue
        normal = np.asarray(face["normal"])
        offset = np.abs((centroids - np.asarray(face["point"])) @ normal)
        on_plane = (normals @ normal > cos_tol) & (offset < 1e-3)
        assert areas[on_plane].sum() > 1.0, f"{variant_name}: no mesh support for {face['id']}"


@pytest.mark.xfail(
    raises=ImportError, strict=True,
    reason="segmentation pipeline (CLAUDE.md steps 1-3) not built yet",
)
@pytest.mark.parametrize("variant_name", list(VARIANTS))
def test_segmentation_recovers_faces_and_edges(rendered, variant_name):
    from stl2scad.core.segmentation import segment_mesh

    result = segment_mesh(rendered[variant_name])
    tol = EXPECTED["tolerances"]
    expected_faces = transformed_faces(VARIANTS[variant_name])
    assert len(result.faces) == len(expected_faces)

    matched = {}
    for face in expected_faces:
        candidates = [f for f in result.faces if f.kind == face["kind"]]
        best = min(candidates, key=lambda f: f.distance_to(face), default=None)
        assert best is not None and best.matches(face, tol), f"{variant_name}: {face['id']} not recovered"
        if face["kind"] == "cylinder":
            assert best.convexity == face["convexity"], face["id"]
        matched[face["id"]] = best

    for edge in EXPECTED["edges"]:
        a, b = (matched[i] for i in edge["faces"])
        assert result.edge_convexity(a, b) == edge["convexity"], edge


@pytest.mark.xfail(
    raises=ImportError, strict=True,
    reason="feature detection from the region graph (CLAUDE.md step 4) not built yet",
)
@pytest.mark.parametrize("variant_name", list(VARIANTS))
def test_features_recovered_with_polarity_and_hausdorff(rendered, variant_name):
    from stl2scad.core.segmentation import detect_features, hausdorff_to_mesh, segment_mesh

    mesh = rendered[variant_name]
    features = detect_features(segment_mesh(mesh))
    by_kind = {f.kind: f for f in features}
    for expected in EXPECTED["features"]:
        found = by_kind.get(expected["kind"])
        assert found is not None, f"{variant_name}: {expected['kind']} not detected"
        assert found.polarity == expected["polarity"], expected["id"]
        for key in ("radius", "height", "depth"):
            if key in expected:
                assert abs(getattr(found, key) - expected[key]) / expected[key] < 0.02, (expected["id"], key)
    assert hausdorff_to_mesh(features, mesh) < EXPECTED["hausdorff_max_mm"]


def _part_frame_points(points, variant):
    """Map world points of a variant back into the un-rotated part frame."""
    rot = _rotation(variant["rotate_deg"])
    return points @ rot - np.asarray(variant["translate_before"], dtype=float)


def _far_points(points, reference, threshold):
    """Points farther than threshold from every reference point (brute force, chunked)."""
    far = []
    for start in range(0, len(points), 512):
        chunk = points[start:start + 512]
        dists = np.linalg.norm(chunk[:, None, :] - reference[None, :, :], axis=2).min(axis=1)
        far.append(chunk[dists > threshold])
    return np.concatenate(far) if far else np.empty((0, 3))


@pytest.mark.xfail(
    raises=ImportError, strict=True,
    reason="labeled SCAD emission (pipeline step 5) not built yet",
)
@pytest.mark.parametrize("variant_name", list(VARIANTS))
def test_emitted_scad_is_labeled_and_adjustable(rendered, openscad_path, tmp_path, variant_name):
    import re

    from stl2scad.core.segmentation import (
        detect_features, emit_scad, gate_limit_mm, segment_mesh,
    )

    variant = VARIANTS[variant_name]
    mesh = rendered[variant_name]
    scad = emit_scad(detect_features(segment_mesh(mesh)), mesh)

    assert "polyhedron(" not in scad, "all-or-nothing gate fell back to a polyhedron"
    assert re.search(r"/\*\s*\[[^\]]+\]\s*\*/", scad), "no Customizer group heading"
    for name in ("boss_1_height", "blind_hole_1_depth", "fillet_1_radius"):
        assert re.search(rf"^{name}\s*=\s*[-\d.]+;\s*//\s*\[[-\d.:]+\]", scad, re.M), f"{name} missing or has no range"
    assert "assert(" in scad, "no constraint assert()"
    assert "multmatrix(" in scad or variant["rotate_deg"] == [0, 0, 0]

    def render(source, stem):
        scad_path, stl_path = tmp_path / f"{stem}.scad", tmp_path / f"{stem}.stl"
        scad_path.write_text(source)
        assert run_openscad(stem, ["--render", "-o", str(stl_path), str(scad_path)],
                            str(tmp_path / f"{stem}.log"), openscad_path), f"render failed: {stem}"
        return Mesh.from_file(str(stl_path))

    original = render(scad, "emitted")
    limit = gate_limit_mm(mesh)
    assert limit == pytest.approx(max(0.05, 0.001 * np.linalg.norm(np.ptp(mesh.points.reshape(-1, 3), axis=0))))
    from stl2scad.core.verification.metrics import calculate_hausdorff_distance, sample_mesh_points

    rng = np.random.default_rng(0)
    distance = calculate_hausdorff_distance(
        sample_mesh_points(original, 20000, rng)[0], sample_mesh_points(mesh, 20000, rng)[0]
    )
    assert distance < limit, f"{variant_name}: emitted SCAD is {distance:.4f} mm from the input"

    edited = render(re.sub(r"^(boss_1_height\s*=\s*)[-\d.]+;", r"\g<1>9;", scad, count=1, flags=re.M), "edited")
    a = original.points.reshape(-1, 3)
    b = edited.points.reshape(-1, 3)
    changed = np.concatenate([_far_points(a, b, 0.01), _far_points(b, a, 0.01)])
    assert len(changed), "editing boss_1_height changed nothing"
    local = _part_frame_points(changed, variant)
    radial = np.linalg.norm(local[:, :2] - np.array([25.0, 15.0]), axis=1)
    assert (radial < 6.1).all() and (local[:, 2] > 4.9).all(), "edit changed geometry outside the boss"
