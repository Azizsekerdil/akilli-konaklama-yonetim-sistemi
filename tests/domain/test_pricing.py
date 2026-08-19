"""Fiyatlandirma kurali testleri: sezon gecisi, ekstra kisi, vergi, iptal ucreti."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ValidationError
from app.domain.rules.pricing import (
    RateRule,
    calculate_cancellation_fee,
    calculate_early_late_fee,
    calculate_stay_price,
    select_rate_for_day,
)
from app.domain.value_objects import DateRange, Money

pytestmark = pytest.mark.unit


def aralik(bas_ay: int, bas_gun: int, bit_ay: int, bit_gun: int) -> DateRange:
    return DateRange(date(2026, bas_ay, bas_gun), date(2026, bit_ay, bit_gun))


class TestTemelFiyat:
    def test_taban_fiyat_gece_sayisiyla_carpilir(self):
        dokum = calculate_stay_price(aralik(8, 10, 8, 13), base_rate="1000")
        assert dokum.night_count == 3
        assert dokum.total.amount == Decimal("3000.00")

    def test_her_gece_ayri_kalem_olarak_dokumlenir(self):
        dokum = calculate_stay_price(aralik(8, 10, 8, 13), base_rate="1000")
        assert [n.day.day for n in dokum.nights] == [10, 11, 12]
        assert all(n.source == "Taban fiyat" for n in dokum.nights)

    def test_ortalama_gecelik_ucret(self):
        dokum = calculate_stay_price(aralik(8, 10, 8, 14), base_rate="800")
        assert dokum.average_nightly_rate.amount == Decimal("800.00")


class TestSezonGecisi:
    def test_sezon_gecisi_gece_gece_hesaplanir(self):
        """30 Haziran - 2 Temmuz: iki farkli sezon fiyati uygulanmali.

        Sabit ucreti gece sayisiyla carpan bir hesap burada yanlis sonuc verir.
        """
        kurallar = [
            RateRule(
                amount=Decimal("1000"),
                valid_from=date(2026, 6, 1),
                valid_to=date(2026, 6, 30),
                season_name="Dusuk Sezon",
            ),
            RateRule(
                amount=Decimal("2500"),
                valid_from=date(2026, 7, 1),
                valid_to=date(2026, 8, 31),
                season_name="Yuksek Sezon",
            ),
        ]
        dokum = calculate_stay_price(DateRange(date(2026, 6, 30), date(2026, 7, 2)), rules=kurallar)
        assert dokum.night_count == 2
        assert dokum.nights[0].amount.amount == Decimal("1000.00")
        assert dokum.nights[1].amount.amount == Decimal("2500.00")
        assert dokum.total.amount == Decimal("3500.00")

    def test_kural_yoksa_taban_fiyata_duser(self):
        kurallar = [
            RateRule(
                amount=Decimal("2000"),
                valid_from=date(2026, 7, 1),
                valid_to=date(2026, 7, 31),
            )
        ]
        dokum = calculate_stay_price(aralik(8, 10, 8, 12), rules=kurallar, base_rate="900")
        assert dokum.total.amount == Decimal("1800.00")

    def test_hafta_sonu_farkli_fiyat(self):
        """weekday_mask ile yalnizca Cuma-Cumartesi farkli fiyat."""
        hafta_ici = RateRule(
            amount=Decimal("1000"),
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31),
            weekday_mask=0b0011111,  # Pzt-Cum
        )
        hafta_sonu = RateRule(
            amount=Decimal("1500"),
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31),
            weekday_mask=0b1100000,  # Cmt-Paz
            priority=1,
        )
        # 2026-08-14 Cuma, 15 Cumartesi, 16 Pazar
        dokum = calculate_stay_price(
            DateRange(date(2026, 8, 14), date(2026, 8, 17)),
            rules=[hafta_ici, hafta_sonu],
        )
        tutarlar = [n.amount.amount for n in dokum.nights]
        assert tutarlar == [Decimal("1000.00"), Decimal("1500.00"), Decimal("1500.00")]

    def test_oncelikli_kural_kazanir(self):
        genel = RateRule(
            amount=Decimal("1000"),
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31),
            season_name="Sezon",
            priority=0,
        )
        bayram = RateRule(
            amount=Decimal("3000"),
            valid_from=date(2026, 8, 10),
            valid_to=date(2026, 8, 12),
            season_name="Bayram",
            priority=10,
        )
        secilen = select_rate_for_day(date(2026, 8, 11), [genel, bayram])
        assert secilen is not None
        assert secilen.season_name == "Bayram"

    def test_esit_oncelikte_dar_donem_kazanir(self):
        genis = RateRule(
            amount=Decimal("1000"),
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31),
            season_name="Genis",
        )
        dar = RateRule(
            amount=Decimal("2000"),
            valid_from=date(2026, 8, 10),
            valid_to=date(2026, 8, 11),
            season_name="Dar",
        )
        secilen = select_rate_for_day(date(2026, 8, 10), [genis, dar])
        assert secilen is not None
        assert secilen.season_name == "Dar"

    def test_min_gece_kurali_uymayan_tarife_atlanir(self):
        uzun_konaklama = RateRule(
            amount=Decimal("700"),
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31),
            min_nights=7,
            priority=5,
        )
        dokum = calculate_stay_price(aralik(8, 10, 8, 12), rules=[uzun_konaklama], base_rate="1000")
        assert dokum.total.amount == Decimal("2000.00")


class TestEkstraKisiVeIndirim:
    def test_ekstra_yetiskin_her_gece_ucretlendirilir(self):
        dokum = calculate_stay_price(
            aralik(8, 10, 8, 13),
            base_rate="1000",
            adults=3,
            base_occupancy=2,
            extra_adult_rate="250",
        )
        assert dokum.extra_adult_total.amount == Decimal("750.00")
        assert dokum.total.amount == Decimal("3750.00")

    def test_temel_kapasite_icinde_ekstra_ucret_yok(self):
        dokum = calculate_stay_price(
            aralik(8, 10, 8, 13),
            base_rate="1000",
            adults=2,
            base_occupancy=2,
            extra_adult_rate="250",
        )
        assert dokum.extra_adult_total.is_zero

    def test_indirim_uygulanir(self):
        dokum = calculate_stay_price(aralik(8, 10, 8, 12), base_rate="1000", discount_percent="10")
        assert dokum.discount_amount.amount == Decimal("200.00")
        assert dokum.total.amount == Decimal("1800.00")

    def test_gecersiz_indirim_orani_reddedilir(self):
        with pytest.raises(ValidationError):
            calculate_stay_price(aralik(8, 10, 8, 12), base_rate="1000", discount_percent="150")


class TestVergi:
    def test_vergi_dahil_fiyatta_toplam_degismez(self):
        """Turkiye'de fiyatlar vergi dahil ilan edilir; uzerine eklenmez."""
        dokum = calculate_stay_price(
            aralik(8, 10, 8, 13),
            base_rate="1000",
            tax_rate_percent="10",
            tax_included_in_rate=True,
        )
        assert dokum.total.amount == Decimal("3000.00")
        assert dokum.tax_amount.amount == Decimal("272.73")

    def test_vergi_haric_fiyatta_vergi_eklenir(self):
        dokum = calculate_stay_price(
            aralik(8, 10, 8, 13),
            base_rate="1000",
            tax_rate_percent="10",
            tax_included_in_rate=False,
        )
        assert dokum.tax_amount.amount == Decimal("300.00")
        assert dokum.total.amount == Decimal("3300.00")


