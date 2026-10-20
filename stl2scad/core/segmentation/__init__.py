"""Surface segmentation, sketch/feature recovery and gated editable SCAD."""

from .features import Feature, Profile, ProfileSegment, detect_features
from .emit import emit_scad, gate_limit_mm
from .models import Cylinder, Face, Plane, SegmentationResult
from .pipeline import SegmentationConfig, segment_mesh
from .solid import hausdorff_to_mesh

__all__ = [
    "Cylinder",
    "Face",
    "Feature",
    "Plane",
    "Profile",
    "ProfileSegment",
    "SegmentationConfig",
    "SegmentationResult",
    "detect_features",
    "emit_scad",
    "gate_limit_mm",
    "hausdorff_to_mesh",
    "segment_mesh",
]
