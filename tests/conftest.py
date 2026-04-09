"""
Test configuration and fixtures for STL2SCAD tests.
"""

import pytest
import shutil
import tempfile
from pathlib import Path


@pytest.fixture
def test_data_dir():
    """Return path to test data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture
def test_output_dir():
    """Return an isolated temporary output directory for each test."""
    base_tmp = Path(__file__).parent / ".tmp_output"
    base_tmp.mkdir(exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="test-", dir=base_tmp))
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_stl_file(test_data_dir):
    """Return path to sample STL file."""
    return test_data_dir / "Cube_3d_printing_sample.stl"


@pytest.fixture
def cleanup_output(test_output_dir):
    """Clean up temporary test output files after test."""
    yield
