# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.4
# ---

# %% vscode={"languageId": "sql"}
# %sql

--Cria catalog e schema
CREATE CATALOG IF NOT EXISTS lh_nautical;
CREATE SCHEMA IF NOT EXISTS lh_nautical.bronze;

# %%
from grupo10.utils.logger import get_logger
from grupo10.utils.audit import ensure_audit_table, write_audit_record
from grupo10.ingest import ensure_control_table, run_incremental_ingestion
#Databricks ja importa spark globalmente, mas pylance no VSC grita se não importar deliberadamente.
from databricks.sdk.runtime import spark

#TODO definir a a string do nome da tabela de audit em outro local e referenciar aqui?
#O underline antes do nome da tabela de auditoria de ingestão é uma convenção para dizer que ela é interna, ou seja, não é uma tabela do negócio em si
AUDIT_TABLE = "lh_nautical.bronze._ingestion_audit"
CONTROL_TABLE = "lh_nautical.bronze._ingestion_control"


logger = get_logger("sqlserver_ingest")
ensure_audit_table(spark, AUDIT_TABLE)
ensure_control_table(spark, CONTROL_TABLE)
logger.info(f"Audit table ready: {AUDIT_TABLE}")
logger.info(f"Control table ready: {CONTROL_TABLE}")

# %%
# Isolando a infraestrutura de conexão
from databricks.sdk.runtime import dbutils

db_user = dbutils.secrets.get(scope="sqlserver", key="username")
db_password = dbutils.secrets.get(scope="sqlserver", key="password")
db_host = dbutils.secrets.get(scope="sqlserver", key="host")
db_port = dbutils.secrets.get(scope="sqlserver", key="port")
db_database = dbutils.secrets.get(scope="sqlserver", key="db")

jdbc_url = f"jdbc:sqlserver://{db_host}:{db_port};databaseName={db_database}"

# %%
import json
import os

#TODO Verificar como configura parametros de jobs -> Isso aqui é um hack para achar a pasta do tabelas_config.json de dentro do Databricks. O padrão ja industria seria colocar esses dados como parametros do Job.

#Encontra o  '/Users/user@company.com/grupo_10/src/sqlserver_ingest'
notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
#Remove o nome do notebook para obter o '/Users/user@company.com/grupo_10/src'
notebook_dir = os.path.dirname(notebook_path)

#Adiciona o Workspace para obtermos o '/Workspace/Users/user@company.com/grupo_10/src'
if not notebook_dir.startswith("/Workspace"):
    notebook_dir = "/Workspace" + notebook_dir

#Adiciona o tabelas config para fica '/Workspace/Users/user@company.com/grupo_10/src/tabelas_config.json'
tabelas_config_path = os.path.join(notebook_dir, "tabelas_config.json")

with open(tabelas_config_path, "r", encoding="utf-8") as f:
    target_tables = json.load(f)

#TODO inserir logica para automatizar seleção entre tabelas teste e tabelas reais
# Ingestão usando job parameters. Opções: target_tables, target_tables_test_success, target_tables_test_fail
# O código abaixo só funciona quando o notebook é executado através um Job 
# target_tables = json.loads(dbutils.widgets.get("target_tables_test_success"))

# %%
import time
from databricks.sdk.runtime import spark

failed_tables = []

for table in target_tables:
    start = time.time()
    try:
        logger.info(f"Starting incremental ingestion: {table}")

        row_count = run_incremental_ingestion(
            spark=spark,
            table_name=table,
            url=jdbc_url,
            user=db_user,
            password=db_password,
            control_table=CONTROL_TABLE,
            lines_per_batch=1000,
        )

        duration = time.time() - start
        logger.info(f"Done: {table} | rows~{row_count} | duration={duration:.2f}s")

        write_audit_record(
            spark=spark,
            table_name=table,
            status="success",
            duration_seconds=duration,
            row_count=row_count,
            audit_table=AUDIT_TABLE,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error(f"Failed: {table} | duration={duration:.2f}s | error={e}")
        failed_tables.append(table)

        write_audit_record(
            spark=spark,
            table_name=table,
            status="failed",
            duration_seconds=duration,
            error_message=str(e),
            audit_table=AUDIT_TABLE,
        )

if failed_tables:
    logger.warning(f"Ingestion finished with {len(failed_tables)} failure(s): {failed_tables}")
else:
    logger.info("All tables ingested successfully.")
