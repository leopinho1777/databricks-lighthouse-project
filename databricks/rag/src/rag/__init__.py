"""Pacote do sistema RAG do projeto LH Nautical.

Camadas online (retrieval -> generation) e utilitários batch (documents,
chunking). Ver a especificação técnica e o README do bundle.
"""

__all__ = [
    "config",
    "documents",
    "chunking",
    "retriever",
    "prompts",
    "generator",
    "observability",
]
