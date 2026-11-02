"""Normalizacao de texto para comparacao, compartilhada por dados e dominio.

O cliente escreve "violoes", "Violões" ou "VIOLAO"; a cidade do cadastro vem
como "Campo Grande" mas pode chegar como "campo grande". Comparacao de nome de
categoria, de produto e de cidade passa por aqui para nao depender de acento,
caixa ou espaco repetido.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize_text", "same_text"]

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Devolve o texto sem acento, em minusculas e com espacos colapsados."""
    without_accents = "".join(
        char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn"
    )
    return _WHITESPACE.sub(" ", without_accents).strip().lower()


def same_text(left: str, right: str) -> bool:
    """Compara dois textos ignorando acento, caixa e espaco repetido."""
    return normalize_text(left) == normalize_text(right)
