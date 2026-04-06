import sys
import re

file_path = "stl2scad/core/converter.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

pattern = re.compile(r'    for i, face in enumerate\(quantized_vectors\):\n        for j in range\(3\):', re.DOTALL)

replacement = '''    for i, face in enumerate(quantized_vectors):
        if len(set(tuple(p) for p in face)) < 3:
            continue
        for j in range(3):'''

new_content, count = pattern.subn(replacement, content)
if count > 0:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("SUCCESS")
else:
    print("NOT FOUND")
