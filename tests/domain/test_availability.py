"""Musaitlik ve cakisma kurali testleri.

Kapsanan kritik senaryolar:

* Ayni odaya cakisan iki rezervasyon **engellenir**
* Bitisik rezervasyonlar (cikis gunu = giris gunu) **engellenmez**
* Bakim nedeniyle satisa kapali oda **satilamaz**
* Rezervasyon guncellenirken kayit **kendisiyle cakismaz**
* Oda atanmamis (bekleyen) satirlar envanteri bloke etmez
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import OverlappingReservationError, RoomOutOfServiceError
from app.domain.rules.availability import (
    Booking,
    RoomBlock,
    available_room_ids,
    check_availability,
    compute_occupancy,
    find_conflicting_bookings,
    free_gaps,
    is_room_available,
    summarize_day,
)
from app.domain.value_objects import DateRange

pytestmark = pytest.mark.unit

ODA = 101


def aralik(bas: int, bit: int) -> DateRange:
    """Agustos 2026 icin kisa yardimci."""
    return DateRange(date(2026, 8, bas), date(2026, 8, bit))


class TestCakismaEngelleme:
    def test_ayni_odaya_cakisan_rezervasyon_engellenir(self):
        """EN KRITIK KURAL: ayni oda ayni gece iki kez satilamaz."""
        mevcut = [Booking(ODA, aralik(10, 14), confirmation_number="RZV-0001")]

        with pytest.raises(OverlappingReservationError) as hata:
            check_availability(aralik(12, 16), room_id=ODA, existing_bookings=mevcut)

        assert "RZV-0001" in hata.value.user_message

    def test_tam_ayni_tarihler_engellenir(self):
        mevcut = [Booking(ODA, aralik(10, 14))]
        with pytest.raises(OverlappingReservationError):
            check_availability(aralik(10, 14), room_id=ODA, existing_bookings=mevcut)

    def test_icine_alan_rezervasyon_engellenir(self):
        mevcut = [Booking(ODA, aralik(12, 14))]
        with pytest.raises(OverlappingReservationError):
            check_availability(aralik(10, 20), room_id=ODA, existing_bookings=mevcut)

    def test_bitisik_rezervasyon_engellenmez(self):
        """Cikis gunu = giris gunu ise oda ayni gun yeniden satilabilir."""
        mevcut = [Booking(ODA, aralik(10, 12))]
        check_availability(aralik(12, 15), room_id=ODA, existing_bookings=mevcut)
        check_availability(aralik(7, 10), room_id=ODA, existing_bookings=mevcut)

    def test_farkli_oda_etkilenmez(self):
        mevcut = [Booking(ODA, aralik(10, 14))]
        check_availability(aralik(10, 14), room_id=102, existing_bookings=mevcut)

    def test_birden_fazla_cakisma_sayilir(self):
        mevcut = [
            Booking(ODA, aralik(10, 12)),
            Booking(ODA, aralik(13, 15)),
            Booking(ODA, aralik(16, 18)),
        ]
        cakisanlar = find_conflicting_bookings(aralik(11, 17), mevcut, room_id=ODA)
        assert len(cakisanlar) == 3


class TestGuncellemeSenaryosu:
    def test_kayit_kendisiyle_cakismaz(self):
        """Rezervasyon guncellenirken kendi kaydi cakisma uretmemeli.

        Bu dislama yapilmazsa hicbir rezervasyon duzenlenemez hale gelir.
        """
        mevcut = [Booking(ODA, aralik(10, 14), reservation_room_id=7)]
        check_availability(
            aralik(10, 15),
            room_id=ODA,
            existing_bookings=mevcut,
            exclude_reservation_room_id=7,
        )

    def test_dislama_yapilmazsa_cakisir(self):
        """Dislama unutulursa kayit kendini bloke eder - regresyon korumasi."""
        mevcut = [Booking(ODA, aralik(10, 14), reservation_room_id=7)]
        with pytest.raises(OverlappingReservationError):
            check_availability(aralik(10, 15), room_id=ODA, existing_bookings=mevcut)

    def test_baska_kayitla_cakisma_dislamaya_ragmen_yakalanir(self):
        mevcut = [
            Booking(ODA, aralik(10, 14), reservation_room_id=7),
            Booking(ODA, aralik(15, 18), reservation_room_id=9),
        ]
        with pytest.raises(OverlappingReservationError):
            check_availability(
                aralik(10, 16),
                room_id=ODA,
                existing_bookings=mevcut,
                exclude_reservation_room_id=7,
            )


class TestBakimBlokesi:
    def test_bakimdaki_oda_satilamaz(self):
        bloklar = [RoomBlock(ODA, aralik(10, 20), reason="Klima arizasi")]
        with pytest.raises(RoomOutOfServiceError):
            check_availability(aralik(12, 14), room_id=ODA, blocks=bloklar)

    def test_blok_disindaki_tarih_satilabilir(self):
        bloklar = [RoomBlock(ODA, aralik(10, 15), reason="Boya")]
        check_availability(aralik(15, 18), room_id=ODA, blocks=bloklar)

    def test_suresiz_blok_her_tarihi_kapatir(self):
        bloklar = [RoomBlock(ODA, None, reason="Kullanim disi")]
        with pytest.raises(RoomOutOfServiceError):
            check_availability(aralik(1, 3), room_id=ODA, blocks=bloklar)

    def test_blok_cakismadan_once_kontrol_edilir(self):
        """Hem blok hem cakisma varsa kullaniciya bakim mesaji gosterilmeli."""
        bloklar = [RoomBlock(ODA, aralik(10, 20))]
        mevcut = [Booking(ODA, aralik(11, 13))]
        with pytest.raises(RoomOutOfServiceError):
            check_availability(
                aralik(12, 14), room_id=ODA, existing_bookings=mevcut, blocks=bloklar
            )


class TestAtanmamisOda:
    def test_oda_atanmamis_satir_envanteri_bloke_etmez(self):
        """Oda tipi bazli rezervasyonlar fiziksel oda blokelemez."""
        mevcut = [Booking(room_id=None, date_range=aralik(10, 14))]  # type: ignore[arg-type]
        assert is_room_available(aralik(10, 14), room_id=ODA, existing_bookings=mevcut)


class TestMusaitOdaListesi:
    def test_musait_odalar_sirasi_korunarak_donulur(self):
        mevcut = [Booking(102, aralik(10, 14))]
        bloklar = [RoomBlock(103)]
        sonuc = available_room_ids(
            aralik(11, 13),
            candidate_room_ids=[101, 102, 103, 104],
            existing_bookings=mevcut,
            blocks=bloklar,
        )
        assert sonuc == [101, 104]

    def test_hicbiri_musait_degilse_bos_liste(self):
        mevcut = [Booking(101, aralik(10, 14)), Booking(102, aralik(10, 14))]
        assert (
            available_room_ids(
                aralik(11, 13), candidate_room_ids=[101, 102], existing_bookings=mevcut
            )
            == []
        )


class TestBosluklar:
    def test_bosluklar_dogru_hesaplanir(self):
        rezervasyonlar = [
            Booking(ODA, aralik(5, 8)),
            Booking(ODA, aralik(12, 15)),
        ]
        bosluklar = free_gaps(rezervasyonlar, window=aralik(1, 20), room_id=ODA)
        assert [(g.start.day, g.end.day) for g in bosluklar] == [(1, 5), (8, 12), (15, 20)]

    def test_tamamen_dolu_pencerede_bosluk_yok(self):
        rezervasyonlar = [Booking(ODA, aralik(1, 20))]
        assert free_gaps(rezervasyonlar, window=aralik(1, 20), room_id=ODA) == []

    def test_bos_odada_tum_pencere_bostur(self):
        bosluklar = free_gaps([], window=aralik(1, 10), room_id=ODA)
        assert len(bosluklar) == 1
        assert bosluklar[0].nights == 9


class TestDoluluk:
    def test_doluluk_orani_hesaplanir(self):
        rezervasyonlar = [Booking(101, aralik(10, 12)), Booking(102, aralik(10, 12))]
        istatistik = compute_occupancy(
            [date(2026, 8, 10)], bookings=rezervasyonlar, total_rooms=10
        )[0]
        assert istatistik.occupied_rooms == 2
        assert istatistik.occupancy_percent == 20.0
        assert istatistik.available_rooms == 8

    def test_arizali_odalar_paydadan_dusulur(self):
        """Bakimdaki oda isletmeyi haksiz yere dusuk dolulukta gostermemeli."""
        rezervasyonlar = [Booking(101, aralik(10, 12))]
        istatistik = compute_occupancy(
            [date(2026, 8, 10)],
            bookings=rezervasyonlar,
            total_rooms=10,
            out_of_order_by_day={date(2026, 8, 10): 5},
        )[0]
        assert istatistik.total_rooms == 5
        assert istatistik.occupancy_percent == 20.0

    def test_sifir_odada_bolme_hatasi_olmaz(self):
        istatistik = compute_occupancy([date(2026, 8, 10)], bookings=[], total_rooms=0)[0]
        assert istatistik.occupancy_rate == 0.0

    def test_cikis_gunu_dolu_sayilmaz(self):
        rezervasyonlar = [Booking(101, aralik(10, 12))]
        istatistikler = compute_occupancy(
            [date(2026, 8, 11), date(2026, 8, 12)], bookings=rezervasyonlar, total_rooms=10
        )
        assert istatistikler[0].occupied_rooms == 1
        assert istatistikler[1].occupied_rooms == 0


class TestGunlukOzet:
    def test_giris_cikis_ve_devam_edenler_ayrilir(self):
        rezervasyonlar = [
            Booking(101, aralik(10, 12)),  # giris
            Booking(102, aralik(8, 10)),  # cikis
            Booking(103, aralik(9, 14)),  # devam
        ]
        ozet = summarize_day(date(2026, 8, 10), rezervasyonlar)
        assert ozet.arrival_count == 1
        assert ozet.departure_count == 1
        assert len(ozet.stayovers) == 1
        assert ozet.in_house_count == 2
