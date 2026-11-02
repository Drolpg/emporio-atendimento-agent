"""Testes da ferramenta `get_store_status` (RF-08, horario da loja em Campo Grande)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

import pytest

from emporio.config import STORE_TZ, FixedClock
from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools
from emporio.tools.store_tools import build_store_tools


def _clock(*, year: int, month: int, day: int, hour: int, minute: int = 0) -> FixedClock:
    return FixedClock(datetime(year, month, day, hour, minute, tzinfo=STORE_TZ))


def _tools_by_name(clock: FixedClock) -> Mapping[str, ToolSpec]:
    return {spec.name: spec for spec in build_store_tools(clock)}


def _call(tools_by_name: Mapping[str, ToolSpec]) -> JsonDict:
    return call_tool(tools_by_name, "get_store_status", {})


class TestBuildStoreTools:
    """A fabrica devolve uma unica ferramenta, sem parametros."""

    def test_devolve_uma_ferramenta_sem_parametros(self):
        specs = build_store_tools(_clock(year=2026, month=2, day=18, hour=10))
        assert len(specs) == 1
        spec = specs[0]
        assert spec.name == "get_store_status"
        assert spec.parameters == {"type": "object", "properties": {}, "required": []}


class TestLojaAberta:
    """Quarta-feira 10:00: aberta, com o horario de hoje."""

    def test_quarta_10h_esta_aberta(self):
        clock = _clock(year=2026, month=2, day=18, hour=10)  # quarta-feira
        result = _call(_tools_by_name(clock))

        assert result["is_open"] is True
        assert result["today_opens_at"] == "09:00"
        assert result["today_closes_at"] == "18:00"
        assert "aberto" in result["message"].lower()


class TestLojaFechadaSabado:
    """Sabado 14:00: fechada, proxima abertura segunda 09:00."""

    def test_sabado_14h_fechada_proxima_abertura_segunda(self):
        clock = _clock(year=2026, month=2, day=21, hour=14)  # sabado
        result = _call(_tools_by_name(clock))

        assert result["is_open"] is False
        assert result["next_opening_iso"] == "2026-02-23T09:00:00-04:00"
        assert "segunda" in result["message"].lower()
        assert "09:00" in result["message"]


class TestLojaFechadaDomingo:
    """Domingo: fechada o dia inteiro, proxima abertura segunda 09:00."""

    def test_domingo_fechada_proxima_abertura_segunda(self):
        clock = _clock(year=2026, month=2, day=22, hour=12)  # domingo
        result = _call(_tools_by_name(clock))

        assert result["is_open"] is False
        assert result["next_opening_iso"] == "2026-02-23T09:00:00-04:00"
        assert "today_opens_at" not in result


class TestAvisoDeFeriado:
    """P-06: o agente nunca pode afirmar que a loja abre num feriado nao cadastrado."""

    def test_traz_aviso_curto_sobre_feriados(self):
        clock = _clock(year=2026, month=2, day=18, hour=10)
        result = _call(_tools_by_name(clock))
        message = result["holiday_note"].lower()
        assert "feriado" in message
        assert "não" in message or "nao" in message


class TestSerializacaoJson:
    """Nenhum retorno carrega tipo que `json.dumps` padrao nao serializa."""

    def test_retornos_sao_json_serializaveis(self):
        for clock in (
            _clock(year=2026, month=2, day=18, hour=10),
            _clock(year=2026, month=2, day=21, hour=14),
            _clock(year=2026, month=2, day=22, hour=12),
        ):
            json.dumps(_call(_tools_by_name(clock)))


class TestContratoOpenai:
    """A ferramenta passa por `openai_tools` sem erro."""

    def test_openai_tools_gera_schema_valido(self):
        specs = build_store_tools(_clock(year=2026, month=2, day=18, hour=10))
        schemas = openai_tools(specs)
        assert len(schemas) == 1
        assert schemas[0]["function"]["parameters"]["properties"] == {}


class TestNomeDoDiaEmPortugues:
    """O nome do dia da semana e escrito por nos, sem depender de locale do sistema."""

    @pytest.mark.parametrize("day", [21, 22])  # sabado e domingo, ambos reabrem segunda
    def test_mensagem_cita_o_dia_da_proxima_abertura(self, day: int):
        clock = _clock(year=2026, month=2, day=day, hour=14)
        result = _call(_tools_by_name(clock))
        assert "segunda" in result["message"].lower()
