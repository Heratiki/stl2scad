"""Constrain fitted directions without changing mesh or region provenance.

This module is opt-in: detection continues to use the original segmentation
unless a caller explicitly passes a regularized result.
"""

from dataclasses import replace as _replace

import numpy as np

from .models import Plane, SegmentationResult
from .fitting import cylinder_residuals as _cylinder_residuals

__all__ = ["regularize", "extrusion_axis"]


def _unit(direction):
    direction = np.asarray(direction, dtype=np.float64)
    norm = np.linalg.norm(direction)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("Surface directions must be finite and nonzero")
    return direction / norm


def _supports(result):
    if result.mesh is None:
        raise ValueError("Direction regularization requires indexed mesh support")
    source_to_local = {
        int(source): i for i, source in enumerate(result.mesh.source_indices)
    }
    supports = []
    for face in result.faces:
        try:
            indices = np.array(
                [source_to_local[source] for source in face.triangle_indices], dtype=int
            )
        except KeyError as exc:
            raise ValueError(
                f"Face {face.id} has unknown source triangle {exc.args[0]}"
            ) from exc
        if not len(indices):
            raise ValueError(f"Face {face.id} has no triangle support")
        supports.append(indices)
    return supports


def _clusters(directions, weights, ids, max_deg):
    """Area-first complete-link clusters avoid a chain swallowing real drafts.

    Antipodal directions represent one line; align their signs before averaging.
    Every pair in a cluster must be within the angular tolerance, so a sequence
    of small deviations cannot join two genuinely distinct end directions.
    """
    sine = np.sin(np.radians(max_deg))
    groups = []
    for i in sorted(range(len(directions)), key=lambda i: (-weights[i], ids[i])):
        for members in groups:
            if all(
                np.linalg.norm(np.cross(directions[i], directions[j])) <= sine + 1e-15
                for j in members
            ):
                members.append(i)
                break
        else:
            groups.append([i])
    means = []
    totals = []
    for members in groups:
        anchor = directions[members[0]]
        aligned = [
            directions[i] * (1 if directions[i] @ anchor >= 0 else -1) for i in members
        ]
        means.append(
            _unit(np.sum(np.asarray(aligned) * weights[members, None], axis=0))
        )
        totals.append(float(weights[members].sum()))
    order = sorted(
        range(len(groups)), key=lambda i: (-totals[i], min(ids[j] for j in groups[i]))
    )
    return [groups[i] for i in order], np.asarray([means[i] for i in order])


def _orthogonalize(means, max_deg):
    corrected = means.copy()
    selected = []
    sine = np.sin(np.radians(max_deg))
    for i, direction in enumerate(means):
        if all(abs(direction @ means[j]) <= sine + 1e-15 for j in selected):
            orthogonal = direction.copy()
            # Two passes reduce cancellation when three constraints are used.
            for _ in range(2):
                for j in selected:
                    orthogonal -= (orthogonal @ corrected[j]) * corrected[j]
            corrected[i] = _unit(orthogonal)
            selected.append(i)
            if len(selected) == 3:
                break
    return corrected


def _fixed_axis_cylinder(points, axis, previous, tolerance):
    # A trimmed coarse facet can contain chord-interior intersection vertices.
    # They are not samples of the circumcircle. Retain the original fit's
    # radial inliers when they provide a majority and a non-collinear section.
    inliers = points[_cylinder_residuals(previous, points) <= tolerance]
    if len(inliers) >= max(3, len(points) / 2):
        radial = inliers - previous.point
        radial -= (radial @ previous.axis)[:, None] * np.asarray(previous.axis)
        spread = np.linalg.svd(radial - radial.mean(axis=0), compute_uv=False)
        if spread[1] > tolerance:
            points = inliers
    if previous.radial_reference is None:
        u = _unit(np.cross(axis, np.eye(3)[np.argmin(abs(axis))]))
        reference = None
    else:
        radial = np.asarray(previous.radial_reference)
        u = _unit(radial - (radial @ axis) * axis)
        reference = tuple(u)
    basis = np.column_stack((u, np.cross(axis, u)))
    origin = points.mean(axis=0)
    xy = (points - origin) @ basis
    design = np.column_stack((2 * xy, np.ones(len(xy))))
    solution, _, rank, _ = np.linalg.lstsq(design, np.sum(xy**2, axis=1), rcond=None)
    if rank < 3:
        raise ValueError("Cylinder support has a degenerate cross section")
    radius2 = solution[2] + solution[:2] @ solution[:2]
    if radius2 <= 0:
        raise ValueError("Cylinder radius must be positive")
    point = origin + basis @ solution[:2]
    point -= axis * (point @ axis)
    return _replace(
        previous,
        axis=tuple(axis),
        point=tuple(point),
        radius=float(np.sqrt(radius2)),
        radial_reference=reference,
    )


