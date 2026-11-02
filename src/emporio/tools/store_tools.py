"""Ferramenta de status da loja (RF-08): aberta agora e proxima abertura.

O nome do dia da semana vem de um mapa escrito por nos (nunca de `locale` do
sistema, que varia por maquina). Feriados nao sao modelados (P-06): o aviso
curto evita que o agente afirme que a loja vai abrir num feriado.
"""

from __future__ import annotations

from datetime import time

from emporio.config import Clock
from emporio.domain.store_hours import store_status
from emporio.tools.base import JsonDict, ToolSpec

__all__ = ["build_store_tools"]

# weekday() de Python: 0 = segunda, ..., 6 = domingo. A preposicao ja vem
# certa ("na segunda-feira" / "no sábado" / "no domingo").
_WEEKDAY_WITH_PREPOSITION_PT: dict[int, str] = {
    0: "na segunda-feira",
    1: "na terça-feira",
    2: "na quarta-feira",
    3: "na quinta-feira",
    4: "na sexta-feira",
    5: "no sábado",
    6: "no domingo",
}

_HOLIDAY_NOTE = (
    "Feriados não estão cadastrados no sistema; em feriados a loja não abre, mesmo que "
    "o dia da semana sugira o contrário."
)


def _format_time(value: time) -> str:
    """Formata um `time` como \"HH:MM\"."""
    return value.strftime("%H:%M")


def build_store_tools(clock: Clock) -> tuple[ToolSpec, ...]:
    """Monta a ferramenta `get_store_status`, sem parametros."""

    def handler() -> JsonDict:
        status = store_status(clock.now())
        result: JsonDict = {
            "is_open": status.is_open,
            "holiday_note": _HOLIDAY_NOTE,
        }

        if status.is_open:
            assert status.opens_at is not None
            assert status.closes_at is not None
            result["today_opens_at"] = _format_time(status.opens_at)
            result["today_closes_at"] = _format_time(status.closes_at)
            result["message"] = f"Estamos abertos agora, até às {_format_time(status.closes_at)}."
        else:
            if status.opens_at is not None and status.closes_at is not None:
                result["today_opens_at"] = _format_time(status.opens_at)
                result["today_closes_at"] = _format_time(status.closes_at)
            else:
                result["today_hours_message"] = "Hoje a loja não abre."

            assert status.next_opening is not None
            weekday_text = _WEEKDAY_WITH_PREPOSITION_PT[status.next_opening.weekday()]
            next_opening_time = _format_time(status.next_opening.time())
            result["next_opening_iso"] = status.next_opening.isoformat()
            result["message"] = (
                f"Estamos fechados agora; abrimos {weekday_text} às {next_opening_time}."
            )

        return result

    spec = ToolSpec(
        name="get_store_status",
        description=(
            "Diz se a loja está aberta agora, no horário de Campo Grande (seg a sex "
            "09:00–18:00, sáb 09:00–13:00, domingo fechado), e quando reabre se "
            "estiver fechada."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=handler,
    )
    return (spec,)
