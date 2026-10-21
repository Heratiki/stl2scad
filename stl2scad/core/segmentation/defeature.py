"""Remove supported edge treatments while retaining source face provenance."""

from dataclasses import dataclass, replace
from itertools import product
from typing import Literal

import numpy as np

from .models import Cylinder, Plane, SegmentationResult, Vector
from .regularize import extrusion_axis, regularize

__all__ = ["EdgeTreatment", "Defeatured", "defeature"]


@dataclass(frozen=True)
class EdgeTreatment:
    id: str
    kind: Literal["chamfer", "edge_round"]
    face_id: str
    hosts: tuple[str, str]
    size: float
    edge_point: Vector
    edge_direction: Vector
    segments: int | None = None
    radial_reference: Vector | None = None


@dataclass(frozen=True)
class Defeatured:
    result: SegmentationResult
    axis: Vector
    treatments: tuple[EdgeTreatment, ...]
    rejected: tuple[tuple[str, str], ...]


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)


def _side_frame(result, axis, sine, cosine):
    """Anchor cap-plane coordinates to dominant side support, not world axes."""
    sides = [
        f
        for f in result.faces
        if isinstance(f.params, Plane) and abs(np.dot(f.params.normal, axis)) <= sine
    ]
    if not sides:
        return None
    normals = np.array([f.params.normal for f in sides])
    areas = np.array(
        [
            result.mesh.areas[
                np.isin(result.mesh.source_indices, f.triangle_indices)
            ].sum()
            for f in sides
        ]
    )
    support = (np.abs(normals @ normals.T) >= cosine) @ areas
    # Equal support (a parallel pair) falls to the larger face, then the id.
    index = min(
        range(len(sides)),
        key=lambda i: (
            -round(float(support[i]), 6),
            -round(float(areas[i]), 6),
            sides[i].id,
        ),
    )
    u = _unit(normals[index] - np.dot(normals[index], axis) * axis)
    # The sign sets treatment numbering (customer-visible parameter names), so
    # it comes from the part: u points from the mesh centroid to the side face.
    # A rigid rotation of the part then leaves the labels unchanged. Geometry
    # uses unoriented directions, so eligibility does not depend on it.
    mesh = result.mesh
    centers = mesh.vertices[mesh.triangles].mean(axis=1)
    centroid = (mesh.areas @ centers) / mesh.areas.sum()
    twin = any(
        j != index
        and normals[j] @ normals[index] <= -cosine
        and abs(areas[j] - areas[index]) <= 1e-3 * areas[index]
        for j in range(len(sides))
    )
    if twin:
        # A mirror-symmetric pair has no part-intrinsic order: the labels are
        # interchangeable, so keep the previous world-axis sign here.
        if u[np.argmax(abs(u))] < 0:
            u = -u
    elif np.dot(sides[index].params.point - centroid, u) < 0:
        u = -u
    return u, _unit(np.cross(axis, u))


def _oblique(direction, cap, side, cosine):
    host_direction = _unit(np.cross(cap.params.normal, side.params.normal))
    return abs(np.dot(direction, host_direction)) < cosine


def _intersection(cap, side):
    normals = np.array([cap.params.normal, side.params.normal])
    direction = _unit(np.cross(*normals))
    point = np.linalg.lstsq(
        normals, [cap.params.offset, side.params.offset], rcond=None
    )[0]
    return point, direction


def _host_pairs(result, face, axis, sine, cosine, boundary):
    adjacent = [
        f
        for f in result.faces
        if f.id in result.graph[face.id]
        and isinstance(f.params, Plane)
        and result.graph[face.id][f.id]["convexity"] == boundary
    ]
    caps = [f for f in adjacent if abs(np.dot(f.params.normal, axis)) >= cosine]
    sides = [f for f in adjacent if abs(np.dot(f.params.normal, axis)) <= sine]
    if isinstance(face.params, Plane):
        normal = np.asarray(face.params.normal)
        valid_sides = [s for s in sides if np.dot(normal, s.params.normal) > sine]
        if not valid_sides:
            return []
        best_side = max(valid_sides, key=lambda s: np.dot(normal, s.params.normal))
        pairs = []
        for cap in caps:
            hosts = np.array([cap.params.normal, best_side.params.normal])
            coefficients = np.linalg.lstsq(hosts.T, normal, rcond=None)[0]
            if np.any(coefficients <= 0):
                continue
            point, _ = _intersection(cap, best_side)
            direction = _unit(np.cross(normal, cap.params.normal))
            pairs.append((cap, best_side, point, direction))
        return pairs
    pairs = []
    for cap, side in product(caps, sides):
        point, host_dir = _intersection(cap, side)
        if abs(np.dot(host_dir, face.params.axis)) < cosine:
            continue
        pairs.append((cap, side, point, np.asarray(face.params.axis)))
    return pairs


