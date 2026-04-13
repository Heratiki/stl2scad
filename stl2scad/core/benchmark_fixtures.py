"""
Benchmark fixture generation for parametric conversion development.

Phase 0 scope:
- deterministic fixture set covering primitives and composite solids
- representative performance-size fixtures
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple, Union

import numpy as np
from stl.mesh import Mesh

REQUIRED_PHASE0_FIXTURE_NAMES: Tuple[str, ...] = (
    "primitive_box_axis_aligned",
    "primitive_cylinder_axis_aligned",
    "primitive_cylinder_rotated",
    "primitive_sphere",
    "primitive_cone",
    "composite_union_l_shape",
    "composite_subtraction_shell",
    "composite_disconnected_dual_box",
    "composite_overlapping_dual_box",
    "composite_cylinder_beside_box",
    "perf_sphere_low",
    "perf_sphere_medium",
    "perf_sphere_high",
)


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    filename: str
    category: str
    primitive_family: str
    description: str
    tags: Tuple[str, ...]
    generator: Callable[[], Mesh]


def generate_benchmark_fixture_set(
    output_dir: Union[Path, str],
    overwrite: bool = True,
) -> Dict[str, Any]:
    """
    Generate the benchmark fixture set and return its manifest dictionary.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fixtures_payload: List[Dict[str, Any]] = []
    for spec in _build_fixture_specs():
        fixture_path = out_dir / spec.filename
        fixture_path.parent.mkdir(parents=True, exist_ok=True)

        if overwrite or not fixture_path.exists():
            mesh = spec.generator()
            _ensure_positive_volume(mesh)
            mesh.save(str(fixture_path))
        else:
            mesh = Mesh.from_file(str(fixture_path))

        bbox = _mesh_bbox(mesh)
        fixtures_payload.append(
            {
                "name": spec.name,
                "file": spec.filename,
                "category": spec.category,
                "primitive_family": spec.primitive_family,
                "description": spec.description,
                "tags": list(spec.tags),
                "triangles": int(len(mesh.vectors)),
                "bounding_box": bbox,
            }
        )

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "required_phase0_fixture_names": list(REQUIRED_PHASE0_FIXTURE_NAMES),
        "fixtures": fixtures_payload,
    }

    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, indent=2)

    return manifest


def load_benchmark_manifest(fixtures_dir: Union[Path, str]) -> Dict[str, Any]:
    """Load fixture manifest from a benchmark fixture directory."""
    manifest_path = Path(fixtures_dir) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Benchmark fixture manifest not found: {manifest_path}"
        )
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def ensure_benchmark_fixtures(fixtures_dir: Union[Path, str]) -> Dict[str, Any]:
    """
    Ensure fixture set and manifest exist.
    Generates missing fixtures only when manifest is absent.
    """
    fixtures_path = Path(fixtures_dir)
    manifest_path = fixtures_path / "manifest.json"
    if manifest_path.exists():
        return load_benchmark_manifest(fixtures_path)
    return generate_benchmark_fixture_set(fixtures_path, overwrite=False)


