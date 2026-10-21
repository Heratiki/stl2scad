"""Typed IR to editable SCAD, with rendering, snapping and whole-mesh fallback."""

from dataclasses import replace
import json

import numpy as np
from stl.mesh import Mesh

from .. import ir
from ..openscad.runner import get_openscad_path, run_openscad
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


# Snapping removes float noise from measured values (5.0000021 -> 5). It must
# not move a real design value such as 51.1 to 51, even when the gate passes.
SNAP_MAX_SHIFT_MM = 1e-3


def _snap(raw: float, grid: float) -> float:
    """The raw value on the grid, or the raw value when the grid moves it too far."""
    value = float(np.round(raw / grid) * grid)
    return value if abs(value - raw) <= SNAP_MAX_SHIFT_MM else raw


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
    from .compose_ir import SlabExtrusion, geometry_scad as compose_geometry

    if any(isinstance(b.node, SlabExtrusion) for b in model.bindings):
        return "\n".join(lines) + "\n" + compose_geometry(model)
    if any(
        isinstance(b.node, ir.ExtrudeLinear)
        and isinstance(b.node.profile, ir.SketchPath2D)
        for b in model.bindings
    ):
        from .section_emit import geometry_scad

        return "\n".join(lines + geometry_scad(model)) + "\n"
    lines.extend(
        [
            "/* [Hidden] */",
            "$fn = 64;",
            (
                "_join_epsilon = 0;"
                if isinstance(model.root.child, ir.PrimitiveCylinder)
                else "_join_epsilon = max(body_width, body_depth)*0.000001;"
            ),
        ]
    )
    from .profile_geometry import PROFILE_DEPTH_SCAD

    lines.append(PROFILE_DEPTH_SCAD)
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
        elif isinstance(node, ir.PrimitiveCylinder):
            out.append(
                pad + f"cylinder(r={name}_radius,h={name}_height,$fn={name}_segments);"
            )
        elif isinstance(node, (ir.Boss, ir.HoleBlind, ir.HoleThrough)):
            through = isinstance(node, ir.HoleThrough)
            extra = dict(node.extra_fields) if through else {}
            axis = np.array(extra["direction"] if through else node.axis, dtype=float)
            axis[np.abs(axis) < 1e-7] = 0
            axis /= np.linalg.norm(axis)
            angle = np.degrees(np.arccos(np.clip(axis[2], -1, 1)))
            turn = np.cross([0.0, 0.0, 1.0], axis)
            if np.linalg.norm(turn) < 1e-8:
                turn = np.array([1.0, 0.0, 0.0])
            pads = [0.0, 0.0]
            if through:
                pads = [
                    np.sqrt(max(0.0, 1 / np.dot(n, axis) ** 2 - 1))
                    for n in extra["rim_normals"]
                ]
            start_pad = (
                f"({_number(pads[0])})*{name}_radius+_join_epsilon"
                if through
                else "_join_epsilon"
            )
            center = [
                f"({v})-({_number(axis[i])})*({start_pad})" if axis[i] else v
                for i, v in enumerate(binding.center)
            ]
            length = (
                f"({binding.extent})+({_number(sum(pads))})*{name}_radius+_join_epsilon"
                if through
                else name + ("_height" if isinstance(node, ir.Boss) else "_depth")
            )
            out.append(
                pad
                + f'translate([{", ".join(center)}]) rotate(a={_number(angle)}, v={_array(turn)}) rotate([0,0,{_number(binding.phase_deg)}]) cylinder(r={name}_radius, h={length}+_join_epsilon, $fn={name}_segments);'
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
                pad
                + f"  translate([{x}, {y}]) rotate({_number(binding.phase_deg)}) circle(r={name}_radius, $fn={name}_segments);",
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
        scad.write_text(source, encoding="utf-8")
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
    result = None
    try:
        if features is None:
            from .features import detect_features
            from .pipeline import segment_mesh

            result = segment_mesh(mesh)
            features = detect_features(result)
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
                replace(p, value=_snap(p.raw_value, grid)) for p in model.parameters
            )
            if any(p.value < p.min or p.value > p.max for p in candidate):
                continue
            distance, candidate_source = evaluate(candidate)
            if distance <= limit:
                best, measured, source = candidate, distance, candidate_source
                break
        for i, parameter in enumerate(best):
            for grid in (1.0, 0.1, 0.01):
                value = _snap(parameter.raw_value, grid)
                if value == parameter.value:
                    continue
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
        return (
            _header(mesh, source_file, measured, raw_distance)
            + _remainder_header(features, mesh, result=result)
            + source
        )
    except Exception as exc:
        # Composition is an extension of the existing detector. If its later
        # IR/render stage cannot prove the part, preserve the original public
        # rejection rather than exposing an adapter-specific diagnostic.
        reason = str(exc)
        if features and any(f.kind == "slab" for f in features):
            from .features import _detect_existing
            from .pipeline import segment_mesh

            try:
                _detect_existing(result if result is not None else segment_mesh(mesh))
            except ValueError as original:
                reason = str(original)
        return fallback_scad(mesh, reason, source_file=source_file, measured=measured)


def _remainder_header(features, mesh, *, result=None):
    regions = [f for f in features if f.kind == "remainder"]
    if not regions:
        return ""
    from .pipeline import segment_mesh
    from .remainder import free_form_share

    if result is None:
        result = segment_mesh(mesh)
    areas = {
        f.id: float(
            result.mesh.areas[
                np.isin(result.mesh.source_indices, f.triangle_indices)
            ].sum()
        )
        for f in result.faces
    }
    lines = [
        f"// Free-form region {f.id}: faces {', '.join(f.face_ids)}, area {_number(sum(areas[fid] for fid in f.face_ids))} mm2, reason {_clean(f.reason or 'unexplained surface')}"
        for f in regions
    ]
    lines.append(
        f"// Free-form share: {_number(100 * free_form_share(result, regions))} % (limit 10 %)"
    )
    return "\n".join(lines) + "\n"
