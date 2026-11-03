"""Testes das ferramentas de catalogo: busca, detalhe de produto e categorias.

Usa os CSVs reais de `data/raw/` (sem rede, sem chave de API).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal

import pytest

from emporio.config import project_root
from emporio.data.catalog import Catalog
from emporio.domain.pricing import quote
from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools
from emporio.tools.catalog_tools import _payment_block, build_catalog_tools

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

    def test_violoes_ate_mil_devolve_doze_sem_96_e_113(self, tools_by_name: Mapping[str, ToolSpec]):
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
        assert payment["pix_discount_applies"] is True

    def test_produto_94_promocao_ativa_sem_pix_com_negacao_explicita(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        """Criterio 1: desconto do PIX negado, nao omitido (manual 6.2, nao cumulativo)."""
        result = _call(tools_by_name, "get_product_details", product_id=94)
        payment = result["payment"]

        assert payment["promotion"]["discount_percent"] == 8
        assert payment["promotion"]["original_price_brl"] == "R$ 5.999,00"
        assert payment["final_price_brl"] == "R$ 5.519,08"

        assert "pix_price_brl" not in payment
        assert "pix_price_cents" not in payment
        assert payment["pix_discount_applies"] is False
        message = payment["pix_discount_message"].lower()
        assert "pix" in message
        assert "promo" in message or "cumulativ" in message

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

    def test_busca_por_nome_ambiguo_devolve_candidatos(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", name="takamine")
        assert result["error"] == "multiple_matches"
        assert len(result["candidates"]) > 1
        assert all({"product_id", "name"} == set(c.keys()) for c in result["candidates"])

    def test_busca_por_nome_inexistente(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", name="xilofone")
        assert result["error"] == "product_not_found"

    def test_sem_argumentos_devolve_invalid_arguments(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details")
        assert result["error"] == "invalid_arguments"


class TestNegacaoExplicitaDeParcelamento:
    """Criterio 3: total que so cabe a vista nega o valor da parcela, nao omite."""

    def test_produto_119_cabe_em_tres_parcelas(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", product_id=119)
        payment = result["payment"]

        assert payment["max_installments"] == 3
        assert payment["installment_value_brl"] == "R$ 53,30"
        assert payment["allows_installments"] is True
        assert "installment_value_message" not in payment

    def test_total_abaixo_de_cem_reais_so_permite_a_vista(self):
        """Nenhum produto do catalogo cai nessa faixa (manual 3.1, 2x exige >= R$ 100);
        a cotacao e feita chamando `quote` do dominio diretamente, como combinado."""
        price_quote = quote(Decimal("99.90"))
        assert price_quote.max_installments == 1

        payment = _payment_block(price_quote)

        assert "installment_value_brl" not in payment
        assert "installment_value_cents" not in payment
        assert payment["allows_installments"] is False
        message = payment["installment_value_message"].lower()
        assert "vista" in message


class TestVarreduraDeNegacaoExplicita:
    """Criterio 6: nenhum valor monetario desaparece sem um campo de negacao ao lado.

    Guarda generica: coleta todas as chaves que parecem valor monetario (sufixo
    `_brl`/`_cents`) vistas em qualquer bloco de pagamento da amostra; se faltar
    em algum caso, exige uma chave-irma que cite o mesmo radical (ex.: `pix` ou
    `installment`) explicando a ausencia. Pega omissao nova introduzida depois,
    sem precisar listar cada campo na mao.
    """

    def test_nenhum_valor_monetario_desaparece_sem_negacao(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        product_ids = [94, 95, 90, 96, 119, 121, 130, 136]
        payments = []
        for product_id in product_ids:
            result = _call(tools_by_name, "get_product_details", product_id=product_id)
            if "payment" in result:
                payments.append(result["payment"])
        assert len(payments) >= 2

        value_keys = {
            key
            for payment in payments
            for key in payment
            if key.endswith("_brl") or key.endswith("_cents")
        }

        for payment in payments:
            for key in value_keys:
                if key in payment:
                    continue
                stem = key.split("_")[0]
                siblings = [other for other in payment if other != key and stem in other]
                assert siblings, (
                    f"chave '{key}' ausente sem campo de negacao explicita em {payment!r}"
                )


class TestSituationMessageFidelidade:
    """`situation_message` so repete o que o manual 7.3 sustenta, nunca inventa (RNF-01)."""

    @pytest.mark.parametrize("product_id", [96, 136, 130])
    def test_situation_message_nao_inventa_fato_sem_fonte(
        self, tools_by_name: Mapping[str, ToolSpec], product_id: int
    ):
        result = _call(tools_by_name, "get_product_details", product_id=product_id)
        message = result["situation_message"].lower()

        assert "fabricado" not in message
        assert "reposição" not in message
        assert "reposicao" not in message
        assert "breve" not in message

    def test_produto_136_descontinuado_diz_fora_do_catalogo(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, "get_product_details", product_id=136)
        assert "catálogo" in result["situation_message"].lower()

    def test_produto_96_esgotado_diz_temporariamente_indisponivel(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, "get_product_details", product_id=96)
        assert "temporariamente" in result["situation_message"].lower()

    def test_produto_130_em_breve_nao_promete_prazo(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", product_id=130)
        assert "disponível para venda" in result["situation_message"].lower()


class TestTextoComAcentoParaOCliente:
    """Mensagens que o LLM le (erro, descricao de ferramenta/parametro) vem acentuadas."""

    def test_unknown_category_tem_acento(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "search_products", category="saxofones")
        assert "não encontrada" in result["message"]
        assert "disponíveis" in result["message"]

    def test_invalid_arguments_tem_acento(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details")
        assert "identificar" in result["message"]
        # "Informe" nao tem acento, mas a frase inteira nao pode usar "nao" sem til.
        assert "nao" not in result["message"].split()

    def test_multiple_matches_tem_acento(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, "get_product_details", name="takamine")
        assert "à busca" in result["message"]

    def test_descricao_das_ferramentas_tem_acento(self, tool_specs: tuple[ToolSpec, ...]):
        descriptions = {spec.name: spec.description for spec in tool_specs}
        assert "catálogo" in descriptions["search_products"]
        assert "catálogo" in descriptions["get_product_details"]
        assert "catálogo" in descriptions["list_categories"]
        assert "compráveis" in descriptions["list_categories"]

    def test_descricao_dos_parametros_tem_acento(self, tool_specs: tuple[ToolSpec, ...]):
        by_name = {spec.name: spec for spec in tool_specs}
        search_properties = by_name["search_products"].parameters["properties"]
        assert "descrição" in search_properties["query"]["description"]
        assert "mínimo" in search_properties["min_price"]["description"]
        assert "máximo" in search_properties["max_price"]["description"]
        assert "padrão" in search_properties["only_available"]["description"]
        assert "Número" in search_properties["limit"]["description"]

        details_properties = by_name["get_product_details"].parameters["properties"]
        assert "não há" in details_properties["name"]["description"]


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
            _call(tools_by_name, "search_products", category="violões", max_price=1000, limit=20),
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
