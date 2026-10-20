"""
Segmentation round-trip over the feature fixtures (T-009).

scad fixture -> OpenSCAD render -> convert_stl_to_scad() -> parse the emitted
SCAD -> assert against tests/data/segmentation/fixture_expectations.json.

Every fixture is either parametric (Hausdorff within the gate, Customizer
group counts equal to the expected hole, slot and counterbore counts) or a
named known gap that falls back with its exact expected reason. A known gap
that starts working fails loudly: move it to parametric in the expectations
file. Never loosen a count or reason; list the fixture as a known gap instead.

Fixtures whose conversion takes about 30 s or more carry the "slow" marker;
conftest.py deselects them unless the run passes -m (use -m slow).
"""

import json
import os
import re
from pathlib import Path

import pytest

from stl2scad.core.conversion import FALLBACK_MARKER, convert_stl_to_scad
from stl2scad.core.openscad.runner import get_openscad_path, run_openscad

_DATA_DIR = Path(__file__).parent / "data"
_FIXTURE_DIR = _DATA_DIR / "feature_fixtures_scad"
_MANIFEST_PATH = _DATA_DIR / "feature_fixtures_manifest.json"
_EXPECTATIONS_PATH = _DATA_DIR / "segmentation" / "fixture_expectations.json"

_EXPECTATIONS = json.loads(_EXPECTATIONS_PATH.read_text(encoding="utf-8"))["fixtures"]

_GATE_RE = re.compile(
    r"^// Gate limit: (\S+) mm; measured Hausdorff: (\S+) mm", re.MULTILINE
)
_GROUP_RE = re.compile(r"^/\* \[(.*?)\] \*/", re.MULTILINE)


def _params():
    for name, entry in _EXPECTATIONS.items():
        marks = [pytest.mark.slow] if entry.get("slow") else []
        yield pytest.param(name, entry, id=name, marks=marks)


def _count_groups(groups, prefix):
    return sum(1 for g in groups if re.fullmatch(prefix + r" \d+", g))


def _fallback_line(source):
    for line in source.splitlines():
        if line.startswith(FALLBACK_MARKER):
            return line[len(FALLBACK_MARKER):].strip()
    return None


def _render(name, output_dir):
    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"OpenSCAD is required in CI for fixture round-trip: {exc}")
        pytest.skip(f"OpenSCAD not available: {exc}")
    stl_path = output_dir / f"{name}.stl"
    ok = run_openscad(
        name,
        ["--render", "-o", str(stl_path), str(_FIXTURE_DIR / f"{name}.scad")],
        str(output_dir / f"{name}.log"),
        openscad_path,
        timeout=300,
    )
    assert ok and stl_path.exists(), f"OpenSCAD render failed for {name}"
    return stl_path


def test_expectations_match_fixture_files():
    rendered = {p.stem for p in _FIXTURE_DIR.glob("*.scad")}
    expected = set(_EXPECTATIONS)
    assert rendered - expected == set(), "fixtures without an expectations entry"
    assert expected - rendered == set(), "expectations entries naming no fixture"

    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))["fixtures"]
    in_manifest = {f["name"] for f in manifest}
    for name, entry in _EXPECTATIONS.items():
        assert entry["status"] in ("parametric", "known_gap"), name
        assert (name in in_manifest) == entry.get("manifest", True), (
            f"{name}: 'manifest' flag disagrees with feature_fixtures_manifest.json"
        )
        if entry["status"] == "known_gap":
            assert entry.get("fallback_reason"), f"{name}: known gap needs a reason"
        else:
            for key in ("hole_count", "slot_count", "counterbore_count"):
                assert isinstance(entry.get(key), int), f"{name}: missing {key}"


def test_expected_counts_match_manifest():
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))["fixtures"]
    for fixture in manifest:
        entry = _EXPECTATIONS[fixture["name"]]
        if entry["status"] != "parametric":
            continue
        detection = fixture["candidates"][0]["expected_detection"]
        for key in ("hole_count", "slot_count", "counterbore_count"):
            assert entry[key] == detection[key], f"{fixture['name']} {key}"


@pytest.mark.parametrize("name,entry", list(_params()))
def test_fixture_round_trip(name, entry, test_output_dir):
    stl_path = _render(name, test_output_dir)
    scad_path = test_output_dir / f"{name}.out.scad"
    convert_stl_to_scad(stl_path, scad_path)
    source = scad_path.read_text(encoding="utf-8")
    reason = _fallback_line(source)

    if entry["status"] == "known_gap":
        assert reason is not None, (
            f"{name} is listed as a known gap but now converts parametric; "
            "move it to status 'parametric' in fixture_expectations.json"
        )
        assert reason == entry["fallback_reason"], (
            f"{name} falls back for a different reason: {reason!r}"
        )
        pytest.xfail(f"known gap: {reason}")

    assert reason is None, f"{name} fell back to a polyhedron: {reason}"
    gate = _GATE_RE.search(source)
    assert gate, f"{name}: no measured Hausdorff line in the header"
    limit, measured = float(gate.group(1)), float(gate.group(2))
    assert measured <= limit, f"{name}: Hausdorff {measured} mm over the {limit} mm gate"

    groups = _GROUP_RE.findall(source)
    assert _count_groups(groups, "Hole") == entry["hole_count"], f"{name} hole_count"
    assert _count_groups(groups, "Slot") == entry["slot_count"], f"{name} slot_count"
    assert (
        _count_groups(groups, "Through Hole") == entry["counterbore_count"]
    ), f"{name} counterbore_count (Through Hole groups)"
    assert (
        _count_groups(groups, "Blind Hole") == entry["counterbore_count"]
    ), f"{name} counterbore_count (Blind Hole groups)"
