# RAG — Assistente do Projeto LH Nautical

Bundle do sistema RAG: um chatbot que responde, em linguagem natural e com
números exatos, sobre previsão de demanda, sazonalidade, comparação de modelos,
centros de distribuição e arquitetura do projeto.

O corpus é **gerado deterministicamente** das tabelas gold e da saída da
modelagem (mais `docs/*.md` curados), indexado no Databricks Vector Search e
recuperado por busca híbrida. O LLM (Foundation Model APIs) redige a resposta
usando **apenas** o contexto recuperado. Nenhum número é calculado pelo modelo.

Especificação completa: ver o documento técnico do Checkpoint 5.

## Estrutura

```
databricks/rag/
├── databricks.yml              # bundle (targets dev/prod)
├── resources/
│   └── rag_ingestion.job.yml   # job batch: build_documents -> build_chunks -> sync_index
├── config/rag_config.yaml      # nomes, modelos e parâmetros
├── notebooks/                  # 00_setup .. 06_smoke + _bootstrap
├── src/rag/                    # config, documents, chunking, retriever, prompts, generator, observability
├── tests/                      # test_chunking, test_prompts, test_config (rodam fora do Databricks)
└── docs/                       # arquitetura, decisoes_tecnicas, dicionario_dados (entram no corpus)
```

## Duas metades

| Metade | Formato Databricks | Quando roda |
|---|---|---|
| Gerar corpus + indexar | **Job** `rag_ingestion` (3 tasks) | sob demanda: após remodelar a previsão, após editar `docs/*.md`, antes da apresentação |
| Iterar/testar o chat | notebook `04_chat_teste` | enquanto aberto |

Sem interface externa por ora — teste é só via notebook (`04_chat_teste` / `06_smoke`).

## Pré-requisitos

- Fase 0 do roadmap: confirmar no workspace os nomes de catálogo/schema e os
  endpoints `databricks-*` disponíveis (aba Serving). Ajustar `config/rag_config.yaml`.
- Fase 1 (bloqueio duro): `fct_forecast` e `model_evaluation` materializadas na
  camada gold. Sem elas, o pipeline gera só o corpus documental (`docs/*.md` +
  dicionário de dados) e os cards numéricos ficam de fora.

## Testar localmente (sem Databricks)

Os módulos `chunking`, `prompts` e `config` são Python puro e têm testes.

```bash
cd databricks/rag
uv run pytest
```

Esperado: testes de `test_chunking.py` e `test_prompts.py` passando;
`test_config.py` passa se `pyyaml` estiver no ambiente (senão é pulado).

Cobertura dos testes (§13.1 da spec):
- card (`doc_type` em `SEM_DIVISAO`) gera exatamente 1 chunk;
- nenhum chunk excede `max_chars`;
- todo chunk começa com breadcrumb e contém o título do documento;
- tabela markdown não é cortada entre linhas;
- `produto_id`, `loja_id`, `cd_id`, `fonte`, `atualizado_em` chegam a todos os chunks;
- contexto formatado com título/tipo/origem/data; `format_context([])` vazio;
- regra anti-injeção presente no system prompt.

## Implantar e rodar no Databricks

```bash
databricks auth login
cd databricks/rag
databricks bundle deploy --target dev
```

### Bootstrap (uma vez)

1. **Schema e tabelas** — rodar o notebook `notebooks/00_setup.py` (Serverless).
2. **Corpus** — `databricks bundle run rag_ingestion --target dev`
   (tasks `build_documents` e `build_chunks`; a task `sync_index` vai falhar
   nesta primeira vez porque o índice ainda não existe — tudo bem).
3. **Índice** — rodar `notebooks/03_create_index.py` (cria endpoint + índice +
   primeira `sync()`). Aguardar `ONLINE` na aba Vector Search.

### Ciclo normal

```bash
databricks bundle run rag_ingestion --target dev   # regenera corpus e sincroniza o índice
```

### Smoke test não-interativo

Rodar o notebook `notebooks/06_smoke.py` (Serverless, Run all): dispara 5 perguntas
canônicas de ponta a ponta (retrieval + LLM) e faz `assert` no fim. Cobre respostas
factuais com fontes, recusa correta e resistência a prompt injection.

### Checklist de integração (rodar no `04_chat_teste`)

1. índice existe e está `ONLINE`;
2. consulta conhecida retorna >= 1 chunk com score > 0;
3. chunk esperado aparece no top-5 para uma pergunta canônica;
4. resposta em português com bloco "Fontes:";
5. pergunta fora de escopo dispara a recusa e **não** chama o LLM;
6. pergunta adversarial ("ignore as instruções") é recusada;
7. mesma pergunta duas vezes -> mesma resposta (`temperature=0`);
8. uma linha é gravada em `rag.query_logs`.

## Configuração de ambiente

`config/rag_config.yaml` é a fonte única. O que muda por ambiente é sobrescrito
em runtime, sem editar o YAML:

- **Job**: parâmetros `catalog` / `schema_gold` / `schema_rag` (definidos no
  `databricks.yml` por target) → o `_bootstrap` os exporta como
  `RAG_CATALOG` / `RAG_SCHEMA_GOLD` / `RAG_SCHEMA_RAG`.

Nenhum secret é necessário: a autenticação é resolvida pelo PAT automático do
notebook/job.