def _chamfer_size(face, cap, side, point):
    normal = np.asarray(face.params.normal)
    nc, ns = np.asarray(cap.params.normal), np.asarray(side.params.normal)
    cap_out = _unit(ns - np.dot(ns, nc) * nc)
    side_out = _unit(nc - np.dot(ns, nc) * ns)
    gap = normal @ point - face.params.offset
    setbacks = [gap / np.dot(normal, outward) for outward in (cap_out, side_out)]
    return float(np.mean(setbacks))


def defeature(result: SegmentationResult) -> Defeatured:
    """Regularize and extract symmetric chamfers and convex 3D edge rounds.

    Profile arcs parallel to the extrusion axis remain ordinary side faces.
    Rejected treatments remain in the result for a later remainder pass. The
    graph is copied, with surviving node snapshots updated to fitted faces;
    the input graph and indexed mesh are never changed.
    """
    fitted = regularize(result)
    axis = extrusion_axis(fitted)
    sine, cosine = np.sin(np.radians(0.5)), np.cos(np.radians(0.5))
    frame = _side_frame(fitted, axis, sine, cosine)
    treatments, rejected = [], []
    for face in fitted.faces:
        params = face.params
        if isinstance(params, Plane):
            dot = abs(np.dot(params.normal, axis))
            if dot <= sine or dot >= cosine:
                continue
            kind, boundary = "chamfer", "convex"
        else:
            if face.convexity != "convex" or abs(np.dot(params.axis, axis)) > sine:
                continue
            kind, boundary = "edge_round", "tangent"
        pairs = _host_pairs(fitted, face, axis, sine, cosine, boundary)
        if len(pairs) != 1:
            continue
        cap, side, point, direction = pairs[0]
        if _oblique(direction, cap, side, cosine):
            rejected.append((face.id, "oblique edge"))
            continue
        if kind == "chamfer":
            bisector = _unit(np.asarray(cap.params.normal) + side.params.normal)
            if np.dot(params.normal, bisector) < cosine:
                rejected.append((face.id, "asymmetric chamfer"))
                continue
            size = _chamfer_size(face, cap, side, point)
            segments, reference = None, None
        else:
            size = params.radius
            segments, reference = params.segments, params.radial_reference
            # Preserve the cylinder's signed axis so its angular phase survives.
            direction = np.asarray(params.axis)
        if size <= 0:
            continue
        treatments.append(
            EdgeTreatment(
                "",
                kind,
                face.id,
                (cap.id, side.id),
                size,
                tuple(point),
                tuple(direction),
                segments,
                reference,
            )
        )
    by_id = {f.id: f for f in fitted.faces}

    def order(treatment):
        side = by_id[treatment.hosts[1]].params
        return (
            *(
                [round(float(np.dot(side.normal, d)), 8) for d in frame]
                if frame is not None
                else []
            ),
            treatment.face_id,
        )

    numbered = []
    for kind in ("chamfer", "edge_round"):
        for index, treatment in enumerate(
            sorted((t for t in treatments if t.kind == kind), key=order), 1
        ):
            numbered.append(replace(treatment, id=f"{kind}_{index}"))
    removed = {t.face_id for t in numbered}
    faces = [f for f in fitted.faces if f.id not in removed]
    graph = fitted.graph.copy()
    graph.remove_nodes_from(removed)
    for face in faces:
        graph.nodes[face.id]["face"] = face
    return Defeatured(
        SegmentationResult(faces, graph, fitted.mesh),
        tuple(axis),
        tuple(numbered),
        tuple(rejected),
    )
