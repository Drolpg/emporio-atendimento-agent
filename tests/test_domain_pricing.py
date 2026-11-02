"""Testes para as regras de preco, pix, parcelamento e pagamento combinado."""

from __future__ import annotations

from decimal import Decimal

import pytest

from emporio.domain.pricing import (
    COMBINED_PAYMENT_MIN,
    INSTALLMENT_BANDS,
    PIX_DISCOUNT_PERCENT,
    PriceQuote,
    allows_combined_payment,
    max_installments,
    pix_price,
    promotional_price,
    quote,
)


class TestConstants:
    """Testes para as constantes do modulo."""

    def test_pix_discount_percent(self):
        """O desconto do PIX e de 5%."""
        assert Decimal("5") == PIX_DISCOUNT_PERCENT

    def test_combined_payment_min(self):
        """O minimo para pagamento combinado e R$ 2000."""
        assert Decimal("2000") == COMBINED_PAYMENT_MIN

    def test_installment_bands(self):
        """As faixas de parcela minima seguem o manual 3.1."""
        expected = (
            (1, 3, Decimal("50")),
            (4, 6, Decimal("80")),
            (7, 12, Decimal("100")),
        )
        assert expected == INSTALLMENT_BANDS


class TestPromotionalPrice:
    """Testes para o preco com promocao."""

    def test_without_promotion_returns_list_price(self):
        """Sem desconto, o preco final e igual ao de tabela."""
        assert promotional_price(Decimal("359.00"), None) == Decimal("359.00")

    def test_with_discount_applies_percent(self):
        """Com desconto, aplica o percentual e arredonda a centavos."""
        # produto 94: tabela 5999.00, promocao de 8%
        assert promotional_price(Decimal("5999.00"), 8) == Decimal("5519.08")

    def test_product_90_discount(self):
        """Produto 90: tabela 2399.00, promocao de 18%."""
        assert promotional_price(Decimal("2399.00"), 18) == Decimal("1967.18")

    def test_rounds_half_up(self):
        """Arredondamento de centavos usa ROUND_HALF_UP."""
        # 10 * 0.335 = 3.35 -> mas vamos forcar um caso de meio centavo
        # 33.335 arredonda para 33.34 com ROUND_HALF_UP
        result = promotional_price(Decimal("66.67"), 50)
        assert result == Decimal("33.34")


class TestPixPrice:
    """Testes para o preco no PIX."""

    def test_pix_without_promotion(self):
        """Sem promocao ativa, o PIX da 5% sobre o preco de tabela."""
        # produto 95: tabela 2199.00, sem promocao
        assert pix_price(Decimal("2199.00"), has_active_promotion=False) == Decimal("2089.05")

    def test_pix_with_active_promotion_is_none(self):
        """Com promocao ativa, o desconto do PIX nao se aplica (nao cumulativo)."""
        assert pix_price(Decimal("5999.00"), has_active_promotion=True) is None


class TestMaxInstallments:
    """Testes para o numero maximo de parcelas."""

    @pytest.mark.parametrize(
        "total, expected",
        [
            (Decimal("49.00"), 1),
            (Decimal("50.00"), 1),
            (Decimal("100.00"), 2),
            (Decimal("159.90"), 3),
            (Decimal("480.00"), 6),
            (Decimal("599.90"), 6),
            (Decimal("700.00"), 7),
            (Decimal("1200.00"), 12),
            (Decimal("2199.00"), 12),
        ],
    )
    def test_cases(self, total, expected):
        """Cobre a tabela de aceite do briefing."""
        assert max_installments(total) == expected


class TestAllowsCombinedPayment:
    """Testes para a elegibilidade de pagamento combinado."""

    def test_below_min_not_allowed(self):
        """Abaixo de R$ 2000 nao permite pagamento combinado."""
        assert allows_combined_payment(Decimal("1999.99")) is False

    def test_exactly_min_not_allowed(self):
        """Exatamente R$ 2000 nao permite (precisa ser estritamente maior)."""
        assert allows_combined_payment(Decimal("2000.00")) is False

    def test_above_min_allowed(self):
        """Acima de R$ 2000 permite pagamento combinado."""
        assert allows_combined_payment(Decimal("2000.01")) is True


class TestQuote:
    """Testes para a cotacao completa de preco."""

    def test_product_95_no_promotion(self):
        """Produto 95: sem promocao ativa, tem pix_price e discount_percent None."""
        result = quote(Decimal("2199.00"))
        assert isinstance(result, PriceQuote)
        assert result.list_price == Decimal("2199.00")
        assert result.discount_percent is None
        assert result.final_price == Decimal("2199.00")
        assert result.pix_price == Decimal("2089.05")
        assert result.max_installments == 12
        assert result.installment_value == Decimal("183.25")
        assert result.allows_combined_payment is True

    def test_product_94_with_promotion(self):
        """Produto 94: tabela 5999.00, promocao de 8%, pix_price None."""
        result = quote(Decimal("5999.00"), discount_percent=8)
        assert result.discount_percent == 8
        assert result.final_price == Decimal("5519.08")
        assert result.pix_price is None
        assert result.allows_combined_payment is True

    def test_product_90_with_promotion(self):
        """Produto 90: tabela 2399.00, promocao de 18%, pix_price None."""
        result = quote(Decimal("2399.00"), discount_percent=18)
        assert result.discount_percent == 18
        assert result.final_price == Decimal("1967.18")
        assert result.pix_price is None

    def test_quote_uses_final_price_for_installments(self):
        """O parcelamento e o pagamento combinado usam o preco final, nao o de tabela."""
        # tabela 3000, promocao de 50% -> final 1500 (nao permite combinado)
        result = quote(Decimal("3000.00"), discount_percent=50)
        assert result.final_price == Decimal("1500.00")
        assert result.allows_combined_payment is False

    def test_quote_low_total_only_cash(self):
        """Total abaixo de R$ 50 so permite a vista."""
        result = quote(Decimal("49.00"))
        assert result.max_installments == 1
        assert result.installment_value is None
