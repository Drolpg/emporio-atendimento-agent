"""Ferramentas de catalogo: busca, detalhe de produto e categorias.

O LLM nunca calcula preco: `promotional_price` e `pricing.quote` (ambos em
`emporio.domain.pricing`) sao a unica fonte do preco final, do PIX e do
parcelamento. Aqui so formatamos o que o dominio devolveu para o formato que
o modelo recebe (RF-02, RF-03, RF-04, RF-09, RNF-01, RNF-02).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from emporio.data.catalog import Catalog
from emporio.data.models import Availability, Product
from emporio.domain.pricing import PriceQuote, promotional_price, quote
from emporio.tools.base import JsonDict, ToolSpec, tool_error

__all__ = ["build_catalog_tools"]


_AVAILABILITY_LABELS: dict[Availability, str] = {
    Availability.AVAILABLE: "disponivel",
    Availability.OUT_OF_STOCK: "esgotado",
    Availability.DISCONTINUED: "descontinuado",
    Availability.COMING_SOON: "em breve",
}

_SITUATION_MESSAGES: dict[Availability, str] = {
    Availability.OUT_OF_STOCK: "Produto esgotado no momento, sem previsao de reposicao.",
    Availability.DISCONTINUED: "Produto fora de linha, nao e mais fabricado.",
    Availability.COMING_SOON: "Produto ainda nao disponivel para venda, chega em breve.",
}


def _format_brl(value: Decimal) -> str:
    """Formata um valor em reais no padrao brasileiro (ex.: "R$ 2.199,00")."""
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


def _availability_label(product: Product) -> str:
    """Rotulo em portugues da disponibilidade do produto."""
    return _AVAILABILITY_LABELS[product.availability]


def _final_price(product: Product) -> Decimal:
    """Preco final do produto, com a promocao ativa aplicada (se houver)."""
    discount_percent = product.promotion.discount_percent if product.promotion else None
    return promotional_price(product.price_brl, discount_percent)


def _to_decimal(value: int | float | str | None) -> Decimal | None:
    """Converte um numero recebido do LLM para `Decimal`, sem passar por `float` em dinheiro."""
    if value is None:
        return None
    return Decimal(str(value))


def _product_summary(product: Product) -> JsonDict:
    """Resumo enxuto de um produto para a lista de busca (RNF-08)."""
    final_price = _final_price(product)
    summary: JsonDict = {
        "product_id": product.product_id,
        "name": product.name,
        "category": product.category_name,
        "list_price_brl": _format_brl(product.price_brl),
        "list_price_cents": _cents(product.price_brl),
        "final_price_brl": _format_brl(final_price),
        "final_price_cents": _cents(final_price),
        "availability": _availability_label(product),
    }
    if product.promotion is not None:
        summary["discount_percent"] = product.promotion.discount_percent
    return summary


def _alternative_summary(product: Product) -> JsonDict:
    """Resumo de uma alternativa sugerida para um produto indisponivel."""
    final_price = _final_price(product)
    return {
        "product_id": product.product_id,
        "name": product.name,
        "final_price_brl": _format_brl(final_price),
        "final_price_cents": _cents(final_price),
        "availability": _availability_label(product),
    }


def _payment_block(price_quote: PriceQuote) -> JsonDict:
    """Bloco de condicoes de pagamento, a partir de uma `PriceQuote` do dominio."""
    block: JsonDict = {
        "list_price_brl": _format_brl(price_quote.list_price),
        "list_price_cents": _cents(price_quote.list_price),
        "final_price_brl": _format_brl(price_quote.final_price),
        "final_price_cents": _cents(price_quote.final_price),
        "max_installments": price_quote.max_installments,
        "allows_combined_payment": price_quote.allows_combined_payment,
    }
    if price_quote.discount_percent is not None:
        block["promotion"] = {
            "discount_percent": price_quote.discount_percent,
            "original_price_brl": _format_brl(price_quote.list_price),
            "original_price_cents": _cents(price_quote.list_price),
            "final_price_brl": _format_brl(price_quote.final_price),
            "final_price_cents": _cents(price_quote.final_price),
        }
    if price_quote.pix_price is not None:
        block["pix_price_brl"] = _format_brl(price_quote.pix_price)
        block["pix_price_cents"] = _cents(price_quote.pix_price)
    if price_quote.installment_value is not None:
        block["installment_value_brl"] = _format_brl(price_quote.installment_value)
        block["installment_value_cents"] = _cents(price_quote.installment_value)
    return block


def _product_details(catalog: Catalog, product: Product) -> JsonDict:
    """Monta o detalhe completo de um produto (RF-03, RF-04)."""
    details: JsonDict = {
        "product_id": product.product_id,
        "name": product.name,
        "category": product.category_name,
        "description": product.description,
        "specs": dict(product.specs),
        "availability": _availability_label(product),
    }

    discount_percent = product.promotion.discount_percent if product.promotion else None
    details["payment"] = _payment_block(quote(product.price_brl, discount_percent))

    if product.is_purchasable:
        details["stock_quantity"] = product.stock_quantity
    else:
        details["situation_message"] = _SITUATION_MESSAGES[product.availability]
        alternatives = catalog.alternatives(product)
        details["alternatives"] = [_alternative_summary(item) for item in alternatives]

    return details


def _build_search_products(catalog: Catalog) -> ToolSpec:
    def handler(
        query: str | None = None,
        category: str | None = None,
        min_price: int | float | str | None = None,
        max_price: int | float | str | None = None,
        only_available: bool = True,
        limit: int = 8,
    ) -> JsonDict:
        category_id = None
        category_name = None
        if category is not None:
            found_category = catalog.find_category(category)
            if found_category is None:
                names = ", ".join(cat.name for cat in catalog.categories())
                return tool_error(
                    "unknown_category",
                    f"Categoria '{category}' nao encontrada. Categorias disponiveis: {names}.",
                )
            category_id = found_category.category_id
            category_name = found_category.name

        products = catalog.search(
            query=query,
            category_id=category_id,
            min_price=_to_decimal(min_price),
            max_price=_to_decimal(max_price),
            only_purchasable=only_available,
            limit=limit,
            price_of=_final_price,
        )

        if not products and category_id is not None and catalog.purchasable_count(category_id) == 0:
            return {
                "products": [],
                "total_found": 0,
                "category_empty": True,
                "category": category_name,
            }

        return {
            "products": [_product_summary(product) for product in products],
            "total_found": len(products),
        }

    return ToolSpec(
        name="search_products",
        description=(
            "Busca produtos no catalogo por texto, categoria e faixa de preco final "
            "(ja com promocao aplicada). Por padrao mostra so itens compraveis."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto livre para buscar no nome ou na descricao do produto",
                },
                "category": {
                    "type": "string",
                    "description": "Nome da categoria, ex.: 'violoes', 'guitarras'",
                },
                "min_price": {
                    "type": "number",
                    "description": "Preco final minimo em reais",
                },
                "max_price": {
                    "type": "number",
                    "description": "Preco final maximo em reais",
                },
                "only_available": {
                    "type": "boolean",
                    "description": "Se true (padrao), mostra so produtos compraveis agora",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de produtos no resultado (padrao 8)",
                },
            },
            "required": [],
        },
        handler=handler,
    )


def _build_get_product_details(catalog: Catalog) -> ToolSpec:
    def handler(
        product_id: int | None = None,
        name: str | None = None,
    ) -> JsonDict:
        if product_id is None and name is None:
            return tool_error(
                "invalid_arguments", "Informe product_id ou name para identificar o produto."
            )

        product: Product | None = None
        if product_id is not None:
            product = catalog.product(int(product_id))
            if product is None:
                return tool_error(
                    "product_not_found", f"Nenhum produto encontrado com id {product_id}."
                )
        else:
            assert name is not None
            matches = catalog.find_products_by_name(name)
            if not matches:
                return tool_error("product_not_found", f"Nenhum produto encontrado para '{name}'.")
            if len(matches) > 1:
                return {
                    "error": "multiple_matches",
                    "message": (
                        "Mais de um produto corresponde a busca; pergunte ao cliente "
                        "qual deles ele quer antes de dar detalhes."
                    ),
                    "candidates": [
                        {"product_id": candidate.product_id, "name": candidate.name}
                        for candidate in matches
                    ],
                }
            product = matches[0]

        return _product_details(catalog, product)

    return ToolSpec(
        name="get_product_details",
        description=(
            "Detalha um produto do catalogo: specs, disponibilidade, condicoes de "
            "pagamento e alternativas quando indisponivel. Use product_id ou name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Id do produto"},
                "name": {
                    "type": "string",
                    "description": "Nome ou parte do nome do produto, quando nao ha id",
                },
            },
            "required": [],
        },
        handler=handler,
    )


def _build_list_categories(catalog: Catalog) -> ToolSpec:
    def handler() -> JsonDict:
        categories = [
            {
                "category_id": category.category_id,
                "name": category.name,
                "description": category.description,
                "purchasable_count": catalog.purchasable_count(category.category_id),
            }
            for category in catalog.categories()
        ]
        return {"categories": categories}

    return ToolSpec(
        name="list_categories",
        description="Lista todas as categorias do catalogo, com a contagem de itens compraveis.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=handler,
    )


def build_catalog_tools(catalog: Catalog) -> tuple[ToolSpec, ...]:
    """Monta as ferramentas de catalogo: busca, detalhe e categorias."""
    return (
        _build_search_products(catalog),
        _build_get_product_details(catalog),
        _build_list_categories(catalog),
    )
