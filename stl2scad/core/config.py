"""
Configuration settings for the STL to OpenSCAD converter.
"""

import os
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_CONFIG = {
    "openscad": {
        "required_version": "2025.02.19",
        "paths": {
            "win32": {
                "base": r"C:\Program Files\OpenSCAD (Nightly)",
                "exe": "openscad.exe",  # For GUI operations
                "com": "openscad.com"   # For command-line operations
            },
            "linux": ["/usr/bin/openscad", "/usr/local/bin/openscad"],
            "darwin": ["/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"]
        }
    }
}

def get_config_path() -> Path:
    """Get the path to the configuration file."""
    if sys.platform == "win32":
        config_dir = Path(os.getenv("APPDATA", "")) / "stl2scad"
    else:
        config_dir = Path.home() / ".config" / "stl2scad"
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

def load_config() -> Dict[str, Any]:
    """Load configuration from file or create with defaults if not exists."""
    config_path = get_config_path()
    
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                # Merge with defaults to ensure all required keys exist
                merged = DEFAULT_CONFIG.copy()
                merged["openscad"].update(config.get("openscad", {}))
                return merged
        except Exception as e:
            print(f"Error loading config: {e}. Using defaults.", file=sys.stderr)
            return DEFAULT_CONFIG
    else:
        # Create default config file
        try:
            with open(config_path, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except Exception as e:
            print(f"Error creating config file: {e}", file=sys.stderr)
    
    return DEFAULT_CONFIG

def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file."""
    config_path = get_config_path()
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}", file=sys.stderr)

def get_openscad_config() -> Dict[str, Any]:
    """Get OpenSCAD-specific configuration."""
    config = load_config()
    return config["openscad"]

def get_required_version() -> str:
    """Get required OpenSCAD version."""
    return get_openscad_config()["required_version"]

def get_openscad_paths() -> Dict[str, Any]:
    """Get platform-specific OpenSCAD paths."""
    return get_openscad_config()["paths"]

def update_openscad_path(path: str) -> None:
    """Update OpenSCAD path in configuration."""
    config = load_config()
    if sys.platform == "win32":
        config["openscad"]["paths"]["win32"]["base"] = path
    else:
        platform = sys.platform
        if platform not in config["openscad"]["paths"]:
            config["openscad"]["paths"][platform] = []
        if path not in config["openscad"]["paths"][platform]:
            config["openscad"]["paths"][platform].insert(0, path)
    save_config(config)

def update_required_version(version: str) -> None:
    """Update required OpenSCAD version in configuration."""
    config = load_config()
    config["openscad"]["required_version"] = version
    save_config(config)
