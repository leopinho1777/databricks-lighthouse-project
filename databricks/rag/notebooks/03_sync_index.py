# Databricks notebook source
# MAGIC %md
# MAGIC # 03_sync_index — sincroniza o índice (task 3 do job `rag_ingestion`)
# MAGIC Só dispara o sync do índice já criado por `03_create_index`. O Delta Sync
# MAGIC lê o Change Data Feed e reembeda apenas os chunks que mudaram.

# COMMAND ----------

# Defaults para execução INTERATIVA em dev. O job sobrescreve via job parameters.
dbutils.widgets.text("catalog", "develop")
dbutils.widgets.text("schema_gold", "gabriel_analytics_marts")
dbutils.widgets.text("schema_rag", "gabrielhs336_rag")

# COMMAND ----------

# MAGIC %pip install databricks-ai-search
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

from databricks.ai_search.client import AISearchClient

index = AISearchClient().get_index(index_name=CFG.index_name)
index.sync()
print("sync disparado para", CFG.index_name)