def regularize(
    result: SegmentationResult, *, max_deg: float = 0.5
) -> SegmentationResult:
    """Area-average near-parallel fitted directions and constrain dominant axes.

    Plane offsets minimize squared vertex distances with the corrected normal;
    cylinder circumcircles are re-fitted to vertices with the corrected axis
    held fixed. Outward plane signs, curved convexity, segment counts and phase
    references are retained. The existing graph (including its original face
    snapshots), indexed mesh and source triangle tuples are not mutated.
    """
    if not np.isfinite(max_deg) or not 0 <= max_deg < 90:
        raise ValueError("max_deg must be finite and between 0 (inclusive) and 90")
    if not result.faces:
        return _replace(result, faces=[])
    supports = _supports(result)
    weights = np.array([result.mesh.areas[indices].sum() for indices in supports])
    directions = np.array(
        [
            _unit(f.params.normal if isinstance(f.params, Plane) else f.params.axis)
            for f in result.faces
        ]
    )
    groups, means = _clusters(
        directions, weights, [f.id for f in result.faces], max_deg
    )
    means = _orthogonalize(means, max_deg)
    fitted = [None] * len(result.faces)
    for members, mean in zip(groups, means):
        for i in members:
            face = result.faces[i]
            direction = mean * (1 if mean @ directions[i] >= 0 else -1)
            points = result.mesh.vertices[result.mesh.triangles[supports[i]]].reshape(
                -1, 3
            )
            if isinstance(face.params, Plane):
                params = Plane(tuple(direction), tuple(points.mean(axis=0)))
            else:
                params = _fixed_axis_cylinder(
                    points, direction, face.params, result.mesh.diagonal * 2e-5
                )
            fitted[i] = _replace(face, params=params)
    return _replace(result, faces=fitted)


def _full_circle(result, face, support):
    """A closed polygon ring has no gap larger than one tessellation step."""
    model, mesh = face.params, result.mesh
    points = mesh.vertices[np.unique(mesh.triangles[support])]
    points = points[_cylinder_residuals(model, points) <= mesh.diagonal * 2e-5]
    if len(points) < 3:
        return False
    axis = _unit(model.axis)
    radial = points - model.point
    radial -= (radial @ axis)[:, None] * axis
    lengths = np.linalg.norm(radial, axis=1)
    radial = radial[lengths > 0]
    if len(radial) < 3:
        return False
    u = _unit(radial[0])
    v = np.cross(axis, u)
    angles = np.sort(np.mod(np.arctan2(radial @ v, radial @ u), 2 * np.pi))
    gaps = np.diff(np.r_[angles, angles[0] + 2 * np.pi])
    angular_noise = max(8 * mesh.weld_tolerance / model.radius, 1e-12)
    distinct = gaps[gaps > angular_noise]
    if len(distinct) < 3:
        return False
    step = 2 * np.pi / model.segments if model.segments else np.median(distinct)
    return bool(gaps.max() <= 1.5 * step + angular_noise)


