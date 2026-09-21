# Databricks notebook source
# MAGIC %md
# MAGIC # 03_create_index — garante o endpoint e o índice vetorial (idempotente)
# MAGIC Task 4 do job `rag_ingestion`: cria o endpoint e o índice se ainda não existirem e
# MAGIC espera ficarem prontos. A sincronização é a task seguinte (`03_sync_index`).
# MAGIC Precisa do corpus COMPLETO em `rag.chunks` antes (capacidade do índice é
# MAGIC provisionada pelo tamanho da tabela fonte na criação).

# COMMAND ----------

# MAGIC %pip install databricks-ai-search
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# Sem valor padrão: o job recebe estes parâmetros do bundle e, ao abrir o notebook na
# interface, o _bootstrap os descobre sozinho a partir do job implantado (sem preencher nada).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema_gold", "")
dbutils.widgets.text("schema_rag", "")

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

# NOTA H6: se o import abaixo falhar, use o pacote antigo:
#   %pip install databricks-vectorsearch
#   from databricks.vector_search.client import VectorSearchClient as AISearchClient
from databricks.ai_search.client import AISearchClient

client = AISearchClient()
vs = CFG.vs

# COMMAND ----------

# 1) Endpoint — no Free Edition só é permitido UM. Criar apenas se não existir.
nomes = [e["name"] for e in client.list_endpoints().get("endpoints", [])]
if vs["endpoint_name"] not in nomes:
    client.create_endpoint(name=vs["endpoint_name"], endpoint_type=vs["endpoint_type"])
    print("endpoint criado:", vs["endpoint_name"])
else:
    print("endpoint já existe:", vs["endpoint_name"])

# COMMAND ----------

# 2) Índice Delta Sync com embeddings gerenciados. Requer CDF na tabela fonte.
#    Idempotente: se já existe, apenas recupera.
try:
    index = client.get_index(index_name=CFG.index_name)
    print("índice já existe:", CFG.index_name)
except Exception:
    index = client.create_delta_sync_index(
        endpoint_name=vs["endpoint_name"],
        source_table_name=CFG.rag("chunks"),
        index_name=CFG.index_name,
        pipeline_type=vs["pipeline_type"],           # TRIGGERED
        primary_key="chunk_id",
        embedding_source_column="texto",
        embedding_model_endpoint_name=vs["embedding_model"],
    )
    print("índice criado:", CFG.index_name)

# COMMAND ----------

# 3) Esperar o endpoint/índice provisionarem antes do primeiro sync.
#    Endpoint STANDARD novo leva ~5-20 min; até lá sync() responde "not ready".
import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
deadline = time.time() + 30 * 60
while time.time() < deadline:
    st = w.vector_search_indexes.get_index(CFG.index_name).status
    if getattr(st, "ready", False):
        print("índice pronto.")
        break
    print("aguardando provisionamento:", getattr(st, "message", ""))
    time.sleep(30)
else:
    raise TimeoutError("índice não ficou pronto em 30 min — verifique o endpoint")
