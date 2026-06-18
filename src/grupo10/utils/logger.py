import logging
import sys

#Manter o severity level em INFO mesmo ou menos verboso com WARNING?
def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Returns a named logger that writes formatted messages to stdout.
    Databricks Job runs capture driver stdout, so logs will appear in the run output.

    Usage:
        from grupo10.utils.logger import get_logger
        logger = get_logger("sqlserver_ingest")
        logger.info("Starting extraction: customers")
        logger.error("Failed: customers — <error>")
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers when the cell is re-run in an interactive session
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
    # Prevent log records from propagating to the root logger (avoids duplicate output)
    logger.propagate = False

    return logger
