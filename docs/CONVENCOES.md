# Projeto `desafio_lh` — Convenções e Guia de Leitura

Documento de contexto para acompanhar o arquivo `dbt_marts_context.json`.
Plataforma: **Databricks**. Schema dos marts: `develop.pinho_analytics_marts`.

> ⚠️ CONFIRMAR: o catálogo `develop` sugere que o JSON foi gerado a partir do
> ambiente de desenvolvimento. Se produção usa outro catálogo/schema, registrar
> aqui o nome de produção — caso contrário as relações citadas nas respostas
> apontarão para o ambiente errado.

---

## 1. Arquitetura em camadas

```
bronze.*  (sources)  →  stg_*  →  int_*  →  marts (dim_ / fct_ / agg_)
```

| Camada | Prefixo | Papel |
|---|---|---|
| Source | `bronze.` | 20 tabelas cruas do sistema de origem. Nunca referenciar direto fora de `stg_`. |
| Staging | `stg_` | 1:1 com a source. Limpeza, tipagem, padronização de nomes. |
| Intermediate | `int_` | Junções e enriquecimento reutilizáveis. Definem o "grão base" de um assunto. |
| Marts | `dim_` / `fct_` / `agg_` | Camada de consumo. É o que o BI e as análises devem usar. |

Apoios: `seed_category_fix` (mapa curado de categorias) e `snap_stock_levels`
(snapshot dbt para histórico de estoque).

### Os quatro `int_`

- `int_sales_enriched` — 1 linha por item de pedido, com contexto do cabeçalho (cliente, vendedor, local, canal, status). Base de vendas.
- `int_returns_enriched` — 1 linha por item devolvido, com contexto da devolução. Base de devoluções.
- `int_purchases_enriched` — 1 linha por item de recebimento, com PO, fornecedor e local resolvidos point-in-time (SCD2) e valores convertidos para BRL.
- `int_products_categorized` — 1 linha por produto, com a categoria corrigida via `seed_category_fix`. Produtos sem mapeamento caem em `'Não Classificado'` com `is_categorized = false`.

---

## 2. Convenções de nomenclatura

**Prefixos de mart**

- `dim_` — dimensão conformada. Grão: uma entidade.
- `fct_` — fato transacional. Grão: uma linha do evento (item de pedido, item devolvido, item recebido).
- `agg_` — agregado pré-calculado para BI. Grão sempre declarado na descrição do modelo.

**Chaves**

| Sufixo | Significado |
|---|---|
| `_sk` | Surrogate key, gerada por hash. É a chave de join entre fato e dimensão. |
| `_id` | Natural key da origem. Mantida nos fatos para rastreabilidade, **não** para join. |
| `date_id` | Inteiro `YYYYMMDD`. Único FK para `dim_calendary`. |

Regra prática: **junte por `_sk`, filtre e rastreie por `_id`.** Nas dimensões SCD2 o
`_sk` é version-aware, então o join por `_id` traz múltiplas versões.

**Datas**: `_at` = timestamp; `_date`/`_day` = date; `date_id` = inteiro.

---

## 3. Dimensões

| Modelo | Grão | Tipo |
|---|---|---|
| `dim_calendary` | 1 dia | Date spine de 2020-01-01 até o fim do ano corrente, sem lacunas. Marcada como date table no Power BI. |
| `dim_customers` | 1 cliente | Enriquecida com a geografia do endereço principal. |
| `dim_products` | 1 variante (SKU) | Categoria corrigida, marca, preço de venda/custo, alíquotas. |
| `dim_employees` | 1 funcionário | Usada como vendedor em `fct_sales` e comprador em `fct_purchases`. |
| `dim_locations` | 1 local × versão | **SCD2** |
| `dim_suppliers` | 1 fornecedor × versão | **SCD2** |
| `dim_customer_addresses` | 1 endereço × versão | **SCD2** |

Nas SCD2, filtrar `is_current = true` para o estado atual; usar `valid_from`/`valid_to`
para consultas point-in-time.

---

## 4. Fatos

| Modelo | Grão | Materialização |
|---|---|---|
| `fct_sales` | item de pedido | table |
| `fct_returns` | item devolvido | table |
| `fct_purchases` | item de recebimento de mercadoria | table |
| `fct_daily_stock_levels` | dia de mudança × produto × local (esparso) | **incremental** |

**Ponte vendas ↔ devoluções**: `fct_returns.order_item_id` referencia
`fct_sales.order_item_id`. É por aí que se calcula receita líquida item a item.

**`fct_daily_stock_levels` é esparso** — só existe linha em dias de mudança de estoque.
Para uma série diária contínua é preciso fazer forward-fill contra `dim_calendary`.

---

## 5. Regras de negócio (o que está codificado nos modelos)

**Pedido válido** = `order_status IN ('paid', 'confirmed')`.
`'cancelled'` e `'draft'` são excluídos de toda receita nos agregados.

**Cascata de receita**, aplicada consistentemente nos `agg_`:

```
receita bruta  = SUM(line_total) de pedidos válidos
devoluções     = SUM(refund_amount)
impostos       = ICMS + IPI, aplicados sobre o valor RESIDUAL (bruto − devolução)
receita líquida = bruto − devolução − impostos
COGS           = quantidade líquida × cost_price (custo padrão de dim_products)
margem contrib. = receita líquida − COGS
```

