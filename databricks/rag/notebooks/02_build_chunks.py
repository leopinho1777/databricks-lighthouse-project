# Databricks notebook source
# MAGIC %md
# MAGIC # 02_build_chunks — rag.documents -> rag.chunks
# MAGIC Task 2 do job. Cards viram 1 chunk; documentos escritos são divididos por
# MAGIC cabeçalho/parágrafo/sentença com breadcrumb (§6.4). MERGE idempotente:
# MAGIC os chunks de um doc alterado são apagados e regerados.

# COMMAND ----------

# Defaults para execução INTERATIVA em dev. O job sobrescreve via job parameters.
dbutils.widgets.text("catalog", "develop")
dbutils.widgets.text("schema_gold", "gabriel_analytics_marts")
dbutils.widgets.text("schema_rag", "gabrielhs336_rag")

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

from rag.chunking import CHUNK_DDL, ChunkCfg, chunk_document

chunk_cfg = ChunkCfg.from_config(CFG)
docs = spark.table(CFG.rag("documents")).collect()

registros = []
for d in docs:
    registros.extend(chunk_document(d.asDict(), chunk_cfg))

print("documentos:", len(docs), "| chunks:", len(registros))

# COMMAND ----------

from pyspark.sql import functions as F

# schema explícito: metadados de card ficam nulos quando não há previsão
chunks_df = spark.createDataFrame(registros, CHUNK_DDL)

# validação: nenhum chunk acima do teto (§13.1)
maior = chunks_df.select(F.max(F.length("texto")).alias("m")).first()["m"]
assert maior <= chunk_cfg.max_chars, f"chunk de {maior} caracteres excede {chunk_cfg.max_chars}"
display(chunks_df.select(F.length("texto").alias("tamanho")).summary())

# COMMAND ----------

chunks_df.createOrReplaceTempView("novos_chunks")
spark.sql(f"""
  MERGE INTO {CFG.rag('chunks')} AS c
  USING novos_chunks AS n
    ON c.chunk_id = n.chunk_id
  WHEN MATCHED THEN UPDATE SET *
  WHEN NOT MATCHED THEN INSERT *
  WHEN NOT MATCHED BY SOURCE THEN DELETE
""")

display(spark.sql(f"SELECT count(*) chunks, count(distinct doc_id) docs FROM {CFG.rag('chunks')}"))
