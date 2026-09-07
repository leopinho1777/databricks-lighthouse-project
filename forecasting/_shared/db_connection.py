# %%
"""Shared Databricks SQL connection helper for the forecasting workstream.

Reads credentials from the developer's existing `~/.dbt/profiles.yml` (dev
target) instead of duplicating them in this repo, so nothing secret gets
committed.
"""

from pathlib import Path

import yaml
from databricks import sql

PROFILE_NAME = "desafio_lh"
PROFILES_PATH = Path.home() / ".dbt" / "profiles.yml"


def _load_dev_profile() -> dict:
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = yaml.safe_load(f)
    outputs = profiles[PROFILE_NAME]["outputs"]
    return outputs["dev"]


def get_connection():
    """Return a databricks-sql-connector connection using the dbt dev profile."""
    profile = _load_dev_profile()
    return sql.connect(
        server_hostname=profile["host"],
        http_path=profile["http_path"],
        access_token=profile["token"],
        catalog=profile["catalog"],
        schema=profile["schema"],
    )


def run_query(query: str):
    """Run a query and return (rows, column_names)."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            columns = [c[0] for c in cursor.description]
            rows = cursor.fetchall()
    return rows, columns


def query_df(query: str):
    """Run a query and return a pandas DataFrame."""
    import pandas as pd

    rows, columns = run_query(query)
    return pd.DataFrame(rows, columns=columns)


if __name__ == "__main__":
    df = query_df("select 1 as ok")
    print(df)
