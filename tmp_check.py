import sys
from pathlib import Path
from stl2scad.core.converter import stl2scad
from stl2scad.core.verification import verify_existing_conversion

# Set paths
base_dir = Path("c:/Users/herat/source/stl2scad")
stl_file = base_dir / "tests/data/Stanford_Bunny_sample.stl"
scad_file = base_dir / ".tmp_bunny.scad"

# Convert
print("Converting...")
stl2scad(str(stl_file), str(scad_file))

# Verify
print("Verifying...")
result = verify_existing_conversion(
    stl_file,
    scad_file,
    tolerance={
        'volume': 5.0,
        'surface_area': 10.0,
        'bounding_box': 2.0
    }
)

print(f"Passed: {result.passed}")
import json
print(json.dumps(result.comparison, indent=2))
if not result.passed:
    print("FAILED METRICS:")
    # We can inspect where the percentage is over tolerance
    for metric, data in result.comparison.items():
        if isinstance(data, dict):
            if 'difference_percent' in data:
                print(f"{metric}: diff {data['difference_percent']}%")
            if metric == 'bounding_box':
                for dim, dim_data in data.items():
                    if 'difference_percent' in dim_data:
                        print(f"  bbox {dim}: diff {dim_data['difference_percent']}%")
