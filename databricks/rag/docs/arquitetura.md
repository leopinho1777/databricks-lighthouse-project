# Arquitetura de Dados do Projeto LH Nautical

Documento curado que entra no corpus do RAG (`doc_type: arquitetura`). Descreve
como os dados chegam ao data warehouse e como o pipeline é orquestrado.

## Camada de Ingestão

A ingestão move dados de um SQL Server de origem para a camada `bronze` do
catálogo Unity Catalog (`lh_nautical` em produção, `develop` em desenvolvimento).
É um Databricks Asset Bundle (`databricks/ingestion`) com um job de duas etapas:
uma task `setup` que cria catálogo, schema e as tabelas de controle e auditoria,
e uma task `ingest_tables` que percorre as 24 tabelas de origem com um
`for_each_task` de concorrência 5. Em paralelo, uma task separada ingere as
taxas de câmbio do Banco Central.

A estratégia de ingestão é escolhida por tabela conforme o formato da chave
primária. Tabelas com chave única usam paginação incremental por watermark:
lotes de linhas entre o último id processado e o id máximo atual da origem,
gravados em modo append. Tabelas com chave composta usam recarga completa com
MERGE (upsert), o que torna a reexecução idempotente. Toda linha ingerida recebe
as colunas de metadados `_ingested_at`, `_source_origin` e `_batch_id`.

O avanço do watermark só acontece depois que todos os lotes da tabela terminam
com sucesso, então uma falha no meio reinicia apenas aquela tabela a partir do
último commit bem-sucedido. Cada execução grava um registro de auditoria com
status, duração, contagem de linhas e erro.

## Camada de Transformação

A transformação roda dbt contra a camada bronze, dentro do bundle
`databricks/transformation`, cujo job único executa `dbt deps` e `dbt build`. O
projeto dbt tem três camadas de modelos: `staging` (limpeza e tipagem 1:1 sobre
o bronze), `intermediate` (junções e regras de negócio) e `marts` (esquema
estrela para BI, com dimensões e fatos). Em desenvolvimento cada pessoa roda em
um schema isolado com prefixo próprio; em produção os schemas são `staging`,
`intermediate` e `marts`.

Os fatos principais são `fct_sales`, `fct_purchases`, `fct_returns` e
`fct_daily_stock_levels`. As dimensões incluem `dim_products`, `dim_customers`,
`dim_employees`, `dim_locations`, `dim_suppliers` e `dim_calendary`. Macros
reutilizáveis cobrem conversão de moeda para BRL, deduplicação de dados que
chegam atrasados e cálculo de diferença de dias.

## Governança e LGPD

O mascaramento dinâmico é aplicado por coluna via `ALTER TABLE ... SET MASK`,
usando uma função que devolve o valor real apenas para os papéis `admins` e
`engenharia_dados` e um placeholder redigido para os demais. As colunas
sensíveis por tabela são declaradas em um arquivo de configuração de governança.
O RBAC é concedido por um notebook dedicado.

## Orquestração

O bundle `databricks/orchestration` define um job que encadeia os jobs já
implantados: ingestão, depois transformação, e em seguida a atualização do
dataset do Power BI. Ele é agendado diariamente à 01:00 no horário de São Paulo.

## Onde o RAG entra

O RAG é um quarto bundle (`databricks/rag`). Ele lê as tabelas gold e a saída da
modelagem de previsão em modo somente leitura, gera um corpus de documentos em
português, indexa esse corpus no Databricks Vector Search e serve um chatbot em
Databricks Apps. O RAG nunca escreve no data warehouse; a única escrita online é
o append na tabela de logs de consulta.
