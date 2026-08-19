"""Fiyatlandirma kurallari: sezonluk fiyat, ekstra kisi, indirim, vergi, iptal ucreti.

Fiyat **gece gece** hesaplanir. Sabit bir gecelik ucreti gece sayisiyla
carpmak, sezon gecisi olan konaklamalarda (or. 30 Haziran - 2 Temmuz) yanlis
sonuc verir. Burada her gun icin gecerli kural ayri ayri secilir ve toplanir;
boylece dokum misafire de kalem kalem gosterilebilir.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.exceptions import ValidationError
from app.domain.enums import Currency
from app.domain.value_objects import DateRange, Money, to_decimal

#: Tum haftanin gunleri (bit 0 = Pazartesi ... bit 6 = Pazar).
ALL_WEEKDAYS = 0b1111111


@dataclass(frozen=True, slots=True)
class RateRule:
    """Belirli bir donem icin gecelik ucret kurali.

    Veritabanindaki ``RatePlanRate`` satirlarindan uretilir; testlerde elle de
    olusturulabilir.
    """

    amount: Decimal
    valid_from: date
    valid_to: date
    """Dahil (inclusive) bitis tarihi."""

    weekday_mask: int = ALL_WEEKDAYS
    min_nights: int | None = None
    max_nights: int | None = None
    priority: int = 0
    """Ayni gun icin birden fazla kural gecerliyse buyuk olan kazanir."""

    season_name: str | None = None
    rate_plan_code: str | None = None

    def applies_on(self, day: date, *, nights: int | None = None) -> bool:
        """Kural verilen gun (ve konaklama uzunlugu) icin gecerli mi?"""
        if not (self.valid_from <= day <= self.valid_to):
            return False
        if not (self.weekday_mask >> day.weekday()) & 1:
            return False
        if nights is not None:
            if self.min_nights is not None and nights < self.min_nights:
                return False
            if self.max_nights is not None and nights > self.max_nights:
                return False
        return True


@dataclass(frozen=True, slots=True)
class NightlyRate:
    """Tek bir gecenin fiyati ve hangi kuraldan geldigi."""

    day: date
    amount: Money
    source: str
    """Or. 'Yuksek Sezon', 'Taban fiyat'."""

    @property
    def weekday_name(self) -> str:
        return ("Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar")[
            self.day.weekday()
        ]


@dataclass(slots=True)
class PriceBreakdown:
    """Konaklama fiyatinin kalem kalem dokumu."""

    nights: list[NightlyRate] = field(default_factory=list)
    currency: Currency = Currency.TRY

    extra_adult_total: Money = field(default=None)  # type: ignore[assignment]
    extra_child_total: Money = field(default=None)  # type: ignore[assignment]
    discount_amount: Money = field(default=None)  # type: ignore[assignment]
    tax_amount: Money = field(default=None)  # type: ignore[assignment]
    tax_rate_percent: Decimal = Decimal("0.00")
    tax_included_in_rate: bool = True

    def __post_init__(self) -> None:
        zero = Money.zero(self.currency)
        if self.extra_adult_total is None:
            self.extra_adult_total = zero
        if self.extra_child_total is None:
            self.extra_child_total = zero
        if self.discount_amount is None:
            self.discount_amount = zero
        if self.tax_amount is None:
            self.tax_amount = zero

    # ---------------- Turetilmis toplamlar ----------------
    @property
    def night_count(self) -> int:
        return len(self.nights)

    @property
    def room_subtotal(self) -> Money:
        """Yalnizca oda ucretlerinin toplami."""
        return sum((n.amount for n in self.nights), start=Money.zero(self.currency))

    @property
    def gross_subtotal(self) -> Money:
        """Oda + ekstra kisi ucretleri (indirim ve vergi oncesi)."""
        return self.room_subtotal + self.extra_adult_total + self.extra_child_total

    @property
    def net_subtotal(self) -> Money:
        """Indirim sonrasi, vergi haric tutar."""
        return self.gross_subtotal - self.discount_amount

    @property
    def total(self) -> Money:
        """Misafirin odeyecegi nihai tutar.

        Fiyat vergi dahil ilan edilmisse (``tax_included_in_rate``) vergi
        ayrica eklenmez; yalnizca icindeki vergi payi bilgi olarak gosterilir.
        """
        if self.tax_included_in_rate:
            return self.net_subtotal
        return self.net_subtotal + self.tax_amount

    @property
    def average_nightly_rate(self) -> Money:
        """Ortalama gecelik ucret (ADR hesabinin girdisi)."""
        if not self.nights:
            return Money.zero(self.currency)
        return self.total / self.night_count

    def as_lines(self) -> list[tuple[str, Money]]:
        """Arayuzde/PDF'te gosterilecek ozet satirlari."""
        lines: list[tuple[str, Money]] = [
            (f"Oda ucreti ({self.night_count} gece)", self.room_subtotal),
        ]
        if not self.extra_adult_total.is_zero:
            lines.append(("Ekstra yetiskin", self.extra_adult_total))
        if not self.extra_child_total.is_zero:
            lines.append(("Ekstra cocuk", self.extra_child_total))
        if not self.discount_amount.is_zero:
            lines.append(("Indirim", -self.discount_amount))
        if not self.tax_amount.is_zero:
            label = "Vergi (fiyata dahil)" if self.tax_included_in_rate else "Vergi"
            lines.append((label, self.tax_amount))
        lines.append(("TOPLAM", self.total))
        return lines


