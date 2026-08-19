"""KPI formullerinin testleri - **veritabani yok**, tamamen saf fonksiyonlar.

Bu dosyadaki testlerin hepsi milisaniyeler icinde calisir. Formuller isletme
kararlarina girdigi icin, her gostergenin hem dogru sonucu hem de bos/sifir
veri davranisi ayri ayri dogrulanir.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.domain.enums import Currency
from app.domain.value_objects import DateRange, Money
from app.reporting import kpi
from app.reporting.models import KPISet

#: Testlerde kullanilan sabit donem: 1-31 Agustos 2026 (30 gece).
AGUSTOS = DateRange(date(2026, 8, 1), date(2026, 8, 31))


# --------------------------------------------------------------------------
#  Satilabilir oda gecesi (payda)
# --------------------------------------------------------------------------
def test_satilabilir_oda_gecesi_temel_hesap():
    assert kpi.compute_available_room_nights(10, 30) == 300


def test_arizali_odalar_paydadan_dusulur():
    """Arizali oda gecesi envanterden cikar - otelcilikteki standart kural."""
    tam = kpi.compute_available_room_nights(10, 30)
    arizali = kpi.compute_available_room_nights(10, 30, out_of_order_room_nights=30)
    assert tam == 300
    assert arizali == 270


def test_arizali_oda_sayisi_envanteri_asarsa_sifir():
    """Veri hatasi negatif payda uretmemelidir."""
    assert kpi.compute_available_room_nights(2, 5, out_of_order_room_nights=999) == 0


def test_oda_yoksa_satilabilir_gece_sifirdir():
    assert kpi.compute_available_room_nights(0, 30) == 0
    assert kpi.compute_available_room_nights(10, 0) == 0


# --------------------------------------------------------------------------
#  Doluluk
# --------------------------------------------------------------------------
def test_doluluk_orani():
    assert kpi.occupancy_rate(80, 100) == 0.8


def test_doluluk_bos_veride_sifira_bolmez():
    """Payda sifirken ZeroDivisionError yerine 0.0 donmelidir."""
    assert kpi.occupancy_rate(0, 0) == 0.0
    assert kpi.occupancy_rate(5, 0) == 0.0


def test_negatif_payda_sifir_sayilir():
    assert kpi.safe_ratio(10, -5) == 0.0


def test_arizali_oda_dolulugu_yukseltir():
    """Ayni satis, kucuk paydayla daha yuksek doluluk uretir."""
    satilan = 200
    tam_envanter = kpi.compute_available_room_nights(10, 30)
    arizali_envanter = kpi.compute_available_room_nights(10, 30, out_of_order_room_nights=60)
    assert kpi.occupancy_rate(satilan, arizali_envanter) > kpi.occupancy_rate(satilan, tam_envanter)


# --------------------------------------------------------------------------
#  ADR
# --------------------------------------------------------------------------
def test_adr_temel_hesap():
    assert kpi.adr(Money.of("240000"), 160) == Money.of("1500.00")


def test_adr_yalnizca_oda_gelirini_sayar():
    """Restoran geliri ADR'yi ETKILEMEZ - en sik yapilan hesap hatasi."""
    oda_geliri = Money.of("100000")
    restoran_geliri = Money.of("40000")

    dogru_adr = kpi.adr(oda_geliri, 80)
    yanlis_adr = kpi.adr(oda_geliri + restoran_geliri, 80)

    assert dogru_adr == Money.of("1250.00")
    assert yanlis_adr == Money.of("1750.00")
    assert dogru_adr != yanlis_adr


def test_adr_kpi_kumesinde_de_yalnizca_oda_gelirini_kullanir():
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("100000"),
        other_revenue=Money.of("40000"),
        room_nights_sold=80,
        total_rooms=10,
    )
    assert kpis.adr == Money.of("1250.00")
    assert kpis.total_revenue == Money.of("140000.00")


def test_adr_satis_yoksa_sifir_doner():
    assert kpi.adr(Money.of("240000"), 0).is_zero


def test_adr_para_birimini_korur():
    sonuc = kpi.adr(Money.of("1000", Currency.EUR), 4)
    assert sonuc.currency is Currency.EUR
    assert isinstance(sonuc.amount, Decimal)


# --------------------------------------------------------------------------
#  RevPAR
# --------------------------------------------------------------------------
def test_revpar_temel_hesap():
    assert kpi.revpar(Money.of("240000"), 200) == Money.of("1200.00")


