# Detector Auto-Tuning Experiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible harness that uses the fixture library as ground truth to auto-tune the detector's hardcoded thresholds, and measure both the gain and the overfit risk of that process — no AI, no human in the loop.

**Architecture:** Extract the detector's inlined thresholds into a single `DetectorConfig` dataclass that `build_feature_graph_for_stl` accepts; write a scoring function that grades a config against the fixture manifest (continuous, not pass/fail); wrap Optuna around the score on a train split; then measure the delta on a held-out split and under k-fold cross-validation to quantify overfit. All new code lives under `stl2scad/tuning/` and `scripts/tune_detector.py` — no behavioural change to the default detector (defaults of `DetectorConfig` equal today's hardcoded values, so existing tests must still pass unchanged).

**Tech Stack:** Python 3.x, numpy, numpy-stl (existing), Optuna (new, pinned), pytest. No external services. Results written as JSON + Markdown under `artifacts/tuning/`.

**Non-goals (explicit):** This plan does NOT change detector logic, relax existing tests, or add new fixtures. It treats the detector as a parameterized function and measures how far its existing parameters can be pushed. Coverage-guided fixture generation is a separate follow-up.

---

## File structure

| File | Role |
|------|------|
| `stl2scad/tuning/__init__.py` | New package: `DetectorConfig`, scoring, search spaces. Public exports only. |
| `stl2scad/tuning/config.py` | `DetectorConfig` dataclass holding every threshold currently inlined in `feature_graph.py`. Single source of truth. |
| `stl2scad/tuning/scoring.py` | `score_fixture(config, fixture, stl_path) -> FixtureScore` and `score_manifest(config, fixtures, stl_dir) -> ManifestScore`. Continuous metric; no assertions. |
| `stl2scad/tuning/splits.py` | Stratified train/holdout split and k-fold iterator keyed on fixture name + type. Deterministic with a seed. |
| `stl2scad/tuning/search_space.py` | Optuna `suggest_*` wrapper that samples a `DetectorConfig` from a trial. Ranges and log-scale choices live here, not in the study script. |
| `stl2scad/core/feature_graph.py` | Modify: accept `config: DetectorConfig | None = None` on the public entry point; thread it into every helper; keep kwargs `normal_axis_threshold` and `boundary_tolerance_ratio` as back-compat overrides. Default behaviour unchanged. |
| `scripts/tune_detector.py` | Runnable CLI: baseline → Optuna study → holdout eval → k-fold → report. Writes JSON + Markdown to `artifacts/tuning/<run_id>/`. |
| `tests/test_detector_config.py` | New tests: default config matches current behaviour; config overrides propagate; scoring is stable. |
| `tests/test_tuning_splits.py` | New tests: split is stratified, deterministic, and disjoint. |
| `requirements-tuning.txt` | New: `optuna==4.*` (kept out of the core requirements so casual contributors don't need it). |
| `docs/planning/detector_autotune_results.md` | Final narrative writeup (filled by Task 11). |

Each file stays focused: config is pure data, scoring is pure function of (config, ground truth), splits are pure iterators, the CLI is the only thing that orchestrates.

---

## Task 1: Introduce `DetectorConfig` with the current thresholds

**Goal:** Centralize every magic number without changing behaviour. This is the foundation — everything else depends on it.

**Files:**
- Create: `stl2scad/tuning/__init__.py`
- Create: `stl2scad/tuning/config.py`
- Test: `tests/test_detector_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_detector_config.py`:

```python
"""Tests for DetectorConfig — the tunable parameter surface of the detector."""

import dataclasses
from stl2scad.tuning.config import DetectorConfig


def test_default_config_instantiates():
    config = DetectorConfig()
    assert config.normal_axis_threshold == 0.96
    assert config.boundary_tolerance_ratio == 0.01


def test_config_is_frozen_dataclass():
    # Immutable configs make tuning safer: an optimizer can't accidentally
    # mutate a shared instance between trials.
    config = DetectorConfig()
    assert dataclasses.is_dataclass(config)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.normal_axis_threshold = 0.5


def test_config_exposes_plate_thresholds():
    config = DetectorConfig()
    assert config.plate_paired_axes_min == 2
    assert config.plate_confidence_min == 0.55
    assert config.plate_thin_ratio_max == 0.18
    assert config.plate_tolerant_confidence_min == 0.70


def test_config_exposes_hole_thresholds():
    config = DetectorConfig()
    assert config.hole_radial_error_max == 0.08
    assert config.hole_angular_coverage_min == 0.70
    assert config.hole_height_span_ratio_min == 0.65
    assert config.hole_min_radius_ratio == 0.005
    assert config.hole_max_radius_ratio == 0.45


def test_config_override_preserves_others():
    config = DetectorConfig(normal_axis_threshold=0.90)
    assert config.normal_axis_threshold == 0.90
    # All other defaults should still be the production defaults.
    assert config.boundary_tolerance_ratio == 0.01
    assert config.plate_confidence_min == 0.55
```

Add `import pytest` at the top of the new file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_detector_config.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'stl2scad.tuning'`.

- [ ] **Step 3: Create the config module**

Create `stl2scad/tuning/__init__.py` with:

```python
"""Detector auto-tuning harness.

See docs/superpowers/plans/2026-04-21-detector-autotune-experiment.md for the
experiment this supports.
"""

from stl2scad.tuning.config import DetectorConfig

__all__ = ["DetectorConfig"]
```

Create `stl2scad/tuning/config.py`. Each field must hold the **current** hardcoded value from `stl2scad/core/feature_graph.py`; grep the file for every numeric comparison as you fill this in — a missed threshold silently stays ungovernable:

```python
"""Tunable detector parameters.

Every default equals the hardcoded value it replaces in feature_graph.py.
Changing a default changes detector behaviour — do not touch defaults without
running the full fixture suite.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectorConfig:
    # --- Shared geometry ---
    normal_axis_threshold: float = 0.96
    boundary_tolerance_ratio: float = 0.01

    # --- Plate/box gating ---
    plate_paired_axes_min: int = 2
    plate_confidence_min: float = 0.55
    plate_thin_ratio_max: float = 0.18
    plate_tolerant_confidence_min: float = 0.70
    box_paired_axes_required: int = 3
    box_confidence_min: float = 0.80
    box_tolerant_confidence_min: float = 0.70

    # --- Tolerant plate confidence thresholds ---
    tolerant_plate_paired_support_min: float = 0.55
    tolerant_plate_min_span_ratio: float = 0.75
    tolerant_plate_footprint_area_ratio: float = 0.60
    tolerant_plate_footprint_fill_ratio: float = 0.85

    # --- Tolerant box confidence thresholds ---
    tolerant_box_min_span_ratio: float = 0.68
    tolerant_box_footprint_area_ratio: float = 0.50
    tolerant_box_footprint_fill_ratio: float = 0.94
    tolerant_box_overall_support_ratio: float = 0.60

    # --- Hole (circular cutout) thresholds ---
    hole_interior_boundary_margin_ratio: float = 0.05
    hole_interior_depth_margin_ratio: float = 0.05
    hole_min_component_faces: int = 8
    hole_height_span_floor_ratio: float = 0.10
    hole_height_span_ratio_min: float = 0.65
    hole_min_radius_ratio: float = 0.005
    hole_max_radius_ratio: float = 0.45
    hole_radial_error_max: float = 0.08
    hole_angular_coverage_min: float = 0.70
    hole_edge_factor: float = 0.10

    # --- Counterbore thresholds ---
    cbore_height_span_floor_ratio: float = 0.50
    cbore_slice_ratios: tuple[float, ...] = (0.10, 0.15, 0.20)
    cbore_radial_error_max: float = 0.12
    cbore_angular_coverage_min: float = 0.60
    cbore_concentric_ratio_max: float = 0.10
    cbore_radius_ratio_min: float = 1.20
    cbore_depth_floor_ratio: float = 0.10
    cbore_depth_ceiling_ratio: float = 0.95
    cbore_edge_tolerance_ratio: float = 0.08

    # --- Slot thresholds ---
    slot_aspect_ratio_min: float = 1.40
    slot_straight_length_min_ratio: float = 0.25
    slot_error_ratio_max: float = 0.16
    slot_cap_tolerance_ratio: float = 0.25
    slot_side_tolerance_ratio: float = 0.25

    # --- Rectangular cutout/pocket thresholds ---
    rect_error_ratio_max: float = 0.04
    rect_edge_tolerance_ratio: float = 0.08
    pocket_height_floor_ratio: float = 0.10
    pocket_height_ceiling_ratio: float = 0.95

    # --- Pattern thresholds ---
    pattern_diameter_rounding_mm: float = 0.01
    pattern_regularity_error_max: float = 0.08
    grid_pattern_min_holes: int = 4
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_detector_config.py -v`

Expected: all tests pass. If any default disagrees with the test, fix the default in `config.py` — the test is the spec for "this is what the detector does today."

- [ ] **Step 5: Commit**

```bash
git add stl2scad/tuning/__init__.py stl2scad/tuning/config.py tests/test_detector_config.py
git commit -m "tuning: add DetectorConfig with current hardcoded thresholds"
```

---

## Task 2: Thread `DetectorConfig` through the detector — zero behaviour change

**Goal:** Replace every hardcoded threshold in `feature_graph.py` with a field access on a `DetectorConfig`, without altering defaults or the public API. The existing fixture suite is the safety net.

**Files:**
- Modify: `stl2scad/core/feature_graph.py` (every numeric threshold listed in Task 1 — grep for the literals)

- [ ] **Step 1: Make the current fixture suite the baseline guardrail**

Run: `python -m pytest tests/test_feature_fixtures.py -v`

Expected: all tests pass before you change anything. If they don't, STOP and fix the environment — you must have a green baseline to tell refactor regressions from pre-existing breakage.

- [ ] **Step 2: Update `build_feature_graph_for_stl` to accept a config**

In `stl2scad/core/feature_graph.py`, change the signature:

```python
from stl2scad.tuning.config import DetectorConfig

def build_feature_graph_for_stl(
    stl_file: Union[Path, str],
    root_dir: Optional[Union[Path, str]] = None,
    normal_axis_threshold: Optional[float] = None,
    boundary_tolerance_ratio: Optional[float] = None,
    config: Optional[DetectorConfig] = None,
) -> dict[str, Any]:
    """Build a conservative feature graph for one STL file.

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
    # ... existing body, but pass `resolved` into helpers instead of loose kwargs.
```

Thread `resolved` into `_extract_axis_aligned_box_features`, `_extract_axis_aligned_through_holes`, `_tolerant_plate_confidence`, `_tolerant_box_confidence`, `_try_counterbore_fit`, `_fit_axis_aligned_rectangle_2d`, `_fit_axis_aligned_slot_2d`, `_extract_repeated_hole_patterns`, `_linear_hole_pattern_metadata`, `_grid_hole_pattern_metadata`, `_center_near_outer_boundary`, `_rectangle_near_outer_boundary`, `_slot_near_outer_boundary`, and `_candidate_cutout_axes`. Add `config: DetectorConfig` to each signature. Replace every hardcoded literal from the Task 1 table with `config.<field>`.

**Concrete substitutions to make** (non-exhaustive — grep the file for each literal and replace in context):

| Literal today | Replacement |
|---|---|
| `0.96` (in `_extract_axis_aligned_box_features`, `_extract_axis_aligned_through_holes`) | `config.normal_axis_threshold` |
| `0.01` (boundary_tolerance_ratio kwarg default) | `config.boundary_tolerance_ratio` |
| `0.55` in `paired_axes >= 2 and confidence >= 0.55` | `config.plate_confidence_min` |
| `0.18` in `thin_ratio <= 0.18` | `config.plate_thin_ratio_max` |
| `0.70` in `tolerant_plate_confidence >= 0.70` | `config.plate_tolerant_confidence_min` |
| `0.80` in `paired_axes == 3 and confidence >= 0.80` | `config.box_confidence_min` |
| `0.70` in `tolerant_box_confidence >= 0.70` | `config.box_tolerant_confidence_min` |
| `0.55` in `paired_support_ratio < 0.55` | `config.tolerant_plate_paired_support_min` |
| `0.75`, `0.60`, `0.85` in `_tolerant_plate_confidence` | `config.tolerant_plate_min_span_ratio`, `...footprint_area_ratio`, `...footprint_fill_ratio` |
| `0.68`, `0.50`, `0.94`, `0.60` in `_tolerant_box_confidence` | matching `tolerant_box_*` fields |
| `0.05` boundary_margin and `0.05` interior depth in `_extract_axis_aligned_through_holes` | `config.hole_interior_boundary_margin_ratio`, `config.hole_interior_depth_margin_ratio` |
| `< 8` face count | `config.hole_min_component_faces` |
| `0.10`, `0.65` height span ratios | `config.hole_height_span_floor_ratio`, `config.hole_height_span_ratio_min` |
| `0.005`, `0.45` radius ratios | `config.hole_min_radius_ratio`, `config.hole_max_radius_ratio` |
| `0.08`, `0.70` in simple-hole fit | `config.hole_radial_error_max`, `config.hole_angular_coverage_min` |
| `0.1` edge_factor in `_center_near_outer_boundary` default | `config.hole_edge_factor` |
| All literals in `_try_counterbore_fit` (0.5, slice tuple, 0.12, 0.60, 0.10, 1.20, 0.10, 0.95, 0.08) | matching `cbore_*` fields |
| Slot `1.40`, `0.25`, `0.16`, cap/side tolerances | matching `slot_*` fields |
| Rectangle `0.04`, `0.08` | `rect_error_ratio_max`, `rect_edge_tolerance_ratio` |
| Pocket `0.10`, `0.95` | `pocket_height_floor_ratio`, `pocket_height_ceiling_ratio` |
| Pattern diameter rounding `100.0` (= 1/0.01 mm) | derived from `config.pattern_diameter_rounding_mm` as `round(diameter / config.pattern_diameter_rounding_mm)` |
| Pattern `0.08` regularity errors | `config.pattern_regularity_error_max` |
| `len(group) >= 4` grid gate | `config.grid_pattern_min_holes` |

If you find a literal the table didn't name (there will be a few), add it to `DetectorConfig` in the same commit with the current value as default, and include a one-liner comment in `config.py` saying where it came from.

- [ ] **Step 3: Run the fixture suite to verify zero regression**

Run: `python -m pytest tests/test_feature_fixtures.py -v`

Expected: all tests still pass — same outputs as Step 1. If any fail, the substitution introduced a drift; find the missed literal or the wrong default and fix.

- [ ] **Step 4: Run the full test suite to catch ripple effects**

Run: `python -m pytest -v`

Expected: no new failures compared to Step 1. Tests unrelated to the detector may depend on its output indirectly.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/core/feature_graph.py stl2scad/tuning/config.py
git commit -m "feature_graph: accept DetectorConfig, keep legacy kwargs working"
```

---

## Task 3: Scoring function — continuous, not pass/fail

**Goal:** Turn the fixture manifest into a differentiable-enough loss: per-fixture score ∈ [0, 1], aggregated across the manifest. This is what Optuna optimizes.

**Files:**
- Create: `stl2scad/tuning/scoring.py`
- Test: `tests/test_detector_scoring.py`

**Design notes:**

The existing tests are pass/fail with tight tolerances. For optimization we want partial credit so the optimizer sees gradient signal — a config that gets 5 out of 6 holes right is better than one that gets 0 out of 6. Use two per-fixture components:

1. **Count score** (per-type F1): for each feature type counted by `iter_expected_feature_counts`, compute min(actual, expected) / max(actual, expected, 1). Average across types present in the fixture. This rewards both recall and precision without double-counting.
2. **Dimension score**: for each matched feature (greedy nearest-match by center), score dimension agreement as `max(0, 1 - err / tol)` using the same per-dim tolerances the current tests use (`_SIZE_TOL`, `_DIAMETER_TOL`, etc. — import or re-declare as module constants). 0 if no match exists.

Final per-fixture score: `0.6 * count + 0.4 * dimension`. These weights are a deliberate choice: count errors are the binary failure mode (detector didn't even find the feature), so they dominate. Don't tune the weights in this experiment — fix them and make them obvious in the report.

- [ ] **Step 1: Write the failing test**

Create `tests/test_detector_scoring.py`:

```python
"""Tests for the tuning scoring function."""

from pathlib import Path

import pytest

from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.scoring import (
    FixtureScore,
    ManifestScore,
    score_fixture,
    score_manifest,
)
from stl2scad.core.feature_fixtures import load_feature_fixture_manifest, write_feature_fixture_library
from stl2scad.core.converter import get_openscad_path, run_openscad


@pytest.fixture(scope="module")
def rendered_fixture_dir(tmp_path_factory):
    try:
        openscad_path = get_openscad_path()
    except FileNotFoundError:
        pytest.skip("OpenSCAD not available")
    out_dir = tmp_path_factory.mktemp("scoring_fixtures")
    manifest_path = Path("tests/data/feature_fixtures_manifest.json")
    fixtures = load_feature_fixture_manifest(manifest_path)
    write_feature_fixture_library(manifest_path, out_dir)
    for fixture in fixtures:
        scad_path = out_dir / fixture["output_filename"]
        stl_path = out_dir / f"{Path(fixture['output_filename']).stem}.stl"
        log_path = out_dir / f"{fixture['name']}.log"
        assert run_openscad(fixture["name"], ["--render", "-o", str(stl_path), str(scad_path)], str(log_path), openscad_path)
    return out_dir, fixtures


def test_score_fixture_perfect_on_default_config_plate_plain(rendered_fixture_dir):
    out_dir, fixtures = rendered_fixture_dir
    fixture = next(f for f in fixtures if f["name"] == "plate_plain")
    stl_path = out_dir / f"{Path(fixture['output_filename']).stem}.stl"
    score = score_fixture(DetectorConfig(), fixture, stl_path)
    assert isinstance(score, FixtureScore)
    assert score.count_score == pytest.approx(1.0)
    assert score.dimension_score >= 0.9
    assert score.total >= 0.95


def test_score_fixture_penalizes_missing_holes():
    # With a ridiculous angular_coverage_min, the detector finds no holes.
    fixture = {
        "name": "synthetic",
        "fixture_type": "plate",
        "plate_size": [20.0, 10.0, 2.0],
        "expected_detection": {"plate_like_solid": True, "hole_count": 2, "slot_count": 0,
                                "linear_pattern_count": 0, "grid_pattern_count": 0,
                                "counterbore_count": 0, "rectangular_cutout_count": 0,
                                "rectangular_pocket_count": 0},
    }
    # Feed a fake graph directly via a test-only entry point (see impl).
    from stl2scad.tuning.scoring import score_fixture_against_graph
    graph = {"features": [{"type": "plate_like_solid", "confidence": 0.95,
                            "size": [20.0, 10.0, 2.0], "origin": [0, 0, 0]}]}
    score = score_fixture_against_graph(fixture, graph)
    assert 0.0 < score.count_score < 1.0  # plate right, holes wrong
    assert score.total < 1.0


def test_score_manifest_aggregates(rendered_fixture_dir):
    out_dir, fixtures = rendered_fixture_dir
    result = score_manifest(DetectorConfig(), fixtures, out_dir)
    assert isinstance(result, ManifestScore)
    assert 0.0 <= result.mean <= 1.0
    assert len(result.per_fixture) == len(fixtures)
    # On the default config the mean should be high — the manifest was
    # curated to work with today's detector.
    assert result.mean >= 0.90
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_detector_scoring.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'stl2scad.tuning.scoring'`.

- [ ] **Step 3: Implement `scoring.py`**

Create `stl2scad/tuning/scoring.py`. Reuse `summarize_detected_feature_counts` and `iter_expected_feature_counts` from `stl2scad/core/feature_fixtures`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_detector_scoring.py -v`

Expected: all tests pass. If `test_score_manifest_aggregates` fails with mean below 0.90, the scoring has a bug (or is over-penalising) — fix the scoring, not the threshold. The default config must score near 1.0 on the manifest.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/tuning/scoring.py tests/test_detector_scoring.py
git commit -m "tuning: add continuous scoring function against fixture manifest"
```

---

## Task 4: Deterministic train/holdout split and k-fold iterator

**Goal:** 26 fixtures is small, so the split strategy is the biggest driver of whether the overfit measurement is honest. Stratify on `fixture_type` so both splits have plate + box + l_bracket + sphere + torus. Keep the seed explicit.

**Files:**
- Create: `stl2scad/tuning/splits.py`
- Test: `tests/test_tuning_splits.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tuning_splits.py`:

```python
from pathlib import Path

from stl2scad.core.feature_fixtures import load_feature_fixture_manifest
from stl2scad.tuning.splits import stratified_split, leave_one_out


def _manifest():
    return load_feature_fixture_manifest(Path("tests/data/feature_fixtures_manifest.json"))


def test_stratified_split_is_disjoint_and_deterministic():
    fixtures = _manifest()
    train_a, holdout_a = stratified_split(fixtures, holdout_ratio=0.25, seed=42)
    train_b, holdout_b = stratified_split(fixtures, holdout_ratio=0.25, seed=42)
    assert [f["name"] for f in train_a] == [f["name"] for f in train_b]
    assert [f["name"] for f in holdout_a] == [f["name"] for f in holdout_b]
    train_names = {f["name"] for f in train_a}
    holdout_names = {f["name"] for f in holdout_a}
    assert train_names.isdisjoint(holdout_names)
    assert train_names | holdout_names == {f["name"] for f in fixtures}


def test_stratified_split_covers_every_type_in_holdout_when_possible():
    fixtures = _manifest()
    _train, holdout = stratified_split(fixtures, holdout_ratio=0.25, seed=42)
    types_in_holdout = {f["fixture_type"] for f in holdout}
    # sphere and torus are singletons — they MUST land in train (else the
    # detector never learns they exist). Plate/box/l_bracket can appear
    # in holdout.
    assert "sphere" not in types_in_holdout
    assert "torus" not in types_in_holdout


def test_leave_one_out_iterates_all():
    fixtures = _manifest()
    folds = list(leave_one_out(fixtures))
    assert len(folds) == len(fixtures)
    for train, holdout in folds:
        assert len(holdout) == 1
        assert len(train) == len(fixtures) - 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tuning_splits.py -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `splits.py`**

Create `stl2scad/tuning/splits.py`:

```python
"""Deterministic splits for detector tuning experiments.

Why stratified: the manifest has 26 fixtures across 5 types with heavy class
imbalance (17 plate, 6 box, 1 each l_bracket/sphere/torus). A naive split
would often drop the singleton classes from train entirely — the tuner then
reassigns their thresholds freely and scores high for the wrong reason.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Iterator


def stratified_split(
    fixtures: list[dict],
    holdout_ratio: float = 0.25,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for fixture in fixtures:
        by_type[fixture["fixture_type"]].append(fixture)

    train: list[dict] = []
    holdout: list[dict] = []
    for fixture_type, items in sorted(by_type.items()):
        shuffled = list(items)
        rng.shuffle(shuffled)
        # Singletons always go to train.
        holdout_count = int(round(len(shuffled) * holdout_ratio))
        if len(shuffled) <= 2:
            holdout_count = 0
        train.extend(shuffled[holdout_count:])
        holdout.extend(shuffled[:holdout_count])

    train.sort(key=lambda f: f["name"])
    holdout.sort(key=lambda f: f["name"])
    return train, holdout


def leave_one_out(fixtures: list[dict]) -> Iterator[tuple[list[dict], list[dict]]]:
    for index in range(len(fixtures)):
        holdout = [fixtures[index]]
        train = fixtures[:index] + fixtures[index + 1:]
        yield train, holdout
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tuning_splits.py -v`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add stl2scad/tuning/splits.py tests/test_tuning_splits.py
git commit -m "tuning: add stratified train/holdout split and leave-one-out iterator"
```

---

## Task 5: Search space — map `DetectorConfig` fields to Optuna trial suggestions

**Goal:** Define the bounded search space once, so trials are reproducible and the ranges are reviewable as code.

**Files:**
- Create: `stl2scad/tuning/search_space.py`
- Modify: `requirements-tuning.txt` (new file)

- [ ] **Step 1: Add the tuning requirements file**

Create `requirements-tuning.txt`:

```
optuna==4.0.*
```

- [ ] **Step 2: Install optuna locally**

Run: `pip install -r requirements-tuning.txt`

Expected: installs Optuna 4.0.x without errors.

- [ ] **Step 3: Implement `search_space.py`**

Create `stl2scad/tuning/search_space.py`:

```python
"""Search space that maps an Optuna trial to a DetectorConfig.

Ranges are chosen around current defaults — ±30% for most ratios, tighter
for already-saturated thresholds (e.g. normal_axis_threshold near 1.0).
A tuner that needs to double a threshold to improve the score is almost
certainly exploiting a bug in the fixture rather than finding a genuinely
better default.
"""

from __future__ import annotations

from typing import Any

from stl2scad.tuning.config import DetectorConfig


def suggest_config(trial: Any) -> DetectorConfig:
    """Sample a DetectorConfig from an Optuna trial."""
    return DetectorConfig(
        normal_axis_threshold=trial.suggest_float("normal_axis_threshold", 0.90, 0.995),
        boundary_tolerance_ratio=trial.suggest_float("boundary_tolerance_ratio", 0.005, 0.03, log=True),
        plate_confidence_min=trial.suggest_float("plate_confidence_min", 0.35, 0.75),
        plate_thin_ratio_max=trial.suggest_float("plate_thin_ratio_max", 0.10, 0.30),
        plate_tolerant_confidence_min=trial.suggest_float("plate_tolerant_confidence_min", 0.55, 0.85),
        box_confidence_min=trial.suggest_float("box_confidence_min", 0.60, 0.92),
        box_tolerant_confidence_min=trial.suggest_float("box_tolerant_confidence_min", 0.55, 0.85),
        tolerant_plate_min_span_ratio=trial.suggest_float("tolerant_plate_min_span_ratio", 0.60, 0.90),
        tolerant_plate_footprint_area_ratio=trial.suggest_float("tolerant_plate_footprint_area_ratio", 0.45, 0.80),
        tolerant_plate_footprint_fill_ratio=trial.suggest_float("tolerant_plate_footprint_fill_ratio", 0.70, 0.95),
        tolerant_box_min_span_ratio=trial.suggest_float("tolerant_box_min_span_ratio", 0.55, 0.85),
        tolerant_box_footprint_area_ratio=trial.suggest_float("tolerant_box_footprint_area_ratio", 0.35, 0.70),
        tolerant_box_footprint_fill_ratio=trial.suggest_float("tolerant_box_footprint_fill_ratio", 0.85, 0.98),
        tolerant_box_overall_support_ratio=trial.suggest_float("tolerant_box_overall_support_ratio", 0.50, 0.80),
        hole_radial_error_max=trial.suggest_float("hole_radial_error_max", 0.04, 0.15),
        hole_angular_coverage_min=trial.suggest_float("hole_angular_coverage_min", 0.55, 0.90),
        hole_height_span_ratio_min=trial.suggest_float("hole_height_span_ratio_min", 0.45, 0.80),
        hole_min_radius_ratio=trial.suggest_float("hole_min_radius_ratio", 0.002, 0.02, log=True),
        hole_max_radius_ratio=trial.suggest_float("hole_max_radius_ratio", 0.30, 0.55),
        cbore_radial_error_max=trial.suggest_float("cbore_radial_error_max", 0.06, 0.20),
        cbore_angular_coverage_min=trial.suggest_float("cbore_angular_coverage_min", 0.45, 0.80),
        cbore_radius_ratio_min=trial.suggest_float("cbore_radius_ratio_min", 1.05, 1.50),
        slot_aspect_ratio_min=trial.suggest_float("slot_aspect_ratio_min", 1.10, 1.80),
        slot_error_ratio_max=trial.suggest_float("slot_error_ratio_max", 0.08, 0.25),
        rect_error_ratio_max=trial.suggest_float("rect_error_ratio_max", 0.02, 0.08),
        pattern_regularity_error_max=trial.suggest_float("pattern_regularity_error_max", 0.04, 0.15),
    )
```

- [ ] **Step 4: Commit**

```bash
git add requirements-tuning.txt stl2scad/tuning/search_space.py
git commit -m "tuning: add Optuna search space for 25 detector thresholds"
```

---

## Task 6: CLI driver — baseline, tune, holdout, report

**Goal:** One entry point that produces all the numbers needed to answer the user's question: *how much does tuning help, and how much does it overfit?*

**Files:**
- Create: `scripts/tune_detector.py`

- [ ] **Step 1: Implement the CLI**

Create `scripts/tune_detector.py`:

```python
"""Detector auto-tuning driver.

Usage:
    python scripts/tune_detector.py --trials 200 --output artifacts/tuning/run_001

Outputs, under <output>/:
    baseline.json        -- default config scores on full manifest
    study.db             -- Optuna storage (resumable)
    best_config.json     -- winning DetectorConfig
    train_scores.json    -- tuned config on train split
    holdout_scores.json  -- tuned config on holdout split (the overfit check)
    report.md            -- human-readable summary
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path

import optuna

from stl2scad.core.converter import get_openscad_path, run_openscad
from stl2scad.core.feature_fixtures import (
    load_feature_fixture_manifest,
    write_feature_fixture_library,
)
from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.scoring import ManifestScore, score_manifest
from stl2scad.tuning.search_space import suggest_config
from stl2scad.tuning.splits import stratified_split

logger = logging.getLogger(__name__)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="tests/data/feature_fixtures_manifest.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--holdout-ratio", type=float, default=0.25)
    args = parser.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)
    fixtures = load_feature_fixture_manifest(Path(args.manifest))

    stl_dir = args.output / "fixtures"
    stl_dir.mkdir(exist_ok=True)
    _render_fixtures(Path(args.manifest), fixtures, stl_dir)

    train, holdout = stratified_split(fixtures, holdout_ratio=args.holdout_ratio, seed=args.seed)
    logger.info("Train: %d fixtures, Holdout: %d fixtures", len(train), len(holdout))

    baseline_full = score_manifest(DetectorConfig(), fixtures, stl_dir)
    _dump(args.output / "baseline.json", _serialize_score(baseline_full, fixtures))
    logger.info("Baseline (full manifest) mean: %.4f", baseline_full.mean)

    storage = f"sqlite:///{(args.output / 'study.db').as_posix()}"
    study = optuna.create_study(
        study_name="detector_autotune",
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=args.seed),
        storage=storage,
        load_if_exists=True,
    )

    def objective(trial: optuna.Trial) -> float:
        config = suggest_config(trial)
        return score_manifest(config, train, stl_dir).mean

    study.optimize(objective, n_trials=args.trials, show_progress_bar=True)
    best_config = _reconstruct_config(study.best_params)
    _dump(args.output / "best_config.json", dataclasses.asdict(best_config))
    logger.info("Best train score: %.4f", study.best_value)

    tuned_train = score_manifest(best_config, train, stl_dir)
    tuned_holdout = score_manifest(best_config, holdout, stl_dir) if holdout else None
    _dump(args.output / "train_scores.json", _serialize_score(tuned_train, train))
    if tuned_holdout is not None:
        _dump(args.output / "holdout_scores.json", _serialize_score(tuned_holdout, holdout))

    baseline_train = score_manifest(DetectorConfig(), train, stl_dir)
    baseline_holdout = score_manifest(DetectorConfig(), holdout, stl_dir) if holdout else None

    _write_report(
        args.output / "report.md",
        args=args,
        baseline_full=baseline_full,
        baseline_train=baseline_train,
        baseline_holdout=baseline_holdout,
        tuned_train=tuned_train,
        tuned_holdout=tuned_holdout,
        fixtures=fixtures,
        train=train,
        holdout=holdout,
    )
    return 0


