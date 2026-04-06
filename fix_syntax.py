import sys

file_path = "stl2scad/core/verification/metrics.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

bad_str = 'error_msg += f" Log output:\n{lf.read()}"'
good_str = 'error_msg += " Log output:\\n" + lf.read()'

new_content = content.replace(bad_str, good_str)
if new_content != content:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("FIXED")
else:
    print("NOT FOUND")
