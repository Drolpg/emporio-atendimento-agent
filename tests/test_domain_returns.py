"""Testes para a elegibilidade de troca, devolucao e garantia."""

from __future__ import annotations

from datetime import date

from emporio.domain.returns import ReturnKind, ReturnWindow, return_windows


class TestReturnWindowsOrder:
    """Testes para a ordem e a composicao do retorno."""

    def test_returns_four_windows_in_order(self):
        """return_windows devolve as quatro modalidades, na ordem da tabela."""
        windows = return_windows(
            order_date=date(2026, 2, 1),
            received_date=date(2026, 2, 5),
            today=date(2026, 2, 6),
        )
        assert len(windows) == 4
        assert [w.kind for w in windows] == [
            ReturnKind.WITHDRAWAL,
            ReturnKind.PREFERENCE,
            ReturnKind.DEFECT,
            ReturnKind.LEGAL_WARRANTY,
        ]
        for window in windows:
            assert isinstance(window, ReturnWindow)


class TestDeadlineDays:
    """Testes para os prazos de cada modalidade."""

    def test_deadline_days_per_kind(self):
        """Cada modalidade tem o prazo correto em dias corridos."""
        windows = return_windows(
            order_date=date(2026, 2, 1),
            received_date=date(2026, 2, 5),
            today=date(2026, 2, 6),
        )
        by_kind = {w.kind: w for w in windows}
        assert by_kind[ReturnKind.WITHDRAWAL].deadline_days == 7
        assert by_kind[ReturnKind.PREFERENCE].deadline_days == 7
        assert by_kind[ReturnKind.DEFECT].deadline_days == 30
        assert by_kind[ReturnKind.LEGAL_WARRANTY].deadline_days == 90


class TestReferenceDate:
    """Testes para a data de referencia de cada modalidade."""

    def test_withdrawal_preference_and_warranty_count_from_received(self):
        """Arrependimento, preferencia e garantia legal contam do recebimento."""
        windows = return_windows(
            order_date=date(2026, 2, 1),
            received_date=date(2026, 2, 5),
            today=date(2026, 2, 6),
        )
        by_kind = {w.kind: w for w in windows}
        assert by_kind[ReturnKind.WITHDRAWAL].reference_date == date(2026, 2, 5)
        assert by_kind[ReturnKind.PREFERENCE].reference_date == date(2026, 2, 5)
        assert by_kind[ReturnKind.LEGAL_WARRANTY].reference_date == date(2026, 2, 5)

    def test_defect_counts_from_order_date(self):
        """Troca por defeito conta da data da compra, nao do recebimento."""
        windows = return_windows(
            order_date=date(2026, 2, 1),
            received_date=date(2026, 2, 5),
            today=date(2026, 2, 6),
        )
        by_kind = {w.kind: w for w in windows}
        assert by_kind[ReturnKind.DEFECT].reference_date == date(2026, 2, 1)


class TestWithdrawalEdges:
    """Testes de borda para o prazo de arrependimento (7 dias do recebimento)."""

    def test_open_with_zero_days_remaining(self):
        """Recebimento 2026-02-17, hoje 2026-02-24: aberto com 0 dias restantes."""
        windows = return_windows(
            order_date=date(2026, 2, 10),
            received_date=date(2026, 2, 17),
            today=date(2026, 2, 24),
        )
        withdrawal = windows[0]
        assert withdrawal.kind == ReturnKind.WITHDRAWAL
        assert withdrawal.deadline == date(2026, 2, 24)
        assert withdrawal.is_open is True
        assert withdrawal.days_remaining == 0
        assert withdrawal.days_expired is None
        assert withdrawal.not_started is False

    def test_expired_one_day_after(self):
        """Mesmo recebimento, hoje 2026-02-25: vencido ha 1 dia."""
        windows = return_windows(
            order_date=date(2026, 2, 10),
            received_date=date(2026, 2, 17),
            today=date(2026, 2, 25),
        )
        withdrawal = windows[0]
        assert withdrawal.is_open is False
        assert withdrawal.days_remaining is None
        assert withdrawal.days_expired == 1


class TestDefectEdges:
    """Testes de borda para o prazo de troca por defeito (30 dias da compra)."""

    def test_open_with_zero_days_remaining(self):
        """Compra 2026-02-03, hoje 2026-03-05: aberto com 0 dias restantes."""
        windows = return_windows(
            order_date=date(2026, 2, 3),
            received_date=date(2026, 2, 10),
            today=date(2026, 3, 5),
        )
        defect = windows[2]
        assert defect.kind == ReturnKind.DEFECT
        assert defect.deadline == date(2026, 3, 5)
        assert defect.is_open is True
        assert defect.days_remaining == 0

    def test_expired_one_day_after(self):
        """Mesma compra, hoje 2026-03-06: vencido."""
        windows = return_windows(
            order_date=date(2026, 2, 3),
            received_date=date(2026, 2, 10),
            today=date(2026, 3, 6),
        )
        defect = windows[2]
        assert defect.is_open is False
        assert defect.days_expired == 1


class TestNotDelivered:
    """Testes para pedido nao entregue (received_date is None)."""

    def test_windows_that_count_from_received_are_not_started(self):
        """Pedido 8: compra 2026-02-15, nao entregue."""
        windows = return_windows(
            order_date=date(2026, 2, 15),
            received_date=None,
            today=date(2026, 2, 20),
        )
        by_kind = {w.kind: w for w in windows}

        for kind in (ReturnKind.WITHDRAWAL, ReturnKind.PREFERENCE, ReturnKind.LEGAL_WARRANTY):
            window = by_kind[kind]
            assert window.not_started is True
            assert window.reference_date is None
            assert window.deadline is None
            assert window.is_open is False
            assert window.days_remaining is None
            assert window.days_expired is None

    def test_defect_still_valid_when_not_delivered(self):
        """Defeito continua valendo porque conta da compra, nao do recebimento."""
        windows = return_windows(
            order_date=date(2026, 2, 15),
            received_date=None,
            today=date(2026, 2, 20),
        )
        defect = windows[2]
        assert defect.not_started is False
        assert defect.reference_date == date(2026, 2, 15)
        assert defect.deadline == date(2026, 3, 17)
        assert defect.is_open is True
        assert defect.days_remaining == 25

    def test_defect_expired_when_not_delivered_past_30_days(self):
        """Defeito vence mesmo sem entrega, se passarem os 30 dias da compra."""
        windows = return_windows(
            order_date=date(2026, 2, 15),
            received_date=None,
            today=date(2026, 3, 20),
        )
        defect = windows[2]
        assert defect.not_started is False
        assert defect.is_open is False
        assert defect.days_expired == 3
