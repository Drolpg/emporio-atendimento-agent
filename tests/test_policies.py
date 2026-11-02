"""Testes para a consulta ao manual de politicas por topico.

Le o `data/processed/politicas.json` versionado; nao precisa do PDF nem do
`pdfplumber` (exceto o teste de reproducibilidade, que pula sem a dependencia).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from emporio.policies import POLICY_TOPICS, PolicyBook, StoreInfo, load_policy_book
from emporio.policies.store import DEFAULT_POLICIES_PATH

FORBIDDEN_INTERNAL_SNIPPETS = (
    "Tom de voz",
    "Tempo de resposta",
    "Fluxo de Atendimento",
    "documento interno",
)


@pytest.fixture(scope="module")
def book() -> PolicyBook:
    return load_policy_book()


@pytest.fixture(scope="module")
def raw_policies() -> dict:
    return json.loads(DEFAULT_POLICIES_PATH.read_text(encoding="utf-8"))


def _joined_text(book: PolicyBook, topic: str) -> str:
    return "\n".join(section.text for section in book.get(topic))


def _all_topics_text(book: PolicyBook) -> str:
    return "\n".join(_joined_text(book, topic) for topic in POLICY_TOPICS)


class TestTopicos:
    """Todo topico devolve pelo menos uma secao; topico invalido levanta KeyError."""

    @pytest.mark.parametrize("topic", POLICY_TOPICS)
    def test_topico_devolve_pelo_menos_uma_secao(self, book: PolicyBook, topic: str):
        sections = book.get(topic)
        assert len(sections) >= 1

    def test_topico_inexistente_levanta_key_error(self, book: PolicyBook):
        with pytest.raises(KeyError):
            book.get("inexistente")

    def test_topics_devolve_todos_os_topicos_do_contrato(self, book: PolicyBook):
        assert book.topics() == POLICY_TOPICS


class TestConteudoInterno:
    """Nenhum topico exposto ao cliente devolve texto de uso interno (secoes 7 e 10)."""

    @pytest.mark.parametrize("snippet", FORBIDDEN_INTERNAL_SNIPPETS)
    def test_nenhum_topico_contem_texto_de_uso_interno(self, book: PolicyBook, snippet: str):
        assert snippet not in _all_topics_text(book)


class TestServiceScope:
    """`service_scope` traz a frase literal de escopo, sem a diretriz interna da secao 7."""

    def test_contem_a_frase_de_escopo(self, book: PolicyBook):
        text = _joined_text(book, "service_scope")
        assert "exclusivamente com instrumentos musicais" in text

    @pytest.mark.parametrize(
        "item", ["cordas", "palhetas", "cabos", "cases", "pedais", "amplificadores"]
    )
    def test_cita_os_acessorios_fora_de_escopo(self, book: PolicyBook, item: str):
        text = _joined_text(book, "service_scope")
        assert item in text


class TestFatosPorTopico:
    """Fatos literais do manual que precisam aparecer em cada topico."""

    def test_hours_contem_horarios(self, book: PolicyBook):
        text = _joined_text(book, "hours")
        assert "09:00" in text
        assert "18:00" in text
        assert "13:00" in text

    def test_payment_contem_parcelamento_e_pix(self, book: PolicyBook):
        text = _joined_text(book, "payment")
        assert "12x" in text
        assert "R$ 100,00" in text
        assert "R$ 80,00" in text
        assert "R$ 50,00" in text
        assert "5%" in text

    def test_returns_exchanges_contem_prazos_e_itens_nao_elegiveis(self, book: PolicyBook):
        text = _joined_text(book, "returns_exchanges")
        assert "7" in text
        assert "30" in text
        assert "personalização" in text
        assert "venda final" in text
        assert "Boquilhas" in text

    def test_warranty_contem_garantia_legal(self, book: PolicyBook):
        text = _joined_text(book, "warranty")
        assert "90" in text

    def test_shipping_contem_valores_e_transportadoras(self, book: PolicyBook):
        text = _joined_text(book, "shipping")
        assert "R$ 500,00" in text
        assert "R$ 35,00" in text
        assert "PAC" in text
        assert "SEDEX" in text
        assert "Jadlog" in text

    def test_tracking_contem_formato_do_codigo(self, book: PolicyBook):
        text = _joined_text(book, "tracking")
        assert "BR4K7M2X9P1BR" in text

    def test_promotions_diz_que_nao_sao_cumulativas(self, book: PolicyBook):
        text = _joined_text(book, "promotions")
        assert "não são cumulativas" in text
        assert "não se aplica sobre" in text
        assert "promocionais" in text


class TestStoreInfoFixture:
    """Dados cadastrais da loja, normalizados conforme P-01/P-02."""

    def test_store_e_storeinfo(self, book: PolicyBook):
        assert isinstance(book.store, StoreInfo)

    def test_telefone_normalizado(self, book: PolicyBook):
        assert book.store.phone == "(67) 3341-4444"

    def test_email_normalizado_sem_acento(self, book: PolicyBook):
        assert book.store.email == "contato@emporiodamusica.com.br"

    def test_cidade(self, book: PolicyBook):
        assert book.store.city == "Campo Grande"

    def test_cep(self, book: PolicyBook):
        assert book.store.postal_code == "79202-333"

    def test_fundacao(self, book: PolicyBook):
        assert book.store.founded_year == 2008

    def test_cnpj(self, book: PolicyBook):
        assert book.store.tax_id == "12.345.678/0001-90"


class TestDivergencias:
    """O JSON registra as divergencias P-01 (telefone) e P-02 (email)."""

    def test_existe_divergencia_p01(self, raw_policies: dict):
        ids = {item["id"] for item in raw_policies["divergencias"]}
        assert "P-01" in ids

    def test_existe_divergencia_p02(self, raw_policies: dict):
        ids = {item["id"] for item in raw_policies["divergencias"]}
        assert "P-02" in ids

    def test_divergencias_tem_campos_completos(self, raw_policies: dict):
        for item in raw_policies["divergencias"]:
            assert item["campo"]
            assert item["no_manual"]
            assert item["adotado"]
            assert item["motivo"]


class TestFormatoDoArquivo:
    """O JSON versionado segue o formato determinístico exigido (RNF de reprodutibilidade)."""

    def test_arquivo_termina_com_uma_linha_em_branco(self):
        content = DEFAULT_POLICIES_PATH.read_bytes()
        assert content.endswith(b"\n")
        assert not content.endswith(b"\n\n")

    def test_arquivo_preserva_acentos_sem_escape_unicode(self):
        content = DEFAULT_POLICIES_PATH.read_text(encoding="utf-8")
        assert "\\u00e9" not in content  # ensure_ascii=False: sem escapes \uXXXX
        assert "Política" in content


@pytest.mark.skipif(
    importlib.util.find_spec("pdfplumber") is None,
    reason="pdfplumber nao instalado: pulando teste de reproducibilidade do extrator",
)
def test_reexecutar_extrator_reproduz_o_json_versionado():
    """Guarda contra o JSON versionado e o extrator saindo de sincronia."""
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    try:
        from extrair_politicas import DEFAULT_PDF, extract_policy_book
    finally:
        sys.path.pop(0)

    freshly_extracted = extract_policy_book(DEFAULT_PDF)
    versioned = json.loads(DEFAULT_POLICIES_PATH.read_text(encoding="utf-8"))
    assert freshly_extracted == versioned
