"""
Test configuration and fixtures for STL2SCAD tests.
"""

import os
import pytest
from pathlib import Path

@pytest.fixture
def test_data_dir():
    """Return path to test data directory."""
    return Path(__file__).parent / "data"

@pytest.fixture
def test_output_dir():
    """Return path to test output directory."""
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    return output_dir

@pytest.fixture
def sample_stl_file(test_data_dir):
    """Return path to sample STL file."""
    return test_data_dir / "Cube_3d_printing_sample.stl"

@pytest.fixture
def cleanup_output(test_output_dir):
    """Clean up test output files after test."""
    yield
    for file in test_output_dir.glob("*"):
        try:
            file.unlink()
        except Exception as e:
            print(f"Warning: Could not delete {file}: {e}")