def _build_fixture_specs() -> List[FixtureSpec]:
    return [
        FixtureSpec(
            name="primitive_box_axis_aligned",
            filename="primitive_box_axis_aligned.stl",
            category="primitive",
            primitive_family="box",
            description="Axis-aligned rectangular box.",
            tags=("phase0", "primitive", "box"),
            generator=lambda: _make_box(width=20.0, depth=12.0, height=8.0),
        ),
        FixtureSpec(
            name="primitive_cylinder_axis_aligned",
            filename="primitive_cylinder_axis_aligned.stl",
            category="primitive",
            primitive_family="cylinder",
            description="Axis-aligned cylinder.",
            tags=("phase0", "primitive", "cylinder"),
            generator=lambda: _make_cylinder(radius=6.0, height=20.0, segments=64),
        ),
        FixtureSpec(
            name="primitive_cylinder_rotated",
            filename="primitive_cylinder_rotated.stl",
            category="primitive",
            primitive_family="cylinder",
            description="Rotated cylinder (non-axis-aligned).",
            tags=("phase0", "primitive", "cylinder", "rotated"),
            generator=lambda: _make_rotated_cylinder(),
        ),
        FixtureSpec(
            name="primitive_sphere",
            filename="primitive_sphere.stl",
            category="primitive",
            primitive_family="sphere",
            description="UV sphere primitive for sphere candidate fitting.",
            tags=("phase0", "primitive", "sphere"),
            generator=lambda: _make_sphere(
                radius=8.0, lat_segments=24, lon_segments=48
            ),
        ),
        FixtureSpec(
            name="primitive_cone",
            filename="primitive_cone.stl",
            category="primitive",
            primitive_family="cone",
            description="Cone primitive (tip + base).",
            tags=("phase0", "primitive", "cone"),
            generator=lambda: _make_cone(radius=6.0, height=18.0, segments=64),
        ),
        FixtureSpec(
            name="composite_union_l_shape",
            filename="composite_union_l_shape.stl",
            category="composite",
            primitive_family="union_like",
            description="Union-like L-shape composed from voxel CSG.",
            tags=("phase0", "composite", "union_like"),
            generator=lambda: _make_union_l_shape(),
        ),
        FixtureSpec(
            name="composite_subtraction_shell",
            filename="composite_subtraction_shell.stl",
            category="composite",
            primitive_family="subtraction_like",
            description="Subtraction-like shell: outer box minus inner cavity.",
            tags=("phase0", "composite", "subtraction_like"),
            generator=lambda: _make_subtraction_shell(),
        ),
        FixtureSpec(
            name="composite_disconnected_dual_box",
            filename="composite_disconnected_dual_box.stl",
            category="composite",
            primitive_family="multi_component",
            description="Disconnected dual-box multi-component mesh.",
            tags=("phase0", "composite", "multi_component"),
            generator=lambda: _make_disconnected_dual_box(),
        ),
        FixtureSpec(
            name="composite_overlapping_dual_box",
            filename="composite_overlapping_dual_box.stl",
            category="composite",
            primitive_family="multi_component",
            description="Two boxes with partial AABB overlap (benign assembly contact).",
            tags=("phase0", "composite", "multi_component", "overlap"),
            generator=lambda: _make_overlapping_dual_box(),
        ),
        FixtureSpec(
            name="composite_cylinder_beside_box",
            filename="composite_cylinder_beside_box.stl",
            category="composite",
            primitive_family="multi_component",
            description="Cylinder placed beside a box with partial bbox overlap.",
            tags=("phase0", "composite", "multi_component", "overlap"),
            generator=lambda: _make_cylinder_beside_box(),
        ),
        FixtureSpec(
            name="perf_sphere_low",
            filename="perf/perf_sphere_low.stl",
            category="performance",
            primitive_family="sphere",
            description="Low complexity sphere fixture for perf baseline.",
            tags=("phase0", "performance", "size_low"),
            generator=lambda: _make_sphere(
                radius=10.0, lat_segments=8, lon_segments=16
            ),
        ),
        FixtureSpec(
            name="perf_sphere_medium",
            filename="perf/perf_sphere_medium.stl",
            category="performance",
            primitive_family="sphere",
            description="Medium complexity sphere fixture for perf baseline.",
            tags=("phase0", "performance", "size_medium"),
            generator=lambda: _make_sphere(
                radius=10.0, lat_segments=24, lon_segments=48
            ),
        ),
        FixtureSpec(
            name="perf_sphere_high",
            filename="perf/perf_sphere_high.stl",
            category="performance",
            primitive_family="sphere",
            description="High complexity sphere fixture for perf baseline.",
            tags=("phase0", "performance", "size_high"),
            generator=lambda: _make_sphere(
                radius=10.0, lat_segments=40, lon_segments=80
            ),
        ),
    ]