@pytest.mark.parametrize(
    ("oda_geliri", "satilan", "satilabilir"),
    [
        ("240000", 160, 200),
        ("100000", 80, 100),
        ("1000", 3, 9),
        ("1000", 7, 13),
        ("87654.32", 123, 300),
        ("55555.55", 41, 97),
    ],
)
def test_revpar_adr_carpi_doluluk_esitligi(oda_geliri, satilan, satilabilir):
    """RevPAR iki yoldan da ayni sonucu vermelidir.

    ``(gelir / satilan) x (satilan / satilabilir) = gelir / satilabilir``
    """
    gelir = Money.of(oda_geliri)
    dogrudan = kpi.revpar(gelir, satilabilir)
    dolayli = kpi.revpar_from_adr(kpi.adr(gelir, satilan), kpi.occupancy_rate(satilan, satilabilir))
    assert dogrudan == dolayli


def test_revpar_bos_envanterde_sifir():
    assert kpi.revpar(Money.of("1000"), 0).is_zero


def test_revpar_from_adr_sifir_dolulukta_sifir():
    assert kpi.revpar_from_adr(Money.of("1500"), 0.0).is_zero


def test_revpar_adr_den_kucuk_veya_esittir():
    """Doluluk 1'i asmadigi surece RevPAR, ADR'yi gecemez."""
    gelir = Money.of("120000")
    assert kpi.revpar(gelir, 200) <= kpi.adr(gelir, 150)


# --------------------------------------------------------------------------
#  TRevPAR
# --------------------------------------------------------------------------
def test_trevpar_toplam_geliri_kullanir():
    assert kpi.trevpar(Money.of("300000"), 200) == Money.of("1500.00")


def test_trevpar_revpar_dan_buyuktur_yan_gelir_varsa():
    oda = Money.of("240000")
    toplam = oda + Money.of("60000")
    assert kpi.trevpar(toplam, 200) > kpi.revpar(oda, 200)


def test_trevpar_bos_envanterde_sifir():
    assert kpi.trevpar(Money.of("1000"), 0).is_zero


# --------------------------------------------------------------------------
#  ALOS
# --------------------------------------------------------------------------
def test_alos_temel_hesap():
    assert kpi.alos(240, 100) == 2.4


def test_alos_konaklama_yoksa_sifir():
    assert kpi.alos(240, 0) == 0.0


def test_alos_iki_haneye_yuvarlanir():
    assert kpi.alos(10, 3) == 3.33


# --------------------------------------------------------------------------
#  Iptal ve gelmeme
# --------------------------------------------------------------------------
def test_iptal_orani():
    assert kpi.cancellation_rate(15, 100) == 0.15


def test_iptal_orani_rezervasyon_yoksa_sifir():
    assert kpi.cancellation_rate(0, 0) == 0.0
    assert kpi.cancellation_rate(3, 0) == 0.0


def test_no_show_orani_iptalden_ayridir():
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("0"),
        room_nights_sold=0,
        total_rooms=10,
        total_reservations=200,
        cancelled_reservations=20,
        no_show_reservations=5,
    )
    assert kpis.cancellation_rate == 0.1
    assert kpis.no_show_rate == 0.025
    assert kpis.cancellation_rate != kpis.no_show_rate


# --------------------------------------------------------------------------
#  calculate_kpis
# --------------------------------------------------------------------------
def test_calculate_kpis_tam_senaryo():
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("240000"),
        other_revenue=Money.of("60000"),
        room_nights_sold=200,
        total_rooms=10,
        stay_count=80,
        total_reservations=100,
        cancelled_reservations=10,
        no_show_reservations=2,
    )
    assert kpis.available_room_nights == 300
    assert kpis.occupancy_rate == pytest.approx(200 / 300, abs=1e-6)
    assert kpis.adr == Money.of("1200.00")
    assert kpis.revpar == Money.of("800.00")
    assert kpis.total_revenue == Money.of("300000.00")
    assert kpis.alos == 2.5
    assert kpis.period_start == date(2026, 8, 1)
    assert kpis.period_end == date(2026, 8, 31)