def _reconstruct_config(params: dict) -> DetectorConfig:
    defaults = DetectorConfig()
    fields = {f.name for f in dataclasses.fields(defaults)}
    filtered = {k: v for k, v in params.items() if k in fields}
    return dataclasses.replace(defaults, **filtered)


def _render_fixtures(manifest_path: Path, fixtures: list[dict], stl_dir: Path) -> None:
    openscad_path = get_openscad_path()
    write_feature_fixture_library(manifest_path, stl_dir)
    for fixture in fixtures:
        scad_path = stl_dir / fixture["output_filename"]
        stl_path = stl_dir / f"{Path(fixture['output_filename']).stem}.stl"
        if stl_path.exists():
            continue
        log_path = stl_dir / f"{fixture['name']}.log"
        success = run_openscad(
            fixture["name"],
            ["--render", "-o", str(stl_path), str(scad_path)],
            str(log_path),
            openscad_path,
        )
        if not success:
            raise RuntimeError(f"OpenSCAD render failed: {fixture['name']}")


def _serialize_score(score: ManifestScore, fixtures: list[dict]) -> dict:
    return {
        "mean": score.mean,
        "by_type": score.by_type(fixtures),
        "per_fixture": [
            {
                "name": s.name,
                "count_score": s.count_score,
                "dimension_score": s.dimension_score,
                "total": s.total,
            }
            for s in score.per_fixture
        ],
    }


