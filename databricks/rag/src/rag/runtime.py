"""Descobre os parâmetros de ambiente (catalog, schemas, nome do app) do job implantado.

O bundle grava esses valores como parâmetros do job de ingestão em cada deploy (dev: derivados
do usuário; prod: fixos). Notebooks abertos na interface os leem de lá, então ninguém precisa
preencher widgets nem existe nome de pessoa no código.
"""
from __future__ import annotations

JOB_SUFIXO = "LH Nautical RAG - Ingestion"  # em dev o bundle prefixa "[dev <usuário>] "
OBRIGATORIOS = ("catalog", "schema_gold", "schema_rag")
OPCIONAIS = ("app_name",)


def params_do_job_implantado(w, sufixo: str = JOB_SUFIXO) -> dict[str, str]:
    """Parâmetros do job de ingestão implantado neste workspace ({} se não houver).

    Com vários jobs (um por desenvolvedor, em dev), prefere o criado pelo usuário atual.
    """
    eu = w.current_user.me().user_name
    candidatos = [j for j in w.jobs.list() if (j.settings.name or "").endswith(sufixo)]
    candidatos.sort(key=lambda j: j.creator_user_name != eu)
    for j in candidatos:
        params = {p.name: p.default for p in (w.jobs.get(j.job_id).settings.parameters or [])}
        if all(params.get(k) for k in OBRIGATORIOS):
            return {k: params[k] for k in (*OBRIGATORIOS, *OPCIONAIS) if params.get(k)}
    return {}
