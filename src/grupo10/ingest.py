import uuid
from datetime import datetime
from pyspark.sql import functions as F
from delta.tables import DeltaTable
import logging
from pyspark.sql import SparkSession


logger = logging.getLogger(__name__)

DEFAULT_LINES_PER_BATCH = 100
DEFAULT_TARGET_CATALOG_SCHEMA = "lh_nautical.bronze"
DEFAULT_INCREMENTAL_KEY = "id"
CONTROL_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {control_table} (
    source_table        STRING    NOT NULL COMMENT 'Source table being ingested',
    last_processed_id   LONG      NOT NULL COMMENT 'Last incremental key value successfully processed',
    updated_at          TIMESTAMP NOT NULL COMMENT 'UTC timestamp of the last update'
)
USING DELTA
COMMENT 'Incremental ingestion control state'
"""


def ensure_control_table(spark: SparkSession, control_table: str) -> None:
    """Creates the control Delta table if it does not already exist."""
    spark.sql(CONTROL_TABLE_DDL.format(control_table=control_table))
    logger.info(f"Control table ready: {control_table}")


def get_last_processed_id(spark: SparkSession, control_table: str, target_table_name: str) -> int:
    """Recupera o último ID processado para uma tabela informada."""
    if not spark.catalog.tableExists(control_table):
        logger.debug(f"Control table '{control_table}' does not exist yet, starting from -1")
        return -1

    df_control = spark.read.table(control_table).filter(F.col("source_table") == target_table_name)

    if df_control.isEmpty():
        logger.debug(f"No control record found for '{target_table_name}', starting from -1")
        return -1

    last_id = df_control.select("last_processed_id").collect()[0][0]
    logger.debug(f"Resuming '{target_table_name}' from last_processed_id={last_id}")
    return last_id


def get_source_max_id(
    spark: SparkSession,
    url: str,
    user: str,
    password: str,
    source_table: str,
    incremental_key: str = DEFAULT_INCREMENTAL_KEY,
) -> int:
    """Consulta o ID máximo absoluto atual na origem via query JDBC leve."""
    jdbc_options_max = {
        "url": url,
        "dbtable": f"(SELECT MAX({incremental_key}) as max_id FROM {source_table}) as src",
        "user": user,
        "password": password,
        "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
        "encrypt": "true",
        "trustServerCertificate": "true",
        "loginTimeout": "30",
    }
    df_max = spark.read.format("jdbc").options(**jdbc_options_max).load()
    row = df_max.collect()[0]
    max_id = row["max_id"] if row["max_id"] is not None else -1
    logger.debug(f"Source max {incremental_key} for '{source_table}': {max_id}")
    return max_id


def update_control_table(spark: SparkSession, control_table: str, target_table_name: str, new_max_id: int):
    """Atualiza a tabela de controle com o novo ID processado via Merge."""
    update_data = [(target_table_name, new_max_id, datetime.now())]
    df_update = spark.createDataFrame(update_data, ["source_table", "last_processed_id", "updated_at"])

    delta_control = DeltaTable.forName(spark, control_table)
    delta_control.alias("target").merge(
        df_update.alias("source"), "target.source_table = source.source_table"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    logger.debug(f"Control table updated: '{target_table_name}' → last_processed_id={new_max_id}")


def run_incremental_ingestion(
    spark: SparkSession,
    table_name: str,
    url: str,
    user: str,
    password: str,
    control_table: str,
    lines_per_batch: int = DEFAULT_LINES_PER_BATCH,
    incremental_key: str = DEFAULT_INCREMENTAL_KEY,
    target_catalog_schema: str = DEFAULT_TARGET_CATALOG_SCHEMA,
) -> int:
    """Orquestra a ingestão particionada consumindo os blocos modulares externos."""
    target_catalog_table = f"{target_catalog_schema}.{table_name}"

    # 1. Busca o ID máximo absoluto na origem
    absolute_max_id = get_source_max_id(spark, url, user, password, table_name, incremental_key)
    if absolute_max_id == -1:
        logger.info(f"No rows found in source for '{table_name}', skipping")
        return 0

    total_rows_table = 0

    # 2. Laço de repetição contínuo para processar de 100 em 100
    last_id = get_last_processed_id(spark, control_table, table_name)
    logger.info(
        f"Starting incremental ingestion for '{table_name}' | last_id={last_id} | absolute_max_id={absolute_max_id}"
    )

    while True:
        if last_id >= absolute_max_id:
            break

        current_max_id = min(last_id + lines_per_batch, absolute_max_id)
        query_base = f"(SELECT * FROM {table_name} WHERE {incremental_key} > {last_id} AND {incremental_key} <= {current_max_id}) as src"

        jdbc_options_batch = {
            "url": url,
            "dbtable": query_base,
            "user": user,
            "password": password,
            "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
            "encrypt": "true",
            "trustServerCertificate": "true",
            "loginTimeout": "30",
            "partitionColumn": incremental_key,
            "lowerBound": str(last_id + 1),
            "upperBound": str(current_max_id),
            "numPartitions": "1",
        }

        df_source = spark.read.format("jdbc").options(**jdbc_options_batch).load()

        if df_source.isEmpty():
            logger.debug(f"Empty batch for '{table_name}' ids {last_id + 1}-{current_max_id}, skipping")
            update_control_table(spark, control_table, table_name, current_max_id)
            continue

        # Metadados operacionais
        batch_id = str(uuid.uuid4())
        df_with_metadata = (
            df_source.withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_origin", F.lit(table_name))
            .withColumn("_batch_id", F.lit(batch_id))
        )

        # Escrita incremental acumulativa (Modo Append)
        batch_count = (
            current_max_id - last_id
        )  # Aproximação. Reduz número de acesso ao banco de dados oa invés de dar count() no df_with_metadata)
        try:
            df_with_metadata.write.format("delta").mode("append").saveAsTable(target_catalog_table)
            update_control_table(spark, control_table, table_name, current_max_id)
            total_rows_table += batch_count
            last_id = current_max_id
            logger.info(f"Batch done: '{table_name}' ids up to {last_id} | rows~{batch_count}")
        except Exception as e:
            logger.error(f"Batch failed for '{table_name}' ids {last_id + 1}-{current_max_id}: {e}")
            raise

    logger.info(f"Ingestion complete for '{table_name}' | total_rows~{total_rows_table}")
    return total_rows_table
