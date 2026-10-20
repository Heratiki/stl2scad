"""Test configuration and fixtures for STL2SCAD tests."""

import shutil
import os
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pytest
import stl


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


def create_cube_stl(output_file):
    """Create a simple cube STL file for testing."""
    # Define the 8 vertices of the cube
    vertices = np.array(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0, 0, 1],
            [1, 0, 1],
            [1, 1, 1],
            [0, 1, 1],
        ]
    )

    # Define the 12 triangles composing the cube
    faces = np.array(
        [
            [0, 3, 1],
            [1, 3, 2],  # bottom face
            [0, 4, 7],
            [0, 7, 3],  # left face
            [4, 5, 6],
            [4, 6, 7],  # top face
            [5, 1, 2],
            [5, 2, 6],  # right face
            [2, 3, 6],
            [3, 7, 6],  # front face
            [0, 1, 5],
            [0, 5, 4],  # back face
        ]
    )

    # Create the mesh
    cube = stl.mesh.Mesh(np.zeros(faces.shape[0], dtype=stl.mesh.Mesh.dtype))
    for i, f in enumerate(faces):
        for j in range(3):
            cube.vectors[i][j] = vertices[f[j], :]

    # Write the mesh to file
    cube.save(output_file)


@pytest.fixture(scope="session")
def cube_stl_path(tmp_path_factory):
    """Write a unit cube STL once per session (per xdist worker); return its path."""
    cube_file = tmp_path_factory.mktemp("cube_stl") / "cube.stl"
    create_cube_stl(cube_file)
    return cube_file


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
def sample_stl_file(test_data_dir, cube_stl_path):
    """Return path to sample STL file."""
    candidate = test_data_dir / "Cube_3d_printing_sample.stl"
    if candidate.exists():
        return candidate
    return cube_stl_path


@pytest.fixture
def cleanup_output(test_output_dir):
    """Clean up temporary test output files after test."""
    yield
