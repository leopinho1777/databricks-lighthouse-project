# README #

Repositório para entrega do projeto Lighthouse do Grupo 10 / TeslaVinci

---

## Estruturação Inicial do Projeto e Ingestão Base

A fundação do pipeline, do projeto no Databricks e a primeira versão funcional da ingestão — sobre a qual as demais camadas (modularização, idempotência, governança e mascaramento) foram posteriormente construídas.

### Etapa 1: Inicialização do Databricks Asset Bundle
Estruturação inicial do repositório a partir do template de *bundle* do Databricks, definindo a base de organização e *deploy* do projeto:
* **`databricks.yml`**: Arquivo central do *bundle*, que declara o nome do projeto (`grupo10`), os artefatos e os *targets* de ambiente (`dev` / `prod`).
* **`pyproject.toml`**: Define o pacote Python do projeto (`src/grupo10`) e suas dependências.
* **`resources/`**: Estrutura de definição dos recursos (*jobs* e *pipelines*) do Databricks.


### Etapa 2: Inicialização da Infraestrutura (Catálogo e Schema)
A primeira célula do notebook garante o isolamento do ambiente no Unity Catalog, criando o catálogo principal e o esquema lógico da camada Bronze de forma idempotente:
* `CREATE CATALOG IF NOT EXISTS lh_nautical;`
* `CREATE SCHEMA IF NOT EXISTS lh_nautical.bronze;`


### Etapa 3: Conexão Segura via Secret Scopes
Implementação da leitura das credenciais de conexão a partir do cofre de segredos do Databricks, evitando qualquer exposição de senhas ou dados de conexão em texto limpo no código:
```python
db_user     = dbutils.secrets.get(scope="sqlserver", key="username")
db_password = dbutils.secrets.get(scope="sqlserver", key="password")
db_host     = dbutils.secrets.get(scope="sqlserver", key="host")
db_port     = dbutils.secrets.get(scope="sqlserver", key="port")
db_database = dbutils.secrets.get(scope="sqlserver", key="db")

jdbc_url = f"jdbc:sqlserver://{db_host}:{db_port};databaseName={db_database}"
```



### Etapa 4: Loop Base de Extração (JDBC → Delta Bronze)
Construção do loop fundamental de ingestão, que percorre a lista de tabelas de origem, estabelece a conexão SQL Server (`encrypt`, `trustServerCertificate`, `fetchsize`) e grava cada tabela na camada Bronze em
formato Delta Lake:
```python
for tabela in tabelas_nomes:
    df_temp = spark.read.format("jdbc").options(**jdbc_options).load()
    output_table = f"lh_nautical.bronze.{tabela}"
    df_temp.write.format("delta").mode("overwrite").saveAsTable(output_table)
```
Essa estrutura base foi posteriormente modularizada (em `src/grupo10/ingestion.py`) e enriquecida com herança de dados pelos demais membros do time.

---

### Detalhes dos Arquivos:
* **`src/tabelas_config.json`**: Centraliza os metadados do projeto. Conta o mapeamento exato de toda ação relacional com suas respectivas listas de colunas. Evita que o script Spark possua arrays
estáticos e "hardcoded", facilitando a inclusão de novas tabelas.
* **`src/sqlserver_ingest.ipynb`**: Notebook estruturado em células conceituais que executa a leitura ocessamento por lote (*batch*) com particionamento controlado e a camada de criptografia.
* **`src/governanca_config.json`**: Isola as regras de negócio de privacidade. Determina quais colunas são de manutenções manuais no notebook.

---

## Bibliotecas Utilizadas e Justificativa

* **`pyspark.sql (SparkSession)`**: Motor de computação distribuída em memória utilizado para processar de forma paralela através do cluster.
* **`json`**: Biblioteca nativa do Python para carregar e interpretar o arquivo de configuração de met).
* **`databricks.sdk.runtime (dbutils)`**: Utilitário nativo do Databricks usado para interagir com o ca através do `dbutils.secrets.get()`, impedindo a exposição de senhas e dados confidenciais de conexão em texto limpo no código.

---

## Etapas Detalhadas do Processo

O script `sqlserver_ingest.ipynb` executa cinco etapas sequenciais automatizadas:

