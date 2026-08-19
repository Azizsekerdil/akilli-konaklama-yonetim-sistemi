"""Otelcilik performans gostergeleri (KPI) - saf fonksiyonlar.

Bu modul **veritabani bilmez**. Tum girdiler sayilardan ve
:class:`~app.domain.value_objects.Money` nesnelerinden olusur; boylece her
formul veritabani kurmadan, milisaniyeler icinde test edilebilir. Sorgular
:mod:`app.reporting.queries` icindedir.

Neden formuller bu kadar onemli?
--------------------------------
Otelcilikte ADR/RevPAR/doluluk sayilari yatirimci raporlarina, acente
sozlesmelerine ve fiyat kararlarina girer. Yanlis bir payda, isletmeyi
oldugundan iyi ya da kotu gosterir. Bu yuzden her fonksiyonun docstring'i
formulu ve **paydanin neden o oldugunu** acikca yazar.

Sifira bolme
------------
Yeni acilan bir tesiste veya bos bir donemde her payda sifir olabilir.
Hicbir fonksiyon bu durumda hata firlatmaz; ``0.0`` veya sifir tutar doner.
Rapor ekraninin bir ``ZeroDivisionError`` ile kapanmasi kabul edilemez.
"""

from __future__ import annotations

from datetime import date

from app.domain.enums import Currency
from app.domain.value_objects import DateRange, Money
from app.reporting.models import KPISet

#: Oran hesaplarinda kullanilan ondalik hassasiyet.
#:
#: Neden 6 ve 4 degil? ``RevPAR = ADR x doluluk`` esitliginin kurus
#: duzeyinde saglanmasi gerekir. Doluluk 4 haneye yuvarlandiginda, kurusun
#: iki katindan buyuk sapmalar olusabiliyor (or. 1.000 TL gelir / 7 satilan
#: gece / 13 satilabilir gece: 76,93 yerine 76,92). 6 hane bu sapmayi
#: pratikte ortadan kaldirir.
RATE_PRECISION = 6

#: Ortalama konaklama suresi gosteriminde iki hane yeterlidir (or. 2,35 gece).
ALOS_PRECISION = 2


def safe_ratio(numerator: float, denominator: float, *, precision: int = RATE_PRECISION) -> float:
    """Sifira bolmeye karsi korumali oran.

    Payda sifir veya negatifse ``0.0`` doner. Negatif paydayi da sifir
    saymak bilincli bir tercihtir: negatif oda sayisi veri hatasidir ve
    rapor bunun uzerine anlamsiz bir oran uretmemelidir.
    """
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, precision)


def compute_available_room_nights(
    total_rooms: int,
    nights: int,
    *,
    out_of_order_room_nights: int = 0,
) -> int:
    """Donemdeki **satilabilir** oda gecesi sayisi.

    Formul::

        satilabilir = (toplam oda x gece) - arizali oda gecesi

    Arizali (``out_of_order``) odalar envanterden **dusulur**. Neden?
    Ciddi arizasi olan bir oda o gun satilamaz; paydada birakilirsa
    isletme, kendi elinde olmayan bir nedenle dusuk doluluklu gorunur.
    Bu, otelcilikteki standart yaklasimdir ve
    :class:`app.domain.rules.availability.OccupancyStats` ile ayni kurali
    uygular.

    .. note::
       ``out_of_service`` (kucuk sorun) odalar envanterde kalir; yalnizca
       ``out_of_order`` dusulur. Ayrim
       :class:`app.domain.enums.RoomHousekeepingStatus` icinde tanimlidir.

    >>> compute_available_room_nights(10, 30)
    300
    >>> compute_available_room_nights(10, 30, out_of_order_room_nights=30)
    270
    """
    if total_rooms <= 0 or nights <= 0:
        return 0
    return max(total_rooms * nights - max(out_of_order_room_nights, 0), 0)


def occupancy_rate(room_nights_sold: int, available_room_nights: int) -> float:
    """Doluluk orani (``0.0 - 1.0``).

    Formul::

        doluluk = satilan oda gecesi / SATILABILIR oda gecesi

    Payda **satilabilir** oda gecesidir; arizali odalar
    :func:`compute_available_room_nights` tarafindan zaten dusulmustur.
    Toplam oda sayisini payda yapmak sik yapilan bir hatadir.

    >>> occupancy_rate(80, 100)
    0.8
    >>> occupancy_rate(5, 0)
    0.0
    """
    return safe_ratio(room_nights_sold, available_room_nights)


