"""Cliente de LLM compativel com a API da OpenAI (Groq, Ollama, etc).

Isola o acesso ao provedor atras do protocolo `LlmClient`, para que o loop do
agente (T-12) nunca dependa do SDK diretamente. Implementa a politica de
resiliencia do RNF-06: timeout por chamada, numero fixo de tentativas e
`retry-after` em `429` (ver decisao D-07 sobre os limites do provedor).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from emporio.config import Settings

__all__ = [
    "ToolCall",
    "LlmReply",
    "LlmError",
    "LlmUnavailable",
    "LlmClient",
    "OpenAiCompatibleClient",
]


@dataclass(frozen=True)
class ToolCall:
    """Uma chamada de ferramenta solicitada pelo modelo."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LlmReply:
    """Resposta do modelo: texto e/ou chamadas de ferramenta, nunca ambos vazios."""

    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()


class LlmError(Exception):
    """Erro irrecuperavel ao falar com o provedor (ex.: chave invalida)."""


class LlmUnavailable(LlmError):
    """Provedor indisponivel apos esgotar as tentativas (timeout, 5xx ou 429)."""


class LlmClient(Protocol):
    """Contrato minimo que o loop do agente espera de um cliente LLM."""

    def complete(
        self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]] = ()
    ) -> LlmReply:
        """Envia a conversa (e, opcionalmente, as ferramentas) e devolve a resposta."""
        ...


def _status_code(exc: Exception) -> int | None:
    """Extrai o status HTTP de uma excecao do SDK, por atributo (sem acoplar a versao)."""
    return getattr(exc, "status_code", None)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Extrai o `retry-after` (em segundos) de uma excecao de `429`, se vier."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    value = headers.get("retry-after") if headers is not None else None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_retryable(status_code: int | None) -> bool:
    """Timeout/erro de conexao (sem status), `429` e `5xx` valem nova tentativa."""
    if status_code is None:
        return True
    return status_code == 429 or status_code >= 500


def _safe_json_loads(raw: str) -> dict[str, Any]:
    """Decodifica argumentos de ferramenta; JSON invalido vira `{}`, sem levantar."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_reply(response: Any) -> LlmReply:
    """Le a primeira escolha da resposta do SDK e monta o `LlmReply`."""
    choices = getattr(response, "choices", None)
    if not choices:
        raise LlmError("O provedor de LLM respondeu sem nenhuma escolha.")

    message = choices[0].message
    content = getattr(message, "content", None)
    text = content if content and content.strip() else None

    raw_tool_calls = getattr(message, "tool_calls", None) or ()
    tool_calls = tuple(
        ToolCall(
            id=call.id,
            name=call.function.name,
            arguments=_safe_json_loads(call.function.arguments),
        )
        for call in raw_tool_calls
    )
    return LlmReply(text=text, tool_calls=tool_calls)


class OpenAiCompatibleClient:
    """Cliente LLM para qualquer provedor compativel com a API da OpenAI."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
    ) -> None:
        """Usa `client` se injetado (testes); senao constroi um `openai.OpenAI`.

        A chave vazia cai para `"nao-usada"`: o SDK exige algum valor nao
        vazio mesmo quando o provedor local (Ollama) nao verifica a chave.
        """
        self._settings = settings
        self._sleep = sleep
        self._max_attempts = max_attempts

        if client is None:
            import openai

            client = openai.OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key or "nao-usada",
                timeout=settings.llm_timeout_seconds,
            )
        self._client = client

    def complete(
        self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]] = ()
    ) -> LlmReply:
        """Chama o provedor, repetindo conforme a politica de resiliencia do RNF-06."""
        kwargs: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": list(messages),
        }
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = "auto"

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - reclassificado abaixo, sem repassar o original
                status_code = _status_code(exc)
                if not _is_retryable(status_code):
                    detail = f" (status {status_code})" if status_code else ""
                    raise LlmError(f"O provedor de LLM recusou a requisicao{detail}.") from None

                if attempt == self._max_attempts:
                    raise LlmUnavailable(
                        "O provedor de LLM ficou indisponivel apos varias tentativas."
                    ) from None

                wait = _retry_after_seconds(exc) if status_code == 429 else None
                if wait is None:
                    wait = float(2 ** (attempt - 1))
                self._sleep(wait)
                continue
            else:
                return _parse_reply(response)

        # Inalcancavel: o loop sempre retorna ou levanta antes de terminar.
        raise LlmUnavailable("O provedor de LLM ficou indisponivel apos varias tentativas.")
