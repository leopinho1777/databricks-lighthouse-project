"""Helpers to restore the Bronze layer from an archive of DDL + parquet files."""

import re

# Fully qualified catalog.schema prefix hardcoded in the archived DDL files
ARCHIVED_PREFIX = "lh_nautical.bronze"


def rewrite_ddl(ddl: str, catalog: str, schema: str, archived_prefix: str = ARCHIVED_PREFIX) -> str:
    """Adapts an archived CREATE TABLE statement to the target catalog/schema so it can be re-run safely.

    Repoints the table to catalog.schema, makes the statement idempotent (CREATE OR REPLACE),
    and drops the DEFAULT COLLATION line and TBLPROPERTIES block (internal Delta properties that
    may not exist in another workspace). Column MASK clauses are dropped too, because the masking
    function may not exist yet: restored tables are unmasked until governance is applied again.
    Column names, types, NOT NULL and comments are kept.
    """
    # Repoint every fully qualified reference to the target catalog.schema
    ddl = ddl.replace(f"{archived_prefix}.", f"{catalog}.{schema}.")
    # Make the statement re-runnable
    ddl = re.sub(r"\bCREATE\s+TABLE\b", "CREATE OR REPLACE TABLE", ddl, count=1, flags=re.IGNORECASE)
    # Drop column masks: "MASK <qualified function name>", with or without backticks
    ddl = re.sub(r"\s+MASK\s+(?:`[^`]+`|\w+)(?:\.(?:`[^`]+`|\w+))+", "", ddl, flags=re.IGNORECASE)
    # Drop the table-level default collation (UTF8_BINARY is already the default)
    ddl = re.sub(r"^\s*DEFAULT\s+COLLATION\s+\w+\s*$", "", ddl, flags=re.IGNORECASE | re.MULTILINE)
    # Drop the TBLPROPERTIES (...) block up to the closing parenthesis before the optional semicolon
    ddl = re.sub(r"TBLPROPERTIES\s*\(.*?\)\s*(?=;|\Z)", "", ddl, flags=re.IGNORECASE | re.DOTALL)
    # spark.sql() runs a single statement, so strip the trailing semicolon
    return ddl.strip().rstrip(";").strip()
