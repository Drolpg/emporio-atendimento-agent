"""Regras de preco: promocao, PIX, parcelamento e pagamento combinado.

Funcoes puras (RF-03, manual 3, 3.1 e 6.2). Nenhuma delas le arquivo, variavel
de ambiente ou relogio; todo valor de dinheiro entra e sai como ``Decimal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

__all__ = [
    "PIX_DISCOUNT_PERCENT",
    "COMBINED_PAYMENT_MIN",
    "INSTALLMENT_BANDS",
    "PriceQuote",
    "promotional_price",
    "pix_price",
    "max_installments",
    "allows_combined_payment",
    "quote",
]


# Desconto do PIX sobre o preco de tabela (manual 6.2)
PIX_DISCOUNT_PERCENT: Final[Decimal] = Decimal("5")

# Minimo para habilitar pagamento combinado (estritamente acima, manual 3)
COMBINED_PAYMENT_MIN: Final[Decimal] = Decimal("2000")

# Faixas de parcela minima por numero de parcelas (manual 3.1): (n_min, n_max, parcela_minima)
INSTALLMENT_BANDS: Final[tuple[tuple[int, int, Decimal], ...]] = (
    (1, 3, Decimal("50")),
    (4, 6, Decimal("80")),
    (7, 12, Decimal("100")),
)

_CENTS: Final[Decimal] = Decimal("0.01")


def _round_money(value: Decimal) -> Decimal:
    """Arredonda um valor em reais a centavos, com ROUND_HALF_UP."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _installment_min(n: int) -> Decimal:
    """Devolve a parcela minima da faixa que contem ``n``."""
    for n_min, n_max, min_installment in INSTALLMENT_BANDS:
        if n_min <= n <= n_max:
            return min_installment
    raise ValueError(f"numero de parcelas fora do intervalo 1..12: {n}")


@dataclass(frozen=True)
class PriceQuote:
    """Cotacao completa de preco para um produto."""

    list_price: Decimal
    discount_percent: int | None
    final_price: Decimal
    pix_price: Decimal | None
    max_installments: int
    installment_value: Decimal | None
    allows_combined_payment: bool


def promotional_price(list_price: Decimal, discount_percent: int | None) -> Decimal:
    """Calcula o preco final a partir do preco de tabela e do desconto da promocao.

    Sem promocao ativa (``discount_percent is None``), o preco final e igual ao
    de tabela. Com promocao, aplica o percentual e arredonda a centavos.
    """
    if discount_percent is None:
        return list_price
    factor = (Decimal(100) - Decimal(discount_percent)) / Decimal(100)
    return _round_money(list_price * factor)


def pix_price(list_price: Decimal, has_active_promotion: bool) -> Decimal | None:
    """Calcula o preco no PIX: 5% sobre o preco de tabela, nao cumulativo.

    Quando ha promocao ativa no produto, o desconto do PIX nao se aplica e o
    resultado e ``None`` (manual 6.2).
    """
    if has_active_promotion:
        return None
    factor = (Decimal(100) - PIX_DISCOUNT_PERCENT) / Decimal(100)
    return _round_money(list_price * factor)


def max_installments(total: Decimal) -> int:
    """Devolve o maior numero de parcelas (1 a 12) que respeita a parcela minima.

    ``n = 1`` (a vista) e sempre permitido. Para os demais, compara
    ``total >= n * parcela_minima(n)`` em vez de dividir, para nao depender de
    arredondamento de divisao na comparacao.
    """
    for n in range(12, 1, -1):
        if total >= Decimal(n) * _installment_min(n):
            return n
    return 1


def allows_combined_payment(total: Decimal) -> bool:
    """Diz se o total permite combinar formas de pagamento (estritamente acima do minimo)."""
    return total > COMBINED_PAYMENT_MIN


def quote(list_price: Decimal, discount_percent: int | None = None) -> PriceQuote:
    """Monta a cotacao completa de preco para um produto.

    O PIX usa o preco de tabela como base; o parcelamento e o pagamento
    combinado usam o preco final (ja com a promocao aplicada, se houver).
    """
    final_price = promotional_price(list_price, discount_percent)
    has_active_promotion = discount_percent is not None
    pix = pix_price(list_price, has_active_promotion)

    installments = max_installments(final_price)
    installment_value = None if installments == 1 else _round_money(final_price / installments)

    return PriceQuote(
        list_price=list_price,
        discount_percent=discount_percent,
        final_price=final_price,
        pix_price=pix,
        max_installments=installments,
        installment_value=installment_value,
        allows_combined_payment=allows_combined_payment(final_price),
    )
