"""
Feature graph prototype for editable parametric reconstruction.

The graph is an intermediate representation: it describes high-confidence
feature candidates without committing to SCAD generation yet.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy as np
from stl.mesh import Mesh

from .feature_inventory import _bbox, _normalized_normals, _triangle_areas

STL_SUFFIXES = {".stl"}
PREVIEW_SOLID_CONFIDENCE_THRESHOLD = 0.70
# Allow tiny numeric drift around the preview threshold while staying conservative.
PREVIEW_SOLID_CONFIDENCE_EPSILON = 0.002


from stl2scad.tuning.config import DetectorConfig


def _passes_preview_solid_confidence(confidence: Any) -> bool:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return False
    return value + PREVIEW_SOLID_CONFIDENCE_EPSILON >= PREVIEW_SOLID_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Detector Intermediate Representation (IR) tree builder
# ---------------------------------------------------------------------------
# Maps flat feature `type` strings to IR node types.
_SOLID_TO_IR_TYPE: dict[str, str] = {
    "plate_like_solid": "PrimitivePlate",
    "box_like_solid": "PrimitiveBox",
    "cylinder_like_solid": "PrimitiveCylinder",
}
_CUTOUT_TO_IR_TYPE: dict[str, str] = {
    "hole_like_cutout": "HoleThrough",
    "slot_like_cutout": "Slot",
    "counterbore_hole": "HoleCounterbore",
    "rectangular_cutout": "RectangularCutout",
    "rectangular_pocket": "RectangularPocket",
}
_PATTERN_TO_IR_TYPE: dict[str, str] = {
    "linear_hole_pattern": "PatternLinear",
    "grid_hole_pattern": "PatternGrid",
}
# Internal detector bookkeeping types that don't appear in the IR.
_INTERNAL_FEATURE_TYPES: frozenset[str] = frozenset({"axis_boundary_plane_pair"})


def _ir_cutout_node(cutout: dict[str, Any]) -> dict[str, Any]:
    """Convert a flat cutout feature dict to an IR cutout node.

    If the cutout has a 'center' field it is lifted into a wrapping
    TransformTranslate so the child node describes *what* the cutout is and
    the transform describes *where* it sits.
    """
    ir_type = _CUTOUT_TO_IR_TYPE[cutout["type"]]
    # Fields to strip from the payload (type/bookkeeping already handled).
    _STRIP = {"type", "confidence", "note", "parent_type", "source_parent_type"}

    if "center" in cutout:
        center = [float(v) for v in cutout["center"]]
        child_fields = {k: v for k, v in cutout.items() if k not in _STRIP | {"center"}}
        return {
            "type": "TransformTranslate",
            "offset": center,
            "child": {"type": ir_type, **child_fields},
        }

    payload = {k: v for k, v in cutout.items() if k not in _STRIP}
    return {"type": ir_type, **payload}


def _ir_pattern_node(pattern: dict[str, Any]) -> dict[str, Any]:
    """Convert a flat pattern feature dict to an IR PatternLinear/PatternGrid node."""
    ir_type = _PATTERN_TO_IR_TYPE[pattern["type"]]
    hole_child: dict[str, Any] = {
        "type": "HoleThrough",
        "axis": pattern.get("axis"),
        "diameter": float(pattern.get("diameter", 0.0)),
    }
    if pattern["type"] == "linear_hole_pattern":
        return {
            "type": ir_type,
            "origin": pattern.get("pattern_origin"),
            "step": pattern.get("pattern_step"),
            "count": int(pattern.get("pattern_count", 0)),
            "spacing": float(pattern.get("pattern_spacing", 0.0)),
            "diameter": float(pattern.get("diameter", 0.0)),
            "axis": pattern.get("axis"),
            "child": hole_child,
        }
    # grid_hole_pattern
    return {
        "type": ir_type,
        "origin": pattern.get("grid_origin"),
        "row_step": pattern.get("grid_row_step"),
        "col_step": pattern.get("grid_col_step"),
        "rows": int(pattern.get("grid_rows", 0)),
        "cols": int(pattern.get("grid_cols", 0)),
        "diameter": float(pattern.get("diameter", 0.0)),
        "axis": pattern.get("axis"),
        "child": hole_child,
    }


def _axis_to_world_z_euler_xyz(axis: list[float]) -> list[float]:
    """Return Euler XYZ angles in degrees that rotate world Z onto `axis`."""
    a = np.asarray(axis, dtype=np.float64)
    a = a / float(np.linalg.norm(a))
    z = np.array([0.0, 0.0, 1.0])
    if np.allclose(a, z, atol=1e-6):
        return [0.0, 0.0, 0.0]
    if np.allclose(a, -z, atol=1e-6):
        return [180.0, 0.0, 0.0]
    v = np.cross(z, a)
    s = float(np.linalg.norm(v))
    c = float(np.dot(z, a))
    vx = np.array([
        [0, -v[2], v[1]],
        [v[2], 0, -v[0]],
        [-v[1], v[0], 0],
    ])
    R = np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s))
    rx = float(np.degrees(np.arctan2(R[2, 1], R[2, 2])))
    ry = float(np.degrees(np.arcsin(-R[2, 0])))
    rz = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    return [rx, ry, rz]


def _ir_revolve_node(feature: dict[str, Any]) -> dict[str, Any]:
    points = [[float(r), float(z)] for r, z in feature["profile"]]
    sketch: dict[str, Any] = {"type": "Sketch2D", "kind": "polygon", "points": points}
    extrude: dict[str, Any] = {"type": "ExtrudeRevolve", "profile": sketch}
    angles = _axis_to_world_z_euler_xyz(feature["axis"])
    return {"type": "TransformRotate", "angles_deg": angles, "child": extrude}


def _build_ir_tree(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a ranked list of IR Interpretation nodes from a flat feature graph.

    Each Interpretation wraps the detected geometry in a boolean tree:

    * A solid with cutouts → ``BooleanDifference { base: Primitive, cuts: [...] }``
    * A solid with no cutouts → ``BooleanUnion { children: [Primitive] }``
    * No solid detected → a single ``FallbackMesh`` Interpretation

    Cutouts that belong to a pattern are subsumed into ``PatternLinear`` /
    ``PatternGrid`` nodes; standalone cutouts are wrapped in
    ``TransformTranslate`` nodes that carry their placement.

    This is an additive representation — ``graph["features"]`` is unchanged.
    """
    features = graph.get("features", [])

    # Revolve solids take priority (Rule 1 + Rule 3): return early when present.
    revolve_feats = [f for f in features if f.get("type") == "revolve_solid"]
    if revolve_feats:
        revolve = revolve_feats[0]
        root = {
            "type": "BooleanUnion",
            "children": [_ir_revolve_node(revolve)],
        }
        return [{
            "type": "Interpretation",
            "rank": 1,
            "confidence": float(revolve["confidence"]),
            "root": root,
        }]

    primitives = sorted(
        [f for f in features if f.get("type") in _SOLID_TO_IR_TYPE],
        key=lambda f: float(f.get("confidence", 0.0)),
        reverse=True,
    )

    if not primitives:
        return [
            {
                "type": "Interpretation",
                "confidence": 0.0,
                "rank": 0,
                "root": {"type": "FallbackMesh"},
            }
        ]

    # Collect hole centers that are claimed by any pattern so they are not
    # also emitted as standalone HoleThrough cuts.
    pattern_features = [
        f
        for f in features
        if f.get("type") in _PATTERN_TO_IR_TYPE
        and float(f.get("confidence", 0.0)) >= PREVIEW_SOLID_CONFIDENCE_THRESHOLD
    ]
    pattern_center_keys: set[tuple[float, float, float]] = set()
    for pat in pattern_features:
        for center in pat.get("centers", []):
            pattern_center_keys.add(tuple(round(float(v), 4) for v in center))

    interpretations: list[dict[str, Any]] = []
    for rank, prim in enumerate(primitives):
        solid_type = prim["type"]
        ir_prim: dict[str, Any] = {
            "type": _SOLID_TO_IR_TYPE[solid_type],
            "confidence": float(prim.get("confidence", 0.0)),
        }
        for key in ("origin", "size", "axis", "radius", "height"):
            if key in prim:
                ir_prim[key] = prim[key]

        # Wrap rotated primitives in a TransformRotate node so the IR tree
        # encodes the orientation explicitly rather than burying it in metadata.
        if prim.get("detected_via") == "rotated_plate":
            angles = prim.get("rotation_euler_deg", [0.0, 0.0, 0.0])
            ir_prim = {
                "type": "TransformRotate",
                "angles_deg": angles,
                "child": ir_prim,
            }

        # Cutouts associated with this solid.
        solid_cutouts = [
            f
            for f in features
            if f.get("type") in _CUTOUT_TO_IR_TYPE
            and float(f.get("confidence", 0.0)) >= PREVIEW_SOLID_CONFIDENCE_THRESHOLD
            and f.get("source_parent_type", solid_type) == solid_type
        ]

        # Patterns (all, since they derive from holes already linked to this solid).
        cuts: list[dict[str, Any]] = []

        # Edge treatment: when the solid was detected via the tolerant path (chamfer
        # or fillet on outer edges), add a ChamferOrFilletEdge annotation node.
        # This is a non-subtractive sibling of the base — it documents the edge
        # treatment so the emitter can eventually print editable chamfer/fillet
        # parameters rather than silently approximating them.
        if prim.get("detected_via") == "tolerant_chamfer_or_fillet":
            cuts.append(
                {
                    "type": "ChamferOrFilletEdge",
                    "note": (
                        "Outer edges were detected as chamfered or filleted. "
                        "Kind (chamfer vs fillet) is not yet distinguished by the detector."
                    ),
                }
            )

        for pat in pattern_features:
            cuts.append(_ir_pattern_node(pat))

        for cutout in solid_cutouts:
            # Skip holes that are subsumed by a pattern.
            if cutout.get("type") == "hole_like_cutout" and "center" in cutout:
                key = tuple(round(float(v), 4) for v in cutout["center"])
                if key in pattern_center_keys:
                    continue
            cuts.append(_ir_cutout_node(cutout))

        if cuts:
            root_node: dict[str, Any] = {
                "type": "BooleanDifference",
                "base": ir_prim,
                "cuts": cuts,
            }
        else:
            root_node = {
                "type": "BooleanUnion",
                "children": [ir_prim],
            }

        interpretations.append(
            {
                "type": "Interpretation",
                "confidence": float(prim.get("confidence", 0.0)),
                "rank": rank,
                "root": root_node,
            }
        )

    return interpretations


def build_feature_graph_for_stl(
    stl_file: Union[Path, str],
    root_dir: Optional[Union[Path, str]] = None,
    normal_axis_threshold: Optional[float] = None,
    boundary_tolerance_ratio: Optional[float] = None,
    config: Optional[DetectorConfig] = None,
    inventory_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Build a conservative feature graph for one STL file.

    config overrides defaults; the legacy kwargs override config fields when
    provided, preserving every existing call site.
    """
    resolved = config or DetectorConfig()
    if normal_axis_threshold is not None or boundary_tolerance_ratio is not None:
        import dataclasses
        overrides: dict[str, float] = {}
        if normal_axis_threshold is not None:
            overrides["normal_axis_threshold"] = normal_axis_threshold
        if boundary_tolerance_ratio is not None:
            overrides["boundary_tolerance_ratio"] = boundary_tolerance_ratio
        resolved = dataclasses.replace(resolved, **overrides)
    path = Path(stl_file)
    mesh = Mesh.from_file(str(path))
    vectors = np.asarray(mesh.vectors, dtype=np.float64)
    points = vectors.reshape(-1, 3)
    normals = _normalized_normals(np.asarray(mesh.normals, dtype=np.float64))
    face_areas = _triangle_areas(vectors)
    bbox = _bbox(points)
    box_features = _extract_axis_aligned_box_features(
        vectors,
        normals,
        face_areas,
        bbox,
        config=resolved,
    )
    # --- Rule 1: revolve recovery runs first (Rule 3: one-owner). ---
    from stl2scad.core.revolve_recovery import detect_revolve_solid
    # Deduplicate the per-triangle vertex soup into a clean vertex + index table
    # so that revolve_recovery's covariance and profile computations are not
    # skewed by the repeated vertices present in the raw STL format.
    _rounded = np.round(points, decimals=6)
    _, _inv, _counts = np.unique(
        _rounded, axis=0, return_inverse=True, return_counts=True
    )
    unique_verts, _inv_idx = np.unique(_rounded, axis=0, return_inverse=True)
    triangles_indices = _inv_idx.reshape(-1, 3).astype(np.int64)
    revolve_features = detect_revolve_solid(unique_verts, triangles_indices, config=resolved)
    if revolve_features:
        plane_pairs = [f for f in box_features if f.get("type") == "axis_boundary_plane_pair"]
        features = plane_pairs + revolve_features
    else:
        solid_found = any(
            f.get("type") in ("plate_like_solid", "box_like_solid") for f in box_features
        )
        box_found = any(f.get("type") == "box_like_solid" for f in box_features)
        cylinder_features = (
            []
            if box_found
            else _extract_cylinder_like_solid(
                normals,
                face_areas,
                bbox,
                vertices=vectors,
                config=resolved,
            )
        )
        if cylinder_features:
            plane_pairs = [f for f in box_features if f.get("type") == "axis_boundary_plane_pair"]
            features = plane_pairs + cylinder_features
        else:
            # If no axis-aligned solid was found, try the rotated-plate detector.
            rotated_plate_features = (
                _extract_rotated_plate_solid(normals, face_areas, bbox, vectors, resolved)
                if not solid_found
                else []
            )
            features = box_features + rotated_plate_features
    if not revolve_features:
        features.extend(
            _extract_axis_aligned_through_holes(
                vectors,
                normals,
                face_areas,
                bbox,
                features,
                config=resolved,
            )
        )
        features.extend(
            _extract_rotated_plate_through_holes(
                vectors,
                normals,
                face_areas,
                features,
                config=resolved,
            )
        )
        features.extend(_extract_repeated_hole_patterns(features, config=resolved))

    graph: dict[str, Any] = {
        "schema_version": 1,
        "source_file": _relative_or_absolute(path, root_dir),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mesh": {
            "triangles": int(len(vectors)),
            "surface_area": float(np.sum(face_areas)),
            "bounding_box": bbox,
        },
        "features": features,
    }
    if inventory_context is not None:
        graph["inventory_context"] = {
            key: inventory_context[key]
            for key in ("classification", "candidate_features", "detector_guidance")
            if key in inventory_context
        }
        detector_guidance = inventory_context.get("detector_guidance", {})
        graph["detector_plan"] = {
            "source": "inventory_guidance",
            "focus": list(detector_guidance.get("detector_focus", [])),
            "preferred_families": list(detector_guidance.get("preferred_families", [])),
            "symmetry_axes": list(detector_guidance.get("symmetry_axes", [])),
            "regular_spacing_axes": list(
                detector_guidance.get("regular_spacing_axes", [])
            ),
        }
    graph["ir_tree"] = _build_ir_tree(graph)
    return graph


def build_feature_graph_for_folder(
    input_dir: Union[Path, str],
    output_json: Union[Path, str],
    recursive: bool = True,
    max_files: Optional[int] = None,
    workers: int = 1,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    """
    Build feature graphs for STL files in a folder and write a JSON report.
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    if not input_path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_path}")

    pattern = "**/*" if recursive else "*"
    files = sorted(
        path
        for path in input_path.glob(pattern)
        if path.is_file() and path.suffix.lower() in STL_SUFFIXES
    )
    if max_files is not None:
        files = files[:max_files]

    worker_count = max(1, int(workers))
    if worker_count == 1 or len(files) <= 1:
        graphs = []
        for idx, path in enumerate(files, 1):
            graph = _build_feature_graph_for_folder_file(path, input_path)
            graphs.append(graph)
            if progress_callback is not None:
                progress_callback(idx, len(files), str(path))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_path = {
                executor.submit(_build_feature_graph_for_folder_worker, (path, input_path)): path
                for path in files
            }
            graph_map: dict[Path, dict[str, Any]] = {}
            done_count = 0
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                graph_map[path] = future.result()
                done_count += 1
                if progress_callback is not None:
                    progress_callback(done_count, len(files), str(path))
            graphs = [graph_map[path] for path in files]

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_path),
        "config": {
            "recursive": recursive,
            "max_files": max_files,
            "workers": worker_count,
        },
        "summary": _summarize_graphs(graphs),
        "graphs": graphs,
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return report


