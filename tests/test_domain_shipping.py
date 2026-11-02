"""Testes para a cotacao de frete por cidade."""

from __future__ import annotations

from decimal import Decimal

from emporio.domain.shipping import (
    FREE_SHIPPING_MIN,
    LOCAL_CITY,
    LOCAL_FLAT_FEE,
    ShippingOption,
    ShippingQuote,
    shipping_quote,
)


class TestConstants:
    """Testes para as constantes do modulo."""

    def test_local_city(self):
        """A cidade local e Campo Grande."""
        assert LOCAL_CITY == "Campo Grande"

    def test_free_shipping_min(self):
        """O frete gratis vale acima de R$ 500."""
        assert Decimal("500") == FREE_SHIPPING_MIN

    def test_local_flat_fee(self):
        """A taxa fixa local e R$ 35."""
        assert Decimal("35") == LOCAL_FLAT_FEE


class TestLocalShipping:
    """Testes para o frete em Campo Grande."""

    def test_below_free_threshold_pays_flat_fee(self):
        """Abaixo de R$ 500, paga a taxa fixa de R$ 35."""
        result = shipping_quote(city="Campo Grande", order_total=Decimal("499.99"))
        assert isinstance(result, ShippingQuote)
        assert result.is_local is True
        assert result.free is False
        assert len(result.options) == 1
        option = result.options[0]
        assert isinstance(option, ShippingOption)
        assert option.min_business_days == 1
        assert option.max_business_days == 3
        assert option.fee_brl == Decimal("35")

    def test_exactly_500_pays_flat_fee(self):
        """Exatamente R$ 500 ainda paga a taxa (precisa ser estritamente acima)."""
        result = shipping_quote(city="Campo Grande", order_total=Decimal("500.00"))
        assert result.free is False
        assert result.options[0].fee_brl == Decimal("35")

    def test_above_500_is_free(self):
        """Acima de R$ 500 o frete e gratis."""
        result = shipping_quote(city="Campo Grande", order_total=Decimal("500.01"))
        assert result.free is True
        assert result.options[0].fee_brl == Decimal("0")

    def test_case_and_accent_insensitive_city(self):
        """'campo grande', 'Campo Grande' e 'CAMPO  GRANDE' sao a mesma cidade."""
        for city in ("campo grande", "Campo Grande", "CAMPO  GRANDE"):
            result = shipping_quote(city=city, order_total=Decimal("100.00"))
            assert result.is_local is True

    def test_local_has_no_note(self):
        """Frete local nao precisa de nota sobre calculo posterior."""
        result = shipping_quote(city="Campo Grande", order_total=Decimal("100.00"))
        assert result.note is None


class TestOtherCityShipping:
    """Testes para o frete fora de Campo Grande."""

    def test_three_options_without_fee(self):
        """Fora de Campo Grande ha tres opcoes, sem valor fixo definido."""
        result = shipping_quote(city="Dourados", order_total=Decimal("1000.00"))
        assert result.is_local is False
        assert result.free is False
        assert len(result.options) == 3
        names = [option.name for option in result.options]
        assert "PAC" in names
        assert "SEDEX" in names
        assert "Jadlog" in names
        for option in result.options:
            assert option.fee_brl is None

    def test_business_days_ranges(self):
        """Os prazos em dias uteis seguem o manual 5.2."""
        result = shipping_quote(city="Dourados", order_total=Decimal("1000.00"))
        by_name = {option.name: option for option in result.options}
        assert (by_name["PAC"].min_business_days, by_name["PAC"].max_business_days) == (5, 12)
        assert (by_name["SEDEX"].min_business_days, by_name["SEDEX"].max_business_days) == (2, 5)
        assert (by_name["Jadlog"].min_business_days, by_name["Jadlog"].max_business_days) == (3, 8)

    def test_note_mentions_cep_and_individual_quote(self):
        """A nota explica que o valor sai pelo CEP e que ha cotacao individual."""
        result = shipping_quote(city="Tres Lagoas", order_total=Decimal("1000.00"))
        assert result.note is not None
        assert "CEP" in result.note
        assert "cotação individual" in result.note or "cotacao individual" in result.note

    def test_different_cities_are_not_local(self):
        """Dourados e Tres Lagoas nao sao Campo Grande."""
        for city in ("Dourados", "Três Lagoas"):
            result = shipping_quote(city=city, order_total=Decimal("1000.00"))
            assert result.is_local is False
