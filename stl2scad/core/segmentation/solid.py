"""Independent feature-solid reconstruction and deterministic surface validation.

This private SCAD is a validation backend, not the step 5 editable/IR emitter.
It consumes measured feature geometry; only fixed remainder regions carry triangles.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from stl.mesh import Mesh

from ..openscad.runner import get_openscad_path, run_openscad
from ..verification.metrics import calculate_hausdorff_distance, sample_mesh_points
from .features import Feature


def _literal(value):
    return json.dumps(np.asarray(value).tolist(), allow_nan=False)


def _cylinder(feature, epsilon):
    direction = np.asarray(feature.axis, dtype=float)
    direction /= np.linalg.norm(direction)
    u = np.cross(direction, np.eye(3)[np.argmin(np.abs(direction))])
    u /= np.linalg.norm(u)
    if feature.radial_reference is not None:
        u = np.asarray(feature.radial_reference, dtype=float)
        u = u - (u @ direction) * direction
        u /= np.linalg.norm(u)
    matrix = np.eye(4)
    matrix[:3, :3] = np.column_stack((u, np.cross(direction, u), direction))
    # Extend the host end only. The cap/floor remains at its measured depth.
    matrix[:3, 3] = np.asarray(feature.position) - direction * epsilon
    length = feature.height if feature.kind in ("boss", "pin") else feature.depth
    if feature.radius is None or feature.radius <= 0 or length is None or length <= 0:
        raise ValueError("Cylinder features need a positive radius and length")
    tail = 0.0
    if feature.kind == "through_hole" and feature.rim_normals:
        pads = [
            feature.radius * np.sqrt(max(0.0, 1 / np.dot(n, direction) ** 2 - 1))
            for n in feature.rim_normals
        ]
        matrix[:3, 3] -= direction * pads[0]
        tail = sum(pads) + epsilon
    return f"multmatrix({_literal(matrix)}) cylinder(r={feature.radius:.17g}, h={length + epsilon + tail:.17g}, $fn={feature.segments or 64});"


def _validation_source(features: list[Feature]) -> str:
    if not features:
        raise ValueError("Cannot reconstruct an empty feature list")
    if len(features) == 1 and features[0].kind == "pin":
        pin = features[0]
        return f"multmatrix({_literal(pin.part_frame)}) " + _cylinder(pin, 0.0)
    if any(f.kind == "slab" for f in features):
        return _composed_validation_source(features)
    bodies = [f for f in features if f.kind.endswith("_profile_extrude")]
    if len(bodies) != 1:
        raise ValueError("Validation currently supports exactly one extruded body")
    body = bodies[0]
    if (
        body.profile is None
        or body.height is None
        or body.height <= 0
        or body.polarity != "additive"
    ):
        raise ValueError(
            "Body requires additive polarity, a section profile and positive extrusion height"
        )
    frame = np.asarray(body.part_frame)
    if (
        frame.shape != (4, 4)
        or not np.isfinite(frame).all()
        or not np.allclose(frame[3], [0, 0, 0, 1])
        or not np.allclose(frame[:3, :3].T @ frame[:3, :3], np.eye(3), atol=1e-7)
        or np.linalg.det(frame[:3, :3]) < 0
    ):
        raise ValueError("Part frame must be a proper rigid transform")
    if any(not np.allclose(f.part_frame, frame, atol=1e-8) for f in features):
        raise ValueError("Features must use one shared part frame")
    scale = max(
        body.height, float(np.ptp(np.asarray(body.profile.points), axis=0).max())
    )
    epsilon = scale * 1e-6
    if body.profile.segments:
        from .sections import profile_points

        cuts = []
        for feature in features:
            if feature is body:
                continue
            if feature.polarity != "subtractive" or feature.kind not in (
                "through_slot",
                "through_hole",
            ):
                raise ValueError("Arc profile supports through cuts only")
            if (
                feature.radius is None
                or feature.radius <= 0
                or feature.depth != body.height
            ):
                raise ValueError("Through cuts must span the body")
            phase = np.degrees(
                np.arctan2(feature.radial_reference[1], feature.radial_reference[0])
            )
            circle = f"rotate({phase:.17g}) circle(r={feature.radius:.17g},$fn={feature.segments});"
            center = np.asarray(feature.position[:2])
            if feature.kind == "through_slot":
                half = (feature.length - feature.width) / 2
                if feature.width <= 0 or half <= 0:
                    raise ValueError("Stadium requires length greater than width")
                direction = np.array(
                    [
                        np.cos(np.radians(feature.angle_deg)),
                        np.sin(np.radians(feature.angle_deg)),
                    ]
                )
                cuts.append(
                    "hull() {"
                    + " ".join(
                        f"translate({_literal(center+sign*half*direction)}) {circle}"
                        for sign in (-1, 1)
                    )
                    + "}"
                )
            else:
                cuts.append(f"translate({_literal(center)}) {circle}")
        return (
            f"multmatrix({_literal(frame)}) linear_extrude(height={body.height:.17g}) difference() {{\n"
            f"polygon(points={_literal(profile_points(body.profile))});\n"
            + "\n".join(cuts)
            + "\n}\n"
        )
    additive = [
        f"linear_extrude(height={body.height:.17g}) polygon(points={_literal(body.profile.points)});"
    ]
    subtractive = []
    for feature in features:
        if feature is body:
            continue
        if feature.kind in ("boss", "blind_hole", "through_hole"):
            expected_polarity = "additive" if feature.kind == "boss" else "subtractive"
            if feature.polarity != expected_polarity:
                raise ValueError("Feature kind and polarity disagree")
            source = _cylinder(feature, epsilon)
            (additive if feature.polarity == "additive" else subtractive).append(source)
        elif feature.kind == "fillet":
            if (
                feature.corner is None
                or feature.radius is None
                or feature.radius <= 0
                or feature.height is None
                or feature.height <= 0
            ):
                raise ValueError("Fillet requires its sharp corner, radius and length")
            if feature.polarity != "additive" or not np.allclose(
                feature.axis, [0, 0, 1]
            ):
                raise ValueError(
                    "Only additive extrusion-spanning fillets are supported"
                )
            center = np.asarray(feature.position, dtype=float)
            corner = np.asarray(feature.corner, dtype=float)
            # Enter the two host half-spaces by a scale-relative epsilon. Raw
            # float32 fits can leave a micrometre gap at an otherwise tangent
            # join; a butt union then retains an entire interior wedge face.
            corner = corner.copy()
            corner[:2] += np.sign(corner[:2] - center[:2]) * epsilon
            # Two orthogonal tangent planes enclose a rectangular wedge. Remove
            # the cylinder's interior to leave the concave round in the corner.
            wedge = [
                corner[:2],
                [center[0], corner[1]],
                center[:2],
                [corner[0], center[1]],
            ]
            phase = (
                float(
                    np.degrees(
                        np.arctan2(
                            feature.radial_reference[1], feature.radial_reference[0]
                        )
                    )
                )
                if feature.radial_reference is not None
                else 0.0
            )
            additive.append(
                f"translate([0,0,{center[2]:.17g}]) linear_extrude(height={feature.height:.17g}) "
                f"difference() {{ polygon(points={_literal(wedge)}); "
                f"translate({_literal(center[:2])}) rotate({phase:.17g}) circle(r={feature.radius:.17g}, $fn={feature.segments or 64}); }}"
            )
        else:
            raise ValueError(f"Unsupported feature solid: {feature.kind}")
    return (
        "$fn=64;\n"
        + f"multmatrix({_literal(frame)}) difference() {{\nunion() {{\n"
        + "\n".join(additive)
        + "\n}\n"
        + "\n".join(subtractive)
        + "\n}\n"
    )


def reconstruct_mesh(features: list[Feature]) -> Mesh:
    """Render only the measured feature solid; failures are never fallback success."""
    source = _validation_source(features)
    openscad = get_openscad_path()
    with TemporaryDirectory(prefix="stl2scad-feature-solid-") as directory:
        root = Path(directory)
        scad, stl, log = root / "solid.scad", root / "solid.stl", root / "render.log"
        scad.write_text(source, encoding="utf-8")
        if not run_openscad(
            "Feature solid validation",
            ["--render", "-o", stl.as_posix(), scad.as_posix()],
            log.as_posix(),
            openscad,
        ):
            raise RuntimeError(
                "Feature solid render failed: "
                + (log.read_text() if log.exists() else "no log")
            )
        if not stl.exists():
            raise RuntimeError("Feature solid render produced no STL")
        return Mesh.from_file(stl.as_posix())


def _closest_points(points, triangles):
    # Trimesh's exact point/triangle primitive requires neither scipy nor rtree.
    # Bound temporary arrays for large meshes instead of allocating N x M x 3.
    from trimesh.triangles import closest_point

    best = np.full(len(points), np.inf)
    nearest = np.empty_like(points, dtype=float)
    for start in range(0, len(triangles), 256):
        target = triangles[start : start + 256]
        with np.errstate(divide="ignore", invalid="ignore"):
            projected = closest_point(
                np.tile(target, (len(points), 1, 1)),
                np.repeat(points, len(target), axis=0),
            ).reshape(len(points), len(target), 3)
        distances = np.sum((projected - points[:, None]) ** 2, axis=2)
        # CSG renders can contain collapsed/near-collinear triangles. Their
        # invalid projections must not mask valid neighbors or leave nearest
        # entries uninitialized.
        distances[~np.isfinite(distances)] = np.inf
        indices = distances.argmin(axis=1)
        current = distances[np.arange(len(points)), indices]
        update = current < best
        nearest[update] = projected[np.arange(len(points)), indices][update]
        best[update] = current[update]
    if not np.isfinite(best).all():
        raise ValueError("No finite closest surface point")
    return nearest


def mesh_hausdorff(first: Mesh, second: Mesh, *, samples=4096) -> float:
    """Sampled-surface Hausdorff in mm, with vertices and edge quarter points.

    Independent random point clouds have a sampling-spacing error much larger
    than 0.05 mm on a bracket. For each sampled point we instead find its exact
    closest point on the other triangle surface. The repository's point-set
    metric on a chunk and these closest points equals the directed surface
    distance for that chunk: every projection has its generating point as a
    witness, and each sample's nearest surface point is present. Max over both
    directions gives a deterministic estimate, not a certified continuous bound.
    """
    if not len(first.vectors) or not len(second.vectors):
        raise ValueError("Hausdorff validation requires two nonempty surfaces")
    rng = np.random.default_rng(0)
    maximum = 0.0
    for source, target in ((first, second), (second, first)):
        triangles = np.asarray(target.vectors, dtype=np.float64)
        sampled, _ = sample_mesh_points(source, samples, rng)
        vertices, indices = np.unique(
            source.vectors.reshape(-1, 3).astype(float), axis=0, return_inverse=True
        )
        ids = indices.reshape(-1, 3)
        edges = np.unique(
            np.sort(
                np.vstack((ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]])), axis=1
            ),
            axis=0,
        )
        endpoints = vertices[edges]
        edge_points = (
            endpoints[:, 0, None, :]
            + np.array([0.25, 0.5, 0.75])[None, :, None]
            * (endpoints[:, 1] - endpoints[:, 0])[:, None, :]
        ).reshape(-1, 3)
        points = np.concatenate(
            (
                sampled,
                vertices,
                edge_points,
                source.vectors.astype(np.float64).mean(axis=1),
            )
        )
        if not np.isfinite(points).all() or not np.isfinite(triangles).all():
            raise ValueError("Hausdorff validation requires finite surfaces")
        for start in range(0, len(points), 64):
            chunk = points[start : start + 64]
            nearest = _closest_points(chunk, triangles)
            maximum = max(maximum, calculate_hausdorff_distance(chunk, nearest))
    return maximum


def hausdorff_to_mesh(features: list[Feature], mesh: Mesh) -> float:
    """Rebuild the measured solid and compare it with the input mesh in mm."""
    return mesh_hausdorff(reconstruct_mesh(features), mesh)


def _composed_validation_source(features):
    """Independent literal reconstruction; no editable IR or SCAD bindings."""
    from .sections import profile_points
    from .compose_ir import treatment_frame

    slabs = [f for f in features if f.kind == "slab"]
    frame = np.asarray(slabs[0].part_frame)
    if (
        frame.shape != (4, 4)
        or not np.isfinite(frame).all()
        or not np.allclose(frame[3], [0, 0, 0, 1])
        or not np.allclose(frame[:3, :3].T @ frame[:3, :3], np.eye(3), atol=1e-7)
        or np.linalg.det(frame[:3, :3]) < 0
        or any(not np.allclose(f.part_frame, frame, atol=1e-8) for f in features)
    ):
        raise ValueError("Features must share a proper rigid part frame")
    points = np.vstack([profile_points(p) for s in slabs for p in s.loops])
    lower = np.r_[points.min(axis=0), min(s.position[2] for s in slabs)]
    upper = np.r_[points.max(axis=0), max(s.position[2] + s.height for s in slabs)]
    epsilon = max(upper - lower) * 1e-6
    additive, cuts = [], []
    for f in features:
        if f.kind == "slab":
            if f.polarity != "additive" or not f.height or f.height <= 0:
                raise ValueError("Slab needs additive polarity and positive height")
            vertices, paths = [], []
            for loop in f.loops:
                ring = profile_points(loop)
                paths.append(list(range(len(vertices), len(vertices) + len(ring))))
                vertices.extend(ring.tolist())
            source = f"translate([0,0,{f.position[2]:.17g}]) linear_extrude(height={f.height:.17g}) polygon(points={_literal(vertices)},paths={json.dumps(paths)});"
        elif f.kind in ("edge_round", "chamfer"):
            matrix, length, phase = treatment_frame(f, lower, upper)
            size = f.radius if f.kind == "edge_round" else f.width
            if size is None or size <= 0 or f.polarity != "subtractive":
                raise ValueError(
                    "Treatment needs positive size and subtractive polarity"
                )
            matrix[:3, 3] -= matrix[:3, 2] * epsilon
            source = f"multmatrix({_literal(matrix)}) linear_extrude(height={length+2*epsilon:.17g}) "
            if f.kind == "chamfer":
                source += f"polygon(points={_literal([[-epsilon,-epsilon],[size+epsilon,-epsilon],[-epsilon,size+epsilon]])});"
            else:
                source += f"difference() {{ translate([-{epsilon:.17g},-{epsilon:.17g}]) square([{size+epsilon:.17g},{size+epsilon:.17g}]); translate([{size:.17g},{size:.17g}]) rotate({phase:.17g}) circle(r={size:.17g},$fn={f.segments}); }}"
        elif f.kind == "remainder":
            local = (np.asarray(f.remainder_triangles) - frame[:3, 3]) @ frame[:3, :3]
            vertices, indices = np.unique(
                local.reshape(-1, 3), axis=0, return_inverse=True
            )
            source = f"polyhedron(points={_literal(vertices)},faces={_literal(indices.reshape(-1,3)[:,::-1])},convexity=10);"
        elif f.kind == "fillet":
            center, corner = np.asarray(f.position), np.asarray(f.corner).copy()
            corner[:2] += np.sign(corner[:2] - center[:2]) * epsilon
            wedge = [
                corner[:2],
                [center[0], corner[1]],
                center[:2],
                [corner[0], center[1]],
            ]
            phase = (
                float(
                    np.degrees(np.arctan2(f.radial_reference[1], f.radial_reference[0]))
                )
                if f.radial_reference is not None
                else 0.0
            )
            source = f"translate([0,0,{center[2]:.17g}]) linear_extrude(height={f.height:.17g}) difference() {{ polygon(points={_literal(wedge)}); translate({_literal(center[:2])}) rotate({phase:.17g}) circle(r={f.radius:.17g},$fn={f.segments or 64}); }}"
        elif f.kind in ("boss", "blind_hole", "through_hole"):
            source = _cylinder(f, epsilon)
        else:
            raise ValueError(f"Unsupported composed validation feature: {f.kind}")
        (additive if f.polarity == "additive" else cuts).append(source)
    return (
        f"multmatrix({_literal(frame)}) difference() {{ union() {{\n"
        + "\n".join(additive)
        + "\n}\n"
        + "\n".join(cuts)
        + "\n}\n"
    )
