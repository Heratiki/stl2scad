"""Temporary diagnostic: inspect the 5 high-PSF no-candidate files."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stl2scad.tuning.config import DetectorConfig
from stl2scad.core.feature_graph import build_feature_graph_for_stl

cfg = DetectorConfig()
files = [
    r"D:\3D Files\FDM\Hero Me Gen7 Release V3.2\Gantry Adapters\Linear Rails\Misc Linear Rail Mounts\HMG7 Box Linear Rail X Carriage Top.stl",
    r"D:\3D Files\FDM\Hero Me Gen7 Release V3.2\Gantry Adapters\Linear Rails\Ender 5 Style - Linear Rail - Front Belt\HMG7.3 Box X Carriage Bottom.stl",
    r"D:\3D Files\FDM\Hero Me Gen7 Release V3.2\Gantry Adapters\Micro Swiss\HMG7.2 MSDD Ender 3 Mosquito Creality Gantry Clip.stl",
    r"D:\3D Files\FDM\Hero Me Gen7 Release V3.2\Gantry Adapters\Tevo\HMG7.2 Tevo Tarantula Pro Gantry Clip.stl",
    r"D:\3D Files\FDM\Limit_Switch_Spacer_V1.stl",
]

for fpath in files:
    g = build_feature_graph_for_stl(fpath)
    bbox = g["mesh"]["bounding_box"]
    sa = g["mesh"]["surface_area"]
    w, h, d = bbox["width"], bbox["height"], bbox["depth"]
    nonzero = [v for v in [w, h, d] if v > 1e-9]
    thin_ratio = min(nonzero) / max(nonzero) if len(nonzero) == 3 else 0.0

    pairs = [f for f in g["features"] if f["type"] == "axis_boundary_plane_pair"]
    total_boundary = sum(
        p.get("negative_area", 0) + p.get("positive_area", 0) for p in pairs
    )
    conf = min(total_boundary / sa, 1.0) if sa > 0 else 0.0
    paired_count = sum(1 for p in pairs if p["paired"])

    name = Path(fpath).name
    print(name)
    print(f"  bbox: {w:.1f} x {h:.1f} x {d:.1f} mm")
    print(f"  conf={conf:.3f}  thin_ratio={thin_ratio:.3f}  paired_axes={paired_count}")

    for p in pairs:
        ax = p["axis"]
        na = p.get("negative_area", 0.0)
        pa2 = p.get("positive_area", 0.0)
        pr = p["paired"]
        print(f"    {ax}: neg={na:.1f}  pos={pa2:.1f}  paired={pr}")

    reasons = []
    if paired_count < cfg.plate_paired_axes_min:
        reasons.append(f"paired_axes {paired_count} < min {cfg.plate_paired_axes_min}")
    if conf < cfg.plate_confidence_min:
        reasons.append(f"conf {conf:.3f} < plate_min {cfg.plate_confidence_min}")
    if thin_ratio > cfg.plate_thin_ratio_max:
        reasons.append(f"thin_ratio {thin_ratio:.3f} > plate_max {cfg.plate_thin_ratio_max}")
    if conf < cfg.box_confidence_min:
        reasons.append(f"conf {conf:.3f} < box_min {cfg.box_confidence_min}")
    print(f"  BLOCKING: {reasons}")
    print()
