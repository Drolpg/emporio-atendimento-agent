"""Testes do livro de pedidos: carga, totais historicos e verificacao do titular.

Usa os CSVs reais de `data/raw/` (sem rede, sem chave de API). O teste central
de privacidade (criterio 19) prova que `verify` nunca casa com o cadastro de
outro cliente que compartilha o mesmo e-mail.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from emporio.config import project_root
from emporio.data.catalog import Catalog
from emporio.data.orders import OrderBook

RAW_DIR = project_root() / "data" / "raw"


@pytest.fixture(scope="module")
def order_book() -> OrderBook:
    return OrderBook.load(RAW_DIR)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(RAW_DIR)


class TestCarga:
    """Contagens basicas e itens de pedido (criterio 13)."""

    def test_numero_de_pedidos(self, order_book: OrderBook):
        pedidos_ids = range(1, 21)
        pedidos = [order_book.order(order_id) for order_id in pedidos_ids]
        assert all(pedido is not None for pedido in pedidos)
        assert order_book.order(21) is None

    def test_numero_de_clientes(self, order_book: OrderBook):
        clientes_ids = range(1, 51)
        clientes = [order_book.customer(customer_id) for customer_id in clientes_ids]
        assert all(cliente is not None for cliente in clientes)
        assert order_book.customer(51) is None

    def test_todo_pedido_tem_ao_menos_um_item(self, order_book: OrderBook):
        for order_id in range(1, 21):
            pedido = order_book.order(order_id)
            assert pedido is not None
            assert len(pedido.items) >= 1

    def test_pedido_15_tem_dois_itens(self, order_book: OrderBook):
        pedido = order_book.order(15)
        assert pedido is not None
        assert len(pedido.items) == 2


class TestTotalHistorico:
    """O total do pedido nao e recalculado a partir dos itens (criterio 14, P-16)."""

    def test_pedido_3_total_nao_recalculado(self, order_book: OrderBook, catalog: Catalog):
        pedido = order_book.order(3)
        assert pedido is not None
        assert pedido.total_brl == Decimal("3450")

        soma_dos_itens = Decimal("0")
        for item in pedido.items:
            produto = catalog.product(item.product_id)
            assert produto is not None
            soma_dos_itens += produto.price_brl * item.quantity

        assert soma_dos_itens == Decimal("3498")
        assert soma_dos_itens != pedido.total_brl

    def test_pedido_20_total(self, order_book: OrderBook):
        pedido = order_book.order(20)
        assert pedido is not None
        assert pedido.total_brl == Decimal("1400")

    def test_total_brl_e_decimal(self, order_book: OrderBook):
        pedido = order_book.order(3)
        assert pedido is not None
        assert isinstance(pedido.total_brl, Decimal)


class TestFormaDePagamento:
    """payment_method do CSV separado em forma + parcelas (criterio 15)."""

    @pytest.mark.parametrize(
        ("order_id", "payment_form", "installments"),
        [
            (1, "pix", 1),
            (2, "credit", 6),
            (3, "credit", 12),
            (7, "credit", 3),
            (8, "debit", 1),
            (4, "boleto", 1),
        ],
    )
    def test_forma_e_parcelas(
        self, order_book: OrderBook, order_id: int, payment_form: str, installments: int
    ):
        pedido = order_book.order(order_id)
        assert pedido is not None
        assert pedido.payment_form == payment_form
        assert pedido.installments == installments


class TestCamposOpcionais:
    """tracking_code, notes e estimated_delivery sao None quando nao se aplicam (criterio 16)."""

    @pytest.mark.parametrize("order_id", range(1, 9))
    def test_tracking_code_existe_nos_pedidos_despachados(
        self, order_book: OrderBook, order_id: int
    ):
        pedido = order_book.order(order_id)
        assert pedido is not None
        assert pedido.tracking_code is not None

    @pytest.mark.parametrize("order_id", range(9, 21))
    def test_tracking_code_e_none_nos_demais(self, order_book: OrderBook, order_id: int):
        pedido = order_book.order(order_id)
        assert pedido is not None
        assert pedido.tracking_code is None

    @pytest.mark.parametrize("order_id", range(17, 21))
    def test_notes_existe_so_nos_cancelados(self, order_book: OrderBook, order_id: int):
        pedido = order_book.order(order_id)
        assert pedido is not None
        assert pedido.notes is not None

    @pytest.mark.parametrize("order_id", range(1, 17))
    def test_notes_e_none_nos_nao_cancelados(self, order_book: OrderBook, order_id: int):
        pedido = order_book.order(order_id)
        assert pedido is not None
        assert pedido.notes is None

    @pytest.mark.parametrize("order_id", [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
    def test_estimated_delivery_none_sem_previsao(self, order_book: OrderBook, order_id: int):
        pedido = order_book.order(order_id)
        assert pedido is not None
        assert pedido.estimated_delivery is None


class TestReceivedDate:
    """Recebimento vem de `estimated_delivery` so quando `delivered` (criterio 17, P-04)."""

    def test_pedido_7_delivered(self, order_book: OrderBook):
        pedido = order_book.order(7)
        assert pedido is not None
        assert pedido.status == "delivered"
        assert pedido.received_date == date(2026, 2, 17)

    def test_pedido_8_shipped_com_previsao_nao_e_recebido(self, order_book: OrderBook):
        pedido = order_book.order(8)
        assert pedido is not None
        assert pedido.status == "shipped"
        assert pedido.estimated_delivery is not None
        assert pedido.received_date is None

    def test_pedido_13_pending(self, order_book: OrderBook):
        pedido = order_book.order(13)
        assert pedido is not None
        assert pedido.status == "pending"
        assert pedido.received_date is None


class TestVerify:
    """`verify` so casa contra o cliente daquele pedido (criterios 18 a 23, RNF-02)."""

    def test_email_do_titular_do_pedido_10(self, order_book: OrderBook):
        pedido = order_book.verify(10, "bruno.martins@jmail.com")
        assert pedido is not None
        assert pedido.order_id == 10

    def test_email_compartilhado_mas_telefone_de_outro_cliente_nao_casa(
        self, order_book: OrderBook
    ):
        """Teste central de privacidade: o e-mail bruno.martins@jmail.com pertence
        aos clientes 11 e 43; o pedido 10 e do cliente 11, e o telefone informado
        e do cliente 43 -- nao pode casar."""
        pedido = order_book.verify(10, "(67) 99456-3456")
        assert pedido is None

    @pytest.mark.parametrize(
        "telefone",
        ["98543-2109", "67985432109", "5567985432109"],
    )
    def test_telefone_com_e_sem_ddd_e_com_codigo_de_pais(
        self, order_book: OrderBook, telefone: str
    ):
        pedido = order_book.verify(10, telefone)
        assert pedido is not None
        assert pedido.order_id == 10

    def test_menos_de_oito_digitos_nunca_casa(self, order_book: OrderBook):
        pedido = order_book.verify(10, "2109")
        assert pedido is None

    def test_pedido_inexistente_devolve_none(self, order_book: OrderBook):
        pedido = order_book.verify(999, "qualquer@email.com")
        assert pedido is None

    def test_email_errado_devolve_none_indistinguivel_do_pedido_inexistente(
        self, order_book: OrderBook
    ):
        pedido = order_book.verify(10, "errado@email.com")
        assert pedido is None

    def test_email_em_caixa_alta(self, order_book: OrderBook):
        pedido = order_book.verify(1, "PEDRO.OLIVEIRA@JMAIL.COM")
        assert pedido is not None
        assert pedido.order_id == 1
