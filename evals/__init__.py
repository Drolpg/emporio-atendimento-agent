"""Avaliação do agente contra o provedor real de LLM (T-15).

Fica fora da suíte padrão do `pytest` (`testpaths = ["tests"]`): roda só sob
`bash scripts/evals.sh`, `make evals` ou invocando `evals.runner` direto,
com a chave do provedor configurada.
"""

from __future__ import annotations
