"""Consulta ao manual de politicas da loja, pre-processado em secoes por topico.

Le `data/processed/politicas.json` (gerado por `scripts/extrair_politicas.py`)
e expoe uma consulta tipada por topico, sem precisar do PDF nem do
`pdfplumber` em tempo de execucao.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

POLICY_TOPICS: Final[tuple[str, ...]] = (
    "about_store",
    "contact_address",
    "hours",
    "payment",
    "returns_exchanges",
    "shipping",
    "tracking",
    "promotions",
    "warranty",
    "privacy",
    "service_scope",
)

DEFAULT_POLICIES_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "processed" / "politicas.json"
)


@dataclass(frozen=True)
class StoreInfo:
    """Dados cadastrais da loja, extraidos da tabela 'Dados da Empresa' do manual."""

    legal_name: str
    trade_name: str
    tax_id: str
    address_line: str
    city: str
    state: str
    postal_code: str
    phone: str
    email: str
    founded_year: int


@dataclass(frozen=True)
class PolicySection:
    """Uma secao numerada do manual, com o texto literal (limpo) do PDF."""

    number: str
    title: str
    text: str


@dataclass(frozen=True)
class PolicyBook:
    """Manual de politicas carregado, consultavel por topico.

    `_by_topic` e um detalhe de implementacao (nao faz parte do contrato
    publico); `get`/`topics` sao a interface usada pelo resto do produto.
    """

    manual_version: str
    store: StoreInfo
    _by_topic: dict[str, tuple[PolicySection, ...]] = field(repr=False)

    def get(self, topic: str) -> tuple[PolicySection, ...]:
        """Devolve as secoes do topico, na ordem do manual.

        Levanta `KeyError` se o topico nao existir.
        """
        return self._by_topic[topic]

    def topics(self) -> tuple[str, ...]:
        """Devolve os topicos consultaveis (ver `POLICY_TOPICS`)."""
        return POLICY_TOPICS


def load_policy_book(path: Path | None = None) -> PolicyBook:
    """Carrega o manual a partir do JSON pre-processado.

    Por padrao le `data/processed/politicas.json`. Secoes marcadas como
    `uso_interno` ou sem topico (`topico: null`) nunca entram em `_by_topic`,
    entao `get` nunca pode devolve-las.
    """
    policies_path = path if path is not None else DEFAULT_POLICIES_PATH
    raw = json.loads(policies_path.read_text(encoding="utf-8"))

    loja = raw["loja"]
    store = StoreInfo(
        legal_name=loja["razao_social"],
        trade_name=loja["nome_fantasia"],
        tax_id=loja["cnpj"],
        address_line=loja["endereco"],
        city=loja["cidade"],
        state=loja["uf"],
        postal_code=loja["cep"],
        phone=loja["telefone"],
        email=loja["email"],
        founded_year=loja["fundacao"],
    )

    by_topic: dict[str, list[PolicySection]] = {topic: [] for topic in POLICY_TOPICS}
    for secao in raw["secoes"]:
        topico = secao["topico"]
        if topico is None or secao["uso_interno"]:
            continue
        section = PolicySection(number=secao["numero"], title=secao["titulo"], text=secao["texto"])
        by_topic.setdefault(topico, []).append(section)

    return PolicyBook(
        manual_version=raw["versao_manual"],
        store=store,
        _by_topic={topic: tuple(sections) for topic, sections in by_topic.items()},
    )
