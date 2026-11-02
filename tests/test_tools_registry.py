"""Testes do registro unico de ferramentas (T-10).

O teste de conformidade (`TestConformidadeSchemaHandler`) e o mais importante
desta tarefa: os JSON Schemas sao escritos a mao (D-10) e precisam continuar
batendo com a assinatura do handler conforme ferramentas sao acrescentadas.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime

import pytest

from emporio.config import STORE_TZ, FixedClock, project_root
from emporio.data.catalog import Catalog
from emporio.data.orders import OrderBook
from emporio.policies.store import load_policy_book
from emporio.tools.handoff_tools import InMemoryHandoffSink
from emporio.tools.registry import ToolRegistry, build_registry

RAW_DIR = project_root() / "data" / "raw"

_EXPECTED_NAMES = {
    "search_products",
    "get_product_details",
    "list_categories",
    "get_order_status",
    "get_policy",
    "get_store_status",
    "create_handoff",
}


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(RAW_DIR)


@pytest.fixture(scope="module")
def order_book() -> OrderBook:
    return OrderBook.load(RAW_DIR)


def _clock(hour: int = 10, weekday_date: tuple[int, int, int] = (2026, 2, 18)) -> FixedClock:
    year, month, day = weekday_date
    return FixedClock(datetime(year, month, day, hour, tzinfo=STORE_TZ))


@pytest.fixture
def registry(catalog: Catalog, order_book: OrderBook) -> ToolRegistry:
    return build_registry(
        catalog=catalog,
        order_book=order_book,
        policy_book=load_policy_book(),
        clock=_clock(),
        handoff_sink=InMemoryHandoffSink(),
    )


class TestBuildRegistry:
    """Criterio 6: as sete ferramentas, com schema de function calling valido."""

    def test_names_devolve_as_sete_ferramentas(self, registry: ToolRegistry):
        assert set(registry.names()) == _EXPECTED_NAMES
        assert len(registry.names()) == 7

    def test_openai_schemas_produz_sete_entradas(self, registry: ToolRegistry):
        schemas = registry.openai_schemas()
        assert len(schemas) == 7
        for schema in schemas:
            assert schema["type"] == "function"
            assert isinstance(schema["function"]["name"], str)
            assert isinstance(schema["function"]["description"], str)
            assert schema["function"]["parameters"]["type"] == "object"
            json.dumps(schema)


class TestCallDelegaParaCallTool:
    """Criterio 7: `call` nunca levanta excecao e usa os erros padrao de `call_tool`."""

    def test_ferramenta_inexistente(self, registry: ToolRegistry):
        result = registry.call("inexistente", {})
        assert result["error"] == "unknown_tool"

    def test_argumento_com_nome_errado(self, registry: ToolRegistry):
        result = registry.call("get_policy", {"topico": "hours"})
        assert result["error"] == "invalid_arguments"


class TestNomeDuplicadoFalhaNaConstrucao:
    """Nome de ferramenta duplicado deve falhar claro na construcao, nunca em silencio."""

    def test_duas_specs_com_mesmo_nome(self):
        from emporio.tools.base import ToolSpec
        from emporio.tools.registry import _index

        specs = (
            ToolSpec(
                name="dup",
                description="a",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=lambda: {},
            ),
            ToolSpec(
                name="dup",
                description="b",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=lambda: {},
            ),
        )
        with pytest.raises(ValueError):
            _index(specs)


class TestConteudoDasPoliticas:
    """Criterio 8: conteudo de `get_policy` acessivel via o registro."""

    def test_hours_traz_os_tres_horarios(self, registry: ToolRegistry):
        result = registry.call("get_policy", {"topic": "hours"})
        text = " ".join(section["text"] for section in result["sections"])
        assert "09:00" in text and "18:00" in text and "13:00" in text

    def test_returns_exchanges_traz_7_e_30_dias(self, registry: ToolRegistry):
        result = registry.call("get_policy", {"topic": "returns_exchanges"})
        text = " ".join(section["text"] for section in result["sections"])
        assert "7 (sete) dias" in text
        assert "30 (trinta) dias" in text

    def test_warranty_traz_90_dias(self, registry: ToolRegistry):
        result = registry.call("get_policy", {"topic": "warranty"})
        text = " ".join(section["text"] for section in result["sections"])
        assert "90 (noventa) dias" in text

    def test_payment_traz_pix_5_e_parcela_minima_100(self, registry: ToolRegistry):
        result = registry.call("get_policy", {"topic": "payment"})
        text = " ".join(section["text"] for section in result["sections"])
        assert "5%" in text
        assert "R$ 100,00" in text


class TestStatusDaLoja:
    """Criterio 9: status da loja via o registro, nos tres cenarios de referencia."""

    def test_quarta_10h_esta_aberta(self, catalog: Catalog, order_book: OrderBook):
        reg = build_registry(
            catalog=catalog,
            order_book=order_book,
            policy_book=load_policy_book(),
            clock=_clock(hour=10, weekday_date=(2026, 2, 18)),  # quarta-feira
            handoff_sink=InMemoryHandoffSink(),
        )
        result = reg.call("get_store_status", {})
        assert result["is_open"] is True

    def test_sabado_14h_fechada_proxima_abertura_segunda(
        self, catalog: Catalog, order_book: OrderBook
    ):
        reg = build_registry(
            catalog=catalog,
            order_book=order_book,
            policy_book=load_policy_book(),
            clock=_clock(hour=14, weekday_date=(2026, 2, 21)),  # sabado
            handoff_sink=InMemoryHandoffSink(),
        )
        result = reg.call("get_store_status", {})
        assert result["is_open"] is False
        assert result["next_opening_iso"].startswith("2026-02-23T09:00:00")

    def test_domingo_fechada_proxima_abertura_segunda(
        self, catalog: Catalog, order_book: OrderBook
    ):
        reg = build_registry(
            catalog=catalog,
            order_book=order_book,
            policy_book=load_policy_book(),
            clock=_clock(hour=12, weekday_date=(2026, 2, 22)),  # domingo
            handoff_sink=InMemoryHandoffSink(),
        )
        result = reg.call("get_store_status", {})
        assert result["is_open"] is False
        assert result["next_opening_iso"].startswith("2026-02-23T09:00:00")


class TestHandoffViaRegistro:
    """Criterio 10 e 11: `create_handoff` via o registro, com o sink injetado."""

    def test_duas_chamadas_no_mesmo_dia_geram_protocolos_sequenciais(
        self, catalog: Catalog, order_book: OrderBook
    ):
        sink = InMemoryHandoffSink()
        reg = build_registry(
            catalog=catalog,
            order_book=order_book,
            policy_book=load_policy_book(),
            clock=_clock(),
            handoff_sink=sink,
        )
        first = reg.call("create_handoff", {"reason": "complaint", "summary": "caso 1"})
        second = reg.call("create_handoff", {"reason": "other", "summary": "caso 2"})
        assert first["protocol"] == "EM-20260218-0001"
        assert second["protocol"] == "EM-20260218-0002"

    def test_summary_vazio_devolve_invalid_arguments(self, registry: ToolRegistry):
        result = registry.call("create_handoff", {"reason": "complaint", "summary": "   "})
        assert result["error"] == "invalid_arguments"


class TestHandoffSinkPadraoJsonl:
    """`handoff_sink=None` usa o `JsonlHandoffSink` apontando para `data/handoffs.jsonl`."""

    def test_sink_padrao_e_jsonl_em_data_handoffs(self, catalog: Catalog, order_book: OrderBook):
        from emporio.tools.handoff_tools import JsonlHandoffSink

        reg = build_registry(
            catalog=catalog,
            order_book=order_book,
            policy_book=load_policy_book(),
            clock=_clock(),
        )
        create_handoff_spec = reg.specs["create_handoff"]
        # O handler fecha sobre o sink; inspecionamos indiretamente via closure.
        closure_sinks = [
            cell.cell_contents
            for cell in (create_handoff_spec.handler.__closure__ or ())
            if isinstance(cell.cell_contents, JsonlHandoffSink)
        ]
        assert len(closure_sinks) == 1
        assert closure_sinks[0].path == project_root() / "data" / "handoffs.jsonl"


class TestSerializacaoJson:
    """Criterio 13: nenhum retorno das tres ferramentas novas falha em `json.dumps`."""

    def test_retornos_sao_json_serializaveis(self, registry: ToolRegistry):
        results = [
            registry.call("get_policy", {"topic": "hours"}),
            registry.call("get_store_status", {}),
            registry.call("create_handoff", {"reason": "complaint", "summary": "caso 1"}),
        ]
        for result in results:
            json.dumps(result)


class TestConformidadeSchemaHandler:
    """Para toda ferramenta do registro: schema e assinatura do handler batem (1 a 5)."""

    def test_todo_parametro_do_schema_existe_no_handler(self, registry: ToolRegistry):
        for spec in registry.specs.values():
            handler_params = set(inspect.signature(spec.handler).parameters)
            schema_params = set(spec.parameters.get("properties", {}))
            missing = schema_params - handler_params
            assert not missing, f"{spec.name}: parametros do schema sem handler: {missing}"

    def test_todo_parametro_obrigatorio_do_handler_esta_no_required(self, registry: ToolRegistry):
        for spec in registry.specs.values():
            signature = inspect.signature(spec.handler)
            required = set(spec.parameters.get("required", []))
            for name, param in signature.parameters.items():
                if param.kind in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    continue
                if param.default is inspect.Parameter.empty:
                    assert name in required, (
                        f"{spec.name}: parametro obrigatorio '{name}' do handler "
                        f"nao esta em 'required'"
                    )

    def test_todo_required_existe_em_properties(self, registry: ToolRegistry):
        for spec in registry.specs.values():
            properties = set(spec.parameters.get("properties", {}))
            required = spec.parameters.get("required", [])
            for name in required:
                assert name in properties, (
                    f"{spec.name}: '{name}' em required mas nao em properties"
                )

    def test_type_object_e_toda_propriedade_tem_type_e_description(self, registry: ToolRegistry):
        for spec in registry.specs.values():
            assert spec.parameters["type"] == "object", f"{spec.name}: parameters.type != object"
            for prop_name, prop_schema in spec.parameters.get("properties", {}).items():
                assert "type" in prop_schema, f"{spec.name}.{prop_name}: sem 'type'"
                assert "description" in prop_schema, f"{spec.name}.{prop_name}: sem 'description'"

    def test_schema_nao_tem_chave_title_em_lugar_nenhum(self, registry: ToolRegistry):
        def _has_title(value: object) -> bool:
            if isinstance(value, dict):
                if "title" in value:
                    return True
                return any(_has_title(item) for item in value.values())
            if isinstance(value, list):
                return any(_has_title(item) for item in value)
            return False

        for spec in registry.specs.values():
            assert not _has_title(spec.parameters), f"{spec.name}: schema traz chave 'title'"
