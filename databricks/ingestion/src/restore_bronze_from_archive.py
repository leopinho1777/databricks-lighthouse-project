# Databricks notebook source
# Notebook: restore_bronze_from_archive
# Purpose: Rebuilds the Bronze tables from an archive in a Unity Catalog volume: creates each table
#          from its DDL file, then loads its parquet file. Re-runnable (CREATE OR REPLACE).

import shutil
import time
from pathlib import Path

from databricks.sdk.runtime import dbutils, spark
from grupo10.restore import rewrite_ddl
from grupo10.utils.logger import get_logger

# COMMAND ----------

# Parameters: target location and the volume folder holding the ddl/ and parquet/ subfolders
dbutils.widgets.text("catalog", "lh_nautical")
dbutils.widgets.text("schema", "bronze")
dbutils.widgets.text("archive_path", "/Volumes/lh_nautical/bronze/archive/sqlserver_bronze")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
archive_path = Path(dbutils.widgets.get("archive_path"))
ddl_dir = archive_path / "ddl"
parquet_dir = archive_path / "parquet"
staging_dir = archive_path / "parquet_staging"

logger = get_logger("restore_bronze_from_archive")

spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

if not ddl_dir.is_dir() or not parquet_dir.is_dir():
    raise FileNotFoundError(f"Expected ddl/ and parquet/ under {archive_path}; upload the archive first")

# COMMAND ----------


def parquet_source(table: str) -> Path:
    """Returns the parquet path for a table; Spark ignores names starting with '_', so those are staged under a visible name."""
    source = parquet_dir / f"{table}.parquet"
    if not table.startswith("_"):
        return source
    staging_dir.mkdir(exist_ok=True)
    staged = staging_dir / f"internal{table}.parquet"
    shutil.copyfile(source, staged)
    return staged


# COMMAND ----------

# Restores one table per DDL file; a failure is recorded and the loop continues so one bad table
# does not leave the rest half-restored. Failures are raised together after the loop.
results = []
failures = []

for ddl_file in sorted(ddl_dir.glob("*.sql")):
    table = ddl_file.stem
    target = f"{catalog}.{schema}.{table}"
    start = time.time()
    try:
        # Create (or replace) the empty table from its DDL, with the target catalog/schema
        spark.sql(rewrite_ddl(ddl_file.read_text(encoding="utf-8"), catalog, schema))

        # Load the archived rows; saveAsTable in append mode matches columns by name
        df = spark.read.parquet(str(parquet_source(table)))
        expected = df.count()
        df.write.format("delta").mode("append").saveAsTable(target)

        # Verify the table holds exactly the archived rows
        actual = spark.table(target).count()
        if actual != expected:
            raise ValueError(f"row count mismatch: parquet={expected} table={actual}")

        results.append((table, expected, round(time.time() - start, 1)))
        logger.info(f"Restored {target} | rows={actual}")
    except Exception as e:  # noqa: BLE001 - recorded and re-raised after the loop
        failures.append((table, str(e)))
        logger.error(f"Failed {target}: {e}")

# COMMAND ----------

# Summary of what was restored and what failed
for table, rows, seconds in results:
    print(f"{table:<28} {rows:>10} rows  {seconds:>6}s")
print(f"\nRestored {len(results)} tables, {len(failures)} failed")

if failures:
    raise RuntimeError("Restore failed for: " + "; ".join(f"{t} ({err})" for t, err in failures))
