"""Testes para o contrato base das ferramentas."""

from __future__ import annotations

import pytest

from emporio.tools.base import JsonDict, ToolSpec, call_tool, openai_tools, tool_error


class TestJsonDict:
    """Testes para o alias JsonDict."""

    def test_json_dict_is_dict(self):
        """JsonDict deve ser um alias para dict[str, Any]."""
        data: JsonDict = {"key": "value", "number": 42, "nested": {"inner": True}}
        assert isinstance(data, dict)


class TestToolError:
    """Testes para a função tool_error."""

    def test_tool_error_structure(self):
        """tool_error deve retornar dicionário com error e message."""
        result = tool_error("unknown_tool", "Ferramenta não encontrada")

        assert isinstance(result, dict)
        assert result["error"] == "unknown_tool"
        assert result["message"] == "Ferramenta não encontrada"

    def test_tool_error_has_only_two_keys(self):
        """tool_error deve retornar exatamente duas chaves."""
        result = tool_error("some_error", "Some message")

        assert set(result.keys()) == {"error", "message"}


class TestToolSpec:
    """Testes para a classe ToolSpec."""

    def test_tool_spec_creation(self):
        """ToolSpec deve ser criável com os atributos especificados."""

        def dummy_handler() -> JsonDict:
            return {"result": "ok"}

        spec = ToolSpec(
            name="test_tool",
            description="Uma ferramenta de teste",
            parameters={"properties": {}, "required": []},
            handler=dummy_handler,
        )

        assert spec.name == "test_tool"
        assert spec.description == "Uma ferramenta de teste"
        assert spec.parameters == {"properties": {}, "required": []}
        assert spec.handler is dummy_handler

    def test_tool_spec_frozen(self):
        """ToolSpec deve ser congelado (dataclass frozen=True)."""

        def dummy_handler() -> JsonDict:
            return {"result": "ok"}

        spec = ToolSpec(
            name="test",
            description="test",
            parameters={},
            handler=dummy_handler,
        )

        with pytest.raises(AttributeError):
            spec.name = "changed"


class TestOpenaiTools:
    """Testes para a conversão para formato OpenAI."""

    def test_openai_tools_single_spec(self):
        """openai_tools deve converter uma ferramenta para formato OpenAI."""

        def dummy_handler() -> JsonDict:
            return {}

        spec = ToolSpec(
            name="search_products",
            description="Busca produtos no catálogo",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto de busca"},
                },
                "required": ["query"],
            },
            handler=dummy_handler,
        )

        result = openai_tools([spec])

        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search_products"
        assert result[0]["function"]["description"] == "Busca produtos no catálogo"
        assert result[0]["function"]["parameters"] == spec.parameters

    def test_openai_tools_multiple_specs(self):
        """openai_tools deve converter múltiplas ferramentas."""

        def handler1() -> JsonDict:
            return {}

        def handler2() -> JsonDict:
            return {}

        specs = [
            ToolSpec("tool1", "Ferramenta 1", {}, handler1),
            ToolSpec("tool2", "Ferramenta 2", {}, handler2),
        ]

        result = openai_tools(specs)

        assert len(result) == 2
        assert result[0]["function"]["name"] == "tool1"
        assert result[1]["function"]["name"] == "tool2"

    def test_openai_tools_no_extra_keys(self):
        """openai_tools não deve adicionar chaves extras."""

        def dummy_handler() -> JsonDict:
            return {}

        spec = ToolSpec("test", "Test tool", {}, dummy_handler)
        result = openai_tools([spec])

        tool = result[0]
        assert set(tool.keys()) == {"type", "function"}
        assert set(tool["function"].keys()) == {"name", "description", "parameters"}

    def test_openai_tools_empty_list(self):
        """openai_tools com lista vazia deve retornar lista vazia."""
        result = openai_tools([])
        assert result == []


