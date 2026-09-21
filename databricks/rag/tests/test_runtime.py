"""Descoberta dos parâmetros do job implantado — roda fora do Databricks (cliente falso)."""
from types import SimpleNamespace as NS

from rag.runtime import params_do_job_implantado


def _param(nome, default):
    return NS(name=nome, default=default)


def _job(job_id, nome, criador, params):
    return NS(job_id=job_id, creator_user_name=criador, settings=NS(name=nome, parameters=params))


class ClienteFalso:
    def __init__(self, jobs, eu="ana@exemplo.com"):
        self._jobs = {j.job_id: j for j in jobs}
        self.current_user = NS(me=lambda: NS(user_name=eu))
        self.jobs = NS(list=lambda: list(self._jobs.values()), get=lambda job_id: self._jobs[job_id])


PARAMS = [_param("catalog", "cat"), _param("schema_gold", "gold"), _param("schema_rag", "rag"),
          _param("app_name", "meu-app")]


def test_le_parametros_do_job_com_prefixo_de_dev():
    w = ClienteFalso([_job(1, "[dev ana] LH Nautical RAG - Ingestion", "ana@exemplo.com", PARAMS)])
    assert params_do_job_implantado(w) == {
        "catalog": "cat", "schema_gold": "gold", "schema_rag": "rag", "app_name": "meu-app"}


def test_prefere_o_job_do_usuario_atual():
    outro = [_param("catalog", "x"), _param("schema_gold", "y"), _param("schema_rag", "z")]
    w = ClienteFalso([
        _job(1, "[dev bia] LH Nautical RAG - Ingestion", "bia@exemplo.com", outro),
        _job(2, "[dev ana] LH Nautical RAG - Ingestion", "ana@exemplo.com", PARAMS),
    ])
    assert params_do_job_implantado(w)["catalog"] == "cat"


def test_prod_sem_prefixo():
    w = ClienteFalso([_job(1, "LH Nautical RAG - Ingestion", "svc@exemplo.com", PARAMS)])
    assert params_do_job_implantado(w)["schema_rag"] == "rag"


def test_sem_job_implantado_devolve_vazio():
    w = ClienteFalso([_job(1, "outro job", "ana@exemplo.com", PARAMS)])
    assert params_do_job_implantado(w) == {}


def test_job_sem_todos_os_parametros_e_ignorado():
    w = ClienteFalso([_job(1, "LH Nautical RAG - Ingestion", "ana@exemplo.com", [_param("catalog", "c")])])
    assert params_do_job_implantado(w) == {}
