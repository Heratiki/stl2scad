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