def _build_feature_graph_for_folder_worker(args: tuple[Path, Path]) -> dict[str, Any]:
    path, input_path = args
    return _build_feature_graph_for_folder_file(path, input_path)


def _build_feature_graph_for_folder_file(
    path: Path, input_path: Path
) -> dict[str, Any]:
    try:
        return build_feature_graph_for_stl(path, root_dir=input_path)
    except Exception as exc:
        return {
            "schema_version": 1,
            "source_file": _relative_or_absolute(path, input_path),
            "status": "error",
            "error": str(exc),
            "features": [],
        }


def _emit_revolve_scad_preview(graph: dict[str, Any], revolve: dict[str, Any]) -> str:
    """Emit parametric SCAD for a revolve_solid feature."""
    axis = [float(v) for v in revolve["axis"]]
    origin = [float(v) for v in revolve["axis_origin"]]
    profile = [(float(r), float(z)) for r, z in revolve["profile"]]

    points_scad = ",\n    ".join(f"[{r:.6f}, {z:.6f}]" for r, z in profile)

    lines: list[str] = [
        "// generated from axisymmetric revolve feature",
        f"// axis = [{axis[0]:.6f}, {axis[1]:.6f}, {axis[2]:.6f}]",
        "revolve_profile = [",
        f"    {points_scad}",
        "];",
        "",
    ]

    angles = _axis_to_world_z_euler_xyz(axis)
    rotation_expr = ""
    if any(abs(a) > 1e-6 for a in angles):
        rotation_expr = f"rotate([{angles[0]:.6f}, {angles[1]:.6f}, {angles[2]:.6f}]) "

    translate_expr = ""
    if any(abs(c) > 1e-6 for c in origin):
        translate_expr = f"translate([{origin[0]:.6f}, {origin[1]:.6f}, {origin[2]:.6f}]) "

    lines.extend([
        f"{translate_expr}{rotation_expr}rotate_extrude($fn=128)",
        "    polygon(points=revolve_profile);",
        "",
    ])
    return "\n".join(lines)


def _emit_cylinder_scad_preview(graph: dict[str, Any], cylinder: dict[str, Any]) -> str:
    """Emit parametric SCAD for a cylinder_like_solid."""
    origin = [float(v) for v in cylinder["origin"]]
    height = float(cylinder["height"])
    diameter = float(cylinder["diameter"])
    axis = str(cylinder.get("axis", "z"))

    lines = [
        "// Feature graph SCAD preview",
        f"// source_file: {graph.get('source_file', '')}",
        "// generated from conservative cylinder feature candidate",
        "",
        f"cylinder_origin = {_scad_vector(origin)};",
        f"cylinder_height = {height:.6f};",
        f"cylinder_diameter = {diameter:.6f};",
        "",
    ]

    # For non-z axes, emit a rotation so OpenSCAD cylinder() (always along z) aligns correctly.
    rotate_expr = {
        "z": "",
        "x": "rotate([0, 90, 0]) ",
        "y": "rotate([-90, 0, 0]) ",
    }.get(axis, "")

    lines.extend([
        "translate(cylinder_origin)",
        f"  {rotate_expr}cylinder(h=cylinder_height, d=cylinder_diameter, center=false);",
        "",
    ])
    return "\n".join(lines)


def _emit_box_scad_preview(graph: dict[str, Any], box: dict[str, Any]) -> str:
    """Emit parametric SCAD for a box_like_solid with optional through-holes."""
    origin = [float(v) for v in box["origin"]]
    size = [float(v) for v in box["size"]]
    axis_depth = {"x": size[0], "y": size[1], "z": size[2]}

    holes = [
        f
        for f in graph.get("features", [])
        if f.get("type") == "hole_like_cutout"
        and float(f.get("confidence", 0.0)) >= 0.70
        and f.get("axis") in axis_depth
    ]

    lines = [
        "// Feature graph SCAD preview",
        f"// source_file: {graph.get('source_file', '')}",
        "// generated from conservative box/hole feature candidates",
        "",
        f"box_origin = {_scad_vector(origin)};",
        f"box_size = {_scad_vector(size)};",
    ]

    for hole_index, hole in enumerate(holes):
        center = [float(v) for v in hole["center"]]
        lines.extend(
            [
                f"hole_{hole_index}_center = {_scad_vector(center)};",
                f"hole_{hole_index}_diameter = {float(hole['diameter']):.6f};",
            ]
        )

    axes_used = sorted({h["axis"] for h in holes})
    for axis in axes_used:
        depth = axis_depth[axis] + 0.2
        lines.extend(
            [
                "",
                f"module hole_cutout_{axis}(center, diameter) {{",
                *_hole_cutout_module_body(depth, axis),
                "}",
            ]
        )

    lines.extend(
        [
            "",
            "difference() {",
            "  translate(box_origin) cube(box_size);",
        ]
    )

    for hole_index, hole in enumerate(holes):
        axis = hole["axis"]
        lines.append(
            f"  hole_cutout_{axis}(hole_{hole_index}_center, hole_{hole_index}_diameter);"
        )

    lines.extend(["}", ""])
    return "\n".join(lines)


