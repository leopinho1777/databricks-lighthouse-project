"""Logging helper: named loggers with a consistent stdout format for the pipeline."""

import logging
import sys

#Builds a custom logger
def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Returns a named logger that writes formatted messages to stdout.

    Usage:
        from grupo10.utils.logger import get_logger
        logger = get_logger("sqlserver_ingest")
        logger.info("Starting extraction: customers")
        logger.error("Failed: customers — <error>")
    """
    logger = logging.getLogger(name)

    # Avoid attaching more than one handler to the logger in interactive sessions
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = True

    return logger
