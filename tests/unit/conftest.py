"""Shared fixtures for unit tests — no Spark cluster required."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture()
def mock_spark():
    """A MagicMock that mimics a SparkSession for unit tests."""
    spark = MagicMock(name="SparkSession")
    return spark
