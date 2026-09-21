# Databricks notebook source
# MAGIC %md
# MAGIC # _bootstrap
# MAGIC Coloca `src/` no `sys.path` e resolve os parâmetros de ambiente.
# MAGIC Rode com `%run ./_bootstrap` no início dos outros notebooks.

# COMMAND ----------

import os
import sys
from pathlib import Path


def _add_src_to_path() -> Path:
    here = Path.cwd()
    for base in [here, *here.parents]:
        if (base / "src" / "rag").is_dir():
            sys.path.insert(0, str(base / "src"))
            return base
        if (base / "databricks" / "rag" / "src" / "rag").is_dir():
            sys.path.insert(0, str(base / "databricks" / "rag" / "src"))
            return base / "databricks" / "rag"
    raise RuntimeError("Não encontrei src/rag a partir de %s" % here)


BUNDLE_ROOT = _add_src_to_path()

# Parâmetros de ambiente -> variáveis RAG_* lidas por rag.config.Config.load().
# Ordem: 1) widgets (o job os recebe do bundle); 2) variáveis já definidas;
# 3) parâmetros do job implantado (uso interativo: nada a preencher).
_PARAMS = ("catalog", "schema_gold", "schema_rag", "app_name")
_valores = {}
for _w in _PARAMS:
    try:
        _valores[_w] = dbutils.widgets.get(_w)  # noqa: F821
    except Exception:
        _valores[_w] = ""  # widget não definido neste notebook
    _valores[_w] = _valores[_w] or os.environ.get("RAG_" + _w.upper(), "")

if not all(_valores[k] for k in _PARAMS[:3]):
    from databricks.sdk import WorkspaceClient
    from rag.runtime import params_do_job_implantado

    _do_job = params_do_job_implantado(WorkspaceClient())
    for _w in _PARAMS:
        _valores[_w] = _valores[_w] or _do_job.get(_w, "")

_faltando = [k for k in _PARAMS[:3] if not _valores[k]]
if _faltando:
    raise RuntimeError(
        "Não encontrei o job 'LH Nautical RAG - Ingestion' implantado neste workspace, "
        "então não sei o catálogo/schemas (" + ", ".join(_faltando) + "). "
        "Faça o deploy do bundle (databricks bundle deploy) e tente novamente."
    )

for _w, _v in _valores.items():
    if _v:
        os.environ["RAG_" + _w.upper()] = _v

os.environ.setdefault("RAG_CONFIG", str(BUNDLE_ROOT / "config" / "rag_config.yaml"))

from rag.config import Config  # noqa: E402

CFG = Config.load()
print("catalog:", CFG.catalog, "| schema_gold:", CFG.raw["schema_gold"],
      "| schema_rag:", CFG.schema_rag)
