"""Testes do cliente LLM compativel com OpenAI e do dublê roteirizado."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from emporio.agent.llm import (
    LlmError,
    LlmReply,
    LlmUnavailable,
    OpenAiCompatibleClient,
    ToolCall,
)
from emporio.config import Settings
from tests.fakes.llm import ScriptedLlm, reply_text, reply_tool


def _settings(**overrides: Any) -> Settings:
    """Monta Settings de teste, sem depender de variaveis de ambiente."""
    defaults: dict[str, Any] = {
        "llm_base_url": "https://example.invalid/v1",
        "llm_api_key": "segredo-super-secreto",
        "llm_model": "modelo-teste",
        "llm_timeout_seconds": 5.0,
        "store_today": None,
        "history_db_path": Path("historico.sqlite3"),
        "raw_data_dir": Path("raw"),
        "processed_data_dir": Path("processed"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_message(
    content: str | None, tool_calls: list[tuple[str, str, str]] | None = None
) -> SimpleNamespace:
    """Monta um objeto parecido com ChatCompletionMessage do SDK."""
    calls = [
        SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))
        for call_id, name, arguments in (tool_calls or [])
    ]
    return SimpleNamespace(content=content, tool_calls=calls or None)


def _make_response(
    content: str | None, tool_calls: list[tuple[str, str, str]] | None = None
) -> SimpleNamespace:
    """Monta um objeto parecido com ChatCompletion do SDK."""
    message = _make_message(content, tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeResponseWithHeaders:
    """Imita o `response` de uma excecao de status do SDK openai."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


