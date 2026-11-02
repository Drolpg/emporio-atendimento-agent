"""Testes da ferramenta `get_order_status`: verificacao do titular e elegibilidade.

Usa os CSVs reais de `data/raw/` e `FixedClock` (sem rede, sem chave de API).
O criterio central (16) prova que o telefone de outro cliente com o mesmo
e-mail nao abre o pedido (RNF-02).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

import pytest

from emporio.config import STORE_TZ, FixedClock, project_root
from emporio.data.catalog import Catalog
from emporio.data.orders import OrderBook
from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools
from emporio.tools.order_tools import build_order_tools

RAW_DIR = project_root() / "data" / "raw"


@pytest.fixture(scope="module")
def order_book() -> OrderBook:
    return OrderBook.load(RAW_DIR)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(RAW_DIR)


def _clock(date_str: str) -> FixedClock:
    year, month, day = (int(part) for part in date_str.split("-"))
    return FixedClock(datetime(year, month, day, 10, 0, tzinfo=STORE_TZ))


def _tools_by_name(
    order_book: OrderBook, catalog: Catalog, clock: FixedClock
) -> Mapping[str, ToolSpec]:
    specs = build_order_tools(order_book, catalog, clock)
    return {spec.name: spec for spec in specs}


def _call(tools_by_name: Mapping[str, ToolSpec], **kwargs: object) -> JsonDict:
    return call_tool(tools_by_name, "get_order_status", kwargs)


def _collect_leaves(value: object) -> list[object]:
    """Lista recursivamente os valores-folha de um JsonDict (sem list/dict)."""
    if isinstance(value, dict):
        leaves: list[object] = []
        for item in value.values():
            leaves.extend(_collect_leaves(item))
        return leaves
    if isinstance(value, list):
        leaves = []
        for item in value:
            leaves.extend(_collect_leaves(item))
        return leaves
    return [value]


class TestBuildOrderTools:
    """A fabrica devolve so a ferramenta de status de pedido."""

    def test_devolve_uma_ferramenta(self, order_book: OrderBook, catalog: Catalog):
        specs = build_order_tools(order_book, catalog, _clock("2026-02-20"))
        assert [spec.name for spec in specs] == ["get_order_status"]


class TestVerificacaoDeTitularidade:
    """Verificacao exige numero do pedido + e-mail ou telefone do titular (criterios 15 a 17)."""

    def test_pedido_10_verificado_por_email(self, order_book: OrderBook, catalog: Catalog):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=10, email_or_phone="bruno.martins@jmail.com")
        assert result["order_id"] == 10

    def test_pedido_10_telefone_de_outro_cliente_falha(
        self, order_book: OrderBook, catalog: Catalog
    ):
        """Teste central: telefone do cliente 43 (mesmo e-mail do 11, titular do pedido 10)."""
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=10, email_or_phone="(67) 99456-3456")
        assert result["error"] == "verification_failed"

    def test_pedido_inexistente_e_credencial_errada_sao_identicos(
        self, order_book: OrderBook, catalog: Catalog
    ):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        resultado_inexistente = _call(tools, order_id=999, email_or_phone="qualquer@email.com")
        resultado_errado = _call(tools, order_id=10, email_or_phone="errado@email.com")

        assert resultado_inexistente == resultado_errado
        assert resultado_inexistente["error"] == "verification_failed"

    def test_mensagem_de_falha_nao_revela_existencia(self, order_book: OrderBook, catalog: Catalog):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=10, email_or_phone="errado@email.com")
        assert set(result.keys()) == {"error", "message"}


class TestDadosDoPedido:
    """Total historico, pagamento, itens e observacoes (criterios 18, 21, 23)."""

    def test_pedido_3_total_e_3450_e_nao_3498(self, order_book: OrderBook, catalog: Catalog):
        customer = order_book.customer(order_book.order(3).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=3, email_or_phone=customer.email)

        assert result["total_brl"] == "R$ 3.450,00"
        assert result["total_cents"] == 345000

    def test_pedido_17_cancelado_traz_motivo_sem_troca(
        self, order_book: OrderBook, catalog: Catalog
    ):
        customer = order_book.customer(order_book.order(17).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=17, email_or_phone=customer.email)

        assert result["status"] == "cancelled"
        assert result["notes"] == "Pedido cancelado pelo cliente antes do processamento"
        assert "return_eligibility" not in result

    def test_rotulos_de_status_em_portugues(self, order_book: OrderBook, catalog: Catalog):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        esperado = {
            "delivered": "entregue",
            "shipped": "enviado",
            "confirmed": "confirmado",
            "pending": "aguardando pagamento",
            "cancelled": "cancelado",
        }
        encontrados: dict[str, str] = {}
        for order_id in range(1, 21):
            order = order_book.order(order_id)
            customer = order_book.customer(order.customer_id)
            result = _call(tools, order_id=order_id, email_or_phone=customer.email)
            encontrados[result["status"]] = result["status_label"]

        assert encontrados == esperado


class TestElegibilidadeDeTrocaEDevolucao:
    """Quatro modalidades, cada uma com sua propria data de referencia (criterios 19 e 20)."""

    def test_pedido_8_shipped_tracking_e_so_defeito_aberto(
        self, order_book: OrderBook, catalog: Catalog
    ):
        customer = order_book.customer(order_book.order(8).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=8, email_or_phone=customer.email)

        assert result["tracking_code"] == "BRJL5544332BR"

        eligibility = result["return_eligibility"]
        assert eligibility["withdrawal"]["is_open"] is False
        assert eligibility["preference"]["is_open"] is False
        assert eligibility["legal_warranty"]["is_open"] is False
        assert eligibility["defect"]["is_open"] is True

    def test_pedido_7_arrependimento_aberto_com_quatro_dias(
        self, order_book: OrderBook, catalog: Catalog
    ):
        customer = order_book.customer(order_book.order(7).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=7, email_or_phone=customer.email)

        withdrawal = result["return_eligibility"]["withdrawal"]
        assert withdrawal["is_open"] is True
        assert withdrawal["deadline"] == "2026-02-24"
        assert "4" in withdrawal["message"]

    def test_pedido_7_arrependimento_vencido_depois(self, order_book: OrderBook, catalog: Catalog):
        customer = order_book.customer(order_book.order(7).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-25"))
        result = _call(tools, order_id=7, email_or_phone=customer.email)

        withdrawal = result["return_eligibility"]["withdrawal"]
        assert withdrawal["is_open"] is False
        assert "vencido" in withdrawal["message"]


class TestTextoComAcentoParaOCliente:
    """Mensagens que o LLM le (erro, rotulo, frase de prazo, descricao) vem acentuadas."""

    def test_verification_failed_tem_acento(self, order_book: OrderBook, catalog: Catalog):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=999, email_or_phone="qualquer@email.com")

        assert "Não foi possível" in result["message"]
        assert "número do pedido" in result["message"]

    def test_rotulo_troca_por_preferencia_tem_acento(self, order_book: OrderBook, catalog: Catalog):
        customer = order_book.customer(order_book.order(7).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=7, email_or_phone=customer.email)

        assert result["return_eligibility"]["preference"]["label"] == "troca por preferência"

    def test_frase_de_prazo_vencido_tem_acento(self, order_book: OrderBook, catalog: Catalog):
        customer = order_book.customer(order_book.order(7).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-25"))
        result = _call(tools, order_id=7, email_or_phone=customer.email)

        assert "há" in result["return_eligibility"]["withdrawal"]["message"]

    def test_frase_de_prazo_nao_iniciado_tem_acento(self, order_book: OrderBook, catalog: Catalog):
        customer = order_book.customer(order_book.order(8).customer_id)
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=8, email_or_phone=customer.email)

        message = result["return_eligibility"]["withdrawal"]["message"]
        assert "começa" in message
        assert "você" in message

    def test_descricao_da_ferramenta_e_dos_parametros_tem_acento(
        self, order_book: OrderBook, catalog: Catalog
    ):
        specs = build_order_tools(order_book, catalog, _clock("2026-02-20"))
        spec = specs[0]

        assert "número" in spec.description
        assert "Número" in spec.parameters["properties"]["order_id"]["description"]


class TestPrivacidade:
    """Nenhum dado pessoal do cliente aparece no retorno (criterio 22, RNF-02)."""

    def test_pedido_10_nao_revela_dados_do_cliente(self, order_book: OrderBook, catalog: Catalog):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = _call(tools, order_id=10, email_or_phone="bruno.martins@jmail.com")

        serialized = json.dumps(result, ensure_ascii=False)
        for proibido in ("Bruno", "bruno.martins@jmail.com", "98543", "Três Lagoas"):
            assert proibido not in serialized


class TestSerializacaoJson:
    """Nenhum retorno carrega `Decimal` ou `date` cru (criterio 13, aplicado a pedidos)."""

    def test_retornos_sao_json_serializaveis(self, order_book: OrderBook, catalog: Catalog):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        resultados = [
            _call(tools, order_id=10, email_or_phone="bruno.martins@jmail.com"),
            _call(tools, order_id=17, email_or_phone="errado@email.com"),
            _call(
                tools,
                order_id=7,
                email_or_phone=order_book.customer(order_book.order(7).customer_id).email,
            ),
        ]
        for resultado in resultados:
            json.dumps(resultado)
            for leaf in _collect_leaves(resultado):
                assert not hasattr(leaf, "quantize"), "Decimal cru encontrado no retorno"
                assert type(leaf).__name__ != "date", "date cru encontrado no retorno"


class TestContratoOpenaiECallTool:
    """`get_order_status` passa por `openai_tools`; argumento inexistente falha (criterio 14)."""

    def test_openai_tools_gera_schema_valido(self, order_book: OrderBook, catalog: Catalog):
        specs = build_order_tools(order_book, catalog, _clock("2026-02-20"))
        schemas = openai_tools(specs)
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "get_order_status"
        assert schema["function"]["parameters"]["type"] == "object"
        json.dumps(schema)

    def test_call_tool_com_argumento_inexistente(self, order_book: OrderBook, catalog: Catalog):
        tools = _tools_by_name(order_book, catalog, _clock("2026-02-20"))
        result = call_tool(tools, "get_order_status", {"nao_existe": "valor"})
        assert result["error"] == "invalid_arguments"
