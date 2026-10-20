"""Typed path/cut IR and geometry-linked editable bindings for prismatic parts."""

import numpy as np

from .. import ir
from .to_ir import Binding, ParametricModel


def section_to_ir(features):
    body = next(f for f in features if f.profile is not None)
    frame = np.asarray(body.part_frame)
    if (
        body.polarity != "additive"
        or not body.height
        or body.height <= 0
        or frame.shape != (4, 4)
        or not np.isfinite(frame).all()
        or not np.allclose(frame[3], [0, 0, 0, 1])
        or not np.allclose(frame[:3, :3].T @ frame[:3, :3], np.eye(3), atol=1e-7)
        or np.linalg.det(frame[:3, :3]) < 0
        or any(not np.allclose(f.part_frame, frame, atol=1e-8) for f in features)
    ):
        raise ValueError(
            "Arc features need a positive extrusion and a shared rigid frame"
        )
    width, height = (
        dict(body.profile.dimensions)["width"],
        dict(body.profile.dimensions)["height"],
    )
    scale, tolerance = max(width, height, body.height), max(width, height) * 2e-5
    parameters, resolutions, constraints, bindings, labels = [], [], [], [], []

    def parameter(
        name, value, maximum, group="Body", minimum=0.01, faces=(), description=None
    ):
        if not np.isfinite(value) or not minimum <= value <= maximum + tolerance:
            raise ValueError(f"Invalid geometry range for {name}")
        parameters.append(
            ir.Parameter(
                name=name,
                value=float(value),
                raw_value=float(value),
                min=minimum,
                max=float(maximum),
                step=0.01,
                group=group,
                description=description or name.replace("_", " "),
                face_ids=faces,
            )
        )
        return name

    def resolution(name, value, faces):
        if value is None or value < 5:
            raise ValueError("Arc needs a measured segment count")
        resolutions.append(
            ir.Parameter(
                name=name + "_segments",
                value=value,
                raw_value=value,
                min=5,
                step=1,
                max=max(256, value),
                group="Resolution",
                description=name.replace("_", " ")
                + " segments; a higher value gives a smoother part",
                face_ids=faces,
            )
        )

    def constraint(expression, message, faces=()):
        constraints.append(
            ir.Constraint(expression=expression, message=message, face_ids=faces)
        )

    recognized = body.profile.kind == "rounded_rectangle"
    if recognized:
        parameter("plate_length", width, 2 * width, faces=body.face_ids)
        parameter("plate_width", height, 2 * height, faces=body.face_ids)
    parameter("plate_thickness", body.height, 2 * body.height, faces=body.face_ids)
    source = body.profile.segments
    nodes, arc_bindings = {}, {}
    corner_count, arc_count = 0, 0
    for i, s in enumerate(source):
        if s.kind != "arc":
            continue
        if s.radius is None or s.radius <= 0 or s.center is None:
            raise ValueError("Sketch arc requires a positive radius and center")
        is_corner = recognized and s.convexity == "convex"
        if is_corner:
            corner_count += 1
            name = f"corner_{corner_count}"
        else:
            arc_count += 1
            name = f"arc_{arc_count}"
        group = name.replace("_", " ").title()
        radius = parameter(
            name + "_radius",
            s.radius,
            min(width, height) / 2 if recognized else 2 * scale,
            group,
            faces=s.face_ids,
        )
        resolution(name, s.segments, s.face_ids)
        center = []
        for j, (value, dimension, limit) in enumerate(
            zip(s.center, ["plate_length", "plate_width"], [width, height])
        ):
            if is_corner:
                center.append(radius if value < limit / 2 else dimension + "-" + radius)
            elif recognized and abs(value) < tolerance:
                center.append("0")
            elif recognized and abs(value - limit) < tolerance:
                center.append(dimension)
            else:
                center.append(
                    parameter(
                        name + "_" + "xy"[j],
                        value,
                        2 * limit,
                        group,
                        minimum=-limit,
                        faces=s.face_ids,
                    )
                )
        angle = lambda a: (
            float(round(a / 90) * 90) if abs(a - round(a / 90) * 90) < 0.001 else a
        )
        node = ir.SketchArc2D(
            center=s.center,
            radius=s.radius,
            start_deg=angle(s.start_deg),
            sweep_deg=angle(s.sweep_deg),
            phase_deg=s.phase_deg,
            segments=s.segments,
            convexity=s.convexity,
            face_ids=s.face_ids,
        )
        binding = Binding(node, name, center=(*center, "0"), phase_deg=s.phase_deg)
        nodes[i], arc_bindings[i] = node, binding
        bindings.append(binding)
        if recognized:
            constraint(
                f"{radius} < min(plate_length,plate_width)/2",
                name + " must fit the available outline",
                s.face_ids,
            )
        labels.extend((f, name, "cylinder") for f in s.face_ids)

    def endpoint(binding, node, end):
        label = "end" if end else "start"
        return tuple(f"_{binding.name}_{label}[{j}]" for j in range(2))

    joints = {}

    def joint(i):
        previous = (i - 1) % len(source)
        if previous in arc_bindings:
            return endpoint(arc_bindings[previous], nodes[previous], True)
        if i in arc_bindings:
            return endpoint(arc_bindings[i], nodes[i], False)
        if i not in joints:
            joints[i] = tuple(
                parameter(
                    f'segment_{i+1}_start_{"xy"[j]}',
                    source[i].start[j],
                    2 * scale,
                    "Profile segments",
                    minimum=-2 * scale,
                    faces=source[i].face_ids,
                )
                for j in range(2)
            )
        return joints[i]

    for i, s in enumerate(source):
        if i in nodes:
            continue
        point, end = joint(i), joint((i + 1) % len(source))
        node = ir.SketchLine2D(start=s.start, end=s.end, face_ids=s.face_ids)
        nodes[i] = node
        bindings.append(Binding(node, f"segment_{i+1}", points=(point, end)))
        labels.extend((f, f"segment_{i+1}", "plane") for f in s.face_ids)
    sketch = ir.SketchPath2D(
        segments=tuple(nodes[i] for i in range(len(source))),
        kind=body.profile.kind,
        face_ids=body.face_ids,
    )
    extrusion = ir.ExtrudeLinear(
        height=body.height, profile=sketch, face_ids=body.face_ids
    )
    bindings.append(Binding(extrusion, "body_1"))
    labels.extend(
        (f, "end_cap", "plane")
        for f in body.face_ids
        if f not in {face for s in source for face in s.face_ids}
    )
    cuts = []
    capsules = []
    for feature in features:
        if feature is body:
            continue
        if (
            feature.kind not in ("through_slot", "through_hole")
            or feature.polarity != "subtractive"
            or abs(feature.depth - body.height) > tolerance
            or feature.radius is None
            or feature.radius <= 0
        ):
            raise ValueError(
                "Arc-profile output requires extrusion-spanning circular or stadium cuts"
            )
        name = feature.id
        group = name.replace("_", " ").title()
        center = tuple(
            parameter(
                name + "_" + "xy"[j],
                feature.position[j],
                [width, height][j],
                group,
                minimum=0,
                faces=feature.face_ids,
            )
            for j in range(2)
        )
        resolution(name, feature.segments, feature.face_ids)
        phase = float(
            np.degrees(
                np.arctan2(feature.radial_reference[1], feature.radial_reference[0])
            )
        )
        if feature.kind == "through_slot":
            parameter(
                name + "_width",
                feature.width,
                min(width, height),
                group,
                faces=feature.face_ids,
            )
            parameter(
                name + "_length",
                feature.length,
                float(np.hypot(width, height)),
                group,
                faces=feature.face_ids,
            )
            parameter(
                name + "_angle",
                feature.angle_deg,
                180,
                group,
                minimum=-180,
                faces=feature.face_ids,
            )
            direction = np.array(
                [
                    np.cos(np.radians(feature.angle_deg)),
                    np.sin(np.radians(feature.angle_deg)),
                    0,
                ]
            )
            delta = (feature.length - feature.width) / 2
            node = ir.Slot(
                start=tuple(np.asarray(feature.position) - delta * direction),
                end=tuple(np.asarray(feature.position) + delta * direction),
                width=feature.width,
                axis="z",
                extra_fields=(
                    ("segments", feature.segments),
                    ("phase_deg", phase),
                    ("depth", feature.depth),
                ),
                face_ids=feature.face_ids,
            )
            constraint(
                f"{name}_length > {name}_width",
                name + " length must exceed its width",
                feature.face_ids,
            )
            a, b = f"_{name}_start", f"_{name}_end"
            radius = name + "_width/2"
        else:
            parameter(
                name + "_diameter",
                2 * feature.radius,
                min(width, height),
                group,
                faces=feature.face_ids,
            )
            node = ir.HoleThrough(
                diameter=2 * feature.radius,
                depth=feature.depth,
                axis="z",
                extra_fields=(
                    ("center", feature.position),
                    ("segments", feature.segments),
                    ("phase_deg", phase),
                ),
                face_ids=feature.face_ids,
            )
            a = b = f"[{center[0]},{center[1]}]"
            radius = name + "_diameter/2"
        bindings.append(Binding(node, name, center=(*center, "0"), phase_deg=phase))
        cuts.append(node)
        constraint(
            f"_capsule_inside({a},{b},{radius},_outline)",
            name + " must stay inside the outline",
            feature.face_ids,
        )
        for other_a, other_b, other_r, other_name in capsules:
            constraint(
                f"_segment_distance({a},{b},{other_a},{other_b}) > ({radius})+({other_r})",
                name + " must not overlap " + other_name,
                feature.face_ids,
            )
        capsules.append((a, b, radius, name))
        labels.extend(
            (f, name, "plane" if f in feature.between else "cylinder")
            for f in feature.face_ids
        )
    root = ir.TransformMultMatrix(
        matrix=body.part_frame,
        child=ir.BooleanDifference(base=extrusion, cuts=tuple(cuts)),
        face_ids=body.face_ids,
    )
    return ParametricModel(
        root,
        tuple(parameters + resolutions),
        tuple(constraints),
        tuple(bindings),
        tuple(labels),
    )
