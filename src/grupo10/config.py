"""
Environment configuration for grupo10.

Set the GRUPO10_ENV environment variable to select the target environment:
  - "dev"  (default) → lh_nautical_dev.bronze
  - "prod"           → lh_nautical.bronze

On Databricks, set GRUPO10_ENV in the job cluster environment variables
or add  %environment GRUPO10_ENV=prod  at the top of a notebook.
"""

import os

_CONFIGS = {
    "dev": {
        "catalog": "lh_nautical_dev",
        "schema": "bronze",
    },
    "prod": {
        "catalog": "lh_nautical",
        "schema": "bronze",
    },
}

#Dá 'dev' como default se a enviroment variable do job cluster não for configurada
ENV: str = os.getenv("GRUPO10_ENV", "dev")

#Avisa se um enviroment inexistente for selecionado
if ENV not in _CONFIGS:
    raise ValueError(
        f"Unknown GRUPO10_ENV='{ENV}'. Valid values: {list(_CONFIGS.keys())}"
    )

CATALOG: str = _CONFIGS[ENV]["catalog"]
SCHEMA: str = _CONFIGS[ENV]["schema"]
TARGET_CATALOG_SCHEMA: str = f"{CATALOG}.{SCHEMA}"
