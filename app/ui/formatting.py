"""Turkce yerel bicimlendirme yardimcilari.

Python'un ``strftime("%B")`` cagrisi isletim sisteminin yerel ayarina baglidir
ve Windows'ta cogu zaman Ingilizce ay adi dondurur ("15 August 2026").
``locale.setlocale`` ile degistirmek surec genelinde yan etki yaratir (sayi
ayiricilarini da degistirir ve is parcaciklarinda guvenli degildir), bu yuzden
ay ve gun adlarini burada acikca tanimliyoruz.
"""

from __future__ import annotations

from datetime import date, datetime

MONTHS_TR: tuple[str, ...] = (
    "Ocak",
    "Subat",
    "Mart",
    "Nisan",
    "Mayis",
    "Haziran",
    "Temmuz",
    "Agustos",
    "Eylul",
    "Ekim",
    "Kasim",
    "Aralik",
)

DAYS_TR: tuple[str, ...] = (
    "Pazartesi",
    "Sali",
    "Carsamba",
    "Persembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
)

MONTHS_SHORT_TR: tuple[str, ...] = (
    "Oca",
    "Sub",
    "Mar",
    "Nis",
    "May",
    "Haz",
    "Tem",
    "Agu",
    "Eyl",
    "Eki",
    "Kas",
    "Ara",
)


def format_date(value: date | None, *, with_day_name: bool = False) -> str:
    """``15 Agustos 2026`` bicimi.

    >>> from datetime import date
    >>> format_date(date(2026, 8, 15))
    '15 Agustos 2026'
    >>> format_date(date(2026, 8, 15), with_day_name=True)
    '15 Agustos 2026, Cumartesi'
    >>> format_date(None)
    '-'
    """
    if value is None:
        return "-"
    text = f"{value.day} {MONTHS_TR[value.month - 1]} {value.year}"
    if with_day_name:
        text += f", {DAYS_TR[value.weekday()]}"
    return text


def format_short_date(value: date | None) -> str:
    """``15.08.2026`` bicimi (tablolar icin kompakt)."""
    return value.strftime("%d.%m.%Y") if value else "-"


def format_datetime(value: datetime | None) -> str:
    """``15.08.2026 14:30`` bicimi."""
    return value.strftime("%d.%m.%Y %H:%M") if value else "-"


def format_day_month(value: date | None) -> str:
    """``15 Agu`` bicimi (grafik eksenleri icin)."""
    if value is None:
        return "-"
    return f"{value.day} {MONTHS_SHORT_TR[value.month - 1]}"


def format_percent(value: float | None, *, decimals: int = 1) -> str:
    """``%42,1`` bicimi - Turkce ondalik ayiricisi ile."""
    if value is None:
        return "-"
    return f"%{value:.{decimals}f}".replace(".", ",")


def format_number(value: float | int | None, *, decimals: int = 0) -> str:
    """``1.234,56`` bicimi.

    >>> format_number(1234567.891, decimals=2)
    '1.234.567,89'
    >>> format_number(42)
    '42'
    """
    if value is None:
        return "-"
    raw = f"{value:,.{decimals}f}"
    return raw.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_path(value, *, home_symbol: str = "~") -> str:
    """Dosya yolunu **kullanici adini sizdirmadan** gosterime hazirlar.

    Neden gerekli?
    --------------
    Yayin oncesi denetimde, tanitim sunumundaki AI Gelistirme Merkezi
    ekraninda tam yol goruntulendi ve icinde gelistiricinin Windows kullanici
    adi vardi (``C:/Users/<ad>/...`` bicimindeki tam yol). Ekran goruntusu, destek talebine
    yapistirilan bir cikti ya da bir hata raporu, gereksiz yere kisisel bir
    tanimlayici tasimamalidir. Yol bilgisinin kendisi kullaniciya lazimdir;
    kullanici adi degildir.

    >>> import os
    >>> format_path(os.path.expanduser("~") + os.sep + "proje").startswith("~")
    True
    """
    import os

    metin = str(value)
    ev = os.path.expanduser("~")
    if ev and metin.lower().startswith(ev.lower()):
        return home_symbol + metin[len(ev) :]
    return metin


def format_nights(nights: int) -> str:
    """``3 gece`` bicimi."""
    return f"{nights} gece"


__all__ = [
    "DAYS_TR",
    "MONTHS_SHORT_TR",
    "MONTHS_TR",
    "format_date",
    "format_datetime",
    "format_day_month",
    "format_nights",
    "format_number",
    "format_path",
    "format_percent",
    "format_short_date",
]
