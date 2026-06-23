"""Unit tests for grupo10.utils.logger — no cluster required."""

import logging
from grupo10.utils.logger import get_logger


def test_get_logger_returns_logger():
    logger = get_logger("test_logger_type")
    assert isinstance(logger, logging.Logger)


def test_get_logger_name_matches():
    logger = get_logger("test_logger_name")
    assert logger.name == "test_logger_name"


def test_get_logger_default_level_is_info():
    logger = get_logger("test_logger_level")
    assert logger.level == logging.INFO


def test_get_logger_custom_level():
    logger = get_logger("test_logger_debug", level=logging.DEBUG)
    assert logger.level == logging.DEBUG


def test_get_logger_idempotent_no_duplicate_handlers():
    """Calling get_logger twice for the same name should not add extra handlers."""
    name = "test_logger_idempotent"
    logger_first = get_logger(name)
    handler_count_after_first = len(logger_first.handlers)

    logger_second = get_logger(name)
    assert len(logger_second.handlers) == handler_count_after_first


def test_get_logger_has_stream_handler():
    import sys

    logger = get_logger("test_logger_handler")
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) >= 1
    assert stream_handlers[0].stream is sys.stdout
