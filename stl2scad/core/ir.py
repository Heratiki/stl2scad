"""Typed Intermediate Representation (IR) dataclasses for stl2scad.

This module defines the typed IR node hierarchy representing geometric
primitives, sketches, transforms, booleans, edge treatments, structural
features, and parameters. Every node is an immutable (frozen) dataclass
carrying ``face_ids`` for provenance tracking back to segmented mesh surface
patches.

The classes support round-trip serialization to and from plain Python
dictionaries via ``to_dict()`` and ``from_dict()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Union


# ---------------------------------------------------------------------------
# Base Node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IRNode:
    """Base class for all Intermediate Representation (IR) nodes.

    Every node carries ``face_ids: tuple[str, ...]`` for provenance tracking back
    to segmented mesh surface patches.
    """

    face_ids: tuple[str, ...] = field(default=(), kw_only=True)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this node to a plain dict matching the IR JSON schema."""
        raise NotImplementedError

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IRNode:
        """Construct an IR node from its dictionary representation."""
        return from_dict(d)


# ---------------------------------------------------------------------------
# Root Nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Interpretation(IRNode):
    """Top-level interpretation candidate wrapping a feature tree."""

    root: IRNode
    rank: int = 0
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "Interpretation",
            "confidence": self.confidence,
            "rank": self.rank,
            "root": self.root.to_dict(),
        }
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Interpretation:
        return cls(
            root=from_dict(d["root"]),
            rank=int(d.get("rank", 0)),
            confidence=float(d.get("confidence", 1.0)),
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class FallbackMesh(IRNode):
    """Terminal node representing unrecovered raw mesh fallback."""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "FallbackMesh"}
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FallbackMesh:
        return cls(face_ids=tuple(d.get("face_ids", ())))


# ---------------------------------------------------------------------------
# Boolean (Combine) Nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BooleanUnion(IRNode):
    """Boolean union combining multiple positive child features."""

    children: tuple[IRNode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "BooleanUnion",
            "children": [c.to_dict() for c in self.children],
        }
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BooleanUnion:
        children = tuple(from_dict(c) for c in d.get("children", []))
        return cls(children=children, face_ids=tuple(d.get("face_ids", ())))


@dataclass(frozen=True)
class BooleanDifference(IRNode):
    """Boolean difference subtracting cuts from a base primitive."""

    base: IRNode
    cuts: tuple[IRNode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "BooleanDifference",
            "base": self.base.to_dict(),
            "cuts": [c.to_dict() for c in self.cuts],
        }
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BooleanDifference:
        cuts = tuple(from_dict(c) for c in d.get("cuts", ()))
        return cls(
            base=from_dict(d["base"]),
            cuts=cuts,
            face_ids=tuple(d.get("face_ids", ())),
        )


# ---------------------------------------------------------------------------
# 2D Sketch Node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sketch2D(IRNode):
    """2D profile sketch defined by 2D vertex points."""

    points: tuple[tuple[float, float], ...] = ()
    kind: str = "polygon"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "Sketch2D",
            "kind": self.kind,
            "points": [list(p) for p in self.points],
        }
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Sketch2D:
        raw_pts = d.get("points", [])
        pts = tuple((float(p[0]), float(p[1])) for p in raw_pts)
        return cls(
            points=pts,
            kind=d.get("kind", "polygon"),
            face_ids=tuple(d.get("face_ids", ())),
        )


# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SketchLine2D(IRNode):
    """A directed straight segment in a sketch path."""

    start: tuple[float, float] = (0.0, 0.0)
    end: tuple[float, float] = (0.0, 0.0)

    def to_dict(self) -> dict[str, Any]:
        d = {"type": "SketchLine2D", "start": list(self.start), "end": list(self.end)}
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SketchLine2D:
        return cls(
            start=tuple(d["start"]),
            end=tuple(d["end"]),
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class SketchArc2D(IRNode):
    """An oriented circumcircle arc, including its original polygon phase."""

    center: tuple[float, float] = (0.0, 0.0)
    radius: float = 0.0
    start_deg: float = 0.0
    sweep_deg: float = 0.0
    segments: int = 64
    phase_deg: float = 0.0
    convexity: str = "convex"

    def to_dict(self) -> dict[str, Any]:
        d = {
            "type": "SketchArc2D",
            "center": list(self.center),
            "radius": self.radius,
            "start_deg": self.start_deg,
            "sweep_deg": self.sweep_deg,
            "segments": self.segments,
            "phase_deg": self.phase_deg,
            "convexity": self.convexity,
        }
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SketchArc2D:
        return cls(
            center=tuple(d["center"]),
            radius=float(d["radius"]),
            start_deg=float(d["start_deg"]),
            sweep_deg=float(d["sweep_deg"]),
            segments=int(d["segments"]),
            phase_deg=float(d["phase_deg"]),
            convexity=d["convexity"],
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class SketchPath2D(IRNode):
    """Closed line/arc profile. Existing point-only Sketch2D stays unchanged."""

    segments: tuple[Union[SketchLine2D, SketchArc2D], ...] = ()
    kind: str = "arc"

    def to_dict(self) -> dict[str, Any]:
        d = {
            "type": "SketchPath2D",
            "kind": self.kind,
            "segments": [s.to_dict() for s in self.segments],
        }
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SketchPath2D:
        segments = tuple(from_dict(s) for s in d["segments"])
        if any(not isinstance(s, (SketchLine2D, SketchArc2D)) for s in segments):
            raise ValueError("SketchPath2D requires line or arc segments")
        return cls(
            segments=segments,
            kind=d.get("kind", "arc"),
            face_ids=tuple(d.get("face_ids", ())),
        )


# Extrusions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtrudeLinear(IRNode):
    """Linear extrusion of a 2D profile sketch along an axis."""

    height: float = 0.0
    profile: Optional[IRNode] = None
    confidence: Optional[float] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "ExtrudeLinear",
            "height": self.height,
        }
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.profile is not None:
            d["profile"] = self.profile.to_dict()
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExtrudeLinear:
        known = {"type", "height", "confidence", "profile", "face_ids"}
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        prof = from_dict(d["profile"]) if "profile" in d else None
        conf = float(d["confidence"]) if "confidence" in d else None
        return cls(
            height=float(d.get("height", 0.0)),
            profile=prof,
            confidence=conf,
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class ExtrudeRevolve(IRNode):
    """Rotational extrusion of a 2D profile sketch around an axis."""

    profile: Optional[IRNode] = None
    axis_origin: Optional[tuple[float, float, float]] = None
    primitive_upgrade: Optional[dict[str, Any]] = None
    detected_via: Optional[str] = None
    inner_r: Optional[float] = None
    outer_r: Optional[float] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "ExtrudeRevolve"}
        if self.profile is not None:
            d["profile"] = self.profile.to_dict()
        if self.axis_origin is not None:
            d["axis_origin"] = list(self.axis_origin)
        if self.primitive_upgrade is not None:
            d["primitive_upgrade"] = dict(self.primitive_upgrade)
        if self.detected_via is not None:
            d["detected_via"] = self.detected_via
        if self.inner_r is not None:
            d["inner_r"] = self.inner_r
        if self.outer_r is not None:
            d["outer_r"] = self.outer_r
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExtrudeRevolve:
        known = {
            "type", "profile", "axis_origin", "primitive_upgrade",
            "detected_via", "inner_r", "outer_r", "face_ids",
        }
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        prof = from_dict(d["profile"]) if "profile" in d else None
        axis_orig = (
            tuple(float(x) for x in d["axis_origin"])
            if "axis_origin" in d and d["axis_origin"] is not None
            else None
        )
        return cls(
            profile=prof,
            axis_origin=axis_orig,
            primitive_upgrade=d.get("primitive_upgrade"),
            detected_via=d.get("detected_via"),
            inner_r=float(d["inner_r"]) if "inner_r" in d else None,
            outer_r=float(d["outer_r"]) if "outer_r" in d else None,
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


# ---------------------------------------------------------------------------
# Transform Nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransformTranslate(IRNode):
    """3D translation offset applied to a child feature."""

    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    child: Optional[IRNode] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "TransformTranslate",
            "offset": list(self.offset),
        }
        if self.child is not None:
            d["child"] = self.child.to_dict()
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TransformTranslate:
        off = tuple(float(x) for x in d.get("offset", (0.0, 0.0, 0.0)))
        ch = from_dict(d["child"]) if "child" in d else None
        return cls(
            offset=off,
            child=ch,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class TransformRotate(IRNode):
    """3D Euler XYZ rotation (in degrees) applied to a child feature."""

    angles_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    child: Optional[IRNode] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "TransformRotate",
            "angles_deg": list(self.angles_deg),
        }
        if self.child is not None:
            d["child"] = self.child.to_dict()
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TransformRotate:
        angles = tuple(float(x) for x in d.get("angles_deg", (0.0, 0.0, 0.0)))
        ch = from_dict(d["child"]) if "child" in d else None
        return cls(
            angles_deg=angles,
            child=ch,
            face_ids=tuple(d.get("face_ids", ())),
        )


_IDENTITY_4X4: tuple[tuple[float, ...], ...] = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


@dataclass(frozen=True)
class TransformMultMatrix(IRNode):
    """4x4 affine matrix transformation for part-frame placement."""

    matrix: tuple[tuple[float, ...], ...] = _IDENTITY_4X4
    child: Optional[IRNode] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "TransformMultMatrix",
            "matrix": [list(row) for row in self.matrix],
            "face_ids": list(self.face_ids),
        }
        if self.child is not None:
            d["child"] = self.child.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TransformMultMatrix:
        raw_m = d.get("matrix", _IDENTITY_4X4)
        m = tuple(tuple(float(v) for v in row) for row in raw_m)
        ch = from_dict(d["child"]) if "child" in d else None
        return cls(
            matrix=m,
            child=ch,
            face_ids=tuple(d.get("face_ids", ())),
        )


