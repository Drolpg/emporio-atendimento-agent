"""Testes das ferramentas de catalogo: busca, detalhe de produto e categorias.

Usa os CSVs reais de `data/raw/` (sem rede, sem chave de API).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from emporio.config import project_root
from emporio.data.catalog import Catalog
from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools
from emporio.tools.catalog_tools import build_catalog_tools

RAW_DIR = project_root() / "data" / "raw"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(RAW_DIR)


@pytest.fixture(scope="module")
def tool_specs(catalog: Catalog) -> tuple[ToolSpec, ...]:
    return build_catalog_tools(catalog)


@pytest.fixture(scope="module")
def tools_by_name(tool_specs: tuple[ToolSpec, ...]) -> Mapping[str, ToolSpec]:
    return {spec.name: spec for spec in tool_specs}


def _call(tools_by_name: Mapping[str, ToolSpec], tool_name: str, **kwargs: object) -> JsonDict:
    return call_tool(tools_by_name, tool_name, kwargs)


def _assert_json_serializable(value: object) -> None:
    """Falha se `value` tiver algum tipo que `json.dumps` padrao nao serializa."""
    json.dumps(value)


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


class TestBuildCatalogTools:
    """A fabrica devolve as tres ferramentas esperadas."""

    def test_devolve_tres_ferramentas(self, tool_specs: tuple[ToolSpec, ...]):
        names = {spec.name for spec in tool_specs}
        assert names == {"search_products", "get_product_details", "list_categories"}


class TestSearchProducts:
    """Busca por categoria e faixa de preco final (criterios 1 a 5)."""

    def test_violoes_ate_mil_devolve_doze_sem_96_e_113(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(
            tools_by_name, "search_products", category="violões", max_price=1000, limit=20
        )

        assert result["total_found"] == 12
        ids = {item["product_id"] for item in result["products"]}
        assert 96 not in ids
        assert 113 not in ids

    def test_categoria_sem_acento_funciona_igual(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(
            tools_by_name, "search_products", category="violoes", max_price=1000, limit=20
        )
        assert result["total_found"] == 12

    def test_categoria_inexistente_devolve_unknown_category(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, "search_products", category="saxofones")
        assert result["error"] == "unknown_category"
        assert "message" in result

    def test_filtro_usa_preco_final_produto_121(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(
            tools_by_name, "search_products", category="ukuleles", max_price=500, limit=50
        )
        ids = {item["product_id"] for item in result["products"]}
        assert 121 in ids
        item_121 = next(item for item in result["products"] if item["product_id"] == 121)
        assert item_121["final_price_brl"] == "R$ 439,20"
        assert item_121["discount_percent"] == 20

    def test_filtro_usa_preco_final_produto_90(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(
            tools_by_name, "search_products", category="violões", max_price=2000, limit=50
        )
        ids = {item["product_id"] for item in result["products"]}
        assert 90 in ids
        item_90 = next(item for item in result["products"] if item["product_id"] == 90)
        assert item_90["final_price_brl"] == "R$ 1.967,18"
        assert item_90["discount_percent"] == 18

    def test_categoria_existente_sem_item_comprável_devolve_vazio(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(
            tools_by_name,
            "search_products",
            category="Instrumentos de Sopro (Madeiras)",
        )
        assert result["products"] == []
        assert result["category_empty"] is True
        assert result["category"] == "Instrumentos de Sopro (Madeiras)"


class TestGetProductDetails:
    """Detalhe de produto, condicoes de pagamento e alternativas (criterios 6 a 11)."""

    def test_produto_95_promocao_inativa_sem_campo_e_com_pix(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, "get_product_details", product_id=95)
        payment = result["payment"]

        assert "promotion" not in payment
        assert payment["pix_price_brl"] == "R$ 2.089,05"
        assert payment["max_installments"] == 12

    def test_produto_94_promocao_ativa_sem_pix(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", product_id=94)
        payment = result["payment"]

        assert payment["promotion"]["discount_percent"] == 8
        assert payment["final_price_brl"] == "R$ 5.519,08"
        assert "pix_price_brl" not in payment

    def test_produto_96_esgotado_com_alternativas(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", product_id=96)

        assert result["availability"] == "esgotado"
        assert len(result["alternatives"]) <= 3
        assert len(result["alternatives"]) > 0
        alt_ids = {item["product_id"] for item in result["alternatives"]}
        assert 96 not in alt_ids

    def test_produto_136_descontinuado_mesmo_com_estoque(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, "get_product_details", product_id=136)

        assert result["availability"] == "descontinuado"
        assert len(result["alternatives"]) > 0

    def test_produto_130_em_breve_mesmo_com_estoque(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", product_id=130)

        assert result["availability"] == "em breve"
        assert len(result["alternatives"]) > 0

    def test_busca_por_nome_exato_acha_95(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", name="takamine gd20")
        assert result["product_id"] == 95

    def test_busca_por_nome_ambiguo_devolve_candidatos(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, "get_product_details", name="takamine")
        assert result["error"] == "multiple_matches"
        assert len(result["candidates"]) > 1
        assert all({"product_id", "name"} == set(c.keys()) for c in result["candidates"])

    def test_busca_por_nome_inexistente(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", name="xilofone")
        assert result["error"] == "product_not_found"

    def test_sem_argumentos_devolve_invalid_arguments(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, "get_product_details")
        assert result["error"] == "invalid_arguments"


class TestListCategories:
    """`list_categories` traz as 9 categorias, com contagem 0 nas sem item (criterio 12)."""

    def test_traz_as_nove_categorias(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "list_categories")
        assert len(result["categories"]) == 9

    @pytest.mark.parametrize("category_id", [6, 7, 8])
    def test_categorias_sem_item_tem_contagem_zero(
        self, tools_by_name: Mapping[str, ToolSpec], category_id: int
    ):
        result = _call(tools_by_name, "list_categories")
        category = next(c for c in result["categories"] if c["category_id"] == category_id)
        assert category["purchasable_count"] == 0


class TestSerializacaoJson:
    """Nenhum retorno de ferramenta carrega `Decimal` ou `date` cru (criterio 13)."""

    def test_retornos_sao_json_serializaveis(self, tools_by_name: Mapping[str, ToolSpec]):
        results = [
            _call(tools_by_name, "search_products"),
            _call(
                tools_by_name, "search_products", category="violões", max_price=1000, limit=20
            ),
            _call(tools_by_name, "get_product_details", product_id=95),
            _call(tools_by_name, "get_product_details", product_id=94),
            _call(tools_by_name, "get_product_details", product_id=96),
            _call(tools_by_name, "get_product_details", product_id=136),
            _call(tools_by_name, "get_product_details", product_id=130),
            _call(tools_by_name, "list_categories"),
        ]
        for result in results:
            _assert_json_serializable(result)
            for leaf in _collect_leaves(result):
                assert not hasattr(leaf, "quantize"), "Decimal cru encontrado no retorno"
                assert type(leaf).__name__ != "date", "date cru encontrado no retorno"


class TestContratoOpenaiECallTool:
    """Toda ToolSpec passa por `openai_tools`; argumento inexistente falha (criterio 14)."""

    def test_openai_tools_gera_schema_valido(self, tool_specs: tuple[ToolSpec, ...]):
        schemas = openai_tools(tool_specs)
        assert len(schemas) == len(tool_specs)
        for schema in schemas:
            assert schema["type"] == "function"
            assert isinstance(schema["function"]["name"], str)
            assert isinstance(schema["function"]["description"], str)
            assert schema["function"]["parameters"]["type"] == "object"
            _assert_json_serializable(schema)

    def test_call_tool_com_argumento_inexistente(self, tools_by_name: Mapping[str, ToolSpec]):
        result = call_tool(tools_by_name, "search_products", {"nao_existe": "valor"})
        assert result["error"] == "invalid_arguments"
