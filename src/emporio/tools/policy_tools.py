"""Ferramenta de consulta ao manual de politicas por topico (RF-06).

O texto devolvido e o texto literal das secoes do manual (ja tratado em
`data/processed/politicas.json`); esta camada nunca resume nem reescreve,
so empacota para o formato que o LLM recebe. A secao 7 (uso interno, D-12)
nunca aparece: `PolicyBook` ja a exclui de `_by_topic`.
"""

from __future__ import annotations

from emporio.policies.store import POLICY_TOPICS, PolicyBook
from emporio.tools.base import JsonDict, ToolSpec, tool_error

__all__ = ["build_policy_tools"]

# Pista curta de cada topico, para o LLM escolher o topico certo sem
# transcrever o manual na descricao do parametro.
_TOPIC_HINTS: dict[str, str] = {
    "about_store": "quem é a loja, história e missão",
    "contact_address": "endereço, CNPJ, telefone e e-mail de contato",
    "hours": "dias e horários de funcionamento",
    "payment": "formas de pagamento, desconto no PIX e regras de parcelamento",
    "returns_exchanges": "prazos e condições de troca, devolução e itens não elegíveis",
    "shipping": "frete, prazos e formas de entrega",
    "tracking": "código e consulta de rastreamento",
    "promotions": "campanhas de desconto e regras de cumulatividade",
    "warranty": "garantia legal e garantia do fabricante",
    "privacy": "uso de dados pessoais e LGPD",
    "service_scope": "quais tipos de produto a loja vende",
}


def _topic_parameter_description() -> str:
    """Monta a descricao do parametro `topic`, com a pista de cada valor do enum."""
    hints = "; ".join(f"{topic} ({_TOPIC_HINTS[topic]})" for topic in POLICY_TOPICS)
    return f"Tópico da política consultada: {hints}."


def build_policy_tools(policy_book: PolicyBook) -> tuple[ToolSpec, ...]:
    """Monta a ferramenta `get_policy`, que consulta o manual por topico."""

    def handler(topic: str) -> JsonDict:
        if topic not in POLICY_TOPICS:
            valid = ", ".join(POLICY_TOPICS)
            return tool_error(
                "unknown_topic",
                f"Tópico '{topic}' não é válido. Tópicos disponíveis: {valid}.",
            )

        sections = policy_book.get(topic)
        return {
            "topic": topic,
            "sections": [
                {"number": section.number, "title": section.title, "text": section.text}
                for section in sections
            ],
        }

    spec = ToolSpec(
        name="get_policy",
        description=(
            "Consulta o manual de políticas da loja por tópico (horário, pagamento, "
            "trocas e devoluções, frete, rastreamento, promoções, garantia, privacidade "
            "e escopo de atendimento). O texto devolvido é o texto oficial do manual; "
            "nunca invente uma regra que não esteja nele."
        ),
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": list(POLICY_TOPICS),
                    "description": _topic_parameter_description(),
                },
            },
            "required": ["topic"],
        },
        handler=handler,
    )
    return (spec,)
