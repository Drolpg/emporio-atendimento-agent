"""Formatacao de dinheiro compartilhada pelas ferramentas de catalogo e pedidos.

Unico lugar que converte um valor em reais (`Decimal`) para o texto e o
numero que o LLM recebe; evita duplicar a mesma conta em cada ferramenta
nova (T-10 em diante).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = ["format_brl", "to_cents"]


def format_brl(value: Decimal) -> str:
    """Formata um valor em reais no padrao brasileiro (ex.: "R$ 2.199,00")."""
    quant = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if quant < 0 else ""
    quant = abs(quant)
    integer_part, decimal_part = f"{quant:.2f}".split(".")
    groups = [integer_part[max(i - 3, 0) : i] for i in range(len(integer_part), 0, -3)]
    grouped_integer = ".".join(reversed(groups))
    return f"{sign}R$ {grouped_integer},{decimal_part}"


def to_cents(value: Decimal) -> int:
    """Converte um valor em reais para centavos (inteiro), para comparacao numerica."""
    quant = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((quant * 100).to_integral_value(rounding=ROUND_HALF_UP))
