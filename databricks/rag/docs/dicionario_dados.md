# Dicionário de Dados — camada gold

Documento curado de apoio (`doc_type: decisao_tecnica` no carregamento de
markdown). O dicionário detalhado e sempre atualizado é **gerado** pelo
`build_dicionario_dados` a partir do `information_schema`; este arquivo cobre o
grão e o propósito de cada tabela em linguagem de negócio.

> HIPÓTESE H1: nomes e grãos abaixo refletem a modelagem dimensional do projeto
> dbt (`dbt/models/marts`) e devem ser conferidos contra o DW real.

## Fatos

- **fct_sales** — grão: um item de venda por pedido (produto x pedido). Métricas:
  quantidade, valor de linha, valor convertido para BRL. Usada para o histórico
  que alimenta a previsão de demanda.
- **fct_purchases** — grão: um item de compra por ordem de compra
  (produto x ordem). Usada na análise de fornecimento.
- **fct_returns** — grão: um item devolvido por devolução. Usada para líquido de
  vendas.
- **fct_daily_stock_levels** — grão: produto x localidade x dia. Nível de estoque
  diário; base do snapshot de estoque.

## Dimensões

- **dim_products** — um registro por produto (SKU). Nome, categoria, atributos.
- **dim_customers** — um registro por cliente.
- **dim_employees** — um registro por funcionário.
- **dim_locations** — um registro por localidade. Cobre lojas e centros de
  distribuição, diferenciados por tipo.
- **dim_suppliers** — um registro por fornecedor.
- **dim_calendary** — um registro por dia. Dimensão de calendário contígua.

## Saída da modelagem (a materializar — HIPÓTESE H2)

- **fct_forecast** — grão: produto x loja x mês. Contém quantidade prevista,
  nome do modelo vencedor, MAE, RMSE, MAPE, total do baseline de média móvel de
  3 meses e média mensal dos últimos 12 meses.
- **model_evaluation** — grão: um registro por modelo candidato. Contém MAE,
  RMSE e MAPE comparáveis entre candidatos.
