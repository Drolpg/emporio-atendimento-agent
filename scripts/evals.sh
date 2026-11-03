#!/bin/bash
set -euo pipefail

# T-15: roda os 12 cenarios de referencia contra o provedor real de LLM.
# Precisa de LLM_API_KEY configurada no .env; sem chave, sai com codigo 2
# sem tentar nenhuma chamada de rede. Aceita --only e --json (ver
# evals/README.md).
uv run python -m evals.runner "$@"
