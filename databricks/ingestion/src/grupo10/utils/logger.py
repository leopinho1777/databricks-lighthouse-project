import logging
import sys

#Cria um logger customizado
def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Retorna um logger nomeado que envia mensagens formatadas para stdout

    Como usar:
        from grupo10.utils.logger import get_logger
        logger = get_logger("sqlserver_ingest")
        logger.info("Starting extraction: customers")
        logger.error("Failed: customers — <error>")
    """
    logger = logging.getLogger(name)

    # Evitar que mais de um handler seja anexado ao logger em caso de sessões interativas
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
