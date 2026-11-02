"""Pedidos e clientes, com a verificacao de titularidade exigida pela LGPD.

`OrderBook.verify` e o ponto de privacidade do sistema (RNF-02, P-11): compara
sempre contra o cliente daquele pedido, nunca busca cliente por e-mail ou
telefone na base (o e-mail `bruno.martins@jmail.com` pertence aos clientes 11
e 43; so o do cliente 11 abre o pedido 10, que e dele).
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from emporio.data.models import Customer, Order, OrderItem

__all__ = ["OrderBook"]

# Menos de 8 digitos informados nunca casa, para um palpite curto nao abrir o pedido.
_MIN_PHONE_DIGITS = 8


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Le um CSV como lista de dicionarios, preservando o texto das celulas."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _digits_only(text: str) -> str:
    """Devolve so os digitos de `text`."""
    return "".join(char for char in text if char.isdigit())


def _optional_text(value: str) -> str | None:
    """Devolve `None` para celula vazia, senao o texto como esta."""
    stripped = value.strip()
    return stripped or None


def _optional_date(value: str) -> date | None:
    """Devolve `None` para celula vazia, senao a data convertida."""
    stripped = value.strip()
    return date.fromisoformat(stripped) if stripped else None


def _parse_payment(payment_method: str) -> tuple[str, int]:
    """Separa a forma de pagamento do numero de parcelas.

    `credit_6x` -> (`credit`, 6); formas sem parcela (`pix`, `debit`,
    `boleto`) tem uma parcela.
    """
    if "_" not in payment_method:
        return payment_method, 1
    form, suffix = payment_method.split("_", 1)
    return form, int(suffix.rstrip("x"))


def _load_product_names(path: Path) -> dict[int, str]:
    """Mapeia `product_id` -> nome, so para rotular os itens do pedido."""
    return {int(row["product_id"]): row["name"] for row in _read_csv(path)}


def _load_customers(path: Path) -> dict[int, Customer]:
    customers: dict[int, Customer] = {}
    for row in _read_csv(path):
        customer_id = int(row["customer_id"])
        customers[customer_id] = Customer(
            customer_id=customer_id,
            name=row["name"],
            phone=row["phone"],
            email=row["email"].strip().lower(),
            city=row["city"],
        )
    return customers


def _load_order_items(path: Path, product_names: Mapping[int, str]) -> dict[int, list[OrderItem]]:
    items_by_order: dict[int, list[OrderItem]] = {}
    for row in _read_csv(path):
        order_id = int(row["order_id"])
        product_id = int(row["product_id"])
        item = OrderItem(
            product_id=product_id,
            product_name=product_names.get(product_id, ""),
            quantity=int(row["quantity"]),
        )
        items_by_order.setdefault(order_id, []).append(item)
    return items_by_order


def _load_orders(path: Path, items_by_order: Mapping[int, list[OrderItem]]) -> tuple[Order, ...]:
    orders = []
    for row in _read_csv(path):
        order_id = int(row["order_id"])
        payment_form, installments = _parse_payment(row["payment_method"])
        orders.append(
            Order(
                order_id=order_id,
                customer_id=int(row["customer_id"]),
                order_date=date.fromisoformat(row["order_date"]),
                status=row["status"],
                total_brl=Decimal(row["total_brl"]),
                payment_form=payment_form,
                installments=installments,
                tracking_code=_optional_text(row["tracking_code"]),
                estimated_delivery=_optional_date(row["estimated_delivery"]),
                notes=_optional_text(row["notes"]),
                items=tuple(items_by_order.get(order_id, [])),
            )
        )
    return tuple(sorted(orders, key=lambda order: order.order_id))


def _matches_email(stored_email: str, candidate: str) -> bool:
    """Compara e-mails em minusculas, sem espaco nas pontas (casamento exato)."""
    return stored_email == candidate.strip().lower()


def _matches_phone(stored_digits: str, candidate: str) -> bool:
    """Compara so os digitos, aceitando DDD e codigo de pais a mais de um lado.

    O lado com mais digitos precisa terminar com o lado mais curto: cobre o
    cliente informando com DDD, sem DDD, ou com o `55` de pais na frente do
    numero cadastrado.
    """
    candidate_digits = _digits_only(candidate)
    if len(candidate_digits) < _MIN_PHONE_DIGITS:
        return False
    if len(stored_digits) >= len(candidate_digits):
        return stored_digits.endswith(candidate_digits)
    return candidate_digits.endswith(stored_digits)


@dataclass(frozen=True)
class OrderBook:
    """Pedidos e clientes carregados, com verificacao de titularidade."""

    _orders_by_id: Mapping[int, Order]
    _customers_by_id: Mapping[int, Customer]

    @classmethod
    def load(cls, raw_dir: Path) -> OrderBook:
        """Carrega pedidos, itens e clientes a partir dos CSVs em `raw_dir`."""
        product_names = _load_product_names(raw_dir / "products.csv")
        customers = _load_customers(raw_dir / "customers.csv")
        items_by_order = _load_order_items(raw_dir / "order_items.csv", product_names)
        orders = _load_orders(raw_dir / "orders.csv", items_by_order)
        return cls(
            _orders_by_id={order.order_id: order for order in orders},
            _customers_by_id=customers,
        )

    def order(self, order_id: int) -> Order | None:
        """Devolve o pedido pelo id, sem nenhuma verificacao de titularidade."""
        return self._orders_by_id.get(order_id)

    def customer(self, customer_id: int) -> Customer | None:
        """Devolve o cliente pelo id, ou None se nao existir."""
        return self._customers_by_id.get(customer_id)

    def verify(self, order_id: int, email_or_phone: str) -> Order | None:
        """Devolve o pedido somente se `email_or_phone` casar com o titular.

        Pedido inexistente e verificacao que nao casa devolvem `None`
        igualmente: a camada de cima nao pode distinguir os dois casos, senao
        o agente revela que um pedido existe (RNF-02).
        """
        order = self._orders_by_id.get(order_id)
        if order is None:
            return None
        customer = self._customers_by_id.get(order.customer_id)
        if customer is None:
            return None
        if _matches_email(customer.email, email_or_phone) or _matches_phone(
            customer.phone_digits, email_or_phone
        ):
            return order
        return None