class TestCallTool:
    """Testes para a invocação de ferramentas."""

    def test_call_tool_success(self):
        """call_tool deve invocar handler com sucesso."""

        def dummy_handler(query: str) -> JsonDict:
            return {"results": [query]}

        specs = {
            "search": ToolSpec(
                name="search",
                description="Search",
                parameters={
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                handler=dummy_handler,
            )
        }

        result = call_tool(specs, "search", {"query": "test"})

        assert result == {"results": ["test"]}

    def test_call_tool_unknown_tool(self):
        """call_tool com ferramenta desconhecida deve retornar error."""
        specs = {}
        result = call_tool(specs, "unknown", {})

        assert "error" in result
        assert result["error"] == "unknown_tool"
        assert isinstance(result["message"], str)

    def test_call_tool_invalid_arguments(self):
        """call_tool com argumento não listado em properties deve retornar error."""

        def dummy_handler(valid: str) -> JsonDict:
            return {}

        specs = {
            "test": ToolSpec(
                name="test",
                description="test",
                parameters={
                    "properties": {"valid": {"type": "string"}},
                    "required": [],
                },
                handler=dummy_handler,
            )
        }

        result = call_tool(specs, "test", {"valid": "ok", "invalid": "bad"})

        assert result["error"] == "invalid_arguments"
        assert "invalid" in result["message"]

    def test_call_tool_missing_required(self):
        """call_tool sem argumento required deve retornar error."""

        def dummy_handler(required: str) -> JsonDict:
            return {}

        specs = {
            "test": ToolSpec(
                name="test",
                description="test",
                parameters={
                    "properties": {"required": {"type": "string"}},
                    "required": ["required"],
                },
                handler=dummy_handler,
            )
        }

        result = call_tool(specs, "test", {})

        assert result["error"] == "invalid_arguments"
        assert "required" in result["message"]

    def test_call_tool_handler_exception_hidden(self):
        """call_tool quando handler levanta deve mascarar a exceção."""

        def failing_handler() -> JsonDict:
            raise ValueError("Erro interno específico")

        specs = {
            "fail": ToolSpec(
                name="fail",
                description="Fails",
                parameters={"properties": {}, "required": []},
                handler=failing_handler,
            )
        }

        result = call_tool(specs, "fail", {})

        assert result["error"] == "tool_failed"
        # A mensagem genérica não deve conter o texto específico da exceção
        assert "Erro interno específico" not in result["message"]
        assert "ValueError" not in result["message"]

    def test_call_tool_handler_returns_error_dict(self):
        """call_tool devolvendo erro do handler deve ser passado através."""

        def error_handler() -> JsonDict:
            return {"error": "custom_error", "message": "Custom message"}

        specs = {
            "error": ToolSpec(
                name="error",
                description="Returns error",
                parameters={"properties": {}, "required": []},
                handler=error_handler,
            )
        }

        result = call_tool(specs, "error", {})

        # O handler retornou um dicionário com erro, que deve passar through
        assert result == {"error": "custom_error", "message": "Custom message"}

    def test_call_tool_with_valid_arguments(self):
        """call_tool com argumentos válidos deve invocar handler."""

        def add_handler(a: int, b: int) -> JsonDict:
            return {"result": a + b}

        specs = {
            "add": ToolSpec(
                name="add",
                description="Add two numbers",
                parameters={
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                    "required": ["a", "b"],
                },
                handler=add_handler,
            )
        }

        result = call_tool(specs, "add", {"a": 5, "b": 3})

        assert result == {"result": 8}

    def test_call_tool_empty_parameters_allowed(self):
        """call_tool com ferramenta sem parâmetros deve funcionar."""

        def no_params_handler() -> JsonDict:
            return {"status": "ok"}

        specs = {
            "status": ToolSpec(
                name="status",
                description="Get status",
                parameters={"properties": {}, "required": []},
                handler=no_params_handler,
            )
        }

        result = call_tool(specs, "status", {})

        assert result == {"status": "ok"}

    def test_call_tool_checks_in_order(self):
        """call_tool deve verificar problemas na ordem especificada."""
        # Esta é mais uma verificação de que a ordem é consistente:
        # 1. ferramenta inexistente
        # 2. argumento inválido
        # 3. falta argumento required
        # 4. handler levanta
        # 5. sucesso

        # Teste 1: ferramenta inexistente
        result = call_tool({}, "unknown", {})
        assert result["error"] == "unknown_tool"

        # Teste 2: argumento inválido
        def handler(valid: str) -> JsonDict:
            return {}

        specs = {
            "test": ToolSpec(
                "test",
                "test",
                {"properties": {"valid": {}}, "required": []},
                handler,
            )
        }
        result = call_tool(specs, "test", {"invalid": "arg"})
        assert result["error"] == "invalid_arguments"

        # Teste 3: falta required
        specs["test2"] = ToolSpec(
            "test2",
            "test2",
            {"properties": {"required": {}}, "required": ["required"]},
            handler,
        )
        result = call_tool(specs, "test2", {})
        assert result["error"] == "invalid_arguments"
