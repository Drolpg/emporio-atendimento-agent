"""Ferramenta de status de pedido, com verificacao de titularidade (RNF-02).

`get_order_status` e o unico ponto de privacidade do sistema: pedido
inexistente e verificacao que nao casa produzem a mesma resposta, e nenhum
dado pessoal do cliente (nome, e-mail, telefone, cidade) entra no retorno.
"""

from __future__ import annotations

from emporio.config import Clock
from emporio.data.catalog import Catalog
from emporio.data.models import Order
from emporio.data.orders import OrderBook
from emporio.domain.returns import ReturnKind, ReturnWindow, return_windows
from emporio.tools.base import JsonDict, ToolSpec, tool_error
from emporio.tools.formatting import format_brl, to_cents

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
    ReturnKind.PREFERENCE: "troca por preferência",
    ReturnKind.DEFECT: "troca por defeito",
    ReturnKind.LEGAL_WARRANTY: "garantia legal",
}

_VERIFICATION_FAILED_MESSAGE = (
    "Não foi possível verificar o pedido. Informe o número do pedido e o "
    "e-mail ou telefone cadastrado no pedido para eu poder consultar."
)

# Valor que nao se aplica e dito explicitamente, com o motivo, nunca omitido:
# campo ausente parece lacuna a preencher, e o modelo tende a inventar um
# codigo de rastreio ou um prazo em vez de reconhecer que, para este pedido,
# eles ainda nao existem (RNF-01).
_NO_TRACKING_MESSAGE = "Ainda não há código de rastreio porque o pedido não foi despachado."
_NO_ESTIMATED_DELIVERY_MESSAGE = (
    "Ainda não há previsão de entrega porque o pedido não foi despachado."
)


def _window_message(window: ReturnWindow) -> str:
    """Frase pronta em portugues para o estado da janela de troca/devolucao."""
    if window.not_started:
        return "o prazo começa a contar quando você receber o pedido"
    if window.is_open:
        if window.days_remaining == 0:
            return "aberto: vence hoje"
        return f"aberto: restam {window.days_remaining} dia(s)"
    return f"vencido há {window.days_expired} dia(s)"


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
            "total_brl": format_brl(order.total_brl),
            "total_cents": to_cents(order.total_brl),
            "payment_form": order.payment_form,
            "installments": order.installments,
            "items": _items_block(order),
        }

        if order.estimated_delivery is not None:
            result["estimated_delivery"] = order.estimated_delivery.isoformat()
        else:
            result["estimated_delivery_message"] = _NO_ESTIMATED_DELIVERY_MESSAGE

        if order.tracking_code is not None:
            result["tracking_code"] = order.tracking_code
        else:
            result["tracking_code_message"] = _NO_TRACKING_MESSAGE

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
            "Consulta o status de um pedido. Exige o número do pedido e o e-mail "
            "ou telefone cadastrado no titular do pedido."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Número do pedido"},
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
