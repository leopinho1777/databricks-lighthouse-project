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

## Camada de Transformação de Dados (dbt)

A fase de transformação de dados é orquestrada via dbt (data build tool) sobre o Databricks, seguindo os princípios de engenharia de analytics modular e separação de responsabilidades em camadas. 

## Arquitetura de Schemas e Isolamento de Ambiência

Para garantir a qualidade dos testes e impedir que o trabalho individual de um desenvolvedor sobreponha o de outro, configuramos uma resolução dinâmica de schemas por meio de macro customizada (generate_schema_name):
Ambiente de Desenvolvimento (Dev): Todas as camadas de cada desenvolvedor são isoladas em schemas individuais com o prefixo da sua credencial (<usuario>_<camada>), por exemplo: usuario_analytics_staging, usuario_analytics_intermediate e usuario_analytics_marts. 
Sufixo e Padronização: Cada camada aplica automaticamente seu sufixo correspondente no Databricks.

## Estrutura dos Modelos

Atualmente, o projeto conta com 32 modelos compilados e testados, divididos entre as três camadas principais:
models/
├── staging/          # (22 modelos) Limpeza, padronização e tipagem dos dados brutos
├── intermediate/     # (4 modelos) Regras de negócio, enriquecimento e relacionamentos complexos
└── marts/            # (9 modelos) Modelagem dimensional pronta para análise (Star Schema)

## 1. Camada Staging

Responsável pela limpeza técnica, padronização de nomenclatura, remoção de duplicatas e tipagem correta dos dados vindos da camada Bronze.
Clientes e Localidades: stg_addresses, stg_customers, stg_employees, stg_locations
Catálogo e Produtos: stg_brands, stg_categories, stg_products, stg_product_variants
Vendas, Financeiro e Operações: stg_orders, stg_order_items, stg_payments, stg_fiscal_invoices, stg_returns, stg_return_items, stg_exchange_rates
Suprimentos e Estoque: stg_suppliers, stg_purchase_orders, stg_purchase_order_items, stg_goods_receipts, stg_goods_receipt_items, stg_stock_levels, stg_stock_movements

## 2. Camada Intermediate

Responsável por centralizar regras de negócio intermediárias, cruzamento de entidades e cruzamento de métricas operacionais.
int_products_categorized: Consolida produtos, variantes, marcas e hierarquia de categorias.
int_sales_enriched: Enriquece transações de vendas combinando pedidos, itens, pagamentos e notas fiscais.
int_supplier_delivery_delay: Calcula métricas e indicadores de atraso na entrega de pedidos de compras de fornecedores.
int_purchases_enriched: Consolida e enriquece os pedidos de compras integrando dados de itens e recebimentos.

## 3. Camada Marts

Contém os modelos dimensionais finais (Tabelas Fato e Dimensão) modelados no formato Star Schema, otimizados para consultas analíticas e ferramentas de BI. 

## Tabelas Dimensão 

dim_calendary: Dimensão temporal para análises de tendências e sazonalidade.
dim_customers: Visão consolidada dos clientes e seus endereços.
dim_employees: Cadastro e perfil de funcionários.
dim_locations: Localizações físicas e filiais.
dim_products: Dimensão completa do catálogo de produtos, atributos e categorias.
dim_suppliers: Cadastro e atributos dos fornecedores.

## Tabelas Fato

fct_sales: Fato de vendas com granularidade de itens de pedidos, valores, descontos e métricas financeiras.
fct_daily_stock_levels: Fato de acompanhamento diário dos níveis e movimentações de estoque.
fct_purchases: Fato de compras e suprimentos consolidando métricas de pedidos de compras e recebimentos de fornecedores.

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
