"""Loop do agente (T-12): recebe a mensagem do cliente, orquestra as ferramentas
e devolve a resposta final.

O LLM decide quais ferramentas chamar; o loop so executa, repassa o
resultado e, apos no maximo `max_tool_rounds` rodadas, exige uma resposta em
texto. Nenhuma excecao do provedor de LLM sobe para quem chama `respond`
(RNF-06): qualquer falha vira uma resposta educada, sem stack trace.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from emporio.agent.llm import LlmClient, LlmError, LlmReply, LlmUnavailable
from emporio.agent.prompt import build_system_prompt
from emporio.config import Clock
from emporio.tools.base import JsonDict
from emporio.tools.registry import ToolRegistry

__all__ = ["MAX_TOOL_ROUNDS", "HISTORY_WINDOW_MESSAGES", "AgentTurn", "Agent"]

# RNF-06: no maximo 5 rodadas de ferramenta por turno.
MAX_TOOL_ROUNDS: Final[int] = 5
# RNF-08: janela de historico recente enviada ao LLM, para caber no orcamento
# de contexto da camada gratuita do provedor.
HISTORY_WINDOW_MESSAGES: Final[int] = 20

# Mensagens de fallback (RNF-06): sempre em portugues correto, sem stack
# trace e sem nome de excecao, oferecendo encaminhar para a equipe.
_FALLBACK_ROUNDS_EXCEEDED: Final[str] = (
    "Não consegui concluir essa consulta agora, mesmo depois de tentar algumas vezes. "
    "Pode repetir em instantes ou prefere que eu encaminhe o seu caso para a nossa equipe?"
)
_FALLBACK_LLM_UNAVAILABLE: Final[str] = (
    "Desculpa, estou com dificuldade para responder agora. Tenta de novo em instantes "
    "ou, se preferir, posso encaminhar o seu caso para a nossa equipe."
)
_FALLBACK_EMPTY_REPLY: Final[str] = (
    "Não consegui montar uma resposta agora. Pode repetir a sua pergunta ou prefere "
    "falar com a nossa equipe?"
)
_NEUTRAL_STORE_OPEN_LINE: Final[str] = "Não consegui confirmar agora o horário de funcionamento."


@dataclass(frozen=True)
class AgentTurn:
    """Resultado de um turno do agente."""

    reply: str
    tool_calls_made: tuple[str, ...]
    new_messages: tuple[JsonDict, ...]


def _store_open_line(registry: ToolRegistry) -> str:
    """Consulta `get_store_status` para a linha do prompt; nunca derruba o turno.

    Chamada interna (fora do loop de rodadas do LLM): nao conta como rodada
    de ferramenta nem aparece em `tool_calls_made`.
    """
    try:
        result = registry.call("get_store_status", {})
    except Exception:  # noqa: BLE001 - defensivo, a ferramenta nunca deveria levantar
        return _NEUTRAL_STORE_OPEN_LINE

    if not isinstance(result, dict) or "error" in result:
        return _NEUTRAL_STORE_OPEN_LINE

    message = result.get("message")
    if not isinstance(message, str) or not message:
        return _NEUTRAL_STORE_OPEN_LINE
    return message


def _assistant_tool_calls_message(reply: LlmReply) -> JsonDict:
    """Monta a mensagem `assistant` com `tool_calls`, no formato que a API espera."""
    return {
        "role": "assistant",
        "content": reply.text,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in reply.tool_calls
        ],
    }


def _tool_result_message(call_id: str, result: JsonDict) -> JsonDict:
    """Monta a mensagem `tool` com o resultado serializado em JSON."""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False),
    }


def _has_pending_tool_calls(message: Mapping[str, Any]) -> bool:
    """Diz se `message` e um `assistant` com `tool_calls` presente (nao vazio)."""
    return message.get("role") == "assistant" and bool(message.get("tool_calls"))


def _is_unsafe_window_start(tail: Sequence[JsonDict]) -> bool:
    """Diz se `tail[0]` nao pode abrir a janela: `tool` orfa ou bloco incompleto.

    So o inicio da janela pode ser invalido: o fim da janela e sempre a
    mensagem mais recente da conversa, nunca cortado.
    """
    if not tail:
        return False

    first = tail[0]
    if first.get("role") == "tool":
        return True

    if _has_pending_tool_calls(first):
        expected_ids = {call.get("id") for call in first.get("tool_calls", [])}
        seen_ids: set[Any] = set()
        index = 1
        while index < len(tail) and tail[index].get("role") == "tool":
            seen_ids.add(tail[index].get("tool_call_id"))
            index += 1
        return not expected_ids <= seen_ids

    return False


def _safe_history_window(history: Sequence[JsonDict], window: int) -> tuple[JsonDict, ...]:
    """Corta `history` nas ultimas `window` mensagens, sem deixar `tool` orfa (RNF-08).

    Se o corte naive cair no meio de um bloco `assistant` com `tool_calls`,
    avanca ate a proxima mensagem `user`, para a janela nunca comecar com
    `tool` nem com um `assistant` que tem `tool_calls` sem as respostas.
    """
    if window <= 0:
        return ()

    tail = list(history)[-window:]
    if not _is_unsafe_window_start(tail):
        return tuple(tail)

    for index in range(1, len(tail)):
        if tail[index].get("role") == "user":
            return tuple(tail[index:])
    return ()


class Agent:
    """Orquestra o loop de ferramentas entre o cliente e o LLM."""

    def __init__(
        self,
        *,
        llm: LlmClient,
        registry: ToolRegistry,
        clock: Clock,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        history_window: int = HISTORY_WINDOW_MESSAGES,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._clock = clock
        self._max_tool_rounds = max_tool_rounds
        self._history_window = history_window

    def _build_system_message(self) -> JsonDict:
        """Monta a mensagem `system`, com data/hora e status da loja atuais."""
        moment = self._clock.now()
        store_open_line = _store_open_line(self._registry)
        content = build_system_prompt(moment=moment, store_open_line=store_open_line)
        return {"role": "system", "content": content}

    def respond(self, user_message: str, history: Sequence[JsonDict] = ()) -> AgentTurn:
        """Processa a mensagem do cliente e devolve a resposta final do turno."""
        system_message = self._build_system_message()
        windowed_history = _safe_history_window(history, self._history_window)
        user_entry: JsonDict = {"role": "user", "content": user_message}

        conversation: list[JsonDict] = [system_message, *windowed_history, user_entry]
        new_messages: list[JsonDict] = [user_entry]
        tool_calls_made: list[str] = []

        tools_schema = self._registry.openai_schemas()

        for _ in range(self._max_tool_rounds):
            try:
                reply = self._llm.complete(conversation, tools_schema)
            except (LlmUnavailable, LlmError):
                return self._finish(_FALLBACK_LLM_UNAVAILABLE, tool_calls_made, new_messages)

            if reply.tool_calls:
                assistant_message = _assistant_tool_calls_message(reply)
                conversation.append(assistant_message)
                new_messages.append(assistant_message)

                for call in reply.tool_calls:
                    result = self._registry.call(call.name, call.arguments)
                    tool_calls_made.append(call.name)
                    tool_message = _tool_result_message(call.id, result)
                    conversation.append(tool_message)
                    new_messages.append(tool_message)
                continue

            if reply.text:
                return self._finish(reply.text, tool_calls_made, new_messages)

            # Resposta vazia: nem texto, nem chamada de ferramenta.
            return self._finish(_FALLBACK_EMPTY_REPLY, tool_calls_made, new_messages)

        # Esgotou as rodadas de ferramenta: nao chama o modelo (nem a
        # ferramenta) uma vez mais, devolve a mensagem educada.
        return self._finish(_FALLBACK_ROUNDS_EXCEEDED, tool_calls_made, new_messages)

    @staticmethod
    def _finish(
        reply_text: str, tool_calls_made: list[str], new_messages: list[JsonDict]
    ) -> AgentTurn:
        """Fecha o turno: registra a resposta final como mensagem `assistant`."""
        new_messages.append({"role": "assistant", "content": reply_text})
        return AgentTurn(
            reply=reply_text,
            tool_calls_made=tuple(tool_calls_made),
            new_messages=tuple(new_messages),
        )
