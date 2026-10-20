"""Recover height intervals and analytic, provenance-bearing section loops.

Geometry is expressed in the caller's rigid part frame. Mesh sections provide
ordering hints and unmodeled wall polylines; fitted surfaces provide the lines
and faceted arcs, including the virtual outline after removing treatments.
"""

from dataclasses import dataclass, replace

import networkx as nx
import numpy as np

from .defeature import Defeatured
from .features import Profile, ProfileSegment
from .models import Cylinder, Plane
from .profile_geometry import boundary_distance
from .repair import _weld
from .sections import arc_points, profile_points

__all__ = ["Slab", "slab_levels", "slab_profiles"]


@dataclass(frozen=True)
class Slab:
    index: int
    bottom: float
    top: float
    loops: tuple[Profile, ...]
    face_ids: tuple[str, ...]
    point_face_ids: tuple[str, ...] = ()


def _context(defeatured, frame):
    frame = np.asarray(frame, dtype=float)
    if (
        frame.shape != (4, 4)
        or not np.isfinite(frame).all()
        or not np.allclose(frame[3], [0, 0, 0, 1])
        or not np.allclose(frame[:3, :3].T @ frame[:3, :3], np.eye(3), atol=1e-8)
        or not np.isclose(np.linalg.det(frame[:3, :3]), 1)
    ):
        raise ValueError("Slabs require a rigid, right-handed part frame")
    if abs(np.dot(frame[:3, 2], defeatured.axis)) < 1 - 1e-8:
        raise ValueError("Part frame Z must follow the extrusion axis")
    mesh = defeatured.result.mesh
    if mesh is None:
        raise ValueError("Slabs require indexed mesh support")
    vertices = (mesh.vertices - frame[:3, 3]) @ frame[:3, :3]
    return mesh, vertices, mesh.diagonal * 2e-5


def _cap(face, axis):
    return isinstance(face.params, Plane) and abs(
        np.dot(face.params.normal, axis)
    ) >= np.cos(np.radians(0.5))


def _analytic(face, frame):
    """Only extrusion-compatible surfaces have a line or circular section."""
    p = face.params
    if isinstance(p, Plane) and abs(np.dot(p.normal, frame[:3, 2])) <= np.sin(
        np.radians(0.5)
    ):
        return "line"
    if isinstance(p, Cylinder) and abs(np.dot(p.axis, frame[:3, 2])) >= np.cos(
        np.radians(0.5)
    ):
        return "arc"
    return None


def slab_levels(defeatured: Defeatured, frame: np.ndarray) -> list[float]:
    """Merge fitted cap heights at the scale-relative section tolerance."""
    _, _, tolerance = _context(defeatured, frame)
    heights = sorted(
        float((np.asarray(f.params.point) - frame[:3, 3]) @ frame[:3, 2])
        for f in defeatured.result.faces
        if _cap(f, frame[:3, 2])
    )
    groups = []
    for height in heights:
        if not groups or height - groups[-1][0] > tolerance:
            groups.append([height])
        else:
            groups[-1].append(height)
    return [float(np.mean(group)) for group in groups]


def _section(face, mesh, vertices, height, tolerance):
    """Ordered section of one source region, retaining nonanalytic chords."""
    indices = np.flatnonzero(np.isin(mesh.source_indices, face.triangle_indices))
    pieces = []
    for tri in vertices[mesh.triangles[indices]]:
        hits = []
        for a, b in zip(tri, np.roll(tri, -1, axis=0)):
            if (a[2] <= height < b[2]) or (b[2] <= height < a[2]):
                hits.append((a + (b - a) * ((height - a[2]) / (b[2] - a[2])))[:2])
        if len(hits) == 2 and np.linalg.norm(hits[0] - hits[1]) > tolerance * 1e-4:
            pieces.extend(hits)
    if not pieces:
        return np.empty((0, 2))
    points, labels = _weld(
        np.column_stack((pieces, np.zeros(len(pieces)))), tolerance * 0.01
    )
    graph = nx.Graph()
    graph.add_edges_from(labels.reshape(-1, 2))
    ends = [i for i in graph if graph.degree(i) == 1]
    if not nx.is_connected(graph) or any(graph.degree(i) > 2 for i in graph):
        raise ValueError(f"Face {face.id} has multiple or branched section chains")
    seed = min(ends or list(graph))
    order, previous, current = [], None, seed
    while True:
        order.append(current)
        following = sorted(i for i in graph[current] if i != previous and i != seed)
        if not following:
            break
        previous, current = current, following[0]
    if not ends:
        order.append(seed)
    return points[order, :2]


