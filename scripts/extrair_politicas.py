"""Extrai o manual de politicas da loja (PDF) em secoes consultaveis por topico.

Le `data/raw/politicas_da_loja.pdf`, limpa o texto (cabecalho/rodape, linhas
quebradas pela paginacao, tabelas viram texto legivel em linhas) e grava
`data/processed/politicas.json`, deterministico e versionado.

Uso:
    uv run python scripts/extrair_politicas.py [--pdf CAMINHO] [--out CAMINHO]
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover - ambiente sem dependencia de dev
    raise SystemExit(
        "pdfplumber nao esta instalado. Rode 'uv sync' (grupo dev) antes de executar este script."
    ) from exc

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = REPO_ROOT / "data" / "raw" / "politicas_da_loja.pdf"
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / "politicas.json"

HEADER_TEXT = "Empório da Música Manual de Políticas e Procedimentos"
FOOTER_RE = re.compile(r"^Página \d+$")
TAGLINE_TEXT = "Empório da Música — Sua música começa aqui."
LAST_UPDATE_RE = re.compile(r"^Última atualização: (?P<atualizado_em>.+) — Versão (?P<versao>.+)$")

BASE_X0 = 72.0
LIST_X0 = 90.0
X0_TOLERANCE = 3.0
# Gaps verticais dentro de um paragrafo ficam em ~14-16pt; quebras de
# paragrafo (mesmo sem heading) ficam em ~19-20pt. 17 separa os dois casos
# (calibrado medindo as posicoes reais das linhas no PDF do manual).
PARAGRAPH_GAP_THRESHOLD = 17.0

SERVICE_SCOPE_MARKER = "Trabalhamos exclusivamente com instrumentos musicais"

# numero, titulo (como aparece no PDF), topico (None = sem topico ao cliente), uso_interno
SectionDef = tuple[str, str, str | None, bool]
SECTION_DEFS: tuple[SectionDef, ...] = (
    ("1", "Sobre a Empório da Música", "about_store", False),
    ("1.1", "Missão", "about_store", False),
    ("1.2", "Dados da Empresa", "contact_address", False),
    ("2", "Horário de Funcionamento", "hours", False),
    ("3", "Formas de Pagamento", "payment", False),
    ("3.1", "Regras de Parcelamento", "payment", False),
    ("4", "Política de Trocas e Devoluções", "returns_exchanges", False),
    ("4.1", "Direito de Arrependimento (Compras Online)", "returns_exchanges", False),
    ("4.2", "Trocas por Defeito", "returns_exchanges", False),
    ("4.3", "Trocas por Preferência", "returns_exchanges", False),
    ("4.4", "Itens Não Elegíveis para Troca", "returns_exchanges", False),
    ("5", "Política de Frete e Entregas", "shipping", False),
    ("5.1", "Entregas na Região Metropolitana de Campo Grande", "shipping", False),
    ("5.2", "Entregas para Outras Cidades", "shipping", False),
    ("5.3", "Código de Rastreamento", "tracking", False),
    ("6", "Promoções e Descontos", "promotions", False),
    ("6.1", "Tipos de Promoção", "promotions", False),
    ("6.2", "Regras de Promoções", "promotions", False),
    ("7", "Atendimento via WhatsApp", None, True),
    ("7.1", "Diretrizes de Atendimento", None, True),
    ("7.2", "Fluxo de Atendimento Padrão", None, True),
    ("7.3", "Situações Especiais", None, True),
    ("8", "Garantia", "warranty", False),
    ("8.1", "Garantia Legal", "warranty", False),
    ("8.2", "Garantia do Fabricante", "warranty", False),
    ("8.3", "O que Não Cobre a Garantia", "warranty", False),
    ("9", "Privacidade e Proteção de Dados", "privacy", False),
    ("10", "Disposições Finais", None, True),
)


def _heading_text(numero: str, titulo: str) -> str:
    """Reproduz como o titulo da secao aparece no PDF: '1. Titulo' ou '1.1 Titulo'."""
    separador = " " if "." in numero else ". "
    return f"{numero}{separador}{titulo}"


HEADING_TO_DEF: dict[str, SectionDef] = {
    _heading_text(numero, titulo): (numero, titulo, topico, uso_interno)
    for numero, titulo, topico, uso_interno in SECTION_DEFS
}


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    return _normalize_spaces(value.replace("\n", " "))


def format_table(rows: list[list[str | None]]) -> list[str]:
    """Formata uma tabela do PDF (lista de linhas) em texto legivel, uma linha por registro.

    A primeira linha da tabela (cabecalho) e descartada; cada linha seguinte
    vira 'Rotulo: valor1 — valor2 — ...', preservando todos os valores.
    """
    lines: list[str] = []
    for row in rows[1:]:
        cells = [_clean_cell(c) for c in row]
        label = cells[0]
        rest = " — ".join(c for c in cells[1:] if c)
        lines.append(f"{label}: {rest}" if rest else label)
    return lines


@dataclass
class _Line:
    top: float
    x0: float
    text: str
    is_table: bool = False


def _page_lines(page: Any) -> list[_Line]:
    """Monta as linhas de uma pagina em ordem de leitura, com tabelas ja formatadas."""
    words = page.extract_words()
    grouped: dict[int, list[Any]] = {}
    for word in words:
        key = round(word["top"])
        grouped.setdefault(key, []).append(word)

    raw: list[_Line] = []
    for top in sorted(grouped):
        ws = sorted(grouped[top], key=lambda w: w["x0"])
        text = _normalize_spaces(" ".join(w["text"] for w in ws))
        raw.append(_Line(top=float(top), x0=ws[0]["x0"], text=text))

    for table in page.find_tables():
        top0, bottom0 = table.bbox[1], table.bbox[3]
        span = [i for i, line in enumerate(raw) if top0 - 1 <= line.top <= bottom0 + 1]
        if not span:
            continue
        first, last = span[0], span[-1]
        formatted = format_table(table.extract())
        replacement = [_Line(top=top0, x0=BASE_X0, text=t, is_table=True) for t in formatted]
        raw[first : last + 1] = replacement

    return [
        line
        for line in raw
        if line.text not in (HEADER_TEXT, TAGLINE_TEXT) and not FOOTER_RE.match(line.text)
    ]


def _extract_company_table(pdf: Any) -> dict[str, str]:
    """Localiza a tabela 'Dados da Empresa' (cabecalho Campo/Informacao) e devolve um dict."""
    for page in pdf.pages:
        for table in page.find_tables():
            rows = table.extract()
            if rows and rows[0] == ["Campo", "Informação"]:
                return {_clean_cell(row[0]): _clean_cell(row[1]) for row in rows[1:]}
    raise ValueError("Tabela 'Dados da Empresa' nao encontrada no PDF.")


def _build_store_info(company: dict[str, str]) -> dict[str, Any]:
    endereco_completo = company["Endereço"]
    match = re.search(r" - ([A-Z]{2}), (\d{5}-\d{3})$", endereco_completo)
    if match is None:
        raise ValueError(f"Endereco em formato inesperado: {endereco_completo!r}")
    uf, cep = match.group(1), match.group(2)
    antes = endereco_completo[: match.start()]
    endereco, _, cidade = antes.rpartition(", ")

    return {
        "razao_social": company["Razão Social"],
        "nome_fantasia": company["Nome Fantasia"],
        "cnpj": company["CNPJ"],
        "endereco": endereco,
        "cidade": cidade,
        "uf": uf,
        "cep": cep,
        "telefone": company["Telefone / WhatsApp"],
        "email": _strip_accents(company["E-mail"]),
        "fundacao": int(company["Fundação"]),
    }


def _build_section_texts(pdf: Any) -> tuple[dict[str, str], dict[str, str]]:
    """Agrupa as linhas de todas as paginas em texto por secao.

    Devolve (texto por numero de secao, metadados do manual: versao e data).
    """
    section_texts: dict[str, list[str]] = {}
    manual_meta: dict[str, str] = {}

    current_def: SectionDef | None = None
    current_lines: list[str] = []
    paragraph: list[str] = []
    list_item: list[str] | None = None
    prev_kind: str | None = None
    prev_top: float | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            current_lines.append(" ".join(paragraph))
            paragraph = []

    def flush_list_item() -> None:
        nonlocal list_item
        if list_item is not None:
            current_lines.append(" ".join(list_item))
            list_item = None

    def flush_section() -> None:
        flush_paragraph()
        flush_list_item()
        if current_def is not None:
            numero = current_def[0]
            section_texts[numero] = list(current_lines)

    for page in pdf.pages:
        for line in _page_lines(page):
            text = line.text
            if not text:
                continue

            last_update = LAST_UPDATE_RE.match(text)
            if last_update:
                manual_meta["atualizado_em"] = last_update.group("atualizado_em")
                manual_meta["versao_manual"] = last_update.group("versao")
                continue

            if text in HEADING_TO_DEF:
                flush_section()
                current_def = HEADING_TO_DEF[text]
                current_lines = []
                prev_kind = "heading"
                prev_top = line.top
                continue

            if current_def is None:
                continue  # conteudo antes da primeira secao (capa)

            if line.is_table:
                flush_paragraph()
                flush_list_item()
                current_lines.append(text)
                prev_kind = "table"
                prev_top = line.top
                continue

            if abs(line.x0 - LIST_X0) <= X0_TOLERANCE:
                flush_paragraph()
                flush_list_item()
                list_item = [text]
                prev_kind = "list_start"
                prev_top = line.top
                continue

            if line.x0 > LIST_X0 + X0_TOLERANCE:
                if list_item is not None:
                    list_item.append(text)
                else:
                    paragraph.append(text)
                prev_kind = "list_cont"
                prev_top = line.top
                continue

            # linha de prosa (x0 ~ margem base)
            flush_list_item()
            if (
                paragraph
                and prev_kind == "prose"
                and prev_top is not None
                and (line.top - prev_top) <= PARAGRAPH_GAP_THRESHOLD
            ):
                paragraph.append(text)
            else:
                flush_paragraph()
                paragraph = [text]
            prev_kind = "prose"
            prev_top = line.top

    flush_section()
    return {numero: "\n".join(lines) for numero, lines in section_texts.items()}, manual_meta


def _build_service_scope_text(about_store_text: str) -> str:
    for paragrafo in about_store_text.split("\n"):
        if SERVICE_SCOPE_MARKER in paragrafo:
            inicio = paragrafo.index(SERVICE_SCOPE_MARKER)
            return paragrafo[inicio:]
    raise ValueError("Trecho de escopo de atendimento nao encontrado na secao 1.")


def _build_divergencias(
    section_texts: dict[str, str], store: dict[str, Any]
) -> list[dict[str, str]]:
    whatsapp_match = re.search(r"\(\d{2}\) \d{4}-\d{4}", section_texts["7"])
    numero_secao_7 = whatsapp_match.group(0) if whatsapp_match else "(67) 3321-4500"

    return [
        {
            "id": "P-01",
            "campo": "telefone",
            "no_manual": (
                f"A seção 7 (Atendimento via WhatsApp) cita o canal {numero_secao_7}, "
                f"diferente do telefone {store['telefone']} da tabela de Dados da "
                "Empresa (seção 1.2) e da capa."
            ),
            "adotado": store["telefone"],
            "motivo": (
                f"{store['telefone']} aparece duas vezes no manual, incluindo a "
                "tabela oficial de dados da empresa; o número da seção 7 é tratado "
                "como divergência pontual e não substitui o telefone oficial."
            ),
        },
        {
            "id": "P-02",
            "campo": "email",
            "no_manual": (
                "A tabela de Dados da Empresa (seção 1.2) traz o e-mail com acento "
                "no domínio: contato@empóriodamusica.com.br; a capa traz "
                f"{store['email']}, sem acento."
            ),
            "adotado": store["email"],
            "motivo": (
                "Domínio de e-mail com acento é tecnicamente improvável; a forma "
                "sem acento, presente na capa, foi adotada como oficial."
            ),
        },
    ]


def _apply_adopted_values(
    section_texts: dict[str, str], company: dict[str, str], store: dict[str, Any]
) -> dict[str, str]:
    """Troca, no texto das secoes expostas, o valor divergente do manual pelo adotado.

    P-01 e P-02 normalizam telefone e e-mail nos campos estruturados de
    `loja`; essa mesma normalizacao precisa valer dentro do texto das
    secoes (ex.: a tabela de Dados da Empresa, secao 1.2), senao
    `get_policy` devolveria ao cliente o valor divergente que a loja
    decidiu nao adotar. O valor divergente continua rastreavel em
    `divergencias`.
    """
    substituicoes = {
        company["E-mail"]: store["email"],
        company["Telefone / WhatsApp"]: store["telefone"],
    }
    resultado = dict(section_texts)
    for numero, texto in resultado.items():
        for divergente, adotado in substituicoes.items():
            if divergente != adotado:
                texto = texto.replace(divergente, adotado)
        resultado[numero] = texto
    return resultado


def extract_policy_book(pdf_path: Path) -> dict[str, Any]:
    """Le o PDF do manual e monta a estrutura do politicas.json."""
    with pdfplumber.open(pdf_path) as pdf:
        company = _extract_company_table(pdf)
        store = _build_store_info(company)
        section_texts, manual_meta = _build_section_texts(pdf)

    section_texts = _apply_adopted_values(section_texts, company, store)

    secoes: list[dict[str, Any]] = []
    for numero, titulo, topico, uso_interno in SECTION_DEFS:
        secoes.append(
            {
                "numero": numero,
                "titulo": titulo,
                "topico": topico,
                "uso_interno": uso_interno,
                "texto": section_texts[numero],
            }
        )

    secoes.append(
        {
            "numero": "1",
            "titulo": "Escopo de Atendimento (trecho da seção 1)",
            "topico": "service_scope",
            "uso_interno": False,
            "texto": _build_service_scope_text(section_texts["1"]),
        }
    )

    return {
        "fonte": "data/raw/politicas_da_loja.pdf",
        "versao_manual": manual_meta["versao_manual"],
        "atualizado_em": manual_meta["atualizado_em"],
        "loja": store,
        "divergencias": _build_divergencias(section_texts, store),
        "secoes": secoes,
    }


def write_policy_book(data: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    out_path.write_text(content + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="Caminho do PDF de origem")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Caminho do JSON de saida")
    args = parser.parse_args()

    data = extract_policy_book(args.pdf)
    write_policy_book(data, args.out)
    print(f"Politicas extraidas: {args.out}")


if __name__ == "__main__":
    main()
