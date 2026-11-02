"""Testes de `create_handoff`: protocolo diario, prazo de 24h uteis e os dois sinks (RF-10)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from emporio.config import STORE_TZ, FixedClock
from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools
from emporio.tools.handoff_tools import (
    InMemoryHandoffSink,
    JsonlHandoffSink,
    build_handoff_tools,
)


def _clock(*, year: int = 2026, month: int = 2, day: int = 20, hour: int = 10) -> FixedClock:
    return FixedClock(datetime(year, month, day, hour, tzinfo=STORE_TZ))


def _tools_by_name(clock: FixedClock, sink: object) -> Mapping[str, ToolSpec]:
    return {spec.name: spec for spec in build_handoff_tools(clock, sink)}  # type: ignore[arg-type]


def _call(tools_by_name: Mapping[str, ToolSpec], **kwargs: object) -> JsonDict:
    return call_tool(tools_by_name, "create_handoff", kwargs)


class TestBuildHandoffTools:
    """A fabrica devolve uma unica ferramenta."""

    def test_devolve_uma_ferramenta(self):
        specs = build_handoff_tools(_clock(), InMemoryHandoffSink())
        assert len(specs) == 1
        assert specs[0].name == "create_handoff"


class TestProtocoloDeterministico:
    """Mesmo dia, duas chamadas: protocolos sequenciais 0001 e 0002 (criterio 10)."""

    def test_duas_chamadas_no_mesmo_dia(self):
        sink = InMemoryHandoffSink()
        tools_by_name = _tools_by_name(_clock(), sink)

        first = _call(tools_by_name, reason="complaint", summary="cliente insatisfeito")
        second = _call(tools_by_name, reason="other", summary="outra dúvida")

        assert first["protocol"] == "EM-20260220-0001"
        assert second["protocol"] == "EM-20260220-0002"

    def test_sink_guarda_reason_summary_e_contact(self):
        sink = InMemoryHandoffSink()
        tools_by_name = _tools_by_name(_clock(), sink)

        _call(
            tools_by_name,
            reason="price_negotiation",
            summary="quer desconto maior",
            contact="cliente@exemplo.com",
        )

        assert len(sink.recorded) == 1
        entry = sink.recorded[0]
        assert entry["reason"] == "price_negotiation"
        assert entry["summary"] == "quer desconto maior"
        assert entry["contact"] == "cliente@exemplo.com"

    def test_dia_diferente_reinicia_sequencial(self):
        sink = InMemoryHandoffSink()
        tools_by_name_dia1 = _tools_by_name(_clock(day=20), sink)
        tools_by_name_dia2 = _tools_by_name(_clock(day=21), sink)

        first = _call(tools_by_name_dia1, reason="complaint", summary="caso 1")
        second = _call(tools_by_name_dia2, reason="complaint", summary="caso 2")

        assert first["protocol"] == "EM-20260220-0001"
        assert second["protocol"] == "EM-20260221-0001"


class TestPrazoDeRetorno:
    """O prazo de retorno vem de `add_business_hours(clock.now(), 24)`, em ISO e em frase."""

    def test_prazo_24h_uteis_a_partir_de_sexta_17h(self):
        sink = InMemoryHandoffSink()
        clock = FixedClock(datetime(2026, 2, 20, 17, 0, tzinfo=STORE_TZ))  # sexta-feira
        tools_by_name = _tools_by_name(clock, sink)

        result = _call(tools_by_name, reason="unanswered", summary="pergunta sem resposta")

        assert result["response_deadline_iso"] == "2026-02-25T10:00:00-04:00"
        assert "24 horas úteis" in result["message"]


class TestSummaryVazio:
    """`summary` vazio ou so espaco devolve `invalid_arguments` (criterio 11)."""

    def test_summary_so_espaco(self):
        sink = InMemoryHandoffSink()
        tools_by_name = _tools_by_name(_clock(), sink)
        result = _call(tools_by_name, reason="complaint", summary="   ")
        assert result["error"] == "invalid_arguments"
        assert sink.recorded == []

    def test_summary_vazio(self):
        sink = InMemoryHandoffSink()
        tools_by_name = _tools_by_name(_clock(), sink)
        result = _call(tools_by_name, reason="complaint", summary="")
        assert result["error"] == "invalid_arguments"


class TestReasonInvalido:
    """Motivo fora do enum tambem devolve `invalid_arguments`."""

    def test_reason_fora_do_enum(self):
        sink = InMemoryHandoffSink()
        tools_by_name = _tools_by_name(_clock(), sink)
        result = _call(tools_by_name, reason="nao_existe", summary="algo")
        assert result["error"] == "invalid_arguments"


class TestJsonlHandoffSink:
    """Sink de producao: grava uma linha por chamada e retoma o sequencial (criterio 12)."""

    def test_grava_uma_linha_por_chamada(self, tmp_path: Path):
        path = tmp_path / "handoffs.jsonl"
        sink = JsonlHandoffSink(path=path)
        tools_by_name = _tools_by_name(_clock(), sink)

        _call(tools_by_name, reason="complaint", summary="caso 1")
        _call(tools_by_name, reason="complaint", summary="caso 2")

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first_record = json.loads(lines[0])
        assert first_record["protocol"] == "EM-20260220-0001"
        second_record = json.loads(lines[1])
        assert second_record["protocol"] == "EM-20260220-0002"

    def test_cria_arquivo_e_diretorio_se_faltarem(self, tmp_path: Path):
        path = tmp_path / "subdir" / "handoffs.jsonl"
        sink = JsonlHandoffSink(path=path)
        tools_by_name = _tools_by_name(_clock(), sink)

        _call(tools_by_name, reason="complaint", summary="caso 1")

        assert path.exists()

    def test_sequencial_continua_ao_recriar_o_sink(self, tmp_path: Path):
        path = tmp_path / "handoffs.jsonl"

        sink_1 = JsonlHandoffSink(path=path)
        _call(_tools_by_name(_clock(), sink_1), reason="complaint", summary="caso 1")

        sink_2 = JsonlHandoffSink(path=path)
        result = _call(_tools_by_name(_clock(), sink_2), reason="complaint", summary="caso 2")

        assert result["protocol"] == "EM-20260220-0002"

    def test_ensure_ascii_false_e_fim_de_linha_unix(self, tmp_path: Path):
        path = tmp_path / "handoffs.jsonl"
        sink = JsonlHandoffSink(path=path)
        tools_by_name = _tools_by_name(_clock(), sink)

        _call(tools_by_name, reason="complaint", summary="reclamação com acentuação")

        raw = path.read_bytes().decode("utf-8")
        assert "reclamação com acentuação" in raw
        assert "\\u" not in raw
        assert raw.endswith("\n")
        assert "\r\n" not in raw


class TestSerializacaoJson:
    """Nenhum retorno carrega tipo que `json.dumps` padrao nao serializa."""

    def test_retornos_sao_json_serializaveis(self):
        sink = InMemoryHandoffSink()
        tools_by_name = _tools_by_name(_clock(), sink)
        results = [
            _call(tools_by_name, reason="complaint", summary="caso 1"),
            _call(tools_by_name, reason="data_deletion", summary="excluir meus dados"),
            _call(tools_by_name, reason="complaint", summary="   "),
            _call(tools_by_name, reason="invalido", summary="algo"),
        ]
        for result in results:
            json.dumps(result)


class TestContratoOpenai:
    """A ferramenta passa por `openai_tools` sem erro."""

    def test_openai_tools_gera_schema_valido(self):
        specs = build_handoff_tools(_clock(), InMemoryHandoffSink())
        schemas = openai_tools(specs)
        assert len(schemas) == 1
        assert schemas[0]["function"]["parameters"]["required"] == ["reason", "summary"]


class TestTextoComAcentoParaOCliente:
    """Mensagens e descricoes que o LLM le vem em portugues com acento."""

    def test_descricao_da_ferramenta_tem_acento(self):
        specs = build_handoff_tools(_clock(), InMemoryHandoffSink())
        assert "é" in specs[0].description or "ã" in specs[0].description

    def test_mensagem_de_confirmacao_tem_acento(self):
        sink = InMemoryHandoffSink()
        tools_by_name = _tools_by_name(_clock(), sink)
        result = _call(tools_by_name, reason="complaint", summary="caso 1")
        assert "é" in result["message"] or "á" in result["message"] or "ã" in result["message"]