O detalhe que mais gera divergência: **os impostos incidem sobre o valor residual**,
não sobre o bruto.

**Risco de churn** (`agg_customer_metrics.is_churn_risk`): limiares por `person_type` —
PJ após 180 dias sem compra, PF após 240 dias.

**Curva ABC** (`agg_customer_metrics.abc_class`): dinâmica por concentração de receita.
A = 80% do topo, B = 15% seguintes, C = 5% finais.

**`person_type`**: `PF` = pessoa física, `PJ` = pessoa jurídica. Deriva também
`inferred_purchase_reason` ('Professional Use' para PJ, 'Leisure' para PF) — é um
**proxy inferido**, não um dado de origem.

**Moeda**: `fct_purchases` guarda valores na moeda original da PO e a versão
convertida com sufixo `_brl`. Para somar valores de compra, usar sempre `_brl`.

---

## 6. Qual agregado usar

Os seis `agg_` existem para evitar varredura dos fatos no BI. Escolha pelo grão:

| Pergunta | Modelo | Grão |
|---|---|---|
| Receita/pedidos por dia e canal | `agg_sales_daily` | dia × canal |
| Receita por estado e categoria | `agg_sales_regional_category_daily` | dia × canal × UF × categoria |
| Contagem de pedidos por estado | `agg_sales_regional_orders_daily` | dia × canal × UF |
| Performance e margem de produto | `agg_product_performance` | mês × variante |
| LTV, churn, curva ABC | `agg_customer_metrics` | cliente |
| Coorte, MRR, retenção MoM | `agg_customer_monthly` | cliente × mês |

**Por que dois agregados regionais.** Um pedido com itens de várias categorias
apareceria repetido ao contar pedidos no agregado por categoria (fan-out). Por isso
`agg_sales_regional_category_daily` carrega só métricas aditivas (itens e receita) e
**não tem contagem de pedidos** — essa contagem vive em
`agg_sales_regional_orders_daily`. Nunca somar pedidos a partir do agregado de categoria.

`agg_customer_monthly` usa cross-join com date spine, então **todo mês desde a
primeira compra existe**, com zeros quando não houve pedido. Isso é intencional para
retenção — mas significa que uma contagem ingênua de linhas superestima clientes ativos.

---

## 7. Armadilhas conhecidas

- **`fct_sales.date_id` usa fallback `19000101`** quando `placed_at` é nulo. Essa
  chave não existe em `dim_calendary`, então tais linhas somem num inner join com a
  dimensão de data. Verificar antes de concluir que houve perda de receita.
- **`agg_customer_metrics.days_since_last_purchase` é calculado contra a data atual**,
  ou seja, muda a cada execução. Não é reproduzível historicamente.
- **`fct_daily_stock_levels` tem `raw_quantity_on_hand` possivelmente negativo**; use
  `physical_quantity_on_hand` para análise operacional e `is_negative_raw_quantity` /
  `has_zero_quantity_movement_review` para auditoria.
- **Categorias não mapeadas** aparecem como `'Não Classificado'`; UF desconhecida
  aparece como `'Não Informado'`. Ambos são valores válidos, não nulos.
- **Colunas sem documentação** em `fct_purchases`: `employee_sk`, `product_variant_sk`,
  `unit_cost_brl`. Existem na tabela mas não têm descrição no `.yml`.

---

## 8. Testes

111 das 217 colunas dos marts têm testes. Além dos genéricos (`unique`, `not_null`,
`relationships`, `accepted_values`), há testes singulares relevantes:

- `assert_fct_sales_no_future_dates`, `assert_fct_sales_positive_quantity`, `assert_fct_sales_line_total_non_negative`
- `assert_fct_returns_positive_quantity`, `assert_fct_returns_non_negative_refund`
- `assert_lead_time_not_negative`, `assert_quantity_received_not_exceed_ordered`, `assert_no_future_dates`
- `test_fct_daily_stock_levels_matches_snapshot_7d`, `test_fct_daily_stock_levels_daily_count_parity_7d`

---

## 9. A completar

> ⚠️ CONFIRMAR — pontos que não dá para inferir do manifest:
>
> - **Nenhum modelo tem tags.** Não há como distinguir mart oficial de experimental,
>   nem marcar depreciações. Vale adotar tags (`core`, `bi`, `deprecated`).
> - **Cadência de atualização** de cada mart e horário do job.
> - **Ownership**: quem responde por cada domínio (vendas, compras, estoque).
> - **Fonte oficial de cada métrica de negócio** — se "receita" no dashboard executivo
>   vem de `agg_sales_daily` ou de `fct_sales`, por exemplo.
> - **Consumo downstream**: quais dashboards do Power BI leem quais marts.
> - **Idioma**: as descrições do dbt estão em inglês. Padronizar se as perguntas
>   forem feitas em português.

---

## 10. Como ler o `dbt_marts_context.json`

- `models[]` — os 17 marts, com `columns` completas (nome, tipo, descrição, testes).
- `upstream_direct` — pais imediatos.
- `upstream_lineage` — cadeia completa até as sources; `depth` é a distância no DAG.
- `source_tables` — tabelas `bronze.*` na raiz da linhagem.
- `upstream_nodes` — dicionário dos 54 nós upstream (staging, intermediate, sources),
  listados uma única vez com seus próprios `parents`. Para reconstruir o caminho
  completo de um mart, siga `parents` recursivamente a partir daqui.
