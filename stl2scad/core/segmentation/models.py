"""Analytic surfaces and provenance produced by surface segmentation."""

from dataclasses import dataclass
from typing import Literal

import networkx as nx
import numpy as np

from .repair import RepairedMesh

Vector = tuple[float, float, float]
Convexity = Literal["convex", "concave", "tangent"]


def angle_degrees(a, b, *, unoriented=False) -> float:
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    cosine = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    return float(
        np.degrees(np.arccos(np.clip(abs(cosine) if unoriented else cosine, -1, 1)))
    )


@dataclass(frozen=True)
class Plane:
    """Outward unit normal; the plane equation is normal.dot(x) = offset."""

    normal: Vector
    point: Vector

    @property
    def offset(self) -> float:
        return float(np.dot(self.normal, self.point))


@dataclass(frozen=True)
class Cylinder:
    """Unoriented unit axis; point is the axis point nearest the world origin."""

    axis: Vector
    point: Vector
    radius: float
    segments: int | None = None
    radial_reference: Vector | None = None


# Add cone/sphere/torus parameter dataclasses here, and a corresponding fitter
# in fitting.py. Region ownership and adjacency do not depend on surface kind.
@dataclass(frozen=True)
class Face:
    id: str
    kind: Literal["plane", "cylinder"]
    triangle_indices: tuple[int, ...]
    params: Plane | Cylinder
    convexity: Convexity | None = None

    def _errors(self, expected: dict) -> tuple[float, float, float]:
        if self.kind != expected["kind"]:
            return float("inf"), float("inf"), float("inf")
        p = self.params
        delta = np.asarray(expected["point"]) - p.point
        if isinstance(p, Plane):
            return (
                angle_degrees(p.normal, expected["normal"]),
                abs(float(delta @ p.normal)),
                0.0,
            )
        return (
            angle_degrees(p.axis, expected["axis"], unoriented=True),
            float(np.linalg.norm(np.cross(delta, p.axis))),
            abs(p.radius - expected["radius"]),
        )

    def distance_to(self, expected: dict) -> float:
        """Geometric ranking score (mm plus angular error in radians)."""
        angle, position, radius = self._errors(expected)
        return float(np.radians(angle) + position + radius)

    def matches(self, expected: dict, tol: dict) -> bool:
        angle, position, radius = self._errors(expected)
        if self.kind == "plane":
            return (
                angle <= tol["plane_normal_deg"] and position <= tol["plane_offset_mm"]
            )
        return (
            angle <= tol["cylinder_axis_deg"]
            # The harness has no cylinder-position tolerance; use its absolute
            # plane-position tolerance for the perpendicular axis-line distance.
            and position <= tol["plane_offset_mm"]
            and radius <= tol["cylinder_radius_rel"] * expected["radius"]
            and self.convexity == expected.get("convexity", self.convexity)
        )


@dataclass(frozen=True)
class SegmentationResult:
    faces: list[Face]
    graph: nx.Graph
    # Indexed support is needed for section loops in step 4. It is never used
    # as fallback geometry in the reconstructed feature solid.
    mesh: RepairedMesh | None = None

    def edge_convexity(self, face_a: Face, face_b: Face) -> Convexity:
        """Return a boundary's classification; absent adjacencies raise KeyError."""
        return self.graph[face_a.id][face_b.id]["convexity"]
