"""Typed composition IR and bindings for slabs, edge cutters and fixed regions.

These private nodes extend the segmentation model without changing public IR
field shapes. Geometry remains numeric; editable expressions live in Binding.
"""

from dataclasses import dataclass
import json

import numpy as np

from .. import ir
from .to_ir import Binding, ParametricModel


@dataclass(frozen=True)
class SlabExtrusion(ir.ExtrudeLinear):
    loops: tuple[ir.SketchPath2D | ir.Sketch2D, ...] = ()
    bottom: float = 0.0

    def to_dict(self):
        return dict(
            super().to_dict(),
            loops=[p.to_dict() for p in self.loops],
            bottom=self.bottom,
        )


@dataclass(frozen=True)
class EdgeCutter(ir.IRNode):
    kind: str
    size: float
    matrix: tuple[tuple[float, ...], ...]
    length: float
    segments: int | None = None

    def to_dict(self):
        return dict(
            type="EdgeCutter",
            kind=self.kind,
            size=self.size,
            matrix=self.matrix,
            length=self.length,
            segments=self.segments,
            face_ids=self.face_ids,
        )


@dataclass(frozen=True)
class RegionSolid(ir.IRNode):
    points: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]

    def to_dict(self):
        return dict(
            type="RegionSolid",
            points=self.points,
            triangles=self.triangles,
            face_ids=self.face_ids,
        )


def treatment_frame(feature, lower, upper):
    """Inward host directions and a finite edge span in the part frame."""
    normals = np.asarray(feature.rim_normals, dtype=float)
    if normals.shape != (2, 3) or abs(normals[0] @ normals[1]) > 1e-7:
        raise ValueError("Treatment needs two orthogonal planar host normals")
    u, v = -normals
    direction = np.cross(u, v)
    corners = np.array(np.meshgrid(*zip(lower, upper))).reshape(3, -1).T
    origin = np.asarray(feature.position, dtype=float)
    start, end = ((corners - origin) @ direction).min(), (
        (corners - origin) @ direction
    ).max()
    matrix = np.eye(4)
    matrix[:3, :3] = np.column_stack((u, v, direction))
    matrix[:3, 3] = origin + start * direction
    phase = 0.0
    if feature.radial_reference is not None:
        ref = np.asarray(feature.radial_reference)
        phase = float(np.degrees(np.arctan2(ref @ v, ref @ u)))
    return matrix, float(end - start), phase


