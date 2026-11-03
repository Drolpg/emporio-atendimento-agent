"""Testes sem rede e sem chave do runner de evals (T-15).

Fica fora de `testpaths` (só `tests/`), mas roda como suíte normal do
`pytest` quando invocado direto (`uv run pytest evals/`): nenhum teste aqui
usa `@pytest.mark.llm` nem toca o provedor real — é o próprio runner
(`evals.runner`) que é testado com `ScriptedLlm`, o mesmo dublê usado em
`tests/test_agent_loop.py`.
"""

from __future__ import annotations

import re

import pytest

from emporio.config import load_settings, project_root
from evals.runner import ORDER_TOOL_NAME, contains_fact, main, run_scenario
from evals.scenarios import SCENARIOS, Scenario
from tests.fakes.llm import ScriptedLlm, reply_text, reply_tool


def _settings():
    return load_settings(
        {
            "LLM_API_KEY": "chave-de-teste",
            "LLM_MODEL": "modelo-de-teste",
            "LLM_BASE_URL": "https://provedor.invalido/v1",
        }
    )


def _scenario_by_id(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise AssertionError(f"cenario {scenario_id!r} nao encontrado em SCENARIOS")


def _blank_scenario(**overrides: object) -> Scenario:
    """Cenário mínimo, só com o que cada teste precisa verificar."""
    base = dict(
        scenario_id="E-TESTE",
        title="cenário de teste",
        requirements=(),
        messages=("oi",),
        expected_tools=(),
        must_contain=(),
        must_not_contain=(),
    )
    base.update(overrides)
    return Scenario(**base)  # type: ignore[arg-type]


class TestCatalogoDeCenarios:
    """Criterio 1: os 12 cenarios citados nas notas existem no codigo, com ids unicos."""

    def test_doze_cenarios_com_ids_unicos_de_e01_a_e12(self):
        ids = [scenario.scenario_id for scenario in SCENARIOS]
        assert len(ids) == 12
        assert len(set(ids)) == 12
        assert set(ids) == {f"E-{n:02d}" for n in range(1, 13)}

    def test_todo_scenario_id_das_notas_existe_no_codigo(self):
        notas_path = project_root() / "notas-internas" / "cenarios-eval.md"
        texto = notas_path.read_text(encoding="utf-8")
        ids_nas_notas = set(re.findall(r"##\s+(E-\d\d)\b", texto))

        assert ids_nas_notas, "nao encontrei nenhum cabecalho de cenario nas notas"
        ids_no_codigo = {scenario.scenario_id for scenario in SCENARIOS}
        assert ids_nas_notas <= ids_no_codigo


class TestNormalizacaoTolerante:
    """Criterios 2 e 3: a normalizacao de dinheiro/percentual mede fidelidade, nao formato."""

    @pytest.mark.parametrize(
        "resposta",
        ["R$ 2.199,00", "R$ 2199,00", "R$ 2 199", "2199 reais"],
    )
    def test_formatos_equivalentes_de_dinheiro_casam_o_mesmo_fato(self, resposta: str):
        assert contains_fact(resposta, "2199")

    def test_espaco_antes_do_percentual_casa(self):
        assert contains_fact("12 %", "12%")

    def test_nao_casa_valor_errado_mesmo_normalizado(self):
        assert not contains_fact("R$ 1.935,12", "2199")

    def test_must_not_contain_pega_valor_proibido_com_separador_diferente(self):
        assert contains_fact("R$ 1 935,12", "1935,12")


class TestRunScenario:
    """Criterios 4, 5 e 6: `run_scenario` com `ScriptedLlm`, sem rede."""

    def test_aprova_quando_fato_obrigatorio_aparece(self):
        scenario = _blank_scenario(must_contain=("R$ 429,90",))
        llm = ScriptedLlm([reply_text("O violão sai por R$ 429,90.")])

        result = run_scenario(scenario, settings=_settings(), llm=llm)

        assert result.passed is True
        assert result.missing == ()

    def test_reprova_e_lista_o_que_faltou_quando_fato_obrigatorio_nao_aparece(self):
        scenario = _blank_scenario(must_contain=("R$ 429,90",))
        llm = ScriptedLlm([reply_text("Não tenho esse valor agora.")])

        result = run_scenario(scenario, settings=_settings(), llm=llm)

        assert result.passed is False
        assert result.missing == ("R$ 429,90",)

    def test_reprova_e_lista_o_que_apareceu_de_proibido(self):
        scenario = _blank_scenario(must_not_contain=("R$ 1.935,12",))
        llm = ScriptedLlm([reply_text("Com o desconto antigo, sairia por R$ 1.935,12.")])

        result = run_scenario(scenario, settings=_settings(), llm=llm)

        assert result.passed is False
        assert result.forbidden_found == ("R$ 1.935,12",)

    def test_fallback_de_indisponibilidade_marca_unavailable_e_nao_aprovado(self):
        from emporio.agent.loop import _FALLBACK_LLM_UNAVAILABLE

        scenario = _blank_scenario(must_contain=("qualquer coisa",))
        llm = ScriptedLlm([reply_text(_FALLBACK_LLM_UNAVAILABLE)])

        result = run_scenario(scenario, settings=_settings(), llm=llm)

        assert result.unavailable is True
        assert result.passed is False
        # "nao avaliado" e distinto de "falhou": nao lista fatos faltando.
        assert result.missing == ()


class TestCenarioE04PedidoSemVerificacao:
    """Criterio 8: expected_tools vazio reprova quando `get_order_status` tem sucesso."""

    def test_aprova_sem_nenhuma_chamada_de_pedido(self):
        scenario = _scenario_by_id("E-04")
        llm = ScriptedLlm(
            [
                reply_text(
                    "Para consultar o pedido 10, preciso do número do pedido e do seu "
                    "e-mail ou telefone cadastrados no titular."
                )
            ]
        )

        result = run_scenario(scenario, settings=_settings(), llm=llm)

        assert result.passed is True
        assert ORDER_TOOL_NAME not in result.tools_used

    def test_reprova_quando_get_order_status_aparece_com_sucesso(self):
        scenario = _scenario_by_id("E-04")
        # Pedido 10 pertence ao cliente 11 (bruno.martins@jmail.com): credenciais
        # corretas, a chamada tem sucesso (sem "error" no resultado da ferramenta).
        llm = ScriptedLlm(
            [
                reply_tool(
                    "get_order_status", order_id=10, email_or_phone="bruno.martins@jmail.com"
                ),
                reply_text("Seu pedido 10 está confirmado, no valor de R$ 87,32."),
            ]
        )

        result = run_scenario(scenario, settings=_settings(), llm=llm)

        assert result.passed is False
        assert ORDER_TOOL_NAME in result.tools_used


class TestMainSemChave:
    """Criterio 7: sem chave configurada, `main` sai com codigo 2 sem chamar o provedor."""

    def test_sem_chave_devolve_2_e_nao_chama_provedor(self, capsys: pytest.CaptureFixture[str]):
        codigo = main(["--only", "E-01"], env={})

        captured = capsys.readouterr()
        assert codigo == 2
        assert "chave" in captured.out.lower()


class TestNormalizacaoDescobertaNaExecucaoReal:
    """Casos que so apareceram rodando contra o provedor de verdade.

    Cada um tem o par positivo (mesmo fato, formato diferente, deve casar) e o
    negativo (valor diferente, nao pode casar) - sem o negativo, afrouxar a
    comparacao deixaria passar preco errado.
    """

    @pytest.mark.parametrize(
        ("resposta", "fato"),
        [
            ("Rozini RC\u2011104 Nylon", "Rozini RC-104"),  # hifen nao separavel
            ("Tagima Memphis AC\u201139", "Tagima Memphis AC-39"),
            ("informe seu e\u2011mail", "e-mail"),
            ("Taylor 110e \u2013 R$ 5.519,08", "Taylor 110e - R$ 5.519,08"),  # en dash
            ("parcela minima de R$ 100", "R$ 100,00"),  # centavos zerados omitidos
            ("ate 12x de R$ 183,25", "R$ 183,25"),
        ],
    )
    def test_casa_mesmo_fato_em_formato_diferente(self, resposta: str, fato: str) -> None:
        assert contains_fact(resposta, fato)

    @pytest.mark.parametrize(
        ("resposta", "fato"),
        [
            ("R$ 21,99", "R$ 2.199,00"),  # separador nao pode colapsar valor diferente
            ("R$ 100,05", "R$ 100,00"),  # centavo real nao e centavo zerado
            ("R$ 1.935,12", "R$ 2.199,00"),  # preco da promocao inativa
            ("desconto de 18%", "8%"),  # 18 nao contem 8 como fato isolado
        ],
    )
    def test_nao_casa_valor_diferente(self, resposta: str, fato: str) -> None:
        assert not contains_fact(resposta, fato)
