"""Testes do prompt de sistema (T-12)."""

from __future__ import annotations

from datetime import datetime

from emporio.agent.prompt import (
    AGENT_NAME,
    SYSTEM_PROMPT_TEMPLATE,
    build_system_prompt,
    format_store_datetime,
)
from emporio.config import STORE_TZ


class TestFormatStoreDatetime:
    """`format_store_datetime` formata em portugues, sem depender de `locale`."""

    def test_quarta_feira_10h(self):
        moment = datetime(2026, 11, 4, 10, 0, tzinfo=STORE_TZ)
        assert format_store_datetime(moment) == "quarta-feira, 4 de novembro de 2026, 10:00"

    def test_domingo_18h30(self):
        moment = datetime(2026, 11, 1, 18, 30, tzinfo=STORE_TZ)
        assert format_store_datetime(moment) == "domingo, 1 de novembro de 2026, 18:30"


class TestBuildSystemPrompt:
    """`build_system_prompt` so preenche o template, funcao pura (criterio 14)."""

    def test_preenche_data_hora_e_linha_de_status(self):
        moment = datetime(2026, 11, 4, 10, 0, tzinfo=STORE_TZ)
        prompt = build_system_prompt(
            moment=moment, store_open_line="Estamos abertos agora, até às 18:00."
        )
        assert "quarta-feira, 4 de novembro de 2026, 10:00" in prompt
        assert "Estamos abertos agora, até às 18:00." in prompt

    def test_e_funcao_pura_mesmo_argumento_mesmo_resultado(self):
        moment = datetime(2026, 11, 4, 10, 0, tzinfo=STORE_TZ)
        first = build_system_prompt(moment=moment, store_open_line="linha")
        second = build_system_prompt(moment=moment, store_open_line="linha")
        assert first == second


class TestGuardaDoPrompt:
    """Criterio 15: sem chaves sobrando, com o nome Nina, sem regra numerica de negocio."""

    def test_sem_chaves_sobrando_e_com_o_nome_nina(self):
        moment = datetime(2026, 11, 4, 10, 0, tzinfo=STORE_TZ)
        prompt = build_system_prompt(moment=moment, store_open_line="linha")
        assert "{" not in prompt
        assert "}" not in prompt
        assert AGENT_NAME in prompt

    def test_sem_numero_de_regra_de_negocio(self):
        moment = datetime(2026, 11, 4, 10, 0, tzinfo=STORE_TZ)
        prompt = build_system_prompt(moment=moment, store_open_line="linha")
        proibidos = ("7 dias", "30 dias", "90", "12x", "5%", "R$")
        for termo in proibidos:
            assert termo not in prompt, f"prompt nao deveria conter '{termo}'"

    def test_template_bruto_tambem_nao_tem_regra_numerica(self):
        proibidos = ("7 dias", "30 dias", "90", "12x", "5%", "R$")
        for termo in proibidos:
            assert termo not in SYSTEM_PROMPT_TEMPLATE


class TestGuardasDeRedacaoDoPrompt:
    """Guardas de linhas do prompt que existem por causa de defeito observado em execucao real.

    Nao substituem os evals (a verificacao de comportamento e o cenario E-02), mas impedem que
    uma edicao futura remova a instrucao sem que ninguem perceba.
    """

    def test_manda_consultar_detalhe_do_produto_nomeado(self) -> None:
        # Sem esta linha o modelo respondeu promocao expirada usando get_policy e
        # search_products, e ficou sem o preco atual para informar.
        assert "detalhe daquele produto" in SYSTEM_PROMPT_TEMPLATE
        assert "não o preço de um item" in SYSTEM_PROMPT_TEMPLATE

    def test_proibe_prometer_capacidade_que_nao_existe(self) -> None:
        # Sem esta linha o modelo ofereceu "te avisar quando houver alguma oferta".
        assert "não avisa quando algo entra em promoção" in SYSTEM_PROMPT_TEMPLATE
        assert "Não prometa o que você não pode fazer." in SYSTEM_PROMPT_TEMPLATE

    def test_exige_o_valor_junto_da_promocao_vencida(self) -> None:
        assert "nunca só dizendo que não há desconto" in SYSTEM_PROMPT_TEMPLATE
