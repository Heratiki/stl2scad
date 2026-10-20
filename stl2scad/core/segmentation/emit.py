"""Typed IR to editable SCAD, with rendering, snapping and whole-mesh fallback."""

from dataclasses import replace
import json

import numpy as np
from stl.mesh import Mesh

from .. import ir
from ..converter import get_openscad_path, run_openscad
from ..temp_paths import temporary_directory
from .solid import mesh_hausdorff
from .to_ir import ParametricModel, features_to_ir


def _number(value):
    value = float(value)
    if abs(value) < 1e-12:
        value = 0.0
    return np.format_float_positional(
        value, precision=12, unique=False, fractional=False, trim="-"
    )


def _array(value):
    if isinstance(value, (tuple, list, np.ndarray)):
        return "[" + ", ".join(_array(v) for v in value) + "]"
    return _number(value)


def gate_limit_mm(mesh: Mesh) -> float:
    return max(
        0.05,
        0.001
        * float(
            np.linalg.norm(np.ptp(mesh.vectors.reshape(-1, 3).astype(float), axis=0))
        ),
    )


def _clean(text):
    return " ".join(str(text).split()).replace("*/", "* /")


def fallback_scad(mesh, reason, *, source_file=None, measured=None):
    points, indices = np.unique(
        mesh.vectors.reshape(-1, 3), axis=0, return_inverse=True
    )
    # OpenSCAD polyhedron uses clockwise outward faces, opposite STL winding.
    faces = indices.reshape(-1, 3)[:, ::-1]
    return (
        _header(mesh, source_file, measured)
        + "// Full mesh fallback: "
        + _clean(reason)
        + "\n"
        + "polyhedron(points="
        + _array(points)
        + ", faces="
        + json.dumps(faces.tolist(), separators=(",", ":"))
        + ", convexity=10);\n"
    )


def _header(mesh, source_file, measured, raw=None):
    source = (
        source_file
        or getattr(mesh, "source_file", None)
        or getattr(mesh, "name", None)
        or "unknown"
    )
    if isinstance(source, bytes):
        source = source.decode(errors="replace")
    return (
        "// Source: "
        + _clean(source)
        + "\n"
        + f"// Gate limit: {_number(gate_limit_mm(mesh))} mm; measured Hausdorff: "
        + (_number(measured) + " mm" if measured is not None else "unavailable")
        + "\n"
        + (
            f"// Before snapping Hausdorff: {_number(raw)} mm\n"
            if raw is not None
            else ""
        )
        + "// How to edit: change Customizer parameters; host expressions move attached features.\n"
        + "// Assertions stop edits that violate linked dimensions. Distances are in mm.\n"
    )


def ir_to_scad(model: ParametricModel) -> str:
    """Emit geometry by traversing typed IR, with bindings for editable values."""
    lines = []
    group = None
    for p in model.parameters:
        if group != p.group:
            group = p.group
            lines.append(f"/* [{group}] */")
        # The Customizer takes the description from the comment line above and
        # parses the range only when it ends the assignment line.
        lines.append(f"// {p.description} (raw {_number(p.raw_value)})")
        lines.append(
            f"{p.name} = {_number(p.value)}; // [{_number(p.min)}:{_number(p.step)}:{_number(p.max)}]"
        )
    lines.extend(
        [
            "/* [Hidden] */",
            "$fn = 64;",
            "_join_epsilon = max(body_width, body_depth)*0.000001;",
        ]
    )
    for constraint in model.constraints:
        lines.append(
            f"assert({constraint.expression}, {json.dumps(constraint.message)});"
        )
    labels = {face: (label, kind) for face, label, kind in model.labels}

    def walk(node, indent=0):
        pad = "  " * indent
        binding = next((b for b in model.bindings if b.node is node), None)
        if isinstance(node, ir.TransformMultMatrix):
            return [pad + "multmatrix(" + _array(node.matrix) + ")"] + walk(
                node.child, indent
            )
        if isinstance(node, ir.BooleanDifference):
            out = [pad + "difference() {"] + walk(node.base, indent + 1)
            for cut in node.cuts:
                out += walk(cut, indent + 1)
            return out + [pad + "}"]
        if isinstance(node, ir.BooleanUnion):
            out = [pad + "union() {"]
            for child in node.children:
                out += walk(child, indent + 1)
            return out + [pad + "}"]
        if binding is None:
            raise ValueError(f"Missing parameter binding for {type(node).__name__}")
        out = [
            pad + f"// face {face} {labels[face][0]} ({labels[face][1]})"
            for face in node.face_ids
        ]
        name = binding.name
        if isinstance(node, ir.ExtrudeLinear):
            if not isinstance(node.profile, ir.Sketch2D):
                raise ValueError("ExtrudeLinear requires a Sketch2D")
            for index, point in enumerate(binding.points):
                out.append(pad + f'// P{index} = [{", ".join(point)}]')
            polygon = (
                "[" + ", ".join("[" + ", ".join(p) + "]" for p in binding.points) + "]"
            )
            out.append(
                pad + f"linear_extrude(height=body_depth) polygon(points={polygon});"
            )
        elif isinstance(node, (ir.Boss, ir.HoleBlind)):
            axis = np.array(node.axis, dtype=float)
            axis[np.abs(axis) < 1e-7] = 0
            axis /= np.linalg.norm(axis)
            angle = np.degrees(np.arccos(np.clip(axis[2], -1, 1)))
            turn = np.cross([0.0, 0.0, 1.0], axis)
            if np.linalg.norm(turn) < 1e-8:
                turn = np.array([1.0, 0.0, 0.0])
            center = [
                f"({v})-({_number(axis[i])})*_join_epsilon" if axis[i] else v
                for i, v in enumerate(binding.center)
            ]
            length = name + ("_height" if isinstance(node, ir.Boss) else "_depth")
            out.append(
                pad
                + f'translate([{", ".join(center)}]) rotate(a={_number(angle)}, v={_array(turn)}) cylinder(r={name}_radius, h={length}+_join_epsilon);'
            )
        elif isinstance(node, ir.Fillet):
            # Enter the hosts slightly, avoiding near-coincident internal faces.
            corner = [
                f"({binding.corner[i]})+sign(({binding.corner[i]})-({binding.center[i]}))*_join_epsilon"
                for i in range(2)
            ]
            x, y = binding.center[:2]
            out += [
                pad + "linear_extrude(height=body_depth) difference() {",
                pad
                + f"  polygon(points=[[{corner[0]}, {corner[1]}], [{x}, {corner[1]}], [{x}, {y}], [{corner[0]}, {y}]]);",
                pad + f"  translate([{x}, {y}]) circle(r={name}_radius);",
                pad + "}",
            ]
        else:
            raise ValueError(f"Unsupported IR node: {type(node).__name__}")
        return out

    return "\n".join(lines + walk(model.root)) + "\n"


