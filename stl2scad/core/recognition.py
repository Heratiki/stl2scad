import numpy as np
import stl
from typing import Optional, Dict

def detect_primitive(mesh: stl.mesh.Mesh, tolerance: float = 0.01) -> Optional[str]:
    """
    Analyzes the mesh topology to detect if it perfectly matches an axis-aligned basic primitive.
    
    Args:
        mesh: The STL mesh to analyze.
        tolerance: Allowable deviation percentage (e.g. 0.01 = 1%).
        
    Returns:
        Optional[str]: Parametric SCAD string if a primitive is detected, otherwise None.
    """
    # Feature 1: Axis-Aligned Bounding Box (Cube)
    min_coords = [float(x) for x in mesh.min_]
    max_coords = [float(x) for x in mesh.max_]
    dimensions = [max_coords[i] - min_coords[i] for i in range(3)]
    width, height, depth = dimensions
    
    # Check volume
    bbox_volume = width * height * depth
    mesh_volume = float(mesh.get_mass_properties()[0])
    
    # If it's a cube, the mesh volume should very closely match the bbox volume.
    if bbox_volume > 0:
        vol_diff_ratio = abs(mesh_volume - bbox_volume) / bbox_volume
        if vol_diff_ratio <= tolerance:
            # It's an axis-aligned cube!
            scad_code = (
                f"translate([{min_coords[0]:.6f}, {min_coords[1]:.6f}, {min_coords[2]:.6f}]) "
                "{\n"
                f"    cube([{width:.6f}, {height:.6f}, {depth:.6f}]);\n"
                "}\n"
            )
            return scad_code
            
    # Add Cylinder/Sphere detection in Phase 1.5 if needed
    
    return None
