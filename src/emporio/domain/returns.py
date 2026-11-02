"""Elegibilidade de troca, devolucao e garantia (RF-07, D-08).

Cada modalidade tem sua propria data de referencia (manual 4.1, 4.2, 4.3 e
8.1): tres contam do recebimento e a troca por defeito conta da data da
compra. Funcoes puras; a data "hoje" entra por parametro.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

__all__ = ["ReturnKind", "ReturnWindow", "return_windows"]


class ReturnKind(StrEnum):
    """Modalidade de troca, devolucao ou garantia."""

    WITHDRAWAL = "withdrawal"
    PREFERENCE = "preference"
    DEFECT = "defect"
    LEGAL_WARRANTY = "legal_warranty"


@dataclass(frozen=True)
class ReturnWindow:
    """Janela de prazo de uma modalidade, calculada para uma data de referencia."""

    kind: ReturnKind
    deadline_days: int
    reference_date: date | None
    deadline: date | None
    is_open: bool
    days_remaining: int | None
    days_expired: int | None
    not_started: bool


def _build_window(
    kind: ReturnKind, deadline_days: int, reference_date: date | None, today: date
) -> ReturnWindow:
    """Monta a janela de uma modalidade a partir da data de referencia (se houver)."""
    if reference_date is None:
        return ReturnWindow(
            kind=kind,
            deadline_days=deadline_days,
            reference_date=None,
            deadline=None,
            is_open=False,
            days_remaining=None,
            days_expired=None,
            not_started=True,
        )

    deadline = reference_date + timedelta(days=deadline_days)
    is_open = today <= deadline

    return ReturnWindow(
        kind=kind,
        deadline_days=deadline_days,
        reference_date=reference_date,
        deadline=deadline,
        is_open=is_open,
        days_remaining=(deadline - today).days if is_open else None,
        days_expired=(today - deadline).days if not is_open else None,
        not_started=False,
    )


def return_windows(
    *, order_date: date, received_date: date | None, today: date
) -> tuple[ReturnWindow, ReturnWindow, ReturnWindow, ReturnWindow]:
    """Calcula as quatro janelas de troca/devolucao/garantia de um pedido.

    ``received_date`` e ``None`` quando o pedido ainda nao foi entregue
    (P-04): as modalidades que contam do recebimento ficam ``not_started``.
    A troca por defeito conta de ``order_date`` e por isso continua valendo
    mesmo sem entrega.
    """
    return (
        _build_window(ReturnKind.WITHDRAWAL, 7, received_date, today),
        _build_window(ReturnKind.PREFERENCE, 7, received_date, today),
        _build_window(ReturnKind.DEFECT, 30, order_date, today),
        _build_window(ReturnKind.LEGAL_WARRANTY, 90, received_date, today),
    )
