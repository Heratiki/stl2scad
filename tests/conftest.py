"""Test configuration and fixtures for STL2SCAD tests."""

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def test_data_dir():
    """Return path to test data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture
def test_output_dir():
    """Return an isolated temporary output directory for each test."""
    base_tmp = Path(__file__).parent / ".tmp_output"
    base_tmp.mkdir(exist_ok=True)
    temp_dir = base_tmp / f"test-{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def tmp_path():
    """Provide a repo-local tmp_path to avoid restricted system temp dirs."""
    base_tmp = Path(__file__).parent / ".tmp_output"
    base_tmp.mkdir(exist_ok=True)
    temp_dir = base_tmp / f"pytest-{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_stl_file(test_data_dir):
    """Return path to sample STL file."""
    candidate = test_data_dir / "Cube_3d_printing_sample.stl"
    if candidate.exists():
        return candidate
    return test_data_dir / "cube.stl"


@pytest.fixture
def cleanup_output(test_output_dir):
    """Clean up temporary test output files after test."""
    yield
