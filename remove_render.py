import sys
import re

file_path = "stl2scad/core/converter.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

pattern = re.compile(r'def render_stl_preview\(.*?logging\.error\(f"Error generating STL preview: \{str\(e\)\}"\)\n        logging\.debug\("Stack trace:", exc_info=True\)\n', re.DOTALL)

new_content, count = pattern.subn('', content)
if count > 0:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("SUCCESS")
else:
    print("NOT FOUND")
