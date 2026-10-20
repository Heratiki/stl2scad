"""Map recovered features to typed IR and separate editable-expression bindings.

The IR retains measured numeric geometry and provenance. Bindings describe how
its dimensions depend on Parameters, without changing any IR field shapes.
"""

from dataclasses import dataclass

import numpy as np

from .. import ir
from .features import Feature


@dataclass(frozen=True)
class Binding:
    node: ir.IRNode
    name: str
    points: tuple[tuple[str, str], ...] = ()
    center: tuple[str, str, str] = ("0", "0", "0")
    corner: tuple[str, str, str] = ("0", "0", "0")


@dataclass(frozen=True)
class ParametricModel:
    root: ir.TransformMultMatrix
    parameters: tuple[ir.Parameter, ...]
    constraints: tuple[ir.Constraint, ...]
    bindings: tuple[Binding, ...]
    labels: tuple[tuple[str, str, str], ...]


def _levels(values, tolerance):
    result = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > tolerance:
            result.append(float(value))
    return result


def features_to_ir(features: list[Feature]) -> ParametricModel:
    bodies = [f for f in features if f.profile is not None]
    if len(bodies) != 1 or bodies[0].height is None:
        raise ValueError("Editable output requires one extruded body")
    body = bodies[0]
    if body.polarity != "additive":
        raise ValueError("The body must add material")
    frame = np.asarray(body.part_frame)
    if (
        frame.shape != (4, 4)
        or not np.isfinite(frame).all()
        or not np.allclose(frame[3], [0, 0, 0, 1])
        or not np.allclose(frame[:3, :3].T @ frame[:3, :3], np.eye(3), atol=1e-7)
        or np.linalg.det(frame[:3, :3]) < 0
        or any(not np.allclose(f.part_frame, frame, atol=1e-8) for f in features)
    ):
        raise ValueError("Features must share a proper rigid part frame")
    dims = dict(body.profile.dimensions)
    points = np.asarray(body.profile.points)
    width, height, depth = dims["width"], dims["height"], body.height
    scale = max(width, height, depth)
    tolerance = scale * 2e-5
    parameters, constraints, bindings, labels = [], [], [], []

    def parameter(name, value, maximum, *, group="Body", minimum=0.01, faces=()):
        value = float(value)
        maximum = float(np.round(maximum, 2))
        if not np.isfinite(value) or value < minimum or value > maximum + tolerance:
            raise ValueError(f"Parameter {name} is outside its geometry range")
        parameters.append(
            ir.Parameter(
                name=name,
                value=value,
                raw_value=value,
                min=minimum,
                step=0.01,
                max=float(maximum),
                group=group,
                description=name.replace("_", " "),
                face_ids=faces,
            )
        )
        return name

    def constraint(expression, message, faces=()):
        constraints.append(
            ir.Constraint(expression=expression, message=message, face_ids=faces)
        )

    parameter("body_width", width, 2 * width, faces=body.face_ids)
    yname = "base_thickness" if body.profile.kind == "rectangle" else "body_height"
    parameter(yname, height, 2 * height, faces=body.face_ids)
    parameter("body_depth", depth, 2 * depth, faces=body.face_ids)
    levels = [_levels(points[:, i], tolerance) for i in range(2)]
    expressions = [["0", "body_width"], ["0", yname]]
    if body.profile.kind == "l":
        for name, maximum in [("base_thickness", height), ("wall_thickness", width)]:
            parameter(name, dims[name], maximum, faces=body.face_ids)
        expressions = [
            [
                "0",
                (
                    "wall_thickness"
                    if abs(levels[0][1] - dims["wall_thickness"]) < tolerance
                    else "body_width-wall_thickness"
                ),
                "body_width",
            ],
            [
                "0",
                (
                    "base_thickness"
                    if abs(levels[1][1] - dims["base_thickness"]) < tolerance
                    else "body_height-base_thickness"
                ),
                "body_height",
            ],
        ]
        constraint(
            "base_thickness < body_height && wall_thickness < body_width",
            "Body legs must have positive free lengths",
            body.face_ids,
        )
    elif body.profile.kind in ("u", "t"):
        along = next(i for i in range(2) if len(levels[i]) == 3)
        across = 1 - along
        dimension = ["body_width", "body_height"]
        size = [width, height]
        web = "web_thickness" if body.profile.kind == "u" else "flange_thickness"
        parameter(web, dims[web], size[along], faces=body.face_ids)
        middle = (
            web
            if abs(levels[along][1] - dims[web]) < tolerance
            else f"{dimension[along]}-{web}"
        )
        expressions[along] = ["0", middle, dimension[along]]
        if body.profile.kind == "u":
            for name in ("arm_1_thickness", "arm_2_thickness"):
                parameter(name, dims[name], size[across], faces=body.face_ids)
            expressions[across] = [
                "0",
                "arm_1_thickness",
                f"{dimension[across]}-arm_2_thickness",
                dimension[across],
            ]
            constraint(
                f"arm_1_thickness+arm_2_thickness < {dimension[across]} && {web} < {dimension[along]}",
                "U slot must remain open",
                body.face_ids,
            )
        else:
            parameter(
                "stem_width", dims["stem_width"], size[across], faces=body.face_ids
            )
            parameter(
                "stem_offset",
                levels[across][1],
                size[across],
                minimum=0.0,
                faces=body.face_ids,
            )
            expressions[across] = [
                "0",
                "stem_offset",
                "stem_offset+stem_width",
                dimension[across],
            ]
            constraint(
                f"stem_offset+stem_width < {dimension[across]} && {web} < {dimension[along]}",
                "T stem must fit inside its flange",
                body.face_ids,
            )
    elif body.profile.kind != "rectangle":
        expressions = [[], []]
        for axis in range(2):
            for i, value in enumerate(levels[axis]):
                expressions[axis].append(
                    parameter(
                        f'profile_1_p{i}_{"xy"[axis]}',
                        value,
                        2 * scale,
                        minimum=-2 * scale,
                        faces=body.face_ids,
                    )
                )

    def coordinate(axis, value):
        index = int(np.argmin(np.abs(np.asarray(levels[axis]) - value)))
        if abs(levels[axis][index] - value) > tolerance:
            raise ValueError("Feature host is not a supported profile plane")
        return expressions[axis][index]

    point_expressions = tuple(
        tuple(coordinate(i, p[i]) for i in range(2)) for p in points
    )
    sketch = ir.Sketch2D(
        points=body.profile.points, kind=body.profile.kind, face_ids=body.face_ids
    )
    extrusion = ir.ExtrudeLinear(height=depth, profile=sketch, face_ids=body.face_ids)
    bindings.append(Binding(extrusion, "body_1", points=point_expressions))
    labels.extend((f, "body_1_boundary", "plane") for f in body.face_ids)
    additive, cuts = [extrusion], []
    names = set()
    for feature in features:
        if feature is body:
            continue
        name = feature.id
        if name in names:
            raise ValueError("Feature names must be unique")
        names.add(name)
        group = name.replace("_", " ").title()
        if feature.kind in ("boss", "blind_hole"):
            expected = "additive" if feature.kind == "boss" else "subtractive"
            if feature.polarity != expected or not feature.on_face:
                raise ValueError("Cylinder ownership and polarity are required")
            axis = np.asarray(feature.axis)
            host_axis = int(np.argmax(np.abs(axis)))
            if host_axis == 2 or abs(axis[host_axis]) < 0.999999:
                raise ValueError(
                    "Editable cylinders currently require a profile-side host"
                )
            tangent = 1 - host_axis
            center = list(feature.position)
            host = coordinate(host_axis, center[host_axis])
            bound = ["body_width", yname][tangent]
            radius_limit = min(
                center[tangent],
                [width, height][tangent] - center[tangent],
                center[2],
                depth - center[2],
            )
            if body.profile.kind == "l" and host_axis == 1:
                radius_limit = min(radius_limit, abs(center[0] - levels[0][1]))
            parameter(
                f"{name}_radius",
                feature.radius,
                radius_limit - 0.01,
                group=group,
                faces=feature.face_ids,
            )
            for index in (tangent, 2):
                parameter(
                    f'{name}_{"xyz"[index]}',
                    center[index],
                    [width, height, depth][index],
                    minimum=0.0,
                    group=group,
                    faces=feature.face_ids,
                )
            location = [
                host if i == host_axis else f'{name}_{"xyz"[i]}' for i in range(3)
            ]
            if feature.kind == "boss":
                parameter(
                    f"{name}_height",
                    feature.height,
                    max(width, height),
                    group=group,
                    faces=feature.face_ids,
                )
                node = ir.Boss(
                    height=feature.height,
                    radius=feature.radius,
                    center=feature.position,
                    axis=feature.axis,
                    host_face_id=feature.on_face,
                    face_ids=feature.face_ids,
                )
                additive.append(node)
            else:
                # The linked assert remains meaningful after editing the host.
                material_available = (
                    center[host_axis]
                    if axis[host_axis] < 0
                    else [width, height][host_axis] - center[host_axis]
                )
                parameter(
                    f"{name}_depth",
                    feature.depth,
                    material_available - 0.01,
                    group=group,
                    faces=feature.face_ids,
                )
                node = ir.HoleBlind(
                    depth=feature.depth,
                    radius=feature.radius,
                    center=feature.position,
                    axis=feature.axis,
                    host_face_id=feature.on_face,
                    face_ids=feature.face_ids,
                )
                cuts.append(node)
                material = (
                    host
                    if axis[host_axis] < 0
                    else f'{["body_width", yname][host_axis]}-({host})'
                )
                constraint(
                    f"{name}_depth < {material}",
                    "Blind hole must leave a floor",
                    feature.face_ids,
                )
            constraint(
                f'{name}_{"xyz"[tangent]} > {name}_radius && {name}_{"xyz"[tangent]}+{name}_radius < {bound} && {name}_z > {name}_radius && {name}_z+{name}_radius < body_depth',
                "Cylinder must stay inside the host footprint",
                feature.face_ids,
            )
            if body.profile.kind == "l" and host_axis == 1:
                inner = expressions[0][1]
                fillets = [
                    f"{f.id}_radius"
                    for f in features
                    if f.kind == "fillet" and feature.on_face in f.between
                ]
                clearance = "+".join(fillets) or "0"
                inequality = (
                    f"{name}_x+{name}_radius+{clearance} < {inner}"
                    if abs(levels[0][1] - (width - dims["wall_thickness"])) < tolerance
                    else f"{name}_x-{name}_radius-({clearance}) > {inner}"
                )
                constraint(inequality, "Cylinder must clear the wall", feature.face_ids)
            bindings.append(Binding(node, name, center=tuple(location)))
            labels.extend(
                (
                    f,
                    name
                    + (
                        "_side"
                        if i == 0
                        else "_cap" if feature.kind == "boss" else "_floor"
                    ),
                    "cylinder" if i == 0 else "plane",
                )
                for i, f in enumerate(feature.face_ids)
            )
            labels = [
                (
                    f,
                    (
                        "base_top"
                        if f == feature.on_face and host == "base_thickness"
                        else label
                    ),
                    kind,
                )
                for f, label, kind in labels
            ]
        elif feature.kind == "fillet":
            if (
                feature.polarity != "additive"
                or feature.corner is None
                or len(feature.between) != 2
            ):
                raise ValueError("Fillet needs two host faces and a sharp corner")
            parameter(
                f"{name}_radius",
                feature.radius,
                min(
                    width - dims.get("wall_thickness", 0),
                    height - dims.get("base_thickness", 0),
                ),
                group=group,
                faces=feature.face_ids,
            )
            corner = tuple(coordinate(i, feature.corner[i]) for i in range(2)) + ("0",)
            direction = np.sign(
                np.asarray(feature.position)[:2] - np.asarray(feature.corner)[:2]
            )
            center = tuple(
                f'{corner[i]}{"+" if direction[i] > 0 else "-"}{name}_radius'
                for i in range(2)
            ) + ("0",)
            node = ir.Fillet(
                radius=feature.radius,
                face1_id=feature.between[0],
                face2_id=feature.between[1],
                face_ids=feature.face_ids,
            )
            additive.append(node)
            bindings.append(Binding(node, name, center=center, corner=corner))
            labels.extend((f, name, "cylinder") for f in feature.face_ids)
            constraint(
                f"{name}_radius < body_width-wall_thickness && {name}_radius < body_height-base_thickness",
                "Fillet must fit between the free leg ends",
                feature.face_ids,
            )
        else:
            raise ValueError(f"Unsupported editable feature: {feature.kind}")
    positives = [p.name + " > 0" for p in parameters if p.min > 0]
    constraint(" && ".join(positives), "Dimensions must stay positive")
    cylinders = [f for f in features if f.kind in ("boss", "blind_hole")]
    for i, first in enumerate(cylinders):
        for second in cylinders[i + 1 :]:
            if first.on_face != second.on_face:
                continue
            a, b = first.id, second.id
            plane_axis = int(np.argmax(np.abs(first.axis)))
            tangent = "xy"[1 - plane_axis]
            constraint(
                f"norm([{a}_{tangent}-{b}_{tangent}, {a}_z-{b}_z]) > {a}_radius+{b}_radius",
                "Features on one host must not overlap",
                first.face_ids + second.face_ids,
            )
    union = ir.BooleanUnion(
        children=tuple(additive),
        face_ids=tuple(f for n in additive for f in n.face_ids),
    )
    root = ir.BooleanDifference(
        base=union,
        cuts=tuple(cuts),
        face_ids=tuple(f for feature in features for f in feature.face_ids),
    )
    return ParametricModel(
        ir.TransformMultMatrix(
            matrix=body.part_frame, child=root, face_ids=root.face_ids
        ),
        tuple(parameters),
        tuple(constraints),
        tuple(bindings),
        tuple(labels),
    )
