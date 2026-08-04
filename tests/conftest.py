"""Pytest configuration."""

from pathlib import Path

import pytest

from . import checked
from .configuration import TEST_TMP_CACHE, clear_test_cache


@pytest.fixture
def fix_test_cache() -> Path:
    """Fixture to clear and return the test cache directory for use.

    Returns:
        Path: Path to the test cache directory

    """
    clear_test_cache()
    return TEST_TMP_CACHE


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A throwaway project, with the working directory moved into it.

    Everything a checker resolves is relative to the project root, so the chdir is what makes
    ``checked.reported`` behave the way a real run does.
    """
    root = checked.lay_out(tmp_path)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def examples_project(tmp_path, monkeypatch) -> Path:
    """The same, plus the repo's own ``examples/`` copied in so its templates can be checked."""
    root = checked.lay_out(tmp_path, examples=True)
    monkeypatch.chdir(root)
    return root
