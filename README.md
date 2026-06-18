# README #

Repositório para entrega do projeto Lighthouse do Grupo 10 / TeslaVinci

---

# ----------------------------------------------------------------------

### Detalhes dos Arquivos:
* **`src/tabelas_config.json`**: Centraliza os metadados do projeto. Contem o mapeamento exato de todas as tabelas selecionadas do banco relacional com suas respectivas listas de colunas. Evita que o script Spark possua arrays estáticos e "hardcoded", facilitando a inclusão de novas tabelas.
* **`src/sqlserver_ingest.ipynb`**: Notebook estruturado em células conceituais que executa a leitura das credenciais, o loop de processamento por lote (*batch*) com particionamento controlado e a camada de criptografia.

---

## Bibliotecas Utilizadas e Justificativa

* **`pyspark.sql (SparkSession)`**: Motor de computação distribuída em memória utilizado para processar grandes volumes de dados de forma paralela através do cluster.
* **`pyspark.sql.functions (F)`**: Utilizada especificamente pela função `F.sha2()` para aplicar algoritmos criptográficos diretamente nas colunas do DataFrame, e `F.col()` para manipulação das referências de colunas.
* **`json`**: Biblioteca nativa do Python para carregar e interpretar o arquivo de configuração de metadados (`tabelas_config.json`).
* **`databricks.sdk.runtime (dbutils)`**: Utilitário nativo do Databricks usado para interagir com o cofre de chaves de forma segura através do `dbutils.secrets.get()`, impedindo a exposição de senhas e dados confidenciais de conexão em texto limpo no código.

---

## Etapas Detalhadas do Processo

O script `sqlserver_ingest.ipynb` executa rigidamente quatro etapas sequenciais:

### Etapa 1: Inicialização da Infraestrutura (SQL)
A primeira célula garante o isolamento do ambiente criando o catálogo principal e o esquema lógico dentro do **Unity Catalog**:
* `CREATE CATALOG IF NOT EXISTS lh_nautical;`
* `CREATE SCHEMA IF NOT EXISTS lh_nautical.bronze;`

### Etapa 2: Autenticação Segura e Conexão JDBC
O Spark estabelece uma conexão via protocolo JDBC com o banco de dados SQL Server corporativo. As credenciais são extraídas em tempo de execução do escopo de segredos:
* **Segurança:** Uso de criptografia forçada na sessão JDBC (`"encrypt": "true"`, `"trustServerCertificate": "true"`).
* **Performance:** Configuração de `"loginTimeout": "30"` para evitar travamentos de rede e `"fetchsize": "1000"` para otimizar o tamanho dos pacotes de linhas transferidos para o driver do Spark por vez.

### Etapa 3: Descoberta de Dados e Governança Ativa (LGPD)
O loop lê as chaves do arquivo `tabelas_config.json` e, para cada tabela interceptada, verifica a existência de campos mapeados na **Política de Governança PII (Personally Identifiable Information)**.
Se uma coluna sensível for encontrada, o Spark aplica uma transformação aplicando criptografia de sentido único baseada em **SHA-256 (Secure Hash Algorithm 256-bit)**. O dado original é ofuscado e transformado em uma string alfanumérica única e irreversível de 64 caracteres.

## Catálogo de Tabelas e Variáveis (Camada Bronze)

Abaixo está listado o dicionário completo das 24 tabelas ingeridas integralmente para a camada Bronze, detalhando cada variável contida nos esquemas relacionais originais:

* **addresses** (Cadastro de endereços de clientes)
  * `id`, `customer_id`, `address_type`, `postal_code`, `street`, `number`, `complement`, `district`, `city`, `state`, `country`, `is_primary`
* **attributes** (Especificações técnicas de variações de produtos)
  * `id`, `name`, `data_type`
* **brands** (Marcas dos produtos comercializados)
  * `id`, `name`, `country`, `is_active`, `created_at`, `updated_at`
* **categories** (Árvore de categorias de produtos)
  * `id`, `name`, `slug`, `parent_category_id`, `is_active`, `created_at`, `updated_at`
* **customers** (Cadastro de clientes ativos e inativos)
  * `id`, `person_type`, `legal_name`, `trade_name`, `tax_id`, `state_registration`, `email`, `phone`, `is_active`, `created_at`, `updated_at`
* **employees** (Quadro de colaboradores da companhia)
  * `id`, `full_name`, `cpf`, `email`, `role`, `primary_location_id`, `hire_date`, `termination_date`, `is_active`, `created_at`, `updated_at`
* **fiscal_invoices** (Notas fiscais vinculadas a pedidos)
  * `id`, `order_id`, `nfe_number`, `nfe_access_key`, `series`, `issued_at`, `status`, `total_amount`, `xml_storage_uri`, `created_at`, `updated_at`
* **goods_receipts** (Registros de recebimento de cargas no galpão)
  * `id`, `purchase_order_id`, `received_by_employee_id`, `received_at`, `notes`, `created_at`
