import logging
import sys

#Manter o severity level em INFO mesmo ou menos verboso com WARNING?
def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Retorna um logger nomeado que envia mensagens formatadas para stdout

    Como usar:
        from grupo10.utils.logger import get_logger
        logger = get_logger("sqlserver_ingest")
        logger.info("Starting extraction: customers")
        logger.error("Failed: customers — <error>")
    """
    #Idempotência
    logger = logging.getLogger(name)

    # Evitar que mais de um handler seja anexado ao logger em caso de sessões interativas
    #Idempotência
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
    #TODO precisa mesmo evitar a propagação na estrutura atual do nosso projeto? Como o databricks iria tratar este log caso a propadação não estivesse 'False'
    logger.propagate = True

    return logger
