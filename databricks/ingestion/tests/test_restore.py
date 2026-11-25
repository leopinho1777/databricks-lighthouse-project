"""Unit tests for grupo10.restore.rewrite_ddl (pure Python, no Spark needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grupo10.restore import rewrite_ddl

# Shape copied from the archived DDL files (columns, collation, table properties)
ARCHIVED_DDL = """CREATE TABLE lh_nautical.bronze.raw_exchange_rates (
  exchange_date DATE,
  currency_from STRING COLLATE UTF8_BINARY,
  exchange_rate DECIMAL(10,4),
  _ingested_at TIMESTAMP)
USING delta
COMMENT 'BCB rates (daily)'
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.format.version.afe.internal' = '2.12.0')
;
"""


def test_repoints_catalog_and_schema():
    out = rewrite_ddl(ARCHIVED_DDL, "my_catalog", "my_schema")
    assert "CREATE OR REPLACE TABLE my_catalog.my_schema.raw_exchange_rates (" in out
    assert "lh_nautical" not in out


def test_drops_table_properties_and_default_collation():
    out = rewrite_ddl(ARCHIVED_DDL, "c", "s")
    assert "TBLPROPERTIES" not in out
    assert "DEFAULT COLLATION" not in out
    assert not out.endswith(";")


def test_keeps_columns_types_and_comment():
    out = rewrite_ddl(ARCHIVED_DDL, "c", "s")
    assert "exchange_rate DECIMAL(10,4)" in out
    assert "currency_from STRING COLLATE UTF8_BINARY" in out
    assert "USING delta" in out
    assert "COMMENT 'BCB rates (daily)'" in out


def test_is_idempotent():
    once = rewrite_ddl(ARCHIVED_DDL, "c", "s")
    assert rewrite_ddl(once, "c", "s") == once