def emit_feature_graph_scad_preview(graph: dict[str, Any]) -> Optional[str]:
    """
    Emit conservative SCAD preview for supported feature graph patterns.

        Currently supported:
        - one plate_like_solid
        - optional hole_like_cutout, counterbore_hole, slot_like_cutout,
          rectangular_cutout, and rectangular_pocket features along the plate
          thickness axis
        - one box_like_solid with optional through-holes along any axis
        - one cylinder_like_solid
        - one revolve_solid
    """
    revolve = _best_feature(graph, "revolve_solid")
    if revolve is not None and _passes_preview_solid_confidence(revolve.get("confidence")):
        return _emit_revolve_scad_preview(graph, revolve)

    plate = _best_feature(graph, "plate_like_solid")
    if plate is None or not _passes_preview_solid_confidence(plate.get("confidence")):
        box = _best_feature(graph, "box_like_solid")
        if box is None or not _passes_preview_solid_confidence(box.get("confidence")):
            cylinder = _best_feature(graph, "cylinder_like_solid")
            if cylinder is None or not _passes_preview_solid_confidence(cylinder.get("confidence")):
                return None
            return _emit_cylinder_scad_preview(graph, cylinder)
        return _emit_box_scad_preview(graph, box)

    holes = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "hole_like_cutout"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    # Local-frame holes detected on rotated plates (detected_via == "rotated_plate_local_frame").
    local_holes = [
        h for h in holes if h.get("detected_via") == "rotated_plate_local_frame" and "local_center" in h
    ]
    slots = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "slot_like_cutout"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    counterbores = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "counterbore_hole"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    rectangular_cutouts = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "rectangular_cutout"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    rectangular_pockets = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == "rectangular_pocket"
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]
    origin = [float(value) for value in plate["origin"]]
    size = [float(value) for value in plate["size"]]
    thickness_axis_index = int(np.argmin(size))
    thickness_axis = ("x", "y", "z")[thickness_axis_index]
    supported_patterns = _supported_hole_patterns(graph, thickness_axis)
    linear_pattern_names: dict[int, str] = {}
    grid_pattern_names: dict[int, str] = {}
    emitted_hole_keys: set[tuple[float, float, float]] = set()
    standalone_holes: list[dict[str, Any]] = []

    lines = [
        "// Feature graph SCAD preview",
        f"// source_file: {graph.get('source_file', '')}",
        "// generated from conservative plate/hole feature candidates",
        "",
        f"plate_origin = {_scad_vector(origin)};",
        f"plate_size = {_scad_vector(size)};",
    ]
    if holes or slots or counterbores or rectangular_cutouts or rectangular_pockets or local_holes:
        for pattern_index, pattern in enumerate(supported_patterns):
            if pattern.get(
                "type"
            ) == "linear_hole_pattern" and _has_linear_pattern_fields(pattern):
                pattern_name = f"hole_pattern_{len(linear_pattern_names)}"
                linear_pattern_names[pattern_index] = pattern_name
                origin = [float(value) for value in pattern["pattern_origin"]]
                step = [float(value) for value in pattern["pattern_step"]]
                lines.extend(
                    [
                        f"{pattern_name}_count = {int(pattern['pattern_count'])};",
                        f"{pattern_name}_origin = {_scad_vector(origin)};",
                        f"{pattern_name}_step = {_scad_vector(step)};",
                        f"{pattern_name}_diameter = {float(pattern['diameter']):.6f};",
                    ]
                )
            elif pattern.get(
                "type"
            ) == "grid_hole_pattern" and _has_grid_pattern_fields(pattern):
                pattern_name = f"hole_grid_{len(grid_pattern_names)}"
                grid_pattern_names[pattern_index] = pattern_name
                origin = [float(value) for value in pattern["grid_origin"]]
                row_step = [float(value) for value in pattern["grid_row_step"]]
                col_step = [float(value) for value in pattern["grid_col_step"]]
                lines.extend(
                    [
                        f"{pattern_name}_rows = {int(pattern['grid_rows'])};",
                        f"{pattern_name}_cols = {int(pattern['grid_cols'])};",
                        f"{pattern_name}_origin = {_scad_vector(origin)};",
                        f"{pattern_name}_row_step = {_scad_vector(row_step)};",
                        f"{pattern_name}_col_step = {_scad_vector(col_step)};",
                        f"{pattern_name}_diameter = {float(pattern['diameter']):.6f};",
                    ]
                )
            emitted_hole_keys.update(
                _hole_key([float(value) for value in center])
                for center in pattern.get("centers", [])
            )
        for hole in holes:
            # Local-frame holes on rotated plates are handled separately.
            if hole.get("detected_via") == "rotated_plate_local_frame":
                continue
            if hole.get("axis") != thickness_axis:
                continue
            center = [float(value) for value in hole["center"]]
            if _hole_key(center) in emitted_hole_keys:
                continue
            standalone_holes.append(hole)
        for hole_index, hole in enumerate(standalone_holes):
            lines.extend(
                [
                    f"hole_{hole_index}_center = {_scad_vector([float(value) for value in hole['center']])};",
                    f"hole_{hole_index}_diameter = {float(hole['diameter']):.6f};",
                ]
            )
        for slot_index, slot in enumerate(slots):
            if slot.get("axis") != thickness_axis:
                continue
            lines.extend(
                [
                    f"slot_{slot_index}_start = {_scad_vector([float(value) for value in slot['start']])};",
                    f"slot_{slot_index}_end = {_scad_vector([float(value) for value in slot['end']])};",
                    f"slot_{slot_index}_width = {float(slot['width']):.6f};",
                ]
            )
        for cbore_index, counterbore in enumerate(counterbores):
            if counterbore.get("axis") != thickness_axis:
                continue
            lines.extend(
                [
                    f"counterbore_{cbore_index}_center = {_scad_vector([float(value) for value in counterbore['center']])};",
                    f"counterbore_{cbore_index}_through_diameter = {float(counterbore['through_diameter']):.6f};",
                    f"counterbore_{cbore_index}_bore_diameter = {float(counterbore['bore_diameter']):.6f};",
                    f"counterbore_{cbore_index}_bore_depth = {float(counterbore['bore_depth']):.6f};",
                ]
            )
        for cutout_index, cutout in enumerate(rectangular_cutouts):
            if cutout.get("axis") != thickness_axis:
                continue
            lines.extend(
                [
                    f"rect_cutout_{cutout_index}_center = {_scad_vector([float(value) for value in cutout['center']])};",
                    f"rect_cutout_{cutout_index}_size = {_scad_vector([float(value) for value in cutout['size']])};",
                ]
            )
        for pocket_index, pocket in enumerate(rectangular_pockets):
            if pocket.get("axis") != thickness_axis:
                continue
            lines.extend(
                [
                    f"rect_pocket_{pocket_index}_center = {_scad_vector([float(value) for value in pocket['center']])};",
                    f"rect_pocket_{pocket_index}_size = {_scad_vector([float(value) for value in pocket['size']])};",
                ]
            )
        lines.extend(
            [
                "",
                "module hole_cutout(center, diameter) {",
                *_hole_cutout_module_body(
                    size[thickness_axis_index] + 0.2, thickness_axis
                ),
                "}",
            ]
        )
        if counterbores:
            lines.extend(
                [
                    "",
                    "module counterbore_cutout(center, through_diameter, bore_diameter, bore_depth) {",
                    "  hole_cutout(center, through_diameter);",
                    *_counterbore_bore_module_body(
                        size[thickness_axis_index] + 0.2,
                        thickness_axis,
                    ),
                    "}",
                ]
            )
        if slots:
            lines.extend(
                [
                    "",
                    "module slot_cutout(start, end, width) {",
                    "  hull() {",
                    "    hole_cutout(start, width);",
                    "    hole_cutout(end, width);",
                    "  }",
                    "}",
                ]
            )
        if rectangular_cutouts or rectangular_pockets:
            lines.extend(
                [
                    "",
                    "module rectangular_prism_cutout(center, size) {",
                    "  translate([center[0] - size[0] / 2, center[1] - size[1] / 2, center[2] - size[2] / 2])",
                    "    cube(size);",
                    "}",
                ]
            )
    # For a rotated plate with detected local-frame holes, emit a rotation-wrapped
    # difference block so the holes are bored along the plate normal, not world Z.
    is_rotated_with_local_holes = (
        plate is not None
        and plate.get("detected_via") == "rotated_plate"
        and bool(local_holes)
    )

    if is_rotated_with_local_holes:
        angles = plate.get("rotation_euler_deg", [0.0, 0.0, 0.0])
        depth = float(size[thickness_axis_index])
        # Declare local-frame hole variables.
        for hole_local_index, hole in enumerate(local_holes):
            lc = [float(v) for v in hole["local_center"]]
            lines.extend(
                [
                    f"hole_local_{hole_local_index}_center = {_scad_vector(lc)};",
                    f"hole_local_{hole_local_index}_diameter = {float(hole['diameter']):.6f};",
                ]
            )
        lines.extend(
            [
                "",
                f"translate(plate_origin) rotate([{angles[0]:.6f}, {angles[1]:.6f}, {angles[2]:.6f}]) {{",
                "  difference() {",
                "    cube(plate_size);",
            ]
        )
        for hole_local_index in range(len(local_holes)):
            lines.extend(
                [
                    f"    translate([hole_local_{hole_local_index}_center[0],"
                    f" hole_local_{hole_local_index}_center[1], -0.100000])",
                    f"      cylinder(h={depth + 0.200000:.6f},"
                    f" d=hole_local_{hole_local_index}_diameter, $fn=64);",
                ]
            )
        lines.extend(["  }", "}", ""])
        return "\n".join(lines)

    if plate:
        if plate.get("detected_via") == "rotated_plate":
            angles = plate.get("rotation_euler_deg", [0.0, 0.0, 0.0])
            rotation_expr = f"rotate([{angles[0]:.6f}, {angles[1]:.6f}, {angles[2]:.6f}]) "
        else:
            rotation_expr = ""
    else:
        rotation_expr = ""

    lines.extend(
        [
            "",
            "difference() {",
            f"  translate(plate_origin) {rotation_expr}cube(plate_size);",
        ]
    )

    for pattern_index, pattern in enumerate(supported_patterns):
        diameter = float(pattern["diameter"])
        centers = [[float(value) for value in center] for center in pattern["centers"]]
        linear_name: Optional[str] = linear_pattern_names.get(pattern_index)
        if linear_name is not None:
            lines.append(f"  for (i = [0 : {linear_name}_count - 1]) {{")
            lines.append(
                f"    hole_cutout({_scad_named_linear_point_expression(linear_name, 'i')}, {linear_name}_diameter);"
            )
            lines.append("  }")
        elif pattern_index in grid_pattern_names:
            grid_name = grid_pattern_names[pattern_index]
            lines.append(f"  for (row = [0 : {grid_name}_rows - 1]) {{")
            lines.append(f"    for (col = [0 : {grid_name}_cols - 1]) {{")
            lines.append(
                f"      hole_cutout({_scad_named_grid_point_expression(grid_name)}, {grid_name}_diameter);"
            )
            lines.append("    }")
            lines.append("  }")
        else:
            center_list = (
                "[" + ", ".join(_scad_vector(center) for center in centers) + "]"
            )
            lines.append(f"  for (hole_center = {center_list}) {{")
            lines.append(f"    hole_cutout(hole_center, {diameter:.6f});")
            lines.append("  }")

    for hole_index, hole in enumerate(standalone_holes):
        lines.append(
            f"  hole_cutout(hole_{hole_index}_center, hole_{hole_index}_diameter);"
        )

    for slot_index, slot in enumerate(slots):
        if slot.get("axis") != thickness_axis:
            continue
        lines.append(
            f"  slot_cutout(slot_{slot_index}_start, slot_{slot_index}_end, slot_{slot_index}_width);"
        )

    for cbore_index, counterbore in enumerate(counterbores):
        if counterbore.get("axis") != thickness_axis:
            continue
        lines.append(
            "  counterbore_cutout("
            f"counterbore_{cbore_index}_center, "
            f"counterbore_{cbore_index}_through_diameter, "
            f"counterbore_{cbore_index}_bore_diameter, "
            f"counterbore_{cbore_index}_bore_depth"
            ");"
        )

    for cutout_index, cutout in enumerate(rectangular_cutouts):
        if cutout.get("axis") != thickness_axis:
            continue
        lines.append(
            f"  rectangular_prism_cutout(rect_cutout_{cutout_index}_center, rect_cutout_{cutout_index}_size);"
        )

    for pocket_index, pocket in enumerate(rectangular_pockets):
        if pocket.get("axis") != thickness_axis:
            continue
        lines.append(
            f"  rectangular_prism_cutout(rect_pocket_{pocket_index}_center, rect_pocket_{pocket_index}_size);"
        )

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _find_dominant_normal_axis(
    normals: np.ndarray,
    face_areas: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Return (dominant_axis, eigenvalue_fraction) via area-weighted covariance.

    The dominant axis is the eigenvector of ``C = sum(w_i * n_i ⊗ n_i)``
    with the largest eigenvalue.  It represents the surface-normal direction
    that accounts for the greatest share of mesh surface area.

    The returned vector is normalised and oriented toward the positive
    hemisphere (z-positive preferred, then y, then x) so the caller
    gets a deterministic sign for cap-area checks.
    """
    total_area = float(np.sum(face_areas))
    if total_area < 1e-9 or len(normals) == 0:
        return np.array([0.0, 0.0, 1.0]), 0.0

    weights = face_areas / total_area
    # Area-weighted outer-product covariance: (3, 3) PSD matrix
    C = np.einsum("i,ij,ik->jk", weights, normals, normals)
    eigenvalues, eigenvectors = np.linalg.eigh(C)  # eigenvalues in ascending order
    dominant = eigenvectors[:, -1].copy()           # column for largest eigenvalue

    # Canonical sign: prefer the component that is most positive
    for dim in (2, 1, 0):
        if abs(dominant[dim]) > 1e-6:
            if dominant[dim] < 0.0:
                dominant = -dominant
            break

    return dominant, float(eigenvalues[-1])


def _matrix_to_euler_xyz(R: np.ndarray) -> list[float]:
    """Extract Z-Y-X Euler angles (applied in X, then Y, then Z order in SCAD)."""
    sy = math.sqrt(R[0, 0] * R[0, 0] + R[1, 0] * R[1, 0])
    singular = sy < 1e-6
    if not singular:
        x = math.atan2(R[2, 1], R[2, 2])
        y = math.atan2(-R[2, 0], sy)
        z = math.atan2(R[1, 0], R[0, 0])
    else:
        x = math.atan2(-R[1, 2], R[1, 1])
        y = math.atan2(-R[2, 0], sy)
        z = 0
    return [math.degrees(x), math.degrees(y), math.degrees(z)]

def _convex_hull_2d(points: np.ndarray) -> np.ndarray:
    """Computes the convex hull of a set of 2D points using Monotone Chain."""
    pts = np.unique(points, axis=0)
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]
    if len(pts) <= 2:
        return pts
    
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return np.array(lower[:-1] + upper[:-1])

def _min_area_rect_2d(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Find the minimum area bounding rectangle for a set of 2D points.
    Returns (u_axis, v_axis) that minimize the bounding box area.
    """
    hull = _convex_hull_2d(points)
    if len(hull) < 3:
        return np.array([1.0, 0.0]), np.array([0.0, 1.0])

    min_area = float('inf')
    best_u = np.array([1.0, 0.0])
    
    for i in range(len(hull)):
        p1 = hull[i]
        p2 = hull[(i + 1) % len(hull)]
        edge = p2 - p1
        length = np.linalg.norm(edge)
        if length < 1e-9:
            continue
        u = edge / length
        v = np.array([-u[1], u[0]])
        
        proj_u = hull @ u
        proj_v = hull @ v
        span_u = np.max(proj_u) - np.min(proj_u)
        span_v = np.max(proj_v) - np.min(proj_v)
        area = span_u * span_v
        if area < min_area:
            min_area = area
            best_u = u

    best_v = np.array([-best_u[1], best_u[0]])
    return best_u, best_v


def _extract_rotated_plate_solid(
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    vertices: np.ndarray,
    config: DetectorConfig = DetectorConfig(),
) -> list[dict[str, Any]]:
    """Detect a plate with arbitrary (non-axis-aligned) orientation.

    Uses the area-weighted covariance of face normals to find the dominant
    surface-normal direction, then checks whether the mesh is thin along that
    axis.  Only called when the axis-aligned detector found neither a plate
    nor a box (so there is no risk of double-counting).
    """
    if len(normals) == 0 or len(face_areas) == 0 or vertices is None:
        return []

    total_area = float(np.sum(face_areas))
    if total_area < 1e-12:
        return []

    dominant_axis, _eigenvalue = _find_dominant_normal_axis(normals, face_areas)

    # The caller already ensures this is only run if the axis-aligned detector
    # failed. We can safely process plates rotated around a world axis (e.g. Z)
    # because they failed the axis-aligned bounding-box side tests.

    # Cap-area fraction: faces whose normals are close to ±dominant_axis.
    pos_mask = (normals @ dominant_axis) >= config.normal_axis_threshold
    neg_mask = (normals @ (-dominant_axis)) >= config.normal_axis_threshold
    pos_area = float(np.sum(face_areas[pos_mask]))
    neg_area = float(np.sum(face_areas[neg_mask]))
    if pos_area <= 0.0 or neg_area <= 0.0:
        return []

    confidence = (pos_area + neg_area) / total_area
    if confidence < config.plate_confidence_min:
        return []

    # Plate thickness: vertex projection range along dominant_axis.
    all_verts = vertices.reshape(-1, 3)
    proj_along = all_verts @ dominant_axis
    thickness = float(np.max(proj_along) - np.min(proj_along))

    # Footprint: bounding box of vertex projections in the perpendicular plane.
    # Build an orthonormal basis {u, v, dominant_axis}.
    abs_da = np.abs(dominant_axis)
    min_comp = int(np.argmin(abs_da))
    ref = np.zeros(3)
    ref[min_comp] = 1.0
    u_axis = ref - float(np.dot(ref, dominant_axis)) * dominant_axis
    u_axis = u_axis / float(np.linalg.norm(u_axis))
    v_axis = np.cross(dominant_axis, u_axis)

    proj_u = all_verts @ u_axis
    proj_v = all_verts @ v_axis
    
    pts_2d = np.column_stack((proj_u, proj_v))
    best_u_2d, best_v_2d = _min_area_rect_2d(pts_2d)
    
    true_u = best_u_2d[0] * u_axis + best_u_2d[1] * v_axis
    true_v = best_v_2d[0] * u_axis + best_v_2d[1] * v_axis
    
    true_proj_u = all_verts @ true_u
    true_proj_v = all_verts @ true_v
    min_u = float(np.min(true_proj_u))
    min_v = float(np.min(true_proj_v))
    span_u = float(np.max(true_proj_u) - min_u)
    span_v = float(np.max(true_proj_v) - min_v)
    
    if span_v > span_u:
        span_u, span_v = span_v, span_u
        true_u, true_v = true_v, true_u
        min_u, min_v = min_v, min_u
        
    max_perp_span = max(span_u, span_v, 1e-9)

    thin_ratio = thickness / max_perp_span
    if thin_ratio > config.plate_thin_ratio_max:
        return []

    min_z = float(np.min(proj_along))
    origin_3d = min_u * true_u + min_v * true_v + min_z * dominant_axis
    origin = origin_3d.tolist()
    
    R = np.column_stack((true_u, true_v, dominant_axis))
    euler_angles = _matrix_to_euler_xyz(R)

    return [
        {
            "type": "plate_like_solid",
            "confidence": float(confidence),
            "detected_via": "rotated_plate",
            "dominant_axis": dominant_axis.tolist(),
            "rotation_euler_deg": euler_angles,
            "origin": origin,
            "thickness": float(thickness),
            "footprint": [float(span_u), float(span_v)],
            "thin_ratio": float(thin_ratio),
            # size uses the local-frame order [span_u, span_v, thickness] so that
            # _candidate_cutout_axes can find the thin axis (argmin → index 2).
            "size": [float(span_u), float(span_v), float(thickness)],
            "local_u_axis": true_u.tolist(),
            "local_v_axis": true_v.tolist(),
            "parameters": {
                "thickness": float(thickness),
                "footprint_u": float(span_u),
                "footprint_v": float(span_v),
            },
            "note": (
                f"Rotated plate detected via dominant face-normal axis "
                f"[{dominant_axis[0]:.3f}, {dominant_axis[1]:.3f}, {dominant_axis[2]:.3f}]. "
                "rz cannot be recovered from surface normals alone."
            ),
        }
    ]


def _extract_cylinder_like_solid(
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    vertices: Optional[np.ndarray] = None,
    config: DetectorConfig = DetectorConfig(),
) -> list[dict[str, Any]]:
    """
    Detect a solid axis-aligned cylinder (boss / standoff / disk) by looking for:
      - Two opposing flat circular caps on one axis (fill ratio ≈ π/4 ≈ 0.785).
      - A roughly square cross-section in the plane perpendicular to that axis.
      - No significant inward-pointing lateral surface area (which would indicate
        an internal void / through-hole rather than a solid exterior).

    Only one cylinder feature is returned (highest-confidence axis).
    """
    if len(normals) == 0 or len(face_areas) == 0:
        return []

    total_area = float(np.sum(face_areas))
    if total_area <= 1e-12:
        return []

    axis_defs = [
        ("x", 0, np.array([1.0, 0.0, 0.0])),
        ("y", 1, np.array([0.0, 1.0, 0.0])),
        ("z", 2, np.array([0.0, 0.0, 1.0])),
    ]
    bbox_spans = [
        float(bbox["width"]),
        float(bbox["height"]),
        float(bbox["depth"]),
    ]

    # Mesh centroid (used to determine inward vs outward lateral normals)
    mesh_center = np.array([
        float(bbox["min_x"]) + float(bbox["width"]) / 2.0,
        float(bbox["min_y"]) + float(bbox["height"]) / 2.0,
        float(bbox["min_z"]) + float(bbox["depth"]) / 2.0,
    ])

    best: Optional[dict[str, Any]] = None
    best_confidence = 0.0

    for axis_name, axis_index, axis_vec in axis_defs:
        cap_span = bbox_spans[axis_index]
        if cap_span <= 1e-9:
            continue

        perp_indices = [i for i in range(3) if i != axis_index]
        perp_spans = [bbox_spans[i] for i in perp_indices]
        if min(perp_spans) <= 1e-9:
            continue

        # Squareness of the cross-section (perp plane must be roughly circular)
        squareness = float(min(perp_spans)) / float(max(perp_spans))
        if squareness < config.cylinder_cross_section_squareness_min:
            continue

        neg_mask = normals @ (-axis_vec) >= config.normal_axis_threshold
        pos_mask = normals @ axis_vec >= config.normal_axis_threshold
        neg_area = float(np.sum(face_areas[neg_mask]))
        pos_area = float(np.sum(face_areas[pos_mask]))
        cap_area = neg_area + pos_area

        # Both caps must be present
        if neg_area <= 0.0 or pos_area <= 0.0:
            continue

        cap_area_fraction = cap_area / total_area
        if cap_area_fraction < config.cylinder_cap_area_fraction_min:
            continue

        # Cap fill ratio: actual cap area vs. bounding rectangle of the cap.
        # For a circle: fill ≈ π/4 ≈ 0.785.  For a rectangle: fill ≈ 1.0.
        cap_bbox_area = float(perp_spans[0]) * float(perp_spans[1])
        avg_cap_area = cap_area / 2.0
        cap_fill_ratio = avg_cap_area / cap_bbox_area if cap_bbox_area > 1e-9 else 0.0

        if not (config.cylinder_cap_fill_ratio_min <= cap_fill_ratio <= config.cylinder_cap_fill_ratio_max):
            continue

        # Inward lateral face check: for a solid cylinder the outer surface normals
        # all point away from the axis.  Any significant inward-pointing lateral area
        # indicates an internal void (through-hole or cavity) — reject the candidate.
        lateral_mask = ~neg_mask & ~pos_mask
        lateral_normals = normals[lateral_mask]
        lateral_areas = face_areas[lateral_mask]
        lateral_area = float(np.sum(lateral_areas))

        if len(np.unique(np.round(lateral_normals, decimals=2), axis=0)) < 12:
            continue

        if lateral_area > 1e-9 and vertices is not None and len(lateral_normals) > 0:
            # Approximate face centroids from vertex data passed in
            # vertices shape: (n_faces, 3, 3) or we use bbox centre fallback
            lat_vert = vertices[lateral_mask]  # (n_lat, 3, 3)
            lat_centroids = lat_vert.mean(axis=1)  # (n_lat, 3)
            to_centroid = lat_centroids - mesh_center  # vector from mesh centre to face
            # Project onto perp plane only
            to_c_perp = to_centroid[:, perp_indices]
            lat_n_perp = lateral_normals[:, perp_indices]
            dot = np.sum(to_c_perp * lat_n_perp, axis=1)
            inward_lat_area = float(np.sum(lateral_areas[dot < 0]))
            inward_frac = inward_lat_area / lateral_area
        else:
            inward_frac = 0.0

        # More than 5% inward lateral area → internal surface present → not solid
        if inward_frac > 0.05:
            continue

        # Confidence: reward fill ratio closeness to π/4 and squareness
        ideal_fill = 3.14159265 / 4.0
        fill_score = max(0.0, 1.0 - abs(cap_fill_ratio - ideal_fill) / ideal_fill)
        confidence = float(fill_score * squareness)

        if confidence < config.cylinder_confidence_min:
            continue

        if confidence > best_confidence:
            best_confidence = confidence
            height = cap_span
            diameter = (perp_spans[0] + perp_spans[1]) / 2.0
            origin = [
                float(bbox["min_x"]),
                float(bbox["min_y"]),
                float(bbox["min_z"]),
            ]
            best = {
                "type": "cylinder_like_solid",
                "confidence": confidence,
                "axis": axis_name,
                "origin": origin,
                "height": float(height),
                "diameter": float(diameter),
                "radius": float(diameter / 2.0),
                "parameters": {
                    "height": float(height),
                    "diameter": float(diameter),
                },
                "note": (
                    "Candidate for a cylinder(h, d) parametric feature "
                    f"along the {axis_name}-axis."
                ),
            }

    return [best] if best is not None else []


def _extract_axis_aligned_box_features(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    config: DetectorConfig,
) -> list[dict[str, Any]]:
    if len(vectors) == 0:
        return []

    total_area = float(np.sum(face_areas))
    if total_area <= 1e-12:
        return []

    face_centers = np.mean(vectors, axis=1)
    diagonal = max(float(bbox.get("diagonal", 0.0)), 1e-9)
    boundary_tolerance = max(diagonal * config.boundary_tolerance_ratio, 1e-6)
    axis_pairs = {
        "x": (0, np.array([1.0, 0.0, 0.0]), bbox["min_x"], bbox["max_x"]),
        "y": (1, np.array([0.0, 1.0, 0.0]), bbox["min_y"], bbox["max_y"]),
        "z": (2, np.array([0.0, 0.0, 1.0]), bbox["min_z"], bbox["max_z"]),
    }

    supporting_area = 0.0
    plane_features: list[dict[str, Any]] = []
    boundary_support: dict[str, dict[str, Any]] = {}
    for axis_name, (axis_index, axis, min_coord, max_coord) in axis_pairs.items():
        negative_mask = (normals @ -axis >= config.normal_axis_threshold) & (
            np.abs(face_centers[:, axis_index] - min_coord) <= boundary_tolerance
        )
        positive_mask = (normals @ axis >= config.normal_axis_threshold) & (
            np.abs(face_centers[:, axis_index] - max_coord) <= boundary_tolerance
        )
        negative_area = float(np.sum(face_areas[negative_mask]))
        positive_area = float(np.sum(face_areas[positive_mask]))
        supporting_area += negative_area + positive_area
        plane_axes = [index for index in range(3) if index != axis_index]
        boundary_support[axis_name] = {
            "axis_index": axis_index,
            "negative_area": negative_area,
            "positive_area": positive_area,
            "negative_projection": _boundary_projection_metrics(
                vectors[negative_mask].reshape(-1, 3),
                plane_axes,
                bbox,
                negative_area,
            ),
            "positive_projection": _boundary_projection_metrics(
                vectors[positive_mask].reshape(-1, 3),
                plane_axes,
                bbox,
                positive_area,
            ),
        }
        plane_features.append(
            {
                "type": "axis_boundary_plane_pair",
                "axis": axis_name,
                "negative_coord": float(min_coord),
                "positive_coord": float(max_coord),
                "negative_area": negative_area,
                "positive_area": positive_area,
                "paired": bool(negative_area > 0.0 and positive_area > 0.0),
            }
        )

    confidence = min(supporting_area / total_area, 1.0)
    dimensions = {
        "width": float(bbox["width"]),
        "depth": float(bbox["height"]),
        "height": float(bbox["depth"]),
    }
    size = [dimensions["width"], dimensions["depth"], dimensions["height"]]
    nonzero_dims = [value for value in dimensions.values() if value > 1e-9]
    thin_ratio = (
        min(nonzero_dims) / max(nonzero_dims) if len(nonzero_dims) == 3 else 0.0
    )
    paired_axes = sum(1 for feature in plane_features if feature["paired"])
    tolerant_plate_confidence = _tolerant_plate_confidence(
        boundary_support,
        bbox,
        total_area,
        size,
        config=config,
    )
    tolerant_box_confidence = _tolerant_box_confidence(
        boundary_support,
        total_area,
        size,
        config=config,
    )

    features: list[dict[str, Any]] = plane_features
    if (
        paired_axes >= config.plate_paired_axes_min and confidence >= config.plate_confidence_min and thin_ratio <= config.plate_thin_ratio_max
    ) or tolerant_plate_confidence >= config.plate_tolerant_confidence_min:
        plate_confidence = max(confidence, tolerant_plate_confidence)
        strict_plate_passes = (
            paired_axes >= config.plate_paired_axes_min
            and confidence >= config.plate_confidence_min
            and thin_ratio <= config.plate_thin_ratio_max
        )
        via_tolerant = not strict_plate_passes
        features.append(
            {
                "type": "plate_like_solid",
                "confidence": float(plate_confidence),
                "detected_via": "tolerant_chamfer_or_fillet" if via_tolerant else "strict",
                "origin": [
                    float(bbox["min_x"]),
                    float(bbox["min_y"]),
                    float(bbox["min_z"]),
                ],
                "size": [
                    dimensions["width"],
                    dimensions["depth"],
                    dimensions["height"],
                ],
                "parameters": {
                    "width": dimensions["width"],
                    "depth": dimensions["depth"],
                    "thickness": min(nonzero_dims) if nonzero_dims else 0.0,
                },
                "note": (
                    "Candidate for an editable plate or slab feature."
                    if not via_tolerant
                    else (
                        "Candidate for an editable plate or slab feature, allowing"
                        " chamfer-broken side planes when the thin-axis footprint"
                        " remains strongly rectangular."
                    )
                ),
            }
        )
    elif (paired_axes == config.box_paired_axes_required and confidence >= config.box_confidence_min) or tolerant_box_confidence >= config.box_tolerant_confidence_min:
        box_confidence = max(confidence, tolerant_box_confidence)
        strict_box_passes = (
            paired_axes == config.box_paired_axes_required
            and confidence >= config.box_confidence_min
        )
        via_tolerant_box = not strict_box_passes
        features.append(
            {
                "type": "box_like_solid",
                "confidence": float(box_confidence),
                "detected_via": "tolerant_chamfer_or_fillet" if via_tolerant_box else "strict",
                "origin": [
                    float(bbox["min_x"]),
                    float(bbox["min_y"]),
                    float(bbox["min_z"]),
                ],
                "size": [
                    dimensions["width"],
                    dimensions["depth"],
                    dimensions["height"],
                ],
                "parameters": {
                    "width": dimensions["width"],
                    "depth": dimensions["depth"],
                    "height": dimensions["height"],
                },
                "note": (
                    "Candidate for a cube()/translate() parametric base feature."
                    if not via_tolerant_box
                    else (
                        "Candidate for a cube()/translate() parametric base feature,"
                        " allowing chamfer- or fillet-broken outer edges when all"
                        " three axis boundary pairs retain strong rectangular"
                        " support."
                    )
                ),
            }
        )
    return features


def _best_feature(graph: dict[str, Any], feature_type: str) -> Optional[dict[str, Any]]:
    candidates = [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") == feature_type
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda feature: float(feature.get("confidence", 0.0)))


def _boundary_projection_metrics(
    points: np.ndarray,
    plane_axes: list[int],
    bbox: dict[str, float],
    boundary_area: float,
) -> dict[str, float]:
    if len(points) == 0 or len(plane_axes) != 2:
        return {
            "span_ratio_a": 0.0,
            "span_ratio_b": 0.0,
            "area_ratio": 0.0,
            "fill_ratio": 0.0,
        }

    labels = ("x", "y", "z")
    span_ratios: list[float] = []
    for axis_index in plane_axes:
        bbox_span = float(bbox[f"max_{labels[axis_index]}"] - bbox[f"min_{labels[axis_index]}"])
        if bbox_span <= 1e-9:
            span_ratios.append(0.0)
            continue
        point_span = float(np.ptp(points[:, axis_index]))
        span_ratios.append(max(0.0, min(1.0, point_span / bbox_span)))

    projected_bbox_area = float(
        max(np.ptp(points[:, plane_axes[0]]), 0.0) * max(np.ptp(points[:, plane_axes[1]]), 0.0)
    )
    fill_ratio = 0.0
    if projected_bbox_area > 1e-9:
        fill_ratio = max(0.0, min(1.0, float(boundary_area) / projected_bbox_area))

    return {
        "span_ratio_a": span_ratios[0],
        "span_ratio_b": span_ratios[1],
        "area_ratio": float(span_ratios[0] * span_ratios[1]),
        "fill_ratio": float(fill_ratio),
    }


def _tolerant_plate_confidence(
    boundary_support: dict[str, dict[str, Any]],
    bbox: dict[str, float],
    total_area: float,
    size: list[float],
    config: DetectorConfig,
) -> float:
    if total_area <= 1e-12 or len(size) != 3:
        return 0.0

    thickness_axis_index = int(np.argmin(size))
    max_span = max(float(value) for value in size)
    if max_span <= 1e-9 or float(size[thickness_axis_index]) / max_span > config.plate_thin_ratio_max:
        return 0.0

    axis_name = ("x", "y", "z")[thickness_axis_index]
    support = boundary_support.get(axis_name)
    if support is None:
        return 0.0

    paired_support_ratio = (
        float(support["negative_area"]) + float(support["positive_area"])
    ) / total_area
    negative_projection = support["negative_projection"]
    positive_projection = support["positive_projection"]
    min_span_ratio = min(
        float(negative_projection["span_ratio_a"]),
        float(negative_projection["span_ratio_b"]),
        float(positive_projection["span_ratio_a"]),
        float(positive_projection["span_ratio_b"]),
    )
    footprint_area_ratio = min(
        float(negative_projection["area_ratio"]),
        float(positive_projection["area_ratio"]),
    )
    footprint_fill_ratio = min(
        float(negative_projection["fill_ratio"]),
        float(positive_projection["fill_ratio"]),
    )

    if paired_support_ratio < config.tolerant_plate_paired_support_min:
        return 0.0
    if min_span_ratio < config.tolerant_plate_min_span_ratio or footprint_area_ratio < config.tolerant_plate_footprint_area_ratio:
        return 0.0
    if footprint_fill_ratio < config.tolerant_plate_footprint_fill_ratio:
        return 0.0

    return min(1.0, 0.6 * paired_support_ratio + 0.4 * footprint_area_ratio)


def _tolerant_box_confidence(
    boundary_support: dict[str, dict[str, Any]],
    total_area: float,
    size: list[float],
    config: DetectorConfig,
) -> float:
    if total_area <= 1e-12 or len(size) != 3 or min(float(value) for value in size) <= 1e-9:
        return 0.0

    ideal_face_areas = {
        "x": float(size[1] * size[2]),
        "y": float(size[0] * size[2]),
        "z": float(size[0] * size[1]),
    }
    axis_confidences: list[float] = []
    supporting_area = 0.0
    full_fill_axes = 0
    for axis_name, ideal_face_area in ideal_face_areas.items():
        if ideal_face_area <= 1e-9:
            return 0.0
        support = boundary_support.get(axis_name)
        if support is None:
            return 0.0

        negative_area = float(support["negative_area"])
        positive_area = float(support["positive_area"])
        if negative_area <= 0.0 or positive_area <= 0.0:
            return 0.0

        supporting_area += negative_area + positive_area
        negative_projection = support["negative_projection"]
        positive_projection = support["positive_projection"]
        min_span_ratio = min(
            float(negative_projection["span_ratio_a"]),
            float(negative_projection["span_ratio_b"]),
            float(positive_projection["span_ratio_a"]),
            float(positive_projection["span_ratio_b"]),
        )
        footprint_area_ratio = min(
            float(negative_projection["area_ratio"]),
            float(positive_projection["area_ratio"]),
        )
        footprint_fill_ratio = min(
            float(negative_projection["fill_ratio"]),
            float(positive_projection["fill_ratio"]),
        )
        pair_support_ratio = min(
            1.0,
            (negative_area + positive_area) / (2.0 * ideal_face_area),
        )

        if min_span_ratio < config.tolerant_box_min_span_ratio or footprint_area_ratio < config.tolerant_box_footprint_area_ratio:
            return 0.0
        if footprint_fill_ratio < config.tolerant_box_relaxed_fill_ratio:
            return 0.0
        if footprint_fill_ratio >= config.tolerant_box_footprint_fill_ratio:
            full_fill_axes += 1

        axis_confidences.append(
            min(
                1.0,
                0.4 * pair_support_ratio
                + 0.3 * min_span_ratio
                + 0.2 * footprint_area_ratio
                + 0.1 * footprint_fill_ratio,
            )
        )

    if full_fill_axes < config.tolerant_box_full_fill_axes_min:
        return 0.0

    overall_support_ratio = supporting_area / total_area
    if overall_support_ratio < config.tolerant_box_overall_support_ratio:
        return 0.0

    min_axis_confidence = min(axis_confidences)
    mean_axis_confidence = sum(axis_confidences) / len(axis_confidences)
    return min(1.0, 0.6 * min_axis_confidence + 0.4 * mean_axis_confidence)


def _scad_vector(values: list[float]) -> str:
    return "[" + ", ".join(f"{value:.6f}" for value in values) + "]"


def _scad_named_linear_point_expression(pattern_name: str, index_name: str) -> str:
    parts = [
        f"{pattern_name}_origin[{axis}] + {index_name} * {pattern_name}_step[{axis}]"
        for axis in range(3)
    ]
    return "[" + ", ".join(parts) + "]"


def _scad_named_grid_point_expression(pattern_name: str) -> str:
    parts = [
        (
            f"{pattern_name}_origin[{axis}] + row * {pattern_name}_row_step[{axis}] "
            f"+ col * {pattern_name}_col_step[{axis}]"
        )
        for axis in range(3)
    ]
    return "[" + ", ".join(parts) + "]"


def _supported_hole_patterns(
    graph: dict[str, Any],
    axis: str,
) -> list[dict[str, Any]]:
    return [
        feature
        for feature in graph.get("features", [])
        if feature.get("type") in {"linear_hole_pattern", "grid_hole_pattern"}
        and feature.get("axis") == axis
        and float(feature.get("confidence", 0.0)) >= 0.70
    ]


def _has_linear_pattern_fields(pattern: dict[str, Any]) -> bool:
    return (
        isinstance(pattern.get("pattern_origin"), list)
        and isinstance(pattern.get("pattern_step"), list)
        and "pattern_count" in pattern
    )


def _has_grid_pattern_fields(pattern: dict[str, Any]) -> bool:
    return (
        isinstance(pattern.get("grid_origin"), list)
        and isinstance(pattern.get("grid_row_step"), list)
        and isinstance(pattern.get("grid_col_step"), list)
        and "grid_rows" in pattern
        and "grid_cols" in pattern
    )


def _hole_key(center: list[float]) -> tuple[float, float, float]:
    rounded = [round(float(value), 4) for value in center]
    return (rounded[0], rounded[1], rounded[2])


def _fit_axis_aligned_rectangle_2d(
    points: np.ndarray,
    config: DetectorConfig,
) -> Optional[tuple[np.ndarray, float, float, float]]:
    if len(points) < 8:
        return None

    mins = np.min(points, axis=0)
    maxs = np.max(points, axis=0)
    spans = maxs - mins
    min_span = float(np.min(spans))
    if min_span <= 1e-9:
        return None

    edge_distances = np.minimum.reduce(
        [
            np.abs(points[:, 0] - mins[0]),
            np.abs(points[:, 0] - maxs[0]),
            np.abs(points[:, 1] - mins[1]),
            np.abs(points[:, 1] - maxs[1]),
        ]
    )
    rectangle_error_ratio = float(np.percentile(edge_distances, 90) / min_span)
    if rectangle_error_ratio > config.rect_error_ratio_max:
        return None

    edge_tolerance = max(min_span * config.rect_edge_tolerance_ratio, 1e-6)
    if not (
        np.any(np.abs(points[:, 0] - mins[0]) <= edge_tolerance)
        and np.any(np.abs(points[:, 0] - maxs[0]) <= edge_tolerance)
        and np.any(np.abs(points[:, 1] - mins[1]) <= edge_tolerance)
        and np.any(np.abs(points[:, 1] - maxs[1]) <= edge_tolerance)
    ):
        return None

    center = (mins + maxs) * 0.5
    return center, float(spans[0]), float(spans[1]), rectangle_error_ratio


def _hole_cutout_module_body(
    depth: float,
    axis: str,
) -> list[str]:
    if axis == "z":
        return [
            f"  translate([center[0], center[1], center[2] - {depth * 0.5:.6f}])",
            f"    cylinder(h={depth:.6f}, d=diameter, $fn=64);",
        ]
    elif axis == "x":
        return [
            f"  translate([center[0] - {depth * 0.5:.6f}, center[1], center[2]])",
            "    rotate(a=90, v=[0, 1, 0])",
            f"      cylinder(h={depth:.6f}, d=diameter, $fn=64);",
        ]
    elif axis == "y":
        return [
            f"  translate([center[0], center[1] - {depth * 0.5:.6f}, center[2]])",
            "    rotate(a=90, v=[1, 0, 0])",
            f"      cylinder(h={depth:.6f}, d=diameter, $fn=64);",
        ]
    return ["  // unsupported hole axis"]


def _counterbore_bore_module_body(
    depth: float,
    axis: str,
) -> list[str]:
    if axis == "z":
        return [
            "  translate([center[0], center[1], center[2] + "
            f"{depth * 0.5:.6f} - bore_depth])",
            "    cylinder(h=bore_depth + 0.1, d=bore_diameter, $fn=64);",
        ]
    elif axis == "x":
        return [
            "  translate([center[0] + "
            f"{depth * 0.5:.6f} - bore_depth, center[1], center[2]])",
            "    rotate(a=90, v=[0, 1, 0])",
            "      cylinder(h=bore_depth + 0.1, d=bore_diameter, $fn=64);",
        ]
    elif axis == "y":
        return [
            "  translate([center[0], center[1] + "
            f"{depth * 0.5:.6f} - bore_depth, center[2]])",
            "    rotate(a=90, v=[1, 0, 0])",
            "      cylinder(h=bore_depth + 0.1, d=bore_diameter, $fn=64);",
        ]
    return ["  // unsupported hole axis"]


def _extract_axis_aligned_through_holes(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    existing_features: list[dict[str, Any]],
    config: DetectorConfig,
) -> list[dict[str, Any]]:
    axis_labels = ("x", "y", "z")
    face_centers = np.mean(vectors, axis=1)
    features: list[dict[str, Any]] = []

    for target in _candidate_cutout_axes(existing_features, config=config):
        cutout_axis_index = int(target["axis_index"])
        cutout_depth = float(target["depth"])
        if cutout_depth <= 1e-9:
            continue

        plane_axes = [index for index in range(3) if index != cutout_axis_index]
        axis_vector = np.zeros(3, dtype=np.float64)
        axis_vector[cutout_axis_index] = 1.0
        span_min = float(bbox[f"min_{axis_labels[cutout_axis_index]}"])
        span_max = float(bbox[f"max_{axis_labels[cutout_axis_index]}"])
        sidewall_mask = np.abs(normals @ axis_vector) <= (1.0 - config.normal_axis_threshold)
        # Keep only cutout-region faces away from the outer boundary planes on
        # the two perpendicular axes. This avoids merging hole sidewalls with
        # the parent solid's outer side faces into one giant component.
        interior_plane_mask = np.ones(len(vectors), dtype=bool)
        for axis in plane_axes:
            axis_min = float(bbox[f"min_{axis_labels[axis]}"])
            axis_max = float(bbox[f"max_{axis_labels[axis]}"])
            axis_span = max(axis_max - axis_min, 1e-9)
            boundary_margin = axis_span * config.hole_interior_boundary_margin_ratio
            interior_plane_mask &= (
                (face_centers[:, axis] > axis_min + boundary_margin)
                & (face_centers[:, axis] < axis_max - boundary_margin)
            )
        interior_mask = (
            face_centers[:, cutout_axis_index] > span_min + cutout_depth * config.hole_interior_depth_margin_ratio
        ) & (face_centers[:, cutout_axis_index] < span_max - cutout_depth * config.hole_interior_depth_margin_ratio)
        candidate_faces = np.where((sidewall_mask | interior_mask) & interior_plane_mask)[0]
        if len(candidate_faces) == 0:
            continue

        components = _connected_face_components(vectors, candidate_faces)
        min_radius = max(min(target["size"][axis] for axis in plane_axes) * config.hole_min_radius_ratio, 0.05)
        max_radius = max(target["size"][axis] for axis in plane_axes) * config.hole_max_radius_ratio
        for component_index, face_indices in enumerate(components):
            if len(face_indices) < config.hole_min_component_faces:
                continue
            component_vertices = vectors[face_indices].reshape(-1, 3)
            coords_2d = component_vertices[:, plane_axes]
            height_values = component_vertices[:, cutout_axis_index]
            height_span = float(np.max(height_values) - np.min(height_values))
            if height_span < cutout_depth * config.hole_height_span_floor_ratio:
                continue

            # Counterbores are stepped holes and often fail a single-circle fit,
            # so try this path before the simple-hole fallback.
            cbore = _try_counterbore_fit(
                component_vertices,
                cutout_axis_index,
                plane_axes,
                cutout_depth,
                span_min,
                span_max,
                config=config,
            )
            if (
                cbore is not None
                and cbore["confidence"] >= 0.70
                and min_radius <= cbore["bore_radius"] <= max_radius
                and min_radius <= cbore["through_radius"] <= max_radius
                and not _center_near_outer_boundary(
                    cbore["center_2d"],
                    bbox,
                    plane_axes,
                    cbore["bore_radius"],
                    config=config,
                    edge_factor=0.05,
                )
            ):
                center = [0.0, 0.0, 0.0]
                center[plane_axes[0]] = float(cbore["center_2d"][0])
                center[plane_axes[1]] = float(cbore["center_2d"][1])
                center[cutout_axis_index] = (span_min + span_max) * 0.5
                features.append(
                    {
                        "type": "counterbore_hole",
                        "confidence": float(cbore["confidence"]),
                        "axis": axis_labels[cutout_axis_index],
                        "center": center,
                        "through_diameter": float(cbore["through_radius"] * 2.0),
                        "bore_diameter": float(cbore["bore_radius"] * 2.0),
                        "bore_depth": float(cbore["bore_depth"]),
                        "through_depth": float(cbore["through_depth"]),
                        "total_depth": float(cbore["total_depth"]),
                        "component_faces": int(len(face_indices)),
                        "radial_error_ratio": float(cbore["radial_error_ratio"]),
                        "angular_coverage": float(cbore["angular_coverage"]),
                        "source_component_index": component_index,
                        "source_parent_type": target["parent_type"],
                        "note": (
                            "Candidate counterbore hole cutout in a "
                            f"{target['parent_type'].replace('_', '-')}"
                        ),
                    }
                )
                continue

            fit = _fit_circle_2d(coords_2d)
            if fit is not None:
                center_2d, radius, radial_error_ratio, angular_coverage = fit
                if (
                    height_span >= cutout_depth * config.hole_height_span_ratio_min
                    and min_radius <= radius <= max_radius
                    and radial_error_ratio <= config.hole_radial_error_max
                    and angular_coverage >= config.hole_angular_coverage_min
                    and not _center_near_outer_boundary(center_2d, bbox, plane_axes, radius, config=config)
                ):
                    center = [0.0, 0.0, 0.0]
                    center[plane_axes[0]] = float(center_2d[0])
                    center[plane_axes[1]] = float(center_2d[1])
                    center[cutout_axis_index] = (span_min + span_max) * 0.5
                    confidence = max(
                        0.0,
                        min(1.0, (1.0 - radial_error_ratio / config.hole_radial_error_max) * angular_coverage),
                    )
                    features.append(
                        {
                            "type": "hole_like_cutout",
                            "confidence": float(confidence),
                            "axis": axis_labels[cutout_axis_index],
                            "center": center,
                            "diameter": float(radius * 2.0),
                            "depth": float(height_span),
                            "component_faces": int(len(face_indices)),
                            "radial_error_ratio": float(radial_error_ratio),
                            "angular_coverage": float(angular_coverage),
                            "source_component_index": component_index,
                            "source_parent_type": target["parent_type"],
                            "note": (
                                "Candidate circular through-hole cutout in a "
                                f"{target['parent_type'].replace('_', '-')}"
                            ),
                        }
                    )
                    continue

            slot_fit = _fit_axis_aligned_slot_2d(coords_2d, config=config)
            if slot_fit is not None and height_span >= cutout_depth * config.hole_height_span_ratio_min:
                (
                    center_2d,
                    start_2d,
                    end_2d,
                    width,
                    length,
                    slot_error_ratio,
                    slot_axis_index,
                ) = slot_fit
                radius = width * 0.5
                if (
                    min_radius <= radius <= max_radius
                    and not _slot_near_outer_boundary(
                        start_2d,
                        end_2d,
                        radius,
                        bbox,
                        plane_axes,
                        config=config,
                    )
                ):
                    center = [0.0, 0.0, 0.0]
                    center[plane_axes[0]] = float(center_2d[0])
                    center[plane_axes[1]] = float(center_2d[1])
                    start = [0.0, 0.0, 0.0]
                    end = [0.0, 0.0, 0.0]
                    start[plane_axes[0]] = float(start_2d[0])
                    start[plane_axes[1]] = float(start_2d[1])
                    end[plane_axes[0]] = float(end_2d[0])
                    end[plane_axes[1]] = float(end_2d[1])
                    for vector in (center, start, end):
                        vector[cutout_axis_index] = (span_min + span_max) * 0.5
                    confidence = max(
                        0.0,
                        min(1.0, 1.0 - slot_error_ratio / config.slot_error_ratio_max),
                    )
                    features.append(
                        {
                            "type": "slot_like_cutout",
                            "confidence": float(confidence),
                            "axis": axis_labels[cutout_axis_index],
                            "center": center,
                            "start": start,
                            "end": end,
                            "width": float(width),
                            "length": float(length),
                            "depth": float(height_span),
                            "component_faces": int(len(face_indices)),
                            "slot_error_ratio": float(slot_error_ratio),
                            "slot_axis": axis_labels[plane_axes[slot_axis_index]],
                            "source_component_index": component_index,
                            "source_parent_type": target["parent_type"],
                            "note": (
                                "Candidate rounded slot through-cutout in a "
                                f"{target['parent_type'].replace('_', '-')}"
                            ),
                        }
                    )
                    continue

            rect_fit = _fit_axis_aligned_rectangle_2d(coords_2d, config=config)
            if rect_fit is None:
                continue
            center_2d, width, length, rectangle_error_ratio = rect_fit
            if _rectangle_near_outer_boundary(
                center_2d,
                np.asarray([width, length], dtype=np.float64),
                bbox,
                plane_axes,
                config=config,
            ):
                continue

            cutout_min = float(np.min(height_values))
            cutout_max = float(np.max(height_values))
            edge_tolerance = max(cutout_depth * config.rect_edge_tolerance_ratio, 1e-6)
            touches_min = cutout_min <= span_min + edge_tolerance
            touches_max = cutout_max >= span_max - edge_tolerance
            if touches_min and touches_max and height_span >= cutout_depth * config.hole_height_span_ratio_min:
                feature_type = "rectangular_cutout"
                center_axis_value = (span_min + span_max) * 0.5
                open_direction = "both"
                note = "Candidate axis-aligned rectangular through-cutout in a "
            elif (
                touches_min != touches_max
                and cutout_depth * config.pocket_height_floor_ratio <= height_span <= cutout_depth * config.pocket_height_ceiling_ratio
            ):
                feature_type = "rectangular_pocket"
                center_axis_value = (cutout_min + cutout_max) * 0.5
                open_direction = "negative" if touches_min else "positive"
                note = "Candidate axis-aligned rectangular blind pocket in a "
            else:
                continue

            center = [0.0, 0.0, 0.0]
            size_vector = [0.0, 0.0, 0.0]
            center[plane_axes[0]] = float(center_2d[0])
            center[plane_axes[1]] = float(center_2d[1])
            center[cutout_axis_index] = float(center_axis_value)
            size_vector[plane_axes[0]] = float(width)
            size_vector[plane_axes[1]] = float(length)
            size_vector[cutout_axis_index] = float(height_span)
            confidence = max(0.0, min(1.0, 1.0 - rectangle_error_ratio / config.rect_error_ratio_max))
            features.append(
                {
                    "type": feature_type,
                    "confidence": float(confidence),
                    "axis": axis_labels[cutout_axis_index],
                    "center": center,
                    "size": size_vector,
                    "depth": float(height_span),
                    "profile_width": float(width),
                    "profile_height": float(length),
                    "rectangle_error_ratio": float(rectangle_error_ratio),
                    "open_direction": open_direction,
                    "component_faces": int(len(face_indices)),
                    "source_component_index": component_index,
                    "source_parent_type": target["parent_type"],
                    "note": note + f"{target['parent_type'].replace('_', '-')}",
                }
            )
    return features



def _extract_rotated_plate_through_holes(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    existing_features: list[dict[str, Any]],
    config: DetectorConfig = DetectorConfig(),
) -> list[dict[str, Any]]:
    """Detect hole/slot/rect cutouts on plates found by the rotated-plate detector.

    Projects all mesh geometry into each rotated plate's local (u, v, n) frame,
    runs the standard axis-aligned cutout extractor in that frame, then converts
    detected centers back to world space.

    The returned features carry both a world-space ``center`` and a
    ``local_center`` (local-frame coordinates) so the SCAD emitter can embed
    holes inside the plate's rotation block without needing to invert the
    rotation matrix at emit time.  The ``axis`` field is set to ``"local_n"``
    to distinguish these from world-aligned cutouts in downstream code.
    """
    rotated_plates = [
        f
        for f in existing_features
        if f.get("type") == "plate_like_solid"
        and f.get("detected_via") == "rotated_plate"
        and "local_u_axis" in f
        and "local_v_axis" in f
    ]
    if not rotated_plates:
        return []

    all_verts = vectors.reshape(-1, 3)
    face_centers = np.mean(vectors, axis=1)
    features: list[dict[str, Any]] = []

    for plate in rotated_plates:
        u_axis = np.array(plate["local_u_axis"], dtype=np.float64)
        v_axis = np.array(plate["local_v_axis"], dtype=np.float64)
        n_axis = np.array(plate["dominant_axis"], dtype=np.float64)
        origin = np.array(plate["origin"], dtype=np.float64)
        span_u, span_v, thickness = (
            float(plate["size"][0]),
            float(plate["size"][1]),
            float(plate["size"][2]),
        )

        # Offsets so that origin maps to local (0, 0, 0).
        origin_u = float(origin @ u_axis)
        origin_v = float(origin @ v_axis)
        origin_n = float(origin @ n_axis)

        # Project all vertices into the local (u, v, n) frame.
        local_all_verts = np.column_stack(
            [
                all_verts @ u_axis - origin_u,
                all_verts @ v_axis - origin_v,
                all_verts @ n_axis - origin_n,
            ]
        )
        local_vectors = local_all_verts.reshape(vectors.shape)

        # Project normals (rotation only – no translation needed for unit normals).
        local_normals = np.column_stack(
            [normals @ u_axis, normals @ v_axis, normals @ n_axis]
        )

        # Build a local bbox identical in structure to the world-space bbox used
        # by the axis-aligned extractor.  The plate spans [0, span_u] × [0, span_v]
        # × [0, thickness] in this frame.
        local_bbox: dict[str, float] = {
            "min_x": 0.0,
            "max_x": float(span_u),
            "width": float(span_u),
            "min_y": 0.0,
            "max_y": float(span_v),
            "height": float(span_v),
            "min_z": 0.0,
            "max_z": float(thickness),
            "depth": float(thickness),
        }
        # Minimal fake plate feature that satisfies _candidate_cutout_axes.
        local_plate: dict[str, Any] = {
            "type": "plate_like_solid",
            "size": [float(span_u), float(span_v), float(thickness)],
        }

        local_features = _extract_axis_aligned_through_holes(
            local_vectors,
            local_normals,
            face_areas,
            local_bbox,
            [local_plate],
            config=config,
        )

        for feat in local_features:
            # Convert local-frame centers to world space and attach both.
            if "center" in feat:
                lu, lv, ln = (
                    float(feat["center"][0]),
                    float(feat["center"][1]),
                    float(feat["center"][2]),
                )
                world_center = (
                    origin + lu * u_axis + lv * v_axis + ln * n_axis
                )
                feat["local_center"] = [lu, lv, ln]
                feat["center"] = world_center.tolist()
            if "start" in feat and "end" in feat:
                ls = [float(v) for v in feat["start"]]
                le = [float(v) for v in feat["end"]]
                world_start = origin + ls[0] * u_axis + ls[1] * v_axis + ls[2] * n_axis
                world_end = origin + le[0] * u_axis + le[1] * v_axis + le[2] * n_axis
                feat["local_start"] = ls
                feat["local_end"] = le
                feat["start"] = world_start.tolist()
                feat["end"] = world_end.tolist()
            # Tag axis as local-n so the emitter knows to bore along plate normal.
            feat["axis"] = "local_n"
            feat["detected_via"] = "rotated_plate_local_frame"
            feat["local_u_axis"] = u_axis.tolist()
            feat["local_v_axis"] = v_axis.tolist()
            feat["local_n_axis"] = n_axis.tolist()
            feat["local_origin"] = origin.tolist()

        features.extend(local_features)

    return features


def _candidate_cutout_axes(
    existing_features: list[dict[str, Any]],
    config: DetectorConfig,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for feature in existing_features:
        feature_type = feature.get("type")
        if feature_type == "plate_like_solid":
            # Rotated plates need local-frame cutout extraction; skip here.
            if feature.get("detected_via") == "rotated_plate":
                continue
            size = [float(value) for value in feature["size"]]
            axis_index = int(np.argmin(size))
            candidates.append(
                {
                    "parent_type": "plate_like_solid",
                    "axis_index": axis_index,
                    "depth": float(size[axis_index]),
                    "size": size,
                }
            )
        elif feature_type == "box_like_solid":
            size = [float(value) for value in feature["size"]]
            for axis_index, depth in enumerate(size):
                candidates.append(
                    {
                        "parent_type": "box_like_solid",
                        "axis_index": axis_index,
                        "depth": float(depth),
                        "size": size,
                    }
                )

    return candidates


def _extract_repeated_hole_patterns(
    features: list[dict[str, Any]],
    config: DetectorConfig,
) -> list[dict[str, Any]]:
    holes = [
        feature for feature in features if feature.get("type") == "hole_like_cutout"
    ]
    patterns: list[dict[str, Any]] = []
    if len(holes) < 2:
        return patterns

    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for hole in holes:
        axis = str(hole.get("axis", ""))
        # Pattern metadata is currently defined for world-aligned axes only.
        # Local-frame rotated-plate holes (axis="local_n") are excluded.
        if axis not in {"x", "y", "z"}:
            continue
        diameter = float(hole["diameter"])
        # Group diameters with a modest tolerance to absorb mesh noise.
        key = (axis, int(round(diameter / config.pattern_diameter_rounding_mm)))
        groups.setdefault(key, []).append(hole)

    for (axis, diameter_key), group in groups.items():
        if len(group) < 2:
            continue
        centers = np.asarray([hole["center"] for hole in group], dtype=np.float64)
        varying_axes = [
            index for index in range(3) if index != {"x": 0, "y": 1, "z": 2}[axis]
        ]
        unique_counts = [
            len(np.unique(np.round(centers[:, axis_index], 4)))
            for axis_index in varying_axes
        ]
        pattern_type = (
            "grid_hole_pattern"
            if len(group) >= config.grid_pattern_min_holes and min(unique_counts) >= 2
            else "linear_hole_pattern"
        )
        pattern = {
            "type": pattern_type,
            "confidence": float(min(float(hole["confidence"]) for hole in group)),
            "axis": axis,
            "hole_count": int(len(group)),
            "diameter": float(diameter_key * config.pattern_diameter_rounding_mm),
            "centers": [[float(value) for value in hole["center"]] for hole in group],
            "note": "Candidate repeated hole pattern for future SCAD loop emission.",
        }
        if pattern_type == "linear_hole_pattern":
            pattern.update(_linear_hole_pattern_metadata(centers, varying_axes, config=config))
        else:
            pattern.update(_grid_hole_pattern_metadata(centers, axis, varying_axes, config=config))
        patterns.append(pattern)
    return patterns


def _linear_hole_pattern_metadata(
    centers: np.ndarray,
    varying_axes: list[int],
    config: DetectorConfig,
) -> dict[str, Any]:
    if len(centers) < 2:
        return {}

    axis_spans = np.ptp(centers[:, varying_axes], axis=0)
    active_axis = varying_axes[int(np.argmax(axis_spans))]
    ordered_centers = centers[np.argsort(centers[:, active_axis])]
    count = len(ordered_centers)
    step = (ordered_centers[-1] - ordered_centers[0]) / float(count - 1)
    spacing = float(np.linalg.norm(step))
    if spacing <= 1e-9:
        return {}

    expected = ordered_centers[0] + np.arange(count, dtype=np.float64)[:, None] * step
    regularity_error = float(
        np.max(np.linalg.norm(ordered_centers - expected, axis=1)) / spacing
    )
    if regularity_error > config.pattern_regularity_error_max:
        return {}

    return {
        "pattern_origin": [float(value) for value in ordered_centers[0]],
        "pattern_step": [float(value) for value in step],
        "pattern_count": int(count),
        "pattern_spacing": spacing,
        "pattern_axis": ("x", "y", "z")[active_axis],
        "regularity_error": regularity_error,
    }


def _grid_hole_pattern_metadata(
    centers: np.ndarray,
    axis: str,
    varying_axes: list[int],
    config: DetectorConfig,
) -> dict[str, Any]:
    if len(centers) < 4 or len(varying_axes) != 2:
        return {}

    rounded = np.round(centers[:, varying_axes], 4)
    row_values = np.sort(np.unique(rounded[:, 1]))
    col_values = np.sort(np.unique(rounded[:, 0]))
    rows = len(row_values)
    cols = len(col_values)
    if rows < 2 or cols < 2 or rows * cols != len(centers):
        return {}

    axis_index = {"x": 0, "y": 1, "z": 2}[axis]
    center_by_key: dict[tuple[float, float], np.ndarray] = {}
    for center in centers:
        key = (
            round(float(center[varying_axes[0]]), 4),
            round(float(center[varying_axes[1]]), 4),
        )
        center_by_key[key] = center

    ordered_centers: list[np.ndarray] = []
    for row_value in row_values:
        for col_value in col_values:
            center = center_by_key.get((float(col_value), float(row_value)))
            if center is None:
                return {}
            ordered_centers.append(center)

    origin = np.array(ordered_centers[0], dtype=np.float64)
    row_step = np.zeros(3, dtype=np.float64)
    col_step = np.zeros(3, dtype=np.float64)
    row_step[varying_axes[1]] = float(row_values[1] - row_values[0])
    col_step[varying_axes[0]] = float(col_values[1] - col_values[0])
    origin[axis_index] = float(np.mean(centers[:, axis_index]))

    expected: list[np.ndarray] = []
    for row_index in range(rows):
        for col_index in range(cols):
            expected.append(origin + row_index * row_step + col_index * col_step)
    expected_array = np.asarray(expected, dtype=np.float64)
    ordered_array = np.asarray(ordered_centers, dtype=np.float64)
    min_spacing = max(
        min(
            abs(float(row_step[varying_axes[1]])), abs(float(col_step[varying_axes[0]]))
        ),
        1e-9,
    )
    regularity_error = float(
        np.max(np.linalg.norm(ordered_array - expected_array, axis=1)) / min_spacing
    )
    if regularity_error > config.pattern_regularity_error_max:
        return {}

    return {
        "grid_origin": [float(value) for value in origin],
        "grid_row_step": [float(value) for value in row_step],
        "grid_col_step": [float(value) for value in col_step],
        "grid_rows": int(rows),
        "grid_cols": int(cols),
        "grid_row_spacing": abs(float(row_step[varying_axes[1]])),
        "grid_col_spacing": abs(float(col_step[varying_axes[0]])),
        "grid_row_axis": ("x", "y", "z")[varying_axes[1]],
        "grid_col_axis": ("x", "y", "z")[varying_axes[0]],
        "regularity_error": regularity_error,
    }


def _try_counterbore_fit(
    component_vertices: np.ndarray,
    cutout_axis_index: int,
    plane_axes: list[int],
    height_span: float,
    span_min: float,
    span_max: float,
    config: DetectorConfig,
) -> Optional[dict[str, Any]]:
    """Try to detect a counterbore (stepped hole) in a connected component.

    Splits vertices by height along the cutout axis, looking for two
    concentric circles of different radii at different height segments.
    Returns a dict with counterbore parameters if found, or None.
    """
    height_values = component_vertices[:, cutout_axis_index]
    h_min = float(np.min(height_values))
    h_max = float(np.max(height_values))
    h_span = h_max - h_min
    if h_span < height_span * config.cbore_height_span_floor_ratio:
        return None

    # Fit circles on endpoint slices first. Try thinner slices before thicker
    # ones so near-through counterbores do not blur one side with two radii.
    endpoint_fit = None
    for slice_ratio in config.cbore_slice_ratios:
        slice_thickness = max(h_span * slice_ratio, 1e-9)
        lower_mask = height_values <= (h_min + slice_thickness)
        upper_mask = height_values >= (h_max - slice_thickness)

        lower_pts = component_vertices[lower_mask][:, plane_axes]
        upper_pts = component_vertices[upper_mask][:, plane_axes]
        if len(lower_pts) < 8 or len(upper_pts) < 8:
            continue

        lower_fit = _fit_circle_2d(lower_pts)
        upper_fit = _fit_circle_2d(upper_pts)
        if lower_fit is None or upper_fit is None:
            continue

        endpoint_fit = (lower_fit, upper_fit)
        break

    if endpoint_fit is None:
        return None

    lower_center, lower_radius, lower_error, lower_coverage = endpoint_fit[0]
    upper_center, upper_radius, upper_error, upper_coverage = endpoint_fit[1]

    # Both fits must be reasonable.
    if lower_error > config.cbore_radial_error_max or upper_error > config.cbore_radial_error_max:
        return None
    if lower_coverage < config.cbore_angular_coverage_min or upper_coverage < config.cbore_angular_coverage_min:
        return None

    # Centers must be concentric.
    larger_radius = max(lower_radius, upper_radius)
    center_distance = float(np.linalg.norm(lower_center - upper_center))
    if center_distance > larger_radius * config.cbore_concentric_ratio_max:
        return None

    # Radii must differ by at least 20%.
    smaller_radius = min(lower_radius, upper_radius)
    if smaller_radius <= 0:
        return None
    radius_ratio = larger_radius / smaller_radius
    if radius_ratio < config.cbore_radius_ratio_min:
        return None

    # Determine which radius is bore vs through-hole.
    if upper_radius > lower_radius:
        bore_radius = upper_radius
        through_radius = lower_radius
        bore_error = upper_error
        through_error = lower_error
        bore_coverage = upper_coverage
        through_coverage = lower_coverage
    else:
        bore_radius = lower_radius
        through_radius = upper_radius
        bore_error = lower_error
        through_error = upper_error
        bore_coverage = lower_coverage
        through_coverage = upper_coverage

    # Use a shared center estimate and classify vertices by nearest radius.
    center_2d = (lower_center + upper_center) * 0.5
    radii = np.linalg.norm(component_vertices[:, plane_axes] - center_2d, axis=1)
    to_bore = np.abs(radii - bore_radius)
    to_through = np.abs(radii - through_radius)
    bore_membership = to_bore <= to_through
    through_membership = ~bore_membership
    if np.count_nonzero(bore_membership) < 16 or np.count_nonzero(through_membership) < 16:
        return None

    bore_segment_heights = height_values[bore_membership]
    through_segment_heights = height_values[through_membership]
    bore_depth = float(np.max(bore_segment_heights) - np.min(bore_segment_heights))
    through_depth = float(np.max(through_segment_heights) - np.min(through_segment_heights))
    total_depth = float(h_max - h_min)

    if (
        bore_depth < total_depth * config.cbore_depth_floor_ratio
        or through_depth < total_depth * config.cbore_depth_floor_ratio
        or bore_depth > total_depth * config.cbore_depth_ceiling_ratio
        or through_depth > total_depth * config.cbore_depth_ceiling_ratio
    ):
        return None

    # Larger-radius bore should touch only one outer boundary plane.
    edge_tolerance = total_depth * config.cbore_edge_tolerance_ratio
    bore_touches_min = np.min(bore_segment_heights) <= h_min + edge_tolerance
    bore_touches_max = np.max(bore_segment_heights) >= h_max - edge_tolerance
    if bore_touches_min == bore_touches_max:
        return None

    worst_error = max(bore_error, through_error)
    worst_coverage = min(bore_coverage, through_coverage)
    confidence = max(
        0.0,
        min(1.0, (1.0 - worst_error / config.cbore_radial_error_max) * worst_coverage),
    )

    return {
        "center_2d": center_2d,
        "through_radius": float(through_radius),
        "bore_radius": float(bore_radius),
        "bore_depth": float(bore_depth),
        "through_depth": float(through_depth),
        "total_depth": float(total_depth),
        "radial_error_ratio": float(worst_error),
        "angular_coverage": float(worst_coverage),
        "confidence": float(confidence),
    }


def _connected_face_components(
    vectors: np.ndarray,
    face_indices: np.ndarray,
    tolerance: float = 1e-5,
) -> list[np.ndarray]:
    if len(face_indices) == 0:
        return []

    scale = 1.0 / tolerance
    vertex_to_faces: dict[tuple[int, int, int], list[int]] = {}
    for local_index, face_index in enumerate(face_indices):
        for vertex in vectors[face_index]:
            key = tuple(np.round(vertex * scale).astype(np.int64))
            vertex_to_faces.setdefault(key, []).append(local_index)

    adjacency: list[set[int]] = [set() for _ in face_indices]
    for local_faces in vertex_to_faces.values():
        for local_index in local_faces:
            adjacency[local_index].update(local_faces)

    seen: set[int] = set()
    components: list[np.ndarray] = []
    for start in range(len(face_indices)):
        if start in seen:
            continue
        stack = [start]
        component: list[int] = []
        seen.add(start)
        while stack:
            current = stack.pop()
            component.append(int(face_indices[current]))
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(np.asarray(component, dtype=np.int64))
    return components


def _fit_circle_2d(
    points: np.ndarray,
) -> Optional[tuple[np.ndarray, float, float, float]]:
    if len(points) < 8:
        return None
    matrix = np.column_stack((2.0 * points, np.ones(len(points))))
    vector = np.sum(points * points, axis=1)
    try:
        solution, *_ = np.linalg.lstsq(matrix, vector, rcond=None)
    except np.linalg.LinAlgError:
        return None

    center = solution[:2]
    radius_sq = float(np.dot(center, center) + solution[2])
    if radius_sq <= 1e-12:
        return None
    radius = float(np.sqrt(radius_sq))
    distances = np.linalg.norm(points - center, axis=1)
    radial_error_ratio = float(
        np.percentile(np.abs(distances - radius), 90) / max(radius, 1e-9)
    )
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    bins = np.unique(np.floor(((angles + np.pi) / (2.0 * np.pi)) * 24.0).astype(int))
    angular_coverage = float(min(len(bins), 24) / 24.0)
    return center, radius, radial_error_ratio, angular_coverage


def _fit_axis_aligned_slot_2d(
    points: np.ndarray,
    config: DetectorConfig,
) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, int]]:
    if len(points) < 16:
        return None

    mins = np.min(points, axis=0)
    maxs = np.max(points, axis=0)
    spans = maxs - mins
    long_axis = int(np.argmax(spans))
    short_axis = 1 - long_axis
    length = float(spans[long_axis])
    width = float(spans[short_axis])
    if width <= 1e-9 or length / width < config.slot_aspect_ratio_min:
        return None

    radius = width * 0.5
    center = (mins + maxs) * 0.5
    straight_length = length - width
    if straight_length <= radius * config.slot_straight_length_min_ratio:
        return None

    start = center.copy()
    end = center.copy()
    start[long_axis] -= straight_length * 0.5
    end[long_axis] += straight_length * 0.5

    segment = end - start
    segment_length_sq = float(np.dot(segment, segment))
    if segment_length_sq <= 1e-12:
        return None
    projections = np.clip(((points - start) @ segment) / segment_length_sq, 0.0, 1.0)
    closest = start + projections[:, None] * segment
    distances = np.linalg.norm(points - closest, axis=1)
    slot_error_ratio = float(
        np.percentile(np.abs(distances - radius), 90) / max(radius, 1e-9)
    )
    if slot_error_ratio > config.slot_error_ratio_max:
        return None

    # Require evidence for both caps and both straight sides to avoid treating noise as a slot.
    long_coords = points[:, long_axis]
    short_coords = points[:, short_axis]
    cap_tolerance = radius * config.slot_cap_tolerance_ratio
    side_tolerance = radius * config.slot_side_tolerance_ratio
    has_start_cap = bool(np.any(long_coords <= start[long_axis] + cap_tolerance))
    has_end_cap = bool(np.any(long_coords >= end[long_axis] - cap_tolerance))
    middle_mask = (long_coords >= start[long_axis] - cap_tolerance) & (
        long_coords <= end[long_axis] + cap_tolerance
    )
    has_negative_side = bool(
        np.any(
            middle_mask & (short_coords <= center[short_axis] - radius + side_tolerance)
        )
    )
    has_positive_side = bool(
        np.any(
            middle_mask & (short_coords >= center[short_axis] + radius - side_tolerance)
        )
    )
    if not (has_start_cap and has_end_cap and has_negative_side and has_positive_side):
        return None

    return center, start, end, width, length, slot_error_ratio, long_axis