def adr(room_revenue: Money, room_nights_sold: int) -> Money:
    """ADR - Average Daily Rate (ortalama gunluk oda fiyati).

    Formul::

        ADR = ODA GELIRI / satilan oda gecesi

    .. warning::
       **Paya yalnizca oda geliri girer.** Restoran, spa, minibar,
       transfer, otopark gibi ek gelirler ADR'ye dahil EDILMEZ. Bu, sektorde
       en sik yapilan hesap hatasidir: toplam gelir kullanildiginda ADR
       sisirilir, fiyat kiyaslamalari (rakip analizi, kanal komisyon
       pazarligi) yanlis temele oturur.

       Sorgu katmani oda gelirini
       ``Charge.charge_type == ChargeType.ROOM`` suzgeciyle ayirir.

    Satilan gece yoksa sifir tutar doner (bolme yapilmaz).

    >>> from app.domain.value_objects import Money
    >>> str(adr(Money.of("240000"), 160))
    '1.500,00 ₺'
    >>> adr(Money.of("240000"), 0).is_zero
    True
    """
    if room_nights_sold <= 0:
        return Money.zero(room_revenue.currency)
    return room_revenue / room_nights_sold


def revpar(room_revenue: Money, available_room_nights: int) -> Money:
    """RevPAR - Revenue Per Available Room (satilabilir oda basina oda geliri).

    Formul::

        RevPAR = oda geliri / SATILABILIR oda gecesi
               = ADR x doluluk

    Iki yol matematiksel olarak ozdestir::

        (gelir / satilan) x (satilan / satilabilir) = gelir / satilabilir

    RevPAR, ADR'den daha durustur: yuksek fiyattan az oda satan bir tesis
    yuksek ADR ama dusuk RevPAR uretir. Doluluk ve fiyati tek sayida
    birlestirdigi icin yonetim panelinin ana gostergesidir.

    >>> from app.domain.value_objects import Money
    >>> str(revpar(Money.of("240000"), 200))
    '1.200,00 ₺'
    """
    if available_room_nights <= 0:
        return Money.zero(room_revenue.currency)
    return room_revenue / available_room_nights


def revpar_from_adr(adr_value: Money, occupancy: float) -> Money:
    """RevPAR'i ``ADR x doluluk`` yolundan hesaplar.

    :func:`revpar` ile ayni sonucu vermelidir; bu esitlik testlerle
    dogrulanir. Yalnizca elde ADR ve doluluk varken (or. disaridan gelen
    bir kiyaslama raporu) kullanilir.

    .. note::
       ADR kurusa, doluluk :data:`RATE_PRECISION` hanesine yuvarlanmis
       degerlerdir; bu yuzden sonuc bir kurus sapabilir. Uretim
       hesaplarinda dogrudan :func:`revpar` tercih edilmelidir.

    >>> from app.domain.value_objects import Money
    >>> str(revpar_from_adr(Money.of("1500"), 0.8))
    '1.200,00 ₺'
    """
    if occupancy <= 0:
        return Money.zero(adr_value.currency)
    return adr_value * occupancy


def trevpar(total_revenue: Money, available_room_nights: int) -> Money:
    """TRevPAR - Total Revenue Per Available Room.

    Formul::

        TRevPAR = TOPLAM gelir / satilabilir oda gecesi

    RevPAR'dan farki, paya **tum** gelirlerin (oda + restoran + spa +
    diger) girmesidir. Her sey dahil tesislerde ve yan gelirleri guclu
    otellerde asil performans gostergesi budur; yalnizca RevPAR'a bakmak
    isletmenin gelirinin buyuk bolumunu gormezden gelmek olur.

    >>> from app.domain.value_objects import Money
    >>> str(trevpar(Money.of("300000"), 200))
    '1.500,00 ₺'
    """
    if available_room_nights <= 0:
        return Money.zero(total_revenue.currency)
    return total_revenue / available_room_nights


def alos(total_room_nights: int, stay_count: int) -> float:
    """ALOS - Average Length of Stay (ortalama konaklama suresi, gece).

    Formul::

        ALOS = toplam oda gecesi / konaklama sayisi

    Paydadaki "konaklama", **oda satiri** sayisidir (rezervasyon degil):
    uc odali tek bir rezervasyon uc konaklamadir. Rezervasyon sayisi
    kullanilsaydi grup rezervasyonlari ALOS'u yapay olarak yukseltirdi.

    ALOS uzadikca oda basina isletme maliyeti (temizlik, giris-cikis
    islemleri) duser; bu yuzden uzun konaklama tarifeleri planlanirken
    dogrudan bu gostergeye bakilir.

    >>> alos(240, 100)
    2.4
    >>> alos(240, 0)
    0.0
    """
    return safe_ratio(total_room_nights, stay_count, precision=ALOS_PRECISION)


def cancellation_rate(cancelled_count: int, total_reservations: int) -> float:
    """Iptal orani (``0.0 - 1.0``).

    Formul::

        iptal orani = iptal edilen rezervasyon / TOPLAM rezervasyon

    Paydaya iptal edilenler de dahildir; aksi halde "gerceklesen
    rezervasyona oranla iptal" gibi anlamsiz, 1'i asabilen bir sayi cikar.

    >>> cancellation_rate(15, 100)
    0.15
    >>> cancellation_rate(0, 0)
    0.0
    """
    return safe_ratio(cancelled_count, total_reservations)


