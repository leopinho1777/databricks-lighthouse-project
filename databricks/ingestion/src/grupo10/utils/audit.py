"""Audit log for ingestion runs: one Delta row per table run (status, duration, row count, error)."""

from datetime import datetime, timezone
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType, TimestampType

# DDL (data definition language) that creates the audit table idempotently
AUDIT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {audit_table} (
    table_name      STRING    NOT NULL COMMENT 'Source table that was ingested',
    status          STRING    NOT NULL COMMENT 'Outcome: success or failed',
    row_count       LONG               COMMENT 'Number of rows written (null on failure)',
    duration_seconds DOUBLE   NOT NULL COMMENT 'Wall-clock time for the ingestion in seconds',
    error_message   STRING             COMMENT 'Exception message (null on success)',
    ingested_at     TIMESTAMP NOT NULL COMMENT 'UTC timestamp when the record was written'
)
USING DELTA
COMMENT 'Audit log for SQL Server ingestion runs'
"""

#Ensures the audit table exists
def ensure_audit_table(spark: SparkSession, audit_table: str) -> None:
    """Creates the audit Delta table if it does not already exist."""
    spark.sql(AUDIT_TABLE_DDL.format(audit_table=audit_table))

#Writes an ingestion record to the audit table
def write_audit_record(
    spark: SparkSession,
    table_name: str,
    status: str,
    duration_seconds: float,
    audit_table: str,
    row_count: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Appends a single audit record to the Delta audit table.

    Args:
        spark:            Active SparkSession.
        table_name:       Name of the source table that was ingested.
        status:           "success" or "failed".
        duration_seconds: Elapsed wall-clock time for this table.
        row_count:        Rows written; None when the ingestion failed.
        error_message:    Exception message; None on success.
        audit_table:      Fully qualified Delta table name for the audit log.
    """
    
    #PySpark schema of each ingestion record
    schema = StructType(
        [
            StructField("table_name", StringType(), nullable=False),
            StructField("status", StringType(), nullable=False),
            StructField("row_count", LongType(), nullable=True),
            StructField("duration_seconds", DoubleType(), nullable=False),
            StructField("error_message", StringType(), nullable=True),
            StructField("ingested_at", TimestampType(), nullable=False),
        ]
    )

    #Builds the record with the run data
    record = (
        table_name,
        status,
        row_count,
        round(duration_seconds, 3),
        error_message,
        datetime.now(timezone.utc).replace(tzinfo=None),  # Spark TIMESTAMP is tz-naive (stored as naive UTC)
    )

    #Appends the ingestion record to the audit table
    df = spark.createDataFrame([record], schema=schema)
    df.write.format("delta").mode("append").saveAsTable(audit_table)
