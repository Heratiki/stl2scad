"""Skip the legacy test directory unless STL2SCAD_LEGACY_TESTS=1 (T-003)."""

import os

import pytest

_ENABLED = os.environ.get("STL2SCAD_LEGACY_TESTS") == "1"


def pytest_collection_modifyitems(config, items):
    if _ENABLED:
        return
    skip = pytest.mark.skip(reason="legacy tests; set STL2SCAD_LEGACY_TESTS=1 to run")
    for item in items:
        if "tests/legacy/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(skip)
