"""Scale-relative welding, winding repair and indexed triangle adjacency."""

from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import product

import numpy as np
from stl.mesh import Mesh


@dataclass(frozen=True)
class MeshEdge:
    vertices: tuple[int, int]  # Directed along the first triangle's winding.
    triangles: tuple[int, int]


@dataclass(frozen=True)
class RepairedMesh:
    vertices: np.ndarray
    triangles: np.ndarray
    source_indices: np.ndarray
    normals: np.ndarray
    areas: np.ndarray
    adjacency: tuple[tuple[int, ...], ...]
    shared_edges: tuple[MeshEdge, ...]
    diagonal: float
    weld_tolerance: float


def _weld(points: np.ndarray, tolerance: float):
    """Union nearby vertices, including pairs across spatial hash cell borders."""
    unique, inverse = np.unique(points, axis=0, return_inverse=True)
    parents = np.arange(len(unique))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    cells = defaultdict(list)
    origin = unique.min(axis=0)
    for i, point in enumerate(unique):
        cell = tuple(np.floor((point - origin) / tolerance).astype(np.int64))
        for step in product((-1, 0, 1), repeat=3):
            neighbor = tuple(a + b for a, b in zip(cell, step))
            for j in cells.get(neighbor, ()):
                if np.linalg.norm(point - unique[j]) <= tolerance:
                    a, b = root(i), root(j)
                    parents[max(a, b)] = min(a, b)
        cells[cell].append(i)
    roots = np.array([root(i) for i in range(len(unique))])
    _, labels = np.unique(roots, return_inverse=True)
    counts = np.bincount(labels)
    vertices = np.column_stack(
        [np.bincount(labels, weights=unique[:, k]) / counts for k in range(3)]
    )
    return vertices, labels[inverse]


def _incidences(triangles):
    edges = defaultdict(list)
    for i, triangle in enumerate(triangles):
        for a, b in zip(triangle, np.roll(triangle, -1)):
            edges[tuple(sorted((int(a), int(b))))].append((i, int(a), int(b)))
    if any(len(uses) > 2 for uses in edges.values()):
        raise ValueError(
            "Segmentation requires manifold edges (at most two incident triangles)"
        )
    return edges


def repair_mesh(mesh: Mesh, *, weld_relative: float = 1e-7) -> RepairedMesh:
    """Keep source triangle IDs while discarding weld-collapsed/duplicate facets.

    Consistent winding is propagated across shared edges. Closed connected shells
    are oriented to positive volume; open patches retain their seed orientation.
    This repairs winding, not holes, self-intersections or nested cavity shells.
    """
    vectors = np.array(mesh.vectors, dtype=np.float64, copy=True)
    if not len(vectors) or not np.isfinite(vectors).all():
        raise ValueError("Mesh must contain finite triangles")
    diagonal = float(np.linalg.norm(np.ptp(vectors.reshape(-1, 3), axis=0)))
    if diagonal <= 0 or not np.isfinite(weld_relative) or weld_relative <= 0:
        raise ValueError("Mesh extent and weld tolerance must be positive")
    tolerance = diagonal * weld_relative
    vertices, indices = _weld(vectors.reshape(-1, 3), tolerance)
    triangles = indices.reshape(-1, 3)
    cross = np.cross(
        vertices[triangles[:, 1]] - vertices[triangles[:, 0]],
        vertices[triangles[:, 2]] - vertices[triangles[:, 0]],
    )
    valid = np.linalg.norm(cross, axis=1) > tolerance**2
    source = np.flatnonzero(valid)
    triangles = triangles[valid]
    _, first = np.unique(np.sort(triangles, axis=1), axis=0, return_index=True)
    first.sort()
    triangles, source = triangles[first], source[first]
    if not len(triangles):
        raise ValueError("Mesh has no nondegenerate triangles after welding")

    incidences = _incidences(triangles)
    neighbors = [[] for _ in triangles]
    boundary = set()
    for uses in incidences.values():
        if len(uses) == 1:
            boundary.add(uses[0][0])
            continue
        (i, a, b), (j, c, d) = uses
        same_direction = a == c and b == d
        neighbors[i].append((j, same_direction))
        neighbors[j].append((i, same_direction))
    flips = {}
    for seed in range(len(triangles)):
        if seed in flips:
            continue
        flips[seed] = False
        queue, component = deque([seed]), []
        while queue:
            i = queue.popleft()
            component.append(i)
            for j, same in neighbors[i]:
                flip = flips[i] ^ same
                if j in flips:
                    if flips[j] != flip:
                        raise ValueError("Mesh winding is not orientable")
                else:
                    flips[j] = flip
                    queue.append(j)
        for i in component:
            if flips[i]:
                triangles[i] = triangles[i, ::-1]
        if not boundary.intersection(component):
            pts = vertices[triangles[component]]
            # Center before volume evaluation to avoid cancellation far from origin.
            pts = pts - pts.mean(axis=(0, 1))
            volume6 = np.einsum(
                "ij,ij->i", pts[:, 0], np.cross(pts[:, 1], pts[:, 2])
            ).sum()
            if volume6 < 0:
                triangles[component] = triangles[component, ::-1]

    shared = []
    for uses in _incidences(triangles).values():
        if len(uses) == 2:
            (i, a, b), (j, _, _) = uses
            shared.append(MeshEdge((a, b), (i, j)))
    pts = vertices[triangles]
    cross = np.cross(pts[:, 1] - pts[:, 0], pts[:, 2] - pts[:, 0])
    twice_area = np.linalg.norm(cross, axis=1)
    normals, areas = cross / twice_area[:, None], twice_area / 2
    for array in (vertices, triangles, source, normals, areas):
        array.setflags(write=False)
    return RepairedMesh(
        vertices,
        triangles,
        source,
        normals,
        areas,
        tuple(tuple(sorted(j for j, _ in row)) for row in neighbors),
        tuple(shared),
        diagonal,
        tolerance,
    )
