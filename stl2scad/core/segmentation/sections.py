"""Constant-section solids: end-cap loops, analytic outline arcs and through cuts.

This path proves a common pair of end caps for *every* side face. Curves on
those loops are sketch arcs, not spatial fillets. Solids with other axial
levels (bosses, blind holes, chamfers) stay with the feature topology detector.
"""

from collections import Counter, defaultdict
from dataclasses import replace

import numpy as np

from .features import Feature, Profile, ProfileSegment, _face_area, _unit
from .models import Cylinder, Plane


def boundary_loops(result, cap):
    """Return all cap loops as indexed vertices with their adjacent side faces."""
    mesh = result.mesh
    triangles = np.flatnonzero(np.isin(mesh.source_indices, cap.triangle_indices))
    counts = Counter(
        tuple(sorted((int(a), int(b))))
        for t in mesh.triangles[triangles]
        for a, b in zip(t, np.roll(t, -1))
    )
    boundary = {edge for edge, count in counts.items() if count == 1}
    side = {}
    for neighbor in result.graph.neighbors(cap.id):
        for edge in result.graph[cap.id][neighbor]["mesh_edges"]:
            side[tuple(sorted(edge))] = neighbor
    if not boundary or not boundary <= side.keys():
        raise ValueError("Section boundary has missing side-face provenance")
    neighbors = defaultdict(list)
    for a, b in boundary:
        neighbors[a].append(b)
        neighbors[b].append(a)
    if any(len(v) != 2 for v in neighbors.values()):
        raise ValueError("Section cap has a non-manifold boundary")
    remaining, loops = set(neighbors), []
    while remaining:
        seed = min(remaining)
        indices, previous, current = [], None, seed
        while True:
            indices.append(current)
            remaining.remove(current)
            following = min(v for v in neighbors[current] if v != previous)
            if following == seed:
                break
            if following not in remaining:
                raise ValueError("Section boundary is self-intersecting")
            previous, current = current, following
        loops.append(
            (
                indices,
                [
                    side[tuple(sorted((a, b)))]
                    for a, b in zip(indices, indices[1:] + indices[:1])
                ],
            )
        )
    return loops


def _area(points):
    return (
        np.sum(
            points[:, 0] * np.roll(points[:, 1], -1)
            - points[:, 1] * np.roll(points[:, 0], -1)
        )
        / 2
    )


def _segments(points, owners, by_id, rotation, origin):
    # Traverse the outer boundary counterclockwise. Start on a face boundary,
    # so even the first and last cylinder strip is represented exactly once.
    if _area(points) < 0:
        points = points[::-1]
        owners = np.roll(owners[::-1], -1).tolist()
    starts = [i for i in range(len(points)) if owners[i] != owners[i - 1]]
    if not starts:
        raise ValueError("A complete circular outline needs a noncircular frame")
    start = min(starts, key=lambda i: (round(points[i, 0], 4), round(points[i, 1], 4)))
    points, owners = np.roll(points, -start, axis=0), np.roll(owners, -start).tolist()
    starts = [i for i in range(len(points)) if owners[i] != owners[i - 1]] + [
        len(points)
    ]
    segments = []
    for a, b in zip(starts, starts[1:]):
        face = by_id[owners[a]]
        samples = np.vstack((points[a:b], points[b % len(points)]))
        fields = dict(
            start=tuple(samples[0]), end=tuple(samples[-1]), face_ids=(face.id,)
        )
        if isinstance(face.params, Plane):
            chord = samples[-1] - samples[0]
            if (
                np.max(
                    abs(
                        np.linalg.det(
                            np.stack(
                                (
                                    samples - samples[0],
                                    np.broadcast_to(chord, samples.shape),
                                ),
                                axis=1,
                            )
                        )
                    )
                )
                > 1e-3
            ):
                raise ValueError("Planar section side is not a straight line")
            segments.append(ProfileSegment("line", **fields))
        else:
            model = face.params
            if model.segments is None or model.radial_reference is None:
                raise ValueError(f"Unresolved arc tessellation at {face.id}")
            center = ((np.asarray(model.point) - origin) @ rotation)[:2]
            angles = np.unwrap(
                np.arctan2(samples[:, 1] - center[1], samples[:, 0] - center[0])
            )
            radial = np.asarray(model.radial_reference) @ rotation
            segments.append(
                ProfileSegment(
                    "arc",
                    **fields,
                    center=tuple(center),
                    radius=model.radius,
                    start_deg=float(np.degrees(angles[0])),
                    sweep_deg=float(np.degrees(angles[-1] - angles[0])),
                    phase_deg=float(np.degrees(np.arctan2(radial[1], radial[0]))),
                    segments=model.segments,
                    convexity=face.convexity,
                )
            )
    return tuple(segments)


