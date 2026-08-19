"""Rapor veri yapilari ve ortak bicimlendirme yardimcilari.

Neden tek bir ``ReportTable`` soyutlamasi?
------------------------------------------
Ihracatcilarin (CSV / Excel / PDF) sayisi zamanla artar. Her ihracatci
kendi veri sozlesmesini tanimlasaydi, yeni bir bicim eklemek tum rapor
sorgularinin degistirilmesini gerektirirdi. Bunun yerine **tum** sorgular
tek bir :class:`ReportTable` uretir; ihracatcilar yalnizca bu yapiyi bilir.
Sonuc: yeni bir bicim eklemek tek dosyalik bir istir.

Bicimlendirme neden burada?
---------------------------
"1234.5" degerinin kullaniciya ``1.234,50 ₺`` olarak gosterilmesi bir
*sunum* kararidir ve uc ihracatcida da ayni olmalidir. Ayni mantigi uc kez
yazmak, birinde duzeltilip digerlerinde unutulan hatalar uretir; bu yuzden
:func:`format_cell` tek dogruluk kaynagidir.

.. note::
   Excel ihracatcisi ham (sayisal) degerleri yazar ve bicimlendirmeyi
   hucre bicimine birakir; aksi halde hucreler metne donusur ve toplam
   alinamaz. :func:`format_cell` yalnizca metin tabanli ciktilar (CSV, PDF)
   ve KPI ozet tablosu icin kullanilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from app.core import paths
from app.core.exceptions import ValidationError
from app.domain.enums import LabeledEnum
from app.domain.value_objects import Money, to_decimal
from app.infrastructure.db.base import utcnow

#: Hucre hizalamasi.
CellAlign = Literal["left", "center", "right"]

#: Hucre icerik turu - bicimlendirmeyi belirler.
CellFormat = Literal[
    "text",
    "integer",
    "decimal",
    "money",
    "percent",
    "date",
    "datetime",
    "boolean",
]

#: Bos raporlarda tablo yerine yazilan metin.
#: Bos bir dosya uretmek yerine bu satiri yazmak, "rapor uretilmedi mi yoksa
#: gercekten kayit mi yok" belirsizligini ortadan kaldirir.
EMPTY_TABLE_MESSAGE = "Kayit bulunamadi"

#: Tarih ve saat gosterim kaliplari (Turkiye kullanimi).
DATE_FORMAT = "%d.%m.%Y"
DATETIME_FORMAT = "%d.%m.%Y %H:%M"


# --------------------------------------------------------------------------
#  Sayi bicimlendirme
# --------------------------------------------------------------------------
def format_number(value: Any, decimals: int = 2) -> str:
    """Sayiyi Turkce yerel bicimde gosterir: ``1.234,56``.

    Python'un ``,`` binlik / ``.`` ondalik varsayilani Turkce'nin tam
    tersidir. Iki ayiricinin yer degistirmesi tek adimda yapilamaz (ilk
    degisim ikincisini bozar), bu yuzden gecici bir ``\\x00`` isareti
    kullanilir - :meth:`app.domain.value_objects.Money.format` ile ayni
    yontem.
    """
    try:
        number = to_decimal(value)
    except ValueError:
        return str(value)
    raw = f"{number:,.{decimals}f}"
    return raw.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


#: Elektronik tablo uygulamalarinin **formul** baslangici saydigi karakterler.
#: ``-`` bilerek listede degildir: negatif tutarlar ("-1.234,56 TL") normal
#: rapor icerigidir ve her birinin basina tirnak koymak tum eksi bakiyeleri
#: metne cevirirdi.
_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "@", "\t", "\r")


def neutralize_formula(text: str) -> str:
    """CSV hucresini formul olarak yorumlanmaktan korur.

    Neden gerekli?
    --------------
    Excel ve LibreOffice, ``=``, ``+``, ``@`` ile baslayan bir hucreyi
    **formul** sayar. Rapor icerigi buyuk olcude kullanicidan gelir: misafir
    adi, ucret aciklamasi, oda notu. Misafir adi alanina
    ``=cmd|'/c calc'!A1`` yazan biri, resepsiyonistin actigi CSV dosyasinda
    kod calistirabilir (CSV enjeksiyonu). Zarar veren dosyayi otel personeli
    kendi eliyle acar; bu yuzden korumanin yazma aninda olmasi gerekir.

    Cozum, sektor standardi tek tirnak on ekidir: hucre metin olarak kalir.
    Tirnak gorunur olur ama okunabilirlik, kod calismasindan onemsizdir.

    >>> neutralize_formula("=1+1")
    "'=1+1"
    >>> neutralize_formula("Cift kisilik oda")
    'Cift kisilik oda'
    """
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def format_cell(value: Any, column: ReportColumn) -> str:
    """Bir hucre degerini sutun turune gore metne cevirir.

    ``None`` her zaman bos dizge olur; "None" yazan bir rapor hucresi
    kullaniciya hicbir sey anlatmaz.
    """
    if value is None:
        return ""
    if isinstance(value, Money):
        # Money kendi para birimini bildigi icin sutun turune bakilmaz.
        return value.format()
    if isinstance(value, LabeledEnum):
        return value.label
    if isinstance(value, bool):
        return "Evet" if value else "Hayir"

    fmt = column.format
    if fmt == "boolean":
        return "Evet" if value else "Hayir"
    if fmt == "integer":
        return format_number(value, 0)
    if fmt in {"decimal", "money"}:
        return format_number(value, 2)
    if fmt == "percent":
        return f"%{format_number(value, 2)}"
    if fmt == "date":
        if isinstance(value, datetime):
            return value.strftime(DATE_FORMAT)
        if isinstance(value, date):
            return value.strftime(DATE_FORMAT)
        return str(value)
    if fmt == "datetime":
        if isinstance(value, datetime):
            return value.strftime(DATETIME_FORMAT)
        return str(value)
    return str(value)


# --------------------------------------------------------------------------
#  Tablo yapilari
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReportColumn:
    """Rapor sutunu tanimi.

    ``key`` satir sozlugundeki anahtardir; ``title`` kullaniciya gosterilen
    Turkce basliktir. Ikisini ayirmak, arayuz metni degistiginde sorgu
    kodunun degismemesini saglar.
    """

    key: str
    title: str
    align: CellAlign = "left"
    format: CellFormat = "text"

    @property
    def is_numeric(self) -> bool:
        """Hucre sayisal mi (Excel'de sag hizali ve toplanabilir olmali)?"""
        return self.format in {"integer", "decimal", "money", "percent"}


@dataclass(slots=True)
class ReportTable:
    """Tum ihracatcilarin anladigi tek rapor gosterimi.

    Satirlar ``{sutun_anahtari: deger}`` sozlukleridir. Sozluk kullanmak
    (demet yerine) sutun sirasi degistiginde satir uretimini bozmaz.
    """

    title: str
    columns: list[ReportColumn]
    rows: list[dict[str, Any]] = field(default_factory=list)
    subtitle: str | None = None
    generated_at: datetime = field(default_factory=utcnow)
    """Raporun uretildigi an (UTC). Mali raporlarda ne zaman alindigi kritiktir."""

    filters_description: str | None = None
    """Uygulanan suzgeclerin okunabilir ozeti, or. "01.08.2026 - 31.08.2026"."""

    footer_note: str | None = None
    """Dipnot. Yapay zeka uretimi raporlarda seffaflik notu icin kullanilir."""

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def header_titles(self) -> list[str]:
        return [column.title for column in self.columns]

    def display_row(self, row: dict[str, Any]) -> list[str]:
        """Tek bir satiri metin listesine cevirir."""
        return [format_cell(row.get(column.key), column) for column in self.columns]

    def display_rows(self) -> list[list[str]]:
        """Tum satirlari metin listesine cevirir (CSV ve PDF icin)."""
        return [self.display_row(row) for row in self.rows]

    def empty_row(self) -> list[str]:
        """Bos raporlarda yazilacak tek satir.

        Ilk hucrede aciklama, kalan hucreler bos: boylece sutun sayisi
        korunur ve CSV/Excel dosyasi bicimsel olarak gecerli kalir.
        """
        return [EMPTY_TABLE_MESSAGE] + [""] * max(self.column_count - 1, 0)


@dataclass(frozen=True, slots=True)
class KPISet:
    """Bir donemin temel otelcilik gostergeleri.

    Tum oranlar ``0.0 - 1.0`` araligindadir (yuzde degil); yuzdeye cevrim
    sunum katmaninda yapilir. Boylece ``0.85`` mi ``85`` mi belirsizligi
    ortadan kalkar.

    ``period_end`` **dahil degildir** (yari acik aralik) -
    :class:`~app.domain.value_objects.DateRange` ile ayni semantik.
    """

    period_start: date
    period_end: date
    occupancy_rate: float
    adr: Money
    revpar: Money
    alos: float
    cancellation_rate: float
    no_show_rate: float
    total_revenue: Money
    room_revenue: Money
    other_revenue: Money
    room_nights_sold: int
    available_room_nights: int

    @property
    def nights(self) -> int:
        """Donemin gun (gece) sayisi."""
        return max((self.period_end - self.period_start).days, 0)

    @property
    def trevpar(self) -> Money:
        """Satilabilir oda gecesi basina **toplam** gelir.

        Hesaplama :func:`app.reporting.kpi.trevpar` ile aynidir; burada
        KPISet'in kendi kendine yetmesi icin turetilmis ozellik olarak da
        sunulur.
        """
        if self.available_room_nights <= 0:
            return Money.zero(self.total_revenue.currency)
        return self.total_revenue / self.available_room_nights

    @property
    def occupancy_percent(self) -> float:
        return round(self.occupancy_rate * 100, 2)

    def to_table(self) -> ReportTable:
        """KPI kumesini iki sutunlu bir rapor tablosuna cevirir.

        Degerler burada metne cevrilir; cunku her satirin turu farklidir
        (oran, para, adet) ve tek bir sutun bicimiyle temsil edilemez.
        """
        columns = [
            ReportColumn("gosterge", "Gosterge", align="left"),
            ReportColumn("deger", "Deger", align="right"),
        ]
        period = (
            f"{self.period_start.strftime(DATE_FORMAT)} - "
            f"{self.period_end.strftime(DATE_FORMAT)} ({self.nights} gece)"
        )
        rows: list[dict[str, Any]] = [
            {"gosterge": "Donem", "deger": period},
            {
                "gosterge": "Satilabilir Oda Gecesi",
                "deger": format_number(self.available_room_nights, 0),
            },
            {"gosterge": "Satilan Oda Gecesi", "deger": format_number(self.room_nights_sold, 0)},
            {"gosterge": "Doluluk Orani", "deger": f"%{format_number(self.occupancy_percent, 2)}"},
            {"gosterge": "ADR (Ortalama Oda Fiyati)", "deger": self.adr.format()},
            {"gosterge": "RevPAR", "deger": self.revpar.format()},
            {"gosterge": "TRevPAR", "deger": self.trevpar.format()},
            {
                "gosterge": "ALOS (Ortalama Konaklama)",
                "deger": f"{format_number(self.alos, 2)} gece",
            },
            {
                "gosterge": "Iptal Orani",
                "deger": f"%{format_number(self.cancellation_rate * 100, 2)}",
            },
            {
                "gosterge": "Gelmeme (No-show) Orani",
                "deger": f"%{format_number(self.no_show_rate * 100, 2)}",
            },
            {"gosterge": "Oda Geliri", "deger": self.room_revenue.format()},
            {"gosterge": "Diger Gelir", "deger": self.other_revenue.format()},
            {"gosterge": "Toplam Gelir", "deger": self.total_revenue.format()},
        ]
        return ReportTable(
            title="Temel Performans Gostergeleri",
            columns=columns,
            rows=rows,
            filters_description=period,
        )


# --------------------------------------------------------------------------
#  Guvenli dosya yolu
# --------------------------------------------------------------------------
def resolve_export_path(output_path: str | os.PathLike[str]) -> Path:
    """Ihracat dosya yolunu :data:`app.core.paths.EXPORT_DIR` altinda cozer.

    Neden bu kadar siki?
    --------------------
    Rapor adi kullanicidan (veya yapay zekadan) gelebilir. ``..\\..\\Windows\\
    System32\\x.csv`` gibi bir ad, kontrol edilmezse sistem dosyalarinin
    uzerine yazabilirdi. Iki asamali kontrol yapilir:

    1. :func:`app.core.paths.resolve_data_path` - veri kokunun disina cikisi
       engeller.
    2. Sonucun ``EXPORT_DIR`` altinda kalmasi - veri kokundeki *diger*
       klasorlere (or. ``data/hotel.db``) yazmayi engeller.

    Goreli yollar ``EXPORT_DIR`` ile birlestirilir; mutlak yollar oldugu gibi
    denetlenir. Hedef klasor yoksa olusturulur.
    """
    export_root = Path(paths.EXPORT_DIR).resolve()
    candidate = Path(output_path)
    raw = candidate if candidate.is_absolute() else export_root / candidate

    try:
        resolved = paths.resolve_data_path(raw)
    except ValueError as exc:
        raise ValidationError(
            "Rapor dosyasi yalnizca disa aktarma klasorune yazilabilir.",
            field="output_path",
            detail=str(exc),
        ) from exc

    if resolved != export_root and export_root not in resolved.parents:
        raise ValidationError(
            "Rapor dosyasi yalnizca disa aktarma klasorune yazilabilir.",
            field="output_path",
            detail=f"Hedef disa aktarma klasorunun disinda: {resolved}",
        )

    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def decimal_or_zero(value: Any) -> Decimal:
    """Sorgu sonucundaki ``None`` toplamlarini ``0`` kabul eder.

    ``SUM()`` hicbir satir eslesmediginde ``NULL`` doner; bu deger
    dogrudan ``Money.of`` icine verilirse hata uretir. Bos veri senaryosu
    tam olarak burada cokerdi.
    """
    if value is None:
        return Decimal("0")
    return to_decimal(value)


__all__ = [
    "DATETIME_FORMAT",
    "DATE_FORMAT",
    "EMPTY_TABLE_MESSAGE",
    "CellAlign",
    "CellFormat",
    "KPISet",
    "ReportColumn",
    "ReportTable",
    "decimal_or_zero",
    "format_cell",
    "format_number",
    "neutralize_formula",
    "resolve_export_path",
]
