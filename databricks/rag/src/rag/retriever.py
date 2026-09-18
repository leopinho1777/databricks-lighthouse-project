"""Recuperação: busca híbrida no Vector Search, corte por score, dedup e formatação.

NOTA H6: a spec usa `databricks-ai-search` / `AISearchClient`. Se o workspace
tiver o pacote antigo, troque por:
    from databricks.vector_search.client import VectorSearchClient
    self._index = VectorSearchClient().get_index(endpoint_name=..., index_name=...)
A interface `similarity_search(...)` é equivalente.
"""
from __future__ import annotations

from dataclasses import dataclass

COLUNAS = [
    "chunk_id", "doc_id", "doc_type", "titulo", "texto",
    "produto_id", "loja_id", "cd_id", "periodo", "fonte", "atualizado_em",
]


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    titulo: str
    texto: str
    fonte: str
    atualizado_em: str
    score: float


class Retriever:
    def __init__(self, cfg):
        self.cfg = cfg
        self.r = cfg.retrieval
        # import tardio: mantém o pacote importável fora do Databricks (testes)
        from databricks.ai_search.client import AISearchClient  # type: ignore

        client = AISearchClient()  # auto-detecta o PAT do contexto (notebook/job)
        self._index = client.get_index(index_name=cfg.index_name)

    def search(self, pergunta: str, filtros: dict | None = None) -> list[Chunk]:
        res = self._index.similarity_search(
            query_text=pergunta,
            columns=COLUNAS,
            num_results=self.r["num_results"],
            query_type=self.r["query_type"],  # HYBRID
            filters=filtros or None,
        )
        return self._pos_processar(self._parse(res))

    @staticmethod
    def _parse(res: dict) -> list[Chunk]:
        """Mapeia data_array pelo manifest -- nunca por posição fixa."""
        nomes = [c["name"] for c in res["manifest"]["columns"]]
        saida: list[Chunk] = []
        for linha in res["result"].get("data_array", []):
            d = dict(zip(nomes, linha))
            saida.append(
                Chunk(
                    chunk_id=d["chunk_id"],
                    doc_id=d["doc_id"],
                    doc_type=d["doc_type"],
                    titulo=d["titulo"],
                    texto=d["texto"],
                    fonte=d["fonte"],
                    atualizado_em=str(d["atualizado_em"]),
                    score=float(d.get("score", linha[-1])),
                )
            )
        return saida

    def _pos_processar(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return []
        corte = chunks[0].score * self.r["relative_score_threshold"]
        vistos: dict[str, int] = {}
        saida: list[Chunk] = []
        for c in chunks:
            if c.score < corte:
                break  # lista já vem ordenada por score desc
            if vistos.get(c.doc_id, 0) >= self.r["max_chunks_per_doc"]:
                continue
            vistos[c.doc_id] = vistos.get(c.doc_id, 0) + 1
            saida.append(c)
            if len(saida) == self.r["final_k"]:
                break
        return saida