def extrusion_axis(result: SegmentationResult) -> np.ndarray:
    """Minimize area unexplained by an extrusion and its adjacent treatments.

    Candidates are area-weighted plane-normal clusters. A cap is a parallel
    plane; a side is a perpendicular plane or a parallel-axis cylinder. An
    otherwise unexplained plane, or convex perpendicular-axis cylinder, is a
    candidate treatment when adjacent to both a cap and a side. Cylindrical
    treatments must be tangent to exactly one of each. Full-circle cylinders
    and their planar end caps are explained independently of candidate axis.
    Candidates within one percent of total area of the minimum use cap area
    as tiebreak.
    Directions are unoriented and angular comparisons use 0.5 degrees.
    """
    if not result.faces:
        raise ValueError("Cannot infer an extrusion axis without faces")
    supports = _supports(result)
    weights = np.array([result.mesh.areas[indices].sum() for indices in supports])
    planar = np.array([isinstance(f.params, Plane) for f in result.faces])
    plane_indices = np.flatnonzero(planar)
    if not len(plane_indices):
        raise ValueError("Cannot infer an extrusion axis without plane faces")
    directions = np.array(
        [
            _unit(f.params.normal if isinstance(f.params, Plane) else f.params.axis)
            for f in result.faces
        ]
    )
    _, candidates = _clusters(
        directions[planar],
        weights[planar],
        [result.faces[i].id for i in plane_indices],
        0.5,
    )
    by_id = {face.id: i for i, face in enumerate(result.faces)}
    neighbors = [
        (
            [by_id[n] for n in result.graph.neighbors(face.id) if n in by_id]
            if face.id in result.graph
            else []
        )
        for face in result.faces
    ]
    convex = np.array([f.convexity == "convex" for f in result.faces])
    sine, cosine = np.sin(np.radians(0.5)), np.cos(np.radians(0.5))
    secondary = np.zeros(len(result.faces), dtype=bool)
    for i in np.flatnonzero(~planar):
        face = result.faces[i]
        if not _full_circle(result, face, supports[i]):
            continue
        secondary[i] = True
        axis = directions[i]
        for j in neighbors[i]:
            if not planar[j] or abs(directions[j] @ axis) < cosine:
                continue
            points = result.mesh.vertices[result.mesh.triangles[supports[j]]]
            radial = points - face.params.point
            radial -= (radial @ axis)[..., None] * axis
            # A boss's host plane or a through-hole rim extends outside the
            # circle: it is body support, not the cylinder's planar end cap.
            if (
                np.linalg.norm(radial, axis=-1).max()
                <= face.params.radius + result.mesh.diagonal * 2e-5
            ):
                secondary[j] = True
    scores = []
    for candidate in candidates:
        dot = np.abs(directions @ candidate)
        parallel, perpendicular = dot >= cosine, dot <= sine
        cap = planar & parallel
        side = (planar & perpendicular) | (~planar & parallel)
        explained = cap | side | secondary
        possible = ~explained & (planar | (convex & perpendicular))
        treatments = 0
        for i in np.flatnonzero(possible):
            adjacent = neighbors[i]
            if not planar[i]:
                adjacent = [
                    j
                    for j in adjacent
                    if result.graph[result.faces[i].id][result.faces[j].id].get(
                        "convexity"
                    )
                    == "tangent"
                ]
                treatment = cap[adjacent].sum() == 1 and side[adjacent].sum() == 1
            else:
                treatment = cap[adjacent].any() and side[adjacent].any()
            if treatment:
                explained[i] = True
                if not planar[i]:
                    treatments += 1
                    continue
                # Count only treatments defeature would keep: exactly one
                # cap/side host pair whose edge lies in the face, with the
                # face centred on the hosts' bisector.
                pairs = []
                for c in (j for j in adjacent if cap[j]):
                    for d in (j for j in adjacent if side[j]):
                        edge = np.cross(directions[c], directions[d])
                        norm = np.linalg.norm(edge)
                        if norm == 0 or abs(directions[i] @ edge) > sine * norm:
                            continue
                        hosts = np.array([directions[c], directions[d]])
                        coefficients = np.linalg.lstsq(
                            hosts.T, directions[i], rcond=None
                        )[0]
                        if np.all(coefficients > 0):
                            pairs.append(hosts)
                if len(pairs) == 1:
                    bisector = pairs[0].sum(axis=0)
                    bisector /= np.linalg.norm(bisector)
                    if directions[i] @ bisector >= cosine:
                        treatments += 1
        scores.append(
            (
                float(weights[~explained].sum()),
                float(weights[cap].sum()),
                treatments,
            )
        )
    minimum = min(score[0] for score in scores)
    total_area = float(weights.sum())
    tied = [
        i
        for i, (unexplained, _, _) in enumerate(scores)
        if unexplained <= minimum + total_area * (0.01 + 1e-12)
    ]
    # Tie: the axis that explains more edge treatments, then the larger cap.
    winner = max(tied, key=lambda i: (scores[i][2], scores[i][1]))
    return candidates[winner].copy()
