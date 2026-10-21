"""Close connected unexplained surface patches against their fitted hosts.

The triangles are a fixed world-space region, not a parametric fit. Surface
share uses only original source triangles, never the artificial closure.
"""

from collections import Counter

import networkx as nx
import numpy as np

from .features import Feature
from .models import Plane, SegmentationResult

FREE_FORM_LIMIT = 0.10


def _triangulate(points, tolerance):
    """Ear-clip one simple planar ring, including concave boundaries."""
    points = np.asarray(points)
    center = points.mean(axis=0)
    _, _, basis = np.linalg.svd(points - center, full_matrices=False)
    p = (points - center) @ basis[:2].T
    cross = lambda a, b: a[0] * b[1] - a[1] * b[0]
    area = sum(cross(a, b) for a, b in zip(p, np.roll(p, -1, axis=0)))
    if abs(area) <= tolerance * tolerance:
        return []
    order = list(range(len(p)))
    sign = 1 if area > 0 else -1
    triangles = []
    while len(order) > 3:
        for i, b in enumerate(order):
            a, c = order[i - 1], order[(i + 1) % len(order)]
            turn = sign * cross(p[b] - p[a], p[c] - p[b])
            if abs(turn) <= tolerance * tolerance:
                order.pop(i)
                break
            if turn < 0:
                continue
            if any(
                all(
                    sign * cross(y - x, p[j] - x) >= -tolerance * tolerance
                    for x, y in [(p[a], p[b]), (p[b], p[c]), (p[c], p[a])]
                )
                for j in order
                if j not in (a, b, c)
            ):
                continue
            triangles.append([points[a], points[b], points[c]])
            order.pop(i)
            break
        else:
            raise ValueError("Remainder closure ring is not a simple polygon")
    if len(order) == 3:
        triangles.append(points[order].tolist())
    return triangles


def _boundary(triangles):
    counts = Counter(
        tuple(sorted((int(a), int(b))))
        for t in triangles
        for a, b in zip(t, np.roll(t, -1))
    )
    edges = [
        (int(a), int(b))
        for t in triangles
        for a, b in zip(t, np.roll(t, -1))
        if counts[tuple(sorted((int(a), int(b))))] == 1
    ]
    following = {}
    for a, b in edges:
        if a in following:
            raise ValueError("Branched remainder boundary")
        following[a] = b
    if set(following) != set(following.values()):
        raise ValueError("Open remainder boundary")
    loops = []
    while following:
        seed = min(following)
        loop, current = [], seed
        while True:
            loop.append(current)
            current = following.pop(current)
            if current == seed:
                break
            if current not in following:
                raise ValueError("Remainder boundary is not a simple loop")
        loops.append(loop)
    return loops