def compose_to_ir(features):
    slabs = [f for f in features if f.kind == "slab"]
    if not slabs:
        raise ValueError("Composition requires at least one slab")
    frame = np.asarray(slabs[0].part_frame)
    if (
        frame.shape != (4, 4)
        or not np.isfinite(frame).all()
        or not np.allclose(frame[3], [0, 0, 0, 1])
        or not np.allclose(frame[:3, :3].T @ frame[:3, :3], np.eye(3), atol=1e-7)
        or np.linalg.det(frame[:3, :3]) < 0
        or any(not np.allclose(f.part_frame, frame, atol=1e-8) for f in features)
    ):
        raise ValueError("Features must share a proper rigid part frame")
    from .sections import profile_points

    all_points = np.vstack([profile_points(p) for s in slabs for p in s.loops])
    lower = np.r_[all_points.min(axis=0), min(s.position[2] for s in slabs)]
    upper = np.r_[all_points.max(axis=0), max(s.position[2] + s.height for s in slabs)]
    scale = float(max(upper - lower))
    tolerance = scale * 2e-5
    parameters, constraints, bindings, labels = [], [], [], []
    counts = {"corner": 0, "segment": 0, "slot": 0}

    def parameter(name, value, maximum=None, minimum=None, group="Body", faces=()):
        minimum = scale * 1e-6 if minimum is None else minimum
        maximum = 2 * scale if maximum is None else maximum
        if not np.isfinite(value) or not minimum <= value <= maximum + tolerance:
            raise ValueError(f"Invalid geometry range for {name}")
        parameters.append(
            ir.Parameter(
                name=name,
                value=float(value),
                raw_value=float(value),
                min=float(minimum),
                step=min(0.01, scale * 1e-3),
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

    parameter("plate_length", upper[0] - lower[0])
    parameter("plate_width", upper[1] - lower[1])
    top_names = []
    for i, slab in enumerate(slabs):
        name = f"step_{i+1}_height" if len(slabs) > 1 else "plate_thickness"
        top_names.append(
            parameter(
                name,
                slab.position[2] + slab.height,
                group="Steps" if len(slabs) > 1 else "Body",
                faces=slab.face_ids,
            )
        )
    constraint(
        " && ".join(f"{a} < {b}" for a, b in zip(["0"] + top_names, top_names)),
        "Slab top levels must increase",
    )

    def coord(value, axis):
        if abs(value - lower[axis]) < tolerance:
            return format(lower[axis], ".12g")
        if abs(value - upper[axis]) < tolerance:
            return (
                f"({lower[axis]:.12g})+"
                + ["plate_length", "plate_width", top_names[-1]][axis]
            )
        if axis == 2:
            for s, name in zip(slabs, top_names):
                if abs(value - (s.position[2] + s.height)) < tolerance:
                    return name
        return format(value, ".12g")

    def profile_node(profile, slab):
        source = profile.segments
        if not source:
            node = ir.Sketch2D(
                points=profile.points, kind=profile.kind, face_ids=slab.face_ids
            )
            bindings.append(
                Binding(
                    node,
                    "outline",
                    points=tuple(
                        tuple(coord(v, j) for j, v in enumerate(p))
                        for p in profile.points
                    ),
                )
            )
            return node
        ring = profile_points(profile)
        signed_area = float(
            np.sum(
                ring[:, 0] * np.roll(ring[:, 1], -1)
                - ring[:, 1] * np.roll(ring[:, 0], -1)
            )
        )
        circular = [edge for edge in source if edge.kind == "arc"]
        slot = None
        if (
            signed_area < 0
            and len(circular) == 2
            and len(source) == 4
            and all(abs(abs(edge.sweep_deg) - 180) < 1e-3 for edge in circular)
            and abs(circular[0].radius - circular[1].radius) < tolerance
        ):
            counts["slot"] += 1
            slot = f"slot_{counts['slot']}"
            c0, c1 = (np.asarray(edge.center) for edge in circular)
            distance = float(np.linalg.norm(c1 - c0))
            if distance <= tolerance:
                raise ValueError("Stadium needs distinct end centers")
            midpoint, direction = (c0 + c1) / 2, (c1 - c0) / distance
            group = slot.replace("_", " ").title()
            parameter(
                slot + "_width",
                2 * circular[0].radius,
                group=group,
                faces=slab.face_ids,
            )
            parameter(
                slot + "_length",
                distance + 2 * circular[0].radius,
                group=group,
                faces=slab.face_ids,
            )
            parameter(
                slot + "_segments",
                circular[0].segments,
                maximum=max(256, circular[0].segments),
                minimum=3,
                group="Resolution",
            )
            constraint(
                f"{slot}_length > {slot}_width", "Slot length must exceed its width"
            )
        arcs, nodes = {}, {}
        for i, s in enumerate(source):
            if s.kind != "arc":
                continue
            if slot:
                name = slot + f"_arc_{len(arcs)+1}"
                r, resolution = slot + "_width/2", slot + "_segments"
            else:
                counts["corner"] += 1
                name = f"corner_{counts['corner']}"
                r = parameter(
                    name + "_radius",
                    s.radius,
                    group="Profile corners",
                    faces=s.face_ids,
                )
                parameter(
                    name + "_segments",
                    s.segments,
                    maximum=max(256, s.segments),
                    minimum=3,
                    group="Resolution",
                    faces=s.face_ids,
                )
                constraint(
                    f"{name}_segments >= 3 && {name}_segments == floor({name}_segments)",
                    "Resolution must be an integer of at least 3",
                )
                resolution = name + "_segments"
            center = []
            # A tangent arc center follows radius edits; straight neighbours
            # stay attached through the computed faceted arc endpoints.
            for j, value in enumerate(s.center):
                if profile.kind == "rounded_rectangle":
                    high = value > (lower[j] + upper[j]) / 2
                    center.append(
                        f"({coord(upper[j] if high else lower[j], j)})"
                        + ("-" if high else "+")
                        + r
                    )
                else:
                    center.append(format(value, ".12g"))
            if slot:
                sign = (
                    -1 if np.linalg.norm(np.asarray(s.center) - c0) < tolerance else 1
                )
                center = [
                    f"({midpoint[j]:.12g})+({sign*direction[j]:.12g})*({slot}_length-{slot}_width)/2"
                    for j in range(2)
                ]
            node = ir.SketchArc2D(
                center=s.center,
                radius=s.radius,
                start_deg=s.start_deg,
                sweep_deg=s.sweep_deg,
                phase_deg=s.phase_deg,
                segments=s.segments,
                convexity=s.convexity,
                face_ids=s.face_ids,
            )
            b = Binding(
                node,
                name,
                center=(*center, "0"),
                phase_deg=s.phase_deg,
                radius=r,
                resolution=resolution,
            )
            nodes[i], arcs[i] = node, b
            bindings.append(b)
            constraint(
                f"{r} < min(plate_length,plate_width)/2",
                "Profile radius must fit its outline",
                s.face_ids,
            )

        def joint(i):
            previous = (i - 1) % len(source)
            if previous in arcs:
                return tuple(f"_{arcs[previous].name}_end[{j}]" for j in range(2))
            if i in arcs:
                return tuple(f"_{arcs[i].name}_start[{j}]" for j in range(2))
            return tuple(coord(v, j) for j, v in enumerate(source[i].start))

        for i, s in enumerate(source):
            if i in nodes:
                continue
            counts["segment"] += 1
            node = ir.SketchLine2D(start=s.start, end=s.end, face_ids=s.face_ids)
            nodes[i] = node
            bindings.append(
                Binding(
                    node,
                    f"segment_{counts['segment']}",
                    points=(joint(i), joint((i + 1) % len(source))),
                )
            )
        return ir.SketchPath2D(
            segments=tuple(nodes[i] for i in range(len(source))),
            kind=profile.kind,
            face_ids=slab.face_ids,
        )

    additive, cuts = [], []
    for i, slab in enumerate(slabs):
        if slab.polarity != "additive" or slab.height is None or slab.height <= 0:
            raise ValueError("Slab needs additive polarity and positive height")

        # Number corners on the dominant island before smaller detached ribs.
        # Winding remains untouched, including CW hole loops.
        def loop_area(profile):
            p = profile_points(profile)
            return abs(
                float(
                    np.sum(
                        p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1)
                    )
                )
            )

        loops = tuple(
            profile_node(p, slab)
            for p in sorted(slab.loops, key=loop_area, reverse=True)
        )
        node = SlabExtrusion(
            height=slab.height,
            profile=loops[0],
            loops=loops,
            bottom=slab.position[2],
            face_ids=slab.face_ids,
        )
        bottom = "0" if i == 0 else top_names[i - 1]
        bindings.append(
            Binding(
                node,
                slab.id,
                center=("0", "0", bottom),
                extent=f"{top_names[i]}-({bottom})",
            )
        )
        additive.append(node)
    for f in features:
        labels.extend((fid, f.id, f.kind) for fid in f.face_ids)
        if f.kind == "slab":
            continue
        name = f.id
        if f.kind in ("chamfer", "edge_round"):
            size = f.width if f.kind == "chamfer" else f.radius
            dim = "_width" if f.kind == "chamfer" else "_radius"
            parameter(
                name + dim, size, group=name.replace("_", " ").title(), faces=f.face_ids
            )
            # Face widths perpendicular to the sharp edge, along each host.
            normals = np.asarray(f.rim_normals)
            widths = [float(np.abs(n) @ (upper - lower)) for n in normals]
            limits = [
                (["plate_length", "plate_width", top_names[-1]][int(np.argmax(abs(n)))])
                for n in normals
            ]
            constraint(
                f'{name}{dim} < min({",".join(limits)})',
                "Treatment must fit both host widths",
                f.face_ids,
            )
            if size <= 0 or size >= min(widths):
                raise ValueError("Treatment exceeds its host widths")
            matrix, length, phase = treatment_frame(f, lower, upper)
            node = EdgeCutter(
                kind=f.kind,
                size=size,
                matrix=tuple(map(tuple, matrix)),
                length=length,
                segments=f.segments,
                face_ids=f.face_ids,
            )
            if f.kind == "edge_round":
                parameter(
                    name + "_segments",
                    f.segments,
                    maximum=max(256, f.segments),
                    minimum=3,
                    group="Resolution",
                    faces=f.face_ids,
                )
                constraint(
                    f"{name}_segments >= 3 && {name}_segments == floor({name}_segments)",
                    "Resolution must be an integer of at least 3",
                )
            bindings.append(
                Binding(
                    node,
                    name,
                    center=tuple(coord(v, j) for j, v in enumerate(matrix[:3, 3])),
                    phase_deg=phase,
                    extent=["plate_length", "plate_width", top_names[-1]][
                        int(np.argmax(abs(matrix[:3, 2])))
                    ],
                )
            )
            cuts.append(node)
        elif f.kind == "remainder":
            triangles = (np.asarray(f.remainder_triangles) - frame[:3, 3]) @ frame[
                :3, :3
            ]
            if not triangles.size or not np.isfinite(triangles).all():
                raise ValueError("Remainder needs finite closed triangles")
            points, indices = np.unique(
                triangles.reshape(-1, 3), axis=0, return_inverse=True
            )
            node = RegionSolid(
                points=tuple(map(tuple, points)),
                triangles=tuple(
                    tuple(map(int, row)) for row in indices.reshape(-1, 3)[:, ::-1]
                ),
                face_ids=f.face_ids,
            )
            bindings.append(Binding(node, name))
            (additive if f.polarity == "additive" else cuts).append(node)
        elif f.kind == "fillet":
            if (
                f.corner is None
                or f.radius is None
                or not np.allclose(f.axis, [0, 0, 1])
            ):
                raise ValueError(
                    "Fillet needs its two hosts and an extrusion-aligned sharp corner"
                )
            parameter(
                name + "_radius",
                f.radius,
                group=name.replace("_", " ").title(),
                faces=f.face_ids,
            )
            parameter(
                name + "_segments",
                f.segments or 64,
                maximum=max(256, f.segments or 64),
                minimum=3,
                group="Resolution",
            )
            node = ir.Fillet(
                radius=f.radius,
                face1_id=f.between[0],
                face2_id=f.between[1],
                face_ids=f.face_ids,
            )
            corner = tuple(coord(v, j) for j, v in enumerate(f.corner))
            direction = np.sign(np.asarray(f.position) - f.corner)
            center = tuple(
                f"({corner[j]}){'+' if direction[j] > 0 else '-'}{name}_radius"
                for j in range(2)
            ) + (corner[2],)
            phase = (
                float(
                    np.degrees(np.arctan2(f.radial_reference[1], f.radial_reference[0]))
                )
                if f.radial_reference is not None
                else 0.0
            )
            bindings.append(
                Binding(
                    node,
                    name,
                    center=center,
                    corner=corner,
                    phase_deg=phase,
                    extent=top_names[-1],
                )
            )
            constraint(
                f"{name}_radius < min(plate_length,plate_width)",
                "Fillet must fit its host legs",
                f.face_ids,
            )
            additive.append(node)
        elif f.kind in ("boss", "blind_hole", "through_hole"):
            group = name.replace("_", " ").title()
            if f.kind == "through_hole":
                paired = any(
                    other.kind == "blind_hole"
                    and np.linalg.norm(
                        np.cross(np.asarray(other.position) - f.position, f.axis)
                    )
                    < tolerance
                    for other in features
                )
                if not paired:
                    group = (
                        name.replace("through_hole", "hole").replace("_", " ").title()
                    )
            parameter(
                name + "_radius",
                f.radius,
                group=group,
                faces=f.face_ids,
            )
            parameter(
                name + "_segments",
                f.segments or 64,
                maximum=max(256, f.segments or 64),
                minimum=3,
                group="Resolution",
            )
            length = f.height if f.kind == "boss" else f.depth
            dimension = "_height" if f.kind == "boss" else "_depth"
            parameter(
                name + dimension,
                length,
                group=group,
                faces=f.face_ids,
            )
            if f.kind == "through_hole":
                node = ir.HoleThrough(
                    diameter=2 * f.radius,
                    depth=length,
                    axis="arbitrary",
                    extra_fields=(
                        ("direction", f.axis),
                        ("rim_normals", f.rim_normals),
                    ),
                    face_ids=f.face_ids,
                )
            else:
                cls = ir.Boss if f.kind == "boss" else ir.HoleBlind
                node = cls(
                    radius=f.radius,
                    **{"height" if f.kind == "boss" else "depth": length},
                    center=f.position,
                    axis=f.axis,
                    host_face_id=f.on_face,
                    face_ids=f.face_ids,
                )
            from .fitting import cylinder_phase

            bindings.append(
                Binding(
                    node,
                    name,
                    center=tuple(coord(v, j) for j, v in enumerate(f.position)),
                    phase_deg=cylinder_phase(f.axis, f.radial_reference),
                )
            )
            (additive if f.kind == "boss" else cuts).append(node)
        else:
            raise ValueError(f"Unsupported composed feature: {f.kind}")
    constraint(
        " && ".join(p.name + " > 0" for p in parameters if p.min > 0),
        "Dimensions must stay positive",
    )
    root = ir.TransformMultMatrix(
        matrix=slabs[0].part_frame,
        child=ir.BooleanDifference(
            base=ir.BooleanUnion(children=tuple(additive)), cuts=tuple(cuts)
        ),
    )
    # One Customizer heading per semantic group; resolution controls must not
    # split Hole/Blind Hole groups and inflate the fixture feature counts.
    groups = list(
        dict.fromkeys(p.group for p in parameters if p.group != "Resolution")
    ) + ["Resolution"]
    ordered = tuple(p for group in groups for p in parameters if p.group == group)
    return ParametricModel(
        root, ordered, tuple(constraints), tuple(bindings), tuple(labels)
    )


def geometry_scad(model):
    """Traverse composition nodes, preserving analytic paths and region polarity."""
    from .emit import _array, _number
    from .section_emit import HELPERS

    bindings = {id(b.node): b for b in model.bindings}
    lines = [HELPERS, "_join_epsilon = max(plate_length,plate_width)*0.000001;"]

    def vec(values):
        return "[" + ",".join(values) + "]"

    def sketch(node):
        b = bindings.get(id(node))
        if isinstance(node, ir.Sketch2D):
            return vec([vec(p) for p in b.points])
        parts = []
        for segment in node.segments:
            b = bindings[id(segment)]
            if isinstance(segment, ir.SketchArc2D):
                radius, resolution = (
                    b.radius or b.name + "_radius",
                    b.resolution or b.name + "_segments",
                )
                args = f"{vec(b.center[:2])},{radius}"
                for label, angle in [
                    ("start", segment.start_deg),
                    ("end", segment.start_deg + segment.sweep_deg),
                ]:
                    lines.append(
                        f"_{b.name}_{label} = _arc_point({args},{_number(angle)},{_number(segment.phase_deg)},{resolution});"
                    )
                parts.append(
                    f"_arc({args},{_number(segment.start_deg)},{_number(segment.sweep_deg)},{_number(segment.phase_deg)},{resolution})"
                )
            else:
                parts.append(vec([vec(p) for p in b.points]))
        return "concat(" + ",".join(parts) + ")"

    outlines = {}
    for b in model.bindings:
        if isinstance(b.node, SlabExtrusion):
            names = []
            for j, loop in enumerate(b.node.loops):
                name = f"_{b.name}_loop_{j+1}"
                expression = sketch(loop)
                lines.append(f"{name} = {expression};")
                names.append(name)
            outlines[id(b.node)] = names
    lines += [
        f"assert({c.expression}, {json.dumps(c.message)});" for c in model.constraints
    ]

    def walk(node):
        if isinstance(node, ir.TransformMultMatrix):
            return "multmatrix(" + _array(node.matrix) + ")\n" + walk(node.child)
        if isinstance(node, ir.BooleanUnion):
            return "union() {\n" + "\n".join(map(walk, node.children)) + "\n}"
        if isinstance(node, ir.BooleanDifference):
            return (
                "difference() {\n"
                + walk(node.base)
                + "\n"
                + "\n".join(map(walk, node.cuts))
                + "\n}"
            )
        b = bindings[id(node)]
        comments = (
            "\n".join(
                f"// face {fid} {b.name} ({type(node).__name__})"
                for fid in node.face_ids
            )
            + "\n"
        )
        if isinstance(node, SlabExtrusion):
            names = outlines[id(node)]
            # OpenSCAD paths implement all CCW islands and CW holes by winding.
            points = "concat(" + ",".join(names) + ")"
            offset, paths = "0", []
            for name in names:
                paths.append(f"[for(i=[0:len({name})-1]) ({offset})+i]")
                offset += "+len(" + name + ")"
            source = f"translate({vec(b.center)}) linear_extrude(height={b.extent}) polygon(points={points},paths={vec(paths)});"
        elif isinstance(node, EdgeCutter):
            dim = b.name + ("_width" if node.kind == "chamfer" else "_radius")
            matrix = np.asarray(node.matrix).copy()
            matrix[:3, 3] = 0
            transform = f"translate({vec(b.center)}) multmatrix({_array(matrix)}) translate([0,0,-_join_epsilon]) linear_extrude(height={b.extent or _number(node.length)}+2*_join_epsilon) "
            if node.kind == "chamfer":
                source = (
                    transform
                    + f"polygon([[-_join_epsilon,-_join_epsilon],[{dim}+_join_epsilon,-_join_epsilon],[-_join_epsilon,{dim}+_join_epsilon]]);"
                )
            else:
                source = (
                    transform
                    + f"difference() {{ translate([-_join_epsilon,-_join_epsilon]) square([{dim}+_join_epsilon,{dim}+_join_epsilon]); translate([{dim},{dim}]) rotate({_number(b.phase_deg)}) circle(r={dim},$fn={b.name}_segments); }}"
                )
        elif isinstance(node, RegionSolid):
            source = f"polyhedron(points={_array(node.points)},faces={json.dumps(node.triangles)},convexity=10);"
        elif isinstance(node, ir.Fillet):
            corner = [
                f"({b.corner[j]})+sign(({b.corner[j]})-({b.center[j]}))*_join_epsilon"
                for j in range(2)
            ]
            x, y = b.center[:2]
            source = f"linear_extrude(height={b.extent}) difference() {{ polygon(points=[[{corner[0]},{corner[1]}],[{x},{corner[1]}],[{x},{y}],[{corner[0]},{y}]]); translate([{x},{y}]) rotate({_number(b.phase_deg)}) circle(r={b.name}_radius,$fn={b.name}_segments); }}"
        elif isinstance(node, (ir.Boss, ir.HoleBlind, ir.HoleThrough)):
            # Same axis convention used by cylinder_phase (orthogonal u/v).
            axis = np.asarray(
                (
                    dict(node.extra_fields)["direction"]
                    if isinstance(node, ir.HoleThrough)
                    else node.axis
                ),
                float,
            )
            turn = np.cross([0.0, 0.0, 1.0], axis)
            cosine = float(axis[2])
            if np.linalg.norm(turn) < 1e-8:
                rotation = np.eye(3) if cosine > 0 else np.diag([1.0, -1.0, -1.0])
            else:
                sine = np.linalg.norm(turn)
                x, y, z = turn / sine
                cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
                rotation = np.eye(3) + sine * cross + (1 - cosine) * cross @ cross
            matrix = np.eye(4)
            matrix[:3, :3] = rotation
            length = b.name + ("_height" if isinstance(node, ir.Boss) else "_depth")
            center = tuple(
                f"({v})-({_number(axis[j])})*_join_epsilon"
                for j, v in enumerate(b.center)
            )
            source = f"translate({vec(center)}) multmatrix({_array(matrix)}) rotate([0,0,{_number(b.phase_deg)}]) cylinder(r={b.name}_radius,h={length}+2*_join_epsilon,$fn={b.name}_segments);"
        else:
            raise ValueError(f"Unsupported composition IR node: {type(node).__name__}")
        return comments + source

    return "\n".join(lines) + "\n" + walk(model.root) + "\n"
