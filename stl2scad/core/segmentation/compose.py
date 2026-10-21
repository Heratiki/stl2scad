"""Compose regularized slab bodies, graph-owned treatments and fixed remainders."""

from collections import Counter, defaultdict
from dataclasses import replace

import numpy as np

from .defeature import defeature
from .features import (
    Feature,
    _axis_plane_point,
    _boundary_loop,
    _cylinder_features,
    _detect_existing,
    _face_area,
    _frame,
    _full_cylinder,
    classify_profile,
)
from .models import Cylinder, Plane, SegmentationResult
from .remainder import FREE_FORM_LIMIT, free_form_share, remainder_regions
from .sections import _rounded_rectangle, profile_points
from .slabs import slab_profiles


def _frame_for(result, axis):
    caps = [
        f
        for f in result.faces
        if isinstance(f.params, Plane)
        and abs(np.dot(f.params.normal, axis)) > np.cos(np.radians(0.5))
    ]
    if not caps:
        raise ValueError("Composition needs an extrusion cap")
    cap = min(caps, key=lambda f: (-round(_face_area(result, f), 6), f.id))
    # The largest cap is the complete lower section on stepped parts. Its
    # material-facing direction defines positive extrusion without world axes.
    axis = -np.asarray(cap.params.normal)
    loop = _boundary_loop(result, cap)
    frame = _frame(result, axis, cap, loop, [])
    projected = (loop - frame[:3, 3]) @ frame[:3, :3]
    if np.ptp(projected[:, 0]) < np.ptp(projected[:, 1]) - result.mesh.diagonal * 2e-5:
        u, v = frame[:3, 0].copy(), frame[:3, 1].copy()
        frame[:3, 0], frame[:3, 1] = v, -u
        coordinates = loop @ frame[:3, :3]
        frame[:3, 3] = (
            frame[:3, :3]
            @ np.r_[coordinates[:, :2].min(axis=0), np.dot(cap.params.point, axis)]
        )
    return frame


def _secondary(result):
    items = []
    for face in result.faces:
        if not isinstance(face.params, Cylinder):
            continue
        try:
            # Classifier still sees all adjacent graph nodes, including lips;
            # one unsupported profile arc must not mask a separate boss/hole.
            classified = _cylinder_features(replace(result, faces=[face]))
            items.extend(
                item
                for item in classified
                if item["kind"] == "fillet" or _full_cylinder(result, face)
            )
        except ValueError:
            continue
    return items


def _hull(points, tolerance):
    """Planar monotone-chain hull: only virtual support, never body geometry."""
    center = points.mean(axis=0)
    _, _, basis = np.linalg.svd(points - center, full_matrices=False)
    projected = (points - center) @ basis[:2].T
    order = sorted(range(len(points)), key=lambda i: tuple(projected[i]))
    cross = lambda a, b, c: float(
        np.linalg.det(
            np.stack((projected[b] - projected[a], projected[c] - projected[a]))
        )
    )

    def half(indices):
        out = []
        for i in indices:
            while len(out) > 1:
                a, b = out[-2:]
                limit = tolerance * (
                    np.linalg.norm(projected[b] - projected[a])
                    + np.linalg.norm(projected[i] - projected[b])
                )
                if cross(a, b, i) > limit:
                    break
                out.pop()
            out.append(i)
        return out

    return half(order)[:-1] + half(order[::-1])[:-1]