def render_scad(source: str) -> Mesh:
    with temporary_directory(prefix="segmentation-emit") as directory:
        scad, stl, log = (
            directory / "model.scad",
            directory / "model.stl",
            directory / "render.log",
        )
        scad.write_text(source)
        if (
            not run_openscad(
                "Editable segmentation gate",
                ["--render", "-o", stl.as_posix(), scad.as_posix()],
                log.as_posix(),
                get_openscad_path(),
            )
            or not stl.exists()
        ):
            raise RuntimeError(
                "SCAD render failed: " + (log.read_text() if log.exists() else "no log")
            )
        return Mesh.from_file(stl.as_posix())


def emit_scad(features, mesh: Mesh, *, source_file=None) -> str:
    """Emit only a measured, passing model; otherwise return the entire input mesh.

    Passing None requests segmentation/detection inside the fallback boundary,
    allowing the CLI to preserve unsupported parts after detection exceptions.
    """
    measured = None
    try:
        if features is None:
            from .features import detect_features
            from .pipeline import segment_mesh

            features = detect_features(segment_mesh(mesh))
        model = features_to_ir(list(features))
        limit = gate_limit_mm(mesh)
        cache = {}

        def evaluate(parameters):
            key = tuple(p.value for p in parameters)
            if key not in cache:
                candidate = replace(model, parameters=tuple(parameters))
                source = ir_to_scad(candidate)
                try:
                    distance = mesh_hausdorff(render_scad(source), mesh)
                except (RuntimeError, ValueError):
                    distance = float("inf")
                cache[key] = (distance, source)
            return cache[key]

        measured, source = evaluate(model.parameters)
        raw_distance = measured
        if not np.isfinite(measured) or measured > limit:
            raise ValueError("Unsnapped feature solid failed the Hausdorff gate")
        best = model.parameters
        # Find a globally passing grid first; then promote individual values
        # back to coarser grids, retaining each promotion only after rendering.
        for grid in (1.0, 0.1, 0.01):
            candidate = tuple(
                replace(p, value=float(np.round(p.raw_value / grid) * grid))
                for p in model.parameters
            )
            if any(p.value < p.min or p.value > p.max for p in candidate):
                continue
            distance, candidate_source = evaluate(candidate)
            if distance <= limit:
                best, measured, source = candidate, distance, candidate_source
                break
        for i, parameter in enumerate(best):
            for grid in (1.0, 0.1, 0.01):
                value = float(np.round(parameter.raw_value / grid) * grid)
                if value < parameter.min or value > parameter.max:
                    continue
                candidate = list(best)
                candidate[i] = replace(parameter, value=value)
                distance, candidate_source = evaluate(candidate)
                if distance <= limit:
                    best, measured, source = (
                        tuple(candidate),
                        distance,
                        candidate_source,
                    )
                    break
        return _header(mesh, source_file, measured, raw_distance) + source
    except Exception as exc:
        return fallback_scad(mesh, str(exc), source_file=source_file, measured=measured)
