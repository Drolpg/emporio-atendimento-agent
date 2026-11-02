"""Contrato base das ferramentas do agente."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "JsonDict",
    "ToolSpec",
    "tool_error",
    "openai_tools",
    "call_tool",
]


# Alias para dicionários JSON
JsonDict = dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    """Especificação de uma ferramenta do agente."""

    name: str
    description: str
    parameters: JsonDict
    handler: Callable[..., JsonDict]


def tool_error(code: str, message: str) -> JsonDict:
    """Retorna um erro de ferramenta no formato padrão.

    Args:
        code: Código do erro (ex: "unknown_tool", "invalid_arguments").
        message: Mensagem de erro descritiva.

    Returns:
        Dicionário com "error" e "message".
    """
    return {"error": code, "message": message}


def openai_tools(specs: Iterable[ToolSpec]) -> list[JsonDict]:
    """Converte especificações de ferramentas para o formato OpenAI.

    Args:
        specs: Iterável de ToolSpec.

    Returns:
        Lista de dicionários no formato OpenAI (compatível com function calling).
    """
    result = []
    for spec in specs:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
        )
    return result


def call_tool(specs: Mapping[str, ToolSpec], name: str, arguments: JsonDict) -> JsonDict:
    """Invoca uma ferramenta com os argumentos fornecidos.

    Verifica em ordem:
    1. Ferramenta existe
    2. Argumentos são válidos (não possuem chaves inválidas)
    3. Argumentos obrigatórios estão presentes
    4. Handler é invocado (capturando exceções)
    5. Resultado é retornado

    Args:
        specs: Mapeamento de nome → ToolSpec.
        name: Nome da ferramenta a invocar.
        arguments: Argumentos (JSON dict).

    Returns:
        Resultado do handler ou error dict.
    """
    # 1. Verificar se ferramenta existe
    if name not in specs:
        return tool_error("unknown_tool", f"Ferramenta '{name}' não encontrada")

    spec = specs[name]
    parameters = spec.parameters
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    # 2. Verificar argumentos inválidos
    for arg_name in arguments:
        if arg_name not in properties:
            return tool_error("invalid_arguments", f"Argumento inválido: {arg_name!r}")

    # 3. Verificar argumentos obrigatórios
    for req_arg in required:
        if req_arg not in arguments:
            return tool_error("invalid_arguments", f"Falta argumento obrigatório: {req_arg!r}")

    # 4. Invocar handler, capturando exceções
    try:
        result = spec.handler(**arguments)
        return result
    except Exception:
        # Retornar erro genérico sem revelar detalhes
        return tool_error("tool_failed", "Erro ao executar a ferramenta")
