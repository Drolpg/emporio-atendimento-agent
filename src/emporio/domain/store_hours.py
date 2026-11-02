"""Horario de funcionamento da loja e proxima abertura (RF-08, manual 2).

Funcao pura: a data e a hora entram por parametro (``moment``), nunca via
``datetime.now()``. Feriados nao sao modelados (P-06).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from emporio.config import STORE_TZ

__all__ = ["StoreStatus", "store_status", "add_business_hours"]


def _hours_for_weekday(weekday: int) -> tuple[time, time] | None:
    """Devolve (abertura, fechamento) do dia da semana, ou None se fechado o dia inteiro.

    ``weekday``: 0 = segunda, ..., 6 = domingo (convencao de ``date.weekday()``).
    """
    if weekday <= 4:  # segunda a sexta
        return (time(9, 0), time(18, 0))
    if weekday == 5:  # sabado
        return (time(9, 0), time(13, 0))
    return None  # domingo


@dataclass(frozen=True)
class StoreStatus:
    """Situacao da loja no momento consultado."""

    is_open: bool
    opens_at: time | None
    closes_at: time | None
    next_opening: datetime | None


def _next_opening(moment: datetime) -> datetime:
    """Calcula a proxima abertura (aware, em STORE_TZ) a partir de um momento fechado.

    A abertura e sempre as 09:00 (segunda a sabado); so precisa achar a
    proxima data que nao e domingo.
    """
    todays_hours = _hours_for_weekday(moment.weekday())
    if todays_hours is not None and moment.time() < todays_hours[0]:
        next_date: date = moment.date()
    else:
        next_date = moment.date() + timedelta(days=1)
        while _hours_for_weekday(next_date.weekday()) is None:
            next_date += timedelta(days=1)
    return datetime.combine(next_date, time(9, 0), tzinfo=STORE_TZ)


def store_status(moment: datetime) -> StoreStatus:
    """Diz se a loja esta aberta no momento informado e quando reabre, se fechada.

    ``moment`` precisa ser aware; datetime ingenuo gera ``ValueError``. E
    normalizado para ``STORE_TZ`` antes de qualquer decisao.
    """
    if moment.tzinfo is None:
        raise ValueError("moment deve ser aware (ter tzinfo)")

    moment = moment.astimezone(STORE_TZ)
    hours = _hours_for_weekday(moment.weekday())

    if hours is None:
        opens_at: time | None = None
        closes_at: time | None = None
        is_open = False
    else:
        opens_at, closes_at = hours
        is_open = opens_at <= moment.time() < closes_at

    next_opening = None if is_open else _next_opening(moment)

    return StoreStatus(
        is_open=is_open,
        opens_at=opens_at,
        closes_at=closes_at,
        next_opening=next_opening,
    )


def add_business_hours(moment: datetime, hours: int) -> datetime:
    """Avanca `hours` horas de expediente a partir de `moment` (RF-10, prazo de 24h uteis).

    Respeita o horario da loja (seg a sex 09:00-18:00, sab 09:00-13:00,
    domingo fechado). Se `moment` cair fora do expediente, a contagem
    comeca na proxima abertura. `moment` precisa ser aware; ingenuo gera
    `ValueError`. `hours` negativo tambem gera `ValueError` (nao ha caso de
    uso para "horas uteis no passado" neste produto).
    """
    if moment.tzinfo is None:
        raise ValueError("moment deve ser aware (ter tzinfo)")
    if hours < 0:
        raise ValueError("hours nao pode ser negativo")

    moment = moment.astimezone(STORE_TZ)
    status = store_status(moment)
    current = moment if status.is_open else status.next_opening
    assert current is not None  # fechado sempre tem proxima abertura

    remaining = timedelta(hours=hours)
    while True:
        hours_today = _hours_for_weekday(current.weekday())
        assert hours_today is not None  # current e sempre um momento de expediente
        _, closes_at = hours_today
        day_close = datetime.combine(current.date(), closes_at, tzinfo=STORE_TZ)
        available_today = day_close - current

        if remaining <= available_today:
            return current + remaining

        remaining -= available_today
        current = _next_opening(day_close)
