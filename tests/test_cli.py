"""Testes da CLI (T-14): conversa interativa, turno unico e listagem de sessoes.

Sem rede: o LLM e sempre `ScriptedLlm` (dublê) injetado via `main(..., llm=...)`.
O store aponta para `tmp_path` via `HISTORY_DB_PATH` no `env` injetado, para
nunca tocar `data/history.sqlite3` real nem o `.env` do projeto.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pytest

from emporio.cli import main
from emporio.config import STORE_TZ, FixedClock
from emporio.history.store import ConversationStore
from tests.fakes.llm import ScriptedLlm, reply_text, reply_tool


def _env(tmp_path: Path, *, api_key: str = "chave-de-teste", **overrides: str) -> dict[str, str]:
    env = {
        "LLM_API_KEY": api_key,
        "LLM_MODEL": "modelo-de-teste",
        "LLM_BASE_URL": "https://provedor.invalido/v1",
        "HISTORY_DB_PATH": str(tmp_path / "history.sqlite3"),
    }
    env.update(overrides)
    return env


def _clock(hour: int = 10, day: int = 2) -> FixedClock:
    return FixedClock(datetime(2026, 11, day, hour, tzinfo=STORE_TZ))


def _stdin(*lines: str) -> io.StringIO:
    text = "".join(f"{line}\n" for line in lines)
    return io.StringIO(text)


class TestSessionsVazio:
    """Criterio 10: `sessions` com store vazio imprime algo informativo e devolve 0."""

    def test_sessions_vazio(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        code = main(["sessions"], env=_env(tmp_path), clock=_clock())

        captured = capsys.readouterr()
        assert code == 0
        assert "sessão" in captured.out.lower() or "sessao" in captured.out.lower()


class TestAskComLlmInjetado:
    """Criterio 11: `ask` com LLM injetado imprime a resposta no stdout e devolve 0."""

    def test_ask_imprime_resposta_no_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        llm = ScriptedLlm([reply_text("Olá! Sou a Nina, como posso ajudar?")])

        code = main(["ask", "Oi"], env=_env(tmp_path), clock=_clock(), llm=llm)

        captured = capsys.readouterr()
        assert code == 0
        assert "Olá! Sou a Nina" in captured.out


class TestAskGravaSoComSessao:
    """Criterio 12: `ask --session` grava no store; sem `--session`, nao grava nada."""

    def test_ask_com_session_grava(self, tmp_path: Path):
        llm = ScriptedLlm([reply_text("Resposta gravada")])
        env = _env(tmp_path)

        code = main(["ask", "Oi", "--session", "s1"], env=env, clock=_clock(), llm=llm)

        assert code == 0
        store = ConversationStore.open(tmp_path / "history.sqlite3", _clock())
        loaded = store.load("s1")
        assert any(m.get("content") == "Oi" for m in loaded)
        assert any(m.get("content") == "Resposta gravada" for m in loaded)

    def test_ask_sem_session_nao_grava(self, tmp_path: Path):
        llm = ScriptedLlm([reply_text("Resposta efêmera")])
        env = _env(tmp_path)

        code = main(["ask", "Oi"], env=env, clock=_clock(), llm=llm)

        assert code == 0
        store = ConversationStore.open(tmp_path / "history.sqlite3", _clock())
        assert store.sessions() == ()


class TestChatAbreEEncerraLimpo:
    """Criterio 13: `chat` com `/sair` na primeira linha abre e encerra limpo."""

    def test_chat_sair_na_primeira_linha(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        llm = ScriptedLlm([])

        code = main(
            ["chat"], env=_env(tmp_path), clock=_clock(), llm=llm, stdin=_stdin("/sair")
        )

        captured = capsys.readouterr()
        assert code == 0
        assert "Sessão" in captured.out


class TestChatGravaOTurno:
    """Criterio 14: depois de uma mensagem e `/sair`, o store tem as mensagens do turno."""

    def test_chat_grava_mensagens_do_turno(self, tmp_path: Path):
        llm = ScriptedLlm([reply_text("Oi, tudo bem?")])
        env = _env(tmp_path)

        code = main(
            ["chat", "--session", "s1"],
            env=env,
            clock=_clock(),
            llm=llm,
            stdin=_stdin("Olá", "/sair"),
        )

        assert code == 0
        store = ConversationStore.open(tmp_path / "history.sqlite3", _clock())
        loaded = store.load("s1")
        assert any(m.get("content") == "Olá" for m in loaded)
        assert any(m.get("content") == "Oi, tudo bem?" for m in loaded)


class TestChatRetomaSessaoExistente:
    """Criterio 15: `chat --session X` passa o historico gravado ao agente."""

    def test_chat_retomado_passa_historico_ao_llm(self, tmp_path: Path):
        env = _env(tmp_path)
        clock = _clock()
        pre_store = ConversationStore.open(tmp_path / "history.sqlite3", clock)
        pre_store.append(
            "antiga",
            [
                {"role": "user", "content": "mensagem antiga do cliente"},
                {"role": "assistant", "content": "resposta antiga da Nina"},
            ],
        )

        llm = ScriptedLlm([reply_text("Resposta nova")])

        code = main(
            ["chat", "--session", "antiga"],
            env=env,
            clock=clock,
            llm=llm,
            stdin=_stdin("Mais uma pergunta", "/sair"),
        )

        assert code == 0
        assert len(llm.calls) == 1
        messages_sent = llm.calls[0][0]
        assert any(m.get("content") == "mensagem antiga do cliente" for m in messages_sent)
        assert any(m.get("content") == "resposta antiga da Nina" for m in messages_sent)


class TestChaveVaziaAsk:
    """Criterio 16: chave vazia em `ask` devolve 2 e cita `.env.example`, sem chamar o provedor."""

    def test_chave_vazia_devolve_2_sem_chamar_provedor(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        llm = ScriptedLlm([])  # qualquer chamada levanta AssertionError

        code = main(
            ["ask", "Oi"], env=_env(tmp_path, api_key=""), clock=_clock(), llm=llm
        )

        captured = capsys.readouterr()
        assert code == 2
        assert ".env.example" in captured.out or ".env.example" in captured.err
        assert llm.calls == []


class TestLinhaDeFerramentas:
    """Criterio 17: a linha de ferramentas aparece so quando o turno usou ferramenta."""

    def test_linha_aparece_quando_usa_ferramenta(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        llm = ScriptedLlm(
            [
                reply_tool("list_categories"),
                reply_text("Temos estas categorias."),
            ]
        )

        code = main(["ask", "Quais categorias vocês têm?"], env=_env(tmp_path), clock=_clock(), llm=llm)

        captured = capsys.readouterr()
        assert code == 0
        assert "list_categories" in captured.err

    def test_linha_nao_aparece_sem_ferramenta(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        llm = ScriptedLlm([reply_text("Oi!")])

        code = main(["ask", "Oi"], env=_env(tmp_path), clock=_clock(), llm=llm)

        captured = capsys.readouterr()
        assert code == 0
        assert "consultou" not in captured.err


class TestAvisoStoreToday:
    """Criterio 18: `STORE_TODAY` preenchido avisa que a data esta fixada."""

    def test_aviso_store_today(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        llm = ScriptedLlm([reply_text("Oi!")])
        env = _env(tmp_path, STORE_TODAY="2026-11-02")

        code = main(["ask", "Oi"], env=env, llm=llm)

        captured = capsys.readouterr()
        assert code == 0
        assert "STORE_TODAY" in captured.out


class TestChaveNuncaAparece:
    """Criterio 19: a chave de API nunca aparece em nenhuma saida da CLI."""

    _SECRET = "chave-secreta-de-teste"

    def test_chave_nao_aparece_em_sessions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        main(["sessions"], env=_env(tmp_path, api_key=self._SECRET), clock=_clock())

        captured = capsys.readouterr()
        assert self._SECRET not in captured.out
        assert self._SECRET not in captured.err

    def test_chave_nao_aparece_em_ask(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        llm = ScriptedLlm([reply_text("Oi!")])
        main(["ask", "Oi"], env=_env(tmp_path, api_key=self._SECRET), clock=_clock(), llm=llm)

        captured = capsys.readouterr()
        assert self._SECRET not in captured.out
        assert self._SECRET not in captured.err

    def test_chave_nao_aparece_em_chat(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        llm = ScriptedLlm([reply_text("Oi!")])
        main(
            ["chat"],
            env=_env(tmp_path, api_key=self._SECRET),
            clock=_clock(),
            llm=llm,
            stdin=_stdin("Olá", "/sair"),
        )

        captured = capsys.readouterr()
        assert self._SECRET not in captured.out
        assert self._SECRET not in captured.err
