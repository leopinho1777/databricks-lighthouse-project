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

# Parâmetros: widgets do job (catalog/schema_gold/schema_rag) -> variáveis de ambiente
# lidas por rag.config.Config.load().
try:
    for _w in ("catalog", "schema_gold", "schema_rag"):
        _v = dbutils.widgets.get(_w)  # noqa: F821
        if _v:
            os.environ["RAG_" + _w.upper()] = _v
except Exception:
    pass  # rodando interativo, sem widgets: usa o rag_config.yaml como está

os.environ.setdefault("RAG_CONFIG", str(BUNDLE_ROOT / "config" / "rag_config.yaml"))

from rag.config import Config  # noqa: E402

CFG = Config.load()
print("catalog:", CFG.catalog, "| schema_gold:", CFG.raw["schema_gold"],
      "| schema_rag:", CFG.schema_rag)
