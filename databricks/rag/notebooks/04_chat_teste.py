# Databricks notebook source
# MAGIC %md
# MAGIC # 04_chat_teste — chat de desenvolvimento (widgets do notebook)
# MAGIC Ferramenta de iteração (§13.2): ajuste prompt / `final_k` / threshold e
# MAGIC repergunte em segundos, sem deploy. Cada pergunta é independente (§9.3) —
# MAGIC sem histórico entrando no prompt.
# MAGIC
# MAGIC **Como perguntar:** edite o widget **`pergunta`** na barra de widgets no
# MAGIC topo do notebook e rode de novo só a célula **RESPONDER** (não precisa de
# MAGIC Run All). Usamos widgets nativos do notebook em vez de `ipywidgets`: um
# MAGIC callback de botão/`on_submit` roda fora do ciclo normal de execução de
# MAGIC célula, e o token de autenticação automática do notebook só é injetado
# MAGIC durante esse ciclo normal — daí o `RuntimeError: Missing api_token` /
# MAGIC `APIConnectionError` se você tentar chamar o LLM de dentro de um callback.

# COMMAND ----------

# MAGIC %pip install databricks-ai-search "databricks-sdk[openai]" openai
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# Sem valor padrão: o job recebe estes parâmetros do bundle e, ao abrir o notebook na
# interface, o _bootstrap os descobre sozinho a partir do job implantado (sem preencher nada).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema_gold", "")
dbutils.widgets.text("schema_rag", "")

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

from rag.generator import Generator
from rag.retriever import Retriever

retriever, generator = Retriever(CFG), Generator(CFG)

# COMMAND ----------

dbutils.widgets.text("pergunta", "Como funciona a arquitetura de ingestão do projeto?")
dbutils.widgets.dropdown("ver_chunks", "sim", ["sim", "nao"])

# COMMAND ----------

# RESPONDER — edite o widget "pergunta" no topo do notebook e rode só esta célula.
import time

from IPython.display import Markdown, display

pergunta = dbutils.widgets.get("pergunta").strip()
if pergunta:
    display(Markdown(f"**Você:** {pergunta}"))
    t0 = time.time()
    chunks = retriever.search(pergunta)
    lat_ret = int((time.time() - t0) * 1000)
    resposta, lat_llm = generator.answer(pergunta, chunks)

    display(Markdown(f"**Assistente:** {resposta}"))
    display(Markdown(
        f"<sub>retrieval {lat_ret} ms · geração {lat_llm} ms · "
        f"{len(chunks)} chunks · recusou: {resposta.startswith('Não encontrei')}</sub>"
    ))
    if dbutils.widgets.get("ver_chunks") == "sim" and chunks:
        linhas = "\n".join(
            f"- `{c.score:.4f}` **{c.titulo}** — `{c.chunk_id}`" for c in chunks)
        display(Markdown(f"<details><summary>Trechos</summary>\n\n{linhas}\n</details>"))
