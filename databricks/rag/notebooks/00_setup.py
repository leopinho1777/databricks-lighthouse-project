# Databricks notebook source
# MAGIC %md
# MAGIC # 00_setup — schema e tabelas do RAG
# MAGIC Roda **1x** (ou quando o schema muda). Cria o schema `rag` e as 5 tabelas.
# MAGIC Nenhuma tabela do DW é tocada.

# COMMAND ----------

# Sem valor padrão: o job recebe estes parâmetros do bundle e, ao abrir o notebook na
# interface, o _bootstrap os descobre sozinho a partir do job implantado (sem preencher nada).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema_gold", "")
dbutils.widgets.text("schema_rag", "")

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

cat, rag = CFG.catalog, CFG.schema_rag

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {cat}.{rag}")

# COMMAND ----------

# documents — unidade lógica de conhecimento, antes do fatiamento (§5.1)
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CFG.rag('documents')} (
  doc_id STRING NOT NULL,
  doc_type STRING, titulo STRING, corpo STRING,
  produto_id STRING, produto_nome STRING,
  loja_id STRING, loja_nome STRING,
  cd_id STRING, cd_nome STRING,
  periodo STRING, fonte STRING,
  content_hash STRING, atualizado_em TIMESTAMP,
  CONSTRAINT documents_pk PRIMARY KEY (doc_id)
)
""")

# COMMAND ----------

# chunks — unidade de recuperação. Change Data Feed é REQUISITO do índice (§5.2)
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CFG.rag('chunks')} (
  chunk_id STRING NOT NULL, doc_id STRING, chunk_index INT, texto STRING,
  doc_type STRING, titulo STRING, produto_id STRING, produto_nome STRING,
  loja_id STRING, loja_nome STRING, cd_id STRING, cd_nome STRING,
  periodo STRING, fonte STRING, atualizado_em TIMESTAMP,
  CONSTRAINT chunks_pk PRIMARY KEY (chunk_id)
) TBLPROPERTIES (delta.enableChangeDataFeed = true)
""")

# COMMAND ----------

# query_logs — append-only, escrita pelo notebook de chat (§5.4)
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CFG.rag('logs')} (
  log_id STRING, ts TIMESTAMP, pergunta STRING,
  chunk_ids ARRAY<STRING>, scores ARRAY<DOUBLE>,
  n_chunks_recuperados INT, n_chunks_usados INT,
  modelo_llm STRING, modelo_embedding STRING,
  resposta STRING, recusou BOOLEAN,
  latencia_retrieval_ms INT, latencia_llm_ms INT, erro STRING
)
""")

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CFG.rag('eval_questions')} (
  pergunta_id STRING, pergunta STRING, categoria STRING,
  chunk_ids_esperados ARRAY<STRING>, resposta_esperada STRING, deve_recusar BOOLEAN
)
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CFG.rag('eval_results')} (
  run_id STRING, ts TIMESTAMP, pergunta_id STRING,
  recall_at_k DOUBLE, precision_at_k DOUBLE, mrr DOUBLE, hit BOOLEAN,
  fidelidade DOUBLE, correto BOOLEAN, resposta_gerada STRING, config_json STRING
)
""")

# COMMAND ----------

display(spark.sql(f"SHOW TABLES IN {cat}.{CFG.schema_rag}"))
