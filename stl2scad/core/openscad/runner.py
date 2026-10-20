"""
OpenSCAD process helpers: locate a valid OpenSCAD build and run it.

Moved out of the legacy converter by T-004 so live code (segmentation,
verification) does not depend on the archived legacy pipeline. Signatures and
the Windows "OpenSCAD (Nightly)" install-path check are unchanged.
"""

import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple

from .. import config


def run_openscad(
    description: str,
    args: List[str],
    log_file: str,
    openscad_path: Optional[str] = None,
    timeout: int = 30,
) -> bool:
    """Execute OpenSCAD command with proper error handling and logging.

    Args:
        description: Description of the command being executed
        args: List of command arguments
        log_file: Path to the log file
        openscad_path: Optional path to OpenSCAD executable
        timeout: Command timeout in seconds

    Returns:
        bool: True if command executed successfully, False otherwise
    """
    logging.info(f"Executing OpenSCAD: {description}")
    logging.debug(f"Command arguments: {args}")
    logging.debug(f"Log file path: {log_file}")
    logging.debug(f"Command timeout: {timeout} seconds")
    logging.debug(f"OpenSCAD path: {openscad_path or 'default'}")

    try:
        command = [openscad_path or "openscad"] + args
        logging.info(f"Executing command: {' '.join(str(c) for c in command)}")

        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )

        # Always write output to log file so callers (e.g. version check) can read it
        with open(log_file, "w", encoding="utf-8") as f:
            if result.stdout:
                f.write(result.stdout)
            if result.stderr:
                f.write(result.stderr)

        if result.stdout:
            logging.debug(f"Command output: {result.stdout}")
        if result.stderr:
            logging.warning(f"Command stderr: {result.stderr}")

        if result.returncode != 0:
            logging.error(f"Command failed with exit code {result.returncode}.")
            return False

        logging.info("Command completed successfully")
        return True

    except subprocess.TimeoutExpired:
        logging.error(
            f"Command timed out after {timeout} seconds. This may indicate that OpenSCAD is having trouble processing the file or the system is under heavy load."
        )
        return False
    except Exception as e:
        logging.error(f"Unexpected error executing OpenSCAD: {str(e)}")
        logging.debug("Stack trace:", exc_info=True)
        return False



def get_openscad_path() -> Optional[str]:
    """Get OpenSCAD executable path and verify version requirements.

    Returns:
        Optional[str]: Path to OpenSCAD executable if found and valid, None otherwise
    """

    def check_version(path: str) -> Tuple[bool, str]:
        """Check if OpenSCAD at path is nightly build with required version.

        Args:
            path: Path to OpenSCAD executable

        Returns:
            Tuple[bool, str]: (is_valid, message)
        """
        try:
            logging.info(f"Checking OpenSCAD version at: {path}")
            args = ["--info"]
            # Use a temp file so the log doesn't litter the working directory
            tmp_fd, log_file = tempfile.mkstemp(
                suffix=".log", prefix="openscad_version_"
            )
            os.close(tmp_fd)

            try:
                if not run_openscad("Version check", args, log_file, path):
                    logging.error("Failed to run OpenSCAD version check")
                    return False, "Failed to run version check"

                # Read version info from log
                with open(log_file, "r", encoding="utf-8") as f:
                    info = f.read().strip()
            finally:
                try:
                    os.unlink(log_file)
                except OSError:
                    pass
            logging.debug(f"Raw OpenSCAD info: {info}")

            # Clean up the info string
            info = " ".join(info.split())
            logging.debug(f"Cleaned version info: {info}")

            # Extract version number (matches YYYY.MM.DD or YYYY.MM)
            version_match = re.search(r"Version:\s*(\d{4}\.\d{2}(?:\.\d{2})?)", info)
            logging.debug(
                f"Version match: {version_match.group(1) if version_match else 'No match'}"
            )

            # Check installation path
            logging.debug(f"Checking installation path: {path}")
            if sys.platform == "win32" and "OpenSCAD (Nightly)" not in path:
                logging.error("OpenSCAD not installed in Nightly directory")
                return False, "Not installed in OpenSCAD (Nightly) directory"

            if not version_match:
                logging.error("Could not determine OpenSCAD version from output")
                return False, "Could not determine version"

            version = version_match.group(1)
            required_version = config.get_required_version()
            logging.info(f"Detected OpenSCAD version: {version}")
            # Compare versions using tuples for proper semantic versioning
            version_tuple = tuple(map(int, version.split(".")))
            required_tuple = tuple(map(int, required_version.split(".")))
            if version_tuple < required_tuple:
                logging.error(
                    f"OpenSCAD version {version} is older than required {required_version}"
                )
                return (
                    False,
                    f"Version {version} is older than required {required_version}",
                )

            logging.info(
                f"OpenSCAD version check passed: {version} >= {required_version}"
            )
            return True, info
        except subprocess.CalledProcessError as e:
            logging.error(f"OpenSCAD command failed with return code {e.returncode}")
            if e.stdout:
                logging.debug(f"Command output: {e.stdout}")
            if e.stderr:
                logging.error(f"Error details: {e.stderr}")
            return False, f"Error checking version: {e}"
        except Exception as e:
            logging.error(f"Unexpected error checking OpenSCAD version: {str(e)}")
            logging.debug("Stack trace:", exc_info=True)
            return False, f"Error checking version: {str(e)}"

    paths_config = config.get_openscad_paths()
    if sys.platform == "win32":
        base_path = paths_config["win32"]["base"]
        exe_path = os.path.join(
            base_path, paths_config["win32"]["exe"]
        )  # For GUI operations
        com_path = os.path.join(
            base_path, paths_config["win32"]["com"]
        )  # For command-line operations

        if not (os.path.exists(exe_path) and os.path.exists(com_path)):
            raise FileNotFoundError(
                "OpenSCAD (Nightly) not found. Please install OpenSCAD (Nightly) version "
                f"{config.get_required_version()} or later from "
                "https://openscad.org/downloads.html#snapshots. The regular OpenSCAD release does not "
                "support the required debug features."
            )

        # Verify version
        is_valid, message = check_version(com_path)
        if not is_valid:
            raise FileNotFoundError(
                f"Invalid OpenSCAD version: {message}. Please install OpenSCAD (Nightly) version "
                f"{config.get_required_version()} or later from "
                "https://openscad.org/downloads.html#snapshots"
            )

        return com_path  # Return the .com path for command-line operations
    else:
        # For non-Windows systems
        platform_paths: list[str] = paths_config.get(sys.platform, [])  # type: ignore[assignment]
        for path in platform_paths:
            if os.path.exists(path):
                is_valid, message = check_version(path)
                if is_valid:
                    return path
                print(
                    f"Warning: Found OpenSCAD at {path} but {message}", file=sys.stderr
                )

        raise FileNotFoundError(
            "OpenSCAD (Nightly) not found. Please install OpenSCAD (Nightly) version "
            f"{config.get_required_version()} or later from "
            "https://openscad.org/downloads.html#snapshots"
        )

