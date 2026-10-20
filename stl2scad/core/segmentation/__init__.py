"""Surface segmentation and feature recovery (pipeline steps 1–4)."""

from .features import Feature, Profile, detect_features
from .models import Cylinder, Face, Plane, SegmentationResult
from .pipeline import SegmentationConfig, segment_mesh
from .solid import hausdorff_to_mesh

__all__ = [
    "Cylinder",
    "Face",
    "Feature",
    "Plane",
    "Profile",
    "SegmentationConfig",
    "SegmentationResult",
    "detect_features",
    "hausdorff_to_mesh",
    "segment_mesh",
]
