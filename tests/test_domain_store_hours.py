"""Testes para o horario da loja e a proxima abertura."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from emporio.config import STORE_TZ
from emporio.domain.store_hours import StoreStatus, add_business_hours, store_status


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


class TestAddBusinessHoursNaiveAndNegative:
    """Validacao de entrada de `add_business_hours`."""

    def test_naive_datetime_raises(self):
        """Datetime ingenuo deve gerar ValueError."""
        naive = datetime(2026, 2, 16, 9, 0)
        with pytest.raises(ValueError):
            add_business_hours(naive, 1)

    def test_negative_hours_raises(self):
        """Horas negativas nao tem caso de uso neste produto; gera ValueError."""
        moment = datetime(2026, 2, 16, 9, 0, tzinfo=STORE_TZ)
        with pytest.raises(ValueError):
            add_business_hours(moment, -1)


class TestAddBusinessHoursEdgeCases:
    """Casos de borda do avanco de horas de expediente (prazo de 24h uteis, RF-10)."""

    def test_zero_hours_dentro_do_expediente_fica_no_mesmo_momento(self):
        """Segunda 09:00 + 0h = segunda 09:00."""
        moment = datetime(2026, 2, 16, 9, 0, tzinfo=STORE_TZ)  # segunda-feira
        result = add_business_hours(moment, 0)
        assert result == moment

    def test_segunda_09h_mais_9h_fecha_no_mesmo_dia(self):
        """Segunda 09:00 + 9h = segunda 18:00 (um dia inteiro de expediente)."""
        moment = datetime(2026, 2, 16, 9, 0, tzinfo=STORE_TZ)
        result = add_business_hours(moment, 9)
        assert result == datetime(2026, 2, 16, 18, 0, tzinfo=STORE_TZ)

    def test_segunda_17h_mais_2h_vira_terca_10h(self):
        """Segunda 17:00 + 2h: 1h fecha a segunda, 1h abre terca = terca 10:00."""
        moment = datetime(2026, 2, 16, 17, 0, tzinfo=STORE_TZ)
        result = add_business_hours(moment, 2)
        assert result == datetime(2026, 2, 17, 10, 0, tzinfo=STORE_TZ)

    def test_sabado_12h_mais_2h_pula_domingo_vira_segunda_10h(self):
        """Sabado 12:00 + 2h: 1h fecha o sabado, domingo fechado, 1h abre segunda = segunda 10:00."""
        moment = datetime(2026, 2, 21, 12, 0, tzinfo=STORE_TZ)  # sabado
        result = add_business_hours(moment, 2)
        assert result == datetime(2026, 2, 23, 10, 0, tzinfo=STORE_TZ)  # segunda

    def test_domingo_10h_mais_1h_conta_so_a_partir_da_abertura_de_segunda(self):
        """Domingo fechado: a contagem comeca na proxima abertura (segunda 09:00)."""
        moment = datetime(2026, 2, 22, 10, 0, tzinfo=STORE_TZ)  # domingo
        result = add_business_hours(moment, 1)
        assert result == datetime(2026, 2, 23, 10, 0, tzinfo=STORE_TZ)  # segunda 10:00

    def test_sexta_17h_mais_24h_vira_quarta_10h(self):
        """Sexta 17:00 + 24h uteis: 1h (sex) + 4h (sab) + 9h (seg) + 9h (ter) + 1h (qua) = 24h.

        Domingo fica fechado, entao a 24a hora cai na quarta-feira as 10:00.
        """
        moment = datetime(2026, 2, 20, 17, 0, tzinfo=STORE_TZ)  # sexta-feira
        result = add_business_hours(moment, 24)
        assert result == datetime(2026, 2, 25, 10, 0, tzinfo=STORE_TZ)  # quarta-feira
