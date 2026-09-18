"""Testes do chunking — rodam fora do Databricks (§13.1)."""
from rag.chunking import SEM_DIVISAO, ChunkCfg, chunk_document

CFG = ChunkCfg()


def _card(doc_type="previsao_produto_loja"):
    return {
        "doc_id": f"{doc_type}:P0142:L07",
        "doc_type": doc_type,
        "titulo": "Previsão de demanda — Âncora Náutica 5kg (P0142) na Loja Santos (L07)",
        "corpo": ("Para o produto Âncora Náutica 5kg (SKU P0142) na loja Santos (L07), "
                  "a previsão de demanda é de 128 unidades em outubro/2026, 141 unidades "
                  "em novembro/2026 e 173 unidades em dezembro/2026."),
        "produto_id": "P0142", "produto_nome": "Âncora Náutica 5kg",
        "loja_id": "L07", "loja_nome": "Loja Santos",
        "cd_id": "CD02", "cd_nome": "CD Sudeste",
        "periodo": "2026-10..2026-12",
        "fonte": "lh_nautical.gold.fct_forecast",
        "atualizado_em": "2026-09-09T14:02:11Z",
    }


def _doc_escrito():
    corpo = "# Arquitetura de Dados\n\n## Camada de Ingestão\n\n"
    corpo += ("A ingestão traz as tabelas do SQL Server para a camada bronze. " * 40 + "\n\n") * 3
    corpo += "## Camada de Transformação\n\n"
    corpo += ("O dbt transforma bronze em staging, intermediate e marts. " * 40 + "\n\n") * 3
    return {
        "doc_id": "arquitetura:arquitetura.md",
        "doc_type": "arquitetura",
        "titulo": "Arquitetura de Dados do Projeto LH Nautical",
        "corpo": corpo,
        "produto_id": None, "produto_nome": None, "loja_id": None, "loja_nome": None,
        "cd_id": None, "cd_nome": None, "periodo": None,
        "fonte": "docs/arquitetura.md",
        "atualizado_em": "2026-09-09T14:02:11Z",
    }


def test_card_nao_e_dividido():
    for dt in SEM_DIVISAO:
        chunks = chunk_document({**_card(), "doc_type": dt}, CFG)
        assert len(chunks) == 1


def test_teto_de_caracteres():
    chunks = chunk_document(_doc_escrito(), CFG)
    assert len(chunks) > 1
    assert all(len(c["texto"]) <= CFG.max_chars for c in chunks)


def test_breadcrumb_presente():
    doc = _doc_escrito()
    for c in chunk_document(doc, CFG):
        assert c["texto"].startswith("[")
        assert doc["titulo"] in c["texto"].splitlines()[0]


def test_tabela_markdown_intacta():
    linhas = "\n".join(f"| M{i} | {i * 10} | {i * 5} |" for i in range(1, 6))
    tabela = "| Modelo | MAE | RMSE |\n| --- | --- | --- |\n" + linhas
    corpo = (
        "# Comparação de Modelos\n\n## Resultados\n\n"
        + ("Texto de contexto antes da tabela. " * 60) + "\n\n"
        + tabela + "\n\n"
        + ("Texto de contexto depois da tabela. " * 60)
    )
    doc = {
        "doc_id": "comparacao_modelos:cmp", "doc_type": "comparacao_modelos",
        "titulo": "Comparação de Modelos de Regressão", "corpo": corpo,
        "produto_id": None, "produto_nome": None, "loja_id": None, "loja_nome": None,
        "cd_id": None, "cd_nome": None, "periodo": None,
        "fonte": "docs/decisoes_tecnicas.md", "atualizado_em": "2026-09-09",
    }
    chunks = chunk_document(doc, CFG)

    # a tabela completa aparece inteira em pelo menos um chunk
    assert any(
        "| Modelo | MAE | RMSE |" in c["texto"]
        and all(f"| M{i} |" in c["texto"] for i in range(1, 6))
        for c in chunks
    )
    # nenhuma linha de tabela foi cortada no meio
    for c in chunks:
        for ln in c["texto"].splitlines():
            s = ln.strip()
            if s.startswith("|"):
                assert s.endswith("|"), f"linha de tabela cortada: {s!r}"


def test_metadados_herdados():
    doc = _card()
    chunks = chunk_document(doc, CFG)
    assert chunks
    for c in chunks:
        for k in ("produto_id", "loja_id", "cd_id", "fonte", "atualizado_em", "doc_type"):
            assert c[k] == doc[k]
        assert c["chunk_id"].startswith(doc["doc_id"] + "#")


def test_chunk_ids_unicos_e_ordenados():
    chunks = chunk_document(_doc_escrito(), CFG)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)
