"""Cotacao de frete por cidade (RF-06, manual 5.1, 5.2 e 5.3).

Campo Grande (P-07: so a cidade, sem definir "regiao metropolitana") tem uma
opcao local com taxa fixa; qualquer outra cidade tem tres opcoes de
transportadora, com valor calculado no fechamento do pedido.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from emporio.textnorm import same_text

__all__ = [
    "LOCAL_CITY",
    "FREE_SHIPPING_MIN",
    "LOCAL_FLAT_FEE",
    "ShippingOption",
    "ShippingQuote",
    "shipping_quote",
]


LOCAL_CITY: Final[str] = "Campo Grande"
FREE_SHIPPING_MIN: Final[Decimal] = Decimal("500")
LOCAL_FLAT_FEE: Final[Decimal] = Decimal("35")

_OTHER_CITY_NOTE: Final[str] = (
    "O valor do frete é calculado no fechamento do pedido, de acordo com CEP, "
    "peso e dimensões; instrumentos de grande porte podem exigir cotação individual."
)


@dataclass(frozen=True)
class ShippingOption:
    """Uma opcao de envio."""

    name: str
    min_business_days: int
    max_business_days: int
    fee_brl: Decimal | None


@dataclass(frozen=True)
class ShippingQuote:
    """Cotacao de frete para um destino e um total de pedido."""

    is_local: bool
    free: bool
    options: tuple[ShippingOption, ...]
    note: str | None


def shipping_quote(*, city: str, order_total: Decimal) -> ShippingQuote:
    """Calcula as opcoes de frete para uma cidade e um total de pedido.

    Campo Grande: motoboy proprio, 1 a 3 dias uteis, gratis estritamente
    acima de ``FREE_SHIPPING_MIN`` (R$ 500 exatos pagam a taxa fixa).
    Qualquer outra cidade: PAC, SEDEX e Jadlog, valor definido no fechamento.
    """
    if same_text(city, LOCAL_CITY):
        free = order_total > FREE_SHIPPING_MIN
        fee = Decimal("0") if free else LOCAL_FLAT_FEE
        option = ShippingOption(
            name="Motoboy próprio",
            min_business_days=1,
            max_business_days=3,
            fee_brl=fee,
        )
        return ShippingQuote(is_local=True, free=free, options=(option,), note=None)

    options = (
        ShippingOption(name="PAC", min_business_days=5, max_business_days=12, fee_brl=None),
        ShippingOption(name="SEDEX", min_business_days=2, max_business_days=5, fee_brl=None),
        ShippingOption(name="Jadlog", min_business_days=3, max_business_days=8, fee_brl=None),
    )
    return ShippingQuote(is_local=False, free=False, options=options, note=_OTHER_CITY_NOTE)
