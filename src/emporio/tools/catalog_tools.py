"""Ferramentas de catalogo: busca, detalhe de produto e categorias.

O LLM nunca calcula preco: `promotional_price` e `pricing.quote` (ambos em
`emporio.domain.pricing`) sao a unica fonte do preco final, do PIX e do
parcelamento. Aqui so formatamos o que o dominio devolveu para o formato que
o modelo recebe (RF-02, RF-03, RF-04, RF-09, RNF-01, RNF-02).
"""

from __future__ import annotations

from decimal import Decimal

from emporio.data.catalog import Catalog
from emporio.data.models import Availability, Product
from emporio.domain.pricing import PriceQuote, promotional_price, quote
from emporio.tools.base import JsonDict, ToolSpec, tool_error
from emporio.tools.formatting import format_brl, to_cents

__all__ = ["build_catalog_tools"]


_AVAILABILITY_LABELS: dict[Availability, str] = {
    Availability.AVAILABLE: "disponivel",
    Availability.OUT_OF_STOCK: "esgotado",
    Availability.DISCONTINUED: "descontinuado",
    Availability.COMING_SOON: "em breve",
}

# Cada frase repete so o que o manual 7.3 sustenta (RNF-01): "discontinued" e
# fora do catalogo da loja, nao diz nada sobre o fabricante continuar ou nao
# produzindo; "out_of_stock" nao tem informacao de reposicao em nenhuma
# fonte; "coming_soon" nao tem prazo definido em nenhuma fonte.
_SITUATION_MESSAGES: dict[Availability, str] = {
    Availability.OUT_OF_STOCK: (
        "Produto temporariamente indisponível no momento; veja alternativas semelhantes abaixo."
    ),
    Availability.DISCONTINUED: (
        "Produto não faz mais parte do catálogo da loja; veja modelos equivalentes "
        "ou sucessores abaixo."
    ),
    Availability.COMING_SOON: "Produto ainda não está disponível para venda.",
}


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
        "list_price_brl": format_brl(product.price_brl),
        "list_price_cents": to_cents(product.price_brl),
        "final_price_brl": format_brl(final_price),
        "final_price_cents": to_cents(final_price),
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
        "final_price_brl": format_brl(final_price),
        "final_price_cents": to_cents(final_price),
        "availability": _availability_label(product),
    }


#  Valor que nao se aplica e dito explicitamente, com o motivo, nunca omitido:
#  campo ausente parece lacuna a preencher, e o modelo tende a preencher com a
#  regra generica da politica (ex.: os 5% do PIX) em vez de reconhecer que, para
#  este produto, essa regra nao vale (RNF-01, manual 6.2 e 3.1).
_PIX_DISCOUNT_MESSAGE = (
    "O desconto do PIX não se aplica a este produto: ele tem promoção ativa, e "
    "promoção e desconto do PIX não são cumulativos (manual de pagamentos, 6.2)."
)
_NO_INSTALLMENTS_MESSAGE = (
    "Esse valor só permite pagamento à vista; não há parcelamento disponível para ele."
)


def _payment_block(price_quote: PriceQuote) -> JsonDict:
    """Bloco de condicoes de pagamento, a partir de uma `PriceQuote` do dominio."""
    block: JsonDict = {
        "list_price_brl": format_brl(price_quote.list_price),
        "list_price_cents": to_cents(price_quote.list_price),
        "final_price_brl": format_brl(price_quote.final_price),
        "final_price_cents": to_cents(price_quote.final_price),
        "max_installments": price_quote.max_installments,
        "allows_combined_payment": price_quote.allows_combined_payment,
    }
    if price_quote.discount_percent is not None:
        block["promotion"] = {
            "discount_percent": price_quote.discount_percent,
            "original_price_brl": format_brl(price_quote.list_price),
            "original_price_cents": to_cents(price_quote.list_price),
            "final_price_brl": format_brl(price_quote.final_price),
            "final_price_cents": to_cents(price_quote.final_price),
        }

    if price_quote.pix_price is not None:
        block["pix_price_brl"] = format_brl(price_quote.pix_price)
        block["pix_price_cents"] = to_cents(price_quote.pix_price)
        block["pix_discount_applies"] = True
    else:
        block["pix_discount_applies"] = False
        block["pix_discount_message"] = _PIX_DISCOUNT_MESSAGE

    if price_quote.installment_value is not None:
        block["installment_value_brl"] = format_brl(price_quote.installment_value)
        block["installment_value_cents"] = to_cents(price_quote.installment_value)
        block["allows_installments"] = True
    else:
        block["allows_installments"] = False
        block["installment_value_message"] = _NO_INSTALLMENTS_MESSAGE

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
                    f"Categoria '{category}' não encontrada. Categorias disponíveis: {names}.",
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
            "Busca produtos no catálogo por texto, categoria e faixa de preço final "
            "(já com promoção aplicada). Por padrão mostra só itens compráveis."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto livre para buscar no nome ou na descrição do produto",
                },
                "category": {
                    "type": "string",
                    "description": "Nome da categoria, ex.: 'violões', 'guitarras'",
                },
                "min_price": {
                    "type": "number",
                    "description": "Preço final mínimo em reais",
                },
                "max_price": {
                    "type": "number",
                    "description": "Preço final máximo em reais",
                },
                "only_available": {
                    "type": "boolean",
                    "description": "Se true (padrão), mostra só produtos compráveis agora",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de produtos no resultado (padrão 8)",
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
                        "Mais de um produto corresponde à busca; pergunte ao cliente "
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
            "Detalha um produto do catálogo: specs, disponibilidade, condições de "
            "pagamento e alternativas quando indisponível. Use product_id ou name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer", "description": "Id do produto"},
                "name": {
                    "type": "string",
                    "description": "Nome ou parte do nome do produto, quando não há id",
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
        description="Lista todas as categorias do catálogo, com a contagem de itens compráveis.",
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
