"""Continuous scoring of a DetectorConfig against the fixture manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import dist
from pathlib import Path
from typing import Any, Iterable

from stl2scad.core.feature_fixtures import (
    iter_expected_feature_counts,
    summarize_detected_feature_counts,
)
from stl2scad.core.feature_graph import build_feature_graph_for_stl
from stl2scad.tuning.config import DetectorConfig

# Same tolerances the fixture tests use; keep in sync.
_SIZE_TOL = 0.05
_CENTER_TOL = 0.15
_DIAMETER_TOL = 0.15

_COUNT_WEIGHT = 0.6
_DIM_WEIGHT = 0.4


@dataclass(frozen=True)
class FixtureScore:
    name: str
    count_score: float
    dimension_score: float
    total: float
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestScore:
    mean: float
    per_fixture: list[FixtureScore]

    def by_type(self, fixtures: list[dict[str, Any]]) -> dict[str, float]:
        by_name = {f["name"]: f["fixture_type"] for f in fixtures}
        totals: dict[str, list[float]] = {}
        for score in self.per_fixture:
            totals.setdefault(by_name.get(score.name, "unknown"), []).append(score.total)
        return {k: sum(v) / len(v) for k, v in totals.items() if v}


def score_fixture(
    config: DetectorConfig,
    fixture: dict[str, Any],
    stl_path: Path,
) -> FixtureScore:
    graph = build_feature_graph_for_stl(stl_path, config=config)
    return score_fixture_against_graph(fixture, graph)


def score_fixture_against_graph(
    fixture: dict[str, Any],
    graph: dict[str, Any],
) -> FixtureScore:
    expected = iter_expected_feature_counts(fixture)
    actual = summarize_detected_feature_counts(graph)
    count_components: list[float] = []
    for feature_type, expected_count in expected.items():
        actual_count = actual.get(feature_type, 0)
        if expected_count == 0 and actual_count == 0:
            count_components.append(1.0)
            continue
        denom = max(actual_count, expected_count, 1)
        count_components.append(min(actual_count, expected_count) / denom)
    count_score = sum(count_components) / len(count_components) if count_components else 1.0

    dim_score = _score_dimensions(fixture, graph)
    total = _COUNT_WEIGHT * count_score + _DIM_WEIGHT * dim_score
    return FixtureScore(
        name=str(fixture["name"]),
        count_score=float(count_score),
        dimension_score=float(dim_score),
        total=float(total),
        detail={"expected": expected, "actual": actual},
    )


def _score_dimensions(fixture: dict[str, Any], graph: dict[str, Any]) -> float:
    """Partial credit for dimension agreement on matched features.

    Greedy nearest-center match per feature type; score each match as
    max(0, 1 - err / tol) averaged over dims. Unmatched expected features
    contribute 0. Returns 1.0 if the fixture has no dimensioned features.
    """
    scorers: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []
    # Plate / box
    if fixture["fixture_type"] == "plate" and fixture["expected_detection"].get("plate_like_solid"):
        scorers.append(("plate_like_solid",
                        [{"size": fixture["plate_size"], "origin": [0, 0, 0]}],
                        [f for f in graph.get("features", []) if f.get("type") == "plate_like_solid"]))
    if fixture["fixture_type"] == "box" and fixture["expected_detection"].get("box_like_solid"):
        scorers.append(("box_like_solid",
                        [{"size": fixture["box_size"], "origin": [0, 0, 0]}],
                        [f for f in graph.get("features", []) if f.get("type") == "box_like_solid"]))
    # Holes
    expected_holes: list[dict[str, Any]] = []
    if fixture["fixture_type"] == "plate":
        for hole in fixture.get("holes", []):
            expected_holes.append({"center": [hole["center"][0], hole["center"][1], float(fixture["plate_size"][2]) * 0.5],
                                    "diameter": float(hole["diameter"])})
    elif fixture["fixture_type"] == "box":
        for hole in fixture.get("holes", []):
            expected_holes.append({"center": list(hole["center"]), "diameter": float(hole["diameter"])})
    if expected_holes:
        scorers.append(("hole_like_cutout", expected_holes,
                        [f for f in graph.get("features", []) if f.get("type") == "hole_like_cutout"]))

    if not scorers:
        return 1.0

    components: list[float] = []
    for feature_type, expected_list, actual_list in scorers:
        for expected in expected_list:
            if not actual_list:
                components.append(0.0)
                continue
            match = min(actual_list, key=lambda a: _match_distance(a, expected, feature_type))
            components.append(_agreement(match, expected, feature_type))
            actual_list.remove(match)
    return sum(components) / len(components) if components else 1.0


def _match_distance(actual: dict[str, Any], expected: dict[str, Any], feature_type: str) -> float:
    if "center" in expected and "center" in actual:
        return dist(list(actual["center"]), list(expected["center"]))
    if "origin" in expected and "origin" in actual:
        return dist(list(actual["origin"]), list(expected["origin"]))
    return 0.0


def _agreement(actual: dict[str, Any], expected: dict[str, Any], feature_type: str) -> float:
    scores: list[float] = []
    if "size" in expected and "size" in actual:
        for a, e in zip(actual["size"], expected["size"]):
            err = abs(float(a) - float(e))
            scores.append(max(0.0, 1.0 - err / _SIZE_TOL))
    if "diameter" in expected and "diameter" in actual:
        err = abs(float(actual["diameter"]) - float(expected["diameter"]))
        scores.append(max(0.0, 1.0 - err / _DIAMETER_TOL))
    if "center" in expected and "center" in actual:
        err = dist(list(actual["center"]), list(expected["center"]))
        scores.append(max(0.0, 1.0 - err / _CENTER_TOL))
    return sum(scores) / len(scores) if scores else 0.0


def score_manifest(
    config: DetectorConfig,
    fixtures: Iterable[dict[str, Any]],
    stl_dir: Path,
) -> ManifestScore:
    scores: list[FixtureScore] = []
    for fixture in fixtures:
        stl_path = Path(stl_dir) / f"{Path(fixture['output_filename']).stem}.stl"
        if not stl_path.exists():
            raise FileNotFoundError(f"Missing rendered STL for {fixture['name']}: {stl_path}")
        scores.append(score_fixture(config, fixture, stl_path))
    mean = sum(s.total for s in scores) / len(scores) if scores else 0.0
    return ManifestScore(mean=float(mean), per_fixture=scores)