# ---------------------------------------------------------------------------
# Pattern Nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternLinear(IRNode):
    """1D linear array repetition of a child feature."""

    origin: Optional[tuple[float, ...]] = None
    step: Optional[tuple[float, ...]] = None
    count: int = 0
    spacing: float = 0.0
    diameter: float = 0.0
    axis: Optional[str] = None
    child: Optional[IRNode] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "PatternLinear",
            "origin": list(self.origin) if self.origin is not None else None,
            "step": list(self.step) if self.step is not None else None,
            "count": self.count,
            "spacing": self.spacing,
            "diameter": self.diameter,
            "axis": self.axis,
        }
        if self.child is not None:
            d["child"] = self.child.to_dict()
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PatternLinear:
        orig = tuple(float(x) for x in d["origin"]) if d.get("origin") is not None else None
        st = tuple(float(x) for x in d["step"]) if d.get("step") is not None else None
        ch = from_dict(d["child"]) if "child" in d else None
        return cls(
            origin=orig,
            step=st,
            count=int(d.get("count", 0)),
            spacing=float(d.get("spacing", 0.0)),
            diameter=float(d.get("diameter", 0.0)),
            axis=d.get("axis"),
            child=ch,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class PatternGrid(IRNode):
    """2D rectangular grid repetition of a child feature."""

    origin: Optional[tuple[float, ...]] = None
    row_step: Optional[tuple[float, ...]] = None
    col_step: Optional[tuple[float, ...]] = None
    rows: int = 0
    cols: int = 0
    diameter: float = 0.0
    axis: Optional[str] = None
    child: Optional[IRNode] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "PatternGrid",
            "origin": list(self.origin) if self.origin is not None else None,
            "row_step": list(self.row_step) if self.row_step is not None else None,
            "col_step": list(self.col_step) if self.col_step is not None else None,
            "rows": self.rows,
            "cols": self.cols,
            "diameter": self.diameter,
            "axis": self.axis,
        }
        if self.child is not None:
            d["child"] = self.child.to_dict()
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PatternGrid:
        orig = tuple(float(x) for x in d["origin"]) if d.get("origin") is not None else None
        rs = tuple(float(x) for x in d["row_step"]) if d.get("row_step") is not None else None
        cs = tuple(float(x) for x in d["col_step"]) if d.get("col_step") is not None else None
        ch = from_dict(d["child"]) if "child" in d else None
        return cls(
            origin=orig,
            row_step=rs,
            col_step=cs,
            rows=int(d.get("rows", 0)),
            cols=int(d.get("cols", 0)),
            diameter=float(d.get("diameter", 0.0)),
            axis=d.get("axis"),
            child=ch,
            face_ids=tuple(d.get("face_ids", ())),
        )


