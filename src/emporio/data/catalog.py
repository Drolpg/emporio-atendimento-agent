"""Catalogo: carga de `categories.csv`, `products.csv` e `promotions.csv`.

So a promocao `is_active = 1` entra no catalogo. A carga valida que nenhum
produto tem mais de uma promocao ativa (hoje sao 4, nos produtos 90, 94, 121
e 127); uma promocao inativa e descartada e nunca aparece em
`Product.promotion`.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from emporio.data.models import Category, Product, Promotion
from emporio.textnorm import normalize_text

__all__ = ["Catalog"]


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Le um CSV como lista de dicionarios, preservando o texto das celulas."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_categories(path: Path) -> tuple[Category, ...]:
    categories = [
        Category(
            category_id=int(row["category_id"]),
            name=row["name"],
            description=row["description"],
        )
        for row in _read_csv(path)
    ]
    return tuple(sorted(categories, key=lambda category: category.category_id))


def _load_active_promotions(path: Path) -> dict[int, Promotion]:
    """Carrega so as promocoes ativas, validando no maximo uma por produto."""
    by_product: dict[int, Promotion] = {}
    for row in _read_csv(path):
        if row["is_active"].strip() != "1":
            continue
        product_id = int(row["product_id"])
        promotion = Promotion(
            promotion_id=int(row["promotion_id"]),
            product_id=product_id,
            discount_percent=int(row["discount_percent"]),
            description=row["description"],
        )
        existing = by_product.get(product_id)
        if existing is not None:
            raise ValueError(
                f"produto {product_id} tem mais de uma promocao ativa: "
                f"{existing.promotion_id} e {promotion.promotion_id}"
            )
        by_product[product_id] = promotion
    return by_product


def _load_products(
    path: Path,
    categories_by_id: Mapping[int, Category],
    active_promotions: Mapping[int, Promotion],
) -> tuple[Product, ...]:
    products = []
    for row in _read_csv(path):
        product_id = int(row["product_id"])
        category_id = int(row["category_id"])
        category = categories_by_id.get(category_id)
        category_name = category.name if category is not None else ""
        products.append(
            Product(
                product_id=product_id,
                name=row["name"],
                category_id=category_id,
                category_name=category_name,
                price_brl=Decimal(row["price_brl"]),
                description=row["description"],
                stock_quantity=int(row["stock_quantity"]),
                status=row["status"],
                specs=json.loads(row["specs"]),
                created_at=date.fromisoformat(row["created_at"]),
                promotion=active_promotions.get(product_id),
            )
        )
    return tuple(sorted(products, key=lambda product: product.product_id))


@dataclass(frozen=True)
class Catalog:
    """Catalogo carregado, consultavel por categoria, nome e faixa de preco."""

    _categories: tuple[Category, ...]
    _categories_by_id: Mapping[int, Category]
    _products: tuple[Product, ...]
    _products_by_id: Mapping[int, Product]

    @classmethod
    def load(cls, raw_dir: Path) -> Catalog:
        """Carrega o catalogo a partir dos CSVs em `raw_dir`."""
        categories = _load_categories(raw_dir / "categories.csv")
        categories_by_id = {category.category_id: category for category in categories}
        active_promotions = _load_active_promotions(raw_dir / "promotions.csv")
        products = _load_products(raw_dir / "products.csv", categories_by_id, active_promotions)
        products_by_id = {product.product_id: product for product in products}
        return cls(
            _categories=categories,
            _categories_by_id=categories_by_id,
            _products=products,
            _products_by_id=products_by_id,
        )

    def categories(self) -> tuple[Category, ...]:
        """Devolve todas as categorias, ordenadas por id."""
        return self._categories

    def category(self, category_id: int) -> Category | None:
        """Devolve a categoria pelo id, ou None se nao existir."""
        return self._categories_by_id.get(category_id)

    def find_category(self, text: str) -> Category | None:
        """Acha a categoria cujo nome casa com `text` por substring normalizada."""
        query = normalize_text(text)
        if not query:
            return None
        matches = [
            category
            for category in self._categories
            if query in normalize_text(category.name) or normalize_text(category.name) in query
        ]
        if not matches:
            return None
        return min(matches, key=lambda category: category.category_id)

    def products(self) -> tuple[Product, ...]:
        """Devolve todos os produtos, ordenados por id."""
        return self._products

    def product(self, product_id: int) -> Product | None:
        """Devolve o produto pelo id, ou None se nao existir."""
        return self._products_by_id.get(product_id)

    def find_products_by_name(self, text: str) -> tuple[Product, ...]:
        """Acha produtos cujo nome contem `text`, por substring normalizada."""
        query = normalize_text(text)
        if not query:
            return ()
        matches = [product for product in self._products if query in normalize_text(product.name)]
        return tuple(sorted(matches, key=lambda product: product.product_id))

    def purchasable_count(self, category_id: int) -> int:
        """Conta produtos compraveis (`is_purchasable`) na categoria."""
        return sum(
            1
            for product in self._products
            if product.category_id == category_id and product.is_purchasable
        )

    def search(
        self,
        *,
        query: str | None = None,
        category_id: int | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        only_purchasable: bool = True,
        limit: int = 8,
        price_of: Callable[[Product], Decimal] | None = None,
    ) -> tuple[Product, ...]:
        """Busca produtos combinando filtros com E logico.

        `price_of` decide o preco usado para filtrar e ordenar por faixa;
        por padrao usa o preco de tabela (`product.price_brl`). A camada de
        ferramentas injeta o preco final (com promocao), que o modulo de
        dados nao calcula.
        """
        price_fn = price_of if price_of is not None else (lambda product: product.price_brl)
        normalized_query = normalize_text(query) if query else None

        def matches(product: Product) -> bool:
            if only_purchasable and not product.is_purchasable:
                return False
            if category_id is not None and product.category_id != category_id:
                return False
            if normalized_query is not None:
                haystack = f"{normalize_text(product.name)} {normalize_text(product.description)}"
                if normalized_query not in haystack:
                    return False
            price = price_fn(product)
            if min_price is not None and price < min_price:
                return False
            return not (max_price is not None and price > max_price)

        filtered = [product for product in self._products if matches(product)]
        filtered.sort(key=lambda product: (price_fn(product), product.product_id))
        return tuple(filtered[:limit])

    def alternatives(self, product: Product, limit: int = 3) -> tuple[Product, ...]:
        """Sugere ate `limit` produtos compraveis da mesma categoria, por proximidade de preco."""
        candidates = [
            other
            for other in self._products
            if other.category_id == product.category_id
            and other.product_id != product.product_id
            and other.is_purchasable
        ]
        candidates.sort(
            key=lambda other: (abs(other.price_brl - product.price_brl), other.product_id)
        )
        return tuple(candidates[:limit])
