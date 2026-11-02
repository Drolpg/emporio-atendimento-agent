"""Testes para carregamento de configuração e relógio da loja."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from emporio.config import (
    STORE_TZ,
    ConfigError,
    FixedClock,
    Settings,
    SystemClock,
    build_clock,
    load_settings,
    project_root,
)


class TestProjectRoot:
    """Testes para descoberta da raiz do projeto."""

    def test_project_root_returns_path(self):
        """project_root deve retornar um Path."""
        result = project_root()
        assert isinstance(result, Path)

    def test_project_root_contains_pyproject(self):
        """project_root deve conter pyproject.toml."""
        root = project_root()
        assert (root / "pyproject.toml").exists()


class TestLoadSettings:
    """Testes para carregamento de configuração."""

    def test_load_settings_with_empty_dict(self):
        """load_settings com dict vazio deve retornar padrões sem tocar em os.environ."""
        # Garantir que os.environ não tem as variáveis
        env = {}
        settings = load_settings(env)

        assert isinstance(settings, Settings)
        assert settings.llm_base_url == "https://api.groq.com/openai/v1"
        assert settings.llm_api_key == ""
        assert settings.llm_model == "openai/gpt-oss-120b"
        assert settings.llm_timeout_seconds == 30.0
        assert settings.store_today is None
        assert settings.history_db_path == project_root() / "data" / "history.sqlite3"
        assert settings.raw_data_dir == project_root() / "data" / "raw"
        assert settings.processed_data_dir == project_root() / "data" / "processed"

    def test_load_settings_respects_llm_base_url(self):
        """load_settings deve respeitar LLM_BASE_URL."""
        env = {"LLM_BASE_URL": "http://localhost:11434/v1"}
        settings = load_settings(env)
        assert settings.llm_base_url == "http://localhost:11434/v1"

    def test_load_settings_respects_llm_api_key(self):
        """load_settings deve respeitar LLM_API_KEY."""
        env = {"LLM_API_KEY": "sk-test"}
        settings = load_settings(env)
        assert settings.llm_api_key == "sk-test"

    def test_load_settings_respects_llm_model(self):
        """load_settings deve respeitar LLM_MODEL."""
        env = {"LLM_MODEL": "llama3.2:3b"}
        settings = load_settings(env)
        assert settings.llm_model == "llama3.2:3b"

    def test_load_settings_respects_llm_timeout_seconds(self):
        """load_settings deve respeitar LLM_TIMEOUT_SECONDS."""
        env = {"LLM_TIMEOUT_SECONDS": "60.5"}
        settings = load_settings(env)
        assert settings.llm_timeout_seconds == 60.5

    def test_load_settings_respects_history_db_path(self):
        """load_settings deve respeitar HISTORY_DB_PATH."""
        env = {"HISTORY_DB_PATH": "custom/history.db"}
        settings = load_settings(env)
        # Caminhos relativos são resolvidos a partir de project_root()
        assert settings.history_db_path == project_root() / "custom" / "history.db"

    def test_load_settings_history_db_path_absolute(self):
        """load_settings deve suportar caminhos absolutos para HISTORY_DB_PATH."""
        # Usar um caminho absoluto (a raiz do projeto é absoluta)
        abs_path = project_root() / "custom_history.db"
        env = {"HISTORY_DB_PATH": str(abs_path)}
        settings = load_settings(env)
        assert settings.history_db_path == abs_path

    def test_load_settings_store_today_none_when_empty(self):
        """load_settings com STORE_TODAY vazio deve resultar em store_today=None."""
        env = {"STORE_TODAY": ""}
        settings = load_settings(env)
        assert settings.store_today is None

    def test_load_settings_store_today_date_format(self):
        """STORE_TODAY no formato AAAA-MM-DD deve usar 10:00 em STORE_TZ."""
        env = {"STORE_TODAY": "2026-02-20"}
        settings = load_settings(env)

        assert settings.store_today is not None
        assert settings.store_today.year == 2026
        assert settings.store_today.month == 2
        assert settings.store_today.day == 20
        assert settings.store_today.hour == 10
        assert settings.store_today.minute == 0
        assert settings.store_today.second == 0
        assert settings.store_today.tzinfo == STORE_TZ

    def test_load_settings_store_today_datetime_format(self):
        """STORE_TODAY no formato AAAA-MM-DDTHH:MM deve respeitar a hora."""
        env = {"STORE_TODAY": "2026-02-20T19:30"}
        settings = load_settings(env)

        assert settings.store_today is not None
        assert settings.store_today.year == 2026
        assert settings.store_today.month == 2
        assert settings.store_today.day == 20
        assert settings.store_today.hour == 19
        assert settings.store_today.minute == 30
        assert settings.store_today.tzinfo == STORE_TZ

    def test_load_settings_store_today_with_utc_offset(self):
        """STORE_TODAY com offset UTC deve converter para STORE_TZ."""
        # 2026-02-20 19:30 UTC = 2026-02-20 15:30 Campo Grande (UTC-4)
        env = {"STORE_TODAY": "2026-02-20T19:30+00:00"}
        settings = load_settings(env)

        assert settings.store_today is not None
        # Verificar o instante (não a hora de parede)
        assert settings.store_today == datetime(2026, 2, 20, 15, 30, tzinfo=STORE_TZ)
        assert settings.store_today.hour == 15
        assert settings.store_today.minute == 30

    def test_load_settings_store_today_with_negative_offset(self):
        """STORE_TODAY com offset negativo deve converter para STORE_TZ."""
        # 2026-02-20 19:30 -03:00 = 2026-02-20 18:30 Campo Grande (UTC-4)
        env = {"STORE_TODAY": "2026-02-20T19:30-03:00"}
        settings = load_settings(env)

        assert settings.store_today is not None
        # Verificar o instante
        assert settings.store_today == datetime(2026, 2, 20, 18, 30, tzinfo=STORE_TZ)
        assert settings.store_today.hour == 18
        assert settings.store_today.minute == 30

    def test_load_settings_store_today_invalid_format(self):
        """STORE_TODAY em formato inválido deve gerar ConfigError."""
        env = {"STORE_TODAY": "20/02/2026"}
        with pytest.raises(ConfigError) as exc_info:
            load_settings(env)
        assert "AAAA-MM-DD" in str(exc_info.value)
        assert "20/02/2026" not in str(exc_info.value)

    def test_load_settings_llm_timeout_not_numeric(self):
        """LLM_TIMEOUT_SECONDS não numérico deve gerar ConfigError."""
        env = {"LLM_TIMEOUT_SECONDS": "abc"}
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_load_settings_llm_timeout_zero(self):
        """LLM_TIMEOUT_SECONDS=0 deve gerar ConfigError."""
        env = {"LLM_TIMEOUT_SECONDS": "0"}
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_load_settings_llm_timeout_negative(self):
        """LLM_TIMEOUT_SECONDS negativo deve gerar ConfigError."""
        env = {"LLM_TIMEOUT_SECONDS": "-1"}
        with pytest.raises(ConfigError):
            load_settings(env)


class TestSettingsRepr:
    """Testes para mascaramento de chave em Settings.__repr__."""

    def test_repr_masks_api_key(self):
        """repr(Settings) deve mascarar a chave de API."""
        env = {"LLM_API_KEY": "segredo-123"}
        settings = load_settings(env)
        repr_str = repr(settings)
        assert "segredo-123" not in repr_str
        assert "llm_api_key='***'" in repr_str

    def test_repr_shows_empty_key_when_absent(self):
        """repr(Settings) deve mostrar llm_api_key='' quando não houver chave."""
        env = {"LLM_API_KEY": ""}
        settings = load_settings(env)
        repr_str = repr(settings)
        assert "llm_api_key=''" in repr_str


class TestStoreTz:
    """Testes para a constante STORE_TZ."""

    def test_store_tz_is_campo_grande(self):
        """STORE_TZ deve ser America/Campo_Grande."""
        assert str(STORE_TZ) == "America/Campo_Grande"


class TestSystemClock:
    """Testes para o relógio do sistema."""

    def test_system_clock_now_has_tzinfo(self):
        """SystemClock.now() deve retornar datetime com tzinfo."""
        clock = SystemClock()
        now = clock.now()
        assert now.tzinfo is not None

    def test_system_clock_now_has_store_tz(self):
        """SystemClock.now() deve estar em STORE_TZ."""
        clock = SystemClock()
        now = clock.now()
        # Verificar o deslocamento de UTC para Campo Grande (UTC-4)
        offset = now.utcoffset()
        assert offset == timedelta(hours=-4)

    def test_system_clock_today(self):
        """SystemClock.today() deve ser a data de now()."""
        clock = SystemClock()
        now = clock.now()
        today = clock.today()
        assert today == now.date()


class TestFixedClock:
    """Testes para o relógio fixo."""

    def test_fixed_clock_with_naive_datetime_raises(self):
        """FixedClock com datetime ingênuo deve gerar ValueError."""
        naive = datetime(2026, 2, 20, 10, 0)
        with pytest.raises(ValueError):
            FixedClock(naive)

    def test_fixed_clock_with_aware_datetime(self):
        """FixedClock com datetime aware deve funcionar."""
        aware = datetime(2026, 2, 20, 10, 0, tzinfo=STORE_TZ)
        clock = FixedClock(aware)
        assert clock.moment == aware

    def test_fixed_clock_now_returns_moment(self):
        """FixedClock.now() deve retornar o moment."""
        moment = datetime(2026, 2, 20, 19, 30, tzinfo=STORE_TZ)
        clock = FixedClock(moment)
        assert clock.now() == moment

    def test_fixed_clock_today(self):
        """FixedClock.today() deve retornar a data de moment."""
        moment = datetime(2026, 2, 20, 19, 30, tzinfo=STORE_TZ)
        clock = FixedClock(moment)
        assert clock.today() == date(2026, 2, 20)

    def test_fixed_clock_normalizes_to_store_tz(self):
        """FixedClock normaliza datetime em outro fuso para STORE_TZ."""
        # Criar um datetime em UTC
        utc_dt = datetime(2026, 2, 20, 14, 0, tzinfo=ZoneInfo("UTC"))
        # Converter para STORE_TZ (UTC-4): 14:00 UTC = 10:00 Campo Grande
        campo_grande_dt = utc_dt.astimezone(STORE_TZ)

        clock = FixedClock(campo_grande_dt)
        # O relógio deve estar em STORE_TZ
        assert clock.moment.tzinfo == STORE_TZ


class TestBuildClock:
    """Testes para a construção do relógio."""

    def test_build_clock_with_store_today(self):
        """build_clock com store_today deve retornar FixedClock."""
        env = {"STORE_TODAY": "2026-02-20T10:00"}
        settings = load_settings(env)
        clock = build_clock(settings)

        assert isinstance(clock, FixedClock)

    def test_build_clock_without_store_today(self):
        """build_clock sem store_today deve retornar SystemClock."""
        env = {"STORE_TODAY": ""}
        settings = load_settings(env)
        clock = build_clock(settings)

        assert isinstance(clock, SystemClock)

    def test_build_clock_default(self):
        """build_clock sem variável STORE_TODAY deve retornar SystemClock."""
        env = {}
        settings = load_settings(env)
        clock = build_clock(settings)

        assert isinstance(clock, SystemClock)
