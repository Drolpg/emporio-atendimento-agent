"""CLI interativa do agente (T-14): `emporio chat`, `emporio ask` e `emporio sessions`.

E a interface que o avaliador executa e que gera as transcricoes dos evals
(T-15) e dos exemplos de conversa (T-16). `main` e o unico lugar do projeto
que chama `load_dotenv()`: `load_settings` nao faz isso de proposito, para o
`pytest` rodar sem rede e sem `.env` (RNF-04).
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from dotenv import load_dotenv
from rich.console import Console

from emporio.agent.llm import LlmClient, OpenAiCompatibleClient
from emporio.agent.loop import Agent, AgentTurn
from emporio.config import Clock, Settings, build_clock, load_settings
from emporio.data.catalog import Catalog
from emporio.data.orders import OrderBook
from emporio.history.store import ConversationStore, SessionInfo
from emporio.policies.store import load_policy_book
from emporio.tools.registry import build_registry

__all__ = ["build_agent", "main"]

_HELP_TEXT = (
    "Comandos: /sair encerra a conversa, /nova abre outra sessao, "
    "/sessoes lista as sessoes gravadas, /ajuda mostra esta mensagem."
)

_MISSING_KEY_MESSAGE = (
    "Nao encontrei uma chave de LLM configurada. Copie .env.example para .env e "
    "preencha LLM_API_KEY (camada gratuita do Groq) - ou, sem chave nenhuma, use a "
    "alternativa local com Ollama documentada no proprio .env.example."
)

_BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def build_agent(settings: Settings, clock: Clock, llm: LlmClient | None = None) -> Agent:
    """Monta o registro de ferramentas e o agente a partir da configuracao.

    `llm=None` usa o cliente real (`OpenAiCompatibleClient`); os testes
    injetam um LLM roteirizado para nunca tocar a rede.
    """
    catalog = Catalog.load(settings.raw_data_dir)
    order_book = OrderBook.load(settings.raw_data_dir)
    policy_book = load_policy_book(settings.processed_data_dir / "politicas.json")
    registry = build_registry(
        catalog=catalog, order_book=order_book, policy_book=policy_book, clock=clock
    )
    llm_client = llm if llm is not None else OpenAiCompatibleClient(settings)
    return Agent(llm=llm_client, registry=registry, clock=clock)


def _base36(number: int) -> str:
    """Codifica `number` (>= 0) em base36, sem zero a esquerda."""
    if number == 0:
        return "0"
    digits: list[str] = []
    while number:
        number, remainder = divmod(number, 36)
        digits.append(_BASE36_DIGITS[remainder])
    return "".join(reversed(digits))


def _new_session_id(clock: Clock, existing_ids: Sequence[str]) -> str:
    """Gera um id curto e legivel, derivado da data da loja e de uma contagem.

    Deterministico com `FixedClock`: o sufixo vem de quantas sessoes do dia
    ja existem, nunca de `random` sem semente.
    """
    prefix = clock.today().isoformat()
    same_day = sum(1 for session_id in existing_ids if session_id.startswith(f"{prefix}-"))
    suffix = _base36(same_day + 1).rjust(4, "0")
    return f"{prefix}-{suffix}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emporio", description="Agente de atendimento Empório")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat_parser = subparsers.add_parser("chat", help="conversa interativa com o agente")
    chat_parser.add_argument("--session", help="id da sessao a abrir ou retomar")
    chat_parser.add_argument("--new", action="store_true", help="forca uma sessao nova")

    ask_parser = subparsers.add_parser("ask", help="um turno so, imprime a resposta e sai")
    ask_parser.add_argument("question", help="pergunta para o agente")
    ask_parser.add_argument("--session", help="grava o turno nesta sessao")

    subparsers.add_parser("sessions", help="lista as sessoes gravadas")

    return parser


def _tool_line(turn: AgentTurn) -> str | None:
    """Monta a linha de transparencia sobre as ferramentas usadas, ou None se nenhuma."""
    if not turn.tool_calls_made:
        return None
    seen: list[str] = []
    for name in turn.tool_calls_made:
        if name not in seen:
            seen.append(name)
    return "· consultou: " + ", ".join(seen)


def _store_today_notice(settings: Settings) -> str | None:
    """Avisa quando `STORE_TODAY` fixa a data da loja, para nao confundir com a data real."""
    if settings.store_today is None:
        return None
    return f"[data da loja fixada por STORE_TODAY: {settings.store_today.isoformat()}]"


def _print_sessions(console: Console, sessions: Sequence[SessionInfo]) -> None:
    if not sessions:
        console.print("Nenhuma sessão gravada ainda.")
        return
    for info in sessions:
        console.print(
            f"{info.session_id} · {info.message_count} mensagem(ns) · "
            f"início em {info.started_at} · última em {info.last_at}"
        )


def _run_sessions(settings: Settings, clock: Clock, console: Console) -> int:
    store = ConversationStore.open(settings.history_db_path, clock)
    _print_sessions(console, store.sessions())
    return 0


def _run_ask(
    args: argparse.Namespace,
    settings: Settings,
    clock: Clock,
    agent: Agent,
    console: Console,
) -> int:
    if args.session:
        store = ConversationStore.open(settings.history_db_path, clock)
        history = store.load(args.session)
    else:
        store = None
        history = ()

    turn = agent.respond(args.question, history=history)

    if store is not None:
        store.append(args.session, turn.new_messages)

    console.print(turn.reply)
    tool_line = _tool_line(turn)
    if tool_line is not None:
        console_err = Console(file=sys.stderr, markup=False)
        console_err.print(tool_line)
    return 0


def _resolve_chat_session(args: argparse.Namespace, store: ConversationStore, clock: Clock) -> str:
    """Decide o id de sessao de `emporio chat`, conforme `--session` e `--new`."""
    if args.session:
        return args.session
    sessions = store.sessions()
    if args.new or not sessions:
        return _new_session_id(clock, [info.session_id for info in sessions])
    return sessions[0].session_id


def _run_chat(
    args: argparse.Namespace,
    settings: Settings,
    clock: Clock,
    agent: Agent,
    console: Console,
    stdin: TextIO,
) -> int:
    store = ConversationStore.open(settings.history_db_path, clock)
    session_id = _resolve_chat_session(args, store, clock)
    resumed_count = len(store.load(session_id))

    console.print(
        f"Sessão {session_id} · modelo {settings.llm_model} ({settings.llm_base_url}) · "
        f"{resumed_count} mensagem(ns) retomada(s)"
    )
    console.print(_HELP_TEXT, style="dim")

    while True:
        console.print("Você: ", end="")
        raw_line = stdin.readline()
        if raw_line == "":
            console.print()
            console.print("Até mais!")
            return 0

        line = raw_line.strip()
        if not line:
            continue

        if line == "/sair":
            console.print("Até mais!")
            return 0
        if line == "/ajuda":
            console.print(_HELP_TEXT, style="dim")
            continue
        if line == "/sessoes":
            _print_sessions(console, store.sessions())
            continue
        if line == "/nova":
            session_id = _new_session_id(clock, [info.session_id for info in store.sessions()])
            resumed_count = 0
            console.print(f"Nova sessão: {session_id}", style="dim")
            continue

        history = store.load(session_id)
        turn = agent.respond(line, history=history)
        store.append(session_id, turn.new_messages)

        console.print(turn.reply, style="bold cyan")
        tool_line = _tool_line(turn)
        if tool_line is not None:
            console.print(tool_line, style="dim")


def _ensure_utf8_streams() -> None:
    """Forca utf-8 em stdout/stderr, para o portugues com acento nao virar lixo.

    Alguns terminais (ex.: `cmd`/PowerShell no Windows) abrem os streams numa
    codificacao local que nao suporta todos os acentos. Melhor esforco: se o
    stream nao aceitar `reconfigure` (ex.: capturado pelo `pytest`), ignora.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8")


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    clock: Clock | None = None,
    llm: LlmClient | None = None,
    stdin: TextIO | None = None,
) -> int:
    """Ponto de entrada do comando `emporio`.

    Parametros extras (`env`, `clock`, `llm`, `stdin`) existem para os testes
    injetarem configuracao, relogio, LLM e entrada sem tocar o ambiente real
    nem a rede; a entrada real do comando so usa `argv`.
    """
    load_dotenv()
    _ensure_utf8_streams()

    parser = _build_parser()
    args = parser.parse_args(argv)

    # `markup=False`: a resposta do agente e textos de cliente podem conter
    # colchetes (ex.: codigo de rastreio, trecho de manual) que o rich por
    # padrao tentaria interpretar como tag de estilo.
    console = Console(markup=False)

    try:
        settings = load_settings(env)
    except Exception as exc:  # noqa: BLE001 - configuracao invalida, sem stack trace
        console.print(f"Configuração inválida: {exc}", style="bold red")
        return 1

    effective_clock = clock if clock is not None else build_clock(settings)

    if args.command == "sessions":
        try:
            return _run_sessions(settings, effective_clock, console)
        except Exception as exc:  # noqa: BLE001
            console.print(f"Erro inesperado: {exc.__class__.__name__}", style="bold red")
            return 1

    # chat e ask precisam do provedor de LLM configurado.
    if not settings.llm_api_key.strip():
        console.print(_MISSING_KEY_MESSAGE, style="bold red")
        return 2

    store_today_notice = _store_today_notice(settings)
    if store_today_notice is not None:
        console.print(store_today_notice, style="dim")

    try:
        agent = build_agent(settings, effective_clock, llm)
        if args.command == "ask":
            return _run_ask(args, settings, effective_clock, agent, console)
        if args.command == "chat":
            effective_stdin = stdin if stdin is not None else sys.stdin
            return _run_chat(args, settings, effective_clock, agent, console, effective_stdin)
    except Exception as exc:  # noqa: BLE001 - erro inesperado, sem stack trace ao usuario
        console.print(f"Erro inesperado: {exc.__class__.__name__}", style="bold red")
        return 1

    parser.error(f"comando desconhecido: {args.command}")
    return 2