def _virtual_support(stripped, faces, links):
    """Fill planar host openings for slicing; preserve original RAG edge hints.

    The private support copy carries source IDs solely to associate patches
    with faces. Original source triangles and areas remain untouched for the
    remainder stage, provenance accounting and later whole-solid validation.
    """
    mesh = stripped.result.mesh
    vertices = list(mesh.vertices)
    graph = stripped.result.graph.subgraph([f.id for f in faces]).copy()
    by_id = {f.id: f for f in faces}
    extra = defaultdict(list)
    moved = {}
    for a, b in links:
        if a not in by_id or b not in by_id:
            continue
        graph.add_edge(a, b, convexity="convex", mesh_edges=[])
        hosts = [by_id[a], by_id[b]]
        if not all(isinstance(f.params, Plane) for f in hosts):
            continue
        # Extend hosts only at an incomplete axial support. Other hosts need
        # opening fills, not changes to the outline's circular vertex phase.
        axis = np.asarray(stripped.axis)
        cap = next(
            (f for f in hosts if abs(np.dot(f.params.normal, axis)) > 0.999), None
        )
        side = next(
            (f for f in hosts if abs(np.dot(f.params.normal, axis)) < 0.001), None
        )
        if cap is None or side is None:
            continue
        rows = np.isin(mesh.source_indices, side.triangle_indices)
        support = mesh.vertices[mesh.triangles[rows]].reshape(-1, 3)
        target = float(np.dot(cap.params.point, axis))
        span = support @ axis
        if (
            span.min() - mesh.diagonal * 2e-5
            <= target
            <= span.max() + mesh.diagonal * 2e-5
        ):
            continue
        normals = np.array([f.params.normal for f in hosts])
        offsets = np.array([f.params.offset for f in hosts])
        inverse = np.linalg.pinv(normals)
        # Source boundary points nearest the removed strip's cap are extended
        # to the virtual sharp edge. New vertices leave the real mesh intact.
        distance = np.abs(span - target)
        closest = np.unique(
            support[distance <= distance.min() + mesh.diagonal * 2e-5], axis=0
        )
        for point in closest:
            sharp = point - (normals @ point - offsets) @ inverse.T
            new = len(vertices)
            vertices.append(sharp)
            extra[side.id].append(new)
            extra[cap.id].append(new)
            old = np.flatnonzero(
                np.linalg.norm(mesh.vertices - point, axis=1) < mesh.weld_tolerance
            )
            moved.update((int(i), new) for i in old)
    for a, b, data in graph.edges(data=True):
        if data.get("mesh_edges"):
            data["mesh_edges"] = [
                tuple(moved.get(int(i), int(i)) for i in edge)
                for edge in data["mesh_edges"]
            ]
    vertices = np.asarray(vertices)
    triangles, source = [], []
    for face in faces:
        rows = np.flatnonzero(np.isin(mesh.source_indices, face.triangle_indices))
        if isinstance(face.params, Plane):
            ids = list(np.unique(mesh.triangles[rows])) + extra[face.id]
            hull = _hull(vertices[ids], mesh.weld_tolerance * 2)
            for i in range(1, len(hull) - 1):
                triangles.append([ids[hull[0]], ids[hull[i]], ids[hull[i + 1]]])
                source.append(face.triangle_indices[0])
        else:
            triangles.extend(mesh.triangles[rows])
            source.extend(mesh.source_indices[rows])
    triangles = np.asarray(triangles, dtype=int)
    vectors = vertices[triangles]
    cross = np.cross(vectors[:, 1] - vectors[:, 0], vectors[:, 2] - vectors[:, 0])
    lengths = np.linalg.norm(cross, axis=1)
    if np.any(lengths <= mesh.weld_tolerance**2):
        raise ValueError("Virtual host support contains degenerate triangles")
    # Build incidence metadata for the support copy, retaining edge vertex IDs
    # used by the separate source graph. It is an open collection of patches.
    from .repair import MeshEdge

    incidence = defaultdict(list)
    for i, t in enumerate(triangles):
        for a, b in zip(t, np.roll(t, -1)):
            incidence[tuple(sorted((int(a), int(b))))].append(i)
    adjacency = [[] for _ in triangles]
    shared = []
    for edge, uses in incidence.items():
        if len(uses) == 2:
            a, b = uses
            adjacency[a].append(b)
            adjacency[b].append(a)
            shared.append(MeshEdge(edge, tuple(uses)))
    support = replace(
        mesh,
        vertices=vertices,
        triangles=triangles,
        source_indices=np.asarray(source),
        areas=lengths / 2,
        normals=cross / lengths[:, None],
        adjacency=tuple(tuple(sorted(row)) for row in adjacency),
        shared_edges=tuple(shared),
    )
    return replace(stripped, result=SegmentationResult(faces, graph, support))


