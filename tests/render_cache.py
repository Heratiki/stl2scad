"""Content-addressed cache for the OpenSCAD renders that tests make (T-016).

Key: SHA-256 of the SCAD text (plus every file it `use`s or `include`s), the
OpenSCAD version string and the render arguments without the input and output
paths. Env: STL2SCAD_RENDER_CACHE is a directory, or "off" to disable it;
STL2SCAD_RENDER_CACHE_LOG names a file that gets one line per call:
"render miss <name>" or "render hit <name>".
"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from stl2scad.core.openscad.runner import run_openscad

DEFAULT_CACHE_DIR = Path(__file__).parent / ".render_cache"
RENDER_COUNT = 0  # real OpenSCAD renders made by this process

_DEPENDENCY = re.compile(r"^\s*(?:use|include)\s*<([^>]+)>", re.M)
_UNCACHEABLE = re.compile(r"\b(?:import|surface)\s*\(")
_VERSIONS: dict = {}


def cache_dir() -> Optional[Path]:
    """The cache directory, or None when the cache is off."""
    value = os.environ.get("STL2SCAD_RENDER_CACHE", "")
    if value.lower() == "off":
        return None
    return Path(value) if value else DEFAULT_CACHE_DIR


def _openscad_version(openscad_path: Optional[str]) -> str:
    exe = openscad_path or "openscad"
    if exe not in _VERSIONS:
        result = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=30
        )
        _VERSIONS[exe] = (result.stdout + result.stderr).strip()
    return _VERSIONS[exe]


def _scad_closure(scad_path: Path, seen: set) -> Optional[List[str]]:
    """The text of a SCAD file and its dependencies; None if not cacheable."""
    path = scad_path.resolve()
    if path in seen:
        return []
    seen.add(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if _UNCACHEABLE.search(text):
        return None
    parts = [text]
    for name in _DEPENDENCY.findall(text):
        dep = path.parent / name
        if not dep.is_file():
            return None
        sub = _scad_closure(dep, seen)
        if sub is None:
            return None
        parts.extend(sub)
    return parts


def _key(args, scad_path: Path, openscad_path: Optional[str]) -> Optional[str]:
    parts = _scad_closure(scad_path, set())
    if parts is None:
        return None
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8") + b"\0")
    digest.update(_openscad_version(openscad_path).encode("utf-8") + b"\0")
    for arg in args:
        digest.update(str(arg).encode("utf-8") + b"\0")
    return digest.hexdigest()


def _note(kind: str, name: str) -> None:
    log = os.environ.get("STL2SCAD_RENDER_CACHE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"render {kind} {name}\n")


def cached_render(
    name: str,
    args: List[str],
    scad_path,
    stl_path,
    log_path,
    openscad_path: Optional[str] = None,
    timeout: int = 30,
) -> bool:
    """Render scad_path to stl_path, or copy the cached STL of an identical render.

    `args` are the render options only (for example ["--render", "-D", "a=1"]);
    the helper appends "-o <stl_path> <scad_path>". Returns what run_openscad
    returns. A failed render stores nothing.
    """
    global RENDER_COUNT
    scad_path, stl_path = Path(scad_path), Path(stl_path)
    directory = cache_dir()
    key = _key(args, scad_path, openscad_path) if directory is not None else None
    command = list(args) + ["-o", str(stl_path), str(scad_path)]
    cached = directory / f"{key}.stl" if key else None
    if cached is not None and cached.is_file():
        shutil.copyfile(cached, stl_path)
        Path(log_path).write_text(f"render cache hit: {name}\n", encoding="utf-8")
        _note("hit", name)
        return True
    ok = run_openscad(name, command, str(log_path), openscad_path, timeout=timeout)
    RENDER_COUNT += 1
    _note("miss", name)
    if ok and cached is not None and stl_path.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        os.close(fd)
        try:
            shutil.copyfile(stl_path, temp)
            os.replace(temp, cached)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return ok
