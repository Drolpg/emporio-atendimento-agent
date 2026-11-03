"""Persistencia do historico de conversa em SQLite, por `session_id` (T-13, D-04).

Cada sessao guarda a conversa inteira, inclusive as mensagens `assistant`
com `tool_calls` e as mensagens `tool`: e isso que permite retomar uma
sessao com o contexto de ferramenta intacto (RF-11). O que vai ao LLM e uma
janela recente (RNF-08, ver `emporio.agent.loop`); aqui fica a sessao
completa.

Abre e fecha uma conexao sqlite por operacao, para nunca deixar um handle
pendurado que impeca o arquivo de ser removido (ex.: `tmp_path` dos testes).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from emporio.config import Clock
from emporio.tools.base import JsonDict

__all__ = ["SessionInfo", "ConversationStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);
"""


@dataclass(frozen=True)
class SessionInfo:
    """Resumo de uma sessao gravada, para listar em `emporio sessions`."""

    session_id: str
    message_count: int
    started_at: str
    last_at: str


def _connect(path: Path) -> sqlite3.Connection:
    """Abre uma conexao sqlite, sem deixar o chamador esquecer de fechar."""
    return sqlite3.connect(path, check_same_thread=False)


@dataclass(frozen=True)
class ConversationStore:
    """Historico de conversa por sessao, persistido em um arquivo sqlite."""

    path: Path
    clock: Clock

    @classmethod
    def open(cls, path: Path, clock: Clock) -> ConversationStore:
        """Cria o diretorio pai e o schema (se faltarem) e devolve o store."""
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        return cls(path=path, clock=clock)

    def append(self, session_id: str, messages: Sequence[JsonDict]) -> None:
        """Grava `messages` ao final da sessao, com `seq` continuo a partir do que ja existe."""
        if not messages:
            return

        created_at = self.clock.now().isoformat()
        conn = _connect(self.path)
        try:
            cursor = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM messages WHERE session_id = ?",
                (session_id,),
            )
            next_seq = cursor.fetchone()[0] + 1

            rows = [
                (
                    session_id,
                    next_seq + offset,
                    message.get("role", ""),
                    json.dumps(message, ensure_ascii=False),
                    created_at,
                )
                for offset, message in enumerate(messages)
            ]
            conn.executemany(
                "INSERT INTO messages (session_id, seq, role, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def load(self, session_id: str, limit: int | None = None) -> tuple[JsonDict, ...]:
        """Devolve as mensagens da sessao em ordem de `seq`; com `limit`, as ultimas."""
        conn = _connect(self.path)
        try:
            if limit is None:
                cursor = conn.execute(
                    "SELECT payload_json FROM messages WHERE session_id = ? ORDER BY seq",
                    (session_id,),
                )
                rows = cursor.fetchall()
            else:
                cursor = conn.execute(
                    "SELECT payload_json FROM messages WHERE session_id = ? "
                    "ORDER BY seq DESC LIMIT ?",
                    (session_id, limit),
                )
                rows = list(reversed(cursor.fetchall()))
        finally:
            conn.close()
        return tuple(json.loads(row[0]) for row in rows)

    def sessions(self) -> tuple[SessionInfo, ...]:
        """Lista as sessoes gravadas, da mais recente para a mais antiga por `last_at`."""
        conn = _connect(self.path)
        try:
            cursor = conn.execute(
                "SELECT session_id, COUNT(*), MIN(created_at), MAX(created_at) "
                "FROM messages GROUP BY session_id ORDER BY MAX(created_at) DESC"
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return tuple(
            SessionInfo(session_id=row[0], message_count=row[1], started_at=row[2], last_at=row[3])
            for row in rows
        )

    def clear(self, session_id: str) -> int:
        """Apaga todas as mensagens da sessao e devolve quantas foram apagadas."""
        conn = _connect(self.path)
        try:
            cursor = conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
