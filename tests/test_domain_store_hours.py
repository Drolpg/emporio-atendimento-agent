"""Testes para o horario da loja e a proxima abertura."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from emporio.config import STORE_TZ
from emporio.domain.store_hours import StoreStatus, store_status


class TestNaiveDatetimeRejected:
    """Testes para a validacao de datetime aware."""

    def test_naive_datetime_raises(self):
        """Datetime ingenuo deve gerar ValueError."""
        naive = datetime(2026, 2, 20, 10, 0)
        with pytest.raises(ValueError):
            store_status(naive)


class TestWeekdayOpen:
    """Testes para o horario de segunda a sexta."""

    def test_monday_at_opening_is_open(self):
        """Segunda as 09:00 a loja esta aberta."""
        moment = datetime(2026, 2, 16, 9, 0, tzinfo=STORE_TZ)  # segunda-feira
        result = store_status(moment)
        assert isinstance(result, StoreStatus)
        assert result.is_open is True
        assert result.opens_at == time(9, 0)
        assert result.closes_at == time(18, 0)
        assert result.next_opening is None

    def test_monday_before_opening_is_closed(self):
        """Segunda as 08:00 a loja ainda nao abriu, reabre no mesmo dia."""
        moment = datetime(2026, 2, 16, 8, 0, tzinfo=STORE_TZ)
        result = store_status(moment)
        assert result.is_open is False
        assert result.opens_at == time(9, 0)
        assert result.closes_at == time(18, 0)
        assert result.next_opening == datetime(2026, 2, 16, 9, 0, tzinfo=STORE_TZ)

    def test_monday_at_closing_is_closed(self):
        """Segunda exatamente as 18:00 a loja ja fechou."""
        moment = datetime(2026, 2, 16, 18, 0, tzinfo=STORE_TZ)
        result = store_status(moment)
        assert result.is_open is False

    def test_friday_after_closing_next_opening_is_saturday(self):
        """Sexta 19:00 fechada, reabre sabado 09:00."""
        moment = datetime(2026, 2, 20, 19, 0, tzinfo=STORE_TZ)  # sexta-feira
        result = store_status(moment)
        assert result.is_open is False
        assert result.next_opening == datetime(2026, 2, 21, 9, 0, tzinfo=STORE_TZ)


class TestSaturday:
    """Testes para o horario de sabado."""

    def test_saturday_at_opening_is_open(self):
        """Sabado as 09:00 a loja esta aberta."""
        moment = datetime(2026, 2, 21, 9, 0, tzinfo=STORE_TZ)  # sabado
        result = store_status(moment)
        assert result.is_open is True
        assert result.opens_at == time(9, 0)
        assert result.closes_at == time(13, 0)

    def test_saturday_before_opening_reopens_same_day(self):
        """Sabado as 08:00 fechada, reabre no mesmo dia as 09:00."""
        moment = datetime(2026, 2, 21, 8, 0, tzinfo=STORE_TZ)
        result = store_status(moment)
        assert result.is_open is False
        assert result.next_opening == datetime(2026, 2, 21, 9, 0, tzinfo=STORE_TZ)

    def test_saturday_at_closing_is_closed(self):
        """Sabado exatamente as 13:00 a loja ja fechou."""
        moment = datetime(2026, 2, 21, 13, 0, tzinfo=STORE_TZ)
        result = store_status(moment)
        assert result.is_open is False

    def test_saturday_after_closing_next_opening_is_monday(self):
        """Sabado 14:00 fechada, reabre segunda 09:00 (domingo fechado)."""
        moment = datetime(2026, 2, 21, 14, 0, tzinfo=STORE_TZ)
        result = store_status(moment)
        assert result.is_open is False
        assert result.next_opening == datetime(2026, 2, 23, 9, 0, tzinfo=STORE_TZ)


class TestSunday:
    """Testes para o domingo (fechado o dia inteiro)."""

    def test_sunday_is_always_closed(self):
        """Domingo a loja esta fechada o dia inteiro, sem horario definido."""
        moment = datetime(2026, 2, 22, 12, 0, tzinfo=STORE_TZ)  # domingo
        result = store_status(moment)
        assert result.is_open is False
        assert result.opens_at is None
        assert result.closes_at is None

    def test_sunday_next_opening_is_monday(self):
        """Qualquer hora de domingo reabre segunda 09:00."""
        moment = datetime(2026, 2, 22, 23, 0, tzinfo=STORE_TZ)
        result = store_status(moment)
        assert result.next_opening == datetime(2026, 2, 23, 9, 0, tzinfo=STORE_TZ)


class TestTimezoneNormalization:
    """Testes para normalizacao de fuso horario."""

    def test_normalizes_other_timezone_to_store_tz(self):
        """Um moment em outro fuso e normalizado para STORE_TZ antes de decidir."""
        from zoneinfo import ZoneInfo

        # 2026-02-16 13:00 UTC = 2026-02-16 09:00 Campo Grande (UTC-4)
        moment = datetime(2026, 2, 16, 13, 0, tzinfo=ZoneInfo("UTC"))
        result = store_status(moment)
        assert result.is_open is True