def _arc(face, frame):
    p = face.params
    center = ((np.asarray(p.point) - frame[:3, 3]) @ frame[:3, :3])[:2]
    reference = (
        np.asarray(p.radial_reference) @ frame[:3, :3]
        if p.radial_reference is not None
        else np.array([1.0, 0.0, 0.0])
    )
    phase = float(np.degrees(np.arctan2(reference[1], reference[0])))
    if p.segments is None:
        raise ValueError(f"Cylinder {face.id} lacks input tessellation")
    return ProfileSegment(
        "arc",
        tuple(center),
        tuple(center),
        (face.id,),
        tuple(center),
        p.radius,
        phase,
        360.0,
        phase,
        p.segments,
        face.convexity,
    )


def _junction(a, b, chains, frame, height, tolerance):
    """Intersect neighboring analytic supports near their observed boundary."""
    ca, cb = chains[a.id], chains[b.id]
    distances = np.linalg.norm(ca[:, None] - cb[None, :], axis=2)
    i, j = np.unravel_index(np.argmin(distances), distances.shape)
    hint = (ca[i] + cb[j]) / 2
    planes = [f for f in (a, b) if _analytic(f, frame) == "line"]
    if len(planes) == 2:
        normals = np.array(
            [np.asarray(f.params.normal) @ frame[:3, :3] for f in planes]
        )
        rhs = [
            f.params.offset - np.dot(f.params.normal, frame[:3, 3]) - n[2] * height
            for f, n in zip(planes, normals)
        ]
        if abs(np.linalg.det(normals[:, :2])) <= 1e-10:
            raise ValueError("Parallel section neighbors cannot define a corner")
        return np.linalg.solve(normals[:, :2], rhs)
    circles = [f for f in (a, b) if _analytic(f, frame) == "arc"]
    if len(planes) == 1 and len(circles) == 1:
        plane = planes[0].params
        normal = np.asarray(plane.normal) @ frame[:3, :3]
        offset = plane.offset - np.dot(plane.normal, frame[:3, 3]) - normal[2] * height
        ring = arc_points(_arc(circles[0], frame))
        candidates = []
        for x, y in zip(ring[:-1], ring[1:]):
            dx, dy = x @ normal[:2] - offset, y @ normal[:2] - offset
            if abs(dx) < tolerance * 0.01:
                candidates.append(x)
            if dx * dy < 0:
                candidates.append(x + (y - x) * dx / (dx - dy))
        if candidates:
            return min(candidates, key=lambda p: np.linalg.norm(p - hint))
        raise ValueError("Plane does not intersect the faceted cylinder")
    if np.linalg.norm(ca[i] - cb[j]) > tolerance:
        raise ValueError("Unmodeled section neighbors have a gap")
    return hint


def _area(profile):
    points = profile_points(profile)
    return float(
        np.sum(
            points[:, 0] * np.roll(points[:, 1], -1)
            - points[:, 1] * np.roll(points[:, 0], -1)
        )
        / 2
    )


def _profile(segments):
    segments = tuple(segments)
    kind = "arc" if any(s.kind == "arc" for s in segments) else "polygon"
    # The section owns its labels even when no named profile is recognized.
    return Profile(kind, tuple(s.start for s in segments), (), segments)


def _reverse(profile):
    return _profile(
        replace(
            s,
            start=s.end,
            end=s.start,
            start_deg=s.start_deg + s.sweep_deg,
            sweep_deg=-s.sweep_deg,
        )
        for s in reversed(profile.segments)
    )


