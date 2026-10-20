"""Feature ownership, part frames and section profiles, independent of the IR."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

import numpy as np

from .models import Cylinder, Face, Plane, SegmentationResult, Vector

Matrix4 = tuple[tuple[float, ...], ...]
FeatureKind = Literal[
    "rectangle_profile_extrude",
    "l_profile_extrude",
    "u_profile_extrude",
    "t_profile_extrude",
    "polygon_profile_extrude",
    "fillet",
    "boss",
    "blind_hole",
    "through_hole",
    "pocket",
]


@dataclass(frozen=True)
class Profile:
    """CCW section in part-frame XY, labeled even when its type is unknown."""

    kind: str
    points: tuple[tuple[float, float], ...]
    dimensions: tuple[tuple[str, float], ...]

    @property
    def labeled_points(self):
        return tuple((f"P{i}", point) for i, point in enumerate(self.points))


@dataclass(frozen=True)
class Feature:
    id: str
    kind: FeatureKind
    polarity: Literal["additive", "subtractive"]
    face_ids: tuple[str, ...]
    part_frame: Matrix4  # Local-to-world rigid transform, shared by all features.
    on_face: str | None = None
    between: tuple[str, ...] = ()
    radius: float | None = None
    height: float | None = None
    depth: float | None = None
    position: Vector = (
        0.0,
        0.0,
        0.0,
    )  # Axis intersection with the host, in part frame.
    axis: Vector = (0.0, 0.0, 1.0)
    profile: Profile | None = None
    corner: Vector | None = None  # Sharp corner replaced by an additive fillet.

    @property
    def host(self):
        return self.on_face


def _unit(v):
    return np.asarray(v, dtype=float) / np.linalg.norm(v)


def _boundary_loop(result, face):
    mesh = result.mesh
    local = np.flatnonzero(np.isin(mesh.source_indices, face.triangle_indices))
    counts = Counter()
    for triangle in mesh.triangles[local]:
        counts.update(
            tuple(sorted((int(a), int(b))))
            for a, b in zip(triangle, np.roll(triangle, -1))
        )
    neighbors = defaultdict(list)
    for (a, b), count in counts.items():
        if count == 1:
            neighbors[a].append(b)
            neighbors[b].append(a)
    if not neighbors or any(len(row) != 2 for row in neighbors.values()):
        raise ValueError("Profile cap must have manifold boundary loops")
    seed = min(neighbors)
    loop, previous, current = [], None, seed
    while True:
        loop.append(current)
        choices = sorted(v for v in neighbors[current] if v != previous)
        following = choices[0]
        if following == seed:
            break
        if following in loop:
            raise ValueError("Self-intersecting profile boundary")
        previous, current = current, following
    if len(loop) != len(neighbors):
        raise ValueError("Profile holes and multiple cap loops are not supported yet")
    return mesh.vertices[loop]


def _simplify(points, tolerance):
    points = np.array(points, dtype=float)
    changed = True
    while changed and len(points) > 3:
        changed = False
        for i in range(len(points)):
            a, b, c = points[i - 1], points[i], points[(i + 1) % len(points)]
            ab, bc = b - a, c - b
            if (
                np.linalg.norm(ab) <= tolerance
                or np.linalg.norm(bc) <= tolerance
                or (
                    abs(np.linalg.det(np.stack((ab, bc))))
                    <= tolerance * (np.linalg.norm(ab) + np.linalg.norm(bc))
                    and ab @ bc >= 0
                )
            ):
                points = np.delete(points, i, axis=0)
                changed = True
                break
    area2 = np.sum(
        points[:, 0] * np.roll(points[:, 1], -1)
        - points[:, 1] * np.roll(points[:, 0], -1)
    )
    if area2 < 0:
        points = points[::-1]
    start = min(range(len(points)), key=lambda i: tuple(points[i]))
    return np.roll(points, -start, axis=0)


def classify_profile(points, tolerance=1e-5) -> Profile:
    points = _simplify(points, tolerance)
    low, high = points.min(axis=0), points.max(axis=0)
    width, height = high - low
    dims = [("width", float(width)), ("height", float(height))]
    edges = np.roll(points, -1, axis=0) - points
    orthogonal = np.all(np.min(np.abs(edges), axis=1) <= tolerance)
    turns = np.linalg.det(np.stack((np.roll(edges, 1, axis=0), edges), axis=1))
    concave = np.flatnonzero(turns < -(tolerance**2))
    kind = "polygon"
    if orthogonal:
        if len(points) == 4 and not len(concave):
            kind = "rectangle"
        elif len(points) == 6 and len(concave) == 1:
            kind = "l"
            corner = points[concave[0]]
            thickness = np.minimum(corner - low, high - corner)
            dims += [
                ("wall_thickness", float(thickness[0])),
                ("base_thickness", float(thickness[1])),
            ]
        elif len(points) == 8 and len(concave) == 2:
            a, b = concave
            shared = np.flatnonzero(np.abs(points[a] - points[b]) <= tolerance)
            if len(shared) == 1:
                along, across = int(shared[0]), 1 - int(shared[0])
                web = float(
                    min(points[a, along] - low[along], high[along] - points[a, along])
                )
                span = float(abs(points[a, across] - points[b, across]))
                if (a - b) % len(points) in (1, len(points) - 1):
                    kind = "u"
                    dims += [
                        ("web_thickness", web),
                        ("slot_width", span),
                        ("slot_depth", float(high[along] - low[along] - web)),
                        (
                            "arm_1_thickness",
                            float(
                                min(points[a, across], points[b, across]) - low[across]
                            ),
                        ),
                        (
                            "arm_2_thickness",
                            float(
                                high[across] - max(points[a, across], points[b, across])
                            ),
                        ),
                    ]
                else:
                    kind = "t"
                    dims += [
                        ("flange_thickness", web),
                        ("stem_width", span),
                        ("stem_height", float(high[along] - low[along] - web)),
                    ]
    return Profile(kind, tuple(tuple(float(x) for x in p) for p in points), tuple(dims))


def _cylinder_features(result):
    """Classify topology first, before selecting any coordinate frame."""
    features = []
    for curved in result.faces:
        if not isinstance(curved.params, Cylinder):
            continue
        adjacent = [
            result.graph.nodes[i]["face"] for i in result.graph.neighbors(curved.id)
        ]
        planes = [f for f in adjacent if isinstance(f.params, Plane)]
        tangent = [f for f in planes if result.edge_convexity(curved, f) == "tangent"]
        if (
            curved.convexity == "concave"
            and len(tangent) == 2
            and all(
                abs(np.dot(f.params.normal, curved.params.axis)) < 1e-3 for f in tangent
            )
            and abs(np.dot(tangent[0].params.normal, tangent[1].params.normal)) < 1e-3
        ):
            features.append(dict(kind="fillet", curved=curved, between=tuple(tangent)))
            continue
        caps = [
            f
            for f in planes
            if abs(np.dot(f.params.normal, curved.params.axis)) > 0.999
        ]
        concave = [f for f in caps if result.edge_convexity(curved, f) == "concave"]
        convex = [f for f in caps if result.edge_convexity(curved, f) == "convex"]
        if len(caps) != 2 or len(concave) != 1 or len(convex) != 1:
            raise ValueError(f"Unsupported cylinder topology at {curved.id}")
        host, end = (
            (concave[0], convex[0])
            if curved.convexity == "convex"
            else (convex[0], concave[0])
        )
        if np.dot(host.params.normal, end.params.normal) < 0.999:
            raise ValueError(
                f"Cylinder caps disagree on material direction at {curved.id}"
            )
        signed = float(
            np.dot(np.asarray(end.params.point) - host.params.point, host.params.normal)
        )
        kind = "boss" if curved.convexity == "convex" else "blind_hole"
        if (kind == "boss" and signed <= 0) or (kind == "blind_hole" and signed >= 0):
            raise ValueError(
                f"Cylinder cap is on the wrong side of its host at {curved.id}"
            )
        features.append(
            dict(kind=kind, curved=curved, host=host, end=end, length=abs(signed))
        )
    return features


def _cap_pair(result, body_faces):
    tolerance = result.mesh.diagonal * 2e-5
    loops = {}
    for face in body_faces:
        try:
            loops[face.id] = _boundary_loop(result, face)
        except ValueError:
            # A host face may contain boss/hole loops; it is not an end cap.
            continue
    candidates = []
    for i, a in enumerate(body_faces):
        for b in body_faces[i + 1 :]:
            if a.id not in loops or b.id not in loops:
                continue
            if np.dot(a.params.normal, b.params.normal) > -0.999:
                continue
            direction = -np.asarray(a.params.normal)
            length = float(
                np.dot(np.asarray(b.params.point) - a.params.point, direction)
            )
            if length <= tolerance:
                continue
            first, second = loops[a.id], loops[b.id]
            projected = first + length * direction
            distances = np.linalg.norm(projected[:, None] - second[None, :], axis=2)
            if (
                max(distances.min(axis=0).max(), distances.min(axis=1).max())
                <= tolerance
            ):
                # Nonrectangular sections have more boundary corners than a
                # side rectangle. Tie-breaking uses provenance, never axes.
                candidates.append(
                    (len(first), -i, -body_faces.index(b), a, b, direction, length)
                )
    if not candidates:
        raise ValueError("No matching opposite section caps for an extruded body")
    _, _, _, first, second, axis, length = max(candidates, key=lambda c: c[:3])
    return first, second, axis, length, loops[first.id]


def _frame(result, axis, cap, loop, secondary):
    # Plane directions are ranked by actual surface area. A host normal
    # provides a useful profile-up direction when a boss/hole supplies one.
    preferred = [item["host"] for item in secondary if "host" in item]
    source = preferred + sorted(
        (f for f in result.faces if isinstance(f.params, Plane)),
        key=lambda f: (-_face_area(result, f), f.id),
    )
    normal = next(
        (
            np.asarray(f.params.normal)
            for f in source
            if abs(np.dot(f.params.normal, axis)) < 1e-3
        ),
        None,
    )
    if normal is None:
        raise ValueError("An extrusion needs independent dominant plane normals")
    u = _unit(np.cross(normal, axis))
    v = _unit(np.cross(axis, u))
    rotation = np.column_stack((u, v, axis))
    local = loop @ rotation
    origin = rotation @ np.array(
        [local[:, 0].min(), local[:, 1].min(), np.dot(cap.params.point, axis)]
    )
    frame = np.eye(4)
    frame[:3, :3], frame[:3, 3] = rotation, origin
    return frame


def _face_area(result, face):
    return float(
        result.mesh.areas[
            np.isin(result.mesh.source_indices, face.triangle_indices)
        ].sum()
    )


def _axis_plane_point(cylinder, plane):
    axis, point = np.asarray(cylinder.axis), np.asarray(cylinder.point)
    normal = np.asarray(plane.normal)
    return point + axis * ((plane.offset - normal @ point) / (normal @ axis))


def detect_features(result: SegmentationResult) -> list[Feature]:
    """Recover one extruded body with graph-owned bosses, blind holes and fillets.

    Unsupported topology fails explicitly; there is no triangle-copy fallback.
    The source mesh is used only to obtain boundary sections and provenance.
    """
    if result.mesh is None:
        raise ValueError("Feature detection requires indexed segmentation support")
    secondary = _cylinder_features(result)
    owned = {
        item[key].id for item in secondary for key in ("curved", "end") if key in item
    }
    body_faces = [f for f in result.faces if f.id not in owned]
    if not body_faces or any(not isinstance(f.params, Plane) for f in body_faces):
        raise ValueError("The base body must have planar section caps and sides")
    cap, _, axis, length, loop = _cap_pair(result, body_faces)
    frame = _frame(result, axis, cap, loop, secondary)
    rot, origin = frame[:3, :3], frame[:3, 3]
    local = lambda p: (np.asarray(p) - origin) @ rot
    profile_points = local(loop)[:, :2]
    tolerance = result.mesh.diagonal * 2e-5
    fillet_data = {}
    for item in secondary:
        if item["kind"] != "fillet":
            continue
        cylinder = item["curved"].params
        if abs(np.dot(cylinder.axis, axis)) < 0.999:
            raise ValueError("Only fillets spanning the body extrusion are supported")
        sides = item["between"]
        normals = np.array([np.asarray(f.params.normal) @ rot for f in sides])[:, :2]
        offsets = np.array(
            [f.params.offset - np.dot(f.params.normal, origin) for f in sides]
        )
        corner = np.linalg.solve(normals, offsets)
        center3 = _axis_plane_point(cylinder, cap.params)
        center = local(center3)
        radial_error = np.abs(
            np.linalg.norm(profile_points - center[:2], axis=1) - cylinder.radius
        )
        arc = radial_error <= tolerance
        if not arc.any() or arc.all():
            raise ValueError("Fillet has no bounded section arc")
        start = int(np.flatnonzero(~arc)[0])
        profile_points, arc = np.roll(profile_points, -start, axis=0), np.roll(
            arc, -start
        )
        indices = np.flatnonzero(arc)
        if np.any(np.diff(indices) != 1):
            raise ValueError("Fillet section arc is not contiguous")
        profile_points = np.concatenate(
            (profile_points[: indices[0]], [corner], profile_points[indices[-1] + 1 :])
        )
        fillet_data[item["curved"].id] = (center, np.r_[corner, 0.0])
    profile = classify_profile(profile_points, tolerance)
    matrix = tuple(tuple(float(v) for v in row) for row in frame)
    features = [
        Feature(
            "body_1",
            f"{profile.kind}_profile_extrude",
            "additive",
            tuple(f.id for f in body_faces),
            matrix,
            height=length,
            profile=profile,
        )
    ]
    counts = Counter()
    for item in secondary:
        kind, curved = item["kind"], item["curved"]
        counts[kind] += 1
        common = dict(
            id=f"{kind}_{counts[kind]}",
            kind=kind,
            part_frame=matrix,
            radius=curved.params.radius,
        )
        if kind == "fillet":
            center, corner = fillet_data[curved.id]
            features.append(
                Feature(
                    **common,
                    polarity="additive",
                    face_ids=(curved.id,),
                    between=tuple(f.id for f in item["between"]),
                    height=length,
                    position=tuple(center),
                    corner=tuple(corner),
                )
            )
        else:
            host, end = item["host"], item["end"]
            direction = np.asarray(host.params.normal) * (1 if kind == "boss" else -1)
            dimensions = {"height" if kind == "boss" else "depth": item["length"]}
            features.append(
                Feature(
                    **common,
                    polarity="additive" if kind == "boss" else "subtractive",
                    face_ids=(curved.id, end.id),
                    on_face=host.id,
                    position=tuple(
                        local(_axis_plane_point(curved.params, host.params))
                    ),
                    axis=tuple(direction @ rot),
                    **dimensions,
                )
            )
    return features
