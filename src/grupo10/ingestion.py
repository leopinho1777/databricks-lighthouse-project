"""
Funções de ingestão da camada Bronze (extração do SQL Server + carga em Delta).

Este módulo concentra a lógica reutilizável que antes vivia inline dentro do
loop do notebook orquestrador `src/sqlserver_ingest.ipynb`. A ideia da
modularização (ver `docs/modularidade.md`) é deixar o notebook responsável
apenas por *orquestrar* (segredos, loop, logging, auditoria) e mover a
complexidade técnica (opções JDBC, colunas de auditoria, modo de escrita)
para funções puras e testáveis aqui.

EVA — Transferência das funções do Markdown (`docs/modularidade.md`) para
código Python de verdade, conforme a task de modularidade.
"""

from databricks.sdk.runtime import spark
import pyspark.sql.functions as F
from pyspark.sql import DataFrame


def extrair_tabela(tabela: str, jdbc_url: str, conn: dict, batch_id: str) -> DataFrame:
    """Lê uma tabela do SQL Server via JDBC e adiciona as colunas de auditoria.

    Args:
        tabela:   Nome da tabela de origem no SQL Server (vira `dbtable`).
        jdbc_url: URL JDBC já montada (jdbc:sqlserver://host:port;databaseName=...).
        conn:     Dicionário com as credenciais — espera as chaves "user" e
                  "password". Passar a conexão como parâmetro (em vez de buscar
                  os segredos aqui dentro) mantém a função pura e testável:
                  quem chama é responsável por fornecer as credenciais.
        batch_id: Identificador do lote, gerado UMA vez pelo orquestrador e
                  compartilhado por todas as tabelas do mesmo run. EVA — recebido
                  como parâmetro (e não gerado aqui dentro) justamente para que
                  todas as tabelas de um run tenham o MESMO _batch_id; do
                  contrário cada chamada teria um id diferente e o "lote"
                  deixaria de identificar o run. Esse contrato é o ponto de
                  encontro com a orquestração incremental em batches do Gabriel.

    Returns:
        DataFrame da tabela já com as colunas `_ingested_at`, `_source_origin`
        e `_batch_id`.
    """
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
        spark.read.format("jdbc")
        .options(**jdbc_options)
        .load()
        # EVA — Colunas de auditoria centralizadas: toda tabela extraída ganha
        # essas três colunas automaticamente. Se a regra mudar, muda só aqui.
        .withColumn("_ingested_at", F.current_timestamp())            # quando foi ingerido
        .withColumn("_source_origin", F.lit(f"sql_server_{tabela}"))  # de onde veio
        .withColumn("_batch_id", F.lit(batch_id))                     # identificador do lote
    )


def carregar_bronze(
    df: DataFrame,
    nome_tabela: str,
    catalog: str = "lh_nautical",
    schema: str = "bronze",
) -> str:
    """Grava o DataFrame na camada Bronze em Delta usando overwrite (idempotente).

    Args:
        df:          DataFrame a ser gravado (tipicamente vindo de `extrair_tabela`).
        nome_tabela: Nome da tabela de destino dentro do schema Bronze.
        catalog:     Catálogo de destino. Default = "lh_nautical"; pode ser
                     trocado (ex.: ambiente de teste) sem reescrever a função.
        schema:      Schema de destino. Default = "bronze".

    Returns:
        Nome totalmente qualificado da tabela escrita (catalog.schema.tabela),
        para o orquestrador poder logar/auditar. A função não imprime nada por
        conta própria — quem decide o que fazer com a informação é o orquestrador.
    """
    output_table = f"{catalog}.{schema}.{nome_tabela}"
    # EVA — mode("overwrite") é o que garante a idempotência: rodar de novo
    # substitui a tabela inteira em vez de duplicar linhas. A decisão fica
    # encapsulada e documentada num único lugar.
    df.write.format("delta").mode("overwrite").saveAsTable(output_table)
    return output_table