def _secondary_features(items, frame, height):
    rotation, origin = frame[:3, :3], frame[:3, 3]
    local = lambda p: (np.asarray(p) - origin) @ rotation
    matrix = tuple(tuple(float(v) for v in row) for row in frame)
    counts = Counter()
    features = []
    for item in items:
        kind, face = item["kind"], item["curved"]
        counts[kind] += 1
        common = dict(
            id=f"{kind}_{counts[kind]}",
            kind=kind,
            part_frame=matrix,
            radius=face.params.radius,
            segments=face.params.segments,
            radial_reference=(
                tuple(np.asarray(face.params.radial_reference) @ rotation)
                if face.params.radial_reference is not None
                else None
            ),
        )
        if kind == "fillet":
            hosts = item["between"]
            normals = np.array([np.asarray(f.params.normal) @ rotation for f in hosts])[
                :, :2
            ]
            offsets = np.array(
                [f.params.offset - np.dot(f.params.normal, origin) for f in hosts]
            )
            corner = np.linalg.solve(normals, offsets)
            # Position is the cylinder-axis point at the section's lower cap.
            center = local(face.params.point)
            center[2] = 0
            features.append(
                Feature(
                    **common,
                    polarity="additive",
                    face_ids=(face.id,) + tuple(f.id for f in item.get("trims", ())),
                    trim_face_ids=tuple(f.id for f in item.get("trims", ())),
                    between=tuple(f.id for f in hosts),
                    height=height,
                    position=tuple(center),
                    corner=tuple(np.r_[corner, 0.0]),
                )
            )
        else:
            host, end = item["host"], item["end"]
            direction = (
                np.asarray(face.params.axis)
                if kind == "through_hole"
                else np.asarray(host.params.normal) * (1 if kind == "boss" else -1)
            )
            features.append(
                Feature(
                    **common,
                    polarity="additive" if kind == "boss" else "subtractive",
                    face_ids=(
                        (face.id,) if kind == "through_hole" else (face.id, end.id)
                    ),
                    on_face=host.id,
                    position=tuple(local(_axis_plane_point(face.params, host.params))),
                    axis=tuple(direction @ rotation),
                    rim_normals=(
                        tuple(
                            tuple(np.asarray(f.params.normal) @ rotation)
                            for f in (host, end)
                        )
                        if kind == "through_hole"
                        else ()
                    ),
                    **{"height" if kind == "boss" else "depth": item["length"]},
                )
            )
    return features


def _coalesce_arc_facets(profile, tolerance):
    """Absorb leftover facet lines only when they match an input arc polygon.

    Trimmed cylindrical faces can leave a few fitted facet planes at the cut.
    Keeping those as fixed lines would prevent a corner-radius edit moving the
    whole corner. This section-level proof preserves their source IDs too.
    """
    from .sections import arc_points

    segments = list(profile.segments)
    while True:
        for i, arc in enumerate(segments):
            if arc.kind != "arc":
                continue
            ring = arc_points(replace(arc, start_deg=arc.phase_deg, sweep_deg=360))
            a, b = ring[:-1], ring[1:]
            d = b - a
            denominator = np.sum(d * d, axis=1)
            direction = np.sign(arc.sweep_deg)
            for before in (True, False):
                j = (i + (-1 if before else 1)) % len(segments)
                line = segments[j]
                if line.kind != "line":
                    continue
                samples = np.array(
                    [line.start, line.end, (np.asarray(line.start) + line.end) / 2]
                )
                u = np.clip(
                    np.sum((samples[:, None] - a) * d, axis=2) / denominator, 0, 1
                )
                distance = (
                    np.linalg.norm(samples[:, None] - (a + u[:, :, None] * d), axis=2)
                    .min(axis=1)
                    .max()
                )
                if distance > tolerance:
                    continue
                point = np.asarray(line.start if before else line.end) - arc.center
                angle = float(np.degrees(np.arctan2(point[1], point[0])))
                delta = (
                    (direction * (arc.start_deg - angle))
                    if before
                    else direction * (angle - arc.start_deg - arc.sweep_deg)
                ) % 360
                if (
                    delta > 360 / arc.segments * 1.1
                    or abs(arc.sweep_deg) + delta > 360 + 1e-5
                ):
                    continue
                segments[i] = replace(
                    arc,
                    start=line.start if before else arc.start,
                    end=arc.end if before else line.end,
                    start_deg=(
                        arc.start_deg - direction * delta if before else arc.start_deg
                    ),
                    sweep_deg=arc.sweep_deg + direction * delta,
                    face_ids=tuple(sorted(set(arc.face_ids) | set(line.face_ids))),
                )
                segments.pop(j)
                break
            else:
                continue
            break
        else:
            break
    return replace(
        profile, segments=tuple(segments), points=tuple(edge.start for edge in segments)
    )