# ---------------------------------------------------------------------------
# Cutouts and Edge Treatments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoleThrough(IRNode):
    """Cylindrical through-hole cutout piercing across a solid."""

    diameter: float = 0.0
    axis: Optional[str] = None
    depth: Optional[float] = None
    component_faces: Optional[int] = None
    radial_error_ratio: Optional[float] = None
    angular_coverage: Optional[float] = None
    source_component_index: Optional[int] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "HoleThrough",
            "diameter": self.diameter,
        }
        if self.axis is not None:
            d["axis"] = self.axis
        if self.depth is not None:
            d["depth"] = self.depth
        if self.component_faces is not None:
            d["component_faces"] = self.component_faces
        if self.radial_error_ratio is not None:
            d["radial_error_ratio"] = self.radial_error_ratio
        if self.angular_coverage is not None:
            d["angular_coverage"] = self.angular_coverage
        if self.source_component_index is not None:
            d["source_component_index"] = self.source_component_index
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HoleThrough:
        known = {
            "type", "diameter", "axis", "depth", "component_faces",
            "radial_error_ratio", "angular_coverage", "source_component_index",
            "face_ids",
        }
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        return cls(
            diameter=float(d.get("diameter", 0.0)),
            axis=d.get("axis"),
            depth=float(d["depth"]) if "depth" in d else None,
            component_faces=int(d["component_faces"]) if "component_faces" in d else None,
            radial_error_ratio=float(d["radial_error_ratio"]) if "radial_error_ratio" in d else None,
            angular_coverage=float(d["angular_coverage"]) if "angular_coverage" in d else None,
            source_component_index=int(d["source_component_index"]) if "source_component_index" in d else None,
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class HoleBlind(IRNode):
    """Depth-limited cylindrical blind hole."""

    depth: float = 0.0
    diameter: float = 0.0
    radius: Optional[float] = None
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    host_face_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.radius is None and self.diameter != 0.0:
            object.__setattr__(self, "radius", self.diameter / 2.0)
        elif self.diameter == 0.0 and self.radius is not None:
            object.__setattr__(self, "diameter", self.radius * 2.0)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "HoleBlind",
            "depth": self.depth,
            "diameter": self.diameter,
            "center": list(self.center),
            "axis": list(self.axis),
            "face_ids": list(self.face_ids),
        }
        if self.radius is not None:
            d["radius"] = self.radius
        if self.host_face_id is not None:
            d["host_face_id"] = self.host_face_id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HoleBlind:
        center = tuple(float(x) for x in d.get("center", (0.0, 0.0, 0.0)))
        axis = tuple(float(x) for x in d.get("axis", (0.0, 0.0, 1.0)))
        return cls(
            depth=float(d.get("depth", 0.0)),
            diameter=float(d.get("diameter", 0.0)),
            radius=float(d["radius"]) if "radius" in d else None,
            center=center,
            axis=axis,
            host_face_id=d.get("host_face_id"),
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class HoleCounterbore(IRNode):
    """Counterbore stepped hole cutout."""

    through_diameter: float = 0.0
    bore_diameter: float = 0.0
    bore_depth: float = 0.0
    axis: Optional[str] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "HoleCounterbore",
            "through_diameter": self.through_diameter,
            "bore_diameter": self.bore_diameter,
            "bore_depth": self.bore_depth,
        }
        if self.axis is not None:
            d["axis"] = self.axis
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HoleCounterbore:
        known = {
            "type", "through_diameter", "bore_diameter", "bore_depth", "axis",
            "face_ids",
        }
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        return cls(
            through_diameter=float(d.get("through_diameter", 0.0)),
            bore_diameter=float(d.get("bore_diameter", 0.0)),
            bore_depth=float(d.get("bore_depth", 0.0)),
            axis=d.get("axis"),
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class Slot(IRNode):
    """Obround slot cutout defined by start and end centers plus width."""

    start: Optional[tuple[float, float, float]] = None
    end: Optional[tuple[float, float, float]] = None
    width: float = 0.0
    axis: Optional[str] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "Slot",
            "width": self.width,
        }
        if self.start is not None:
            d["start"] = list(self.start)
        if self.end is not None:
            d["end"] = list(self.end)
        if self.axis is not None:
            d["axis"] = self.axis
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Slot:
        known = {"type", "width", "start", "end", "axis", "face_ids"}
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        start = tuple(float(x) for x in d["start"]) if "start" in d else None
        end = tuple(float(x) for x in d["end"]) if "end" in d else None
        return cls(
            start=start,
            end=end,
            width=float(d.get("width", 0.0)),
            axis=d.get("axis"),
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class RectangularCutout(IRNode):
    """Rectangular prism cutout piercing a solid."""

    size: tuple[float, float, float] = (0.0, 0.0, 0.0)
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "RectangularCutout",
            "size": list(self.size),
        }
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RectangularCutout:
        known = {"type", "size", "face_ids"}
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        size = tuple(float(x) for x in d.get("size", (0.0, 0.0, 0.0)))
        return cls(
            size=size,
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class RectangularPocket(IRNode):
    """Rectangular pocket cavity removed from a solid."""

    size: tuple[float, float, float] = (0.0, 0.0, 0.0)
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "RectangularPocket",
            "size": list(self.size),
        }
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RectangularPocket:
        known = {"type", "size", "face_ids"}
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        size = tuple(float(x) for x in d.get("size", (0.0, 0.0, 0.0)))
        return cls(
            size=size,
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class ChamferOrFilletEdge(IRNode):
    """Annotation node documenting chamfered or filleted boundary edges."""

    edge_kind: str = "unknown"
    size: float = 0.0
    note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "ChamferOrFilletEdge",
            "edge_kind": self.edge_kind,
            "size": self.size,
        }
        if self.note is not None:
            d["note"] = self.note
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChamferOrFilletEdge:
        return cls(
            edge_kind=d.get("edge_kind", "unknown"),
            size=float(d.get("size", 0.0)),
            note=d.get("note"),
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class Fillet(IRNode):
    """Fillet rounding between two adjacent faces."""

    radius: float = 0.0
    face1_id: str = ""
    face2_id: str = ""

    def __post_init__(self) -> None:
        if not self.face_ids and (self.face1_id or self.face2_id):
            ids = tuple(f for f in (self.face1_id, self.face2_id) if f)
            object.__setattr__(self, "face_ids", ids)
        elif self.face_ids and not (self.face1_id or self.face2_id):
            if len(self.face_ids) >= 1:
                object.__setattr__(self, "face1_id", self.face_ids[0])
            if len(self.face_ids) >= 2:
                object.__setattr__(self, "face2_id", self.face_ids[1])

    @property
    def face_id_a(self) -> str:
        return self.face1_id

    @property
    def face_id_b(self) -> str:
        return self.face2_id

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "Fillet",
            "radius": self.radius,
            "face1_id": self.face1_id,
            "face2_id": self.face2_id,
            "face_ids": list(self.face_ids),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fillet:
        f1 = d.get("face1_id") or d.get("face_id_a") or ""
        f2 = d.get("face2_id") or d.get("face_id_b") or ""
        fids = tuple(d.get("face_ids", ()))
        return cls(
            radius=float(d.get("radius", 0.0)),
            face1_id=f1,
            face2_id=f2,
            face_ids=fids,
        )


# ---------------------------------------------------------------------------
# Structural Features & Positive Primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Boss(IRNode):
    """Added positive cylindrical or prismatic boss feature on a host face."""

    height: float = 0.0
    radius: float = 0.0
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    diameter: Optional[float] = None
    host_face_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.diameter is None and self.radius != 0.0:
            object.__setattr__(self, "diameter", self.radius * 2.0)
        elif self.radius == 0.0 and self.diameter is not None:
            object.__setattr__(self, "radius", self.diameter / 2.0)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "Boss",
            "height": self.height,
            "radius": self.radius,
            "center": list(self.center),
            "axis": list(self.axis),
            "face_ids": list(self.face_ids),
        }
        if self.diameter is not None:
            d["diameter"] = self.diameter
        if self.host_face_id is not None:
            d["host_face_id"] = self.host_face_id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Boss:
        center = tuple(float(x) for x in d.get("center", (0.0, 0.0, 0.0)))
        axis = tuple(float(x) for x in d.get("axis", (0.0, 0.0, 1.0)))
        return cls(
            height=float(d.get("height", 0.0)),
            radius=float(d.get("radius", 0.0)),
            center=center,
            axis=axis,
            diameter=float(d["diameter"]) if "diameter" in d else None,
            host_face_id=d.get("host_face_id"),
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class PrimitivePlate(IRNode):
    """Plate solid primitive defined by origin and size box."""

    origin: Optional[tuple[float, float, float]] = None
    size: Optional[tuple[float, float, float]] = None
    confidence: float = 0.0
    detected_via: Optional[str] = None
    local_u_axis: Optional[tuple[float, float, float]] = None
    local_v_axis: Optional[tuple[float, float, float]] = None
    dominant_axis: Optional[tuple[float, float, float]] = None
    local_n_axis: Optional[tuple[float, float, float]] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "PrimitivePlate",
            "confidence": self.confidence,
        }
        if self.origin is not None:
            d["origin"] = list(self.origin)
        if self.size is not None:
            d["size"] = list(self.size)
        if self.detected_via is not None:
            d["detected_via"] = self.detected_via
        if self.local_u_axis is not None:
            d["local_u_axis"] = list(self.local_u_axis)
        if self.local_v_axis is not None:
            d["local_v_axis"] = list(self.local_v_axis)
        if self.dominant_axis is not None:
            d["dominant_axis"] = list(self.dominant_axis)
        if self.local_n_axis is not None:
            d["local_n_axis"] = list(self.local_n_axis)
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PrimitivePlate:
        known = {
            "type", "confidence", "origin", "size", "detected_via",
            "local_u_axis", "local_v_axis", "dominant_axis", "local_n_axis",
            "face_ids",
        }
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        origin = tuple(float(x) for x in d["origin"]) if "origin" in d else None
        size = tuple(float(x) for x in d["size"]) if "size" in d else None
        u = tuple(float(x) for x in d["local_u_axis"]) if "local_u_axis" in d else None
        v = tuple(float(x) for x in d["local_v_axis"]) if "local_v_axis" in d else None
        dom = tuple(float(x) for x in d["dominant_axis"]) if "dominant_axis" in d else None
        n = tuple(float(x) for x in d["local_n_axis"]) if "local_n_axis" in d else None
        return cls(
            origin=origin,
            size=size,
            confidence=float(d.get("confidence", 0.0)),
            detected_via=d.get("detected_via"),
            local_u_axis=u,
            local_v_axis=v,
            dominant_axis=dom,
            local_n_axis=n,
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class PrimitiveBox(IRNode):
    """Box solid primitive defined by origin and size vector."""

    origin: Optional[tuple[float, float, float]] = None
    size: Optional[tuple[float, float, float]] = None
    confidence: float = 0.0
    detected_via: Optional[str] = None
    local_u_axis: Optional[tuple[float, float, float]] = None
    local_v_axis: Optional[tuple[float, float, float]] = None
    dominant_axis: Optional[tuple[float, float, float]] = None
    local_n_axis: Optional[tuple[float, float, float]] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "PrimitiveBox",
            "confidence": self.confidence,
        }
        if self.origin is not None:
            d["origin"] = list(self.origin)
        if self.size is not None:
            d["size"] = list(self.size)
        if self.detected_via is not None:
            d["detected_via"] = self.detected_via
        if self.local_u_axis is not None:
            d["local_u_axis"] = list(self.local_u_axis)
        if self.local_v_axis is not None:
            d["local_v_axis"] = list(self.local_v_axis)
        if self.dominant_axis is not None:
            d["dominant_axis"] = list(self.dominant_axis)
        if self.local_n_axis is not None:
            d["local_n_axis"] = list(self.local_n_axis)
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PrimitiveBox:
        known = {
            "type", "confidence", "origin", "size", "detected_via",
            "local_u_axis", "local_v_axis", "dominant_axis", "local_n_axis",
            "face_ids",
        }
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        origin = tuple(float(x) for x in d["origin"]) if "origin" in d else None
        size = tuple(float(x) for x in d["size"]) if "size" in d else None
        u = tuple(float(x) for x in d["local_u_axis"]) if "local_u_axis" in d else None
        v = tuple(float(x) for x in d["local_v_axis"]) if "local_v_axis" in d else None
        dom = tuple(float(x) for x in d["dominant_axis"]) if "dominant_axis" in d else None
        n = tuple(float(x) for x in d["local_n_axis"]) if "local_n_axis" in d else None
        return cls(
            origin=origin,
            size=size,
            confidence=float(d.get("confidence", 0.0)),
            detected_via=d.get("detected_via"),
            local_u_axis=u,
            local_v_axis=v,
            dominant_axis=dom,
            local_n_axis=n,
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class PrimitiveCylinder(IRNode):
    """Cylinder solid primitive defined by origin, radius/diameter, and height."""

    origin: Optional[tuple[float, float, float]] = None
    radius: Optional[float] = None
    height: Optional[float] = None
    axis: Optional[str] = None
    diameter: Optional[float] = None
    confidence: float = 0.0
    detected_via: Optional[str] = None
    extra_fields: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "PrimitiveCylinder",
            "confidence": self.confidence,
        }
        if self.origin is not None:
            d["origin"] = list(self.origin)
        if self.radius is not None:
            d["radius"] = self.radius
        if self.height is not None:
            d["height"] = self.height
        if self.axis is not None:
            d["axis"] = self.axis
        if self.diameter is not None:
            d["diameter"] = self.diameter
        if self.detected_via is not None:
            d["detected_via"] = self.detected_via
        for k, v in self.extra_fields:
            d[k] = v
        if self.face_ids:
            d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PrimitiveCylinder:
        known = {
            "type", "confidence", "origin", "radius", "height", "axis",
            "diameter", "detected_via", "face_ids",
        }
        extras = tuple((k, v) for k, v in d.items() if k not in known)
        origin = tuple(float(x) for x in d["origin"]) if "origin" in d else None
        return cls(
            origin=origin,
            radius=float(d["radius"]) if "radius" in d else None,
            height=float(d["height"]) if "height" in d else None,
            axis=d.get("axis"),
            diameter=float(d["diameter"]) if "diameter" in d else None,
            confidence=float(d.get("confidence", 0.0)),
            detected_via=d.get("detected_via"),
            extra_fields=extras,
            face_ids=tuple(d.get("face_ids", ())),
        )


