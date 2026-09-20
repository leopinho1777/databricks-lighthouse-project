"""Chamada ao LLM via Foundation Model APIs. Sem credencial no código (§8, §11.2)."""
from __future__ import annotations

import time

from . import prompts


class Generator:
    def __init__(self, cfg):
        self.cfg = cfg
        # Autenticação resolvida pelo ambiente: PAT automático no notebook/job.
        # Nenhum segredo no código.
        from databricks.sdk import WorkspaceClient  # import tardio (testes)

        self.client = WorkspaceClient().serving_endpoints.get_open_ai_client()

    def answer(self, pergunta: str, chunks) -> tuple[str, int]:
        """Devolve (resposta, latencia_ms). Sem contexto, o LLM NÃO é chamado."""
        if not chunks:
            return prompts.SEM_CONTEXTO, 0

        t0 = time.time()
        kwargs = dict(
            model=self.cfg.llm["endpoint"],
            messages=prompts.build_messages(pergunta, chunks),
            temperature=self.cfg.llm["temperature"],
            max_tokens=self.cfg.llm["max_tokens"],
        )
        # seed melhora (não garante) reprodutibilidade em endpoints MoE.
        seed = self.cfg.llm.get("seed")
        if seed is not None:
            kwargs["seed"] = int(seed)
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content, int((time.time() - t0) * 1000)
