"""Rezervasyon durum makinesi testleri.

Kritik senaryolar: iptal edilen rezervasyona islem yapilamamasi, no-show
sonrasi gecisler ve cikis yapmis rezervasyonun kapali olmasi.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import InvalidStateTransitionError
from app.domain.enums import ReservationStatus as RS
from app.domain.rules.reservation_state import (
    allowed_transitions,
    assert_transition_allowed,
    available_actions,
    can_transition,
    is_cancellable,
    is_modifiable,
    is_terminal,
)

pytestmark = pytest.mark.unit


class TestGecerliGecisler:
    @pytest.mark.parametrize(
        ("mevcut", "hedef"),
        [
            (RS.DRAFT, RS.CONFIRMED),
            (RS.DRAFT, RS.TENTATIVE),
            (RS.TENTATIVE, RS.CONFIRMED),
            (RS.CONFIRMED, RS.CHECKED_IN),
            (RS.CHECKED_IN, RS.CHECKED_OUT),
            (RS.CONFIRMED, RS.CANCELLED),
            (RS.CONFIRMED, RS.NO_SHOW),
            (RS.WAITLIST, RS.CONFIRMED),
        ],
    )
    def test_izin_verilen_gecisler(self, mevcut, hedef):
        assert can_transition(mevcut, hedef)
        assert_transition_allowed(mevcut, hedef)

    def test_ayni_duruma_gecis_islemsizdir(self):
        assert can_transition(RS.CONFIRMED, RS.CONFIRMED)


class TestGecersizGecisler:
    def test_iptal_edilen_rezervasyona_check_in_yapilamaz(self):
        """KRITIK: iptal edilmis rezervasyon yeniden canlandirilamaz."""
        assert not can_transition(RS.CANCELLED, RS.CHECKED_IN)
        with pytest.raises(InvalidStateTransitionError) as hata:
            assert_transition_allowed(RS.CANCELLED, RS.CHECKED_IN)
        assert "Iptal" in hata.value.user_message

    def test_cikis_yapmis_rezervasyon_kapalidir(self):
        assert allowed_transitions(RS.CHECKED_OUT) == frozenset()
        assert is_terminal(RS.CHECKED_OUT)
        with pytest.raises(InvalidStateTransitionError):
            assert_transition_allowed(RS.CHECKED_OUT, RS.CHECKED_IN)

    def test_taslak_dogrudan_check_in_yapilamaz(self):
        """Once onaylanmali; onaysiz rezervasyon oda blokelemez."""
        with pytest.raises(InvalidStateTransitionError):
            assert_transition_allowed(RS.DRAFT, RS.CHECKED_IN)

    def test_no_show_sonrasi_yalnizca_iptal(self):
        assert allowed_transitions(RS.NO_SHOW) == frozenset({RS.CANCELLED})
        with pytest.raises(InvalidStateTransitionError):
            assert_transition_allowed(RS.NO_SHOW, RS.CHECKED_IN)

    def test_hata_mesaji_secenekleri_listeler(self):
        with pytest.raises(InvalidStateTransitionError) as hata:
            assert_transition_allowed(RS.CONFIRMED, RS.CHECKED_OUT)
        assert "Giris Yapildi" in hata.value.user_message


class TestYardimcilar:
    def test_terminal_durumlar(self):
        assert is_terminal(RS.CANCELLED)
        assert is_terminal(RS.NO_SHOW)
        assert not is_terminal(RS.CONFIRMED)

    def test_degistirilebilirlik(self):
        assert is_modifiable(RS.CONFIRMED)
        assert not is_modifiable(RS.CHECKED_IN)
        assert not is_modifiable(RS.CANCELLED)

    def test_iptal_edilebilirlik(self):
        assert is_cancellable(RS.CONFIRMED)
        assert not is_cancellable(RS.CHECKED_OUT)

    def test_arayuz_dugme_durumlari(self):
        eylemler = available_actions(RS.CONFIRMED)
        assert eylemler["check_in"] is True
        assert eylemler["cancel"] is True
        assert eylemler["check_out"] is False

        eylemler = available_actions(RS.CHECKED_IN)
        assert eylemler["check_out"] is True
        assert eylemler["cancel"] is False

        eylemler = available_actions(RS.CANCELLED)
        assert not any(eylemler.values())
