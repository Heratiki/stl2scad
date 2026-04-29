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

    # --- Cylinder thresholds ---
    # Cap fill ratio: area of one flat cap / (span_a * span_b of that cap's bounding rect).
    # A perfect circle fills π/4 ≈ 0.785; we allow generous slop for mesh approximation.
    cylinder_cap_fill_ratio_min: float = 0.68
    cylinder_cap_fill_ratio_max: float = 0.93  # above this → likely a rectangle, not a circle
    # Cross-section squareness: min(perp_span) / max(perp_span). Ellipses score lower.
    cylinder_cross_section_squareness_min: float = 0.80
    # Minimum fraction of total surface area contributed by the two flat caps together.
    cylinder_cap_area_fraction_min: float = 0.08
    # Maximum inward-pointing fraction of lateral area before rejecting as non-solid.
    cylinder_max_inward_lateral_area_fraction: float = 0.05
    cylinder_confidence_min: float = 0.70

    # --- Pattern thresholds ---
    pattern_diameter_rounding_mm: float = 0.01
    pattern_regularity_error_max: float = 0.08
    grid_pattern_min_holes: int = 4

    # --- Revolve (rotate_extrude) thresholds (Phase 1) ---
    revolve_axis_quality_min: float = 0.85
    revolve_slice_count: int = 12
    revolve_cross_slice_tolerance_ratio: float = 0.04
    revolve_normal_field_agreement_min: float = 0.80
    revolve_profile_max_vertices: int = 64
    revolve_douglas_peucker_tolerance_ratio: float = 0.005
    revolve_confidence_min: float = 0.70

    # --- Revolve Phase 2 profile classification thresholds ---
    revolve_phase2_enabled: bool = True
    revolve_phase2_min_confidence: float = 0.85
    revolve_phase2_rect_tolerance_ratio: float = 0.08
    revolve_phase2_circle_fit_tolerance_ratio: float = 0.08

    # --- Linear extrude (Rule 2) thresholds ---
    linear_extrude_axis_quality_min: float = 0.25
    linear_extrude_cross_section_consistency_min: float = 0.60
    linear_extrude_max_profile_vertices: int = 64
    linear_extrude_confidence_min: float = 0.55

    # --- Preview emission gate ---
    # Minimum IR-tree confidence to emit SCAD. Aligns with plate_confidence_min
    # so every detected plate/box feature gets a SCAD preview attempt.
    preview_confidence_min: float = 0.55