def _make_box(
    width: float,
    depth: float,
    height: float,
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Mesh:
    x0, y0, z0 = origin
    x1 = x0 + width
    y1 = y0 + depth
    z1 = z0 + height

    vertices = np.array(
        [
            [x0, y0, z0],
            [x1, y0, z0],
            [x1, y1, z0],
            [x0, y1, z0],
            [x0, y0, z1],
            [x1, y0, z1],
            [x1, y1, z1],
            [x0, y1, z1],
        ],
        dtype=np.float64,
    )
    faces = np.array(
        [
            [0, 2, 1],
            [0, 3, 2],  # bottom
            [4, 5, 6],
            [4, 6, 7],  # top
            [0, 1, 5],
            [0, 5, 4],  # front
            [1, 2, 6],
            [1, 6, 5],  # right
            [2, 3, 7],
            [2, 7, 6],  # back
            [3, 0, 4],
            [3, 4, 7],  # left
        ],
        dtype=np.int32,
    )
    return _mesh_from_vertices_faces(vertices, faces)


def _make_cylinder(radius: float, height: float, segments: int) -> Mesh:
    if segments < 3:
        raise ValueError("Cylinder requires at least 3 segments")

    vertices: List[List[float]] = []
    for i in range(segments):
        theta = 2.0 * math.pi * (i / segments)
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        vertices.append([x, y, 0.0])  # bottom
        vertices.append([x, y, height])  # top

    center_bottom = len(vertices)
    vertices.append([0.0, 0.0, 0.0])
    center_top = len(vertices)
    vertices.append([0.0, 0.0, height])

    faces: List[List[int]] = []
    for i in range(segments):
        ni = (i + 1) % segments
        b0 = 2 * i
        t0 = b0 + 1
        b1 = 2 * ni
        t1 = b1 + 1

        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])

        faces.append([center_bottom, b1, b0])
        faces.append([center_top, t0, t1])

    return _mesh_from_vertices_faces(np.asarray(vertices), np.asarray(faces))


def _make_cone(radius: float, height: float, segments: int) -> Mesh:
    if segments < 3:
        raise ValueError("Cone requires at least 3 segments")

    vertices: List[List[float]] = []
    for i in range(segments):
        theta = 2.0 * math.pi * (i / segments)
        vertices.append([radius * math.cos(theta), radius * math.sin(theta), 0.0])
    apex = len(vertices)
    vertices.append([0.0, 0.0, height])
    center_bottom = len(vertices)
    vertices.append([0.0, 0.0, 0.0])

    faces: List[List[int]] = []
    for i in range(segments):
        ni = (i + 1) % segments
        faces.append([i, ni, apex])
        faces.append([center_bottom, ni, i])

    return _mesh_from_vertices_faces(np.asarray(vertices), np.asarray(faces))


def _make_sphere(radius: float, lat_segments: int, lon_segments: int) -> Mesh:
    if lat_segments < 3 or lon_segments < 3:
        raise ValueError("Sphere requires lat/lon segments >= 3")

    vertices: List[List[float]] = [[0.0, 0.0, radius]]  # top pole

    for lat_idx in range(1, lat_segments):
        phi = math.pi * (lat_idx / lat_segments)
        z = radius * math.cos(phi)
        r = radius * math.sin(phi)
        for lon_idx in range(lon_segments):
            theta = 2.0 * math.pi * (lon_idx / lon_segments)
            x = r * math.cos(theta)
            y = r * math.sin(theta)
            vertices.append([x, y, z])

    bottom_index = len(vertices)
    vertices.append([0.0, 0.0, -radius])  # bottom pole

    def ring_index(lat_idx: int, lon_idx: int) -> int:
        # lat_idx in [1, lat_segments - 1]
        return 1 + (lat_idx - 1) * lon_segments + (lon_idx % lon_segments)

    faces: List[List[int]] = []

    # Top cap
    for lon_idx in range(lon_segments):
        faces.append([0, ring_index(1, lon_idx + 1), ring_index(1, lon_idx)])

    # Middle strips
    for lat_idx in range(1, lat_segments - 1):
        for lon_idx in range(lon_segments):
            a = ring_index(lat_idx, lon_idx)
            b = ring_index(lat_idx, lon_idx + 1)
            c = ring_index(lat_idx + 1, lon_idx)
            d = ring_index(lat_idx + 1, lon_idx + 1)
            faces.append([a, b, d])
            faces.append([a, d, c])

    # Bottom cap
    last_ring = lat_segments - 1
    for lon_idx in range(lon_segments):
        faces.append(
            [
                bottom_index,
                ring_index(last_ring, lon_idx),
                ring_index(last_ring, lon_idx + 1),
            ]
        )

    return _mesh_from_vertices_faces(np.asarray(vertices), np.asarray(faces))


def _make_rotated_cylinder() -> Mesh:
    mesh = _make_cylinder(radius=5.0, height=18.0, segments=64)
    vertices = mesh.vectors.reshape(-1, 3)

    rx = _rotation_matrix_x(math.radians(28.0))
    ry = _rotation_matrix_y(math.radians(21.0))
    transform = ry @ rx
    rotated = vertices @ transform.T
    rotated[:, 0] += 7.5
    rotated[:, 2] += 1.0

    mesh.vectors = rotated.reshape(mesh.vectors.shape)
    return mesh


