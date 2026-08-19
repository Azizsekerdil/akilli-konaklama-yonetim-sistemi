"""Deger nesnesi testleri: para aritmetigi ve tarih araligi semantigi."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.domain.enums import Currency
from app.domain.value_objects import (
    DateRange,
    Money,
    any_overlap,
    merge_ranges,
    to_decimal,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
#  Money
# --------------------------------------------------------------------------
class TestMoney:
    def test_float_kayipsiz_donusturulur(self):
        """0.1 + 0.2 ikili gosterim hatasi para hesabina sizmamali."""
        toplam = Money.of(0.1) + Money.of(0.2)
        assert toplam.amount == Decimal("0.30")

    def test_kurusa_yuvarlanir(self):
        assert Money.of("100.005").amount == Decimal("100.01")
        assert Money.of("100.004").amount == Decimal("100.00")

    def test_farkli_para_birimleri_toplanamaz(self):
        with pytest.raises(ValueError, match="Farkli para birimleri"):
            Money.of(100, Currency.TRY) + Money.of(50, Currency.EUR)

    def test_farkli_para_birimleri_karsilastirilamaz(self):
        with pytest.raises(ValueError):
            _ = Money.of(100, Currency.TRY) < Money.of(50, Currency.EUR)

    def test_sifira_bolme_engellenir(self):
        with pytest.raises(ZeroDivisionError):
            Money.of(100) / 0

    @pytest.mark.parametrize(
        ("tutar", "parca", "beklenen"),
        [
            ("10.00", 3, ["3.34", "3.33", "3.33"]),
            ("100.00", 4, ["25.00"] * 4),
            ("0.05", 3, ["0.02", "0.02", "0.01"]),
            ("-10.00", 3, ["-3.34", "-3.33", "-3.33"]),
        ],
    )
    def test_bolusturme_kurus_kaybetmez(self, tutar, parca, beklenen):
        """Parcalarin toplami her zaman orijinal tutara esit olmali."""
        parcalar = Money.of(tutar).allocate(parca)
        assert [str(p.amount) for p in parcalar] == beklenen
        assert sum((p.amount for p in parcalar), Decimal("0")) == Decimal(tutar)

    def test_vergi_dahil_tutardan_vergi_ayristirma(self):
        """3000 TL vergi dahil, %10 KDV -> icindeki vergi 272,73 TL."""
        assert Money.of("3000").tax_part(10).amount == Decimal("272.73")

    def test_vergi_ekleme(self):
        assert Money.of("1000").with_tax(20).amount == Decimal("1200.00")

    def test_turkce_bicimlendirme(self):
        assert Money.of("1234.5").format() == "1.234,50 ₺"
        assert Money.of("-99.9").format() == "-99,90 ₺"
        assert Money.of("1234.5", Currency.EUR).format() == "1.234,50 €"

    def test_gecersiz_deger_hata_verir(self):
        with pytest.raises(ValueError):
            to_decimal("bu bir sayi degil")


# --------------------------------------------------------------------------
#  DateRange
# --------------------------------------------------------------------------
class TestDateRange:
    def test_gece_sayisi(self):
        assert DateRange(date(2026, 8, 10), date(2026, 8, 12)).nights == 2

    def test_cikis_girisden_sonra_olmali(self):
        with pytest.raises(ValueError, match="Cikis tarihi"):
            DateRange(date(2026, 8, 12), date(2026, 8, 10))

    def test_ayni_gun_araligi_gecersiz(self):
        """Sifir gecelik konaklama olmaz."""
        with pytest.raises(ValueError):
            DateRange(date(2026, 8, 10), date(2026, 8, 10))

    def test_cikis_gunu_araliga_dahil_degil(self):
        aralik = DateRange(date(2026, 8, 10), date(2026, 8, 12))
        assert date(2026, 8, 10) in aralik
        assert date(2026, 8, 11) in aralik
        assert date(2026, 8, 12) not in aralik

    def test_bitisik_araliklar_cakismaz(self):
        """Sabah cikan misafirin odasi ayni gun tekrar satilabilmeli."""
        onceki = DateRange(date(2026, 8, 10), date(2026, 8, 12))
        sonraki = DateRange(date(2026, 8, 12), date(2026, 8, 14))
        assert not onceki.overlaps(sonraki)
        assert onceki.is_adjacent_to(sonraki)

    @pytest.mark.parametrize(
        ("a_bas", "a_bit", "b_bas", "b_bit", "cakisir"),
        [
            ((2026, 8, 10), (2026, 8, 12), (2026, 8, 11), (2026, 8, 13), True),
            ((2026, 8, 10), (2026, 8, 12), (2026, 8, 12), (2026, 8, 14), False),
            ((2026, 8, 10), (2026, 8, 12), (2026, 8, 8), (2026, 8, 10), False),
            ((2026, 8, 10), (2026, 8, 20), (2026, 8, 12), (2026, 8, 14), True),
            ((2026, 8, 12), (2026, 8, 14), (2026, 8, 10), (2026, 8, 20), True),
            ((2026, 8, 10), (2026, 8, 12), (2026, 8, 10), (2026, 8, 12), True),
        ],
    )
    def test_cakisma_matrisi(self, a_bas, a_bit, b_bas, b_bit, cakisir):
        a = DateRange(date(*a_bas), date(*a_bit))
        b = DateRange(date(*b_bas), date(*b_bit))
        assert a.overlaps(b) is cakisir
        assert b.overlaps(a) is cakisir, "Cakisma simetrik olmali"

    def test_kesisim_gece_sayisi(self):
        a = DateRange(date(2026, 8, 10), date(2026, 8, 15))
        b = DateRange(date(2026, 8, 13), date(2026, 8, 20))
        assert a.overlapping_nights(b) == 2

    def test_kesisim_yoksa_none(self):
        a = DateRange(date(2026, 8, 10), date(2026, 8, 12))
        b = DateRange(date(2026, 8, 12), date(2026, 8, 14))
        assert a.intersection(b) is None

    def test_gunler_uzerinde_yineleme(self):
        aralik = DateRange(date(2026, 8, 10), date(2026, 8, 13))
        assert aralik.days == [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]

    def test_uzatma_ve_kaydirma(self):
        aralik = DateRange(date(2026, 8, 10), date(2026, 8, 12))
        assert aralik.extend_end(2).nights == 4
        assert aralik.extend_start(1).start == date(2026, 8, 9)
        assert aralik.shift(7).start == date(2026, 8, 17)

    def test_gece_sayisindan_uretme(self):
        aralik = DateRange.of_nights(date(2026, 8, 10), 3)
        assert aralik.end == date(2026, 8, 13)

    def test_sifir_gece_uretilemez(self):
        with pytest.raises(ValueError):
            DateRange.of_nights(date(2026, 8, 10), 0)


class TestRangeHelpers:
    def test_cakisan_cift_bulunur(self):
        araliklar = [
            DateRange(date(2026, 8, 1), date(2026, 8, 5)),
            DateRange(date(2026, 8, 4), date(2026, 8, 8)),
        ]
        assert any_overlap(araliklar) is not None

    def test_cakisma_yoksa_none(self):
        araliklar = [
            DateRange(date(2026, 8, 1), date(2026, 8, 5)),
            DateRange(date(2026, 8, 5), date(2026, 8, 8)),
        ]
        assert any_overlap(araliklar) is None

    def test_bitisik_araliklar_birlestirilir(self):
        birlesik = merge_ranges(
            [
                DateRange(date(2026, 8, 1), date(2026, 8, 5)),
                DateRange(date(2026, 8, 5), date(2026, 8, 9)),
                DateRange(date(2026, 8, 20), date(2026, 8, 22)),
            ]
        )
        assert len(birlesik) == 2
        assert birlesik[0] == DateRange(date(2026, 8, 1), date(2026, 8, 9))

    def test_bos_liste(self):
        assert merge_ranges([]) == []
