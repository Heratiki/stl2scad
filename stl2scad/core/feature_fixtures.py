"""
Manifest-driven OpenSCAD feature fixtures for detector validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional, Union


def load_feature_fixture_manifest(
    manifest_path: Union[str, Path],
) -> list[dict[str, Any]]:
    """Load and validate feature fixtures from a JSON manifest."""
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("Feature fixture manifest must contain a non-empty fixtures list")

    normalized: list[dict[str, Any]] = []
    names_seen: set[str] = set()
    for raw_fixture in fixtures:
        fixture = validate_feature_fixture_spec(raw_fixture)
        name = str(fixture["name"])
        if name in names_seen:
            raise ValueError(f"Duplicate feature fixture name: {name}")
        names_seen.add(name)
        normalized.append(fixture)
    return normalized


def validate_feature_fixture_spec(raw_fixture: dict[str, Any]) -> dict[str, Any]:
    """Validate one feature fixture spec and return a normalized copy."""
    if not isinstance(raw_fixture, dict):
        raise ValueError("Feature fixture entries must be objects")

    fixture_type = str(raw_fixture.get("fixture_type", "")).strip()
    if fixture_type != "plate":
        raise ValueError(
            f"Unsupported feature fixture type '{fixture_type}'. Only 'plate' is supported"
        )

    name = str(raw_fixture.get("name", "")).strip()
    if not name:
        raise ValueError("Feature fixture name is required")

    output_filename = str(raw_fixture.get("output_filename", "")).strip()
    if not output_filename.endswith(".scad"):
        raise ValueError(f"Feature fixture '{name}' must define a .scad output_filename")

    plate_size = _as_vector3(raw_fixture.get("plate_size"), f"{name}.plate_size")
    _require_positive(plate_size, f"{name}.plate_size")

    spec: dict[str, Any] = {
        "name": name,
        "fixture_type": fixture_type,
        "description": str(raw_fixture.get("description", "")).strip(),
        "output_filename": output_filename,
        "plate_size": plate_size,
        "holes": [],
        "linear_hole_patterns": [],
        "grid_hole_patterns": [],
        "slots": [],
        "expected_detection": _validate_expected_detection(
            raw_fixture.get("expected_detection"), name
        ),
    }

    for index, raw_hole in enumerate(raw_fixture.get("holes", [])):
        hole = _validate_hole(raw_hole, name, index, plate_size)
        spec["holes"].append(hole)

    for index, raw_pattern in enumerate(raw_fixture.get("linear_hole_patterns", [])):
        pattern = _validate_linear_pattern(raw_pattern, name, index, plate_size)
        spec["linear_hole_patterns"].append(pattern)

    for index, raw_pattern in enumerate(raw_fixture.get("grid_hole_patterns", [])):
        pattern = _validate_grid_pattern(raw_pattern, name, index, plate_size)
        spec["grid_hole_patterns"].append(pattern)

    for index, raw_slot in enumerate(raw_fixture.get("slots", [])):
        slot = _validate_slot(raw_slot, name, index, plate_size)
        spec["slots"].append(slot)

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

    expected = spec["expected_detection"]
    if expected["hole_count"] > explicit_holes:
        raise ValueError(
            f"Feature fixture '{name}' expects {expected['hole_count']} holes but only defines {explicit_holes}"
        )
    if expected["slot_count"] > len(spec["slots"]):
        raise ValueError(
            f"Feature fixture '{name}' expects {expected['slot_count']} slots but only defines {len(spec['slots'])}"
        )

    return spec


def generate_feature_fixture_scad(fixture: dict[str, Any]) -> str:
    """Generate OpenSCAD source for one validated fixture."""
    validate_feature_fixture_spec(fixture)
    plate_size = fixture["plate_size"]
    half_x = plate_size[0] * 0.5
    half_y = plate_size[1] * 0.5
    thickness = plate_size[2]

    lines = [
        "// Auto-generated from tests/data/feature_fixtures_manifest.json",
        f"// fixture: {fixture['name']}",
        f"// description: {fixture.get('description', '')}",
        "$fn = 96;",
        "",
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
        "difference() {",
        "  translate(plate_origin) cube(plate_size);",
    ]

    cut_height = thickness + 0.2
    z_offset = -0.1

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

    for index, slot in enumerate(fixture["slots"]):
        start = [slot["start"][0], slot["start"][1], z_offset]
        end = [slot["end"][0], slot["end"][1], z_offset]
        lines.append(
            f"  through_slot({_format_vector(start)}, {_format_vector(end)}, {slot['width']:.6f}, {cut_height:.6f});  // slot_{index}"
        )

    lines.extend(["}", ""])
    return "\n".join(lines)


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
    return {
        "plate_like_solid": 1 if expected["plate_like_solid"] else 0,
        "hole_like_cutout": expected["hole_count"],
        "slot_like_cutout": expected["slot_count"],
        "linear_hole_pattern": expected["linear_pattern_count"],
        "grid_hole_pattern": expected["grid_pattern_count"],
    }


def _validate_expected_detection(
    raw_expected: Optional[dict[str, Any]], fixture_name: str
) -> dict[str, Any]:
    if not isinstance(raw_expected, dict):
        raise ValueError(
            f"Feature fixture '{fixture_name}' must define expected_detection"
        )
    expected = {
        "plate_like_solid": bool(raw_expected.get("plate_like_solid", True)),
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
    }
    return expected


def _validate_hole(
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
    _require_circle_inside_plate(center, diameter * 0.5, plate_size, fixture_name, f"holes[{index}]")
    return {"center": center, "diameter": diameter}


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
    _require_circle_inside_plate(start, width * 0.5, plate_size, fixture_name, f"slots[{index}].start")
    _require_circle_inside_plate(end, width * 0.5, plate_size, fixture_name, f"slots[{index}].end")
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


def _as_positive_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a float") from exc
    if parsed <= 0.0:
        raise ValueError(f"{label} must be > 0")
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
