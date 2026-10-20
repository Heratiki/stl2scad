"""
Live tests for stl2scad.core.conversion.convert_stl_to_scad (T-004 fix round).

These use the real segmentation emitter, not a stub: input validation
(STLValidationError), a valid cube converting, and UTF-8 output for a
non-ASCII input path.
"""

import numpy as np
import pytest
from stl import mesh as stl_mesh

from stl2scad import cli
from stl2scad.core.conversion import (
    ConversionStats,
    STLValidationError,
    convert_stl_to_scad,
)


def _save_triangles(path, triangles):
    data = np.zeros(len(triangles), dtype=stl_mesh.Mesh.dtype)
    data["vectors"] = np.asarray(triangles, dtype=np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    stl_mesh.Mesh(data).save(str(path))  # binary STL by default
    return path


def _non_manifold_stl(path):
    # Three triangles share the edge (0,0,0)-(1,0,0).
    a, b = (0, 0, 0), (1, 0, 0)
    return _save_triangles(
        path, [[a, b, (0, 1, 0)], [a, b, (0, 0, 1)], [a, b, (0, -1, 0)]]
    )


def _collapsed_stl(path):
    # One triangle whose three vertices are all (0,0,0).
    return _save_triangles(path, [[(0, 0, 0), (0, 0, 0), (0, 0, 0)]])


def _cube_stl(path):
    from tests.test_segmentation_geometry import cube, mesh_of

    path.parent.mkdir(parents=True, exist_ok=True)
    mesh_of(cube()).save(str(path))
    return path


def test_non_manifold_edge_raises_stl_validation_error(tmp_path):
    source = _non_manifold_stl(tmp_path / "non_manifold.stl")
    target = tmp_path / "out.scad"

    with pytest.raises(STLValidationError, match="Non-manifold edges found: 1 edges"):
        convert_stl_to_scad(source, target)
    assert not target.exists()


def test_all_collapsed_triangle_raises_stl_validation_error(tmp_path):
    source = _collapsed_stl(tmp_path / "collapsed.stl")
    target = tmp_path / "out.scad"

    with pytest.raises(STLValidationError, match="No valid faces remain"):
        convert_stl_to_scad(source, target)
    assert not target.exists()


def test_valid_cube_converts_with_real_emitter(tmp_path):
    source = _cube_stl(tmp_path / "cube.stl")
    target = tmp_path / "cube.scad"

    stats = convert_stl_to_scad(source, target)

    assert isinstance(stats, ConversionStats)
    assert stats.faces == 12
    assert stats.metadata["pipeline"] == "segmentation"
    text = target.read_text(encoding="utf-8")
    assert text.startswith("// Source: ")
    assert str(source) in text.splitlines()[0]
    # Either a gated parametric model or the whole-mesh polyhedron fallback.
    assert ("polyhedron(" in text) == (
        stats.metadata["segmentation_output"] == "polyhedron_fallback"
    )


@pytest.mark.parametrize("make", [_non_manifold_stl, _collapsed_stl])
def test_cli_convert_invalid_stl_exits_nonzero(make, tmp_path, capsys):
    source = make(tmp_path / "bad.stl")
    target = tmp_path / "bad.scad"

    exit_code = cli.main(["convert", str(source), str(target)])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "Invalid STL file" in captured.err
    assert "Conversion successful" not in captured.out
    assert not target.exists()


def test_non_ascii_input_path_converts_and_output_is_utf8(tmp_path):
    source = _cube_stl(tmp_path / "模型" / "part.stl")
    target = tmp_path / "模型" / "part.scad"

    convert_stl_to_scad(source, target)

    text = target.read_bytes().decode("utf-8")
    assert "模型" in text.splitlines()[0]
