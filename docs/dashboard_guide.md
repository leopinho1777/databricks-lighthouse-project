# Guia do Dashboard Executivo — LH Nautical

## 1. Visão Geral
Este é o Painel Executivo da LH Nautical, projetado para resolver dores estratégicas da operação: unificação de canais (lojas físicas e e-commerce), erradicação do "lucro fantasma" e visibilidade real do comportamento de clientes e regiões.

## 2. Acesso, Links e Arquitetura
* **Acesso ao Painel:** [Inserir Link do Workspace/App do Power BI]
* **Restrições:** O acesso é controlado via Row-Level Security (RLS) conforme o nível hierárquico do usuário.
* **Origem dos Dados:** Os dados são consumidos diretamente do Databricks, baseados na nossa camada *Marts* gerada pelo dbt (tabelas `fct_sales`, `fct_returns`, `agg_customer_monthly`, etc.).
* **Atualização:** Pipeline automatizado com atualização diária agendada para as 06h00.

## 3. Dicionário de KPIs (Primários)
* **Faturamento Bruto:** Total transacionado em todos os canais, sem deduções.
* **Faturamento Líquido:** Receita real no caixa após abater rigorosamente as devoluções (no mês da venda original) e os impostos.
* **Volume de Pedidos:** Contagem distinta de ordens de compra válidas (exclui cancelados).
* **Ticket Médio:** Faturamento Líquido dividido pelo Volume de Pedidos (nunca por itens ou clientes).
* **Clientes Ativos (Rolling 12M):** Compradores únicos com pelo menos um pedido válido nos últimos 12 meses (janela escolhida para absorver a sazonalidade do verão náutico).
* **Taxa de Devolução:** Valor devolvido dividido pelo Faturamento Bruto do mesmo período.

## 4. Navegação das Páginas
* **Visão Executiva:** Resumo C-Level com Faturamento, Lucro Líquido, Devoluções e indicadores macro de crescimento YoY (Year-over-Year).
* **Análise por Pedido:** Detalhamento da frequência de compras, ticket médio, tamanho da cesta (itens por pedido) e formas de pagamento.
* **Análise por Região:** Participação de mercado, força regional, volume de clientes por estado e comparativo de receita.
* **Análise por Clientes:** Curva ABC (identificação de clientes de alto valor), métricas de retenção, clientes novos x recorrentes e análise de risco de churn (receita em risco de clientes inativos).

## 5. Suporte e Propriedade
Para dúvidas sobre as regras de negócio, reporte de bugs no visual ou problemas de atualização de dados, por favor contate:
* **Tech Lead:** [Nome da Tech Lead]
* **Engenharia de Analytics:** [Seu Nome]