def test_calculate_kpis_arizali_odayi_paydadan_duser():
    ortak = {
        "date_range": AGUSTOS,
        "room_revenue": Money.of("240000"),
        "room_nights_sold": 200,
        "total_rooms": 10,
    }
    tam = kpi.calculate_kpis(**ortak)
    arizali = kpi.calculate_kpis(**ortak, out_of_order_room_nights=60)

    assert tam.available_room_nights == 300
    assert arizali.available_room_nights == 240
    assert arizali.occupancy_rate > tam.occupancy_rate
    assert arizali.revpar > tam.revpar


def test_calculate_kpis_toplam_gelir_oda_plus_diger():
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("1000"),
        other_revenue=Money.of("250.50"),
        room_nights_sold=1,
        total_rooms=1,
    )
    assert kpis.total_revenue == Money.of("1250.50")
    assert kpis.other_revenue == Money.of("250.50")


def test_calculate_kpis_bos_veride_cokmez():
    """Hicbir veri yokken tum gostergeler sifir olmali, hata olmamali."""
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.zero(),
        room_nights_sold=0,
        total_rooms=0,
    )
    assert kpis.available_room_nights == 0
    assert kpis.occupancy_rate == 0.0
    assert kpis.adr.is_zero
    assert kpis.revpar.is_zero
    assert kpis.trevpar.is_zero
    assert kpis.alos == 0.0
    assert kpis.cancellation_rate == 0.0
    assert kpis.no_show_rate == 0.0
    assert kpis.total_revenue.is_zero


def test_calculate_kpis_farkli_para_birimi_reddedilir():
    with pytest.raises(ValueError, match="para birim"):
        kpi.calculate_kpis(
            date_range=AGUSTOS,
            room_revenue=Money.of("100", Currency.TRY),
            other_revenue=Money.of("100", Currency.EUR),
            room_nights_sold=1,
            total_rooms=1,
        )


def test_calculate_kpis_hazir_payda_verilebilir():
    """Gun bazinda oda sayisi degisen tesisler paydayi disaridan verebilir."""
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("1000"),
        room_nights_sold=1,
        total_rooms=999,
        available_room_nights=10,
    )
    assert kpis.available_room_nights == 10
    assert kpis.revpar == Money.of("100.00")


# --------------------------------------------------------------------------
#  KPISet
# --------------------------------------------------------------------------
def test_empty_kpis_tumuyle_sifirdir():
    kpis = kpi.empty_kpis(date(2026, 8, 1), date(2026, 8, 31))
    assert isinstance(kpis, KPISet)
    assert kpis.room_nights_sold == 0
    assert kpis.available_room_nights == 0
    assert kpis.total_revenue.is_zero
    assert kpis.nights == 30


def test_kpiset_trevpar_ozelligi():
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("240000"),
        other_revenue=Money.of("60000"),
        room_nights_sold=200,
        total_rooms=10,
    )
    assert kpis.trevpar == kpi.trevpar(kpis.total_revenue, kpis.available_room_nights)
    assert kpis.trevpar == Money.of("1000.00")


def test_kpiset_yuzde_gosterimi():
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("1000"),
        room_nights_sold=150,
        total_rooms=10,
    )
    assert kpis.occupancy_percent == 50.0


def test_kpiset_tabloya_cevrilir():
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("240000"),
        other_revenue=Money.of("60000"),
        room_nights_sold=200,
        total_rooms=10,
        stay_count=80,
    )
    table = kpis.to_table()
    assert not table.is_empty
    assert table.column_count == 2
    gostergeler = [row["gosterge"] for row in table.rows]
    assert "ADR (Ortalama Oda Fiyati)" in gostergeler
    assert "RevPAR" in gostergeler
    assert "TRevPAR" in gostergeler


def test_bos_kpiset_tablosu_da_uretilebilir():
    """Bos donem tablosu satirli ama sifir degerli olmalidir."""
    table = kpi.empty_kpis(date(2026, 8, 1), date(2026, 8, 31)).to_table()
    assert not table.is_empty
    assert any("0,00" in str(row["deger"]) for row in table.rows)


def test_para_degerleri_decimal_tabanlidir():
    """Para hicbir yerde float'a donusmemelidir."""
    kpis = kpi.calculate_kpis(
        date_range=AGUSTOS,
        room_revenue=Money.of("0.10") + Money.of("0.20"),
        room_nights_sold=1,
        total_rooms=1,
    )
    assert kpis.room_revenue.amount == Decimal("0.30")
    assert isinstance(kpis.adr.amount, Decimal)
    assert isinstance(kpis.revpar.amount, Decimal)