class TestIptalUcreti:
    def test_ucretsiz_iptal_penceresinde_ucret_yok(self):
        ucret = calculate_cancellation_fee(Money.of("2000"), hours_before_arrival=48)
        assert ucret.is_zero

    def test_pencere_disinda_ceza_uygulanir(self):
        ucret = calculate_cancellation_fee(
            Money.of("2000"), hours_before_arrival=5, cancellation_fee_percent="50"
        )
        assert ucret.amount == Decimal("1000.00")

    def test_iade_edilemez_tarifede_tam_tutar(self):
        ucret = calculate_cancellation_fee(
            Money.of("2000"), hours_before_arrival=720, is_refundable=False
        )
        assert ucret.amount == Decimal("2000.00")

    def test_no_show_tam_tutar(self):
        """Misafir gelmedi: ucretsiz iptal penceresi dikkate alinmaz."""
        ucret = calculate_cancellation_fee(
            Money.of("2000"), hours_before_arrival=-3, is_no_show=True
        )
        assert ucret.amount == Decimal("2000.00")

    def test_no_show_kismi_ceza(self):
        ucret = calculate_cancellation_fee(
            Money.of("2000"),
            hours_before_arrival=-3,
            is_no_show=True,
            no_show_fee_percent="50",
        )
        assert ucret.amount == Decimal("1000.00")


class TestErkenGirisGecCikis:
    def test_erken_giris_dilim_basina_ucretlendirilir(self):
        # 4 saat -> 2 dilim (3'er saat) -> %50
        ucret = calculate_early_late_fee(Money.of("1000"), hours=4)
        assert ucret.amount == Decimal("500.00")

    def test_ucret_tam_gece_ile_sinirlidir(self):
        ucret = calculate_early_late_fee(Money.of("1000"), hours=48)
        assert ucret.amount == Decimal("1000.00")

    def test_sifir_saat_ucretsiz(self):
        assert calculate_early_late_fee(Money.of("1000"), hours=0).is_zero
