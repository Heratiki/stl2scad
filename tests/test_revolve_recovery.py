"""Unit tests for stl2scad.core.revolve_recovery."""

from __future__ import annotations

import numpy as np
import pytest

from stl2scad.tuning.config import DetectorConfig


def test_detector_config_has_revolve_defaults():
    config = DetectorConfig()
    assert 0.0 < config.revolve_axis_quality_min < 1.0
    assert config.revolve_slice_count >= 8
    assert config.revolve_slice_count % 2 == 0
    assert config.revolve_cross_slice_tolerance_ratio > 0.0
    assert config.revolve_normal_field_agreement_min > 0.0
    assert config.revolve_profile_max_vertices >= 16
    assert config.revolve_douglas_peucker_tolerance_ratio > 0.0
    assert config.revolve_confidence_min >= 0.70
