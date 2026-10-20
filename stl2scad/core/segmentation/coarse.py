"""Coarse cylindrical strips: common-axis creases and regular polygon chords.

No smooth-angle cutoff is used here. A candidate consists of at least two
extruded facets with a common crease direction. Circumcircles are seeded by
three projected vertices, and verified by a shared regular-polygon chord
angle, radius and phase. Four-sided prisms remain planar (ambiguous boxes).
"""

from dataclasses import replace

import networkx as nx
import numpy as np

from .fitting import cylinder_residuals, fit_cylinder


def _unique(points, tolerance):
    result = []
    for p in points:
        if (
            not result
            or np.linalg.norm(np.asarray(result) - p, axis=1).min() > tolerance
        ):
            result.append(p)
    return np.asarray(result)


def tessellation(model, points, tolerance):
    """Infer full-circle segment count and one true polygon vertex direction."""
    points = np.asarray(points).reshape(-1, 3)
    points = points[cylinder_residuals(model, points) <= tolerance]
    if len(points) < 3:
        return model
    radial = points - model.point
    radial -= (radial @ model.axis)[:, None] * np.asarray(model.axis)
    radial = _unique(radial, tolerance)
    if len(radial) < 3:
        return model
    u = radial[0] / np.linalg.norm(radial[0])
    v = np.cross(model.axis, u)
    angles = np.sort(np.mod(np.arctan2(radial @ v, radial @ u), 2 * np.pi))
    gaps = np.diff(np.r_[angles, angles[0] + 2 * np.pi])
    step = np.median(np.sort(gaps)[: len(gaps) - 1])
    n = int(round(2 * np.pi / step))
    if n < 5 or n > 4096:
        return model
    step = 2 * np.pi / n
    if np.max(np.abs(gaps / step - np.round(gaps / step))) > max(
        1e-3, 4 * tolerance / model.radius / step
    ):
        return model
    return replace(model, segments=n, radial_reference=tuple(u))


def extract_coarse(mesh, patches, labels, claimed, config):
    tolerance = mesh.diagonal * config.cylinder_distance_relative
    points = mesh.vertices[mesh.triangles]
    normals = np.array([mesh.normals[p[0]] for p in patches])
    available = {
        i for i, p in enumerate(patches) if len(p) >= 2 and int(p[0]) not in claimed
    }
    groups = []
    seen = set()
    for edge in mesh.shared_edges:
        a, b = (int(labels[i]) for i in edge.triangles)
        pair = tuple(sorted((a, b)))
        if a == b or a not in available or b not in available or pair in seen:
            continue
        seen.add(pair)
        direction = np.cross(normals[a], normals[b])
        if np.linalg.norm(direction) < np.sin(np.radians(config.plane_normal_deg)):
            continue
        direction /= np.linalg.norm(direction)
        group = next(
            (
                g
                for g in groups
                if abs(g[0] @ direction) > np.cos(np.radians(config.plane_normal_deg))
            ),
            None,
        )
        if group is None:
            group = (direction, nx.Graph())
            groups.append(group)
        group[1].add_edge(a, b)
    recovered = []
    for axis, graph in groups:
        # An extruded facet projects to one line segment, not a general triangle.
        projected = {}
        for p in list(graph.nodes):
            if p not in available:
                graph.remove_node(p)
                continue
            vertices = points[patches[p]].reshape(-1, 3)
            vertices = vertices - (vertices @ axis)[:, None] * axis
            unique = _unique(vertices, tolerance)
            if len(unique) != 2:
                graph.remove_node(p)
            else:
                projected[p] = unique
        for component in list(nx.connected_components(graph)):
            remaining = set(component)
            while len(remaining) >= 2:
                best = None
                for a, b in graph.subgraph(remaining).edges:
                    sample = _unique(
                        np.concatenate((projected[a], projected[b])), tolerance
                    )
                    if len(sample) != 3:
                        continue
                    try:
                        model = fit_cylinder(
                            sample,
                            np.array([normals[a], normals[b], normals[a], normals[b]]),
                        )
                    except (ValueError, np.linalg.LinAlgError):
                        continue
                    votes = {}
                    for p in remaining:
                        vertices = points[patches[p]].reshape(-1, 3)
                        delta = vertices - model.point
                        radial = delta - (delta @ model.axis)[:, None] * np.asarray(
                            model.axis
                        )
                        radii = np.linalg.norm(radial, axis=1)
                        chord = abs(
                            float((vertices.mean(axis=0) - model.point) @ normals[p])
                        )
                        if (
                            radii.max() > model.radius + tolerance
                            or np.min(abs(radii - model.radius)) > tolerance
                            or chord / model.radius >= 1
                            or chord / model.radius
                            < np.cos(np.pi / 5) - tolerance / model.radius
                        ):
                            continue
                        n = int(round(np.pi / np.arccos(chord / model.radius)))
                        if (
                            n < 5
                            or n > 4096
                            or abs(chord - model.radius * np.cos(np.pi / n)) > tolerance
                        ):
                            continue
                        votes.setdefault(n, set()).add(p)
                    for n, support in votes.items():
                        for connected in nx.connected_components(
                            graph.subgraph(support)
                        ):
                            if len(connected) < 2:
                                continue
                            step = 2 * np.pi / n
                            if any(
                                abs(
                                    np.arccos(np.clip(normals[i] @ normals[j], -1, 1))
                                    - step
                                )
                                > max(0.001, 4 * tolerance / model.radius)
                                for i, j in graph.subgraph(connected).edges
                            ):
                                continue
                            if best is None or len(connected) > len(best[0]):
                                best = (set(connected), model)
                if best is None:
                    break
                support, model = best
                members = np.sort(np.concatenate([patches[p] for p in sorted(support)]))
                vertices = points[members].reshape(-1, 3)
                on_circle = cylinder_residuals(model, vertices) <= tolerance
                try:
                    model = fit_cylinder(vertices[on_circle], mesh.normals[members])
                except (ValueError, np.linalg.LinAlgError):
                    break
                model = tessellation(model, vertices, tolerance)
                if model.segments is None:
                    break
                radial = points[members].mean(axis=1) - model.point
                radial -= (radial @ model.axis)[:, None] * np.asarray(model.axis)
                polarity = np.sum(
                    mesh.areas[members]
                    * np.einsum("ij,ij->i", radial, mesh.normals[members])
                )
                recovered.append(
                    (members, model, "convex" if polarity > 0 else "concave")
                )
                claimed.update(int(i) for i in members)
                available.difference_update(support)
                remaining.difference_update(support)
    return recovered
