"""Connected normal/curvature patches, robust primitive fits and region graph."""

from collections import defaultdict
from dataclasses import dataclass

import networkx as nx
import numpy as np
from stl.mesh import Mesh

from .fitting import cylinder_residuals, fit_cylinder, fit_plane
from .models import Cylinder, Face, SegmentationResult
from .repair import RepairedMesh, repair_mesh
from .coarse import extract_coarse, tessellation


@dataclass(frozen=True)
class SegmentationConfig:
    """Distances scale with mesh extent; angular thresholds are in degrees."""

    weld_relative: float = 1e-7
    plane_distance_relative: float = 2e-6
    plane_normal_deg: float = 0.25
    smooth_angle_deg: float = 20.0
    cylinder_distance_relative: float = 2e-5
    cylinder_normal_deg: float = 10.0
    tangent_angle_deg: float = 7.5
    ransac_iterations: int = 128


def _plane_patches(mesh: RepairedMesh, config: SegmentationConfig):
    """Grow against the seed plane, so small normal changes cannot drift."""
    pts = mesh.vertices[mesh.triangles]
    centers = pts.mean(axis=1)
    labels = np.full(len(pts), -1, dtype=int)
    patches = []
    cosine = np.cos(np.radians(config.plane_normal_deg))
    distance = mesh.diagonal * config.plane_distance_relative
    # Large facets supply numerically stable seed normals. A fan-triangulated
    # cap's tiny first triangle can otherwise split an exact float32 plane.
    for seed in sorted(range(len(pts)), key=lambda i: (-mesh.areas[i], i)):
        if labels[seed] >= 0:
            continue
        patch_id = len(patches)
        labels[seed] = patch_id
        stack, members = [seed], []
        while stack:
            i = stack.pop()
            members.append(i)
            for j in mesh.adjacency[i]:
                if labels[j] >= 0:
                    continue
                if (
                    mesh.normals[j] @ mesh.normals[seed] >= cosine
                    and np.max(np.abs((pts[j] - centers[seed]) @ mesh.normals[seed]))
                    <= distance
                ):
                    labels[j] = patch_id
                    stack.append(j)
        patches.append(np.array(sorted(members)))
    return patches, labels


def _smooth_components(mesh, patches, labels, config):
    """Nonzero, low-dihedral curvature connects facets into candidate surfaces.

    Tangent planes may join a strip here. RANSAC's all-vertices distance test
    excludes those planes rather than absorbing them into the cylinder.
    """
    graph = nx.Graph()
    cosine = np.cos(np.radians(config.smooth_angle_deg))
    for edge in mesh.shared_edges:
        i, j = edge.triangles
        a, b = int(labels[i]), int(labels[j])
        if a != b and mesh.normals[i] @ mesh.normals[j] >= cosine:
            graph.add_edge(a, b)
    return [sorted(c) for c in nx.connected_components(graph) if len(c) >= 4]


def _cylinder_support(model, points, normals, config, tolerance):
    residual = cylinder_residuals(model, points).max(axis=1)
    delta = points.mean(axis=1) - model.point
    radial = delta - (delta @ model.axis)[:, None] * np.asarray(model.axis)
    radial /= np.maximum(
        np.linalg.norm(radial, axis=1, keepdims=True), np.finfo(float).tiny
    )
    normal_alignment = np.abs(np.einsum("ij,ij->i", normals, radial))
    return (
        (residual <= tolerance)
        & (np.abs(normals @ model.axis) <= np.sin(np.radians(config.plane_normal_deg)))
        & (normal_alignment >= np.cos(np.radians(config.cylinder_normal_deg)))
    )


def _extract_cylinders(mesh, patches, labels, config):
    points = mesh.vertices[mesh.triangles]
    rng = np.random.default_rng(0)
    recovered = []
    for component in _smooth_components(mesh, patches, labels, config):
        remaining = component
        while len(remaining) >= 4:
            triangle_ids = np.concatenate([patches[p] for p in remaining])
            local_points, local_normals = (
                points[triangle_ids],
                mesh.normals[triangle_ids],
            )
            patch_ranges = []
            start = 0
            for p in remaining:
                patch_ranges.append(slice(start, start + len(patches[p])))
                start += len(patches[p])
            tolerance = config.cylinder_distance_relative * mesh.diagonal
            best_support = []
            # Sample patches equally, not triangles or area: a large tangent
            # plane must not overwhelm the small facets of a fillet strip.
            for _ in range(config.ransac_iterations):
                sample_patches = rng.choice(len(remaining), 3, replace=False)
                sample = np.concatenate([patches[remaining[i]] for i in sample_patches])
                try:
                    model = fit_cylinder(
                        points[sample].reshape(-1, 3), mesh.normals[sample]
                    )
                except (ValueError, np.linalg.LinAlgError):
                    continue
                inliers = _cylinder_support(
                    model, local_points, local_normals, config, tolerance
                )
                support = [
                    i
                    for i, section in enumerate(patch_ranges)
                    if inliers[section].all()
                ]
                if len(support) > len(best_support):
                    best_support = support
                    if len(support) == len(remaining):
                        break
            if len(best_support) < 4:
                break
            support_patches = {remaining[i] for i in best_support}
            # Keep disconnected co-cylindrical regions as separate faces.
            support_graph = nx.Graph()
            support_graph.add_nodes_from(support_patches)
            for edge in mesh.shared_edges:
                a, b = (int(labels[i]) for i in edge.triangles)
                if a != b and a in support_patches and b in support_patches:
                    support_graph.add_edge(a, b)
            accepted = set()
            for connected in nx.connected_components(support_graph):
                if len(connected) < 4:
                    continue
                members = np.sort(
                    np.concatenate([patches[p] for p in sorted(connected)])
                )
                model = fit_cylinder(
                    points[members].reshape(-1, 3), mesh.normals[members]
                )
                if not _cylinder_support(
                    model, points[members], mesh.normals[members], config, tolerance
                ).all():
                    continue
                delta = points[members].mean(axis=1) - model.point
                radial = delta - (delta @ model.axis)[:, None] * np.asarray(model.axis)
                polarity = np.sum(
                    mesh.areas[members]
                    * np.einsum("ij,ij->i", radial, mesh.normals[members])
                )
                recovered.append(
                    (members, model, "convex" if polarity > 0 else "concave")
                )
                accepted.update(connected)
            if not accepted:
                break
            remaining = [p for p in remaining if p not in accepted]
    return recovered


