"""Testes do catalogo: carga de categories/products/promotions, busca e alternativas.

Usa os CSVs reais de `data/raw/` (sem rede, sem chave de API).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from emporio.config import project_root
from emporio.data.catalog import Catalog
from emporio.data.models import Availability, Product

RAW_DIR = project_root() / "data" / "raw"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(RAW_DIR)


class TestCarga:
    """Contagens basicas da carga (criterio 1)."""

    def test_numero_de_produtos(self, catalog: Catalog):
        assert len(catalog.products()) == 65

    def test_numero_de_categorias(self, catalog: Catalog):
        assert len(catalog.categories()) == 9

    def test_numero_de_promocoes_ativas(self, catalog: Catalog):
        produtos_com_promocao = [p for p in catalog.products() if p.promotion is not None]
        assert len(produtos_com_promocao) == 4
        ids = {p.product_id for p in produtos_com_promocao}
        assert ids == {90, 94, 121, 127}


class TestPromocoes:
    """Promocao inativa nunca aparece; so a ativa de cada produto conta (criterios 2 e 3)."""

    def test_produto_95_sem_promocao_inativa(self, catalog: Catalog):
        produto = catalog.product(95)
        assert produto is not None
        assert produto.promotion is None

    def test_produto_96_sem_promocao_mesmo_com_duas_inativas(self, catalog: Catalog):
        produto = catalog.product(96)
        assert produto is not None
        assert produto.promotion is None

    def test_produto_94_tem_desconto_de_8_por_cento(self, catalog: Catalog):
        produto = catalog.product(94)
        assert produto is not None
        assert produto.promotion is not None
        assert produto.promotion.discount_percent == 8

    def test_produto_90_tem_desconto_de_18_por_cento(self, catalog: Catalog):
        produto = catalog.product(90)
        assert produto is not None
        assert produto.promotion is not None
        assert produto.promotion.discount_percent == 18

    def test_promocao_duplicada_levanta_erro_claro(self, tmp_path):
        import shutil

        tmp_raw = tmp_path / "raw"
        shutil.copytree(RAW_DIR, tmp_raw)
        promotions_path = tmp_raw / "promotions.csv"
        content = promotions_path.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
        # Duplicar uma promocao ativa (produto 90) com outro id de promocao.
        content += "26,90,25,Promocao Duplicada,1\n"
        promotions_path.write_text(content, encoding="utf-8")

        with pytest.raises(ValueError, match="90"):
            Catalog.load(tmp_raw)


class TestDisponibilidade:
    """`status` tem precedencia sobre o estoque (criterio 4, P-15)."""

    def test_produto_81_disponivel(self, catalog: Catalog):
        produto = catalog.product(81)
        assert produto is not None
        assert produto.availability == Availability.AVAILABLE
        assert produto.is_purchasable is True

    def test_produto_96_esgotado(self, catalog: Catalog):
        produto = catalog.product(96)
        assert produto is not None
        assert produto.stock_quantity == 0
        assert produto.status == "active"
        assert produto.availability == Availability.OUT_OF_STOCK
        assert produto.is_purchasable is False

    def test_produto_136_descontinuado_mesmo_com_estoque(self, catalog: Catalog):
        produto = catalog.product(136)
        assert produto is not None
        assert produto.stock_quantity == 13
        assert produto.status == "discontinued"
        assert produto.availability == Availability.DISCONTINUED
        assert produto.is_purchasable is False

    def test_produto_113_descontinuado(self, catalog: Catalog):
        produto = catalog.product(113)
        assert produto is not None
        assert produto.availability == Availability.DISCONTINUED
        assert produto.is_purchasable is False

    def test_produto_130_em_breve_mesmo_com_estoque(self, catalog: Catalog):
        produto = catalog.product(130)
        assert produto is not None
        assert produto.stock_quantity == 2
        assert produto.status == "coming_soon"
        assert produto.availability == Availability.COMING_SOON
        assert produto.is_purchasable is False


class TestBusca:
    """`search` combina filtros com E logico e ordena por preco (criterios 5 e 6)."""

    def test_violoes_compraveis_ate_mil_reais(self, catalog: Catalog):
        resultado = catalog.search(category_id=5, max_price=Decimal("1000"))
        ids = {p.product_id for p in resultado}
        assert 96 not in ids
        assert 113 not in ids
        assert all(p.category_id == 5 for p in resultado)
        assert all(p.is_purchasable for p in resultado)
        assert all(p.price_brl <= Decimal("1000") for p in resultado)

    def test_limit_maior_que_resultado_devolve_todos_os_12(self, catalog: Catalog):
        resultado = catalog.search(category_id=5, max_price=Decimal("1000"), limit=100)
        assert len(resultado) == 12

    def test_limit_padrao_restringe_a_8(self, catalog: Catalog):
        resultado = catalog.search(category_id=5, max_price=Decimal("1000"))
        assert len(resultado) == 8

    def test_price_of_falso_inclui_item_caro_de_tabela(self, catalog: Catalog):
        """Com `price_of` = metade do preco de tabela, um item acima de 1000 de
        tabela passa a caber na faixa ate 1000 -- prova que a injecao e usada."""

        def metade_do_preco(product: Product) -> Decimal:
            return product.price_brl / 2

        resultado_tabela = catalog.search(category_id=5, max_price=Decimal("1000"), limit=100)
        resultado_com_price_of = catalog.search(
            category_id=5, max_price=Decimal("1000"), limit=100, price_of=metade_do_preco
        )

        ids_tabela = {p.product_id for p in resultado_tabela}
        ids_com_price_of = {p.product_id for p in resultado_com_price_of}

        assert ids_com_price_of != ids_tabela
        extras = ids_com_price_of - ids_tabela
        assert extras, "esperava pelo menos um produto novo com o preco falso"
        for product_id in extras:
            produto = catalog.product(product_id)
            assert produto is not None
            assert produto.price_brl > Decimal("1000")
            assert produto.price_brl / 2 <= Decimal("1000")


class TestFindCategory:
    """`find_category` casa por substring normalizada (criterio 7)."""

    def test_find_category_minusculo_sem_acento(self, catalog: Catalog):
        categoria = catalog.find_category("violoes")
        assert categoria is not None
        assert categoria.category_id == 5

    def test_find_category_maiusculo_com_acento(self, catalog: Catalog):
        categoria = catalog.find_category("VIOLÕES")
        assert categoria is not None
        assert categoria.category_id == 5

    def test_find_category_sem_correspondencia(self, catalog: Catalog):
        assert catalog.find_category("saxofone") is None


class TestPurchasableCount:
    """Categorias sem produto contam 0; violoes tem itens (criterio 8, P-13)."""

    @pytest.mark.parametrize("category_id", [6, 7, 8])
    def test_categorias_sem_produto(self, catalog: Catalog, category_id: int):
        assert catalog.purchasable_count(category_id) == 0

    def test_violoes_tem_itens_compraveis(self, catalog: Catalog):
        assert catalog.purchasable_count(5) > 0


class TestFindProductsByName:
    """`find_products_by_name` casa por substring normalizada (criterio 9)."""

    def test_acha_takamine_gd20(self, catalog: Catalog):
        resultado = catalog.find_products_by_name("takamine gd20")
        ids = {p.product_id for p in resultado}
        assert 95 in ids


class TestAlternatives:
    """Alternativas sao compraveis, da mesma categoria e ordenadas por proximidade (criterio 10)."""

    def test_alternativas_do_produto_96(self, catalog: Catalog):
        produto_96 = catalog.product(96)
        assert produto_96 is not None

        alternativas = catalog.alternatives(produto_96)

        assert len(alternativas) <= 3
        assert 96 not in {p.product_id for p in alternativas}
        assert all(p.category_id == 5 for p in alternativas)
        assert all(p.is_purchasable for p in alternativas)

        precos_absolutos = [abs(p.price_brl - produto_96.price_brl) for p in alternativas]
        assert precos_absolutos == sorted(precos_absolutos)

    def test_alternativas_sao_deterministicas_entre_execucoes(self, catalog: Catalog):
        produto_96 = catalog.product(96)
        assert produto_96 is not None

        primeira = catalog.alternatives(produto_96)
        segunda = catalog.alternatives(produto_96)

        assert primeira == segunda


class TestTiposDeDados:
    """Preco e specs tem o tipo e o valor exatos esperados (criterios 11 e 12)."""

    def test_price_brl_e_decimal_exato(self, catalog: Catalog):
        produto = catalog.product(81)
        assert produto is not None
        assert isinstance(produto.price_brl, Decimal)
        assert produto.price_brl == Decimal("599.9")

    def test_specs_do_produto_81(self, catalog: Catalog):
        produto = catalog.product(81)
        assert produto is not None
        assert produto.specs["top"] == "Spruce"
