"""Carrega e expõe a configuração do RAG. Fonte única de nomes e parâmetros.

Os campos catalog / schema_gold / schema_rag podem ser sobrescritos em runtime
(parâmetros do job, variáveis de ambiente do app) sem editar o YAML.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "rag_config.yaml"

# Nome da variável de ambiente -> chave no YAML. Usado pelo app e pelos notebooks.
_ENV_OVERRIDES = {
    "RAG_CATALOG": "catalog",
    "RAG_SCHEMA_GOLD": "schema_gold",
    "RAG_SCHEMA_RAG": "schema_rag",
}


@dataclass
class Config:
    raw: dict = field(repr=False)

    @classmethod
    def load(cls, path: str | Path | None = None, *, apply_env: bool = True) -> "Config":
        path = Path(path or os.getenv("RAG_CONFIG") or _DEFAULT_PATH)
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        cfg = cls(raw=raw)
        if apply_env:
            cfg.apply_env_overrides()
        cfg.validate()
        return cfg

    def apply_env_overrides(self) -> "Config":
        for env_key, cfg_key in _ENV_OVERRIDES.items():
            val = os.getenv(env_key)
            if val:
                self.raw[cfg_key] = val
        return self

    def validate(self) -> None:
        obrigatorias = ("catalog", "schema_gold", "schema_rag", "tables",
                        "rag_tables", "vector_search", "llm", "retrieval", "chunking")
        faltando = [k for k in obrigatorias if k not in self.raw]
        if faltando:
            raise ValueError(f"rag_config.yaml sem as chaves: {faltando}")

    # --- nomes totalmente qualificados -----------------------------------------
    def gold(self, key: str) -> str:
        c = self.raw
        return f"{c['catalog']}.{c['schema_gold']}.{c['tables'][key]}"

    def rag(self, key: str) -> str:
        c = self.raw
        return f"{c['catalog']}.{c['schema_rag']}.{c['rag_tables'][key]}"

    # --- atalhos -------------------------------------------------------------
    @property
    def catalog(self) -> str:
        return self.raw["catalog"]

    @property
    def schema_rag(self) -> str:
        return self.raw["schema_rag"]

    @property
    def index_name(self) -> str:
        return self.rag("index")

    @property
    def vs(self) -> dict:
        return self.raw["vector_search"]

    @property
    def llm(self) -> dict:
        return self.raw["llm"]

    @property
    def retrieval(self) -> dict:
        return self.raw["retrieval"]

    @property
    def chunking(self) -> dict:
        return self.raw["chunking"]
