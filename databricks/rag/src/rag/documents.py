"""Gera os documentos textuais do RAG a partir das tabelas gold.

Regra inegociável (§6.3): todo número que aparece no corpo vem de uma coluna de
uma tabela Delta, formatado por template. Nenhum número é calculado pelo LLM.

HIPÓTESE H1/H2: os nomes de colunas abaixo refletem uma modelagem dimensional
típica e DEVEM ser conferidos contra o DW real antes da primeira execução.
"""
from __future__ import annotations

import datetime
import hashlib
import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

DOC_SCHEMA = (
    "doc_id string, doc_type string, titulo string, corpo string, "
    "produto_id string, produto_nome string, loja_id string, loja_nome string, "
    "cd_id string, cd_nome string, periodo string, fonte string, "
    "content_hash string, atualizado_em timestamp"
)


def _fmt_int(col):
    """Inteiro no padrão brasileiro: 1234 -> '1.234'."""
    return F.regexp_replace(F.format_number(col, 0), ",", ".")


def _fmt_pct(col):
    """Percentual: 0.238 -> '23,8%'."""
    return F.concat(
        F.regexp_replace(F.format_number(col * 100, 1), r"\.", ","), F.lit("%")
    )


def build_previsao_produto_loja(spark: SparkSession, cfg) -> DataFrame:
    """Um documento por par produto x loja, cobrindo os 3 meses previstos."""
    fc = spark.table(cfg.gold("fct_forecast"))
    dp = spark.table(cfg.gold("dim_product"))
    ds = spark.table(cfg.gold("dim_store"))

    meses = (
        fc.join(dp, "product_sk")
        .join(ds, "store_sk")
        .groupBy(
            "product_id", "product_name", "store_id", "store_name",
            "dc_id", "dc_name", "model_name", "mae", "rmse", "mape",
            "baseline_ma3_total", "media_mensal_12m",
        )
        .agg(
            F.sort_array(F.collect_list(F.struct("month", "forecast_qty"))).alias("serie"),
            F.sum("forecast_qty").alias("total_trimestre"),
            F.min("month").alias("mes_ini"),
            F.max("month").alias("mes_fim"),
        )
    )

    serie_txt = F.expr(
        """
        concat_ws(', ', transform(serie,
            x -> concat(format_number(x.forecast_qty, 0), ' unidades em ',
                        date_format(x.month, 'MMMM/yyyy'))))
        """
    )

    corpo = F.concat(
        F.lit("Para o produto "), F.col("product_name"),
        F.lit(" (SKU "), F.col("product_id"), F.lit(") na loja "), F.col("store_name"),
        F.lit(" ("), F.col("store_id"), F.lit("), a previsão de demanda é de "),
        serie_txt,
        F.lit(", totalizando "), _fmt_int(F.col("total_trimestre")),
        F.lit(" unidades no trimestre. A média mensal dos últimos 12 meses foi de "),
        _fmt_int(F.col("media_mensal_12m")),
        F.lit(" unidades, o que representa variação de "),
        _fmt_pct(F.col("total_trimestre") / (F.col("media_mensal_12m") * 3) - 1),
        F.lit(" no período previsto. O modelo utilizado foi "), F.col("model_name"),
        F.lit(" (MAE "), F.format_number("mae", 1),
        F.lit(" / RMSE "), F.format_number("rmse", 1),
        F.lit(" / MAPE "), _fmt_pct(F.col("mape")),
        F.lit("). O baseline de média móvel de 3 meses projetaria "),
        _fmt_int(F.col("baseline_ma3_total")),
        F.lit(" unidades no mesmo período. Esta loja é atendida pelo centro de distribuição "),
        F.col("dc_name"), F.lit(" ("), F.col("dc_id"), F.lit(")."),
    )

    return meses.select(
        F.concat_ws(":", F.lit("previsao_produto_loja"),
                    F.col("product_id"), F.col("store_id")).alias("doc_id"),
        F.lit("previsao_produto_loja").alias("doc_type"),
        F.concat(F.lit("Previsão de demanda — "), F.col("product_name"),
                 F.lit(" ("), F.col("product_id"), F.lit(") na "),
                 F.col("store_name"), F.lit(" ("), F.col("store_id"),
                 F.lit(")")).alias("titulo"),
        corpo.alias("corpo"),
        F.col("product_id").alias("produto_id"),
        F.col("product_name").alias("produto_nome"),
        F.col("store_id").alias("loja_id"),
        F.col("store_name").alias("loja_nome"),
        F.col("dc_id").alias("cd_id"),
        F.col("dc_name").alias("cd_nome"),
        F.concat_ws("..", F.date_format("mes_ini", "yyyy-MM"),
                    F.date_format("mes_fim", "yyyy-MM")).alias("periodo"),
        F.lit(cfg.gold("fct_forecast")).alias("fonte"),
        F.sha2(corpo, 256).alias("content_hash"),
        F.current_timestamp().alias("atualizado_em"),
    )