### Etapa 1: Inicialização da Infraestrutura (SQL)
A primeira célula garante o isolamento do ambiente criando o catálogo principal e o esquema lógico dentro do Unity Catalog.
* `CREATE CATALOG IF NOT EXISTS lh_nautical;`
* `CREATE SCHEMA IF NOT EXISTS lh_nautical.bronze;`

### Etapa 2: Autenticação Segura e Conexão JDBC
O Spark estabelece uma conexão criptografada via protocolo JDBC com o banco de dados SQL Server corporativo utilizando os parâmetros de segurança `"encrypt": "true"` e `"trustServerCertificate": "true"`. A performance é otimizada por
lote através da diretriz `"fetchsize": "1000"`.

### Etapa 3: Criação da UDF de Mascaramento Dinâmico
O script injeta uma função de controle nativa no Unity Catalog (`lh_nautical.bronze.regra_mascaramento`). Essa função inspeciona em tempo real o usuário que está disparando a consulta. Se ele não fizer parte explicitamente de `admins` ou `engenharia_dados`, o motor substitui o valor original pela máscara: **`████████ (RESTRITO LGPD)`**.


### Etapa 4: Extração Limpa e Vinculação de Máscaras
O loop realiza a extração integral de cada uma das 24 tabelas e as salva no formato Delta Lake. Na sequência, para cada tabela que possui mapeamento no arquivo `governanca_config.json`, o script executa um comando de alteração estrutural:
```sql
ALTER TABLE lh_nautical.bronze.<tabela> ALTER COLUMN <coluna> SET MASK lh_nautical.bronze.regra_mascaramento;
```

### Etapa 5: Aplicação de Privilégios e Segurança RBAC
Na quinta etapa, o script automatiza as políticas de concessão de acessos diretamente no Schema Bronze:
Concede SELECT (Apenas leitura) para o grupo de avaliadores da LH Nautical (stakeholders).
Concede SELECT, MODIFY (Leitura, inserção, alteração e deleção) para o time de desenvolvimento (engenharia_dados).


## Catálogo de Tabelas e Variáveis (Camada Bronze)

Abaixo está listado o dicionário completo das 24 tabelas ingeridas integralmente para a camada Bronze,tida nos esquemas relacionais originais:

* **addresses** (Cadastro de endereços de clientes)
  * `id`, `customer_id`, `address_type`, `postal_code`, `street`, `number`, `complement`, `district`, is_primary`
* **attributes** (Especificações técnicas de variações de produtos)
  * `id`, `name`, `data_type`
* **brands** (Marcas dos produtos comercializados)
  * `id`, `name`, `country`, `is_active`, `created_at`, `updated_at`
* **categories** (Árvore de categorias de produtos)
  * `id`, `name`, `slug`, `parent_category_id`, `is_active`, `created_at`, `updated_at`
* **customers** (Cadastro de clientes ativos e inativos)
  * `id`, `person_type`, `legal_name`, `trade_name`, `tax_id`, `state_registration`, `email`, `phone`,updated_at`
* **employees** (Quadro de colaboradores da companhia)
  * `id`, `full_name`, `cpf`, `email`, `role`, `primary_location_id`, `hire_date`, `termination_date`,updated_at`
* **fiscal_invoices** (Notas fiscais vinculadas a pedidos)
  * `id`, `order_id`, `nfe_number`, `nfe_access_key`, `series`, `issued_at`, `status`, `total_amount`,at`, `updated_at`
* **goods_receipts** (Registros de recebimento de cargas no galpão)
  * `id`, `purchase_order_id`, `received_by_employee_id`, `received_at`, `notes`, `created_at`
* **goods_receipt_items** (Vínculo de itens físicos recebidos)
  * `id`, `goods_receipt_id`, `purchase_order_item_id`, `quantity_received`
* **locations** (Centros de distribuição, lojas e galpões físicos)
  * `id`, `name`, `location_type`, `postal_code`, `street`, `number`, `complement`, `district`, `city`ive`, `created_at`, `updated_at`
* **orders** (Cabeçalho de pedidos de venda capturados)
  * `id`, `order_number`, `channel`, `customer_id`, `salesperson_id`, `location_id`, `status`, `subtotl`, `placed_at`, `created_at`, `updated_at`
* **order_items** (Linhas de produtos associadas a cada pedido)
  * `id`, `order_id`, `product_variant_id`, `quantity`, `unit_price`, `icms_rate`, `ipi_rate`, `line_t
