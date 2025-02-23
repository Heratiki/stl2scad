"""
Utility functions for STL2SCAD tests.
"""

import os
import sys
import logging
import subprocess
from pathlib import Path
from datetime import datetime

def setup_logging(log_file="test_run.log"):
    """Setup test logging with timestamps."""
    def log(msg, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] {level}: {msg}"
        print(log_msg, flush=True)
        with open(log_file, 'a') as f:
            f.write(f"{log_msg}\n")

    # Clear previous log
    with open(log_file, 'w') as f:
        f.write("=== Starting Test ===\n")
    
    return log

def check_openscad_processes():
    """Check for running OpenSCAD processes."""
    import psutil
    openscad_procs = [p for p in psutil.process_iter(['name']) 
                      if p.info['name'] and 'openscad' in p.info['name'].lower()]
    if openscad_procs:
        print(f"Found {len(openscad_procs)} OpenSCAD processes running")
        for proc in openscad_procs:
            print(f"OpenSCAD process: PID={proc.pid}")
        return True
    return False

def verify_debug_files(debug_files):
    """Verify debug files were created and have content."""
    files_status = {}
    for name, path in debug_files.items():
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        files_status[name] = {
            'exists': exists,
            'size': size,
            'status': "[OK]" if exists and size > 0 else "[MISSING]"
        }
    return files_status

def format_file_status(files_status):
    """Format file status for logging."""
    output = []
    for name, status in files_status.items():
        output.append(f"{name}: {status['status']} ({status['size']:,} bytes)")
        if not status['exists'] or status['size'] == 0:
            output.append(f"Warning: {name} file is missing or empty")
    return "\n".join(output)