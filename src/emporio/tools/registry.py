"""Registro unico das ferramentas do agente (T-10).

Junta as sete ferramentas (catalogo, pedido, politica, status da loja e
encaminhamento) num unico objeto que o loop do agente consome: a lista de
schemas para o LLM e o `call` que despacha qualquer chamada de ferramenta
sem nunca levantar excecao para fora.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from emporio.config import Clock, project_root
from emporio.data.catalog import Catalog
from emporio.data.orders import OrderBook
from emporio.policies.store import PolicyBook
from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools
from emporio.tools.catalog_tools import build_catalog_tools
from emporio.tools.handoff_tools import HandoffSink, JsonlHandoffSink, build_handoff_tools
from emporio.tools.order_tools import build_order_tools
from emporio.tools.policy_tools import build_policy_tools
from emporio.tools.store_tools import build_store_tools

__all__ = ["ToolRegistry", "build_registry"]

_DEFAULT_HANDOFFS_PATH = project_root() / "data" / "handoffs.jsonl"


@dataclass(frozen=True)
class ToolRegistry:
    """Conjunto de ferramentas do agente, indexado por nome."""

    specs: Mapping[str, ToolSpec]

    def names(self) -> tuple[str, ...]:
        """Devolve os nomes das ferramentas registradas."""
        return tuple(self.specs.keys())

    def openai_schemas(self) -> list[JsonDict]:
        """Devolve os schemas no formato de function calling da OpenAI."""
        return openai_tools(self.specs.values())

    def call(self, name: str, arguments: JsonDict) -> JsonDict:
        """Invoca a ferramenta `name`; nunca levanta excecao para fora (delega a `call_tool`)."""
        return call_tool(self.specs, name, arguments)


def _index(specs: tuple[ToolSpec, ...]) -> dict[str, ToolSpec]:
    """Indexa as specs por nome, falhando claro se algum nome vier duplicado."""
    by_name: dict[str, ToolSpec] = {}
    for spec in specs:
        if spec.name in by_name:
            raise ValueError(f"ferramenta duplicada no registro: {spec.name!r}")
        by_name[spec.name] = spec
    return by_name


def build_registry(
    *,
    catalog: Catalog,
    order_book: OrderBook,
    policy_book: PolicyBook,
    clock: Clock,
    handoff_sink: HandoffSink | None = None,
) -> ToolRegistry:
    """Monta o registro com as sete ferramentas do agente.

    `handoff_sink` `None` usa o `JsonlHandoffSink` apontando para
    `data/handoffs.jsonl` (registro de execucao local, fora do repositorio).
    """
    sink = handoff_sink if handoff_sink is not None else JsonlHandoffSink(_DEFAULT_HANDOFFS_PATH)

    specs: tuple[ToolSpec, ...] = (
        *build_catalog_tools(catalog),
        *build_order_tools(order_book, catalog, clock),
        *build_policy_tools(policy_book),
        *build_store_tools(clock),
        *build_handoff_tools(clock, sink),
    )

    return ToolRegistry(specs=_index(specs))
