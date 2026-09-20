"""Registro de cada interação em rag.query_logs (append-only). Fire-and-forget:
observabilidade nunca derruba a resposta ao usuário.
"""
from __future__ import annotations

import uuid


def _sql_str(v) -> str:
    return "'" + str(v or "").replace("'", "''") + "'"


class QueryLogger:
    def __init__(self, cfg, warehouse_id: str):
        self.tabela = cfg.rag("logs")
        self.warehouse_id = warehouse_id
        from databricks.sdk import WorkspaceClient  # import tardio (testes)

        self.w = WorkspaceClient()

    def log(self, **e) -> None:
        chunk_ids = ", ".join(_sql_str(c) for c in e.get("chunk_ids", []))
        scores = ", ".join(str(float(s)) for s in e.get("scores", []))
        erro = e.get("erro")
        sql = f"""
            INSERT INTO {self.tabela} VALUES (
              {_sql_str(uuid.uuid4())}, current_timestamp(), {_sql_str(e.get('pergunta'))},
              array({chunk_ids}), array({scores}),
              {int(e.get('n_recuperados', 0))}, {int(e.get('n_usados', 0))},
              {_sql_str(e.get('modelo_llm'))}, {_sql_str(e.get('modelo_embedding'))},
              {_sql_str(e.get('resposta'))}, {str(bool(e.get('recusou'))).lower()},
              {int(e.get('lat_retrieval_ms', 0))}, {int(e.get('lat_llm_ms', 0))},
              {'NULL' if not erro else _sql_str(erro)}
            )"""
        try:
            self.w.statement_execution.execute_statement(
                statement=sql, warehouse_id=self.warehouse_id, wait_timeout="0s"
            )
        except Exception:  # noqa: BLE001 -- nunca propaga
            pass
