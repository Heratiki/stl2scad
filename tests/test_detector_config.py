"""Tests for DetectorConfig — the tunable parameter surface of the detector."""

import dataclasses
import pytest
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
    assert config.plate_thin_ratio_max == 0.25
    assert config.plate_tolerant_confidence_min == 0.70


def test_config_exposes_hole_thresholds():
    config = DetectorConfig()
    assert config.hole_radial_error_max == 0.08
    assert config.hole_angular_coverage_min == 0.70
    assert config.hole_height_span_ratio_min == 0.65
    assert config.hole_min_radius_ratio == 0.005
    assert config.hole_max_radius_ratio == 0.45


def test_config_exposes_cylinder_thresholds():
    config = DetectorConfig()
    assert config.cylinder_cap_fill_ratio_min == 0.68
    assert config.cylinder_cap_fill_ratio_max == 0.93
    assert config.cylinder_cross_section_squareness_min == 0.80
    assert config.cylinder_cap_area_fraction_min == 0.08
    assert config.cylinder_max_inward_lateral_area_fraction == 0.05
    assert config.cylinder_confidence_min == 0.70


def test_config_override_preserves_others():
    config = DetectorConfig(normal_axis_threshold=0.90)
    assert config.normal_axis_threshold == 0.90
    # All other defaults should still be the production defaults.
    assert config.boundary_tolerance_ratio == 0.01
    assert config.plate_confidence_min == 0.55
