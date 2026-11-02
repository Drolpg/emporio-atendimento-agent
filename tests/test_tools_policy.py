"""Testes da ferramenta `get_policy` (consulta ao manual por topico, D-12).

Usa `data/processed/politicas.json` real (sem rede, sem chave de API).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from emporio.policies.store import POLICY_TOPICS, PolicyBook, load_policy_book
from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools
from emporio.tools.policy_tools import build_policy_tools


@pytest.fixture(scope="module")
def policy_book() -> PolicyBook:
    return load_policy_book()


@pytest.fixture(scope="module")
def tool_specs(policy_book: PolicyBook) -> tuple[ToolSpec, ...]:
    return build_policy_tools(policy_book)


@pytest.fixture(scope="module")
def tools_by_name(tool_specs: tuple[ToolSpec, ...]) -> Mapping[str, ToolSpec]:
    return {spec.name: spec for spec in tool_specs}


def _call(tools_by_name: Mapping[str, ToolSpec], **kwargs: object) -> JsonDict:
    return call_tool(tools_by_name, "get_policy", kwargs)


def _all_topics_text(tools_by_name: Mapping[str, ToolSpec]) -> str:
    """Concatena o texto de todas as secoes de todos os topicos consultaveis."""
    chunks: list[str] = []
    for topic in POLICY_TOPICS:
        result = _call(tools_by_name, topic=topic)
        for section in result["sections"]:
            chunks.append(section["text"])
            chunks.append(section["title"])
    return "\n".join(chunks)


class TestBuildPolicyTools:
    """A fabrica devolve uma unica ferramenta."""

    def test_devolve_uma_ferramenta(self, tool_specs: tuple[ToolSpec, ...]):
        names = {spec.name for spec in tool_specs}
        assert names == {"get_policy"}


class TestEnumDeTopicos:
    """O parametro `topic` e um enum com exatamente os valores de POLICY_TOPICS."""

    def test_enum_bate_com_policy_topics(self, tool_specs: tuple[ToolSpec, ...]):
        spec = tool_specs[0]
        topic_schema = spec.parameters["properties"]["topic"]
        assert set(topic_schema["enum"]) == set(POLICY_TOPICS)
        assert len(topic_schema["enum"]) == len(POLICY_TOPICS)


class TestTopicoInvalido:
    """Topico fora do enum devolve `unknown_topic` listando os validos."""

    def test_topico_inexistente(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, topic="saxofone")
        assert result["error"] == "unknown_topic"
        for topic in POLICY_TOPICS:
            assert topic in result["message"]


class TestSecao7NaoEhTopico:
    """D-12: a secao 7 (uso interno) nunca aparece em nenhum topico."""

    def test_nenhum_topico_devolve_texto_da_secao_7(self, tools_by_name: Mapping[str, ToolSpec]):
        full_text = _all_topics_text(tools_by_name)
        assert "Tom de voz" not in full_text
        assert "Tempo de resposta" not in full_text
        assert "Fluxo de Atendimento" not in full_text
        assert "documento interno" not in full_text


class TestConteudoPorTopico:
    """Criterio 8: o conteudo devolvido traz os fatos que o agente precisa citar."""

    def test_hours_traz_os_tres_horarios(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, topic="hours")
        text = " ".join(section["text"] for section in result["sections"])
        assert "09:00" in text
        assert "18:00" in text
        assert "13:00" in text

    def test_returns_exchanges_traz_prazos_de_7_e_30_dias(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, topic="returns_exchanges")
        text = " ".join(section["text"] for section in result["sections"])
        assert "7 (sete) dias" in text
        assert "30 (trinta) dias" in text

    def test_warranty_traz_os_90_dias(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, topic="warranty")
        text = " ".join(section["text"] for section in result["sections"])
        assert "90 (noventa) dias" in text

    def test_payment_traz_pix_5_por_cento_e_parcela_minima_100(
        self, tools_by_name: Mapping[str, ToolSpec]
    ):
        result = _call(tools_by_name, topic="payment")
        text = " ".join(section["text"] for section in result["sections"])
        assert "5%" in text
        assert "R$ 100,00" in text


class TestRetornoTrazNumeroTituloETexto:
    """O retorno traz as secoes com numero, titulo e texto, sem resumir o manual."""

    def test_secoes_tem_numero_titulo_texto(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, topic="hours")
        assert result["topic"] == "hours"
        for section in result["sections"]:
            assert set(section.keys()) == {"number", "title", "text"}
            assert section["number"]
            assert section["title"]


class TestTextoComAcentoParaOCliente:
    """Mensagens e descricoes que o LLM le vem em portugues com acento."""

    def test_descricao_da_ferramenta_tem_acento(self, tool_specs: tuple[ToolSpec, ...]):
        spec = tool_specs[0]
        assert "política" in spec.description.lower() or "políticas" in spec.description.lower()

    def test_descricao_do_parametro_tem_acento(self, tool_specs: tuple[ToolSpec, ...]):
        spec = tool_specs[0]
        description = spec.parameters["properties"]["topic"]["description"]
        assert "ó" in description or "ã" in description or "é" in description

    def test_mensagem_de_erro_tem_acento(self, tools_by_name: Mapping[str, ToolSpec]):
        result = _call(tools_by_name, topic="saxofone")
        assert "não" in result["message"]


class TestSerializacaoJson:
    """Nenhum retorno carrega tipo que `json.dumps` padrao nao serializa."""

    def test_retornos_sao_json_serializaveis(self, tools_by_name: Mapping[str, ToolSpec]):
        for topic in POLICY_TOPICS:
            result = _call(tools_by_name, topic=topic)
            json.dumps(result)
        json.dumps(_call(tools_by_name, topic="saxofone"))


class TestContratoOpenai:
    """A ferramenta passa por `openai_tools` sem erro."""

    def test_openai_tools_gera_schema_valido(self, tool_specs: tuple[ToolSpec, ...]):
        schemas = openai_tools(tool_specs)
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert schema["function"]["parameters"]["type"] == "object"
