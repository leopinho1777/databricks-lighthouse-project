# README #

Repositório para entrega do projeto Lighthouse do Grupo 10 / TeslaVinci

### How do I get set up? ###

* Summary of set up
* Configuration
* Dependencies
* Database configuration
* How to run tests
* Deployment instructions

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

#### Mapeamento de Campos Protegidos:
* **`customers`**: `legal_name`, `trade_name`, `tax_id` (CPF/CNPJ), `email`
* **`employees`**: `full_name`, `cpf`, `email`
* **`suppliers`**: `legal_name`, `trade_name`, `tax_id`
* **`fiscal_invoices`**: `nfe_access_key`, `xml_storage_uri`
* **`goods_receipts`**: `notes` (Prevenção contra vazamento em comentários de texto aberto)

### Etapa 4: Carga e Persistência em Formato Delta
Os DataFrames processados e mascarados em memória são persistidos diretamente no armazenamento sob o formato **Delta Lake**. A escrita utiliza o modo `.mode("overwrite")` com o método `.saveAsTable()`, garantindo a criação de tabelas gerenciadas com suporte a transações ACID, histórico de versão (*Time Travel*) e otimização de índices para as fases futuras (Silver e Gold).

---

## Como Executar o Pipeline

1. Certifique-se de que o ambiente virtual está ativo e o Databricks Connect configurado:
   ```powershell
   .venv\Scripts\Activate.ps1