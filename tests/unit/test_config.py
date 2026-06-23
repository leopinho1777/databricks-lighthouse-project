"""Unit tests for grupo10.config — no cluster required.

Each test reloads the module after patching GRUPO10_ENV to isolate state.
"""

import importlib
import pytest


def _reload_config(monkeypatch, env_value=None):
    """Helper: set or unset GRUPO10_ENV then reload config."""
    import grupo10.config as config_module  # noqa: ensure it is importable

    if env_value is None:
        monkeypatch.delenv("GRUPO10_ENV", raising=False)
    else:
        monkeypatch.setenv("GRUPO10_ENV", env_value)

    return importlib.reload(config_module)


class TestDevEnvironment:
    def test_default_env_is_dev(self, monkeypatch):
        config = _reload_config(monkeypatch)
        assert config.ENV == "dev"

    def test_dev_catalog(self, monkeypatch):
        config = _reload_config(monkeypatch)
        assert config.CATALOG == "lh_nautical_dev"

    def test_dev_schema(self, monkeypatch):
        config = _reload_config(monkeypatch)
        assert config.SCHEMA == "bronze"

    def test_dev_target_catalog_schema(self, monkeypatch):
        config = _reload_config(monkeypatch)
        assert config.TARGET_CATALOG_SCHEMA == "lh_nautical_dev.bronze"


class TestProdEnvironment:
    def test_prod_env(self, monkeypatch):
        config = _reload_config(monkeypatch, "prod")
        assert config.ENV == "prod"

    def test_prod_catalog(self, monkeypatch):
        config = _reload_config(monkeypatch, "prod")
        assert config.CATALOG == "lh_nautical"

    def test_prod_schema(self, monkeypatch):
        config = _reload_config(monkeypatch, "prod")
        assert config.SCHEMA == "bronze"

    def test_prod_target_catalog_schema(self, monkeypatch):
        config = _reload_config(monkeypatch, "prod")
        assert config.TARGET_CATALOG_SCHEMA == "lh_nautical.bronze"


class TestInvalidEnvironment:
    def test_unknown_env_raises_value_error(self, monkeypatch):
        with pytest.raises(ValueError, match="Unknown GRUPO10_ENV"):
            _reload_config(monkeypatch, "staging")

    def test_error_message_includes_env_name(self, monkeypatch):
        with pytest.raises(ValueError, match="staging"):
            _reload_config(monkeypatch, "staging")

    def test_error_message_lists_valid_values(self, monkeypatch):
        with pytest.raises(ValueError, match="dev"):
            _reload_config(monkeypatch, "staging")
