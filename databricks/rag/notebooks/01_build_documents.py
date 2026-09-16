# Databricks notebook source
# MAGIC %md
# MAGIC # 01_build_documents — tabelas gold -> rag.documents
# MAGIC Task 1 do job `rag_ingestion`. Templates determinísticos + docs/*.md.
# MAGIC MERGE idempotente por `doc_id` + `content_hash` (§6.2).

# COMMAND ----------

# Defaults para execução INTERATIVA em dev. O job sobrescreve via job parameters.
dbutils.widgets.text("catalog", "develop")
dbutils.widgets.text("schema_gold", "gabriel_analytics_marts")
dbutils.widgets.text("schema_rag", "gabrielhs336_rag")

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

from rag import documents as D

frames = []

# --- cards numéricos (dependem da Fase 1: fct_forecast materializada) ----------
try:
    frames.append(D.build_previsao_produto_loja(spark, CFG))  # HIPÓTESE H2
except Exception as e:
    print("previsao_produto_loja pulado:", e)

try:
    frames.append(D.build_dicionario_dados(spark, CFG))
except Exception as e:
    print("dicionario_dados pulado:", e)

# --- documentos curados do repositório ---------------------------------------
docs_dir = str(BUNDLE_ROOT / "docs")
frames.append(D.load_markdown_docs(spark, CFG, docs_dir))

# COMMAND ----------

from functools import reduce

df = reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), frames)
print("documentos gerados:", df.count())
display(df.select("doc_id", "doc_type", "titulo", "fonte").orderBy("doc_type"))

# COMMAND ----------

D.upsert_documents(spark, CFG, df)
display(spark.sql(f"SELECT doc_type, count(*) n FROM {CFG.rag('documents')} GROUP BY doc_type ORDER BY doc_type"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Inspeção manual (§ roadmap Fase 3): leia 10 documentos gerados.

# COMMAND ----------

for r in spark.sql(f"SELECT titulo, corpo FROM {CFG.rag('documents')} LIMIT 10").collect():
    print("=" * 80)
    print(r.titulo)
    print("-" * 80)
    print(r.corpo[:1500])
