# Databricks notebook source
# MAGIC %md
# MAGIC # 03_sync_index — sincroniza o índice (task 3 do job `rag_ingestion`)
# MAGIC Só dispara o sync do índice já criado por `03_create_index`. O Delta Sync
# MAGIC lê o Change Data Feed e reembeda apenas os chunks que mudaram.

# COMMAND ----------

# Sem valor padrão: o job recebe estes parâmetros do bundle e, ao abrir o notebook na
# interface, o _bootstrap os descobre sozinho a partir do job implantado (sem preencher nada).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema_gold", "")
dbutils.widgets.text("schema_rag", "")

# COMMAND ----------

# MAGIC %pip install databricks-ai-search
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

from databricks.ai_search.client import AISearchClient

import time

index = AISearchClient().get_index(index_name=CFG.index_name)

# O sync só é aceito quando o pipeline do índice está parado (COMPLETED/FAILED/CANCELED).
# Logo após criar o índice, ou se uma sincronização anterior ainda roda, ele responde
# "not ready to sync": esperamos e tentamos de novo, em vez de falhar.
prazo = time.time() + 30 * 60
while True:
    try:
        index.sync()
        print("sync disparado para", CFG.index_name)
        break
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if any(t in msg for t in ("already", "in progress", "ongoing")):
            print("sincronização já em andamento para", CFG.index_name)
            break
        if "not ready" in msg and time.time() < prazo:
            print("índice ainda ocupado, aguardando 30 s:", str(e)[:120])
            time.sleep(30)
            continue
        raise