# ---------------------------------------------------------------------------
# Parameters and Constraints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Parameter(IRNode):
    """Named parametric variable with metadata for OpenSCAD Customizer."""

    name: str = ""
    value: float = 0.0
    raw_value: float = 0.0
    min: Optional[float] = None
    step: Optional[float] = None
    max: Optional[float] = None
    group: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "Parameter",
            "name": self.name,
            "value": self.value,
            "raw_value": self.raw_value,
            "min": self.min,
            "step": self.step,
            "max": self.max,
            "group": self.group,
            "description": self.description,
            "face_ids": list(self.face_ids),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Parameter:
        val = float(d.get("value", 0.0))
        raw_val = float(d.get("raw_value", val))
        min_v = float(d["min"]) if d.get("min") is not None else None
        step_v = float(d["step"]) if d.get("step") is not None else None
        max_v = float(d["max"]) if d.get("max") is not None else None
        return cls(
            name=d.get("name", ""),
            value=val,
            raw_value=raw_val,
            min=min_v,
            step=step_v,
            max=max_v,
            group=d.get("group", ""),
            description=d.get("description", ""),
            face_ids=tuple(d.get("face_ids", ())),
        )


@dataclass(frozen=True)
class Constraint(IRNode):
    """OpenSCAD assert statement expression with an explanatory error message."""

    expression: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "Constraint",
            "expression": self.expression,
            "message": self.message,
            "face_ids": list(self.face_ids),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Constraint:
        return cls(
            expression=d.get("expression", ""),
            message=d.get("message", ""),
            face_ids=tuple(d.get("face_ids", ())),
        )