def _close(result, ids, explained):
    mesh = result.mesh
    source = {t for f in result.faces if f.id in ids for t in f.triangle_indices}
    rows = np.flatnonzero(np.isin(mesh.source_indices, list(source)))
    triangles = mesh.triangles[rows]
    boundary = _boundary(triangles)
    if not boundary:
        raise ValueError("Unexplained closed component has no planar host")
    neighbors = {n for fid in ids for n in result.graph[fid] if n in explained}
    average = np.sum(mesh.normals[rows] * mesh.areas[rows, None], axis=0)
    if np.linalg.norm(average) <= mesh.diagonal**2 * 1e-12:
        raise ValueError("Remainder has no consistent material direction")
    average /= np.linalg.norm(average)
    hosts = [
        f
        for f in result.faces
        if f.id in neighbors
        and isinstance(f.params, Plane)
        and np.dot(f.params.normal, average) > 1e-3
    ]
    if not hosts:
        raise ValueError("Remainder has no explained planar host")
    # Co-planar host regions contribute one constraint, not a rank increase.
    selected = []
    tolerance = mesh.diagonal * 2e-5
    for face in sorted(hosts, key=lambda f: f.id):
        if not any(
            np.dot(face.params.normal, f.params.normal) > 1 - 1e-8
            and abs(face.params.offset - f.params.offset) < tolerance
            for f in selected
        ):
            selected.append(face)
    normals = np.array([f.params.normal for f in selected])
    offsets = np.array([f.params.offset for f in selected])
    rank = np.linalg.matrix_rank(normals, tol=1e-8)
    if len(selected) != rank:
        raise ValueError("Remainder hosts do not define a unique support intersection")
    points = mesh.vertices[triangles].reshape(-1, 3)
    signed = (points @ normals.T - offsets).mean(axis=0)
    if np.any(signed > tolerance) and np.any(signed < -tolerance):
        raise ValueError("Remainder crosses its extended host planes")
    polarity = "additive" if signed.max() > tolerance else "subtractive"
    if np.max(abs(signed)) <= tolerance:
        raise ValueError("Remainder is indistinguishable from its host")
    inverse = np.linalg.pinv(normals)
    epsilon = mesh.diagonal * 1e-6
    # Additive closure enters material; subtractive closure extends outside
    # the hosts so the cutter never leaves coincident slivers on their edges.
    target = offsets + (-epsilon if polarity == "additive" else epsilon)
    out = mesh.vertices[triangles].copy()
    if polarity == "subtractive":
        out = out[:, ::-1]
    patches = list(out)
    for loop in boundary:
        original = mesh.vertices[loop]
        projected = original - (original @ normals.T - target) @ inverse.T
        if polarity == "subtractive":
            original = original[::-1]
            projected = projected[::-1]
        for a, b, qa, qb in zip(
            original,
            np.roll(original, -1, axis=0),
            projected,
            np.roll(projected, -1, axis=0),
        ):
            patches.extend(([b, a, qa], [b, qa, qb]))
        if rank == 1:
            # Original patch boundary follows its outward winding; the cap
            # must oppose it on the projected rim.
            patches.extend(_triangulate(projected[::-1], mesh.weld_tolerance))
    vectors = np.asarray(patches, dtype=float)
    keep = (
        np.linalg.norm(
            np.cross(vectors[:, 1] - vectors[:, 0], vectors[:, 2] - vectors[:, 0]),
            axis=1,
        )
        > mesh.weld_tolerance**2
    )
    vectors = vectors[keep]
    # A projected line collapses two boundary vertices. Weld before checking
    # manifoldness, keeping closure topology independent of triangulation.
    from .repair import _weld

    vertices, labels = _weld(vectors.reshape(-1, 3), mesh.weld_tolerance)
    triangles = labels.reshape(-1, 3)
    triangles = triangles[np.array([len(set(t)) == 3 for t in triangles])]
    incidence = {}
    for triangle in triangles:
        for a, b in zip(triangle, np.roll(triangle, -1)):
            incidence.setdefault(tuple(sorted((int(a), int(b)))), []).append(
                (int(a), int(b))
            )
    if any(len(uses) != 2 for uses in incidence.values()):
        raise ValueError("Remainder closure is not watertight")
    if any(first != second[::-1] for first, second in incidence.values()):
        raise ValueError("Remainder closure has inconsistent winding")
    vectors = vertices[triangles]
    relative = vectors - vertices.mean(axis=0)
    volume = (
        np.einsum(
            "ij,ij->i", relative[:, 0], np.cross(relative[:, 1], relative[:, 2])
        ).sum()
        / 6
    )
    if abs(volume) <= mesh.weld_tolerance**3:
        raise ValueError("Remainder closure has zero volume")
    if volume < 0:
        vectors = vectors[:, ::-1]
    return polarity, vectors


def remainder_regions(
    result: SegmentationResult, explained: set[str], frame
) -> list[Feature]:
    """Return closed solids for connected unexplained source-face regions."""
    unexplained = {f.id for f in result.faces} - set(explained)
    if not unexplained:
        return []
    if result.mesh is None:
        raise ValueError("Remainder closure requires indexed mesh support")
    matrix = tuple(tuple(float(v) for v in row) for row in np.asarray(frame))
    regions = []
    for ids in sorted(
        nx.connected_components(result.graph.subgraph(unexplained)),
        key=lambda group: min(group),
    ):
        polarity, triangles = _close(result, ids, set(explained))
        regions.append(
            Feature(
                f"remainder_{len(regions)+1}",
                "remainder",
                polarity,
                tuple(sorted(ids)),
                matrix,
                remainder_triangles=tuple(
                    tuple(tuple(float(v) for v in point) for point in t)
                    for t in triangles
                ),
                reason="unmodeled surface",
            )
        )
    return regions


def free_form_share(result: SegmentationResult, regions) -> float:
    """Original area fraction, deduplicated by source triangle provenance."""
    ids = {fid for region in regions for fid in region.face_ids}
    if not ids:
        return 0.0
    if result.mesh is None:
        raise ValueError("Surface area requires indexed mesh support")
    source = {
        i for face in result.faces if face.id in ids for i in face.triangle_indices
    }
    return float(
        result.mesh.areas[np.isin(result.mesh.source_indices, list(source))].sum()
        / result.mesh.areas.sum()
    )
