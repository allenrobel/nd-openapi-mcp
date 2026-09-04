"""Shared fixture paths for nd-openapi-mcp tests."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def versioned_dir() -> Path:
    """Root containing 1.0.0/, 2.0.0/, and notaversion/."""
    return FIXTURES / "versioned"


@pytest.fixture
def flat_dir() -> Path:
    """Root containing spec files directly, no version subdirectories."""
    return FIXTURES / "flat"