def _region_graph(mesh, faces, owner, config):
    graph = nx.Graph()
    graph.add_nodes_from((face.id, {"face": face}) for face in faces)
    boundaries = defaultdict(list)
    analytic_tangent = defaultdict(list)
    for edge in mesh.shared_edges:
        i, j = edge.triangles
        a, b = int(owner[i]), int(owner[j])
        if a == b:
            continue
        p, q = mesh.vertices[list(edge.vertices)]
        direction = q - p
        length = float(np.linalg.norm(direction))
        direction /= length
        # The edge direction follows triangle i's outward winding. Positive
        # normal turn is convex, negative is concave, independently of frame.
        sine = np.cross(mesh.normals[i], mesh.normals[j]) @ direction
        cosine = mesh.normals[i] @ mesh.normals[j]
        angle = float(np.degrees(np.arctan2(sine, cosine)))
        boundaries[tuple(sorted((a, b)))].append((edge, angle, length))
        fitted_normals = []
        for owner_id in (a, b):
            face = faces[owner_id]
            if isinstance(face.params, Cylinder):
                radial = (p + q) / 2 - face.params.point
                radial -= np.dot(radial, face.params.axis) * np.asarray(
                    face.params.axis
                )
                fitted_normals.append(
                    radial
                    / np.linalg.norm(radial)
                    * (1 if face.convexity == "convex" else -1)
                )
            else:
                fitted_normals.append(np.asarray(face.params.normal))
        analytic_tangent[tuple(sorted((a, b)))].append(
            any(isinstance(faces[k].params, Cylinder) for k in (a, b))
            and np.dot(*fitted_normals) > np.cos(np.radians(config.plane_normal_deg))
        )
    for (a, b), evidence in sorted(boundaries.items()):
        angles = np.array([angle for _, angle, _ in evidence])
        lengths = np.array([length for _, _, length in evidence])
        signed = float(np.average(angles, weights=lengths))
        if (
            all(analytic_tangent[(a, b)])
            or np.max(np.abs(angles)) <= config.tangent_angle_deg
        ):
            convexity = "tangent"
        else:
            convexity = "convex" if signed > 0 else "concave"
        graph.add_edge(
            faces[a].id,
            faces[b].id,
            convexity=convexity,
            signed_dihedral_deg=signed,
            dihedral_angles_deg=tuple(angles.tolist()),
            mesh_edges=tuple(edge.vertices for edge, _, _ in evidence),
            triangle_pairs=tuple(
                tuple(int(mesh.source_indices[i]) for i in edge.triangles)
                for edge, _, _ in evidence
            ),
        )
    return nx.freeze(graph)


def segment_mesh(
    mesh: Mesh, *, config: SegmentationConfig | None = None
) -> SegmentationResult:
    """Recover connected analytic faces and their signed-dihedral adjacencies.

    IDs are ordered by the first original triangle in each face. Unsupported
    curved surfaces remain coplanar facet patches; no geometry is discarded.
    """
    config = config or SegmentationConfig()
    repaired = repair_mesh(mesh, weld_relative=config.weld_relative)
    patches, labels = _plane_patches(repaired, config)
    cylinders = _extract_cylinders(repaired, patches, labels, config)
    cylinders = [
        (
            members,
            tessellation(
                model,
                repaired.vertices[repaired.triangles[members]],
                repaired.diagonal * config.cylinder_distance_relative,
            ),
            convexity,
        )
        for members, model, convexity in cylinders
    ]
    claimed = set(int(i) for members, _, _ in cylinders for i in members)
    cylinders += extract_coarse(repaired, patches, labels, claimed, config)
    regions = list(cylinders)
    for patch in patches:
        if int(patch[0]) in claimed:
            continue
        points = repaired.vertices[repaired.triangles[patch]].reshape(-1, 3)
        plane = fit_plane(points, repaired.normals[patch] * repaired.areas[patch, None])
        regions.append((patch, plane, None))
    regions.sort(key=lambda region: int(repaired.source_indices[region[0]].min()))
    faces, owner = [], np.full(len(repaired.triangles), -1, dtype=int)
    for index, (members, params, convexity) in enumerate(regions):
        owner[members] = index
        faces.append(
            Face(
                f"F{index}",
                "cylinder" if isinstance(params, Cylinder) else "plane",
                tuple(sorted(int(i) for i in repaired.source_indices[members])),
                params,
                convexity,
            )
        )
    return SegmentationResult(
        faces, _region_graph(repaired, faces, owner, config), repaired
    )