def _center_near_outer_boundary(
    center_2d: np.ndarray,
    bbox: dict[str, float],
    plane_axes: list[int],
    radius: float,
    config: DetectorConfig,
    edge_factor: Optional[float] = None,
) -> bool:
    if edge_factor is None:
        edge_factor = config.hole_edge_factor
    labels = ("x", "y", "z")
    for value, axis_index in zip(center_2d, plane_axes):
        min_coord = float(bbox[f"min_{labels[axis_index]}"])
        max_coord = float(bbox[f"max_{labels[axis_index]}"])
        if value - radius <= min_coord + radius * edge_factor:
            return True
        if value + radius >= max_coord - radius * edge_factor:
            return True
    return False


def _rectangle_near_outer_boundary(
    center_2d: np.ndarray,
    spans_2d: np.ndarray,
    bbox: dict[str, float],
    plane_axes: list[int],
    config: DetectorConfig,
) -> bool:
    labels = ("x", "y", "z")
    for value, span, axis_index in zip(center_2d, spans_2d, plane_axes):
        min_coord = float(bbox[f"min_{labels[axis_index]}"])
        max_coord = float(bbox[f"max_{labels[axis_index]}"])
        half_span = float(span) * 0.5
        margin = max(half_span * 0.10, 1e-6)
        if value - half_span <= min_coord + margin:
            return True
        if value + half_span >= max_coord - margin:
            return True
    return False


