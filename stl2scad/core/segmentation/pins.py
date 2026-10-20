"""Closed standalone cylinders, with no inferred host or fictitious profile."""

import numpy as np

from .. import ir
from .models import Cylinder, Plane
from .features import Feature, _axis_plane_point, _full_cylinder


def detect_pin(result):
    curves = [f for f in result.faces if isinstance(f.params, Cylinder)]
    caps = [f for f in result.faces if isinstance(f.params, Plane)]
    if len(result.faces) != 3 or len(curves) != 1 or len(caps) != 2:
        return None
    curved = curves[0]
    axis = np.asarray(curved.params.axis)
    if (
        curved.convexity != "convex"
        or not _full_cylinder(result, curved)
        or any(abs(np.dot(c.params.normal, axis)) < 0.999 for c in caps)
        or np.dot(caps[0].params.normal, caps[1].params.normal) > -0.999
        or any(result.edge_convexity(curved, c) != "convex" for c in caps)
    ):
        return None
    caps.sort(key=lambda c: np.dot(c.params.normal, axis))
    start, stop = (_axis_plane_point(curved.params, c.params) for c in caps)
    u = np.asarray(curved.params.radial_reference)
    if u.shape != (3,):
        u = np.cross(axis, np.eye(3)[np.argmin(abs(axis))])
    u = u - (u @ axis) * axis
    u /= np.linalg.norm(u)
    frame = np.eye(4)
    frame[:3, :3] = np.column_stack((u, np.cross(axis, u), axis))
    frame[:3, 3] = start
    return Feature(
        "pin_1",
        "pin",
        "additive",
        tuple(f.id for f in result.faces),
        tuple(tuple(float(v) for v in row) for row in frame),
        radius=curved.params.radius,
        height=float(np.linalg.norm(stop - start)),
        segments=curved.params.segments,
        radial_reference=(1.0, 0.0, 0.0),
    )


def pin_to_ir(feature):
    from .to_ir import ParametricModel, Binding

    scale = max(feature.radius, feature.height)
    if feature.radius <= 0 or feature.height <= 0 or feature.polarity != "additive":
        raise ValueError("Pin dimensions must be positive")
    node = ir.PrimitiveCylinder(
        radius=feature.radius,
        height=feature.height,
        axis="z",
        origin=feature.position,
        face_ids=feature.face_ids,
    )
    parameters = tuple(
        ir.Parameter(
            name="pin_1_" + name,
            value=value,
            raw_value=value,
            min=scale * 1e-6,
            step=min(0.01, scale * 1e-3),
            max=2 * value,
            group="Pin 1",
            description="pin 1 " + name,
            face_ids=feature.face_ids,
        )
        for name, value in [("radius", feature.radius), ("height", feature.height)]
    )
    parameters += (
        ir.Parameter(
            name="pin_1_segments",
            value=feature.segments or 64,
            raw_value=feature.segments or 64,
            min=3,
            step=1,
            max=max(256, feature.segments or 64),
            group="Resolution",
            description="Higher value gives a smoother pin",
            face_ids=feature.face_ids,
        ),
    )
    constraints = (
        ir.Constraint(
            expression="pin_1_radius>0 && pin_1_height>0 && pin_1_segments>=3 && pin_1_segments==floor(pin_1_segments)",
            message="Pin dimensions and resolution must be positive",
            face_ids=feature.face_ids,
        ),
    )
    return ParametricModel(
        ir.TransformMultMatrix(
            matrix=feature.part_frame, child=node, face_ids=feature.face_ids
        ),
        parameters,
        constraints,
        (Binding(node, "pin_1"),),
        tuple((f, "pin_1", "cylinder or cap") for f in feature.face_ids),
    )