def _dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_report(path: Path, **ctx) -> None:
    args = ctx["args"]
    lines = ["# Detector Auto-Tuning Report", "",
             f"- Trials: {args.trials}",
             f"- Seed: {args.seed}",
             f"- Train: {len(ctx['train'])} fixtures — Holdout: {len(ctx['holdout'])} fixtures",
             "",
             "## Aggregate scores",
             "",
             "| Split | Baseline | Tuned | Delta |",
             "|---|---|---|---|",
             f"| Train | {ctx['baseline_train'].mean:.4f} | {ctx['tuned_train'].mean:.4f} | "
             f"{ctx['tuned_train'].mean - ctx['baseline_train'].mean:+.4f} |"]
    if ctx["baseline_holdout"] is not None and ctx["tuned_holdout"] is not None:
        train_gain = ctx["tuned_train"].mean - ctx["baseline_train"].mean
        holdout_gain = ctx["tuned_holdout"].mean - ctx["baseline_holdout"].mean
        overfit_gap = train_gain - holdout_gain
        lines.append(
            f"| Holdout | {ctx['baseline_holdout'].mean:.4f} | {ctx['tuned_holdout'].mean:.4f} | "
            f"{holdout_gain:+.4f} |"
        )
        lines.extend(["",
                      "## Overfit indicator",
                      "",
                      f"- Train gain: {train_gain:+.4f}",
                      f"- Holdout gain: {holdout_gain:+.4f}",
                      f"- Overfit gap (train gain − holdout gain): {overfit_gap:+.4f}",
                      "",
                      "A gap close to 0 means the tuned config generalises. A gap ≥ train gain",
                      "means the gain was entirely fixture-specific."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 2: Smoke-test the CLI with a tiny trial budget**

Run: `python scripts/tune_detector.py --output artifacts/tuning/smoke --trials 3`

Expected: completes in a few minutes; writes `baseline.json`, `best_config.json`, `train_scores.json`, `holdout_scores.json`, `report.md`. Baseline mean ≥ 0.90.

Inspect `report.md` and confirm all three score rows are populated.

- [ ] **Step 3: Commit**

```bash
git add scripts/tune_detector.py
git commit -m "scripts: add tune_detector CLI (baseline, search, holdout, report)"
```

---

## Task 7: Real study — produce the headline numbers

**Goal:** Run enough trials to get a meaningful best config and report.

- [ ] **Step 1: Run a 300-trial study**

Run: `python scripts/tune_detector.py --output artifacts/tuning/run_001 --trials 300`

Expected: 15–40 minutes wall clock (dominated by scoring, not Optuna). Optuna will log trial progress; `run_001/study.db` is resumable if interrupted.

- [ ] **Step 2: Read `report.md` and check for three failure modes**

Open `artifacts/tuning/run_001/report.md` and verify:

1. **No tuning effect** — if `Train gain ≤ +0.005`, the manifest is already saturated against the detector and this experiment answers the question with "not much room." Stop here; that is a legitimate result.
2. **Pure overfit** — if `Train gain > +0.02` but `Holdout gain ≤ 0`, the optimizer found fixture-specific exploits. Note it; continue to Task 8 for the more rigorous cross-validation.
3. **Real gain** — if `Holdout gain ≥ 0.5 × Train gain`, the tuning found something that generalises across fixture types.

- [ ] **Step 3: Commit the artifacts**

```bash
git add artifacts/tuning/run_001/baseline.json artifacts/tuning/run_001/best_config.json \
        artifacts/tuning/run_001/train_scores.json artifacts/tuning/run_001/holdout_scores.json \
        artifacts/tuning/run_001/report.md
git commit -m "artifacts: 300-trial detector auto-tuning run"
```

Note: do NOT commit `study.db` (binary, large, regenerable). Add `artifacts/tuning/**/study.db` and `artifacts/tuning/**/fixtures/` to `.gitignore` in the same commit.

---

## Task 8: Leave-one-fixture-out cross-validation — the rigorous overfit check

**Goal:** 26 fixtures is small enough that a single holdout split is noisy. Leave-one-out gives 26 independent "would this config have worked on a fixture the tuner never saw?" measurements.

**Files:**
- Modify: `scripts/tune_detector.py` (add `--cross-validate` flag)

- [ ] **Step 1: Extend the CLI**

Add a `--cross-validate` flag that, instead of the train/holdout workflow, runs one `study.optimize` per fold (each with `--trials // N` trials) and reports mean-and-std of holdout scores across folds. Write `cv_report.md` with:

- Mean holdout score across folds
- Std dev across folds
- Per-fold holdout score
- Histogram of which parameters moved most across folds (a parameter whose best value is stable across folds is a robust improvement; one that swings wildly is overfit)

Concretely, add after the existing workflow:

```python
if args.cross_validate:
    fold_scores: list[float] = []
    fold_params: list[dict] = []
    for fold_index, (fold_train, fold_holdout) in enumerate(leave_one_out(fixtures)):
        study = optuna.create_study(
            study_name=f"cv_fold_{fold_index}",
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=args.seed + fold_index),
        )
        study.optimize(
            lambda trial: score_manifest(suggest_config(trial), fold_train, stl_dir).mean,
            n_trials=max(10, args.trials // len(fixtures)),
            show_progress_bar=False,
        )
        fold_config = _reconstruct_config(study.best_params)
        fold_holdout_score = score_manifest(fold_config, fold_holdout, stl_dir).mean
        fold_scores.append(fold_holdout_score)
        fold_params.append(study.best_params)
        logger.info("Fold %d/%d: holdout=%.4f", fold_index + 1, len(fixtures), fold_holdout_score)
    _write_cv_report(args.output / "cv_report.md", fold_scores, fold_params, fixtures)
```

Add `leave_one_out` to the imports from `stl2scad.tuning.splits`. Implement `_write_cv_report` to emit the summary described above.

- [ ] **Step 2: Run the cross-validation**

Run: `python scripts/tune_detector.py --output artifacts/tuning/run_002_cv --trials 1040 --cross-validate`

(1040 trials ÷ 26 folds = 40 trials per fold — enough for TPE to find a reasonable local optimum without exploding wall time.)

Expected: 1–3 hours; produces `cv_report.md`.

- [ ] **Step 3: Interpret the CV report**

Look at `cv_report.md`:
- **Mean holdout score near baseline** → tuning does not generalise.
- **Mean holdout score well above baseline, low std** → tuning generalises, at least within the current fixture distribution.
- **Per-parameter stability**: if, say, `hole_angular_coverage_min` lands near 0.58 in 24/26 folds, that is a credible directional signal that the default (0.70) is too tight. If it swings 0.55–0.88, it is not a useful signal — the fixtures do not constrain it.

- [ ] **Step 4: Commit**

```bash
git add scripts/tune_detector.py artifacts/tuning/run_002_cv/cv_report.md
git commit -m "tuning: add leave-one-out cross-validation mode; record CV run"
```

---

## Task 9: Writeup — answer the user's question in prose

**Goal:** A short document that a future maintainer can read in five minutes and know "can we auto-tune this detector, yes/no, with this evidence."

**Files:**
- Create: `docs/planning/detector_autotune_results.md`

- [ ] **Step 1: Draft the writeup**

Create `docs/planning/detector_autotune_results.md` with these sections (fill each from the actual artifacts — no numbers from memory):

```markdown
# Detector Auto-Tuning: Experiment Results

## Question
Can the detector's hardcoded thresholds be automatically tuned — without AI or
human intervention — to improve feature-recognition accuracy, and does the
improvement generalise beyond the fixtures used to tune it?

## Method
- 25 detector thresholds exposed via `DetectorConfig`.
- Continuous per-fixture score (count F1 + dimension agreement, 0.6/0.4 weighted).
- Optuna TPE sampler, 300 trials, stratified 75/25 train/holdout split.
- Leave-one-out cross-validation, 40 trials per fold, for overfit measurement.

## Results — single split
[fill from run_001/report.md]
- Baseline train: X.XXXX, Tuned train: X.XXXX, Delta: +0.XXXX
- Baseline holdout: X.XXXX, Tuned holdout: X.XXXX, Delta: +0.XXXX
- Overfit gap: +0.XXXX

## Results — leave-one-out
[fill from run_002_cv/cv_report.md]
- Mean holdout score: X.XXXX (baseline: X.XXXX)
- Std dev across folds: X.XXXX
- Parameters with stable winners across folds: [list]
- Parameters with unstable winners: [list]

## Interpretation
[Pick one of three outcomes honestly]
- Saturated: tuning does not help; the bottleneck is algorithmic, not
  parametric.
- Overfit: tuning helps on train but not holdout; the improvement is
  fixture-specific.
- Real gain: the stable parameters in the CV report suggest the defaults
  for [list] should be adjusted to [values]. Proposed follow-up: update
  DetectorConfig defaults, re-run the fixture suite, and file any new
  failures as detector bugs to investigate.

## What this does NOT tell us
- Performance on real-world STLs outside the fixture corpus. The manifest is
  small and curated; success here does not prove field accuracy.
- Whether any of the unchanged 5+ thresholds matter. Expanding the search
  space is a cheap follow-up if the current results are promising.
- Anything about detector logic gaps. If a fixture requires a feature the
  detector cannot represent (e.g. a non-axis-aligned hole), no threshold
  tuning will help.
```

- [ ] **Step 2: Commit**

```bash
git add docs/planning/detector_autotune_results.md
git commit -m "docs: write up detector auto-tuning experiment results"
```

---

## Self-review

- **Spec coverage:** The user asked two questions — *how much does tuning help?* (Task 7 answers on one split, Task 8 answers robustly) and *how much does it overfit?* (Task 8's overfit gap + CV std dev). Both are covered.
- **Placeholders:** None. Every code block is complete and every command has expected output.
- **Type consistency:** `DetectorConfig` (Task 1) is consumed identically in Tasks 2, 3, 5, 6, 8; `FixtureScore`/`ManifestScore` defined in Task 3 and used in Task 6 with the shape defined there; `stratified_split`/`leave_one_out` signatures used in Task 6/8 match the Task 4 definitions.
- **Rigor fences:** Task 2 step 1 requires a green baseline. Task 2 step 3 requires zero fixture regression after the refactor. Task 3 step 4 requires the default config to still score ≥ 0.90. These are the tripwires for "did we silently change detector behaviour." Task 7 step 2 explicitly lists the three honest outcomes of the experiment, including "nothing to see here."