def _slot_near_outer_boundary(
    start_2d: np.ndarray,
    end_2d: np.ndarray,
    radius: float,
    bbox: dict[str, float],
    plane_axes: list[int],
    config: DetectorConfig,
) -> bool:
    labels = ("x", "y", "z")
    for local_axis, axis_index in enumerate(plane_axes):
        min_coord = float(bbox[f"min_{labels[axis_index]}"])
        max_coord = float(bbox[f"max_{labels[axis_index]}"])
        feature_min = (
            min(float(start_2d[local_axis]), float(end_2d[local_axis])) - radius
        )
        feature_max = (
            max(float(start_2d[local_axis]), float(end_2d[local_axis])) + radius
        )
        if feature_min <= min_coord + radius * 0.1:
            return True
        if feature_max >= max_coord - radius * 0.1:
            return True
    return False


def _relative_or_absolute(path: Path, root_dir: Optional[Union[Path, str]]) -> str:
    if root_dir is None:
        return str(path)
    try:
        return str(path.relative_to(Path(root_dir)))
    except ValueError:
        return str(path)


def _summarize_graphs(graphs: list[dict[str, Any]]) -> dict[str, Any]:
    feature_counts: dict[str, int] = {}
    error_count = 0
    for graph in graphs:
        if graph.get("status") == "error":
            error_count += 1
        for feature in graph.get("features", []):
            feature_type = str(feature.get("type", "unknown"))
            feature_counts[feature_type] = feature_counts.get(feature_type, 0) + 1
    return {
        "file_count": len(graphs),
        "error_count": error_count,
        "feature_counts": feature_counts,
    }


