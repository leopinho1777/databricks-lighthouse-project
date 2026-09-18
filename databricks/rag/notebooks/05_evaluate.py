# Databricks notebook source
# MAGIC %md
# MAGIC # 05_evaluate — avaliação de retrieval e generation (§14)
# MAGIC Roda o dataset dourado (`rag.eval_questions`) e grava em `rag.eval_results`.
# MAGIC Critérios de sucesso: correção numérica = 1,00 · recusa correta = 1,00 ·
# MAGIC Hit Rate@5 >= 0,90.

# COMMAND ----------

# MAGIC %pip install databricks-ai-search "databricks-sdk[openai]" openai
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# Defaults para execução INTERATIVA em dev.
dbutils.widgets.text("catalog", "develop")
dbutils.widgets.text("schema_gold", "gabriel_analytics_marts")
dbutils.widgets.text("schema_rag", "gabrielhs336_rag")

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

import json
import time
import uuid

from rag.generator import Generator
from rag.retriever import Retriever

retriever, generator = Retriever(CFG), Generator(CFG)
run_id = str(uuid.uuid4())
K = CFG.retrieval["final_k"]

perguntas = spark.table(CFG.rag("eval_questions")).collect()
linhas = []

for q in perguntas:
    chunks = retriever.search(q.pergunta)
    ids = [c.chunk_id for c in chunks]
    esperados = set(q.chunk_ids_esperados or [])

    hit = bool(esperados & set(ids))
    recall = len(esperados & set(ids)) / len(esperados) if esperados else None
    precision = (len(esperados & set(ids)) / len(ids)) if ids else None
    mrr = next((1 / (i + 1) for i, cid in enumerate(ids) if cid in esperados), 0.0)

    resposta, _ = generator.answer(q.pergunta, chunks)
    recusou = resposta.startswith("Não encontrei")
    correto = recusou if q.deve_recusar else (not recusou)

    linhas.append((
        run_id, None, q.pergunta_id, recall, precision, mrr, hit,
        None, bool(correto), resposta,
        json.dumps(CFG.retrieval, ensure_ascii=False),
    ))

# COMMAND ----------

from pyspark.sql import functions as F

schema = ("run_id string, ts timestamp, pergunta_id string, recall_at_k double, "
          "precision_at_k double, mrr double, hit boolean, fidelidade double, "
          "correto boolean, resposta_gerada string, config_json string")
res = spark.createDataFrame(linhas, schema).withColumn("ts", F.current_timestamp())
res.write.mode("append").saveAsTable(CFG.rag("eval_results"))

# COMMAND ----------

display(res.select(
    F.avg(F.col("hit").cast("int")).alias("hit_rate"),
    F.avg("recall_at_k").alias("recall_medio"),
    F.avg("mrr").alias("mrr_medio"),
    F.avg(F.col("correto").cast("int")).alias("taxa_correta"),
))
