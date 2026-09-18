# Decisões Técnicas do Projeto LH Nautical

Documento curado para o corpus do RAG (`doc_type: decisao_tecnica`). Uma seção
por decisão relevante, com a alternativa considerada e o motivo da rejeição.

## Por que dbt para a transformação

O dbt dá modelagem em camadas versionada, testes de dados declarativos,
documentação de linhagem e isolamento por desenvolvedor via schema com prefixo.
A alternativa de notebooks PySpark soltos foi rejeitada por não ter testes de
dados de primeira classe nem linhagem navegável, e por dificultar revisão em
pull request.

## Por que Databricks Asset Bundles

Cada artefato implantável do projeto é um bundle com targets `dev` e `prod` e
variáveis de catálogo e schema. Isso mantém a infraestrutura como código,
reproduzível por `databricks bundle deploy`, e permite o mesmo fluxo para
ingestão, transformação, atualização de Power BI e RAG.

## Por que RAG documental em vez de Text-to-SQL

O RAG do projeto responde sobre um corpus gerado a partir das tabelas, não
traduzindo perguntas em SQL. Motivos: com Text-to-SQL o modelo passaria a
produzir os números, e um join errado gera uma resposta plausível e falsa
apresentada a executivos; a avaliação exigiria comparar SQL gerado com SQL de
referência para dezenas de casos; cada pergunta consumiria o único SQL warehouse
do ambiente; e Text-to-SQL não responde às perguntas que não são de dados, como
"por que vocês escolheram esse modelo".

## Por que os números são renderizados por template

Todo número que aparece em um documento do corpus vem de uma coluna de uma
tabela Delta, formatado por template determinístico. Agregações como total do
trimestre e variação percentual são calculadas em Spark, antes de chegarem ao
modelo. O LLM só seleciona e redige, nunca calcula. Isso reduz ao mínimo a
superfície de alucinação numérica.

## Por que busca híbrida

As perguntas citam SKUs, códigos de loja e nomes próprios, que são termos
literais que a busca puramente semântica erra. A busca híbrida combina
similaridade de vetores com correspondência de palavra-chave (BM25) por fusão
Reciprocal Rank Fusion.

## Por que sync TRIGGERED e não CONTINUOUS

O modo contínuo provisiona um cluster de streaming permanente, o que consome
cota de compute continuamente para um corpus que muda uma vez por ciclo de
desenvolvimento. O modo TRIGGERED sincroniza sob demanda, ao fim do job de
ingestão do RAG.

## Por que sem histórico de conversa na primeira versão

As perguntas de negócio são autocontidas. Colocar histórico no prompt injeta
contexto de perguntas anteriores que pode contaminar a resposta atual, e
perguntas de acompanhamento reais exigiriam um passo de reescrita da consulta,
que adiciona latência e mais um ponto de falha.
