"""Deger nesneleri (value objects).

Deger nesneleri kimliksizdir: iki nesne ayni degerlere sahipse esittir ve
olusturulduktan sonra degistirilemezler (immutable). Bu, para ve tarih
hesaplarinda sessiz hatalari onler.

Iki temel deger nesnesi:

* :class:`Money`     - ``float`` yerine ``Decimal`` ile kayipsiz para aritmetigi
* :class:`DateRange` - konaklama tarih araligi ve **cakisma mantigi**
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from app.domain.enums import Currency

#: Para tutarlarinda kullanilan ondalik hassasiyet (kurus).
MONEY_QUANTUM = Decimal("0.01")


def to_decimal(value: Any) -> Decimal:
    """Herhangi bir sayisal degeri guvenle ``Decimal``'e cevirir.

    ``float`` degerler once ``str``'e cevrilir; aksi halde ikili gosterim
    hatalari (0.1 + 0.2 != 0.3) para hesabina sizar.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Sayisal degere cevrilemedi: {value!r}") from exc


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """Para tutari - miktar + para birimi.

    Farkli para birimlerindeki tutarlar toplanmaya calisildiginda hata verir;
    boylece ``100 TRY + 50 EUR = 150`` gibi sessiz bir hata olusamaz.

    >>> Money.of("100.005")            # yukari yuvarlama (bankaci degil, ticari)
    Money(amount=Decimal('100.01'), currency=<Currency.TRY: 'TRY'>)
    >>> Money.of(100, Currency.TRY) + Money.of(50, Currency.TRY)
    Money(amount=Decimal('150.00'), currency=<Currency.TRY: 'TRY'>)
    """

    amount: Decimal
    currency: Currency = Currency.TRY

    # ---------------- Olusturucular ----------------
    @classmethod
    def of(cls, amount: Any, currency: Currency | str = Currency.TRY) -> Money:
        """Herhangi bir sayisal degerden ``Money`` uretir ve kurusa yuvarlar."""
        cur = Currency(currency) if not isinstance(currency, Currency) else currency
        return cls(to_decimal(amount).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP), cur)

    @classmethod
    def zero(cls, currency: Currency | str = Currency.TRY) -> Money:
        """Sifir tutar."""
        return cls.of(0, currency)

    # ---------------- Aritmetik ----------------
    def _check_currency(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise ValueError(
                f"Farkli para birimleri islenemez: {self.currency.value} / {other.currency.value}"
            )

    def __add__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money.of(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money.of(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Any) -> Money:
        return Money.of(self.amount * to_decimal(factor), self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor: Any) -> Money:
        d = to_decimal(divisor)
        if d == 0:
            raise ZeroDivisionError("Para tutari sifira bolunemez.")
        return Money.of(self.amount / d, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    # ---------------- Karsilastirma ----------------
    def __lt__(self, other: Money) -> bool:
        self._check_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._check_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._check_currency(other)
        return self.amount >= other.amount

    # ---------------- Ozellikler ----------------
    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def allocate(self, parts: int) -> list[Money]:
        """Tutari ``parts`` esit parcaya boler, **kurus kaybi olmadan**.

        Artan kurusler ilk parcalara dagitilir; parcalarin toplami her zaman
        orijinal tutara esittir.

        >>> [str(m.amount) for m in Money.of("10.00").allocate(3)]
        ['3.34', '3.33', '3.33']
        """
        if parts < 1:
            raise ValueError("Parca sayisi en az 1 olmalidir.")
        cents = int((self.amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
        base, remainder = divmod(abs(cents), parts)
        sign = -1 if cents < 0 else 1
        result: list[Money] = []
        for index in range(parts):
            share = base + (1 if index < remainder else 0)
            # quantize sart: Decimal(2500)/100 -> Decimal('25') olur ve iki
            # ondalikli gosterim ("25.00") kaybolur. Money her zaman kurus
            # hassasiyetinde olmalidir.
            amount = (Decimal(sign * share) / 100).quantize(MONEY_QUANTUM)
            result.append(Money(amount, self.currency))
        return result

    def with_tax(self, rate_percent: Any) -> Money:
        """Uzerine yuzde ``rate_percent`` vergi ekler."""
        return self * (1 + to_decimal(rate_percent) / 100)

    def tax_part(self, rate_percent: Any) -> Money:
        """Tutar **vergi dahil** ise, icindeki vergi tutarini hesaplar."""
        rate = to_decimal(rate_percent)
        return Money.of(self.amount * rate / (100 + rate), self.currency)

    # ---------------- Gosterim ----------------
    def format(self, *, with_symbol: bool = True, thousands: bool = True) -> str:
        """Turkce yerel bicimde gosterir: ``1.234,56 ₺``."""
        raw = f"{abs(self.amount):,.2f}"
        # Ingilizce ayiricilari Turkce'ye cevir: 1,234.56 -> 1.234,56
        raw = raw.replace(",", "\x00").replace(".", ",").replace("\x00", "." if thousands else "")
        sign = "-" if self.is_negative else ""
        return f"{sign}{raw} {self.currency.symbol}" if with_symbol else f"{sign}{raw}"

    def __str__(self) -> str:
        return self.format()


@dataclass(frozen=True, slots=True)
class DateRange:
    """Konaklama tarih araligi - **[start, end)** yari acik aralik.

    Otelcilikte cikis gunu konaklamaya dahil degildir: 10-12 Agustos
    rezervasyonu 2 gece surer ve 12 Agustos'ta oda yeni misafire satilabilir.
    Bu sinif tam olarak bu semantigi uygular.

    >>> DateRange(date(2026, 8, 10), date(2026, 8, 12)).nights
    2
    >>> a = DateRange(date(2026, 8, 10), date(2026, 8, 12))
    >>> b = DateRange(date(2026, 8, 12), date(2026, 8, 14))
    >>> a.overlaps(b)          # cikis gunu = giris gunu -> cakisma YOK
    False
    >>> c = DateRange(date(2026, 8, 11), date(2026, 8, 13))
    >>> a.overlaps(c)          # bir gece ortak -> cakisma VAR
    True
    """

    start: date
    """Giris tarihi - araliga dahildir."""

    end: date
    """Cikis tarihi - araliga **dahil degildir**."""

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or not isinstance(self.end, date):
            raise TypeError("DateRange yalnizca 'date' nesneleri kabul eder.")
        if self.end <= self.start:
            raise ValueError(
                f"Cikis tarihi giris tarihinden sonra olmalidir "
                f"(giris={self.start.isoformat()}, cikis={self.end.isoformat()})."
            )

    # ---------------- Temel ozellikler ----------------
    @property
    def nights(self) -> int:
        """Konaklama gece sayisi."""
        return (self.end - self.start).days

    @property
    def days(self) -> list[date]:
        """Konaklanan gunlerin listesi (cikis gunu **haric**)."""
        return list(self)

    def __iter__(self) -> Iterator[date]:
        current = self.start
        while current < self.end:
            yield current
            current += timedelta(days=1)

    def __len__(self) -> int:
        return self.nights

    def __contains__(self, day: object) -> bool:
        """Bir gunun konaklamaya dahil olup olmadigi (cikis gunu haric)."""
        if not isinstance(day, date):
            return False
        return self.start <= day < self.end

    # ---------------- Cakisma mantigi ----------------
    def overlaps(self, other: DateRange) -> bool:
        """Iki aralik en az bir gece paylasiyor mu?

        Yari acik aralik kurali: ``self.start < other.end and other.start < self.end``.
        Bu, rezervasyon cakisma kontrolunun tek dogruluk kaynagidir.
        """
        return self.start < other.end and other.start < self.end

    def is_adjacent_to(self, other: DateRange) -> bool:
        """Araliklar birbirine bitisik mi (biri bitince digeri basliyor)?"""
        return self.end == other.start or other.end == self.start

    def intersection(self, other: DateRange) -> DateRange | None:
        """Ortak araligi dondurur; kesisim yoksa ``None``."""
        if not self.overlaps(other):
            return None
        return DateRange(max(self.start, other.start), min(self.end, other.end))

    def overlapping_nights(self, other: DateRange) -> int:
        """Kac gece ortak? Kesisim yoksa 0."""
        common = self.intersection(other)
        return common.nights if common else 0

    def contains_range(self, other: DateRange) -> bool:
        """``other`` tamamen bu araligin icinde mi?"""
        return self.start <= other.start and other.end <= self.end

    # ---------------- Donusumler ----------------
    def shift(self, days: int) -> DateRange:
        """Araligi ``days`` gun kaydirir."""
        delta = timedelta(days=days)
        return DateRange(self.start + delta, self.end + delta)

    def extend_end(self, nights: int) -> DateRange:
        """Cikis tarihini ``nights`` gece uzatir (gec cikis / uzatma)."""
        return DateRange(self.start, self.end + timedelta(days=nights))

    def extend_start(self, nights: int) -> DateRange:
        """Giris tarihini ``nights`` gece one ceker (erken giris)."""
        return DateRange(self.start - timedelta(days=nights), self.end)

    @classmethod
    def of_nights(cls, start: date, nights: int) -> DateRange:
        """Giris tarihi ve gece sayisindan aralik uretir."""
        if nights < 1:
            raise ValueError("Gece sayisi en az 1 olmalidir.")
        return cls(start, start + timedelta(days=nights))

    @classmethod
    def single_night(cls, start: date) -> DateRange:
        """Tek gecelik aralik."""
        return cls.of_nights(start, 1)

    # ---------------- Gosterim ----------------
    def format(self) -> str:
        """``10.08.2026 - 12.08.2026 (2 gece)``"""
        return (
            f"{self.start.strftime('%d.%m.%Y')} - {self.end.strftime('%d.%m.%Y')} "
            f"({self.nights} gece)"
        )

    def __str__(self) -> str:
        return self.format()


def any_overlap(ranges: list[DateRange]) -> tuple[DateRange, DateRange] | None:
    """Listedeki ilk cakisan aralik ciftini dondurur; yoksa ``None``.

    Grup rezervasyonlarinda ayni odaya birden fazla tarih araligi eklenirken
    kullanilir. Karmasiklik: siralama sonrasi O(n log n).
    """
    ordered = sorted(ranges, key=lambda r: (r.start, r.end))
    for previous, current in pairwise(ordered):
        if previous.overlaps(current):
            return previous, current
    return None


def merge_ranges(ranges: list[DateRange]) -> list[DateRange]:
    """Cakisan/bitisik araliklari birlestirir.

    Oda musaitlik takvimini cizerken ardisik dolu bloklarin tek parca
    gosterilmesi icin kullanilir.
    """
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: (r.start, r.end))
    merged = [ordered[0]]
    for current in ordered[1:]:
        last = merged[-1]
        if last.overlaps(current) or last.is_adjacent_to(current):
            merged[-1] = DateRange(last.start, max(last.end, current.end))
        else:
            merged.append(current)
    return merged


__all__ = [
    "MONEY_QUANTUM",
    "DateRange",
    "Money",
    "any_overlap",
    "merge_ranges",
    "to_decimal",
]