* **payments** (Fluxo de transações financeiras dos pedidos)
  * `id`, `order_id`, `method`, `installments`, `amount`, `status`, `paid_at`, `created_at`, `updated_
* **products** (Cadastro mestre de produtos da plataforma)
  * `id`, `name`, `description`, `brand_id`, `category_id`, `ncm_code`, `unit_of_measure`, `is_active`
* **product_suppliers** (Vínculo comercial de custos e prazos com fornecedores)
  * `product_variant_id`, `supplier_id`, `supplier_sku`, `last_quoted_cost`, `lead_time_days`, `is_preed_at`
* **product_variants** (Especificações de SKUs das variantes de produtos)
  * `id`, `product_id`, `sku`, `barcode_ean`, `sale_price`, `cost_price`, `weight_kg`, `icms_rate`, `ipi_rate`, `is_active`, `created_at`, `updated_at`
* **purchase_orders** (Ordens de compra emitidas para fornecedores)
  * `id`, `po_number`, `supplier_id`, `buyer_id`, `destination_location_id`, `status`, `currency`, `su, `expected_delivery_at`, `created_at`, `updated_at`
* **purchase_order_items** (Detalhamento de custos de insumos comprados)
  * `id`, `purchase_order_id`, `product_variant_id`, `quantity_ordered`, `unit_cost`, `line_total`
* **returns** (Solicitações de devolução de mercadorias por clientes)
  * `id`, `return_number`, `order_id`, `customer_id`, `received_at_location_id`, `status`, `reason`, `d_at`, `updated_at`
