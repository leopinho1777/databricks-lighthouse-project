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

# %%
from grupo10.utils.logger import get_logger
from grupo10.utils.audit import write_audit_record
from grupo10.ingest import run_incremental_ingestion
import time
from databricks.sdk.runtime import spark

# %%

logger = get_logger("sqlserver_ingest_single")
AUDIT_TABLE   = "lh_nautical.bronze._ingestion_audit"
CONTROL_TABLE = "lh_nautical.bronze._ingestion_control"

db_user = dbutils.secrets.get(scope="lh_nautical", key="lh_nautical_sqlserver_user")
db_password = dbutils.secrets.get(scope="lh_nautical", key="lh_nautical_sqlserver_password")
db_host = dbutils.secrets.get(scope="lh_nautical", key="lh_nautical_sqlserver_host")
db_port = dbutils.secrets.get(scope="lh_nautical", key="lh_nautical_sqlserver_port")
db_database = dbutils.secrets.get(scope="lh_nautical", key="lh_nautical_sqlserver_database")

jdbc_url = f"jdbc:sqlserver://{db_host}:{db_port};databaseName={db_database}"
# -----------------------------------------------------

# %%

dbutils.widgets.text("table_name", "")

table = dbutils.widgets.get("table_name")  
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
        lines_per_batch=10,
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

    write_audit_record(
        spark=spark,
        table_name=table,
        status="failed",
        duration_seconds=duration,
        error_message=str(e),
        audit_table=AUDIT_TABLE,
    )
    raise  
