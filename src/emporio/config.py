"""Carregamento de configuração, relógio injetável e contrato de ferramentas."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Final, Protocol
from zoneinfo import ZoneInfo

__all__ = [
    "STORE_TZ",
    "ConfigError",
    "Settings",
    "Clock",
    "SystemClock",
    "FixedClock",
    "project_root",
    "load_settings",
    "build_clock",
]


# Fuso horário da loja
STORE_TZ: Final[ZoneInfo] = ZoneInfo("America/Campo_Grande")


class ConfigError(Exception):
    """Erro na configuração do agente."""

    pass


@dataclass(frozen=True)
class Settings:
    """Configuração do agente."""

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float
    store_today: datetime | None
    history_db_path: Path
    raw_data_dir: Path
    processed_data_dir: Path

    def __repr__(self) -> str:
        """Máscara a chave de API na representação."""
        api_key_repr = "***" if self.llm_api_key else ""
        return (
            f"Settings("
            f"llm_base_url={self.llm_base_url!r}, "
            f"llm_api_key={api_key_repr!r}, "
            f"llm_model={self.llm_model!r}, "
            f"llm_timeout_seconds={self.llm_timeout_seconds!r}, "
            f"store_today={self.store_today!r}, "
            f"history_db_path={self.history_db_path!r}, "
            f"raw_data_dir={self.raw_data_dir!r}, "
            f"processed_data_dir={self.processed_data_dir!r})"
        )


def project_root() -> Path:
    """Retorna a raiz do projeto."""
    # Procurar pela raiz indo para cima até encontrar pyproject.toml
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Se não encontrar, retornar o pai de src/emporio
    return Path(__file__).resolve().parent.parent.parent


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Carrega a configuração a partir das variáveis de ambiente.

    Args:
        env: Mapeamento de variáveis de ambiente. Padrão: os.environ.

    Returns:
        Settings com as configurações carregadas.

    Raises:
        ConfigError: Se houver erro na configuração.
    """
    if env is None:
        env = os.environ

    root = project_root()

    # Padrões
    llm_base_url = env.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    llm_api_key = env.get("LLM_API_KEY", "")
    llm_model = env.get("LLM_MODEL", "openai/gpt-oss-120b")

    # LLM_TIMEOUT_SECONDS
    timeout_str = env.get("LLM_TIMEOUT_SECONDS", "30.0")
    try:
        llm_timeout_seconds = float(timeout_str)
    except ValueError as e:
        raise ConfigError(
            f"LLM_TIMEOUT_SECONDS deve ser um número, recebido: {timeout_str!r}"
        ) from e

    if llm_timeout_seconds <= 0:
        raise ConfigError("LLM_TIMEOUT_SECONDS deve ser maior que 0")

    # STORE_TODAY
    store_today_str = env.get("STORE_TODAY", "").strip()
    store_today: datetime | None = None

    if store_today_str:
        try:
            # Tentar formato AAAA-MM-DD
            if len(store_today_str) == 10:
                dt = datetime.strptime(store_today_str, "%Y-%m-%d")
                # Adicionar hora 10:00 em STORE_TZ
                store_today = dt.replace(hour=10, minute=0, second=0, tzinfo=STORE_TZ)
            # Tentar formato AAAA-MM-DDTHH:MM
            elif "T" in store_today_str:
                dt = datetime.fromisoformat(store_today_str)
                # Normalizar para STORE_TZ
                store_today = dt.replace(tzinfo=STORE_TZ)
            else:
                raise ValueError(f"Formato inválido: {store_today_str}")
        except (ValueError, AttributeError) as e:
            raise ConfigError(
                "STORE_TODAY deve estar em formato AAAA-MM-DD ou AAAA-MM-DDTHH:MM"
            ) from e

    # HISTORY_DB_PATH
    history_db_path_str = env.get("HISTORY_DB_PATH", "data/history.sqlite3")
    history_db_path = Path(history_db_path_str)
    if not history_db_path.is_absolute():
        history_db_path = root / history_db_path

    # Diretórios de dados
    raw_data_dir = root / "data" / "raw"
    processed_data_dir = root / "data" / "processed"

    return Settings(
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_timeout_seconds=llm_timeout_seconds,
        store_today=store_today,
        history_db_path=history_db_path,
        raw_data_dir=raw_data_dir,
        processed_data_dir=processed_data_dir,
    )


class Clock(Protocol):
    """Protocolo para relógio da loja."""

    def now(self) -> datetime:
        """Retorna a data e hora atual em STORE_TZ."""
        ...

    def today(self) -> date:
        """Retorna a data atual."""
        ...


@dataclass(frozen=True)
class SystemClock:
    """Relógio que retorna a data/hora real do sistema."""

    def now(self) -> datetime:
        """Retorna a data e hora atual em STORE_TZ."""
        return datetime.now(STORE_TZ)

    def today(self) -> date:
        """Retorna a data atual."""
        return self.now().date()


@dataclass(frozen=True)
class FixedClock:
    """Relógio que retorna uma data/hora fixa."""

    moment: datetime

    def __post_init__(self) -> None:
        """Valida que moment é aware e está em STORE_TZ."""
        if self.moment.tzinfo is None:
            raise ValueError("moment deve ter tzinfo (datetime aware)")
        # Normalizar para STORE_TZ se estiver em outro fuso
        if self.moment.tzinfo != STORE_TZ:
            normalized = self.moment.astimezone(STORE_TZ)
            # Usar object.__setattr__ porque a dataclass é frozen
            object.__setattr__(self, "moment", normalized)

    def now(self) -> datetime:
        """Retorna o moment fixo."""
        return self.moment

    def today(self) -> date:
        """Retorna a data do moment."""
        return self.moment.date()


def build_clock(settings: Settings) -> Clock:
    """Constrói o relógio baseado nas configurações.

    Args:
        settings: Configurações carregadas.

    Returns:
        FixedClock se store_today estiver definido, senão SystemClock.
    """
    if settings.store_today is not None:
        return FixedClock(settings.store_today)
    return SystemClock()