* **return_items** (Detalhamento de SKUs devolvidos ou trocados)
  * `id`, `return_id`, `order_item_id`, `quantity`, `action`, `exchange_variant_id`, `unit_refund_amou
* **stock_levels** (Balanço de inventário atual por localidade)
  * `product_variant_id`, `location_id`, `quantity_on_hand`, `reorder_point`, `updated_at`
* **stock_movements** (Histórico de entradas e saídas de inventário físico)
  * `id`, `product_variant_id`, `location_id`, `movement_type`, `quantity`, `reference_table`, `referes`, `occurred_at`, `created_at`
* **suppliers** (Cadastro de fornecedores parceiros)
  * `id`, `legal_name`, `trade_name`, `country`, `tax_id`, `tax_id_type`, `email`, `phone`, `contact_nt`, `updated_at`
* **variant_attribute_values** (Valores específicos atribuídos às variantes)
  * `product_variant_id`, `attribute_id`, `value`

---

## Política de Mascaramento Externa e LGPD (`governanca_config.json`)

# Matriz de Acesso e Grupos Role-Based Access Control (RBAC)

O ecossistema está segmentado em 4 níveis de controle de acesso baseados em papéis para garantir a segurança da infraestrutura e a privacidade das informações:

| Nome do Grupo | Membros e Papel | Permissão no Catálogo | Visão de Dados Sensíveis |
| :--- | :--- | :--- | :--- |
| **`admins`** | Dono do Workspace | Controle Total (Owner) | **Texto Limpo** (Acesso Total) |
| **`engenharia_dados`** | Engenheiros de Dados do Time | `SELECT`, `MODIFY` | **Texto Limpo** (Para T
| **`time_negocios`** | Analistas de Negócio / BI | `SELECT` (Em camadas superiores) | 🎭 **Mascarado** (LGPD Ativa) |
| **`stakeholders`** | Time de Avaliadores da LH Nautical | `SELECT` (Apenas Leitura) | 🎭 **Mascarado

Campos afetados mapeados no arquivo de configuração externa:
* **customers**: `legal_name`, `trade_name`, `tax_id`, `email`
* **employees**: `full_name`, `cpf`, `email`
* **suppliers**: `legal_name`, `trade_name`, `tax_id`
* **fiscal_invoices**: `nfe_access_key`, `xml_storage_uri`
* **goods_receipts**: `notes`

—

---

## Ingestão Incremental com Controle de Watermark

A evolução do loop base de extração — que realizava `overwrite` integral de cada tabela — para uma estratégia incremental que extrai apenas as linhas novas ou modificadas desde a última execução bem-sucedida, controladas por uma tabela de watermark interna.

### Etapa 1: Arquitetura de Orquestração (ForEach)

O pipeline foi reestruturado em dois notebooks com responsabilidades distintas, executados em sequência pelo Databricks Workflow:

* **`sqlserver_ingest_setup.ipynb`**: Notebook de setup, executado uma única vez por ciclo. Garante a existência das estruturas de controle, lê o catálogo de tabelas e publica a lista para as tasks filhas via `dbutils.jobs.taskValues.set()`.
* **`sqlserver_ingest.ipynb`**: Notebook de ingestão unitária, executado em paralelo pelo tipo de task **ForEach** do Databricks Workflow — uma instância independente por tabela.

### Etapa 2: Setup e Publicação das Tabelas-Alvo

O notebook de setup inicializa os dois artefatos internos de controle (`_ingestion_audit` e `_ingestion_control`) antes de qualquer extração. Em seguida, lê o catálogo de tabelas do arquivo `tabelas_config_v2.json` e publica a lista como `taskValues`, tornando-a acessível às tasks filhas do ForEach. Cada elemento da lista (`{"name": ..., "primary_key": ...}`) se torna um input independente para uma instância paralela do notebook de ingestão.

### Etapa 3: Ingestão Incremental por Tabela

Cada instância recebe sua tabela-alvo via widget injetado pelo ForEach e delega a extração à função `run_incremental_ingestion()`. Essa função consulta a `_ingestion_control` para recuperar o watermark da última execução bem-sucedida e usa a `primary_key` da tabela para identificar e extrair apenas as linhas novas ou modificadas desde então. O parâmetro `lines_per_batch=1000` controla o `fetchsize` do driver JDBC, limitando o volume transferido por lote para evitar pressão de memória no driver.

### Etapa 4: Tabelas Internas de Controle

Duas tabelas Delta internas sustentam a rastreabilidade e a idempotência do pipeline:

| Tabela | Papel |
| :--- | :--- |
| **`lh_nautical.bronze._ingestion_control`** | Armazena o watermark por tabela — o marcador do ponto até onde a última extração avançou. Consultada no início e atualizada ao fim de cada execução bem-sucedida. |
| **`lh_nautical.bronze._ingestion_audit`** | Registra o histórico de execuções: status (`success` / `failed`), duração, contagem de linhas e mensagem de erro quando aplicável. |

O prefixo `_` em ambas as tabelas sinaliza que são artefatos internos de infraestrutura, não expostos às camadas superiores.

### Etapa 5: Auditoria e Tratamento de Falhas

Ao fim de cada execução — com sucesso ou falha — `write_audit_record()` registra o resultado na tabela de auditoria com status, duração, contagem de linhas e mensagem de erro quando aplicável. Em caso de falha, a exceção é relançada intencionalmente para que o Databricks Workflow marque a task individual como falha, permitindo reprocessamento seletivo da tabela afetada sem reexecutar o ciclo inteiro.

---


## Idempotência e Auditoria da Ingestão

Para garantir que o pipeline possa ser reexecutado com segurança — sem gerar dados duplicados nem corromper a camada Bronze —, a lógica de extração foi modularizada e enriquecida com mecanismos de idempotência e rastreabilidade.

### Etapa 1: Modularização da Lógica de Ingestão
A complexidade técnica da ingestão (opções JDBC, colunas de auditoria e modo de escrita) foi extraída do notebook para um módulo Python reutilizável e testável, deixando o notebook responsável apenas por *orquestrar* (segredos, loop, logging e auditoria).
* **`src/grupo10/ingestion.py`**: Concentra a lógica de extração e carga da camada Bronze através de duas funções puras:
  * `extrair_tabela()`: Lê a tabela do SQL Server via JDBC e adiciona automaticamente as colunas de auditoria.
  * `carregar_bronze()`: Grava o DataFrame em formato Delta de forma idempotente.


### Etapa 2: Colunas de Auditoria
Toda tabela extraída recebe automaticamente três colunas de metadados, centralizadas em um único lugar (se a regra mudar, muda apenas no módulo):

| Coluna | Conteúdo | Função |
| :--- | :--- | :--- |
| **`_batch_id`** | Identificador do lote (*run*) | Permite identificar e reprocessar exatamente o lote problemático |
| **`_ingested_at`** | Timestamp da ingestão | Registra quando o dado foi carregado |
| **`_source_origin`** | Origem do dado (ex.: `sql_server_customers`) | Rastreia de qual tabela de origem o dado veio |


### Etapa 3: `batch_id` Único por Execução
O `batch_id` é gerado **uma única vez** pelo orquestrador e passado como parâmetro para todas as tabelas do mesmo *run*. Dessa forma, o lote inteiro compartilha o mesmo identificador — se cada chamada gerasse o próprio id, o conceito de "lote" deixaria de identificar a execução. Esse contrato é o ponto de integração com a orquestração incremental em *batches*.

### Etapa 4: Escrita Idempotente
A carga na Bronze utiliza `df.write.format("delta").mode("overwrite")`. É esse modo que garante a idempotência: reexecutar o pipeline **substitui** a tabela inteira em vez de acumular linhas duplicadas, deixando a decisão encapsulada e documentada em um único ponto.

### Etapa 5: Tabela de Auditoria de Execuções
Foi criada a tabela interna **`lh_nautical.bronze._ingestion_audit`** (o *underline* sinaliza que é uma tabela interna, não de negócio), populada via utilitários em **`src/grupo10/utils/audit.py`** (`ensure_audit_table` / `write_audit_record`). Ela registra o histórico de cada execução do pipeline, garantindo rastreabilidade das ingestões.

---
## Agendamento Automatizado (Schedule / Cron)

Para que a ingestão da camada Bronze ocorra de forma autônoma e recorrente, o *job* do Databricks foi configurado com um agendamento *cron* nativo.

* **`resources/ingestion.job.yml`**: Define o gatilho de execução automática do *job* de ingestão:

```yaml
schedule:
  quartz_cron_expression: "0 0 1 * * ?"   # Todos os dias às 01:00
  timezone_id: "America/Sao_Paulo"
  pause_status: UNPAUSED                   # Agendamento ativo
