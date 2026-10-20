"""Surface segmentation (pipeline steps 1–3), independent of feature detection."""

from .models import Cylinder, Face, Plane, SegmentationResult
from .pipeline import SegmentationConfig, segment_mesh

__all__ = [
    "Cylinder",
    "Face",
    "Plane",
    "SegmentationConfig",
    "SegmentationResult",
    "segment_mesh",
]
