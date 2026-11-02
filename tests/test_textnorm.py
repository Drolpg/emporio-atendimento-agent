"""Testes da normalizacao de texto compartilhada."""

from __future__ import annotations

import pytest

from emporio.textnorm import normalize_text, same_text


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Violões", "violoes"),
        ("VIOLAO", "violao"),
        ("Campo Grande", "campo grande"),
        ("  Campo   Grande  ", "campo grande"),
        ("Instrumentos de Sopro (Madeiras)", "instrumentos de sopro (madeiras)"),
        ("Baterias e Percussão", "baterias e percussao"),
        ("Três Lagoas", "tres lagoas"),
        ("", ""),
    ],
)
def test_normalize_text_remove_acento_caixa_e_espaco(entrada: str, esperado: str) -> None:
    assert normalize_text(entrada) == esperado


def test_same_text_ignora_acento_e_caixa() -> None:
    assert same_text("Violões", "violoes")
    assert same_text("campo grande", "Campo  Grande")
    assert not same_text("Violões", "Baixos")


def test_normalize_text_nao_junta_palavras_distintas() -> None:
    # "violao" nao deve virar igual a "violoes": a normalizacao nao faz stemming.
    assert normalize_text("violao") != normalize_text("violoes")
