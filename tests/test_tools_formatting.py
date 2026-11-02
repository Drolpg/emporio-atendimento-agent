"""Testes da formatacao de dinheiro compartilhada pelas ferramentas."""

from __future__ import annotations

from decimal import Decimal

import pytest

from emporio.tools.formatting import format_brl, to_cents


class TestFormatBrl:
    """`format_brl` usa separador de milhar "." e decimal ",", sem separador abaixo de mil."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("2089.05"), "R$ 2.089,05"),
            (Decimal("5519.08"), "R$ 5.519,08"),
            (Decimal("8732"), "R$ 8.732,00"),
            (Decimal("439.20"), "R$ 439,20"),
            (Decimal("0"), "R$ 0,00"),
        ],
    )
    def test_valores_exatos(self, value: Decimal, expected: str):
        assert format_brl(value) == expected


class TestToCents:
    """`to_cents` converte reais para centavos inteiros."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("2089.05"), 208905),
            (Decimal("5519.08"), 551908),
            (Decimal("8732"), 873200),
            (Decimal("439.20"), 43920),
        ],
    )
    def test_valores_exatos(self, value: Decimal, expected: int):
        assert to_cents(value) == expected
