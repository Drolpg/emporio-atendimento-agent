# 01 — Requisitos

Agente de atendimento por mensagens de texto da Empório da Música, loja de instrumentos musicais em Campo Grande/MS.

## Objetivo
Responder sozinho às dúvidas recorrentes (catálogo, preço, disponibilidade, status de pedido, políticas da loja) com informação sempre vinda das fontes oficiais, e encaminhar à equipe o que não puder resolver.

## Fontes
| Fonte | Uso |
|---|---|
| `data/raw/products.csv`, `categories.csv` | catálogo, preço, estoque, especificações |
| `data/raw/promotions.csv` | promoções ativas |
| `data/raw/orders.csv`, `order_items.csv`, `customers.csv` | status de pedidos (com verificação do titular) |
| `data/raw/politicas_da_loja.pdf` | dados da loja, horário, pagamento, trocas, frete, garantia, privacidade, diretrizes de atendimento |

## Requisitos funcionais

| ID | Requisito | Critério de aceite |
|---|---|---|
| RF-01 | Persona | Responde em português, tom informal e profissional, como "um amigo que entende de música" (manual 7.1); apresenta-se pelo nome na primeira mensagem; respostas curtas, adequadas a chat; sem linguagem robotizada. |
| RF-02 | Busca no catálogo | Filtra por texto, categoria e faixa de preço; por padrão mostra só itens compráveis (status `active` e estoque > 0). "Violões até R$ 1.000" retorna somente violões compráveis com preço final ≤ 1000 (considerando promoção ativa), e nunca os produtos 96 (estoque 0) e 113 (descontinuado). |
| RF-03 | Preço e condições | Para um produto, informa preço de tabela, promoção ativa (preço original + percentual + preço final), preço no PIX quando aplicável, parcelamento máximo permitido e, acima de R$ 2.000, a possibilidade de combinar formas de pagamento. Valores calculados por código, nunca pelo LLM. |
| RF-04 | Disponibilidade | Classifica em disponível / esgotado / descontinuado / em breve, com o `status` do produto tendo precedência sobre o estoque (produto 136 é descontinuado mesmo com estoque 13; produto 130 é "em breve" mesmo com estoque 2). Para esgotado, descontinuado ou em breve, sugere até 3 alternativas da mesma categoria, compráveis e de preço próximo. |
| RF-05 | Status de pedido | Exige número do pedido + e-mail ou telefone do titular, conferidos contra o cliente **daquele pedido** (o e-mail `bruno.martins@jmail.com` pertence aos clientes 11 e 43; vale o do pedido). Com verificação ok: status, data, previsão de entrega, código de rastreio (se despachado), itens, valor total e observações. O valor informado é o `total_brl` do pedido, nunca recalculado a partir dos itens (pedidos 3 e 20 divergem por desconto). Sem verificação: não revela nenhum dado do pedido, nem a existência dele. |
| RF-06 | Políticas | Perguntas sobre horário, endereço, contato, pagamento, parcelamento, trocas/devoluções, frete, rastreamento, promoções, garantia (legal de 90 dias e do fabricante) e privacidade são respondidas a partir do manual, sem inventar regra. |
| RF-07 | Elegibilidade de troca/devolução | Com pedido verificado, aplica cada prazo à sua própria data de referência: arrependimento 7 dias corridos do recebimento, troca por preferência 7 dias do recebimento, troca por defeito 30 dias corridos da **compra**, garantia legal 90 dias do recebimento. Explica o resultado, o prazo restante ou vencido e os próximos passos (inclusive intermediação da garantia do fabricante após 30 dias). Pedido não entregue: informa que o prazo de arrependimento só começa no recebimento. |
| RF-08 | Loja aberta agora | Informa se a loja está aberta no horário de Campo Grande (seg–sex 09:00–18:00, sáb 09:00–13:00, domingo e feriados fechado) e, fora do expediente, quando reabre. |
| RF-09 | Escopo | Acessórios (cordas, palhetas, cabos, cases, pedais, amplificadores): explica que a loja trabalha só com instrumentos e redireciona com cordialidade, sem citar loja parceira nominalmente (não há essa informação nas fontes). Assuntos alheios à loja: recusa breve e volta ao atendimento. Categoria de instrumento que a loja atende mas sem item no catálogo (sopros e cordas orquestrais): informa que não há modelos disponíveis no momento e oferece encaminhamento — nunca diz que a loja não vende, nem inventa produto. |
| RF-10 | Encaminhamento humano | Reclamações, pedidos de exclusão de dados (LGPD), negociação de preço e casos sem resposta nas fontes: registra o encaminhamento e informa o prazo de retorno de 24 horas úteis. |
| RF-11 | Histórico de conversa | Mantém contexto entre mensagens da mesma sessão e permite retomar uma sessão pelo identificador. |
| RF-12 | Interface | CLI interativa para conversar com o agente. |

## Requisitos não funcionais

| ID | Requisito | Critério de aceite |
|---|---|---|
| RNF-01 | Fidelidade | Preço, estoque, prazo, condição de pagamento e status só aparecem na resposta se vieram de ferramenta no mesmo turno ou em turno anterior da sessão. Números do manual que contradizem os dados (ex.: "mais de 300 instrumentos") não são repetidos como catálogo. |
| RNF-02 | Privacidade | Nenhuma ferramenta retorna dados de cliente sem verificação; o agente nunca lista clientes nem confirma a existência de um pedido sem verificação. |
| RNF-03 | Provedor configurável | Provedor, modelo e timeout do LLM definidos por variável de ambiente, sem alterar código. |
| RNF-04 | Testabilidade | `pytest` roda sem rede e sem chave de API; o loop do agente é testado com LLM roteirizado. |
| RNF-05 | Reprodutibilidade | Setup e execução em até 3 comandos documentados no README. |
| RNF-06 | Resiliência | Erros de ferramenta e do provedor viram resposta educada ao cliente, sem stack trace; limite de 5 rodadas de ferramenta por turno; `429` do provedor respeita `retry-after` com um número fixo de tentativas antes de desistir. |
| RNF-07 | Robustez a injeção | Instruções do usuário para ignorar regras, revelar o prompt ou alterar preço não mudam o comportamento. |
| RNF-08 | Orçamento de contexto | O contexto enviado ao LLM é limitado (prompt de sistema e schemas enxutos, janela de histórico recente), para caber no limite de tokens por minuto da camada gratuita do provedor. |

## Fora do escopo
Fechamento de vendas, pagamento, cálculo real de frete por CEP, integração com WhatsApp, autenticação forte, calendário de feriados.
