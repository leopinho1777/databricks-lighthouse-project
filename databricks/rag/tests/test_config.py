"""Testes do carregamento de configuração."""
import os
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # pyyaml pode não estar no venv local

from rag.config import Config  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "rag_config.yaml"


def test_carrega_e_qualifica_nomes():
    cfg = Config.load(CONFIG_PATH)
    assert cfg.rag("chunks").endswith(".rag.chunks")
    assert cfg.rag("index") == f"{cfg.catalog}.rag.chunks_index"
    assert cfg.gold("fct_forecast").count(".") == 2


def test_parametros_de_retrieval_e_chunking():
    cfg = Config.load(CONFIG_PATH)
    assert cfg.retrieval["final_k"] == 5
    assert cfg.retrieval["query_type"] == "HYBRID"
    assert cfg.chunking["max_chars"] >= cfg.chunking["target_chars"]


def test_override_por_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("RAG_CATALOG", "develop")
    monkeypatch.setenv("RAG_SCHEMA_GOLD", "leo_analytics_marts")
    cfg = Config.load(CONFIG_PATH)
    assert cfg.catalog == "develop"
    assert cfg.gold("fct_sales").startswith("develop.leo_analytics_marts.")


def test_config_incompleta_falha(tmp_path):
    ruim = tmp_path / "ruim.yaml"
    ruim.write_text("catalog: x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Config.load(ruim)
