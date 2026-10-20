"""Host-relative through cuts, including oblique axes and extrusion end caps."""

import numpy as np

from .. import ir
from .fitting import cylinder_phase
from .profile_geometry import exclusive_limit


def bind_through_hole(feature, body, points, coordinate, parameter, constraint, scale):
    from .to_ir import Binding

    if feature.polarity != "subtractive" or not feature.on_face or feature.depth <= 0:
        raise ValueError("Through hole requires two rims and positive depth")
    normal = np.asarray(feature.rim_normals[0])
    axis = np.asarray(feature.axis)
    host_axis = int(np.argmax(abs(normal)))
    dimensions = dict(body.profile.dimensions)
    bounds = [dimensions["width"], dimensions["height"], body.height]
    name = feature.id
    group = name.replace("_", " ").title()
    center = np.asarray(feature.position)
    location = ["0"] * 3
    if abs(normal[host_axis]) > 0.999999:
        location[host_axis] = (
            coordinate(host_axis, center[host_axis])
            if host_axis < 2
            else "0" if abs(center[2]) < scale * 2e-5 else "body_depth"
        )
        for j in range(3):
            if j != host_axis:
                location[j] = parameter(
                    f'{name}_{"xyz"[j]}',
                    center[j],
                    bounds[j],
                    group=group,
                    minimum=0.0,
                    faces=feature.face_ids,
                )
    else:
        # An angled profile-side host is a line segment in the section. Keep
        # the attachment on that segment when either endpoint is edited.
        raw = np.asarray(body.profile.points)
        host_edge = None
        for i, (a, b) in enumerate(zip(raw, np.roll(raw, -1, axis=0))):
            edge = b - a
            t = np.dot(center[:2] - a, edge) / np.dot(edge, edge)
            if 0 <= t <= 1 and np.linalg.norm(a + t * edge - center[:2]) < scale * 2e-5:
                host_edge = (i, t)
                break
        if host_edge is None:
            raise ValueError("Through-hole host is not a profile boundary")
        i, t = host_edge
        along = parameter(
            name + "_along", t, 1.0, group=group, minimum=0.0, faces=feature.face_ids
        )
        location[:2] = [
            f"(1-{along})*({points[i][j]})+{along}*({points[(i+1)%len(points)][j]})"
            for j in range(2)
        ]
        location[2] = parameter(
            name + "_z",
            center[2],
            body.height,
            group=group,
            minimum=0.0,
            faces=feature.face_ids,
        )
    tangent = [j for j in range(3) if j != host_axis]
    clearance = min(min(center[j], bounds[j] - center[j]) for j in tangent)
    radius_limit = clearance * abs(np.dot(normal, axis))
    parameter(
        name + "_radius",
        feature.radius,
        exclusive_limit(radius_limit, feature.radius, scale),
        group=group,
        faces=feature.face_ids,
    )
    polygon = "[" + ", ".join("[" + ", ".join(p) + "]" for p in points) + "]"
    extent = f'_material_depth([{", ".join(location)}],[{", ".join(str(x) for x in axis)}],{polygon},body_depth)'
    constraint(f"{extent} > 0", "Through hole must cross material", feature.face_ids)
    node = ir.HoleThrough(
        diameter=2 * feature.radius,
        depth=feature.depth,
        extra_fields=(
            ("center", feature.position),
            ("direction", feature.axis),
            ("rim_normals", feature.rim_normals),
        ),
        face_ids=feature.face_ids,
    )
    return node, Binding(
        node,
        name,
        center=tuple(location),
        phase_deg=cylinder_phase(feature.axis, feature.radial_reference),
        extent=extent,
    )
