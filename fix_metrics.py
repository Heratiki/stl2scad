import sys
import re

file_path = "stl2scad/core/verification/metrics.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Pattern for the first block: if not success or not temp_stl.exists():
pattern1 = re.compile(r'        if not success or not temp_stl\.exists\(\):\n            return \{\n                \'volume\': None,\n                \'surface_area\': None,\n                \'bounding_box\': None,\n                \'mesh\': None\n            \}')

replacement1 = '''        if not success or not temp_stl.exists():
            error_msg = "OpenSCAD rendering failed."
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as lf:
                    error_msg += f" Log output:\\n{lf.read()}"
            raise RuntimeError(f"Failed to calculate SCAD metrics: {error_msg}")'''

# Pattern for the second block: except Exception: return { None }
pattern2 = re.compile(r'        except Exception:\n            return \{\n                \'volume\': None,\n                \'surface_area\': None,\n                \'bounding_box\': None,\n                \'mesh\': None\n            \}')

replacement2 = '''        except Exception as e:
            raise RuntimeError(f"Failed to calculate SCAD metrics after rendering: {str(e)}")'''

new_content1, count1 = pattern1.subn(replacement1, content)
new_content2, count2 = pattern2.subn(replacement2, new_content1)

if count1 > 0 and count2 > 0:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content2)
    print("SUCCESS")
else:
    print(f"NOT FOUND: count1={count1}, count2={count2}")