# ---------------------------------------------------------------------------
# Track A: triage report
# ---------------------------------------------------------------------------

_TRIAGE_BUCKETS = (
    "parametric_preview",
    "feature_graph_no_preview",
    "axis_pairs_only",
    "polyhedron_fallback",
    "error",
)


def _classify_graph_bucket(graph: dict[str, Any]) -> str:
    """Assign a single graph to one of the five triage buckets.

    Bucket priority (highest wins):
    1. ``error``              – graph has ``status == "error"``
    2. ``parametric_preview`` – ``emit_feature_graph_scad_preview`` returns SCAD
    3. ``feature_graph_no_preview`` – has plate or box candidates (any confidence)
       but preview was not emitted
    4. ``axis_pairs_only``    – only ``axis_boundary_plane_pair`` features present
    5. ``polyhedron_fallback`` – no features at all
    """
    if graph.get("status") == "error":
        return "error"
    if emit_feature_graph_scad_preview(graph) is not None:
        return "parametric_preview"
    features = graph.get("features", [])
    feature_types = {str(f.get("type", "")) for f in features}
    solid_types = {"plate_like_solid", "box_like_solid"}
    if feature_types & solid_types:
        return "feature_graph_no_preview"
    non_pair = feature_types - {"axis_boundary_plane_pair"}
    if not non_pair and feature_types:
        return "axis_pairs_only"
    return "polyhedron_fallback"