def build_dicionario_dados(spark: SparkSession, cfg) -> DataFrame:
    """Um documento por tabela gold, gerado do information_schema.

    Barato, sempre correto e responde a boa parte das perguntas de arquitetura.
    """
    cat, sch = cfg.raw["catalog"], cfg.raw["schema_gold"]
    cols = spark.sql(
        f"""
        SELECT table_name,
               column_name,
               data_type,
               comment AS column_comment
        FROM {cat}.information_schema.columns
        WHERE table_schema = '{sch}'
        ORDER BY table_name, ordinal_position
        """
    )

    linha_col = F.concat_ws(
        " ",
        F.lit("- Coluna"), F.col("column_name"),
        F.lit("("), F.col("data_type"), F.lit(")"),
        F.coalesce(F.concat(F.lit(": "), F.col("column_comment")), F.lit("")),
    )

    por_tabela = cols.groupBy("table_name").agg(
        F.concat_ws("\n", F.collect_list(linha_col)).alias("colunas_txt")
    )

    corpo = F.concat(
        F.lit("A tabela "), F.lit(f"{cat}.{sch}."), F.col("table_name"),
        F.lit(" contém as colunas:\n"), F.col("colunas_txt"),
    )

    return por_tabela.select(
        F.concat_ws(":", F.lit("dicionario_dados"), F.col("table_name")).alias("doc_id"),
        F.lit("dicionario_dados").alias("doc_type"),
        F.concat(F.lit("Dicionário de dados — "), F.col("table_name")).alias("titulo"),
        corpo.alias("corpo"),
        *[F.lit(None).cast("string").alias(c) for c in
          ("produto_id", "produto_nome", "loja_id", "loja_nome", "cd_id", "cd_nome", "periodo")],
        F.lit(f"{cat}.information_schema.columns").alias("fonte"),
        F.sha2(corpo, 256).alias("content_hash"),
        F.current_timestamp().alias("atualizado_em"),
    )


def load_markdown_docs(spark: SparkSession, cfg, folder: str = "docs") -> DataFrame:
    """Lê docs/*.md do repositório e transforma cada arquivo em um documento."""
    linhas = []
    for nome in sorted(os.listdir(folder)):
        if not nome.endswith(".md"):
            continue
        texto = open(os.path.join(folder, nome), encoding="utf-8").read()
        doc_type = "arquitetura" if "arquitetura" in nome else "decisao_tecnica"
        titulo = next((ln.lstrip("# ").strip() for ln in texto.splitlines()
                       if ln.strip()), nome)
        linhas.append((
            f"{doc_type}:{nome}", doc_type, titulo, texto,
            None, None, None, None, None, None, None,
            f"docs/{nome}",  # origem relativa ao repo, não o caminho do workspace
            hashlib.sha256(texto.encode()).hexdigest(),
            datetime.datetime.utcnow(),
        ))
    return spark.createDataFrame(linhas, DOC_SCHEMA)


def upsert_documents(spark: SparkSession, cfg, df: DataFrame) -> None:
    """Escrita idempotente: doc_id determinístico + content_hash (§6.2)."""
    df.createOrReplaceTempView("novos_docs")
    spark.sql(
        f"""
        MERGE INTO {cfg.rag('documents')} AS d
        USING novos_docs AS n
          ON d.doc_id = n.doc_id
        WHEN MATCHED AND d.content_hash <> n.content_hash THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        WHEN NOT MATCHED BY SOURCE THEN DELETE
        """
    )
