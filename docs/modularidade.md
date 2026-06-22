A estrutura do bundle é:

- `src/grupo10/` → pacote Python compartilhado (a lógica reutilizável vai aqui).
- `src/sqlserver_ingest.ipynb` → o notebook orquestrador.
- `tests/` → testes unitários.
- `resources/*.yml` → a orquestração no Databricks (job que roda diariamente).

A proposta é criar um arquivo novo, **`src/grupo10/ingestion.py`**, com duas funções: `extrair_tabela()` e `carregar_bronze()`. O notebook passa a **importar** essas funções de lá.

> **Status:** já implementado. O módulo `src/grupo10/ingestion.py` existe e o notebook `src/sqlserver_ingest.ipynb` já foi refatorado para importar e chamar essas funções (a lógica inline de JDBC, colunas de auditoria e escrita saiu do notebook).

## Exemplo de código

### Função de extração — `extrair_tabela()`

```python
# src/grupo10/ingestion.py
from databricks.sdk.runtime import spark
import pyspark.sql.functions as F
from pyspark.sql import DataFrame


def extrair_tabela(tabela: str, jdbc_url: str, conn: dict, batch_id: str) -> DataFrame:
    """Lê uma tabela do SQL Server e adiciona colunas de auditoria."""
    jdbc_options = {
        "url": jdbc_url,
        "dbtable": tabela,
        "user": conn["user"],
        "password": conn["password"],
        "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
        "encrypt": "true",
        "trustServerCertificate": "true",
        "loginTimeout": "30",
        "fetchsize": "1000",
    }
    return (
        spark.read.format("jdbc").options(**jdbc_options).load()
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_origin", F.lit(f"sql_server_{tabela}"))
        .withColumn("_batch_id", F.lit(batch_id))
    )
```

Explicação:

- ** `(tabela: str, jdbc_url: str, conn: dict, batch_id: str) -> DataFrame`** a função recebe o nome de uma tabela, a URL de conexão, um dicionário com as credenciais e o id do lote, e devolve um DataFrame. Os type hints (`str`, `dict`, `DataFrame`) são uma boa prática — documentam o que entra e o que sai, e seguem o mesmo estilo que já existe no `taxis.py` do projeto.
- ** `jdbc_url` e `conn` como parâmetros** em vez de buscar os segredos dentro da função? Porque uma função modular não deve depender de variáveis globais escondidas. Quem chama a função é responsável por fornecer as credenciais (que vêm dos segredos no notebook). Isso deixa a função **pura e testável**: num teste, você pode passar uma conexão de mentira.
- **As colunas de auditoria** (`_ingested_at`, `_source_origin`, `_batch_id`) A diferença é que agora ficam centralizadas: toda tabela extraída ganha essas colunas automaticamente, e se a regra mudar, muda só aqui.
- **O `batch_id` agora vem por parâmetro** (e não é gerado dentro da função). Decisão de design: um `_batch_id` representa um *run* inteiro, então todas as tabelas do mesmo run precisam compartilhar o mesmo valor. Se a função gerasse o id internamente, cada tabela receberia um `batch_id` diferente (porque `datetime.now()` muda a cada chamada) e o "lote" deixaria de identificar o run. Quem gera o id é o orquestrador, **uma vez antes do loop**. Esse contrato é também o ponto de contato com a orquestração incremental em batches do Gabriel — ele controla o que é um "lote".

### Função de carga — `carregar_bronze()`

```python
def carregar_bronze(df: DataFrame, nome_tabela: str,
    catalog: str = "lh_nautical", schema: str = "bronze") -> str:
    """Grava o DataFrame na camada bronze em Delta (overwrite = idempotente)."""
    output_table = f"{catalog}.{schema}.{nome_tabela}"
    df.write.format("delta").mode("overwrite").saveAsTable(output_table)
    return output_table
```

Explicação:

- **Por padrão grava no destino certo, mas se um dia precisarem gravar em outro schema (por exemplo, num ambiente de teste), é só passar outro valor, sem reescrever a função.
- **O `mode("overwrite")` é o que garante a idempotência** — A função encapsula essa decisão, então a garantia de idempotência fica documentada e centralizada num único lugar.
- A função **retorna o nome da tabela** (`output_table`) para quem chamou poder logar/imprimir. Ela não imprime nada por conta própria — quem decide o que fazer com essa informação é o orquestrador.

### O notebook orquestrador (depois da modularização)

Esta é a forma que o `src/sqlserver_ingest.ipynb` realmente tem hoje. Além de chamar as duas funções, o orquestrador é também o responsável por **logging** e **auditoria** (que ficam de fora das funções puras, de propósito):

```python
from datetime import datetime
from grupo10.ingestion import extrair_tabela, carregar_bronze

# Credenciais agrupadas num dict -> mantém as funções puras e testáveis
conn = {
    "user": dbutils.secrets.get(scope="sqlserver", key="username"),
    "password": dbutils.secrets.get(scope="sqlserver", key="password"),
}
jdbc_url = f"jdbc:sqlserver://{host}:{port};databaseName={db}"

# Um único batch_id para todo o run — compartilhado por todas as tabelas
batch_id = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

failed_tables = []
for table in target_tables:
    start = time.time()
    try:
        logger.info(f"Starting extraction: {table}")

        df = extrair_tabela(table, jdbc_url, conn, batch_id)
        output_table = carregar_bronze(df, table)

        row_count = df.count()
        duration = time.time() - start
        logger.info(f"Done: {output_table} | rows={row_count} | duration={duration:.2f}s")
        write_audit_record(spark=spark, table_name=table, status="success",
                           duration_seconds=duration, row_count=row_count,
                           audit_table=AUDIT_TABLE)
    except Exception as e:
        duration = time.time() - start
        logger.error(f"Failed: {table} | duration={duration:.2f}s | error={e}")
        failed_tables.append(table)
        write_audit_record(spark=spark, table_name=table, status="failed",
                           duration_seconds=duration, error_message=str(e),
                           audit_table=AUDIT_TABLE)
```

Busca os segredos, monta a URL, gera **um** `batch_id` do run e, para cada tabela, chama as duas funções. Toda a complexidade técnica (opções do JDBC, colunas de auditoria, modo de escrita) está escondida dentro das funções, em `ingestion.py`. O que **sobra** no notebook é justamente o papel de orquestração:

- **Logging** (`logger.info/error`) — acompanhar o progresso e o tempo de cada tabela.
- **Auditoria** (`write_audit_record`) — registrar sucesso/falha de cada tabela na tabela `_ingestion_audit`.
- **Tolerância a falha** (`try/except` + `failed_tables`) — uma tabela que falha não derruba o run inteiro; as falhas são coletadas e reportadas no final.

Essas três responsabilidades ficam de fora das funções de propósito: `extrair_tabela`/`carregar_bronze` continuam puras (sem efeitos colaterais de log/print), e quem decide o que fazer com o resultado é o orquestrador.