# ---------------------------------------------------------------------------
# Node Type Registry and Top-Level Dispatcher
# ---------------------------------------------------------------------------


_NODE_REGISTRY: dict[str, type[IRNode]] = {
    "Interpretation": Interpretation,
    "FallbackMesh": FallbackMesh,
    "BooleanUnion": BooleanUnion,
    "BooleanDifference": BooleanDifference,
    "Sketch2D": Sketch2D,
    "SketchLine2D": SketchLine2D,
    "SketchArc2D": SketchArc2D,
    "SketchPath2D": SketchPath2D,
    "ExtrudeLinear": ExtrudeLinear,
    "ExtrudeRevolve": ExtrudeRevolve,
    "TransformTranslate": TransformTranslate,
    "TransformRotate": TransformRotate,
    "TransformMultMatrix": TransformMultMatrix,
    "PatternLinear": PatternLinear,
    "PatternGrid": PatternGrid,
    "HoleThrough": HoleThrough,
    "HoleBlind": HoleBlind,
    "HoleCounterbore": HoleCounterbore,
    "Slot": Slot,
    "RectangularCutout": RectangularCutout,
    "RectangularPocket": RectangularPocket,
    "ChamferOrFilletEdge": ChamferOrFilletEdge,
    "Fillet": Fillet,
    "Boss": Boss,
    "PrimitivePlate": PrimitivePlate,
    "PrimitiveBox": PrimitiveBox,
    "PrimitiveCylinder": PrimitiveCylinder,
    "Parameter": Parameter,
    "Constraint": Constraint,
}