def _inside(point, polygon):
    inside = False
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        if (a[1] > point[1]) != (b[1] > point[1]):
            if point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]:
                inside = not inside
    return inside


def _loops(result, active, chains, frame, height, tolerance):
    graph = result.graph.subgraph(active).copy()
    # A source face may span several levels. Its adjacency at another height
    # must not join disjoint islands in this section (for example a step head).
    for a, b, data in list(graph.edges(data=True)):
        edges = data.get("mesh_edges", ())
        if edges:
            z = (result.mesh.vertices[np.asarray(edges)] - frame[:3, 3]) @ frame[:3, 2]
            if not np.any((z.min(axis=1) <= height) & (z.max(axis=1) >= height)):
                graph.remove_edge(a, b)
    loops, point_ids = [], set()
    by_id = {f.id: f for f in result.faces}
    for component in sorted(nx.connected_components(graph), key=lambda ids: min(ids)):
        if len(component) == 1:
            face = by_id[next(iter(component))]
            chain = chains[face.id]
            if np.linalg.norm(chain[0] - chain[-1]) > tolerance:
                raise ValueError("An isolated section face must have a closed section")
            if _analytic(face, frame) == "arc":
                arc = _arc(face, frame)
                start = tuple(arc_points(arc)[0])
                loops.append(_profile([replace(arc, start=start, end=start)]))
            else:
                point_ids.add(face.id)
                loop = _profile(
                    ProfileSegment("line", tuple(a), tuple(b), (face.id,))
                    for a, b in zip(chain[:-1], chain[1:])
                )
                loops.append(_reverse(loop) if _area(loop) < 0 else loop)
            continue
        if any(graph.degree(i) != 2 for i in component):
            raise ValueError("Active face graph is not a section cycle")
        seed = min(component)
        order, previous, current = [], None, seed
        while True:
            order.append(current)
            following = min(i for i in graph[current] if i != previous)
            if following == seed:
                break
            previous, current = current, following
        junctions = [
            _junction(by_id[a], by_id[b], chains, frame, height, tolerance)
            for a, b in zip(order, order[1:] + order[:1])
        ]
        segments = []
        for i, fid in enumerate(order):
            face = by_id[fid]
            start, end = junctions[i - 1], junctions[i]
            fields = dict(start=tuple(start), end=tuple(end), face_ids=(fid,))
            if _analytic(face, frame) == "line":
                segments.append(ProfileSegment("line", **fields))
            elif _analytic(face, frame) == "arc":
                arc = _arc(face, frame)
                angles = np.degrees(
                    np.arctan2(*((np.array([start, end]) - arc.center)[:, ::-1].T))
                )
                positive = float((angles[1] - angles[0]) % 360)
                support = chains[fid] - arc.center
                support_angles = (
                    np.degrees(np.arctan2(support[:, 1], support[:, 0])) - angles[0]
                ) % 360
                # Interior section samples determine which of the two arcs is material.
                sweep = (
                    positive
                    if np.count_nonzero(support_angles < positive + 1e-4)
                    >= len(support_angles) / 2
                    else positive - 360
                )
                segments.append(
                    replace(arc, **fields, start_deg=float(angles[0]), sweep_deg=sweep)
                )
            else:
                point_ids.add(fid)
                points = chains[fid]
                if np.linalg.norm(points[-1] - start) < np.linalg.norm(
                    points[0] - start
                ):
                    points = points[::-1]
                points = np.vstack((start, points[1:-1], end))
                segments.extend(
                    ProfileSegment("line", tuple(a), tuple(b), (fid,))
                    for a, b in zip(points[:-1], points[1:])
                )
        loop = _profile(segments)
        loops.append(_reverse(loop) if _area(loop) < 0 else loop)
    # A loop inside another boundary is a hole; disjoint islands stay CCW.
    polygons = [profile_points(p) for p in loops]
    loops = [
        (
            _reverse(p)
            if sum(_inside(polygons[i][0], q) for j, q in enumerate(polygons) if i != j)
            % 2
            else p
        )
        for i, p in enumerate(loops)
    ]
    return tuple(loops), tuple(sorted(point_ids))


