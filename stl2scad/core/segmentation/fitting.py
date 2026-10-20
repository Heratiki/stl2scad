"""Orientation-independent least-squares primitive fits for RANSAC inliers.

Future primitive fitters belong here; the pipeline supplies connected support
patches and keeps original triangle provenance independently of the fitter.
"""

import numpy as np

from .models import Cylinder, Plane


def _unit(vector):
    return vector / np.linalg.norm(vector)


def fit_plane(points: np.ndarray, normals: np.ndarray) -> Plane:
    points = np.asarray(points, dtype=np.float64)
    center = points.mean(axis=0)
    _, singular, vh = np.linalg.svd(points - center, full_matrices=False)
    if len(singular) < 3 or singular[1] <= singular[0] * 1e-10:
        raise ValueError("Plane support must not be collinear")
    normal = vh[-1]
    if normal @ np.sum(normals, axis=0) < 0:
        normal = -normal
    return Plane(tuple(normal), tuple(center))


def fit_cylinder(points: np.ndarray, normals: np.ndarray) -> Cylinder:
    """Fit the axis from the normal nullspace, then a circle in its normal plane.

    Use mesh vertices, not triangle centroids: centroids lie inside the analytic
    cylinder by a tessellation-dependent chord error. Normals may point either
    inward or outward. At least three distinct angular samples are required.
    """
    points, normals = np.asarray(points, dtype=np.float64), np.asarray(
        normals, dtype=np.float64
    )
    _, singular, vh = np.linalg.svd(normals, full_matrices=False)
    if len(singular) < 3 or singular[1] < 0.05 * singular[0]:
        raise ValueError("Cylinder support needs a spread of normals")
    axis = vh[-1]
    if axis[np.argmax(np.abs(axis))] < 0:
        axis = -axis
    u = _unit(np.cross(axis, np.eye(3)[np.argmin(np.abs(axis))]))
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
    return Cylinder(tuple(axis), tuple(point), float(np.sqrt(radius2)))


def cylinder_residuals(cylinder: Cylinder, points: np.ndarray) -> np.ndarray:
    delta = points - cylinder.point
    radial = delta - (delta @ cylinder.axis)[..., None] * np.asarray(cylinder.axis)
    return np.abs(np.linalg.norm(radial, axis=-1) - cylinder.radius)


def cylinder_phase(axis, radial_reference):
    """Phase about local Z after the emitter's Z-to-axis rotation."""
    if radial_reference is None:
        return 0.0
    axis = np.asarray(axis, dtype=float).copy()
    axis[np.abs(axis) < 1e-7] = 0
    axis /= np.linalg.norm(axis)
    turn = np.cross([0.0, 0.0, 1.0], axis)
    cosine = axis[2]
    if np.linalg.norm(turn) < 1e-8:
        rotation = np.eye(3) if cosine > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        sine = np.linalg.norm(turn)
        x, y, z = turn / sine
        cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
        rotation = np.eye(3) + sine * cross + (1 - cosine) * (cross @ cross)
    reference = np.asarray(radial_reference)
    return float(
        np.degrees(np.arctan2(reference @ rotation[:, 1], reference @ rotation[:, 0]))
    )
