"""Runner dos evals (T-15): roda os cenários de `evals.scenarios` contra um
`LlmClient` de verdade e verifica ferramenta esperada + fatos obrigatórios/
proibidos na resposta final.

Cada cenário monta o seu próprio agente (catálogo e pedidos reais, mas
sessão em memória e `JsonlHandoffSink` em arquivo temporário): nunca toca
`data/history.sqlite3` nem `data/handoffs.jsonl` reais, e nunca o `.env`
real quando o cenário fixa `store_today` (entra via o mapeamento de
ambiente passado a `load_settings`).

A pausa de 30 segundos entre cenários e a repetição única em caso de
indisponibilidade do provedor existem por causa do limite de taxa da
camada gratuita do Groq — ver `evals/README.md` e
`notas-internas/cenarios-eval.md` para a conta de tokens que justifica.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

from emporio.agent.llm import LlmClient, OpenAiCompatibleClient
from emporio.agent.loop import _FALLBACK_LLM_UNAVAILABLE, Agent
from emporio.config import Clock, ConfigError, Settings, build_clock, load_settings
from emporio.data.catalog import Catalog
from emporio.data.orders import OrderBook
from emporio.policies.store import load_policy_book
from emporio.textnorm import normalize_text
from emporio.tools.base import JsonDict
from emporio.tools.handoff_tools import JsonlHandoffSink
from emporio.tools.registry import build_registry
from evals.scenarios import SCENARIOS, Scenario

__all__ = [
    "ORDER_TOOL_NAME",
    "ScenarioResult",
    "contains_fact",
    "run_scenario",
    "run_all",
    "main",
]

# Única ferramenta de pedido do agente: é o que "nenhuma ferramenta de
# pedido usada com sucesso" (caso E-04) verifica.
ORDER_TOOL_NAME: Final[str] = "get_order_status"

_DEFAULT_SLEEP_SECONDS: Final[float] = 30.0

_MISSING_KEY_MESSAGE: Final[str] = (
    "Nao encontrei uma chave de LLM configurada (LLM_API_KEY). Os evals precisam do "
    "provedor real - configure o .env (camada gratuita do Groq) antes de rodar."
)

# Normalizacao tolerante de dinheiro/percentual (ver evals/README.md):
# remove separador de milhar ("." "," ou espaco entre grupos de 3 digitos
# que nao seguem de outro digito) e o espaco antes do sinal de "%". Nao
# toca a virgula decimal (que fica seguida de 1 ou 2 digitos apenas).
_THOUSANDS_SEP_RE = re.compile(r"(?<=\d)[.,\s](?=\d{3}(?!\d))")
_PERCENT_SPACE_RE = re.compile(r"(?<=\d)\s+(?=%)")


def _normalize_money(text: str) -> str:
    """Normaliza `text` para comparacao tolerante de valores em dinheiro/percentual."""
    normalized = normalize_text(text)
    normalized = _THOUSANDS_SEP_RE.sub("", normalized)
    normalized = _PERCENT_SPACE_RE.sub("", normalized)
    return normalized


def contains_fact(haystack: str, needle: str) -> bool:
    """Diz se `needle` aparece em `haystack`, tolerando acento/caixa/espaco e
    formatacao de dinheiro/percentual (separador de milhar, espaco antes de "%")."""
    return _normalize_money(needle) in _normalize_money(haystack)


@dataclass(frozen=True)
class ScenarioResult:
    """Resultado da avaliação de um cenário."""

    scenario: Scenario
    passed: bool
    unavailable: bool
    tools_used: tuple[str, ...]
    reply: str
    missing: tuple[str, ...]
    forbidden_found: tuple[str, ...]
    elapsed_seconds: float


def _successful_tool_names(messages: Sequence[JsonDict]) -> set[str]:
    """Extrai os nomes das ferramentas cujo resultado veio sem `error`.

    Correlaciona `tool_call_id` das mensagens `assistant` (que trazem o
    nome) com as mensagens `tool` (que trazem o resultado), sem depender de
    nenhum campo novo no contrato do loop do agente.
    """
    id_to_name: dict[str, str] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or ():
            call_id = call.get("id")
            name = (call.get("function") or {}).get("name")
            if call_id and name:
                id_to_name[call_id] = name

    successful: set[str] = set()
    for message in messages:
        if message.get("role") != "tool":
            continue
        name = id_to_name.get(message.get("tool_call_id"))
        if name is None:
            continue
        raw_content = message.get("content", "")
        try:
            content = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
        except (json.JSONDecodeError, TypeError):
            content = {}
        if isinstance(content, dict) and "error" not in content:
            successful.add(name)
    return successful


def _tools_ok(scenario: Scenario, tools_used: tuple[str, ...], successful_tools: set[str]) -> bool:
    """Critério de ferramenta: ver docstring de `Scenario.expected_tools`."""
    if scenario.expected_tools:
        return any(name in tools_used for name in scenario.expected_tools)
    return ORDER_TOOL_NAME not in successful_tools


def _scenario_env(settings: Settings, scenario: Scenario, tmp_dir: Path) -> dict[str, str]:
    """Monta o mapeamento de ambiente de um cenário: mesmo provedor, sem tocar o `.env`."""
    env: dict[str, str] = {
        "LLM_BASE_URL": settings.llm_base_url,
        "LLM_API_KEY": settings.llm_api_key,
        "LLM_MODEL": settings.llm_model,
        "LLM_TIMEOUT_SECONDS": str(settings.llm_timeout_seconds),
        "HISTORY_DB_PATH": str(tmp_dir / "history.sqlite3"),
    }
    if scenario.store_today is not None:
        env["STORE_TODAY"] = scenario.store_today
    return env


def run_scenario(
    scenario: Scenario, *, settings: Settings, llm: LlmClient | None = None
) -> ScenarioResult:
    """Roda um cenário de ponta a ponta: monta o agente, conversa, avalia a resposta final."""
    start = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="emporio-eval-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        scenario_settings = load_settings(_scenario_env(settings, scenario, tmp_dir))
        clock: Clock = build_clock(scenario_settings)

        catalog = Catalog.load(scenario_settings.raw_data_dir)
        order_book = OrderBook.load(scenario_settings.raw_data_dir)
        policy_book = load_policy_book(scenario_settings.processed_data_dir / "politicas.json")
        handoff_sink = JsonlHandoffSink(tmp_dir / "handoffs.jsonl")
        registry = build_registry(
            catalog=catalog,
            order_book=order_book,
            policy_book=policy_book,
            clock=clock,
            handoff_sink=handoff_sink,
        )
        llm_client = llm if llm is not None else OpenAiCompatibleClient(scenario_settings)
        agent = Agent(llm=llm_client, registry=registry, clock=clock)

        history: tuple[JsonDict, ...] = ()
        reply = ""
        tools_used: list[str] = []
        for message in scenario.messages:
            turn = agent.respond(message, history=history)
            tools_used.extend(turn.tool_calls_made)
            history = history + turn.new_messages
            reply = turn.reply

    elapsed = time.monotonic() - start
    unavailable = reply == _FALLBACK_LLM_UNAVAILABLE

    if unavailable:
        missing: tuple[str, ...] = ()
        forbidden_found: tuple[str, ...] = ()
        passed = False
    else:
        successful_tools = _successful_tool_names(history)
        missing = tuple(fact for fact in scenario.must_contain if not contains_fact(reply, fact))
        forbidden_found = tuple(
            fact for fact in scenario.must_not_contain if contains_fact(reply, fact)
        )
        tools_ok = _tools_ok(scenario, tuple(tools_used), successful_tools)
        passed = tools_ok and not missing and not forbidden_found

    return ScenarioResult(
        scenario=scenario,
        passed=passed,
        unavailable=unavailable,
        tools_used=tuple(tools_used),
        reply=reply,
        missing=missing,
        forbidden_found=forbidden_found,
        elapsed_seconds=elapsed,
    )


def run_all(
    scenarios: Sequence[Scenario],
    *,
    settings: Settings,
    sleep_seconds: float = _DEFAULT_SLEEP_SECONDS,
    llm: LlmClient | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[ScenarioResult, ...]:
    """Roda `scenarios` em sequência, com pausa entre eles e uma repetição se indisponível."""
    results: list[ScenarioResult] = []
    for index, scenario in enumerate(scenarios):
        if index > 0:
            sleep(sleep_seconds)

        result = run_scenario(scenario, settings=settings, llm=llm)
        if result.unavailable:
            sleep(sleep_seconds)
            result = run_scenario(scenario, settings=settings, llm=llm)

        results.append(result)
    return tuple(results)


def _situacao(result: ScenarioResult) -> str:
    if result.unavailable:
        return "não avaliado (provedor indisponível)"
    return "aprovado" if result.passed else "falhou"


def _format_result_line(result: ScenarioResult) -> str:
    scenario = result.scenario
    requisitos = ", ".join(scenario.requirements)
    line = f"{scenario.scenario_id} · {scenario.title} · {requisitos} · {_situacao(result)}"
    if result.unavailable or result.passed:
        return line

    details = []
    if scenario.expected_tools or result.tools_used:
        details.append(f"ferramentas usadas: {', '.join(result.tools_used) or '(nenhuma)'}")
    if result.missing:
        details.append(f"faltou: {', '.join(result.missing)}")
    if result.forbidden_found:
        details.append(f"apareceu proibido: {', '.join(result.forbidden_found)}")
    if details:
        line += "\n    " + " · ".join(details)
    return line


def _print_report(results: Sequence[ScenarioResult]) -> None:
    for result in results:
        print(_format_result_line(result))

    evaluated = [r for r in results if not r.unavailable]
    passed_count = sum(1 for r in evaluated if r.passed)
    failed_count = len(evaluated) - passed_count
    unavailable_count = len(results) - len(evaluated)
    total_elapsed = sum(r.elapsed_seconds for r in results)

    print()
    print(
        f"Resumo: {passed_count} aprovado(s), {failed_count} falhou(aram), "
        f"{unavailable_count} não avaliado(s) de {len(results)} cenário(s) · "
        f"{total_elapsed:.1f}s"
    )


def _result_to_json(result: ScenarioResult) -> JsonDict:
    scenario_dict = asdict(result.scenario)
    return {
        "scenario": scenario_dict,
        "passed": result.passed,
        "unavailable": result.unavailable,
        "tools_used": list(result.tools_used),
        "reply": result.reply,
        "missing": list(result.missing),
        "forbidden_found": list(result.forbidden_found),
        "elapsed_seconds": result.elapsed_seconds,
    }


def _write_json(results: Sequence[ScenarioResult], path: Path) -> None:
    payload: JsonDict = {"results": [_result_to_json(result) for result in results]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emporio-evals", description="Avalia o agente contra o provedor real de LLM"
    )
    parser.add_argument("--only", help="lista separada por vírgula de scenario_id (ex.: E-02,E-05)")
    parser.add_argument("--json", dest="json_path", help="grava o resultado completo neste arquivo")
    return parser


def _select_scenarios(only: str | None) -> tuple[Scenario, ...]:
    if only is None:
        return SCENARIOS
    ids = {value.strip() for value in only.split(",") if value.strip()}
    return tuple(scenario for scenario in SCENARIOS if scenario.scenario_id in ids)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    llm: LlmClient | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Ponto de entrada: roda os cenários (ou um subconjunto) e imprime o relatório."""
    load_dotenv()

    parser = _build_parser()
    args = parser.parse_args(argv)

    effective_env: Mapping[str, str] = env if env is not None else os.environ

    try:
        settings = load_settings(effective_env)
    except ConfigError as exc:
        print(f"Configuração inválida: {exc}")
        return 2

    if not settings.llm_api_key.strip():
        print(_MISSING_KEY_MESSAGE)
        return 2

    sleep_seconds_raw = effective_env.get("EVAL_SLEEP_SECONDS", str(_DEFAULT_SLEEP_SECONDS))
    try:
        sleep_seconds = float(sleep_seconds_raw)
    except ValueError:
        print(f"EVAL_SLEEP_SECONDS deve ser um número, recebido: {sleep_seconds_raw!r}")
        return 2

    scenarios = _select_scenarios(args.only)
    if not scenarios:
        print(f"Nenhum cenário encontrado para --only {args.only!r}.")
        return 2

    results = run_all(
        scenarios, settings=settings, sleep_seconds=sleep_seconds, llm=llm, sleep=sleep
    )
    _print_report(results)

    if args.json_path:
        _write_json(results, Path(args.json_path))

    evaluated = [result for result in results if not result.unavailable]
    if any(not result.passed for result in evaluated):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