```

| Parâmetro | Valor | Significado |
| :--- | :--- | :--- |
| **Expressão Cron** | `0 0 1 * * ?` | Execução diária à **01:00** |
| **Timezone** | `America/Sao_Paulo` | Horário de Brasília |
| **Status** | `UNPAUSED` | Agendamento ativo desde o *deploy* |

---

## Como Executar o Pipeline

O projeto é um **Databricks Asset Bundle**, então a execução é feita via Databricks CLI. Os passos abaixo cobrem desde a preparação do ambiente até o deploy e a execução do *job* de ingestão.

### 1. Pré-requisitos
* **Databricks CLI** instalado ([docs](https://docs.databricks.com/dev-tools/cli/databricks-cli.html)).
* **uv** (gerenciador de pacotes Python) instalado ([docs](https://docs.astral.sh/uv/getting-started/installation/)).
* Acesso a um *workspace* Databricks com permissão para criar catálogos, schemas e *jobs*.

### 2. Instalação das Dependências
Sincronize o ambiente virtual do projeto com as dependências declaradas no `pyproject.toml`:
```bash
uv sync --dev
```
> No Windows (PowerShell), ative o ambiente virtual com:
> ```powershell
> .venv\Scripts\Activate.ps1
> ```

### 3. Autenticação no Workspace
Autentique-se no Databricks (caso ainda não tenha feito):
```bash
databricks auth login
```

### 4. Configuração do Secret Scope
As credenciais do SQL Server **não ficam no código** — são lidas do cofre de segredos. Crie o *scope* `sqlserver` e cadastre as cinco chaves utilizadas pelo notebook:
```bash
databricks secrets create-scope sqlserver

databricks secrets put-secret sqlserver username
databricks secrets put-secret sqlserver password
databricks secrets put-secret sqlserver host
databricks secrets put-secret sqlserver port
databricks secrets put-secret sqlserver db
```

### 5. Deploy do Bundle
Faça o *deploy* dos recursos (job de ingestão + pipeline) para o ambiente desejado. O *target* padrão é `dev_pessoal`:
```bash
# Ambiente de desenvolvimento (padrão)
databricks bundle deploy --target dev_pessoal

# Ambiente de produção
databricks bundle deploy --target prod
```
> Targets disponíveis: `dev_pessoal` (default), `dev` e `prod`.

### 6. Execução do Job de Ingestão
Dispare manualmente o *job* de ingestão (chave `ingestion` no bundle):
```bash
databricks bundle run ingestion
```
> Em produção, além da execução manual, o *job* roda automaticamente todos os dias às **01:00 (America/Sao_Paulo)** conforme o agendamento *cron* configurado em `resources/ingestion.job.yml`.

### 7. Execução dos Testes
Para rodar os testes unitários localmente:
```bash
uv run pytest
```