def _failure_shape_metadata(graph: dict[str, Any]) -> dict[str, Any]:
    """Extract failure-shape diagnostics for non-preview graphs.

    Returns a dict with:
    - ``axis_pair_count``           number of axis_boundary_plane_pair features
    - ``paired_axis_count``         subset where both planes are present
    - ``thinnest_axis``             bounding-box axis with smallest extent
    - ``thinnest_axis_paired``      whether that axis has both planes present
    - ``planar_support_fraction``   boundary_area / total_surface_area (0–1).
                                    The real discriminator: high values mean the mesh
                                    surface is dominated by axis-aligned flat faces
                                    (genuine box/plate candidate); low values mean the
                                    mesh is mostly curved/complex (e.g. 3DBenchy).
    - ``plate_candidate_confidence``  confidence of best plate_like_solid, or null
    - ``box_candidate_confidence``    confidence of best box_like_solid, or null
    """
    features = graph.get("features", [])
    bbox = graph.get("mesh", {}).get("bounding_box", {})
    surface_area = float(graph.get("mesh", {}).get("surface_area", 0.0))

    axis_pairs = [f for f in features if f.get("type") == "axis_boundary_plane_pair"]
    paired_axes = [f for f in axis_pairs if f.get("paired", False)]

    dims = {
        "x": float(bbox.get("width", 0.0)),
        "y": float(bbox.get("height", 0.0)),
        "z": float(bbox.get("depth", 0.0)),
    }
    thinnest_axis: Optional[str] = min(dims, key=dims.get) if dims else None  # type: ignore[arg-type]
    thinnest_axis_paired = any(
        f.get("axis") == thinnest_axis and f.get("paired", False)
        for f in axis_pairs
    )

    total_boundary_area = sum(
        f.get("negative_area", 0.0) + f.get("positive_area", 0.0)
        for f in axis_pairs
    )
    planar_support_fraction = (
        round(total_boundary_area / surface_area, 4)
        if surface_area > 0.0
        else 0.0
    )

    plate = _best_feature(graph, "plate_like_solid")
    box = _best_feature(graph, "box_like_solid")
    plate_confidence = round(float(plate["confidence"]), 4) if plate else None
    box_confidence = round(float(box["confidence"]), 4) if box else None

    return {
        "axis_pair_count": len(axis_pairs),
        "paired_axis_count": len(paired_axes),
        "thinnest_axis": thinnest_axis,
        "thinnest_axis_paired": thinnest_axis_paired,
        "planar_support_fraction": planar_support_fraction,
        "plate_candidate_confidence": plate_confidence,
        "box_candidate_confidence": box_confidence,
    }


