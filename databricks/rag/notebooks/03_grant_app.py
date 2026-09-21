# Databricks notebook source
# MAGIC %md
# MAGIC # 03_grant_app — dá ao app acesso de leitura ao índice (task final do job)
# MAGIC O app roda como um service principal próprio. O bundle já concede warehouse, modelo e
# MAGIC a tabela de logs; o `SELECT` no índice vetorial é concedido aqui, para que o deploy
# MAGIC funcione de ponta a ponta sem nenhum passo manual. Idempotente.

# COMMAND ----------

# Sem valor padrão: o job recebe estes parâmetros do bundle (e o _bootstrap os descobre sozinho
# quando o notebook é aberto na interface).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema_gold", "")
dbutils.widgets.text("schema_rag", "")
dbutils.widgets.text("app_name", "")

# COMMAND ----------

# MAGIC %run ./_bootstrap

# COMMAND ----------

import os

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import PermissionsChange, Privilege

app_name = os.environ.get("RAG_APP_NAME")
assert app_name, "parâmetro app_name ausente no job implantado"

w = WorkspaceClient()
sp = w.apps.get(app_name).service_principal_client_id
assert sp, f"o app {app_name} ainda não tem service principal"

w.grants.update(
    securable_type="table",  # string: aceita por todas as versões do SDK
    full_name=CFG.index_name,
    changes=[PermissionsChange(principal=sp, add=[Privilege.SELECT])],
)
print(f"SELECT em {CFG.index_name} concedido ao app {app_name} ({sp})")
