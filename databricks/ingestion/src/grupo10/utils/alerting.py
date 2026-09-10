"""Daily run history and consecutive-failure streaks, used to alert only after repeated failures."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import DateType, StringType, StructField, StructType, TimestampType

# DDL that creates the run-history table idempotently
RUN_HISTORY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {run_history_table} (
    task_name   STRING    NOT NULL COMMENT 'Task being tracked for consecutive-failure alerting',
    run_date    DATE      NOT NULL COMMENT 'Calendar date (UTC) of the scheduled run',
    status      STRING    NOT NULL COMMENT 'Outcome: success or failed',
    recorded_at TIMESTAMP NOT NULL COMMENT 'UTC timestamp when the record was written'
)
USING DELTA
COMMENT 'Daily run outcomes used to gate consecutive-failure alerts'
"""


def ensure_run_history_table(spark: SparkSession, run_history_table: str) -> None:
    """Creates the run-history Delta table if it does not already exist."""
    spark.sql(RUN_HISTORY_TABLE_DDL.format(run_history_table=run_history_table))


def record_run_result(
    spark: SparkSession,
    run_history_table: str,
    task_name: str,
    status: str,
    run_date: Optional[date] = None,
) -> None:
    """Upserts today's outcome for `task_name`, keyed by (task_name, run_date) so reruns on the same day don't inflate the streak."""
    from delta.tables import DeltaTable

    run_date = run_date or datetime.now(timezone.utc).date()
    schema = StructType(
        [
            StructField("task_name", StringType(), nullable=False),
            StructField("run_date", DateType(), nullable=False),
            StructField("status", StringType(), nullable=False),
            StructField("recorded_at", TimestampType(), nullable=False),
        ]
    )
    record = (task_name, run_date, status, datetime.now(timezone.utc).replace(tzinfo=None))
    df_update = spark.createDataFrame([record], schema=schema)

    if not spark.catalog.tableExists(run_history_table):
        df_update.write.format("delta").mode("append").saveAsTable(run_history_table)
        return

    DeltaTable.forName(spark, run_history_table).alias("target").merge(
        df_update.alias("source"),
        "target.task_name = source.task_name AND target.run_date = source.run_date",
    ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()


def get_consecutive_failure_streak(
    spark: SparkSession,
    run_history_table: str,
    task_name: str,
    as_of: Optional[date] = None,
) -> int:
    """Counts consecutive daily failures for `task_name` ending on `as_of` (defaults to today), stopping at the first day that succeeded or has no record."""
    if not spark.catalog.tableExists(run_history_table):
        return 0

    as_of = as_of or datetime.now(timezone.utc).date()
    history = {
        row["run_date"]: row["status"]
        for row in spark.read.table(run_history_table)
        .filter(F.col("task_name") == task_name)
        .select("run_date", "status")
        .collect()
    }

    streak = 0
    day = as_of
    while history.get(day) == "failed":
        streak += 1
        day -= timedelta(days=1)
    return streak
