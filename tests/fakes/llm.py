"""LLM roteirizado: dublê de `LlmClient` sem rede para os testes do agente."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from emporio.agent.llm import LlmReply, ToolCall


class ScriptedLlm:
    """Devolve respostas pre-definidas, em ordem, e registra o que recebeu.

    Qualquer chamada alem do roteiro levanta `AssertionError`: um teste que
    precisa de mais rodadas do que previu deve falhar alto, nao silenciar.
    """

    def __init__(self, replies: Sequence[LlmReply]) -> None:
        self._replies = list(replies)
        self._next = 0
        self.calls: list[tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]] = []

    def complete(
        self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]] = ()
    ) -> LlmReply:
        """Registra a chamada e devolve a proxima resposta do roteiro."""
        self.calls.append(
            (tuple(dict(message) for message in messages), tuple(dict(tool) for tool in tools))
        )

        if self._next >= len(self._replies):
            raise AssertionError(
                f"ScriptedLlm chamado alem do roteiro: {self._next + 1}a chamada, "
                f"mas o roteiro tem apenas {len(self._replies)} resposta(s)."
            )

        reply = self._replies[self._next]
        self._next += 1
        return reply


def reply_text(text: str) -> LlmReply:
    """Monta uma resposta somente com texto, sem chamada de ferramenta."""
    return LlmReply(text=text)


def reply_tool(name: str, call_id: str = "call-1", **arguments: Any) -> LlmReply:
    """Monta uma resposta com uma unica chamada de ferramenta."""
    return LlmReply(
        text=None, tool_calls=(ToolCall(id=call_id, name=name, arguments=dict(arguments)),)
    )
