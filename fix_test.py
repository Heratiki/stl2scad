import sys
import re

file_path = "tests/test_verification.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

pattern = re.compile(r'    # Only use STL files small enough to complete.*?    \]', re.DOTALL)

replacement = '''    # Process all STL files for thorough batch verification.
    # OpenSCAD metrics computation is fully implemented and handles failures reliably.
    stl_files = list(test_data_dir.glob("*.stl"))'''

new_content, count = pattern.subn(replacement, content)
if count > 0:
    # Also add the timeout decorator
    content = new_content
    pattern2 = re.compile(r'def test_batch_verification\(test_data_dir, test_output_dir\):')
    new_content, count2 = pattern2.subn('@pytest.mark.timeout(300)\ndef test_batch_verification(test_data_dir, test_output_dir):', content)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"SUCCESS: count={count}, count2={count2}")
else:
    print("NOT FOUND")
