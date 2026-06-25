# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.4
#   kernelspec:
#     display_name: .venv
#     language: python
#     name: python3
# ---

# %%
# %sql
CREATE CATALOG IF NOT EXISTS lh_nautical;
CREATE SCHEMA IF NOT EXISTS lh_nautical.bronze;

# %%

from grupo10.utils.logger import get_logger
from grupo10.utils.audit import ensure_audit_table, write_audit_record
from grupo10.ingest import ensure_control_table
from databricks.sdk.runtime import spark, dbutils

AUDIT_TABLE   = "lh_nautical.bronze._ingestion_audit"
CONTROL_TABLE = "lh_nautical.bronze._ingestion_control"

logger = get_logger("sqlserver_ingest_setup")
ensure_audit_table(spark, AUDIT_TABLE)
ensure_control_table(spark, CONTROL_TABLE)
logger.info(f"Audit table ready: {AUDIT_TABLE}")
logger.info(f"Control table ready: {CONTROL_TABLE}")

# %%
# Célula 3 (sem alteração)
from databricks.sdk.runtime import dbutils

db_user = dbutils.secrets.get(scope="sqlserver", key="username")
db_password = dbutils.secrets.get(scope="sqlserver", key="password")
db_host = dbutils.secrets.get(scope="sqlserver", key="host")
db_port = dbutils.secrets.get(scope="sqlserver", key="port")
db_database = dbutils.secrets.get(scope="sqlserver", key="db")

jdbc_url = f"jdbc:sqlserver://{db_host}:{db_port};databaseName={db_database}"

# %%
# Célula 4 (adicionado apenas o taskValues.set no final)
import json
import os

#TODO Verificar como configura parametros de jobs -> Isso aqui é um hack para achar a pasta do tabelas_config.json de dentro do Databricks. O padrão ja industria seria colocar esses dados como parametros do Job.
notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
notebook_dir = os.path.dirname(notebook_path)

if not notebook_dir.startswith("/Workspace"):
    notebook_dir = "/Workspace" + notebook_dir

tabelas_config_path = os.path.join(notebook_dir, "tabelas_config.json")

with open(tabelas_config_path, "r", encoding="utf-8") as f:
    target_tables = json.load(f)

#TODO inserir logica para automatizar seleção entre tabelas teste e tabelas reais
# Ingestão usando job parameters. Opções: target_tables, target_tables_test_success, target_tables_test_fail
# O código abaixo só funciona quando o notebook é executado através um Job 
# target_tables = json.loads(dbutils.widgets.get("target_tables_test_success"))

# NOVO: publica a lista para o ForEach task
dbutils.jobs.taskValues.set(key="tables", value=target_tables)