class FakeApiStatusError(Exception):
    """Imita APIStatusError do SDK openai: tem status_code e response.headers."""

    def __init__(
        self, message: str, *, status_code: int, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = _FakeResponseWithHeaders(headers)


class FakeConnectionError(Exception):
    """Imita um erro de conexao/timeout do SDK: sem status_code nenhum."""


class _FakeCompletions:
    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeOpenAiClient:
    """Cliente falso que imita a interface usada do SDK openai, sem rede."""

    def __init__(self, script: list[Any]) -> None:
        self.completions = _FakeCompletions(script)
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.completions.calls


class TestOpenAiCompatibleClientReplies:
    """Criterios 1 a 6: leitura da resposta e montagem da chamada ao SDK."""

    def test_text_only_reply_returns_text_without_tool_calls(self) -> None:
        response = _make_response("Ola, tudo bem?")
        client = FakeOpenAiClient([response])
        sut = OpenAiCompatibleClient(_settings(), client=client)

        result = sut.complete([{"role": "user", "content": "oi"}])

        assert result == LlmReply(text="Ola, tudo bem?", tool_calls=())

    def test_reply_with_one_tool_call_decodes_arguments_and_text_is_none(self) -> None:
        response = _make_response("", tool_calls=[("call-1", "get_policy", '{"topic": "hours"}')])
        client = FakeOpenAiClient([response])
        sut = OpenAiCompatibleClient(_settings(), client=client)

        result = sut.complete([{"role": "user", "content": "horario?"}])

        assert result.text is None
        assert result.tool_calls == (
            ToolCall(id="call-1", name="get_policy", arguments={"topic": "hours"}),
        )

    def test_reply_with_whitespace_only_content_has_text_none(self) -> None:
        response = _make_response("   ", tool_calls=[("call-1", "get_policy", "{}")])
        client = FakeOpenAiClient([response])
        sut = OpenAiCompatibleClient(_settings(), client=client)

        result = sut.complete([{"role": "user", "content": "horario?"}])

        assert result.text is None

    def test_reply_with_two_tool_calls_preserves_order(self) -> None:
        response = _make_response(
            None,
            tool_calls=[
                ("call-1", "search_products", "{}"),
                ("call-2", "get_store_status", "{}"),
            ],
        )
        client = FakeOpenAiClient([response])
        sut = OpenAiCompatibleClient(_settings(), client=client)

        result = sut.complete([{"role": "user", "content": "..."}])

        assert [call.name for call in result.tool_calls] == ["search_products", "get_store_status"]
        assert [call.id for call in result.tool_calls] == ["call-1", "call-2"]

    def test_tool_call_with_invalid_json_arguments_becomes_empty_dict(self) -> None:
        response = _make_response(None, tool_calls=[("call-1", "search_products", "{nao e json")])
        client = FakeOpenAiClient([response])
        sut = OpenAiCompatibleClient(_settings(), client=client)

        result = sut.complete([{"role": "user", "content": "..."}])

        assert result.tool_calls[0].arguments == {}

    def test_call_without_tools_omits_tools_and_tool_choice_keys(self) -> None:
        client = FakeOpenAiClient([_make_response("ok")])
        sut = OpenAiCompatibleClient(_settings(), client=client)

        sut.complete([{"role": "user", "content": "oi"}])

        kwargs = client.calls[0]
        assert "tools" not in kwargs
        assert "tool_choice" not in kwargs

    def test_call_with_tools_includes_tools_and_tool_choice_auto(self) -> None:
        client = FakeOpenAiClient([_make_response("ok")])
        sut = OpenAiCompatibleClient(_settings(), client=client)
        tools = [{"type": "function", "function": {"name": "get_store_status"}}]

        sut.complete([{"role": "user", "content": "oi"}], tools=tools)

        kwargs = client.calls[0]
        assert kwargs["tools"] == tools
        assert kwargs["tool_choice"] == "auto"

    def test_call_never_includes_reasoning_format(self) -> None:
        client = FakeOpenAiClient([_make_response("ok")])
        sut = OpenAiCompatibleClient(_settings(), client=client)
        tools = [{"type": "function", "function": {"name": "get_store_status"}}]

        sut.complete([{"role": "user", "content": "oi"}], tools=tools)

        assert "reasoning_format" not in client.calls[0]

    def test_response_without_any_choice_raises_llm_error(self) -> None:
        client = FakeOpenAiClient([SimpleNamespace(choices=[])])
        sut = OpenAiCompatibleClient(_settings(), client=client)

        with pytest.raises(LlmError):
            sut.complete([{"role": "user", "content": "oi"}])


class TestOpenAiCompatibleClientResilience:
    """Criterios 7 a 12: 429, timeout/conexao, erro irrecuperavel e sigilo da chave."""

    def test_rate_limit_with_retry_after_waits_the_informed_seconds(self) -> None:
        error = FakeApiStatusError("limite excedido", status_code=429, headers={"retry-after": "2"})
        client = FakeOpenAiClient([error, _make_response("ok")])
        sleeps: list[float] = []
        sut = OpenAiCompatibleClient(_settings(), client=client, sleep=sleeps.append, max_attempts=3)

        result = sut.complete([{"role": "user", "content": "oi"}])

        assert result.text == "ok"
        assert sleeps == [2.0]

    def test_rate_limit_exhausted_raises_unavailable(self) -> None:
        errors = [FakeApiStatusError("limite", status_code=429) for _ in range(3)]
        client = FakeOpenAiClient(list(errors))
        sleeps: list[float] = []
        sut = OpenAiCompatibleClient(_settings(), client=client, sleep=sleeps.append, max_attempts=3)

        with pytest.raises(LlmUnavailable):
            sut.complete([{"role": "user", "content": "oi"}])

        assert len(sleeps) == 2

    def test_rate_limit_without_retry_after_uses_fixed_backoff(self) -> None:
        errors = [
            FakeApiStatusError("limite", status_code=429),
            FakeApiStatusError("limite", status_code=429),
        ]
        client = FakeOpenAiClient([*errors, _make_response("ok")])
        sleeps: list[float] = []
        sut = OpenAiCompatibleClient(_settings(), client=client, sleep=sleeps.append, max_attempts=3)

        sut.complete([{"role": "user", "content": "oi"}])

        assert sleeps == [1.0, 2.0]

    def test_connection_error_exhausted_raises_unavailable(self) -> None:
        client = FakeOpenAiClient(
            [FakeConnectionError("falhou"), FakeConnectionError("falhou"), FakeConnectionError("falhou")]
        )
        sleeps: list[float] = []
        sut = OpenAiCompatibleClient(_settings(), client=client, sleep=sleeps.append, max_attempts=3)

        with pytest.raises(LlmUnavailable):
            sut.complete([{"role": "user", "content": "oi"}])

        assert len(sleeps) == 2

    def test_server_error_exhausted_raises_unavailable(self) -> None:
        errors = [FakeApiStatusError("fora do ar", status_code=503) for _ in range(3)]
        client = FakeOpenAiClient(list(errors))
        sleeps: list[float] = []
        sut = OpenAiCompatibleClient(_settings(), client=client, sleep=sleeps.append, max_attempts=3)

        with pytest.raises(LlmUnavailable):
            sut.complete([{"role": "user", "content": "oi"}])

    def test_authentication_error_fails_immediately_without_retry(self) -> None:
        client = FakeOpenAiClient([FakeApiStatusError("chave invalida", status_code=401)])
        sleeps: list[float] = []
        sut = OpenAiCompatibleClient(_settings(), client=client, sleep=sleeps.append, max_attempts=3)

        with pytest.raises(LlmError):
            sut.complete([{"role": "user", "content": "oi"}])

        assert sleeps == []
        assert len(client.calls) == 1

    def test_other_4xx_error_fails_immediately_without_retry(self) -> None:
        client = FakeOpenAiClient([FakeApiStatusError("payload invalido", status_code=400)])
        sleeps: list[float] = []
        sut = OpenAiCompatibleClient(_settings(), client=client, sleep=sleeps.append, max_attempts=3)

        with pytest.raises(LlmError):
            sut.complete([{"role": "user", "content": "oi"}])

        assert sleeps == []

    def test_error_messages_never_contain_the_api_key(self) -> None:
        api_key = "segredo-super-secreto"
        client = FakeOpenAiClient(
            [FakeApiStatusError(f"Incorrect API key provided: {api_key}", status_code=401)]
        )
        sut = OpenAiCompatibleClient(
            _settings(llm_api_key=api_key), client=client, sleep=lambda _seconds: None
        )

        with pytest.raises(LlmError) as exc_info:
            sut.complete([{"role": "user", "content": "oi"}])

        assert api_key not in str(exc_info.value)
        assert api_key not in repr(exc_info.value)


class TestOpenAiCompatibleClientConstruction:
    """O cliente real so e construido quando nenhum client e injetado."""

    def test_builds_openai_client_with_fallback_key_when_empty(self) -> None:
        settings = _settings(llm_api_key="")
        sut = OpenAiCompatibleClient(settings)

        assert sut._client.api_key == "nao-usada"
        assert str(sut._client.base_url).rstrip("/") == settings.llm_base_url.rstrip("/")

    def test_builds_openai_client_using_the_configured_api_key(self) -> None:
        settings = _settings(llm_api_key="chave-de-verdade")
        sut = OpenAiCompatibleClient(settings)

        assert sut._client.api_key == "chave-de-verdade"


class TestScriptedLlm:
    """Criterio 13: o dublê roteirizado usado pelas demais tarefas."""

    def test_returns_replies_in_order(self) -> None:
        first = reply_text("oi, como posso ajudar?")
        second = reply_tool("get_store_status")
        fake = ScriptedLlm([first, second])

        assert fake.complete([{"role": "user", "content": "oi"}]) == first
        assert fake.complete([{"role": "user", "content": "a loja esta aberta?"}]) == second

    def test_records_messages_and_tools_sent(self) -> None:
        fake = ScriptedLlm([reply_text("ok")])
        messages = [{"role": "user", "content": "oi"}]
        tools = [{"type": "function", "function": {"name": "get_store_status"}}]

        fake.complete(messages, tools=tools)

        assert fake.calls == [((messages[0],), (tools[0],))]

    def test_raises_assertion_error_when_called_beyond_the_script(self) -> None:
        fake = ScriptedLlm([reply_text("ok")])
        fake.complete([{"role": "user", "content": "oi"}])

        with pytest.raises(AssertionError):
            fake.complete([{"role": "user", "content": "de novo"}])

    def test_reply_tool_builds_a_single_tool_call_with_arguments(self) -> None:
        reply = reply_tool("get_policy", call_id="call-9", topic="hours")

        assert reply.text is None
        assert reply.tool_calls == (ToolCall(id="call-9", name="get_policy", arguments={"topic": "hours"}),)