def _rounded_rectangle(segments, width, height, tolerance):
    corners = [s for s in segments if s.kind == "arc" and s.convexity == "convex"]
    if len(corners) != 4:
        return False
    quadrants = set()
    for s in corners:
        center, r = np.asarray(s.center), s.radius
        target = np.where(
            center < [width / 2, height / 2], r, np.array([width, height]) - r
        )
        if (
            np.linalg.norm(center - target) > tolerance
            or abs(abs(s.sweep_deg) - 90) > 0.1
        ):
            return False
        quadrants.add(tuple(center > [width / 2, height / 2]))
    return len(quadrants) == 4 and all(
        s.kind != "line" or min(abs(np.asarray(s.end) - s.start)) < tolerance
        for s in segments
    )


def detect_section_features(result):
    """Return a proved prismatic decomposition, or None for a nonprismatic solid."""
    mesh = result.mesh
    planes = [f for f in result.faces if isinstance(f.params, Plane)]
    curves = [f for f in result.faces if isinstance(f.params, Cylinder)]
    if not curves:
        return None  # Existing rectangular/L/U/T path retains its API.
    tolerance = mesh.diagonal * 2e-5
    pairs = []
    for i, a in enumerate(planes):
        for b in planes[i + 1 :]:
            if np.dot(a.params.normal, b.params.normal) > -0.999999:
                continue
            axis = -np.asarray(a.params.normal)
            length = float((np.asarray(b.params.point) - a.params.point) @ axis)
            if length <= tolerance:
                continue
            if any(abs(np.dot(f.params.axis, axis)) < 0.999999 for f in curves):
                continue
            if any(
                abs(np.dot(f.params.normal, axis)) > 1e-3
                for f in planes
                if f not in (a, b)
            ):
                continue
            levels = mesh.vertices @ axis
            if abs(np.ptp(levels) - length) > tolerance:
                continue
            pairs.append((_face_area(result, a), -i, a, b, axis, length))
    if not pairs:
        return None
    _, _, cap, other, axis, length = max(pairs, key=lambda row: row[:2])
    first, second = boundary_loops(result, cap), boundary_loops(result, other)
    p = mesh.vertices[[i for loop, _ in first for i in loop]]
    q = mesh.vertices[[i for loop, _ in second for i in loop]]
    distances = np.linalg.norm((p + axis * length)[:, None] - q[None, :], axis=2)
    if (
        len(first) != len(second)
        or max(distances.min(axis=0).max(), distances.min(axis=1).max()) > tolerance
    ):
        raise ValueError("Opposite caps have different sections")
    # Every side face must touch both caps; the cap match alone cannot prove
    # the absence of an interior shelf or an unsupported spatial round.
    sides = [f for f in result.faces if f not in (cap, other)]
    if any(
        not all(result.graph.has_edge(f.id, c.id) for c in (cap, other)) for f in sides
    ):
        raise ValueError("Side face does not span the extrusion")
    side_planes = sorted(
        (f for f in sides if isinstance(f.params, Plane)),
        key=lambda f: (-_face_area(result, f), f.id),
    )
    if not side_planes:
        raise ValueError("An arc profile needs a straight side to define its frame")
    v = -np.asarray(side_planes[0].params.normal)
    u = _unit(np.cross(v, axis))
    rotation = np.column_stack((u, np.cross(axis, u), axis))
    projected = p @ rotation
    origin = (
        rotation @ np.r_[projected[:, :2].min(axis=0), np.dot(cap.params.point, axis)]
    )
    frame = np.eye(4)
    frame[:3, :3] = rotation
    frame[:3, 3] = origin
    matrix = tuple(tuple(float(x) for x in row) for row in frame)
    loops = [
        ((mesh.vertices[indices] - origin) @ rotation, owners)
        for indices, owners in first
    ]
    loops.sort(key=lambda row: -abs(_area(row[0][:, :2])))
    outer, owners = loops[0]
    by_id = {f.id: f for f in result.faces}
    segments = _segments(outer[:, :2], owners, by_id, rotation, origin)
    width, height = np.ptp(outer[:, :2], axis=0)
    kind = (
        "rounded_rectangle"
        if _rounded_rectangle(segments, width, height, tolerance)
        else "arc"
    )
    dimensions = [("width", float(width)), ("height", float(height))]
    if kind == "rounded_rectangle":
        dimensions += [("plate_length", float(width)), ("plate_width", float(height))]
    profile = Profile(
        kind, tuple(tuple(p) for p in outer[:, :2]), tuple(dimensions), segments
    )
    body_ids = tuple(
        f.id for f in result.faces if f.id in set(owners) | {cap.id, other.id}
    )
    features = [
        Feature(
            "body_1",
            kind + "_profile_extrude",
            "additive",
            body_ids,
            matrix,
            height=length,
            profile=profile,
        )
    ]
    cuts = []
    for points, owners in loops[1:]:
        faces = [f for f in result.faces if f.id in set(owners)]
        curved = [f for f in faces if isinstance(f.params, Cylinder)]
        straight = [f for f in faces if isinstance(f.params, Plane)]
        if not curved or any(f.convexity != "concave" for f in curved):
            raise ValueError(
                "Unsupported through-cut section: expected circular hole or stadium"
            )
        centers = [
            ((np.asarray(f.params.point) - origin) @ rotation)[:2] for f in curved
        ]
        r = curved[0].params.radius
        n = curved[0].params.segments
        if n is None or any(f.params.radial_reference is None for f in curved):
            raise ValueError("Unresolved through-cut tessellation")
        if any(
            abs(f.params.radius - r) > tolerance or f.params.segments != n
            for f in curved
        ):
            raise ValueError(
                "Stadium end arcs must have the same radius and tessellation"
            )
        ref = np.asarray(curved[0].params.radial_reference) @ rotation
        common = dict(
            polarity="subtractive",
            face_ids=tuple(f.id for f in faces),
            part_frame=matrix,
            on_face=cap.id,
            radius=r,
            depth=length,
            segments=n,
            radial_reference=tuple(ref),
            position=tuple(np.r_[np.mean(centers, axis=0), 0.0]),
        )
        if len(curved) == 1 and not straight:
            cuts.append(Feature("", "through_hole", **common))
        elif len(curved) == 2 and len(straight) == 2:
            direction = _unit(centers[1] - centers[0])
            delta = float(np.linalg.norm(centers[1] - centers[0]))
            angle = float(
                (np.degrees(np.arctan2(direction[1], direction[0])) + 90) % 180 - 90
            )
            # Validate both walls against the actual faceted end polygons. A
            # decagon's support is r*cos(18deg), not its circumradius r.
            ns = [np.asarray(f.params.normal) @ rotation for f in straight]
            if abs(ns[0] @ ns[1] + 1) > 1e-4 or any(
                abs(normal[:2] @ direction) > 1e-4 for normal in ns
            ):
                raise ValueError(
                    "Through-slot walls are not parallel to its end centers"
                )
            for face, normal in zip(straight, ns):
                actual = abs(
                    (
                        ((np.asarray(face.params.point) - origin) @ rotation)[:2]
                        - centers[0]
                    )
                    @ normal[:2]
                )
                phase = np.arctan2(ref[1], ref[0])
                directions = np.column_stack(
                    (
                        np.cos(phase + np.arange(n) * 2 * np.pi / n),
                        np.sin(phase + np.arange(n) * 2 * np.pi / n),
                    )
                )
                support = r * np.max(abs(directions @ normal[:2]))
                if abs(actual - support) > tolerance:
                    raise ValueError("Stadium walls disagree with the end polygons")
            cuts.append(
                Feature(
                    "",
                    "through_slot",
                    **common,
                    between=tuple(f.id for f in straight),
                    width=2 * r,
                    length=delta + 2 * r,
                    angle_deg=angle,
                )
            )
        else:
            raise ValueError(
                "Unsupported through-cut section: expected circular hole or stadium"
            )
    # Geometric ordering survives STL triangle ordering and rigid rotations.
    # Alignments to the dominant side direction precede angled slots; then
    # distance to the section centroid, with a part-frame tie break.
    counts = Counter()
    for cut in sorted(
        cuts,
        key=lambda f: (
            f.kind,
            round(abs(f.angle_deg), 3),
            round(
                np.linalg.norm(np.asarray(f.position[:2]) - [width / 2, height / 2]), 3
            ),
            tuple(np.round(f.position, 3)),
        ),
    ):
        prefix = "slot" if cut.kind == "through_slot" else "hole"
        counts[prefix] += 1
        features.append(replace(cut, id=f"{prefix}_{counts[prefix]}"))
    if set(i for f in features for i in f.face_ids) != set(by_id):
        raise ValueError("Section decomposition does not own every face")
    return features


def arc_points(segment):
    """Tessellate an arc, retaining intersections with a clipped end chord."""
    start, end = segment.start_deg, segment.start_deg + segment.sweep_deg
    step = 360 / segment.segments
    low, high = sorted((start, end))
    interior = segment.phase_deg + step * np.arange(
        np.floor((low - segment.phase_deg) / step) + 1,
        np.ceil((high - segment.phase_deg) / step),
    )
    interior = interior[(interior > low + 1e-7) & (interior < high - 1e-7)]
    if end < start:
        interior = interior[::-1]
    angles = np.r_[start, interior, end]
    mid = (
        segment.phase_deg + (np.floor((angles - segment.phase_deg) / step) + 0.5) * step
    )
    radii = (
        segment.radius * np.cos(np.radians(step / 2)) / np.cos(np.radians(angles - mid))
    )
    return np.asarray(segment.center) + radii[:, None] * np.column_stack(
        (np.cos(np.radians(angles)), np.sin(np.radians(angles)))
    )


def profile_points(profile):
    return np.vstack(
        [arc_points(s) if s.kind == "arc" else [s.start] for s in profile.segments]
    )
