"""Modelos tipados do catalogo e dos pedidos, carregados dos CSVs em `data/raw`.

Dinheiro sempre em `Decimal` (nunca `float`): os valores sao lidos a partir do
texto da celula do CSV, nunca convertidos via `float`, para nao introduzir
erro de arredondamento no preco mostrado ao cliente.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

__all__ = [
    "Availability",
    "Category",
    "Promotion",
    "Product",
    "Customer",
    "OrderItem",
    "Order",
]


class Availability(StrEnum):
    """Disponibilidade de um produto para compra.

    O `status` do produto tem precedencia sobre o estoque (P-15): um produto
    `discontinued` ou `coming_soon` nunca e `AVAILABLE`, mesmo com estoque.
    """

    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


@dataclass(frozen=True)
class Category:
    """Categoria do catalogo (ex.: Violoes, Guitarras)."""

    category_id: int
    name: str
    description: str


@dataclass(frozen=True)
class Promotion:
    """Promocao ativa de um produto."""

    promotion_id: int
    product_id: int
    discount_percent: int
    description: str


@dataclass(frozen=True)
class Product:
    """Produto do catalogo, com a promocao ativa (se houver)."""

    product_id: int
    name: str
    category_id: int
    category_name: str
    price_brl: Decimal
    description: str
    stock_quantity: int
    status: str  # cru do CSV: active | discontinued | coming_soon
    specs: Mapping[str, str]
    created_at: date
    promotion: Promotion | None  # somente a promocao ativa, se houver

    @property
    def availability(self) -> Availability:
        """Classifica a disponibilidade combinando `status` e estoque (P-15)."""
        if self.status == "discontinued":
            return Availability.DISCONTINUED
        if self.status == "coming_soon":
            return Availability.COMING_SOON
        # status == "active": so aqui o estoque decide
        return Availability.OUT_OF_STOCK if self.stock_quantity <= 0 else Availability.AVAILABLE

    @property
    def is_purchasable(self) -> bool:
        """Verdadeiro somente quando o produto esta disponivel para compra."""
        return self.availability == Availability.AVAILABLE


@dataclass(frozen=True)
class Customer:
    """Cliente do cadastro, usado para verificar o titular de um pedido."""

    customer_id: int
    name: str
    phone: str  # como esta no CSV
    email: str  # minusculas
    city: str

    @property
    def phone_digits(self) -> str:
        """Devolve so os digitos do telefone cadastrado."""
        return "".join(char for char in self.phone if char.isdigit())


@dataclass(frozen=True)
class OrderItem:
    """Item de um pedido."""

    product_id: int
    product_name: str
    quantity: int


@dataclass(frozen=True)
class Order:
    """Pedido, com o total historico e os itens comprados."""

    order_id: int
    customer_id: int
    order_date: date
    status: str  # delivered | shipped | confirmed | pending | cancelled
    total_brl: Decimal
    payment_form: str  # pix | debit | credit | boleto
    installments: int  # 1 para pix, debit e boleto; 3, 6 ou 12 para credit
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: tuple[OrderItem, ...]

    @property
    def received_date(self) -> date | None:
        """Data de recebimento (P-04): `estimated_delivery` se entregue, senao None."""
        if self.status == "delivered":
            return self.estimated_delivery
        return None