def _make_union_l_shape() -> Mesh:
    a = _box_cells(0, 8, 0, 4, 0, 4)
    b = _box_cells(0, 4, 0, 8, 0, 4)
    cells = a | b
    return _mesh_from_voxels(cells, voxel_size=1.0, origin=(-4.0, -4.0, -2.0))


def _make_subtraction_shell() -> Mesh:
    outer = _box_cells(0, 12, 0, 12, 0, 12)
    inner = _box_cells(3, 9, 3, 9, 3, 9)
    cells = outer - inner
    return _mesh_from_voxels(cells, voxel_size=1.0, origin=(-6.0, -6.0, -6.0))


def _make_disconnected_dual_box() -> Mesh:
    left = _box_cells(0, 4, 0, 4, 0, 4)
    right = _box_cells(7, 11, 0, 4, 0, 4)
    cells = left | right
    return _mesh_from_voxels(cells, voxel_size=1.0, origin=(-5.5, -2.0, -2.0))


def _box_cells(
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    z0: int,
    z1: int,
) -> Set[Tuple[int, int, int]]:
    return {
        (x, y, z) for x in range(x0, x1) for y in range(y0, y1) for z in range(z0, z1)
    }


def _mesh_from_voxels(
    cells: Set[Tuple[int, int, int]],
    voxel_size: float = 1.0,
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Mesh:
    if not cells:
        raise ValueError("Cannot build mesh from an empty voxel set")

    vertex_map: Dict[Tuple[int, int, int], int] = {}
    vertices: List[Tuple[int, int, int]] = []
    faces: List[List[int]] = []

    face_defs = [
        # +X
        ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
        # -X
        ((-1, 0, 0), [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)]),
        # +Y
        ((0, 1, 0), [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)]),
        # -Y
        ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
        # +Z
        ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
        # -Z
        ((0, 0, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]),
    ]

    def vertex_index(coord: Tuple[int, int, int]) -> int:
        idx = vertex_map.get(coord)
        if idx is None:
            idx = len(vertices)
            vertex_map[coord] = idx
            vertices.append(coord)
        return idx

    for x, y, z in sorted(cells):
        for (nx, ny, nz), corners in face_defs:
            if (x + nx, y + ny, z + nz) in cells:
                continue
            corner_indices = [
                vertex_index((x + cx, y + cy, z + cz)) for (cx, cy, cz) in corners
            ]
            faces.append([corner_indices[0], corner_indices[1], corner_indices[2]])
            faces.append([corner_indices[0], corner_indices[2], corner_indices[3]])

    vertices_array = np.asarray(vertices, dtype=np.float64)
    vertices_array *= voxel_size
    vertices_array[:, 0] += origin[0]
    vertices_array[:, 1] += origin[1]
    vertices_array[:, 2] += origin[2]

    return _mesh_from_vertices_faces(vertices_array, np.asarray(faces, dtype=np.int32))


def _mesh_from_vertices_faces(vertices: np.ndarray, faces: np.ndarray) -> Mesh:
    mesh = Mesh(np.zeros(len(faces), dtype=Mesh.dtype), remove_empty_areas=False)
    for idx, face in enumerate(faces):
        mesh.vectors[idx] = vertices[face]
    return mesh


def _mesh_bbox(mesh: Mesh) -> Dict[str, float]:
    min_coords = [float(v) for v in mesh.min_]
    max_coords = [float(v) for v in mesh.max_]
    return {
        "min_x": min_coords[0],
        "min_y": min_coords[1],
        "min_z": min_coords[2],
        "max_x": max_coords[0],
        "max_y": max_coords[1],
        "max_z": max_coords[2],
        "width": max_coords[0] - min_coords[0],
        "height": max_coords[1] - min_coords[1],
        "depth": max_coords[2] - min_coords[2],
    }


def _ensure_positive_volume(mesh: Mesh) -> None:
    with np.errstate(all="ignore"):
        volume = float(mesh.get_mass_properties()[0])
    if not np.isfinite(volume):
        return
    if volume < 0:
        # Flip winding by swapping second and third vertices for every triangle.
        mesh.vectors[:, [1, 2]] = mesh.vectors[:, [2, 1]]


def _rotation_matrix_x(angle_rad: float) -> np.ndarray:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array(
        [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]],
        dtype=np.float64,
    )


def _rotation_matrix_y(angle_rad: float) -> np.ndarray:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array(
        [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]],
        dtype=np.float64,
    )
