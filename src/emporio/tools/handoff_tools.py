"""Ferramenta de encaminhamento humano (RF-10): reclamacao, exclusao de dados pela
LGPD, negociacao de preco e caso sem resposta nas fontes.

O numero de protocolo (`EM-AAAAMMDD-NNNN`) usa a data do relogio da loja e um
sequencial de 4 digitos por dia, que o `HandoffSink` injetado controla -
determinístico com `FixedClock`, para os testes poderem fixar o valor. O
prazo de retorno de 24 horas uteis vem de `add_business_hours`, nunca contado
no prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from emporio.config import Clock
from emporio.domain.store_hours import add_business_hours
from emporio.tools.base import JsonDict, ToolSpec, tool_error

__all__ = [
    "HandoffSink",
    "InMemoryHandoffSink",
    "JsonlHandoffSink",
    "build_handoff_tools",
]

_REASONS: tuple[str, ...] = (
    "complaint",
    "data_deletion",
    "price_negotiation",
    "unanswered",
    "other",
)

_REASON_LABELS: dict[str, str] = {
    "complaint": "reclamação",
    "data_deletion": "exclusão de dados (LGPD)",
    "price_negotiation": "negociação de preço",
    "unanswered": "pergunta sem resposta nas fontes disponíveis",
    "other": "outro assunto",
}


class HandoffSink(Protocol):
    """Destino que grava o encaminhamento e numera o protocolo do dia."""

    def record(self, payload: JsonDict) -> str:
        """Grava `payload` e devolve o numero de protocolo (`EM-AAAAMMDD-NNNN`)."""
        ...


def _protocol_number(day_key: str, sequence: int) -> str:
    """Monta o numero de protocolo a partir da chave do dia (AAAAMMDD) e do sequencial."""
    return f"EM-{day_key}-{sequence:04d}"


@dataclass
class InMemoryHandoffSink:
    """Sink em memoria, para testes: guarda cada encaminhamento registrado."""

    recorded: list[JsonDict] = field(default_factory=list)
    _sequence_by_day: dict[str, int] = field(default_factory=dict, repr=False)

    def record(self, payload: JsonDict) -> str:
        day_key = payload["day_key"]
        sequence = self._sequence_by_day.get(day_key, 0) + 1
        self._sequence_by_day[day_key] = sequence
        protocol = _protocol_number(day_key, sequence)

        entry = dict(payload)
        entry["protocol"] = protocol
        self.recorded.append(entry)
        return protocol


@dataclass
class JsonlHandoffSink:
    """Sink em arquivo JSONL, padrao de producao (`data/handoffs.jsonl`)."""

    path: Path

    def record(self, payload: JsonDict) -> str:
        day_key = payload["day_key"]
        sequence = self._next_sequence(day_key)
        protocol = _protocol_number(day_key, sequence)

        entry = dict(payload)
        entry["protocol"] = protocol

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return protocol

    def _next_sequence(self, day_key: str) -> int:
        """Le o arquivo para descobrir quantos encaminhamentos o dia `day_key` ja tem."""
        if not self.path.exists():
            return 1
        count = 0
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                record = json.loads(stripped)
                if record.get("day_key") == day_key:
                    count += 1
        return count + 1


def build_handoff_tools(clock: Clock, sink: HandoffSink) -> tuple[ToolSpec, ...]:
    """Monta a ferramenta `create_handoff`."""

    def handler(reason: str, summary: str, contact: str | None = None) -> JsonDict:
        if reason not in _REASONS:
            valid = ", ".join(_REASONS)
            return tool_error(
                "invalid_arguments", f"Motivo '{reason}' inválido. Motivos válidos: {valid}."
            )
        if not summary.strip():
            return tool_error(
                "invalid_arguments", "Informe um resumo do caso para registrar o encaminhamento."
            )

        now = clock.now()
        payload: JsonDict = {
            "day_key": now.strftime("%Y%m%d"),
            "created_at": now.isoformat(),
            "reason": reason,
            "summary": summary.strip(),
            "contact": contact,
        }
        protocol = sink.record(payload)

        deadline = add_business_hours(now, 24)
        return {
            "protocol": protocol,
            "reason": reason,
            "reason_label": _REASON_LABELS[reason],
            "response_deadline_iso": deadline.isoformat(),
            "message": (
                f"Encaminhamento registrado com o protocolo {protocol}. Nossa equipe "
                f"retorna em até 24 horas úteis, até {deadline.strftime('%d/%m')} às "
                f"{deadline.strftime('%H:%M')}."
            ),
        }

    spec = ToolSpec(
        name="create_handoff",
        description=(
            "Registra um encaminhamento para a equipe humana quando o agente não pode "
            "resolver sozinho: reclamação, exclusão de dados pela LGPD, negociação de "
            "preço ou pergunta sem resposta nas fontes. Devolve o protocolo e o prazo "
            "de retorno."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": list(_REASONS),
                    "description": (
                        "Motivo do encaminhamento: complaint (reclamação), data_deletion "
                        "(cliente pede para excluir seus dados pessoais), price_negotiation "
                        "(cliente quer negociar o preço), unanswered (pergunta sem resposta "
                        "em nenhuma fonte disponível) ou other (outro assunto)."
                    ),
                },
                "summary": {
                    "type": "string",
                    "description": "Resumo curto do caso, para a equipe entender o contexto",
                },
                "contact": {
                    "type": "string",
                    "description": (
                        "Contato do cliente para retorno (e-mail ou telefone), quando informado"
                    ),
                },
            },
            "required": ["reason", "summary"],
        },
        handler=handler,
    )
    return (spec,)
