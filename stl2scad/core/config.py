"""
Configuration settings for the STL to OpenSCAD converter.

This module handles loading, saving, and accessing configuration settings for the converter.
It provides type-safe access to configuration values and handles platform-specific paths.
"""

import os
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List, TypedDict, Union, cast

class Win32Paths(TypedDict):
    """Windows-specific OpenSCAD paths configuration."""
    base: str  # Base installation directory
    exe: str   # GUI executable name
    com: str   # Command-line executable name

class OpenSCADPaths(TypedDict):
    """Platform-specific OpenSCAD paths configuration."""
    win32: Win32Paths
    linux: List[str]
    darwin: List[str]

class OpenSCADConfig(TypedDict):
    """OpenSCAD-specific configuration."""
    required_version: str
    paths: OpenSCADPaths

class Config(TypedDict):
    """Complete configuration structure."""
    openscad: OpenSCADConfig

# Default configuration with proper typing
DEFAULT_CONFIG: Config = {
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

class ConfigError(Exception):
    """Base class for configuration-related errors."""
    pass

class ConfigLoadError(ConfigError):
    """Raised when configuration cannot be loaded."""
    pass

class ConfigSaveError(ConfigError):
    """Raised when configuration cannot be saved."""
    pass

def get_config_path() -> Path:
    """
    Get the path to the configuration file.
    
    Returns:
        Path: Platform-specific path to the configuration file
        
    Notes:
        - Windows: %APPDATA%/stl2scad/config.json
        - Unix/Mac: ~/.config/stl2scad/config.json
    """
    if sys.platform == "win32":
        config_dir = Path(os.getenv("APPDATA", "")) / "stl2scad"
    else:
        config_dir = Path.home() / ".config" / "stl2scad"
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

def load_config() -> Config:
    """
    Load configuration from file or create with defaults if not exists.
    
    Returns:
        Config: Complete configuration dictionary
        
    Raises:
        ConfigLoadError: If configuration cannot be loaded or created
    """
    config_path = get_config_path()
    
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config_data = json.load(f)
                # Merge with defaults to ensure all required keys exist
                merged = DEFAULT_CONFIG.copy()
                merged["openscad"].update(config_data.get("openscad", {}))
                return cast(Config, merged)
        except Exception as e:
            raise ConfigLoadError(f"Error loading config: {e}") from e
    else:
        # Create default config file
        try:
            with open(config_path, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except Exception as e:
            raise ConfigLoadError(f"Error creating config file: {e}") from e
    
    return DEFAULT_CONFIG

def save_config(config: Config) -> None:
    """
    Save configuration to file.
    
    Args:
        config: Complete configuration dictionary
        
    Raises:
        ConfigSaveError: If configuration cannot be saved
    """
    config_path = get_config_path()
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        raise ConfigSaveError(f"Error saving config: {e}") from e

def get_openscad_config() -> OpenSCADConfig:
    """
    Get OpenSCAD-specific configuration.
    
    Returns:
        OpenSCADConfig: OpenSCAD configuration section
        
    Raises:
        ConfigLoadError: If configuration cannot be loaded
    """
    config = load_config()
    return config["openscad"]

def get_required_version() -> str:
    """
    Get required OpenSCAD version.
    
    Returns:
        str: Required OpenSCAD version string (YYYY.MM.DD format)
        
    Raises:
        ConfigLoadError: If configuration cannot be loaded
    """
    return get_openscad_config()["required_version"]

def get_openscad_paths() -> OpenSCADPaths:
    """
    Get platform-specific OpenSCAD paths.
    
    Returns:
        OpenSCADPaths: Dictionary of platform-specific paths
        
    Raises:
        ConfigLoadError: If configuration cannot be loaded
    """
    return get_openscad_config()["paths"]

def update_openscad_path(path: str) -> None:
    """
    Update OpenSCAD path in configuration.
    
    Args:
        path: New path to OpenSCAD executable or base directory
        
    Raises:
        ConfigLoadError: If configuration cannot be loaded
        ConfigSaveError: If configuration cannot be saved
    """
    config = load_config()
    if sys.platform == "win32":
        config["openscad"]["paths"]["win32"]["base"] = path
    else:
        platform = sys.platform
        if platform not in config["openscad"]["paths"]:
            paths = cast(Dict[str, List[str]], config["openscad"]["paths"])
            paths[platform] = []
        platform_paths = cast(Dict[str, List[str]], config["openscad"]["paths"])[platform]
        if path not in platform_paths:
            platform_paths.insert(0, path)
    save_config(config)

def update_required_version(version: str) -> None:
    """
    Update required OpenSCAD version in configuration.
    
    Args:
        version: New required version string (YYYY.MM.DD format)
        
    Raises:
        ConfigLoadError: If configuration cannot be loaded
        ConfigSaveError: If configuration cannot be saved
    """
    config = load_config()
    config["openscad"]["required_version"] = version
    save_config(config)
