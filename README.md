# README

Repositório para entrega do projeto Lighthouse do Grupo 10 / TeslaVinci.

Pipeline de ingestão incremental de um SQL Server para a camada Bronze do Databricks (Unity Catalog), com governança LGPD, mascaramento dinâmico, RBAC e orquestração via Databricks Workflow.

---

## Estrutura do Projeto

```
databricks.yml              # Definição do Asset Bundle (targets dev/prod)
databricks.local.yml        # Overrides locais (ex.: host por usuário)
pyproject.toml              # Pacote Python e dependências
resources/
  ingestion.job.yml         # Job de ingestão (4 tasks)
  grupo10_etl.pipeline.yml  # Pipeline DLT (camadas futuras)
src/
  tables_config.json        # 24 tabelas e suas chaves primárias
  governance_config.json    # Colunas sensíveis por tabela (LGPD)
  sqlserver_ingest_setup.ipynb  # Setup: catalog/schema, control/audit, taskValues
  sqlserver_ingest.ipynb        # Ingestão unitária (ForEach por tabela)
  governance_setup.ipynb        # Cria a UDF de mascaramento dinâmico
  apply_rbca.ipynb              # Concede privilégios RBAC
  drop_bronze_tables.ipynb      # Utilitário de reset da camada Bronze
  grupo10/
    ingest.py               # Lógica de extração/carga (incremental + MERGE)
    utils/audit.py          # Tabela e registros de auditoria
    utils/logger.py         # Logging do pipeline
tests/                      # conftest (Spark/fixtures) + unit/
fixtures/                   # Dados de teste
```

---

## Arquitetura

* **Databricks Asset Bundle (`databricks.yml`)**: declara o projeto (`grupo10`), artefatos e *targets* (`dev` / `prod`).
* **`pyproject.toml`**: pacote Python do projeto (`src/grupo10`) e dependências.
* **`resources/`**: definição dos *jobs* e *pipelines* do Databricks.
* **Destino**: catálogo `lh_nautical`, schema `bronze` (Unity Catalog), formato Delta Lake.

O job `ingestion` é composto por 4 tasks encadeadas (cada uma depende do sucesso da anterior):

governance_setup -> setup -> ingest_tables -> apply_rbac

## Estratégia de Ingestão

A lógica está modularizada em `src/grupo10/ingest.py`. Para cada tabela, `run_incremental_ingestion()` escolhe a estratégia pela chave primária:

* **Chave simples** (ex.: `"id"`): incremental por watermark, acumulando via `mode("append")`.
* **Chave composta** (ex.: `["product_variant_id", "location_id"]`): recarga completa via `_merge_into_delta()`.

São **24 tabelas** mapeadas em `tables_config.json`, das quais 3 usam chave composta (`stock_levels`, `product_suppliers`, `variant_attribute_values`).

Todas as escritas são idempotentes (MERGE ou watermark), eliminando duplicatas em reexecuções. Duas tabelas internas sustentam a o controle de ingestão os dados para auditoria:

| Tabela | Papel |
| :--- | :--- |
| **`_ingestion_control`** | Watermark por tabela; consultada no início e atualizada ao fim de cada execução. |
| **`_ingestion_audit`** | Histórico de execuções: status, duração, contagem de linhas e erro. |

Em caso de falha, a exceção é relançada para que o Workflow marque a task como falha, permitindo reprocessamento seletivo da tabela afetada.

---

## Governança e Segurança (LGPD)

Mascaramento dinâmico via Unity Catalog: a função `regra_mascaramento` retorna o valor original para `admins` e `engenharia_dados`, e `████████ (RESTRITO LGPD)` para os demais. As colunas sensíveis são mapeadas em `governance_config.json`.

Credenciais lidas via `dbutils.secrets.get()` (scope `sqlserver` no Databricks)

---

## Agendamento

`resources/ingestion.job.yml` agenda execução diária às **01:00 (America/Sao_Paulo)** via cron `0 0 1 * * ?`, com status `UNPAUSED`.

---

## Pré-requisitos

* **Databricks CLI** instalado e configurado.
* **uv** (gerenciador de pacotes Python).
* Acesso a um *workspace* Databricks com permissão para criar catálogos, schemas e *jobs*.

Targets do bundle: `dev` (default, schema por usuário) e `prod`. Configurações locais/sensíveis ficam em `databricks.local.yml`, o qual deve ser criado manualmente ao clonar o repositório.

---

## Como Executar

```bash
# 1. Instala dependências
uv sync --dev

# 2. Autenticação
databricks auth login

# 3. Exporta os segredos via scope do Databricks
databricks secrets create-scope sqlserver
databricks secrets put-secret sqlserver username <valor>
databricks secrets put-secret sqlserver password <valor>
databricks secrets put-secret sqlserver host <valor>
databricks secrets put-secret sqlserver port <valor>
databricks secrets put-secret sqlserver db <valor>

# 4. Deploy
databricks bundle deploy --target dev   # ou prod

# 5. Executar ingestão manualmente
databricks bundle run ingestion

```
