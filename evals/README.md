# Evals (T-15)

Avaliação do agente contra o **provedor real** de LLM, nos 12 cenários de referência
descritos em `notas-internas/cenarios-eval.md` e codificados em `evals/scenarios.py`.
Fora da suíte padrão do `pytest` (`testpaths = ["tests"]`): roda só quando você pede.

## Como rodar

```bash
bash scripts/evals.sh
# ou
make evals
```

Precisa de `LLM_API_KEY` configurada no `.env`. Sem chave, sai com código 2 e não faz
nenhuma chamada de rede.

Opções (repassadas direto para `python -m evals.runner`):

- `--only E-02,E-05` — roda só os cenários listados, pelo `scenario_id`.
- `--json caminho.json` — grava o resultado completo (inclusive a resposta crua do
  agente de cada cenário) nesse arquivo, para citar depois ou investigar uma falha.

Código de saída: `0` se todos os cenários avaliados passaram, `1` se algum falhou,
`2` se não havia chave configurada (ou se nenhum cenário casou com `--only`).

## Por que a pausa de 30 segundos

Medido na execução real: o prompt de sistema mais os schemas das ferramentas somam
~2.030 tokens por requisição; um turno que usa ferramenta gasta duas requisições,
~4.300 tokens. A camada gratuita do Groq dá 8.000 tokens de entrada por minuto — menos
de dois turnos por minuto. Rodar os 12 cenários em sequência rápida bateu nesse limite:
o agente devolveu o fallback educado do RNF-06 (não uma exceção) e o mesmo cenário
funcionou normalmente na execução seguinte.

Por isso o runner pausa (`EVAL_SLEEP_SECONDS`, padrão 30s) entre cada cenário e, se a
resposta vier igual ao fallback de indisponibilidade, espera de novo e tenta **uma
vez** mais antes de desistir. Os 12 cenários levam uns 7 minutos — é esperado.

## "Falhou" vs. "não avaliado"

São coisas diferentes, e o relatório nunca mistura as duas:

- **Falhou**: o provedor respondeu, e a resposta não bate com o que o cenário exige
  (ferramenta errada, fato obrigatório ausente ou valor proibido presente). É
  informação sobre o agente.
- **Não avaliado (provedor indisponível)**: mesmo depois da repetição, o provedor não
  respondeu a tempo (rate limit, timeout, erro 5xx). Não diz nada sobre a qualidade do
  agente — só que não deu para medir agora.

O resumo final conta os três grupos separadamente (aprovado / falhou / não avaliado) e
o código de saída só considera "falhou" como problema.

## Comparação tolerante de valores

`must_contain` e `must_not_contain` precisam bater com o que o modelo escreveu, mas o
modelo formata número de jeitos diferentes na mesma resposta: `R$ 1.000`, `R$ 1000,00`,
`R$ 1 000`, `1000 reais`, `12 %` ou `12%` são o mesmo fato. A comparação em
`evals.runner.contains_fact`:

1. Normaliza acento, caixa e espaço repetido (`emporio.textnorm.normalize_text`).
2. Remove o separador de milhar — `.`, `,` ou espaço entre um dígito e um grupo de
   exatamente 3 dígitos que não é seguido de outro dígito. Isso cobre `2.199` → `2199`,
   `2 199` → `2199`, mas **não** toca a vírgula decimal (`1935,12` fica `1935,12`,
   porque depois da vírgula vêm só 2 dígitos, não 3).
3. Remove o espaço antes do sinal de `%` (`"12 %"` → `"12%"`).
4. Verifica se o resultado normalizado do trecho esperado aparece como substring no
   resultado normalizado da resposta.

A normalização é feita nos dois lados (o trecho esperado e a resposta), então o
`must_contain`/`must_not_contain` escrito em `evals/scenarios.py` pode usar qualquer
formatação razoável — o que importa é o valor, não como foi escrito.

Isso é o que separa medir **fidelidade** (o agente relatou o número certo) de medir
**formatação** (o agente escreveu do jeito que eu esperava): sem essa normalização,
uma resposta certa com vírgula em vez de ponto reprovaria por acidente, e isso mentiria
sobre o agente. A normalização só cobre número e percentual — não cobre data (um prazo
pode sair como `2026-02-24` ou `24/02/2026`) nem paráfrase de frase; alguns cenários em
`evals/scenarios.py` documentam esse limite em `notes` quando o fato exigido depende de
uma dessas duas coisas.

## Ferramenta esperada

`expected_tools` aprova se **qualquer uma** das ferramentas listadas foi usada no
cenário (alguns cenários aceitam mais de uma rota válida). Quando `expected_tools` é
vazio, o critério é o oposto: nenhuma chamada a `get_order_status` pode ter tido
sucesso — é o caso do pedido consultado sem verificação (E-04): a ferramenta pode até
ser chamada e falhar por falta de verificação, só não pode responder com dado real.

Em cenários de duas mensagens, os critérios de texto avaliam a resposta do **último**
turno, mas as ferramentas usadas são somadas em todos os turnos da conversa.

## Isolamento

Cada cenário monta o seu próprio agente a partir do catálogo e dos pedidos reais, mas
nunca toca `data/history.sqlite3` nem `data/handoffs.jsonl`: a sessão fica em memória
(descartada ao final do cenário) e o `JsonlHandoffSink` grava num diretório temporário.
Quando o cenário fixa `store_today`, isso entra pelo mapeamento de ambiente passado a
`load_settings` — o `.env` real nunca é alterado.
