# %%
"""Shared reproducibility helpers for Stage 3 model-comparison sessions.

First written for `eros_randomforest` (task 3.2) -- centralized here rather
than inline in one experiment script so every later `experiments/<name>_<model>/`
session reuses the same mechanism instead of each reimplementing (or skipping)
data-snapshot/library-version tagging slightly differently, the same drift
Stage 2 avoided by centralizing `compute_metrics()`/`most_recent_complete_year()`
in `panel_regression.py`.
"""

import importlib.util
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# Loaded by file path, not `import _shared` -- the repo has three directories
# named `_shared` (this one, `forecasting/_shared`, and
# `10_feature_engineering/_shared`), so a package-name import would resolve to
# whichever one Python's import cache saw first. Same technique `evaluate.py`
# and `panel_regression.py` already use for the same reason.
_DB_CONNECTION_PATH = Path(__file__).resolve().parents[2] / "_shared" / "db_connection.py"
_spec = importlib.util.spec_from_file_location("forecasting_shared_db_connection_repro", _DB_CONNECTION_PATH)
_db_connection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db_connection)
query_df = _db_connection.query_df


# %%
def get_table_version(table: str) -> dict:
    """Delta version/timestamp of `table` via DESCRIBE HISTORY, for MLflow reproducibility tags."""
    hist = query_df(f"DESCRIBE HISTORY {table} LIMIT 1")
    return {"delta_version": int(hist.loc[0, "version"]), "delta_timestamp": str(hist.loc[0, "timestamp"])}


# %%
def get_library_versions(package_names: list[str]) -> dict:
    """Installed pip-distribution versions (e.g. 'scikit-learn', 'xgboost', 'pandas'), keyed
    `lib_<name>` -- generic across whatever model library each Stage 3 session uses.

    Falls back past the exact distribution name for cases like `mlflow`: this project
    depends on `mlflow-skinny` (see pyproject.toml), which still exposes an importable
    `mlflow` module with a `__version__` attribute, but has no `mlflow` entry in
    importlib.metadata -- `version("mlflow")` raises `PackageNotFoundError` even though
    `import mlflow` works fine. Try the `-skinny` distribution name next, then fall back
    to importing the module directly and reading `__version__`.
    """
    versions = {}
    for name in package_names:
        try:
            versions[f"lib_{name}"] = version(name)
            continue
        except PackageNotFoundError:
            pass
        try:
            versions[f"lib_{name}"] = version(f"{name}-skinny")
            continue
        except PackageNotFoundError:
            pass
        versions[f"lib_{name}"] = getattr(import_module(name), "__version__", "unknown")
    return versions


# %%
if __name__ == "__main__":
    print(get_library_versions(["scikit-learn", "pandas", "numpy", "mlflow"]))