def no_show_rate(no_show_count: int, total_reservations: int) -> float:
    """Gelmeme (no-show) orani (``0.0 - 1.0``).

    Formul::

        no-show orani = gelmeyen rezervasyon / TOPLAM rezervasyon

    Iptalden ayri tutulur: iptal onceden bildirilir ve oda yeniden
    satilabilir; no-show gecesi oda bos kalir. Ikisini toplamak, garanti
    ve depozito politikasi kararlarini yaniltir.

    >>> no_show_rate(3, 100)
    0.03
    """
    return safe_ratio(no_show_count, total_reservations)


def calculate_kpis(
    *,
    date_range: DateRange,
    room_revenue: Money,
    other_revenue: Money | None = None,
    room_nights_sold: int = 0,
    total_rooms: int = 0,
    out_of_order_room_nights: int = 0,
    stay_count: int = 0,
    total_reservations: int = 0,
    cancelled_reservations: int = 0,
    no_show_reservations: int = 0,
    available_room_nights: int | None = None,
) -> KPISet:
    """Tum gostergeleri tek bir :class:`~app.reporting.models.KPISet` icinde toplar.

    Parameters
    ----------
    date_range:
        Rapor donemi. Cikis gunu dahil degildir; gece sayisi ``nights``
        ozelliginden gelir.
    room_revenue:
        Yalnizca oda geliri (bkz. :func:`adr` uyarisi).
    other_revenue:
        Oda disi gelirler. ``None`` ise sifir kabul edilir.
    room_nights_sold:
        Donem icinde satilan oda gecesi.
    total_rooms:
        Tesisin aktif oda sayisi.
    out_of_order_room_nights:
        Arizali odalarin donem icindeki gece sayisi - paydadan dusulur.
    stay_count:
        ALOS paydasi: donemde konaklayan oda satiri sayisi.
    total_reservations / cancelled_reservations / no_show_reservations:
        Iptal ve gelmeme oranlarinin girdileri.
    available_room_nights:
        Satilabilir oda gecesi disaridan biliniyorsa (or. gun bazinda
        farkli oda sayisi olan bir tesis) dogrudan verilebilir; verilmezse
        :func:`compute_available_room_nights` ile hesaplanir.

    Tum tutarlar ayni para biriminde olmalidir; farkli birimler
    :class:`~app.domain.value_objects.Money` tarafindan reddedilir.
    """
    currency: Currency = room_revenue.currency
    other = other_revenue if other_revenue is not None else Money.zero(currency)
    total = room_revenue + other

    available = (
        available_room_nights
        if available_room_nights is not None
        else compute_available_room_nights(
            total_rooms,
            date_range.nights,
            out_of_order_room_nights=out_of_order_room_nights,
        )
    )
    available = max(available, 0)

    return KPISet(
        period_start=date_range.start,
        period_end=date_range.end,
        occupancy_rate=occupancy_rate(room_nights_sold, available),
        adr=adr(room_revenue, room_nights_sold),
        revpar=revpar(room_revenue, available),
        alos=alos(room_nights_sold, stay_count),
        cancellation_rate=cancellation_rate(cancelled_reservations, total_reservations),
        no_show_rate=no_show_rate(no_show_reservations, total_reservations),
        total_revenue=total,
        room_revenue=room_revenue,
        other_revenue=other,
        room_nights_sold=max(room_nights_sold, 0),
        available_room_nights=available,
    )


def empty_kpis(
    period_start: date,
    period_end: date,
    *,
    currency: Currency = Currency.TRY,
) -> KPISet:
    """Hicbir veri olmayan donem icin sifirlanmis KPI kumesi.

    Bos veri senaryosunun tek yerden uretilmesi, her cagiran tarafin kendi
    "bos" nesnesini kurmasindan daha guvenlidir.
    """
    zero = Money.zero(currency)
    return KPISet(
        period_start=period_start,
        period_end=period_end,
        occupancy_rate=0.0,
        adr=zero,
        revpar=zero,
        alos=0.0,
        cancellation_rate=0.0,
        no_show_rate=0.0,
        total_revenue=zero,
        room_revenue=zero,
        other_revenue=zero,
        room_nights_sold=0,
        available_room_nights=0,
    )


__all__ = [
    "ALOS_PRECISION",
    "RATE_PRECISION",
    "adr",
    "alos",
    "calculate_kpis",
    "cancellation_rate",
    "compute_available_room_nights",
    "empty_kpis",
    "no_show_rate",
    "occupancy_rate",
    "revpar",
    "revpar_from_adr",
    "safe_ratio",
    "trevpar",
]