def _equal(a, b, tolerance):
    if len(a) != len(b):
        return False
    remaining = list(b)
    for loop in a:
        matches = [
            i
            for i, other in enumerate(remaining)
            if (_area(loop) > 0) == (_area(other) > 0)
            and boundary_distance(profile_points(loop), profile_points(other))
            <= tolerance
        ]
        if not matches:
            return False
        remaining.pop(matches[0])
    return True


def _merged_loops(before, after):
    """Keep source IDs when equal geometry from two intervals is coalesced."""
    remaining, merged = list(after), []
    for loop in before:
        index = min(
            range(len(remaining)),
            key=lambda i: (
                (_area(loop) > 0) != (_area(remaining[i]) > 0),
                boundary_distance(profile_points(loop), profile_points(remaining[i])),
            ),
        )
        other = remaining.pop(index)
        segments = list(loop.segments)
        samples = [
            arc_points(s) if s.kind == "arc" else np.array([s.start, s.end])
            for s in segments
        ]
        for segment in other.segments:
            points = (
                arc_points(segment)
                if segment.kind == "arc"
                else np.array([segment.start, segment.end])
            )
            j = min(
                range(len(samples)), key=lambda i: boundary_distance(samples[i], points)
            )
            segments[j] = replace(
                segments[j],
                face_ids=tuple(
                    sorted(set(segments[j].face_ids) | set(segment.face_ids))
                ),
            )
        merged.append(_profile(segments))
    return tuple(merged)


def slab_profiles(defeatured: Defeatured, frame: np.ndarray) -> list[Slab]:
    """Slice active source faces, trim fitted edges, and merge equal sections.

    A face spanning several intervals is owned by the first interval using it;
    segments in subsequent intervals retain that same source ID. Upward caps
    belong below their height and downward caps above it.
    """
    frame = np.asarray(frame, dtype=float)
    mesh, vertices, tolerance = _context(defeatured, frame)
    levels = slab_levels(defeatured, frame)
    if len(levels) < 2:
        raise ValueError("At least two cap levels are required")
    result = defeatured.result
    spans = {}
    for face in result.faces:
        rows = np.flatnonzero(np.isin(mesh.source_indices, face.triangle_indices))
        if not len(rows):
            raise ValueError(f"Face {face.id} has no mesh support")
        z = vertices[mesh.triangles[rows], 2]
        spans[face.id] = float(z.min()), float(z.max())
    slabs, owned = [], set()
    for bottom, top in zip(levels[:-1], levels[1:]):
        height = (bottom + top) / 2
        active = {
            f.id
            for f in result.faces
            if not _cap(f, frame[:3, 2]) and spans[f.id][0] < height < spans[f.id][1]
        }
        chains = {
            f.id: _section(f, mesh, vertices, height, tolerance)
            for f in result.faces
            if f.id in active
        }
        if not active or any(not len(p) for p in chains.values()):
            raise ValueError("Slab lacks supported side sections")
        loops, point_ids = _loops(result, active, chains, frame, height, tolerance)
        owners = set(active) - owned
        for face in result.faces:
            if face.id in owned or not _cap(face, frame[:3, 2]):
                continue
            level = float((np.asarray(face.params.point) - frame[:3, 3]) @ frame[:3, 2])
            target = top if np.dot(face.params.normal, frame[:3, 2]) > 0 else bottom
            if abs(level - target) <= tolerance:
                owners.add(face.id)
        owned.update(owners)
        slab = Slab(
            len(slabs) + 1, bottom, top, loops, tuple(sorted(owners)), point_ids
        )
        if slabs and _equal(slabs[-1].loops, loops, tolerance):
            before = slabs.pop()
            slab = replace(
                before,
                top=top,
                loops=_merged_loops(before.loops, loops),
                face_ids=tuple(sorted(set(before.face_ids) | owners)),
                point_face_ids=tuple(
                    sorted(set(before.point_face_ids) | set(point_ids))
                ),
            )
        slabs.append(slab)
    # Faces outside the recovered cap intervals remain available to the
    # subsequent remainder stage; Slab.face_ids is the explained-face set.
    return slabs
