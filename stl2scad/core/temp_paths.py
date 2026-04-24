"""Temporary path helpers that avoid Windows tempfile directory ACL issues."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Iterator


@contextmanager
def temporary_directory(prefix: str = "tmp") -> Iterator[Path]:
    """Create a temporary directory with normal Path.mkdir semantics."""
    base_dir = Path(os.environ.get("STL2SCAD_TEMP_DIR") or tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)

    for _ in range(100):
        path = base_dir / f"{prefix}-{uuid.uuid4().hex[:12]}"
        try:
            path.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(
            f"Could not create a unique temporary directory in {base_dir}"
        )

    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
