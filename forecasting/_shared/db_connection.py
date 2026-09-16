# %%
"""Shared Databricks SQL connection helper for the forecasting workstream.

Reads credentials from the developer's existing `~/.dbt/profiles.yml` (dev
target) instead of duplicating them in this repo, so nothing secret gets
committed.

Data source convention (see forecasting/README.md "Data source convention"):
stable reference data (marts/staging) is read from PROD_MARTS/PROD_STAGING,
the same catalog every developer can read regardless of whose dev profile is
connected; disposable scratch/experimental tables are written to each
developer's own dev schema via get_scratch_schema(), never to a hardcoded
teammate's schema.
"""

from pathlib import Path

import yaml
from databricks import sql
from databricks.sql.experimental.oauth_persistence import OAuthPersistenceCache

PROFILE_NAME = "desafio_lh"
PROFILES_PATH = Path.home() / ".dbt" / "profiles.yml"

# Stable, team-shared source data -- read-only. Never write scratch/prototype
# tables here (see PROD_CATALOG's grants under the LGPD/RBAC governance model).
PROD_CATALOG = "lh_nautical"
PROD_MARTS = f"{PROD_CATALOG}.marts"
PROD_STAGING = f"{PROD_CATALOG}.staging"

# One in-memory OAuth cache per process: every connection opened by this module
# reuses the same token, so the browser login happens once per run instead of
# once per query.
_OAUTH_CACHE = OAuthPersistenceCache()


def _load_dev_profile() -> dict:
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = yaml.safe_load(f)
    outputs = profiles[PROFILE_NAME]["outputs"]
    return outputs["dev"]


def get_scratch_schema() -> str:
    """This developer's own forecasting scratch schema (`catalog.schema`), isolated per-user.

    Derived from the dev profile's own catalog/schema rather than hardcoded,
    so every developer's scratch writes (fact_demand_daily, feature-engineering
    outputs) land in their own dev schema instead of a specific teammate's.
    """
    profile = _load_dev_profile()
    return f"{profile['catalog']}.{profile['schema']}_forecasting_scratch"


def get_connection():
    """Return a databricks-sql-connector connection using the dbt dev profile."""
    profile = _load_dev_profile()
    # OAuth profiles (Databricks Free Edition does not allow PATs) carry no
    # token: fall back to the connector's browser-based OAuth flow.
    if profile.get("token"):
        auth = {"access_token": profile["token"]}
    else:
        auth = {
            "auth_type": "databricks-oauth",
            "experimental_oauth_persistence": _OAUTH_CACHE,
        }
    return sql.connect(
        server_hostname=profile["host"],
        http_path=profile["http_path"],
        catalog=profile["catalog"],
        schema=profile["schema"],
        **auth,
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