* **goods_receipt_items** (Vínculo de itens físicos recebidos)
  * `id`, `goods_receipt_id`, `purchase_order_item_id`, `quantity_received`
* **locations** (Centros de distribuição, lojas e galpões físicos)
  * `id`, `name`, `location_type`, `postal_code`, `street`, `number`, `complement`, `district`, `city`, `state`, `country`, `is_active`, `created_at`, `updated_at`
* **orders** (Cabeçalho de pedidos de venda capturados)
  * `id`, `order_number`, `channel`, `customer_id`, `salesperson_id`, `location_id`, `status`, `subtotal`, `discount_amount`, `total`, `placed_at`, `created_at`, `updated_at`
* **order_items** (Linhas de produtos associadas a cada pedido)
  * `id`, `order_id`, `product_variant_id`, `quantity`, `unit_price`, `icms_rate`, `ipi_rate`, `line_total`
* **payments** (Fluxo de transações financeiras dos pedidos)
  * `id`, `order_id`, `method`, `installments`, `amount`, `status`, `paid_at`, `created_at`, `updated_at`
* **products** (Cadastro mestre de produtos da plataforma)
  * `id`, `name`, `description`, `brand_id`, `category_id`, `ncm_code`, `unit_of_measure`, `is_active`, `created_at`, `updated_at`
* **product_suppliers** (Vínculo comercial de custos e prazos com fornecedores)
  * `product_variant_id`, `supplier_id`, `supplier_sku`, `last_quoted_cost`, `lead_time_days`, `is_preferred`, `created_at`, `updated_at`
* **product_variants** (Especificações de SKUs das variantes de produtos)
  * `id`, `product_id`, `sku`, `barcode_ean`, `sale_price`, `cost_price`, `weight_kg`, `icms_rate`, `ipi_rate`, `is_active`, `created_at`, `updated_at`
* **purchase_orders** (Ordens de compra emitidas para fornecedores)
  * `id`, `po_number`, `supplier_id`, `buyer_id`, `destination_location_id`, `status`, `currency`, `subtotal`, `total`, `placed_at`, `expected_delivery_at`, `created_at`, `updated_at`
* **purchase_order_items** (Detalhamento de custos de insumos comprados)
  * `id`, `purchase_order_id`, `product_variant_id`, `quantity_ordered`, `unit_cost`, `line_total`
* **returns** (Solicitações de devolução de mercadorias por clientes)
  * `id`, `return_number`, `order_id`, `customer_id`, `received_at_location_id`, `status`, `reason`, `total_refund_amount`, `created_at`, `updated_at`
* **return_items** (Detalhamento de SKUs devolvidos ou trocados)
  * `id`, `return_id`, `order_item_id`, `quantity`, `action`, `exchange_variant_id`, `unit_refund_amount`
* **stock_levels** (Balanço de inventário atual por localidade)
  * `product_variant_id`, `location_id`, `quantity_on_hand`, `reorder_point`, `updated_at`
* **stock_movements** (Histórico de entradas e saídas de inventário físico)
  * `id`, `product_variant_id`, `location_id`, `movement_type`, `quantity`, `reference_table`, `reference_id`, `employee_id`, `notes`, `occurred_at`, `created_at`
* **suppliers** (Cadastro de fornecedores parceiros)
  * `id`, `legal_name`, `trade_name`, `country`, `tax_id`, `tax_id_type`, `email`, `phone`, `contact_name`, `is_active`, `created_at`, `updated_at`
* **variant_attribute_values** (Valores específicos atribuídos às variantes)
  * `product_variant_id`, `attribute_id`, `value`

---

## Política de Mascaramento Externa e LGPD (`governanca_config.json`)

Para conformidade com as diretrizes de governança de dados e LGPD, variáveis contendo dados pessoais identificáveis (PII) ou metadados críticos sofrem criptografia de sentido único via hash **SHA-256** em tempo de execução.

Campos afetados mapeados no arquivo de configuração externa:
* **customers**: `legal_name`, `trade_name`, `tax_id`, `email`
* **employees**: `full_name`, `cpf`, `email`
* **suppliers**: `legal_name`, `trade_name`, `tax_id`
* **fiscal_invoices**: `nfe_access_key`, `xml_storage_uri`
* **goods_receipts**: `notes`

### Etapa 4: Carga e Persistência em Formato Delta
Os DataFrames processados e mascarados em memória são persistidos diretamente no armazenamento sob o formato **Delta Lake**. A escrita utiliza o modo `.mode("overwrite")` com o método `.saveAsTable()`, garantindo a criação de tabelas gerenciadas com suporte a transações ACID, histórico de versão (*Time Travel*) e otimização de índices para as fases futuras (Silver e Gold).

---

## Como Executar o Pipeline

1. Certifique-se de que o ambiente virtual está ativo e o Databricks Connect configurado:
   ```powershell
   .venv\Scripts\Activate.ps1