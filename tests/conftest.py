"""Test configuration and fixtures for STL2SCAD tests."""

import shutil
import os
import tempfile
import uuid
from pathlib import Path

import pytest


_REPO_LOCAL_TEMP = Path(__file__).parent / ".tmp_output"
_REPO_LOCAL_TEMP.mkdir(exist_ok=True)
os.environ.setdefault("TMPDIR", str(_REPO_LOCAL_TEMP))
os.environ.setdefault("TEMP", str(_REPO_LOCAL_TEMP))
os.environ.setdefault("TMP", str(_REPO_LOCAL_TEMP))
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_REPO_LOCAL_TEMP))
os.environ.setdefault("STL2SCAD_TEMP_DIR", str(_REPO_LOCAL_TEMP))
tempfile.tempdir = str(_REPO_LOCAL_TEMP)


class _LocalTmpPathFactory:
    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        suffix = f"-{uuid.uuid4().hex[:8]}" if numbered else ""
        temp_dir = _REPO_LOCAL_TEMP / f"{basename}{suffix}"
        temp_dir.mkdir()
        return temp_dir


@pytest.fixture
def test_data_dir():
    """Return path to test data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture
def test_output_dir():
    """Return an isolated temporary output directory for each test."""
    temp_dir = _REPO_LOCAL_TEMP / f"test-{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def tmp_path():
    """Provide a repo-local tmp_path to avoid restricted system temp dirs."""
    temp_dir = _REPO_LOCAL_TEMP / f"pytest-{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def tmp_path_factory():
    """Provide a repo-local tmp_path_factory to avoid restricted temp dirs."""
    return _LocalTmpPathFactory()


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