def _failure_pattern_key(metadata: dict[str, Any]) -> str:
    """Derive a short human-readable pattern key from failure-shape metadata.

    Pattern hierarchy (first match wins):
    - plate/box candidate present → use confidence band
    - no candidate → split by ``planar_support_fraction``:
        ≥ 0.65 → high planar support, likely a real box/plate with edge tolerancing issue
        0.35–0.65 → medium planar support, ambiguous
        < 0.35 → low planar support, genuinely complex/organic geometry (e.g. 3DBenchy)
    """
    plate_conf = metadata.get("plate_candidate_confidence")
    box_conf = metadata.get("box_candidate_confidence")
    paired = int(metadata.get("paired_axis_count", 0))
    psf = float(metadata.get("planar_support_fraction", 0.0))

    if plate_conf is not None:
        if float(plate_conf) >= 0.50:
            return "plate_candidate_near_threshold"
        return "plate_candidate_low_confidence"
    if box_conf is not None:
        return "box_candidate_no_preview"
    if paired < 3:
        if paired > 0:
            return "axis_pairs_partial_paired"
        return "no_paired_axis_planes"
    # All 3 axes paired, no plate/box candidate — split by planar support
    if psf >= 0.65:
        return "high_planar_support_no_candidate"
    if psf >= 0.35:
        return "medium_planar_support_no_candidate"
    return "low_planar_support_complex_geometry"


def build_triage_report(
    graphs: list[dict[str, Any]],
    top_n: int = 5,
    input_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Build a triage report from a list of feature graphs.

    Each graph is assigned to one of the five buckets defined by
    :func:`_classify_graph_bucket`.  For the ``axis_pairs_only`` and
    ``feature_graph_no_preview`` buckets, failure-shape metadata is extracted and
    used to produce a ranked top-N failure-pattern summary.

    Args:
        graphs: list of feature-graph dicts (as returned by
            :func:`build_feature_graph_for_stl` / :func:`build_feature_graph_for_folder`).
        top_n:  maximum number of entries in ``ranked_failure_patterns``.
        input_dir: optional path string recorded in the report header.

    Returns:
        A triage-report dict with the keys documented in the Track A spec.
    """
    bucket_counts: dict[str, int] = {bucket: 0 for bucket in _TRIAGE_BUCKETS}
    per_file: list[dict[str, Any]] = []
    pattern_counts: dict[str, int] = {}
    pattern_examples: dict[str, str] = {}

    for graph in graphs:
        bucket = _classify_graph_bucket(graph)
        bucket_counts[bucket] += 1
        source_file = str(graph.get("source_file", ""))

        entry: dict[str, Any] = {"source_file": source_file, "bucket": bucket}
        if bucket in {"axis_pairs_only", "feature_graph_no_preview"}:
            metadata = _failure_shape_metadata(graph)
            entry["failure_shape_metadata"] = metadata
            pattern = _failure_pattern_key(metadata)
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
            if pattern not in pattern_examples:
                pattern_examples[pattern] = source_file
        per_file.append(entry)

    ranked = sorted(pattern_counts.items(), key=lambda kv: kv[1], reverse=True)
    ranked_failure_patterns = [
        {
            "pattern": pattern,
            "count": count,
            "representative_file": pattern_examples.get(pattern, ""),
        }
        for pattern, count in ranked[:top_n]
    ]

    files_processed = len(graphs)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": input_dir,
        "top_n": top_n,
        "files_processed": files_processed,
        "bucket_counts": bucket_counts,
        "ranked_failure_patterns": ranked_failure_patterns,
        "per_file": per_file,
    }
