import uuid
from datetime import datetime
from typing import Union
from pyspark.sql import DataFrame, functions as F
from delta.tables import DeltaTable
import logging
from pyspark.sql import SparkSession

# Instancia o logger referenciando o nome do módulo
logger = logging.getLogger(__name__)

# Constantes do módulo
DEFAULT_LINES_PER_BATCH = 500
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


# Garante que as tabelas que controle existam
def ensure_control_table(spark: SparkSession, control_table: str) -> None:
    """Creates the control Delta table if it does not already exist."""
    spark.sql(CONTROL_TABLE_DDL.format(control_table=control_table))
    logger.info(f"Control table ready: {control_table}")


# Garante que idempotência da colunas das tabelas
def ensure_metadata_columns(spark: SparkSession, target_table: str) -> None:
    """Adds operational metadata columns to an existing Delta table if they are missing."""
    if not spark.catalog.tableExists(target_table):
        return
    existing_columns = {f.name for f in spark.read.table(target_table).schema.fields}
    metadata_columns = {
        "_ingested_at": "TIMESTAMP",
        "_source_origin": "STRING",
        "_batch_id": "STRING",
    }
    for col_name, col_type in metadata_columns.items():
        if col_name not in existing_columns:
            spark.sql(f"ALTER TABLE {target_table} ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added column '{col_name}' to '{target_table}'")


# Obtém o último id ingerido da tabela previamente
def get_last_processed_id(spark: SparkSession, control_table: str, target_table_name: str) -> int:
    """Retrieves the last processed ID for a given table."""
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


# identifica qual o id máximo atual da tabela alvo
def get_source_max_id(
    spark: SparkSession,
    url: str,
    user: str,
    password: str,
    source_table: str,
    incremental_key: str = DEFAULT_INCREMENTAL_KEY,
) -> int:
    """Queries the current absolute maximum ID from the source via a JDBC query."""
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


# Atualiza a tabela de controle
def update_control_table(spark: SparkSession, control_table: str, target_table_name: str, new_max_id: int):
    """Updates the control table with the new processed ID via Merge."""
    update_data = [(target_table_name, new_max_id, datetime.now())]
    df_update = spark.createDataFrame(update_data, ["source_table", "last_processed_id", "updated_at"])

    delta_control = DeltaTable.forName(spark, control_table)
    delta_control.alias("target").merge(
        df_update.alias("source"), "target.source_table = source.source_table"
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    logger.debug(f"Control table updated: '{target_table_name}' → last_processed_id={new_max_id}")


# Função interna para atualizar/inserir (upsert) na tabela delta
def _merge_into_delta(
    spark: SparkSession,
    df: DataFrame,
    target_table: str,
    pk_cols: list,
) -> None:
    """Upsert df into a Delta table keyed on pk_cols. Creates the table on first run."""
    if not spark.catalog.tableExists(target_table):
        df.write.format("delta").mode("overwrite").saveAsTable(target_table)
        logger.debug(f"Created new Delta table '{target_table}' (first write)")
        return

    merge_condition = " AND ".join([f"t.{col} = s.{col}" for col in pk_cols])
    DeltaTable.forName(spark, target_table).alias("t").merge(
        df.alias("s"), merge_condition
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    logger.debug(f"MERGE into '{target_table}' on [{', '.join(pk_cols)}]")


def run_incremental_ingestion(
    spark: SparkSession,
    table_name: str,
    url: str,
    user: str,
    password: str,
    control_table: str,
    primary_key: Union[str, list] = DEFAULT_INCREMENTAL_KEY,
    lines_per_batch: int = DEFAULT_LINES_PER_BATCH,
    target_catalog_schema: str = DEFAULT_TARGET_CATALOG_SCHEMA,
) -> int:
    """Orchestrates partitioned ingestion consuming external modular blocks.

    Tables with a single primary key (e.g. "id") use incremental watermark pagination.
    Tables with a composite primary key use a full reload + MERGE strategy.
    All writes are idempotent MERGE operations.
    """
    pk_cols = [primary_key] if isinstance(primary_key, str) else list(primary_key)
    use_incremental = len(pk_cols) == 1  # single key → incremental; composite → full reload
    incremental_key = pk_cols[0] if use_incremental else None

    target_catalog_table = f"{target_catalog_schema}.{table_name}"
    ensure_metadata_columns(spark, target_catalog_table)

    jdbc_base_opts = {
        "url": url,
        "user": user,
        "password": password,
        "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
        "encrypt": "true", #True é o padrão atual do JDBC, mas declarar é uma boa prática
        "trustServerCertificate": "true",
        "loginTimeout": "30",
    }

    #Caso tenha mais de uma chave, carrega tabela inteira
    if not use_incremental:
        logger.info(f"Full reload for '{table_name}' | composite pk={pk_cols}")
        df_source = spark.read.format("jdbc").options(**{**jdbc_base_opts, "dbtable": table_name}).load()
        if df_source.isEmpty():
            logger.info(f"No rows found in source for '{table_name}', skipping")
            return 0

        batch_id = str(uuid.uuid4())
        df_with_metadata = (
            df_source.withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_origin", F.lit(table_name))
            .withColumn("_batch_id", F.lit(batch_id))
        )
        _merge_into_delta(spark, df_with_metadata, target_catalog_table, pk_cols)
        row_count = df_source.count()
        logger.info(f"Full reload complete for '{table_name}' | rows={row_count}")
        return row_count

    #Caso tenha somente chame primária, carrega incrementalmente
    absolute_max_id = get_source_max_id(spark, url, user, password, table_name, incremental_key)
    if absolute_max_id == -1:
        logger.info(f"No rows found in source for '{table_name}', skipping")
        return 0

    total_rows_table = 0
    last_id = get_last_processed_id(spark, control_table, table_name)
    logger.info(
        f"Starting incremental ingestion for '{table_name}' | last_id={last_id} | absolute_max_id={absolute_max_id}"
    )

    while True:
        if last_id >= absolute_max_id:
            break

        current_max_id = min(last_id + lines_per_batch, absolute_max_id)
        query_base = (
            f"(SELECT * FROM {table_name} "
            f"WHERE {incremental_key} > {last_id} AND {incremental_key} <= {current_max_id}) as src"
        )

        jdbc_options_batch = {
            **jdbc_base_opts,
            "dbtable": query_base,
            "partitionColumn": incremental_key,
            "lowerBound": str(last_id + 1),
            "upperBound": str(current_max_id),
            "numPartitions": "1",
        }

        df_source = spark.read.format("jdbc").options(**jdbc_options_batch).load()

        if df_source.isEmpty():
            logger.debug(f"Empty batch for '{table_name}' ids {last_id + 1}-{current_max_id}, skipping")
            last_id = current_max_id
            continue

        batch_id = str(uuid.uuid4())
        df_with_metadata = (
            df_source.withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_origin", F.lit(table_name))
            .withColumn("_batch_id", F.lit(batch_id))
        )

        batch_count = current_max_id - last_id
        try:
            df_with_metadata.write.format("delta").mode("append").saveAsTable(target_catalog_table)
            total_rows_table += batch_count
            last_id = current_max_id
            logger.info(f"Batch done: '{table_name}' ids up to {last_id} | rows~{batch_count}")
        except Exception as e:
            logger.error(f"Batch failed for '{table_name}' ids {last_id + 1}-{current_max_id}: {e}")
            raise

    update_control_table(spark, control_table, table_name, last_id)
    logger.info(f"Ingestion complete for '{table_name}' | total_rows~{total_rows_table}")
    return total_rows_table
