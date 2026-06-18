A estrutura do bundle é:

- `src/grupo10/` → pacote Python compartilhado (a lógica reutilizável vai aqui).
- `src/sqlserver_ingest.ipynb` → o notebook orquestrador.
- `tests/` → testes unitários.
- `resources/*.yml` → a orquestração no Databricks (job que roda diariamente).

A proposta é criar um arquivo novo, **`src/grupo10/ingestion.py`**, com duas funções: `extrair_tabela()` e `carregar_bronze()`. O notebook passa a **importar** essas funções de lá.

## Exemplo de código

### Função de extração — `extrair_tabela()`

```python
# src/grupo10/ingestion.py
from datetime import datetime
from databricks.sdk.runtime import spark
import pyspark.sql.functions as F
from pyspark.sql import DataFrame


def extrair_tabela(tabela: str, jdbc_url: str, conn: dict) -> DataFrame:
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
    batch_id = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return (
        spark.read.format("jdbc").options(**jdbc_options).load()
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_origin", F.lit(f"sql_server_{tabela}"))
        .withColumn("_batch_id", F.lit(batch_id))
    )
```

Explicação:

- ** `(tabela: str, jdbc_url: str, conn: dict) -> DataFrame`** a função recebe o nome de uma tabela, a URL de conexão e um dicionário com as credenciais, e devolve um DataFrame. Os (`str`, `dict`, `DataFrame`) são uma boa prática — documentam o que entra e o que sai, e seguem o mesmo estilo que já existe no `taxis.py` do projeto.
- ** `jdbc_url` e `conn` como parâmetros** em vez de buscar os segredos dentro da função? Porque uma função modular não deve depender de variáveis globais escondidas. Quem chama a função é responsável por fornecer as credenciais (que vêm dos segredos no notebook). Isso deixa a função **pura e testável**: num teste, você pode passar uma conexão de mentira.
- **As colunas de auditoria** (`_ingested_at`, `_source_origin`, `_batch_id`) A diferença é que agora ficam centralizadas: toda tabela extraída ganha essas colunas automaticamente, e se a regra mudar, muda só aqui.
- O `batch_id` inclui hora/minuto/segundo (`"%Y-%m-%dT%H:%M:%S"`) em vez de só a data. Isso é o ajuste de granularidade: garante que dois runs no mesmo dia tenham IDs diferentes — útil para o futuro.

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

```python
from grupo10.ingestion import extrair_tabela, carregar_bronze

conn = {
    "user": dbutils.secrets.get(scope="sqlserver", key="username"),
    "password": dbutils.secrets.get(scope="sqlserver", key="password"),
}
jdbc_url = f"jdbc:sqlserver://{host}:{port};databaseName={db}"

for tabela in tabelas_nomes:
    df = extrair_tabela(tabela, jdbc_url, conn)
    destino = carregar_bronze(df, tabela)
    print(f"Tabela {destino} salva!")
```

Busca os segredos, monta a URL, e para cada tabela chama as duas funções. Qualquer pessoa do time bate o olho e entende o fluxo inteiro em segundos. Toda a complexidade técnica (opções do JDBC, colunas de auditoria, modo de escrita) está escondida dentro das funções, em `ingestion.py`.


