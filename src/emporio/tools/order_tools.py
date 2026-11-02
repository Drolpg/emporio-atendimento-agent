"""Ferramenta de status de pedido, com verificacao de titularidade (RNF-02).

`get_order_status` e o unico ponto de privacidade do sistema: pedido
inexistente e verificacao que nao casa produzem a mesma resposta, e nenhum
dado pessoal do cliente (nome, e-mail, telefone, cidade) entra no retorno.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from emporio.config import Clock
from emporio.data.catalog import Catalog
from emporio.data.models import Order
from emporio.data.orders import OrderBook
from emporio.domain.returns import ReturnKind, ReturnWindow, return_windows
from emporio.tools.base import JsonDict, ToolSpec, tool_error

__all__ = ["build_order_tools"]


_STATUS_LABELS: dict[str, str] = {
    "delivered": "entregue",
    "shipped": "enviado",
    "confirmed": "confirmado",
    "pending": "aguardando pagamento",
    "cancelled": "cancelado",
}

_RETURN_KIND_LABELS: dict[ReturnKind, str] = {
    ReturnKind.WITHDRAWAL: "arrependimento",
    ReturnKind.PREFERENCE: "troca por preferencia",
    ReturnKind.DEFECT: "troca por defeito",
    ReturnKind.LEGAL_WARRANTY: "garantia legal",
}

_VERIFICATION_FAILED_MESSAGE = (
    "Nao foi possivel verificar o pedido. Informe o numero do pedido e o "
    "e-mail ou telefone cadastrado no pedido para eu poder consultar."
)


def _format_brl(value: Decimal) -> str:
    """Formata um valor em reais no padrao brasileiro (ex.: "R$ 3.450,00")."""
    quant = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if quant < 0 else ""
    quant = abs(quant)
    integer_part, decimal_part = f"{quant:.2f}".split(".")
    groups = [integer_part[max(i - 3, 0) : i] for i in range(len(integer_part), 0, -3)]
    grouped_integer = ".".join(reversed(groups))
    return f"{sign}R$ {grouped_integer},{decimal_part}"


def _cents(value: Decimal) -> int:
    """Converte um valor em reais para centavos (inteiro), para comparacao numerica."""
    quant = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((quant * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _window_message(window: ReturnWindow) -> str:
    """Frase pronta em portugues para o estado da janela de troca/devolucao."""
    if window.not_started:
        return "o prazo comeca a contar quando voce receber o pedido"
    if window.is_open:
        if window.days_remaining == 0:
            return "aberto: vence hoje"
        return f"aberto: restam {window.days_remaining} dia(s)"
    return f"vencido ha {window.days_expired} dia(s)"


def _window_block(window: ReturnWindow) -> JsonDict:
    """Bloco de uma modalidade de troca/devolucao/garantia."""
    return {
        "label": _RETURN_KIND_LABELS[window.kind],
        "is_open": window.is_open,
        "deadline": window.deadline.isoformat() if window.deadline is not None else None,
        "message": _window_message(window),
    }


def _items_block(order: Order) -> list[JsonDict]:
    """Itens do pedido: so nome e quantidade, sem nenhum dado do cliente."""
    return [{"name": item.product_name, "quantity": item.quantity} for item in order.items]


def build_order_tools(
    order_book: OrderBook, catalog: Catalog, clock: Clock
) -> tuple[ToolSpec, ...]:
    """Monta a ferramenta de status de pedido."""

    def handler(order_id: int, email_or_phone: str) -> JsonDict:
        order = order_book.verify(int(order_id), email_or_phone)
        if order is None:
            return tool_error("verification_failed", _VERIFICATION_FAILED_MESSAGE)

        result: JsonDict = {
            "order_id": order.order_id,
            "order_date": order.order_date.isoformat(),
            "status": order.status,
            "status_label": _STATUS_LABELS[order.status],
            "total_brl": _format_brl(order.total_brl),
            "total_cents": _cents(order.total_brl),
            "payment_form": order.payment_form,
            "installments": order.installments,
            "items": _items_block(order),
        }

        if order.estimated_delivery is not None:
            result["estimated_delivery"] = order.estimated_delivery.isoformat()
        if order.tracking_code is not None:
            result["tracking_code"] = order.tracking_code
        if order.notes is not None:
            result["notes"] = order.notes

        if order.status != "cancelled":
            windows = return_windows(
                order_date=order.order_date,
                received_date=order.received_date,
                today=clock.today(),
            )
            result["return_eligibility"] = {
                window.kind.value: _window_block(window) for window in windows
            }

        return result

    spec = ToolSpec(
        name="get_order_status",
        description=(
            "Consulta o status de um pedido. Exige o numero do pedido e o e-mail "
            "ou telefone cadastrado no titular do pedido."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Numero do pedido"},
                "email_or_phone": {
                    "type": "string",
                    "description": "E-mail ou telefone cadastrado no titular do pedido",
                },
            },
            "required": ["order_id", "email_or_phone"],
        },
        handler=handler,
    )
    return (spec,)