def select_rate_for_day(
    day: date,
    rules: Sequence[RateRule],
    *,
    nights: int | None = None,
) -> RateRule | None:
    """Bir gun icin gecerli en oncelikli kurali secer.

    Esitlik durumunda daha **dar** donemli kural kazanir; ozel bir bayram
    fiyati, genis bir sezon fiyatini ezmelidir.
    """
    applicable = [r for r in rules if r.applies_on(day, nights=nights)]
    if not applicable:
        return None
    return max(
        applicable,
        key=lambda r: (r.priority, -(r.valid_to - r.valid_from).days),
    )


def calculate_stay_price(
    date_range: DateRange,
    *,
    rules: Iterable[RateRule] = (),
    base_rate: Decimal | float | str = Decimal("0.00"),
    currency: Currency = Currency.TRY,
    adults: int = 2,
    children: int = 0,
    base_occupancy: int = 2,
    extra_adult_rate: Decimal | float | str = Decimal("0.00"),
    extra_child_rate: Decimal | float | str = Decimal("0.00"),
    discount_percent: Decimal | float | str = Decimal("0.00"),
    tax_rate_percent: Decimal | float | str = Decimal("0.00"),
    tax_included_in_rate: bool = True,
) -> PriceBreakdown:
    """Bir konaklamanin fiyatini gece gece hesaplar.

    Parameters
    ----------
    date_range:
        Konaklama araligi (cikis gunu haric).
    rules:
        Sezonluk fiyat kurallari. Bos ise ``base_rate`` kullanilir.
    base_rate:
        Hicbir kural uymadiginda kullanilacak taban gecelik ucret.
    adults, children:
        Kisi sayilari. ``base_occupancy`` uzerindeki yetiskinler icin
        ``extra_adult_rate`` her gece uygulanir.
    tax_included_in_rate:
        Turkiye'de otel fiyatlari genellikle vergi dahil ilan edilir. ``True``
        ise vergi tutari fiyatin **icinden** ayristirilir, uzerine eklenmez.

    >>> from datetime import date
    >>> d = DateRange(date(2026, 8, 10), date(2026, 8, 13))
    >>> b = calculate_stay_price(d, base_rate="1000", tax_rate_percent="10")
    >>> b.night_count, str(b.total)
    (3, '3.000,00 ₺')
    >>> str(b.tax_amount)
    '272,73 ₺'
    """
    rule_list = list(rules)
    nights = date_range.nights
    base = Money.of(base_rate, currency)

    breakdown = PriceBreakdown(
        currency=currency,
        tax_rate_percent=to_decimal(tax_rate_percent),
        tax_included_in_rate=tax_included_in_rate,
    )

    for day in date_range:
        rule = select_rate_for_day(day, rule_list, nights=nights)
        if rule is not None:
            breakdown.nights.append(
                NightlyRate(
                    day=day,
                    amount=Money.of(rule.amount, currency),
                    source=rule.season_name or rule.rate_plan_code or "Fiyat plani",
                )
            )
        else:
            breakdown.nights.append(NightlyRate(day=day, amount=base, source="Taban fiyat"))

    # ---- Ekstra kisi ----
    extra_adults = max(adults - base_occupancy, 0)
    if extra_adults:
        breakdown.extra_adult_total = Money.of(extra_adult_rate, currency) * extra_adults * nights
    if children:
        breakdown.extra_child_total = Money.of(extra_child_rate, currency) * children * nights

    # ---- Indirim ----
    discount = to_decimal(discount_percent)
    if discount < 0 or discount > 100:
        raise ValidationError("Indirim orani 0-100 arasinda olmalidir.", field="discount_percent")
    if discount > 0:
        breakdown.discount_amount = breakdown.gross_subtotal * (discount / 100)

    # ---- Vergi ----
    rate = to_decimal(tax_rate_percent)
    if rate > 0:
        net = breakdown.net_subtotal
        breakdown.tax_amount = net.tax_part(rate) if tax_included_in_rate else net * (rate / 100)

    return breakdown


