# 03 — Tarefas

| ID | Tarefa | Requisitos | Depende de |
|---|---|---|---|
| T-01 | Estrutura do projeto: `pyproject` (uv), ruff, pytest, Makefile, `.env.example`, `.gitignore` | RNF-04, RNF-05 | — |
| T-02 | Configuração por ambiente e relógio injetável com o fuso da loja e `STORE_TODAY` | RNF-03, RNF-04 | T-01 |
| T-03 | Carga e tratamento dos CSVs + repositórios de catálogo, promoções, clientes e pedidos | RF-02 a RF-05 | T-01 |
| T-04 | Extração do manual em seções + `data/processed/politicas.json` + consulta por tópico | RF-06 | T-01 |
| T-05 | Domínio: promoção, PIX, parcelamento e pagamento combinado | RF-03 | T-01 |
| T-06 | Domínio: horário da loja e próxima abertura | RF-08 | T-02 |
| T-07 | Domínio: elegibilidade de troca, devolução e garantia (quatro prazos, cada um com sua data de referência) e frete | RF-07, RF-06 | T-02 |
| T-08 | Ferramentas de catálogo: `search_products`, `get_product_details`, `list_categories` | RF-02 a RF-04, RF-09, RNF-01 | T-03, T-05 |
| T-09 | Ferramenta `get_order_status` com verificação do titular contra o cliente do pedido | RF-05, RF-07, RNF-02 | T-03, T-07 |
| T-10 | Ferramentas `get_policy`, `get_store_status`, `create_handoff` + registro de ferramentas | RF-06, RF-08, RF-10 | T-04, T-06, T-08, T-09 |
| T-11 | Cliente LLM compatível com OpenAI (timeout, `429` com `retry-after`, campo `reasoning`) + LLM roteirizado para testes | RNF-03, RNF-04, RNF-06 | T-01 |
| T-12 | Prompt de sistema e loop do agente com limite de rodadas, orçamento de contexto e tratamento de erros | RF-01, RF-09, RNF-01, RNF-06, RNF-07, RNF-08 | T-10, T-11 |
| T-13 | Histórico em SQLite, janela de contexto e retomada de sessão | RF-11, RNF-08 | T-12 |
| T-14 | CLI interativa | RF-12 | T-13 |
| T-15 | Evals com cenários de referência e pausa entre eles | todos | T-14 |
| T-16 | Exemplos de conversa reais em `examples/conversas/` | entregável | T-14 |
| T-17 | README completo com diagramas | entregável | T-16 |

## Ondas de execução
Paralelismo só entre tarefas de arquivos disjuntos.

| Onda | Tarefas em paralelo |
|---|---|
| 1 | T-01 |
| 2 | T-02 · T-04 · T-11 |
| 3 | T-03 · (T-05 + T-06 + T-07, um só briefing de domínio) |
| 4 | T-08 · T-09 |
| 5 | T-10 |
| 6 | T-12 |
| 7 | T-13 → T-14 |
| 8 | T-15 → T-16 (sequenciais: compartilham o limite de taxa do provedor) |
| 9 | T-17 |