def from_dict(d: Union[dict[str, Any], IRNode]) -> IRNode:
    """Deserialize a dictionary representation of an IR node into a typed dataclass.

    Dispatches on the ``"type"`` field. If *d* is already an ``IRNode``, it is returned
    directly.
    """
    if isinstance(d, IRNode):
        return d
    if not isinstance(d, dict):
        raise TypeError(f"Expected dict or IRNode, got {type(d).__name__}")
    node_type = d.get("type")
    if not node_type:
        raise ValueError("Missing 'type' field in IR node dictionary")
    cls = _NODE_REGISTRY.get(node_type)
    if cls is None:
        raise ValueError(f"Unknown IR node type: {node_type!r}")
    return cls.from_dict(d)


__all__ = [
    "IRNode",
    "Interpretation",
    "FallbackMesh",
    "BooleanUnion",
    "BooleanDifference",
    "Sketch2D",
    "SketchLine2D",
    "SketchArc2D",
    "SketchPath2D",
    "ExtrudeLinear",
    "ExtrudeRevolve",
    "TransformTranslate",
    "TransformRotate",
    "TransformMultMatrix",
    "PatternLinear",
    "PatternGrid",
    "HoleThrough",
    "HoleBlind",
    "HoleCounterbore",
    "Slot",
    "RectangularCutout",
    "RectangularPocket",
    "ChamferOrFilletEdge",
    "Fillet",
    "Boss",
    "PrimitivePlate",
    "PrimitiveBox",
    "PrimitiveCylinder",
    "Parameter",
    "Constraint",
    "from_dict",
]