def calculate_cancellation_fee(
    total_amount: Money,
    *,
    hours_before_arrival: float,
    is_refundable: bool = True,
    free_cancellation_hours: int = 24,
    cancellation_fee_percent: Decimal | float | str = Decimal("0.00"),
    is_no_show: bool = False,
    no_show_fee_percent: Decimal | float | str = Decimal("100.00"),
) -> Money:
    """Iptal veya gelmeme (no-show) ucretini hesaplar.

    Kurallar
    --------
    * **Gelmedi (no-show)**: ``no_show_fee_percent`` uygulanir; ucretsiz iptal
      penceresi dikkate alinmaz.
    * **Iade edilemez tarife**: her zaman tam tutar tahsil edilir.
    * **Ucretsiz iptal penceresi icinde**: ucret alinmaz.
    * **Pencere disinda**: ``cancellation_fee_percent`` uygulanir.

    >>> t = Money.of("2000")
    >>> str(calculate_cancellation_fee(t, hours_before_arrival=48))
    '0,00 ₺'
    >>> str(calculate_cancellation_fee(t, hours_before_arrival=5,
    ...       cancellation_fee_percent="50"))
    '1.000,00 ₺'
    >>> str(calculate_cancellation_fee(t, hours_before_arrival=100,
    ...       is_refundable=False))
    '2.000,00 ₺'
    >>> str(calculate_cancellation_fee(t, hours_before_arrival=-2, is_no_show=True))
    '2.000,00 ₺'
    """
    if is_no_show:
        return total_amount * (to_decimal(no_show_fee_percent) / 100)

    if not is_refundable:
        return total_amount

    if hours_before_arrival >= free_cancellation_hours:
        return Money.zero(total_amount.currency)

    return total_amount * (to_decimal(cancellation_fee_percent) / 100)


def calculate_early_late_fee(
    nightly_rate: Money,
    *,
    hours: int,
    percent_per_block: Decimal | float | str = Decimal("25.00"),
    block_hours: int = 3,
    max_percent: Decimal | float | str = Decimal("100.00"),
) -> Money:
    """Erken giris / gec cikis ucretini hesaplar.

    Her ``block_hours`` saatlik dilim icin gecelik ucretin
    ``percent_per_block`` kadari alinir; toplam ``max_percent`` ile sinirlanir.

    >>> str(calculate_early_late_fee(Money.of("1000"), hours=4))
    '500,00 ₺'
    >>> str(calculate_early_late_fee(Money.of("1000"), hours=20))
    '1.000,00 ₺'
    """
    if hours <= 0:
        return Money.zero(nightly_rate.currency)
    blocks = -(-hours // block_hours)  # yukari yuvarlayan tam bolme
    percent = min(to_decimal(percent_per_block) * blocks, to_decimal(max_percent))
    return nightly_rate * (percent / 100)


__all__ = [
    "ALL_WEEKDAYS",
    "NightlyRate",
    "PriceBreakdown",
    "RateRule",
    "calculate_cancellation_fee",
    "calculate_early_late_fee",
    "calculate_stay_price",
    "select_rate_for_day",
]
