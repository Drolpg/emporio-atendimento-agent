"""Testes do historico em SQLite (T-13): persistencia por sessao e retomada.

Usa `FixedClock` para o `created_at` ser determinístico e `tmp_path` para
cada teste abrir seu proprio arquivo, sem conexao pendurada entre eles.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from emporio.config import STORE_TZ, FixedClock
from emporio.history.store import ConversationStore, SessionInfo


def _clock(hour: int = 10, minute: int = 0, day: int = 2) -> FixedClock:
    return FixedClock(datetime(2026, 11, day, hour, minute, tzinfo=STORE_TZ))


def _open(tmp_path: Path, clock: FixedClock | None = None) -> ConversationStore:
    return ConversationStore.open(tmp_path / "sub" / "history.sqlite3", clock or _clock())


class TestAppendLoad:
    """Criterio 1: append + load devolve na ordem, seq continua entre chamadas."""

    def test_append_load_ordem_e_seq_continuo(self, tmp_path: Path):
        store = _open(tmp_path)
        store.append("s1", [{"role": "user", "content": "oi"}])
        store.append(
            "s1",
            [
                {"role": "assistant", "content": "ola"},
                {"role": "user", "content": "tudo bem?"},
            ],
        )

        loaded = store.load("s1")
        assert [m["content"] for m in loaded] == ["oi", "ola", "tudo bem?"]


class TestToolMessagesSobrevivem:
    """Criterio 2: assistant com tool_calls e tool sobrevivem sem perder campo."""

    def test_tool_calls_e_tool_result_ida_e_volta(self, tmp_path: Path):
        store = _open(tmp_path)
        assistant_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search_products", "arguments": '{"query": "violao"}'},
                }
            ],
        }
        tool_msg = {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"items": []}',
        }
        store.append("s1", [assistant_msg, tool_msg])

        loaded = store.load("s1")
        assert loaded[0] == assistant_msg
        assert loaded[1] == tool_msg


class TestLoadLimit:
    """Criterio 3: load(limit=3) devolve as ultimas tres."""

    def test_load_com_limit_devolve_ultimas(self, tmp_path: Path):
        store = _open(tmp_path)
        for i in range(5):
            store.append("s1", [{"role": "user", "content": f"msg-{i}"}])

        loaded = store.load("s1", limit=3)
        assert [m["content"] for m in loaded] == ["msg-2", "msg-3", "msg-4"]


class TestSessoesNaoSeMisturam:
    """Criterio 4: load de uma sessao nao traz mensagem de outra; seq independente."""

    def test_sessoes_distintas_tem_seq_proprio(self, tmp_path: Path):
        store = _open(tmp_path)
        store.append("s1", [{"role": "user", "content": "de s1"}])
        store.append("s2", [{"role": "user", "content": "de s2"}])
        store.append("s1", [{"role": "user", "content": "de s1 outra vez"}])

        loaded_s1 = store.load("s1")
        loaded_s2 = store.load("s2")

        assert [m["content"] for m in loaded_s1] == ["de s1", "de s1 outra vez"]
        assert [m["content"] for m in loaded_s2] == ["de s2"]


class TestSessions:
    """Criterio 5: sessions() lista da mais recente para a mais antiga."""

    def test_sessions_ordenadas_por_last_at_desc(self, tmp_path: Path):
        clock = _clock(hour=9)
        store = _open(tmp_path, clock)
        store.append("antiga", [{"role": "user", "content": "a"}])

        clock_depois = _clock(hour=12)
        store_depois = ConversationStore.open(store.path, clock_depois)
        store_depois.append("recente", [{"role": "user", "content": "b"}])
        store_depois.append("recente", [{"role": "user", "content": "c"}])

        sessions = store_depois.sessions()
        assert [s.session_id for s in sessions] == ["recente", "antiga"]
        assert sessions[0].message_count == 2
        assert sessions[1].message_count == 1

    def test_sessions_devolve_sessioninfo_com_datas(self, tmp_path: Path):
        clock = _clock(hour=10, minute=30)
        store = _open(tmp_path, clock)
        store.append("s1", [{"role": "user", "content": "oi"}])

        sessions = store.sessions()
        assert len(sessions) == 1
        info = sessions[0]
        assert isinstance(info, SessionInfo)
        assert info.session_id == "s1"
        assert info.message_count == 1
        assert info.started_at == clock.now().isoformat()
        assert info.last_at == clock.now().isoformat()


class TestClear:
    """Criterio 6: clear apaga so a sessao pedida e devolve a quantidade apagada."""

    def test_clear_apaga_so_a_sessao_pedida(self, tmp_path: Path):
        store = _open(tmp_path)
        store.append("s1", [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
        store.append("s2", [{"role": "user", "content": "c"}])

        removed = store.clear("s1")

        assert removed == 2
        assert store.load("s1") == ()
        assert [m["content"] for m in store.load("s2")] == ["c"]


class TestCreatedAtDoRelogio:
    """Criterio 7: created_at vem do relogio injetado."""

    def test_created_at_igual_ao_relogio_fixo(self, tmp_path: Path):
        clock = _clock(hour=14, minute=5)
        store = _open(tmp_path, clock)
        store.append("s1", [{"role": "user", "content": "oi"}])

        rows = _raw_rows(store.path, "s1")
        assert rows[0][2] == clock.now().isoformat()


class TestOpenCriaDiretorio:
    """Criterio 8: open cria o arquivo e o diretorio pai se nao existirem."""

    def test_open_cria_arquivo_e_diretorio_pai(self, tmp_path: Path):
        path = tmp_path / "nao-existe-ainda" / "history.sqlite3"
        assert not path.exists()

        ConversationStore.open(path, _clock())

        assert path.exists()
        assert path.parent.is_dir()


class TestAcentuacaoSobrevive:
    """Criterio 9: acentuacao sobrevive a ida e volta."""

    def test_acentuacao_sobrevive(self, tmp_path: Path):
        store = _open(tmp_path)
        texto = "Temos promoção em violões hoje!"
        store.append("s1", [{"role": "assistant", "content": texto}])

        loaded = store.load("s1")
        assert loaded[0]["content"] == texto


def _raw_rows(path: Path, session_id: str) -> list[tuple]:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        cursor = conn.execute(
            "SELECT seq, role, created_at FROM messages WHERE session_id = ? ORDER BY seq",
            (session_id,),
        )
        return list(cursor.fetchall())
    finally:
        conn.close()
