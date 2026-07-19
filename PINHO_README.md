# TODO
- Ver uso do main.py no src/grupo10
- alterar tabelas_config para job parameters (vice versa)
!!! - Scrip to setup everything on another workspace
!!! - IaC usando yml
- Remover a tabelas de ingestão de dentro do src
- Adicionar descrição para cada função
- Adicionar testes
- Configurar DEV e PROD para variáveis no databricks.yml
- retirar o CREATE catalog e CREATE schema de dev to notebook de ingestão
- entender _merge_into_delta(), run_incremental_ingestion()
-checar se cron funciona
- remover tabelas_config2v
- renomear tabelas config para inglês
- elencar tudo que trabalha em pŕo da idempotência
- identificar tudo que está em portugues no código e passar para inglês
- Como eu sei que se o job falha na última task as pessoas não podem acabar vendo tudo nas tabelas?
- Qual o POP quando uma tabela dá errado? Qual o procedimento para falhas em diferentes tasks dessa job?
- Não tem que mascarar o endereço?
- Por implementar 

- Por que disso abaixo?
Single key (e.g. "id") → existing watermark pagination, writes via MERGE
Composite key (e.g. ["product_variant_id", "location_id"]) → reads entire table, writes via MERGE (full reload, idempotent)
All writes are now idempotent — no more duplicates on re-run

- Entender melhor a lógica da ingestão das tabelas com mais de uma chave
How MERGE INTO Works (The "Upsert")
The MERGE INTO command is often called an upsert because it combines an UPDATE and an INSERT into a single smart operation. It uses the source primary key as a tracking beacon.

- review uupdate control table update logic when task fails midtable:
What changed: update_control_table moved from inside the loop to once after all batches complete. This reduces control table MERGEs from N batches down to 1 per table run.

Trade-off: If the job fails mid-table, the control table won't have the intermediate checkpoint — the next run will restart that table from the beginning. For most tables this is fine. If you have a table so large that restarting is too expensive, you can checkpoint every N batches instead. But for now the priority is stopping the performance death spiral.

- Como são os warnings the erro de ingestão


O que fazer: Crie funções como extrair_tabela(tabela) e carregar_bronze(df, nome_tabela).

Por que: Facilita os testes unitários e melhora a clareza do código.

Idempotência: O uso do .mode("overwrite") já garante idempotência (você pode rodar 100 vezes que o resultado final será o mesmo), mas adicione logs para que, ao final, você saiba exatamente quais tabelas falharam.


# Apresentação
## idempotência
- 'if not exists' nos DDLs (data definition language)
- logger handler no logger.py
- criação da tabela de controle em ingest.py
- _merge_into_delta() do ingest.py



#Criação dos segredos

# Na versão moderna (CLI v2), basta digitar os nomes em sequência:
databricks secrets create-scope sqlserver
databricks secrets put-secret sqlserver jdbc-url --string-value "sua_url_aqui"
jdbc:sqlserver://<18.209.218.63>:<4563>;databaseName=<lh_nautical>


databricks secrets put-secret sqlserver username --string-value "seu_user_aqui"
databricks secrets put-secret sqlserver password --string-value "sua_senha_aqui"
databricks secrets put-secret sqlserver host --string-value "sua_senha_aqui"
databricks secrets put-secret sqlserver port --string-value "sua_senha_aqui"
databricks secrets put-secret sqlserver db --string-value "sua_senha_aqui"

# rodar testes
uv run pytest tests/unit/ -v

# Cross-check com entrega:
Missing:

Technical (code) — all gaps were already listed: PII masking, infinite loop bug, logger, databricks.yml env wiring, widget vs file-reading hack.

Delivery (repo) — the one remaining item the rubric explicitly requires that wasn't in the previous list: a job schedule. The rubric frames this as an "orchestrated pipeline", but ingestion.job.yml has no schedule: block — it can only be triggered manually. This is a minor gap; a daily cron would complete the orchestration story.

# Tables com outro primary ID
stock-levels
return_items

# Mudanças
- tables_config.json -> tables_config.json