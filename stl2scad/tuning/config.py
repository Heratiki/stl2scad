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
    plate_thin_ratio_max: float = 0.25
    plate_tolerant_confidence_min: float = 0.70
    box_paired_axes_required: int = 3
    box_confidence_min: float = 0.70
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
    tolerant_box_relaxed_fill_ratio: float = 0.55
    tolerant_box_full_fill_axes_min: int = 2
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
