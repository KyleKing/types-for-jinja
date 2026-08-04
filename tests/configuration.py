"""Global variables for testing."""

import os
import shutil
from pathlib import Path

import pytest
from corallium.file_helpers import delete_dir, ensure_dir


def requires_checker(name: str) -> pytest.MarkDecorator:
    """Skip when ``name`` is absent, unless ``TYPES_FOR_JINJA_REQUIRE_CHECKERS`` demands it be present.

    CI sets that variable so a missing checker fails the suite rather than silently skipping it.
    """
    return pytest.mark.skipif(
        shutil.which(name) is None and not os.environ.get('TYPES_FOR_JINJA_REQUIRE_CHECKERS'),
        reason=f'{name} is required',
    )


TEST_DIR = Path(__file__).resolve().parent
"""Path to the `test` directory that contains this file and all other tests."""

TEST_DATA_DIR = TEST_DIR / 'data'
"""Path to subdirectory with test data within the Test Directory."""

TEST_TMP_CACHE = TEST_DIR / '_tmp_cache'
"""Path to the temporary cache folder in the Test directory."""


def clear_test_cache() -> None:
    """Remove the test cache directory if present."""
    delete_dir(TEST_TMP_CACHE)
    ensure_dir(TEST_TMP_CACHE)
