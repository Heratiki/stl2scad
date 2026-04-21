"""
Manifest-driven OpenSCAD feature fixtures for detector validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional, Union

_SUPPORTED_FIXTURE_TYPES = {"plate", "box", "l_bracket", "sphere", "torus"}
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
_COUNTED_FEATURE_TYPES = (
    "plate_like_solid",
    "box_like_solid",
    "hole_like_cutout",
    "slot_like_cutout",
    "linear_hole_pattern",
    "grid_hole_pattern",
    "counterbore_hole",
)


def load_feature_fixture_manifest(
    manifest_path: Union[str, Path],
) -> list[dict[str, Any]]:
    """Load and validate feature fixtures from a JSON manifest."""
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema_version = payload.get("schema_version")
    if schema_version not in (1, 2):
        raise ValueError(
            f"Unsupported feature fixture manifest schema_version '{schema_version}'. Expected 1 or 2"
        )
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("Feature fixture manifest must contain a non-empty fixtures list")

    normalized: list[dict[str, Any]] = []
    names_seen: set[str] = set()
    for raw_fixture in fixtures:
        fixture = validate_feature_fixture_spec(raw_fixture, schema_version=schema_version)
        name = str(fixture["name"])
        if name in names_seen:
            raise ValueError(f"Duplicate feature fixture name: {name}")
        names_seen.add(name)
        normalized.append(fixture)
    return normalized


def validate_feature_fixture_spec(raw_fixture: dict[str, Any], schema_version: int = 1) -> dict[str, Any]:
    """Validate one feature fixture spec and return a normalized copy.
    
    For schema_version 1: expected_detection is required and implicitly represents a single candidate.
    For schema_version 2: candidates array is required; each candidate has rank, name, confidence, expected_detection.
    """
    if not isinstance(raw_fixture, dict):
        raise ValueError("Feature fixture entries must be objects")

    fixture_type = str(raw_fixture.get("fixture_type", "")).strip()
    if fixture_type not in _SUPPORTED_FIXTURE_TYPES:
        supported = ", ".join(sorted(_SUPPORTED_FIXTURE_TYPES))
        raise ValueError(
            f"Unsupported feature fixture type '{fixture_type}'. Supported types: {supported}"
        )

    name = str(raw_fixture.get("name", "")).strip()
    if not name:
        raise ValueError("Feature fixture name is required")

    output_filename = str(raw_fixture.get("output_filename", "")).strip()
    if not output_filename.endswith(".scad"):
        raise ValueError(f"Feature fixture '{name}' must define a .scad output_filename")

    spec: dict[str, Any] = {
        "name": name,
        "fixture_type": fixture_type,
        "description": str(raw_fixture.get("description", "")).strip(),
        "output_filename": output_filename,
        "transform": _validate_fixture_transform(raw_fixture.get("transform"), name),
    }

    # Handle candidates for schema v2; fall back to expected_detection for v1
    if schema_version >= 2:
        candidates = raw_fixture.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"Feature fixture '{name}' (schema v2) requires candidates array")
        spec["candidates"] = _validate_candidates(candidates, name)
        # For backward compatibility, also populate expected_detection from primary candidate
        spec["expected_detection"] = spec["candidates"][0]["expected_detection"]
    else:
        # Schema v1: expected_detection only
        expected_detection = _validate_expected_detection(
            raw_fixture.get("expected_detection"), name
        )
        spec["expected_detection"] = expected_detection
        # Wrap in candidates for consistent internal representation
        spec["candidates"] = [
            {
                "rank": 1,
                "name": "primary",
                "confidence": 0.95,
                "expected_detection": expected_detection,
            }
        ]

    geometry = _validate_geometry_by_fixture_type(raw_fixture, name, fixture_type)
    spec.update(geometry)

    expected = spec["expected_detection"]
    explicit_holes = int(spec.get("explicit_hole_count", 0))
    explicit_slots = int(spec.get("explicit_slot_count", 0))
    explicit_counterbores = int(spec.get("explicit_counterbore_count", 0))
    if expected["hole_count"] > explicit_holes:
        raise ValueError(
            f"Feature fixture '{name}' expects {expected['hole_count']} holes but only defines {explicit_holes}"
        )
    if expected["slot_count"] > explicit_slots:
        raise ValueError(
            f"Feature fixture '{name}' expects {expected['slot_count']} slots but only defines {explicit_slots}"
        )
    if expected["counterbore_count"] > explicit_counterbores:
        raise ValueError(
            f"Feature fixture '{name}' expects {expected['counterbore_count']} counterbores but only defines {explicit_counterbores}"
        )

    return spec


def generate_feature_fixture_scad(fixture: dict[str, Any]) -> str:
    """Generate OpenSCAD source for one validated fixture."""
    normalized = validate_feature_fixture_spec(
        fixture,
        schema_version=_fixture_schema_version(fixture),
    )
    fixture_type = normalized["fixture_type"]
    if fixture_type == "plate":
        return _generate_plate_fixture_scad(normalized)
    if fixture_type == "box":
        return _generate_box_fixture_scad(normalized)
    if fixture_type == "l_bracket":
        return _generate_l_bracket_fixture_scad(normalized)
    if fixture_type == "sphere":
        return _generate_sphere_fixture_scad(normalized)
    if fixture_type == "torus":
        return _generate_torus_fixture_scad(normalized)
    raise ValueError(f"Unsupported feature fixture type '{fixture_type}'")


def write_feature_fixture_library(
    manifest_path: Union[str, Path],
    output_dir: Union[str, Path],
) -> list[Path]:
    """Generate all SCAD fixtures from a manifest."""
    fixtures = load_feature_fixture_manifest(manifest_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for fixture in fixtures:
        target = output_path / fixture["output_filename"]
        target.write_text(generate_feature_fixture_scad(fixture), encoding="utf-8")
        written.append(target)
    return written


def iter_expected_feature_counts(
    fixture: dict[str, Any],
) -> dict[str, int]:
    """Return expected detector counts for a validated fixture."""
    expected = fixture["expected_detection"]
    return _expected_feature_counts(expected)


def summarize_detected_feature_counts(graph: dict[str, Any]) -> dict[str, int]:
    """Count detector output entries for the feature types tracked by fixtures."""
    feature_counts = {feature_type: 0 for feature_type in _COUNTED_FEATURE_TYPES}
    for feature in graph.get("features", []):
        feature_type = str(feature.get("type", ""))
        if feature_type in feature_counts:
            feature_counts[feature_type] += 1
    return feature_counts


def rank_feature_fixture_candidates(
    fixture: dict[str, Any],
    graph: dict[str, Any],
) -> list[dict[str, Any]]:
    """Rank declared fixture interpretations against an observed feature graph."""
    normalized = validate_feature_fixture_spec(
        fixture,
        schema_version=_fixture_schema_version(fixture),
    )
    actual_counts = summarize_detected_feature_counts(graph)
    confidence_by_type: dict[str, list[float]] = {
        feature_type: [] for feature_type in _COUNTED_FEATURE_TYPES
    }
    for feature in graph.get("features", []):
        feature_type = str(feature.get("type", ""))
        if feature_type not in confidence_by_type:
            continue
        confidence_by_type[feature_type].append(float(feature.get("confidence", 0.0)))
    for confidences in confidence_by_type.values():
        confidences.sort(reverse=True)

    rankings: list[dict[str, Any]] = []
    for candidate in normalized["candidates"]:
        expected_counts = _expected_feature_counts(candidate["expected_detection"])
        total_delta = sum(
            abs(actual_counts[feature_type] - expected_counts[feature_type])
            for feature_type in _COUNTED_FEATURE_TYPES
        )
        normalization = sum(
            max(actual_counts[feature_type], expected_counts[feature_type], 1)
            for feature_type in _COUNTED_FEATURE_TYPES
        )
        match_score = max(0.0, 1.0 - float(total_delta) / float(normalization))
        support_confidence = _candidate_support_confidence(
            expected_counts,
            confidence_by_type,
        )
        exact_match = total_delta == 0
        rankings.append(
            {
                "rank": int(candidate["rank"]),
                "name": str(candidate["name"]),
                "declared_confidence": float(candidate["confidence"]),
                "expected_feature_counts": expected_counts,
                "actual_feature_counts": dict(actual_counts),
                "count_delta": int(total_delta),
                "match_score": float(match_score),
                "support_confidence": float(support_confidence),
                "candidate_confidence": float(match_score * support_confidence),
                "exact_match": bool(exact_match),
            }
        )

    rankings.sort(
        key=lambda item: (
            item["exact_match"],
            item["candidate_confidence"],
            item["match_score"],
            item["declared_confidence"],
            -item["rank"],
        ),
        reverse=True,
    )
    return rankings


def _expected_feature_counts(expected: dict[str, Any]) -> dict[str, int]:
    return {
        "plate_like_solid": 1 if expected["plate_like_solid"] else 0,
        "box_like_solid": 1 if expected["box_like_solid"] else 0,
        "hole_like_cutout": expected["hole_count"],
        "slot_like_cutout": expected["slot_count"],
        "linear_hole_pattern": expected["linear_pattern_count"],
        "grid_hole_pattern": expected["grid_pattern_count"],
        "counterbore_hole": expected["counterbore_count"],
    }


def _candidate_support_confidence(
    expected_counts: dict[str, int],
    confidence_by_type: dict[str, list[float]],
) -> float:
    required_confidences: list[float] = []
    for feature_type, expected_count in expected_counts.items():
        if expected_count <= 0:
            continue
        confidences = confidence_by_type.get(feature_type, [])
        if len(confidences) < expected_count:
            return 0.0
        required_confidences.append(float(confidences[expected_count - 1]))
    if not required_confidences:
        return 1.0
    return min(required_confidences)


def _fixture_schema_version(raw_fixture: dict[str, Any]) -> int:
    candidates = raw_fixture.get("candidates")
    if isinstance(candidates, list) and candidates:
        return 2
    return 1


def _validate_geometry_by_fixture_type(
    raw_fixture: dict[str, Any],
    fixture_name: str,
    fixture_type: str,
) -> dict[str, Any]:
    if fixture_type == "plate":
        return _validate_plate_fixture_geometry(raw_fixture, fixture_name)
    if fixture_type == "box":
        return _validate_box_fixture_geometry(raw_fixture, fixture_name)
    if fixture_type == "l_bracket":
        return _validate_l_bracket_fixture_geometry(raw_fixture, fixture_name)
    if fixture_type == "sphere":
        return _validate_sphere_fixture_geometry(raw_fixture, fixture_name)
    if fixture_type == "torus":
        return _validate_torus_fixture_geometry(raw_fixture, fixture_name)
    raise ValueError(f"Unsupported feature fixture type '{fixture_type}'")


def _validate_plate_fixture_geometry(
    raw_fixture: dict[str, Any],
    fixture_name: str,
) -> dict[str, Any]:
    plate_size = _as_vector3(raw_fixture.get("plate_size"), f"{fixture_name}.plate_size")
    _require_positive(plate_size, f"{fixture_name}.plate_size")
    edge_chamfer = _as_non_negative_float(
        raw_fixture.get("edge_chamfer", 0.0),
        f"{fixture_name}.edge_chamfer",
    )
    if edge_chamfer * 2.0 >= min(plate_size[0], plate_size[1]):
        raise ValueError(
            f"{fixture_name}.edge_chamfer must leave a positive top face footprint"
        )
    feature_plate_size = [
        plate_size[0] - 2.0 * edge_chamfer,
        plate_size[1] - 2.0 * edge_chamfer,
        plate_size[2],
    ]

    spec: dict[str, Any] = {
        "plate_size": plate_size,
        "edge_chamfer": edge_chamfer,
        "holes": [],
        "counterbores": [],
        "linear_hole_patterns": [],
        "grid_hole_patterns": [],
        "slots": [],
    }

    for index, raw_hole in enumerate(raw_fixture.get("holes", [])):
        spec["holes"].append(
            _validate_plate_hole(raw_hole, fixture_name, index, feature_plate_size)
        )

    for index, raw_counterbore in enumerate(raw_fixture.get("counterbores", [])):
        spec["counterbores"].append(
            _validate_plate_counterbore(
                raw_counterbore,
                fixture_name,
                index,
                feature_plate_size,
            )
        )

    for index, raw_pattern in enumerate(raw_fixture.get("linear_hole_patterns", [])):
        spec["linear_hole_patterns"].append(
            _validate_linear_pattern(raw_pattern, fixture_name, index, feature_plate_size)
        )

    for index, raw_pattern in enumerate(raw_fixture.get("grid_hole_patterns", [])):
        spec["grid_hole_patterns"].append(
            _validate_grid_pattern(raw_pattern, fixture_name, index, feature_plate_size)
        )

    for index, raw_slot in enumerate(raw_fixture.get("slots", [])):
        spec["slots"].append(_validate_slot(raw_slot, fixture_name, index, feature_plate_size))

    explicit_holes = len(spec["holes"])
    explicit_holes += sum(
        int(pattern["count"]) for pattern in spec["linear_hole_patterns"]
    )
    explicit_holes += sum(
        int(pattern["rows"]) * int(pattern["cols"])
        for pattern in spec["grid_hole_patterns"]
    )
    spec["explicit_hole_count"] = explicit_holes
    spec["explicit_slot_count"] = len(spec["slots"])
    spec["explicit_counterbore_count"] = len(spec["counterbores"])
    return spec


def _validate_box_fixture_geometry(
    raw_fixture: dict[str, Any],
    fixture_name: str,
) -> dict[str, Any]:
    box_size = _as_vector3(raw_fixture.get("box_size"), f"{fixture_name}.box_size")
    _require_positive(box_size, f"{fixture_name}.box_size")

    spec: dict[str, Any] = {
        "box_size": box_size,
        "holes": [],
        "cutouts": [],
        "explicit_hole_count": 0,
        "explicit_slot_count": 0,
    }

    for index, raw_hole in enumerate(raw_fixture.get("holes", [])):
        spec["holes"].append(_validate_box_hole(raw_hole, fixture_name, index, box_size))

    for index, raw_cutout in enumerate(raw_fixture.get("cutouts", [])):
        spec["cutouts"].append(
            _validate_box_cutout(raw_cutout, fixture_name, index, box_size)
        )

    spec["explicit_hole_count"] = len(spec["holes"])
    return spec


def _validate_l_bracket_fixture_geometry(
    raw_fixture: dict[str, Any],
    fixture_name: str,
) -> dict[str, Any]:
    bracket_size = _as_vector3(
        raw_fixture.get("bracket_size"), f"{fixture_name}.bracket_size"
    )
    _require_positive(bracket_size, f"{fixture_name}.bracket_size")
    leg_thickness = _as_positive_float(
        raw_fixture.get("leg_thickness"),
        f"{fixture_name}.leg_thickness",
    )
    max_thickness = min(bracket_size[0], bracket_size[2])
    if leg_thickness >= max_thickness:
        raise ValueError(
            f"{fixture_name}.leg_thickness must be smaller than bracket width and height"
        )

    return {
        "bracket_size": bracket_size,
        "leg_thickness": leg_thickness,
        "explicit_hole_count": 0,
        "explicit_slot_count": 0,
    }


def _validate_sphere_fixture_geometry(
    raw_fixture: dict[str, Any],
    fixture_name: str,
) -> dict[str, Any]:
    radius = _as_positive_float(
        raw_fixture.get("radius"),
        f"{fixture_name}.radius",
    )
    return {
        "radius": radius,
        "explicit_hole_count": 0,
        "explicit_slot_count": 0,
    }


def _validate_torus_fixture_geometry(
    raw_fixture: dict[str, Any],
    fixture_name: str,
) -> dict[str, Any]:
    major_radius = _as_positive_float(
        raw_fixture.get("major_radius"),
        f"{fixture_name}.major_radius",
    )
    minor_radius = _as_positive_float(
        raw_fixture.get("minor_radius"),
        f"{fixture_name}.minor_radius",
    )
    if minor_radius >= major_radius:
        raise ValueError(
            f"{fixture_name}.minor_radius must be smaller than major_radius"
        )
    return {
        "major_radius": major_radius,
        "minor_radius": minor_radius,
        "explicit_hole_count": 0,
        "explicit_slot_count": 0,
    }


def _generate_plate_fixture_scad(fixture: dict[str, Any]) -> str:
    plate_size = fixture["plate_size"]
    edge_chamfer = float(fixture.get("edge_chamfer", 0.0))
    half_x = plate_size[0] * 0.5
    half_y = plate_size[1] * 0.5
    thickness = plate_size[2]
    cut_height = thickness + 0.2
    z_offset = -0.1

    lines = _fixture_header_lines(fixture)
    lines.extend(
        [
            f"plate_size = {_format_vector(plate_size)};",
            f"plate_origin = {_format_vector([-half_x, -half_y, 0.0])};",
            "",
            "module through_hole(center, diameter, height) {",
            "  translate(center) cylinder(d=diameter, h=height, center=false);",
            "}",
            "",
            "module through_slot(start, end, width, height) {",
            "  hull() {",
            "    through_hole(start, width, height);",
            "    through_hole(end, width, height);",
            "  }",
            "}",
            "",
            "module counterbore_hole(center, through_d, bore_d, bore_depth, plate_thickness) {",
            "  translate([center[0], center[1], -0.1])",
            "    cylinder(d=through_d, h=plate_thickness + 0.2, center=false);",
            "  translate([center[0], center[1], plate_thickness - bore_depth])",
            "    cylinder(d=bore_d, h=bore_depth + 0.1, center=false);",
            "}",
            "",
        ]
    )
    if edge_chamfer > 0.0:
        top_scale = [
            (plate_size[0] - 2.0 * edge_chamfer) / plate_size[0],
            (plate_size[1] - 2.0 * edge_chamfer) / plate_size[1],
        ]
        lines.extend(
            [
                f"plate_edge_chamfer = {edge_chamfer:.6f};",
                f"plate_top_scale = {_format_vector(top_scale)};",
                "",
            ]
        )

    transform = fixture.get("transform", _identity_transform())
    has_transform = _has_non_identity_transform(transform)
    plate_base_line = (
        "  linear_extrude(height=plate_size[2], scale=plate_top_scale)"
        " square([plate_size[0], plate_size[1]], center=true);"
        if edge_chamfer > 0.0
        else "  translate(plate_origin) cube(plate_size);"
    )
    if has_transform:
        lines.extend(
            [
                f"translate({_format_vector(transform['translate'])})",
                f"rotate({_format_vector(transform['rotate'])}) {{",
                "difference() {",
                plate_base_line,
            ]
        )
    else:
        lines.extend(["difference() {", plate_base_line])

    for index, hole in enumerate(fixture["holes"]):
        center = [hole["center"][0], hole["center"][1], z_offset]
        lines.append(
            f"  through_hole({_format_vector(center)}, {hole['diameter']:.6f}, {cut_height:.6f});  // hole_{index}"
        )

    for index, pattern in enumerate(fixture["linear_hole_patterns"]):
        origin = [pattern["origin"][0], pattern["origin"][1], z_offset]
        step = [pattern["step"][0], pattern["step"][1], 0.0]
        lines.extend(
            [
                f"  for (i = [0 : {int(pattern['count']) - 1}]) {{",
                f"    through_hole({_format_vector(origin)} + i * {_format_vector(step)}, {pattern['diameter']:.6f}, {cut_height:.6f});  // linear_pattern_{index}",
                "  }",
            ]
        )

    for index, pattern in enumerate(fixture["grid_hole_patterns"]):
        origin = [pattern["origin"][0], pattern["origin"][1], z_offset]
        row_step = [pattern["row_step"][0], pattern["row_step"][1], 0.0]
        col_step = [pattern["col_step"][0], pattern["col_step"][1], 0.0]
        lines.extend(
            [
                f"  for (row = [0 : {int(pattern['rows']) - 1}]) {{",
                f"    for (col = [0 : {int(pattern['cols']) - 1}]) {{",
                f"      through_hole({_format_vector(origin)} + row * {_format_vector(row_step)} + col * {_format_vector(col_step)}, {pattern['diameter']:.6f}, {cut_height:.6f});  // grid_pattern_{index}",
                "    }",
                "  }",
            ]
        )

    for index, counterbore in enumerate(fixture["counterbores"]):
        center = [counterbore["center"][0], counterbore["center"][1], 0.0]
        lines.append(
            f"  counterbore_hole({_format_vector(center)}, {counterbore['through_diameter']:.6f}, {counterbore['bore_diameter']:.6f}, {counterbore['bore_depth']:.6f}, {thickness:.6f});  // counterbore_{index}"
        )

    for index, slot in enumerate(fixture["slots"]):
        start = [slot["start"][0], slot["start"][1], z_offset]
        end = [slot["end"][0], slot["end"][1], z_offset]
        lines.append(
            f"  through_slot({_format_vector(start)}, {_format_vector(end)}, {slot['width']:.6f}, {cut_height:.6f});  // slot_{index}"
        )

    lines.extend(["}"])
    if has_transform:
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _generate_box_fixture_scad(fixture: dict[str, Any]) -> str:
    box_size = fixture["box_size"]
    half_x = box_size[0] * 0.5
    half_y = box_size[1] * 0.5
    half_z = box_size[2] * 0.5
    cut_lengths = {
        "x": box_size[0] + 0.2,
        "y": box_size[1] + 0.2,
        "z": box_size[2] + 0.2,
    }

    lines = _fixture_header_lines(fixture)
    lines.extend(
        [
            f"box_size = {_format_vector(box_size)};",
            f"box_origin = {_format_vector([-half_x, -half_y, -half_z])};",
            "",
            "module through_hole_x(center, diameter, length) {",
            "  translate([box_origin[0] - 0.1, center[1], center[2]])",
            "    rotate(a=90, v=[0, 1, 0]) cylinder(d=diameter, h=length, center=false);",
            "}",
            "",
            "module through_hole_y(center, diameter, length) {",
            "  translate([center[0], box_origin[1] - 0.1, center[2]])",
            "    rotate(a=90, v=[-1, 0, 0]) cylinder(d=diameter, h=length, center=false);",
            "}",
            "",
            "module through_hole_z(center, diameter, length) {",
            "  translate([center[0], center[1], box_origin[2] - 0.1])",
            "    cylinder(d=diameter, h=length, center=false);",
            "}",
            "",
        ]
    )

    transform = fixture.get("transform", _identity_transform())
    has_transform = _has_non_identity_transform(transform)
    if has_transform:
        lines.extend(
            [
                f"translate({_format_vector(transform['translate'])})",
                f"rotate({_format_vector(transform['rotate'])}) {{",
                "difference() {",
                "  translate(box_origin) cube(box_size);",
            ]
        )
    else:
        lines.extend(["difference() {", "  translate(box_origin) cube(box_size);"])

    for index, hole in enumerate(fixture["holes"]):
        center = _format_vector(hole["center"])
        length = cut_lengths[hole["axis"]]
        lines.append(
            f"  through_hole_{hole['axis']}({center}, {hole['diameter']:.6f}, {length:.6f});  // hole_{index}"
        )

    for index, cutout in enumerate(fixture["cutouts"]):
        cutout_origin = [
            cutout["center"][0] - cutout["size"][0] * 0.5,
            cutout["center"][1] - cutout["size"][1] * 0.5,
            cutout["center"][2] - cutout["size"][2] * 0.5,
        ]
        lines.append(
            f"  translate({_format_vector(cutout_origin)}) cube({_format_vector(cutout['size'])});  // cutout_{index}"
        )

    lines.extend(["}"])
    if has_transform:
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _generate_l_bracket_fixture_scad(fixture: dict[str, Any]) -> str:
    bracket_size = fixture["bracket_size"]
    leg_thickness = fixture["leg_thickness"]
    half_x = bracket_size[0] * 0.5
    half_y = bracket_size[1] * 0.5
    half_z = bracket_size[2] * 0.5

    lines = _fixture_header_lines(fixture)
    lines.extend(
        [
            f"bracket_size = {_format_vector(bracket_size)};",
            f"leg_thickness = {leg_thickness:.6f};",
            f"bracket_origin = {_format_vector([-half_x, -half_y, -half_z])};",
            "",
        ]
    )

    transform = fixture.get("transform", _identity_transform())
    has_transform = _has_non_identity_transform(transform)
    if has_transform:
        lines.extend(
            [
                f"translate({_format_vector(transform['translate'])})",
                f"rotate({_format_vector(transform['rotate'])}) {{",
                "union() {",
                "  translate(bracket_origin) cube([bracket_size[0], bracket_size[1], leg_thickness]);",
                "  translate(bracket_origin) cube([leg_thickness, bracket_size[1], bracket_size[2]]);",
                "}",
                "}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "union() {",
                "  translate(bracket_origin) cube([bracket_size[0], bracket_size[1], leg_thickness]);",
                "  translate(bracket_origin) cube([leg_thickness, bracket_size[1], bracket_size[2]]);",
                "}",
                "",
            ]
        )
    return "\n".join(lines)


def _generate_sphere_fixture_scad(fixture: dict[str, Any]) -> str:
    radius = fixture["radius"]
    lines = _fixture_header_lines(fixture)
    lines.extend(
        [
            f"radius = {radius:.6f};",
            "",
            "sphere(r=radius);",
            "",
        ]
    )
    return "\n".join(lines)


def _generate_torus_fixture_scad(fixture: dict[str, Any]) -> str:
    major_radius = fixture["major_radius"]
    minor_radius = fixture["minor_radius"]
    lines = _fixture_header_lines(fixture)
    lines.extend(
        [
            f"major_radius = {major_radius:.6f};",
            f"minor_radius = {minor_radius:.6f};",
            "",
            "module torus(major_r, minor_r) {",
            "  rotate_extrude(convexity = 10, $fn = 96)",
            "    translate([major_r, 0, 0])",
            "      circle(r = minor_r, $fn = 64);",
            "}",
            "",
            "torus(major_radius, minor_radius);",
            "",
        ]
    )
    return "\n".join(lines)


def _fixture_header_lines(fixture: dict[str, Any]) -> list[str]:
    lines = [
        "// Auto-generated from tests/data/feature_fixtures_manifest.json",
        f"// fixture: {fixture['name']}",
        f"// fixture_type: {fixture['fixture_type']}",
        f"// description: {fixture.get('description', '')}",
        "$fn = 96;",
        "",
    ]
    transform = fixture.get("transform", _identity_transform())
    if _has_non_identity_transform(transform):
        lines.insert(
            4,
            "// transform: rotate="
            f"{_format_vector(transform['rotate'])}, "
            f"translate={_format_vector(transform['translate'])}",
        )
    return lines


def _identity_transform() -> dict[str, list[float]]:
    return {"rotate": [0.0, 0.0, 0.0], "translate": [0.0, 0.0, 0.0]}


def _validate_fixture_transform(
    raw_transform: Optional[dict[str, Any]],
    fixture_name: str,
) -> dict[str, list[float]]:
    if raw_transform is None:
        return _identity_transform()
    if not isinstance(raw_transform, dict):
        raise ValueError(f"{fixture_name}.transform must be an object")
    rotate = _as_vector3(raw_transform.get("rotate", [0.0, 0.0, 0.0]), f"{fixture_name}.transform.rotate")
    translate = _as_vector3(
        raw_transform.get("translate", [0.0, 0.0, 0.0]),
        f"{fixture_name}.transform.translate",
    )
    return {"rotate": rotate, "translate": translate}


def _has_non_identity_transform(transform: dict[str, list[float]]) -> bool:
    for key in ("rotate", "translate"):
        if any(abs(float(value)) > 1e-9 for value in transform[key]):
            return True
    return False


def _validate_expected_detection(
    raw_expected: Optional[dict[str, Any]], fixture_name: str
) -> dict[str, Any]:
    if not isinstance(raw_expected, dict):
        raise ValueError(
            f"Feature fixture '{fixture_name}' must define expected_detection"
        )
    expected = {
        "plate_like_solid": bool(raw_expected.get("plate_like_solid", False)),
        "box_like_solid": bool(raw_expected.get("box_like_solid", False)),
        "hole_count": _as_non_negative_int(
            raw_expected.get("hole_count", 0),
            f"{fixture_name}.expected_detection.hole_count",
        ),
        "slot_count": _as_non_negative_int(
            raw_expected.get("slot_count", 0),
            f"{fixture_name}.expected_detection.slot_count",
        ),
        "linear_pattern_count": _as_non_negative_int(
            raw_expected.get("linear_pattern_count", 0),
            f"{fixture_name}.expected_detection.linear_pattern_count",
        ),
        "grid_pattern_count": _as_non_negative_int(
            raw_expected.get("grid_pattern_count", 0),
            f"{fixture_name}.expected_detection.grid_pattern_count",
        ),
        "counterbore_count": _as_non_negative_int(
            raw_expected.get("counterbore_count", 0),
            f"{fixture_name}.expected_detection.counterbore_count",
        ),
    }
    return expected


def _validate_candidates(
    raw_candidates: list[Any],
    fixture_name: str,
) -> list[dict[str, Any]]:
    """Validate candidates array for schema v2 fixtures.
    
    Each candidate must have: rank, name, confidence, expected_detection.
    Candidates must be sorted by rank (ascending).
    """
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError(f"Feature fixture '{fixture_name}' candidates must be non-empty array")
    
    validated_candidates: list[dict[str, Any]] = []
    ranks_seen: set[int] = set()
    
    for index, raw_candidate in enumerate(raw_candidates):
        if not isinstance(raw_candidate, dict):
            raise ValueError(
                f"Feature fixture '{fixture_name}' candidates[{index}] must be object"
            )
        
        rank = int(raw_candidate.get("rank", 0))
        if rank < 1:
            raise ValueError(
                f"Feature fixture '{fixture_name}' candidates[{index}].rank must be >= 1"
            )
        if rank in ranks_seen:
            raise ValueError(
                f"Feature fixture '{fixture_name}' has duplicate rank {rank}"
            )
        ranks_seen.add(rank)
        
        name = str(raw_candidate.get("name", "")).strip()
        if not name:
            raise ValueError(
                f"Feature fixture '{fixture_name}' candidates[{index}].name is required"
            )
        
        confidence = float(raw_candidate.get("confidence", 0.0))
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(
                f"Feature fixture '{fixture_name}' candidates[{index}].confidence must be 0.0-1.0"
            )
        
        expected_detection = _validate_expected_detection(
            raw_candidate.get("expected_detection"),
            f"{fixture_name}.candidates[{index}]",
        )
        
        validated_candidates.append({
            "rank": rank,
            "name": name,
            "confidence": confidence,
            "expected_detection": expected_detection,
        })
    
    # Sort by rank to ensure consistent ordering
    validated_candidates.sort(key=lambda c: c["rank"])
    return validated_candidates


def _validate_plate_hole(
    raw_hole: dict[str, Any],
    fixture_name: str,
    index: int,
    plate_size: list[float],
) -> dict[str, Any]:
    center = _as_vector2(raw_hole.get("center"), f"{fixture_name}.holes[{index}].center")
    diameter = _as_positive_float(
        raw_hole.get("diameter"),
        f"{fixture_name}.holes[{index}].diameter",
    )
    _require_circle_inside_plate(
        center,
        diameter * 0.5,
        plate_size,
        fixture_name,
        f"holes[{index}]",
    )
    return {"center": center, "diameter": diameter}


def _validate_plate_counterbore(
    raw_counterbore: dict[str, Any],
    fixture_name: str,
    index: int,
    plate_size: list[float],
) -> dict[str, Any]:
    center = _as_vector2(
        raw_counterbore.get("center"),
        f"{fixture_name}.counterbores[{index}].center",
    )
    through_diameter = _as_positive_float(
        raw_counterbore.get("through_diameter"),
        f"{fixture_name}.counterbores[{index}].through_diameter",
    )
    bore_diameter = _as_positive_float(
        raw_counterbore.get("bore_diameter"),
        f"{fixture_name}.counterbores[{index}].bore_diameter",
    )
    bore_depth = _as_positive_float(
        raw_counterbore.get("bore_depth"),
        f"{fixture_name}.counterbores[{index}].bore_depth",
    )
    if bore_diameter <= through_diameter:
        raise ValueError(
            f"{fixture_name}.counterbores[{index}].bore_diameter must be larger than through_diameter"
        )
    thickness = plate_size[2]
    if bore_depth >= thickness:
        raise ValueError(
            f"{fixture_name}.counterbores[{index}].bore_depth must be less than plate thickness"
        )
    _require_circle_inside_plate(
        center,
        bore_diameter * 0.5,
        plate_size,
        fixture_name,
        f"counterbores[{index}]",
    )
    return {
        "center": center,
        "through_diameter": through_diameter,
        "bore_diameter": bore_diameter,
        "bore_depth": bore_depth,
    }


def _validate_box_hole(
    raw_hole: dict[str, Any],
    fixture_name: str,
    index: int,
    box_size: list[float],
) -> dict[str, Any]:
    axis = str(raw_hole.get("axis", "")).strip().lower()
    if axis not in _AXIS_INDEX:
        raise ValueError(f"{fixture_name}.holes[{index}].axis must be one of x, y, z")
    center = _as_vector3(raw_hole.get("center"), f"{fixture_name}.holes[{index}].center")
    diameter = _as_positive_float(
        raw_hole.get("diameter"),
        f"{fixture_name}.holes[{index}].diameter",
    )
    _require_point_inside_centered_box(
        center,
        box_size,
        fixture_name,
        f"holes[{index}].center",
    )
    _require_circle_inside_box_cross_section(
        center,
        axis,
        diameter * 0.5,
        box_size,
        fixture_name,
        f"holes[{index}]",
    )
    return {"axis": axis, "center": center, "diameter": diameter}


def _validate_box_cutout(
    raw_cutout: dict[str, Any],
    fixture_name: str,
    index: int,
    box_size: list[float],
) -> dict[str, Any]:
    center = _as_vector3(
        raw_cutout.get("center"),
        f"{fixture_name}.cutouts[{index}].center",
    )
    size = _as_vector3(raw_cutout.get("size"), f"{fixture_name}.cutouts[{index}].size")
    _require_positive(size, f"{fixture_name}.cutouts[{index}].size")
    _require_centered_box_inside_box(center, size, box_size, fixture_name, f"cutouts[{index}]")
    return {"center": center, "size": size}


def _validate_linear_pattern(
    raw_pattern: dict[str, Any],
    fixture_name: str,
    index: int,
    plate_size: list[float],
) -> dict[str, Any]:
    origin = _as_vector2(
        raw_pattern.get("origin"),
        f"{fixture_name}.linear_hole_patterns[{index}].origin",
    )
    step = _as_vector2(
        raw_pattern.get("step"),
        f"{fixture_name}.linear_hole_patterns[{index}].step",
    )
    count = _as_non_negative_int(
        raw_pattern.get("count"),
        f"{fixture_name}.linear_hole_patterns[{index}].count",
    )
    if count < 2:
        raise ValueError(
            f"{fixture_name}.linear_hole_patterns[{index}].count must be >= 2"
        )
    diameter = _as_positive_float(
        raw_pattern.get("diameter"),
        f"{fixture_name}.linear_hole_patterns[{index}].diameter",
    )
    centers = [
        [origin[0] + step[0] * item_index, origin[1] + step[1] * item_index]
        for item_index in range(count)
    ]
    if len({(round(center[0], 8), round(center[1], 8)) for center in centers}) != count:
        raise ValueError(
            f"{fixture_name}.linear_hole_patterns[{index}] produces duplicate hole centers"
        )
    for center in centers:
        _require_circle_inside_plate(
            center,
            diameter * 0.5,
            plate_size,
            fixture_name,
            f"linear_hole_patterns[{index}]",
        )
    return {"origin": origin, "step": step, "count": count, "diameter": diameter}


def _validate_grid_pattern(
    raw_pattern: dict[str, Any],
    fixture_name: str,
    index: int,
    plate_size: list[float],
) -> dict[str, Any]:
    origin = _as_vector2(
        raw_pattern.get("origin"),
        f"{fixture_name}.grid_hole_patterns[{index}].origin",
    )
    row_step = _as_vector2(
        raw_pattern.get("row_step"),
        f"{fixture_name}.grid_hole_patterns[{index}].row_step",
    )
    col_step = _as_vector2(
        raw_pattern.get("col_step"),
        f"{fixture_name}.grid_hole_patterns[{index}].col_step",
    )
    rows = _as_non_negative_int(
        raw_pattern.get("rows"),
        f"{fixture_name}.grid_hole_patterns[{index}].rows",
    )
    cols = _as_non_negative_int(
        raw_pattern.get("cols"),
        f"{fixture_name}.grid_hole_patterns[{index}].cols",
    )
    if rows < 2 or cols < 2:
        raise ValueError(
            f"{fixture_name}.grid_hole_patterns[{index}] rows and cols must both be >= 2"
        )
    diameter = _as_positive_float(
        raw_pattern.get("diameter"),
        f"{fixture_name}.grid_hole_patterns[{index}].diameter",
    )
    centers = [
        [
            origin[0] + row_step[0] * row + col_step[0] * col,
            origin[1] + row_step[1] * row + col_step[1] * col,
        ]
        for row in range(rows)
        for col in range(cols)
    ]
    if len({(round(center[0], 8), round(center[1], 8)) for center in centers}) != rows * cols:
        raise ValueError(
            f"{fixture_name}.grid_hole_patterns[{index}] produces duplicate hole centers"
        )
    for center in centers:
        _require_circle_inside_plate(
            center,
            diameter * 0.5,
            plate_size,
            fixture_name,
            f"grid_hole_patterns[{index}]",
        )
    return {
        "origin": origin,
        "row_step": row_step,
        "col_step": col_step,
        "rows": rows,
        "cols": cols,
        "diameter": diameter,
    }


def _validate_slot(
    raw_slot: dict[str, Any],
    fixture_name: str,
    index: int,
    plate_size: list[float],
) -> dict[str, Any]:
    start = _as_vector2(raw_slot.get("start"), f"{fixture_name}.slots[{index}].start")
    end = _as_vector2(raw_slot.get("end"), f"{fixture_name}.slots[{index}].end")
    width = _as_positive_float(
        raw_slot.get("width"),
        f"{fixture_name}.slots[{index}].width",
    )
    if start == end:
        raise ValueError(f"{fixture_name}.slots[{index}] start and end must differ")
    _require_circle_inside_plate(
        start,
        width * 0.5,
        plate_size,
        fixture_name,
        f"slots[{index}].start",
    )
    _require_circle_inside_plate(
        end,
        width * 0.5,
        plate_size,
        fixture_name,
        f"slots[{index}].end",
    )
    return {"start": start, "end": end, "width": width}


def _require_circle_inside_plate(
    center: list[float],
    radius: float,
    plate_size: list[float],
    fixture_name: str,
    label: str,
) -> None:
    half_x = plate_size[0] * 0.5
    half_y = plate_size[1] * 0.5
    if center[0] - radius < -half_x or center[0] + radius > half_x:
        raise ValueError(f"{fixture_name}.{label} extends beyond the plate width")
    if center[1] - radius < -half_y or center[1] + radius > half_y:
        raise ValueError(f"{fixture_name}.{label} extends beyond the plate depth")


def _require_point_inside_centered_box(
    center: list[float],
    box_size: list[float],
    fixture_name: str,
    label: str,
) -> None:
    half_sizes = [dimension * 0.5 for dimension in box_size]
    axis_names = ("width", "depth", "height")
    for axis_index, axis_name in enumerate(axis_names):
        if center[axis_index] < -half_sizes[axis_index] or center[axis_index] > half_sizes[axis_index]:
            raise ValueError(
                f"{fixture_name}.{label} extends beyond the box {axis_name}"
            )


def _require_circle_inside_box_cross_section(
    center: list[float],
    axis: str,
    radius: float,
    box_size: list[float],
    fixture_name: str,
    label: str,
) -> None:
    half_sizes = [dimension * 0.5 for dimension in box_size]
    cross_section_axes = [index for index in range(3) if index != _AXIS_INDEX[axis]]
    axis_names = ("width", "depth", "height")
    for axis_index in cross_section_axes:
        if center[axis_index] - radius < -half_sizes[axis_index]:
            raise ValueError(
                f"{fixture_name}.{label} extends beyond the box {axis_names[axis_index]}"
            )
        if center[axis_index] + radius > half_sizes[axis_index]:
            raise ValueError(
                f"{fixture_name}.{label} extends beyond the box {axis_names[axis_index]}"
            )


def _require_centered_box_inside_box(
    center: list[float],
    size: list[float],
    box_size: list[float],
    fixture_name: str,
    label: str,
) -> None:
    half_sizes = [dimension * 0.5 for dimension in box_size]
    axis_names = ("width", "depth", "height")
    for axis_index, axis_name in enumerate(axis_names):
        half_cutout = size[axis_index] * 0.5
        if center[axis_index] - half_cutout < -half_sizes[axis_index]:
            raise ValueError(
                f"{fixture_name}.{label} extends beyond the box {axis_name}"
            )
        if center[axis_index] + half_cutout > half_sizes[axis_index]:
            raise ValueError(
                f"{fixture_name}.{label} extends beyond the box {axis_name}"
            )


def _as_positive_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a float") from exc
    if parsed <= 0.0:
        raise ValueError(f"{label} must be > 0")
    return parsed


def _as_non_negative_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a float") from exc
    if parsed < 0.0:
        raise ValueError(f"{label} must be >= 0")
    return parsed


def _as_non_negative_int(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be >= 0")
    return parsed


def _as_vector2(value: Any, label: str) -> list[float]:
    return _as_fixed_length_float_vector(value, label, 2)


def _as_vector3(value: Any, label: str) -> list[float]:
    return _as_fixed_length_float_vector(value, label, 3)


def _as_fixed_length_float_vector(value: Any, label: str, length: int) -> list[float]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        raise ValueError(f"{label} must be a list of {length} numbers")
    items = [float(item) for item in value]
    if len(items) != length:
        raise ValueError(f"{label} must contain exactly {length} numbers")
    return items


def _require_positive(values: Iterable[float], label: str) -> None:
    if any(value <= 0.0 for value in values):
        raise ValueError(f"{label} values must all be > 0")


def _format_vector(values: Iterable[float]) -> str:
    return "[" + ", ".join(f"{value:.6f}" for value in values) + "]"