def compose_features(result: SegmentationResult) -> list[Feature]:
    """Recover slabs, replay removed features and close connected remainders."""
    if result.mesh is None:
        raise ValueError("Composition requires indexed segmentation support")
    stripped = defeature(result)
    fitted = stripped.result
    # Defeature already regularized every surviving face. Removed treatments
    # are fully described by its records, so do not repeat the expensive fit.
    # Reinsert their original provenance for complete source-area accounting;
    # their original params are never used to close unexplained regions.
    by_id = {face.id: face for face in fitted.faces}
    full_faces = [by_id.get(face.id, face) for face in result.faces]
    full_graph = result.graph.copy()
    for face in full_faces:
        full_graph.nodes[face.id]["face"] = face
    complete = replace(result, faces=full_faces, graph=full_graph)
    items = _secondary(fitted)
    secondary_ids = {
        item[key].id
        for item in items
        for key in ("curved", "end")
        if key in item and not (key == "end" and item["kind"] == "through_hole")
    }
    secondary_ids.update(f.id for item in items for f in item.get("trims", ()))
    rejected = dict(stripped.rejected)
    axis = np.asarray(stripped.axis)
    sine, cosine = np.sin(np.radians(0.5)), np.cos(np.radians(0.5))
    sides = {
        f.id
        for f in fitted.faces
        if f.id not in secondary_ids
        and f.id not in rejected
        and (
            (isinstance(f.params, Plane) and abs(np.dot(f.params.normal, axis)) <= sine)
            or (
                isinstance(f.params, Cylinder)
                and abs(np.dot(f.params.axis, axis)) >= cosine
            )
        )
    }
    # A faceted dome has a tiny flat polar cap. Parallel normal alone does not
    # make it an extrusion level: a body cap must meet a compatible side.
    faces = [
        f
        for f in fitted.faces
        if f.id in sides
        or (
            f.id not in secondary_ids
            and f.id not in rejected
            and isinstance(f.params, Plane)
            and abs(np.dot(f.params.normal, axis)) >= cosine
            and any(n in sides for n in fitted.graph[f.id])
        )
    ]
    body = replace(
        fitted, faces=faces, graph=fitted.graph.subgraph([f.id for f in faces]).copy()
    )
    old = None
    if not stripped.treatments and not stripped.rejected:
        try:
            old = _detect_existing(result)
            if abs(
                np.dot(np.asarray(old[0].part_frame)[:3, 2], axis)
            ) < cosine or Counter(f.kind for f in old[1:]) != Counter(
                item["kind"] for item in items
            ):
                old = None
        except ValueError:
            pass
    frame = np.asarray(old[0].part_frame) if old is not None else _frame_for(body, axis)
    # Both signs describe the same unoriented axis; the caller's frame gives
    # the slab height sign, and the largest cap anchors the origin.
    links = [t.hosts for t in stripped.treatments]
    for item in items:
        if item["kind"] == "fillet":
            links.append(tuple(f.id for f in item["between"]))
    for fid in rejected:
        face = next(f for f in complete.faces if f.id == fid)
        from .defeature import _host_pairs

        pairs = _host_pairs(complete, face, axis, sine, cosine, "convex")
        if len(pairs) != 1:
            raise ValueError(f"Rejected treatment {fid} has ambiguous hosts")
        links.append(tuple(f.id for f in pairs[0][:2]))
    virtual = _virtual_support(stripped, faces, links)
    slabs = slab_profiles(virtual, frame)
    matrix = tuple(tuple(float(v) for v in row) for row in frame)
    features = []
    for slab in slabs:
        loops = tuple(
            _coalesce_arc_facets(loop, complete.mesh.diagonal * 2e-5)
            for loop in slab.loops
        )
        primary = loops[0]
        if not primary.segments or all(s.kind == "line" for s in primary.segments):
            classified = classify_profile(
                profile_points(primary), complete.mesh.diagonal * 2e-5
            )
            primary = replace(
                primary, kind=classified.kind, dimensions=classified.dimensions
            )
        else:
            points = profile_points(primary)
            low = points.min(axis=0)
            width, height = np.ptp(points, axis=0)
            shifted = tuple(
                replace(
                    edge,
                    center=(
                        tuple(np.asarray(edge.center) - low)
                        if edge.center is not None
                        else None
                    ),
                    start=tuple(np.asarray(edge.start) - low),
                    end=tuple(np.asarray(edge.end) - low),
                )
                for edge in primary.segments
            )
            if _rounded_rectangle(
                shifted, width, height, complete.mesh.diagonal * 2e-5
            ):
                primary = replace(
                    primary,
                    kind="rounded_rectangle",
                    dimensions=(
                        ("width", float(width)),
                        ("height", float(height)),
                        ("plate_length", float(width)),
                        ("plate_width", float(height)),
                    ),
                )
        features.append(
            Feature(
                f"slab_{slab.index}",
                "slab",
                "additive",
                slab.face_ids,
                matrix,
                height=slab.top - slab.bottom,
                length=float(
                    np.ptp(
                        np.vstack([profile_points(loop) for loop in slab.loops]), axis=0
                    )[0]
                ),
                width=float(
                    np.ptp(
                        np.vstack([profile_points(loop) for loop in slab.loops]), axis=0
                    )[1]
                ),
                position=(0.0, 0.0, slab.bottom),
                profile=primary,
                loops=(primary,) + loops[1:],
            )
        )
    if old is not None:
        features.extend(old[1:])
    else:
        features.extend(
            _secondary_features(
                items, frame, max(s.top for s in slabs) - min(s.bottom for s in slabs)
            )
        )
    for treatment in stripped.treatments:
        features.append(
            Feature(
                treatment.id,
                treatment.kind,
                "subtractive",
                (treatment.face_id,),
                matrix,
                between=treatment.hosts,
                position=tuple(
                    (np.asarray(treatment.edge_point) - frame[:3, 3]) @ frame[:3, :3]
                ),
                axis=tuple(np.asarray(treatment.edge_direction) @ frame[:3, :3]),
                radius=treatment.size if treatment.kind == "edge_round" else None,
                width=treatment.size if treatment.kind == "chamfer" else None,
                segments=treatment.segments,
                radial_reference=(
                    tuple(np.asarray(treatment.radial_reference) @ frame[:3, :3])
                    if treatment.radial_reference is not None
                    else None
                ),
                rim_normals=tuple(
                    tuple(
                        np.asarray(
                            next(f for f in complete.faces if f.id == fid).params.normal
                        )
                        @ frame[:3, :3]
                    )
                    for fid in treatment.hosts
                ),
            )
        )
    explained = {fid for f in features for fid in f.face_ids}
    regions = remainder_regions(complete, explained, frame)
    for region in regions:
        reasons = {rejected[fid] for fid in region.face_ids if fid in rejected}
        features.append(
            replace(region, reason="; ".join(sorted(reasons))) if reasons else region
        )
    share = free_form_share(complete, regions)
    if share > FREE_FORM_LIMIT:
        raise ValueError(f"free-form share {100*share:.3g} % exceeds 10 %")
    return features
