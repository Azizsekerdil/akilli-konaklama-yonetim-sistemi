"""Oda musaitligi ve rezervasyon cakisma kurallari.

Bu modul, sistemin en kritik is kuralini icerir: **ayni oda ayni gece iki kez
satilamaz.** Kural burada saf fonksiyonlar olarak tanimlanir; veritabani
sorgulari repository katmanindadir. Boylece kural, veritabani olmadan
dogrudan test edilebilir.

Temel semantik :class:`~app.domain.value_objects.DateRange` tarafindan
saglanir: aralik **[giris, cikis)** yari aciktir, yani cikis gunu konaklamaya
dahil degildir. Bu sayede "sabah cikan misafirin odasi ayni gun ogleden sonra
yeni misafire satilabilir" kurali dogal olarak calisir.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from app.core.exceptions import (
    OverlappingReservationError,
    RoomOutOfServiceError,
)
from app.domain.value_objects import DateRange


@dataclass(frozen=True, slots=True)
class Booking:
    """Musaitlik hesabina giren tek bir oda dolulugu.

    Veritabanindaki ``ReservationRoom`` satirlarindan uretilir ama ondan
    bagimsizdir; testlerde elle de olusturulabilir.
    """

    room_id: int
    date_range: DateRange
    reservation_room_id: int | None = None
    reservation_id: int | None = None
    confirmation_number: str | None = None

    @classmethod
    def of(
        cls,
        room_id: int,
        start: date,
        end: date,
        *,
        reservation_room_id: int | None = None,
        reservation_id: int | None = None,
        confirmation_number: str | None = None,
    ) -> Booking:
        """Tarihlerden dogrudan bir :class:`Booking` uretir."""
        return cls(
            room_id=room_id,
            date_range=DateRange(start, end),
            reservation_room_id=reservation_room_id,
            reservation_id=reservation_id,
            confirmation_number=confirmation_number,
        )


@dataclass(frozen=True, slots=True)
class RoomBlock:
    """Odanin bakim/ariza nedeniyle satisa kapali oldugu donem.

    ``date_range`` ``None`` ise blok suresizdir (oda tumuyle envanter disi).
    """

    room_id: int
    date_range: DateRange | None = None
    reason: str | None = None

    def blocks(self, requested: DateRange) -> bool:
        """Istenen aralikta bu blok devrede mi?"""
        if self.date_range is None:
            return True
        return self.date_range.overlaps(requested)


@dataclass(slots=True)
class OccupancyStats:
    """Belirli bir gun icin doluluk istatistikleri."""

    day: date
    total_rooms: int = 0
    """Envanterdeki toplam oda (arizali odalar HARIC)."""

    occupied_rooms: int = 0
    out_of_order_rooms: int = 0
    """Envanterden dusulen (arizali) odalar."""

    @property
    def available_rooms(self) -> int:
        return max(self.total_rooms - self.occupied_rooms, 0)

    @property
    def occupancy_rate(self) -> float:
        """Doluluk orani (0.0 - 1.0).

        Payda olarak **satilabilir** oda sayisi kullanilir; arizali odalar
        paydadan dusulur. Aksi halde bakimdaki odalar isletmeyi haksiz yere
        dusuk doluluklu gosterirdi. Bu, otelcilikteki standart yaklasimdir.
        """
        if self.total_rooms <= 0:
            return 0.0
        return round(self.occupied_rooms / self.total_rooms, 4)

    @property
    def occupancy_percent(self) -> float:
        return round(self.occupancy_rate * 100, 2)


def find_conflicting_bookings(
    requested: DateRange,
    existing: Iterable[Booking],
    *,
    room_id: int,
    exclude_reservation_room_id: int | None = None,
) -> list[Booking]:
    """Istenen aralikla cakisan mevcut rezervasyonlari dondurur.

    Parameters
    ----------
    requested:
        Talep edilen tarih araligi.
    existing:
        Ayni odaya ait, envanteri bloke eden mevcut rezervasyonlar.
    room_id:
        Kontrol edilen fiziksel oda.
    exclude_reservation_room_id:
        **Rezervasyon guncellenirken zorunludur.** Kaydin kendisi
        listede oldugu icin, dislanmazsa kayit kendi kendisiyle cakisir ve
        her guncelleme reddedilirdi.

    >>> from datetime import date
    >>> mevcut = [Booking.of(1, date(2026, 8, 10), date(2026, 8, 12))]
    >>> istenen = DateRange(date(2026, 8, 11), date(2026, 8, 13))
    >>> len(find_conflicting_bookings(istenen, mevcut, room_id=1))
    1
    >>> bitisik = DateRange(date(2026, 8, 12), date(2026, 8, 14))
    >>> find_conflicting_bookings(bitisik, mevcut, room_id=1)
    []
    """
    conflicts: list[Booking] = []
    for booking in existing:
        if booking.room_id != room_id:
            continue
        if (
            exclude_reservation_room_id is not None
            and booking.reservation_room_id == exclude_reservation_room_id
        ):
            continue
        if booking.date_range.overlaps(requested):
            conflicts.append(booking)
    return conflicts


def check_availability(
    requested: DateRange,
    *,
    room_id: int,
    existing_bookings: Iterable[Booking] = (),
    blocks: Iterable[RoomBlock] = (),
    exclude_reservation_room_id: int | None = None,
) -> None:
    """Oda musaitse sessizce doner, degilse anlamli bir hata firlatir.

    Raises
    ------
    RoomOutOfServiceError
        Oda istenen tarihlerde bakim/ariza nedeniyle satisa kapaliysa.
    OverlappingReservationError
        Tarihleri cakisan baska bir rezervasyon varsa.
    """
    for block in blocks:
        if block.room_id == room_id and block.blocks(requested):
            raise RoomOutOfServiceError(
                detail=f"Oda {room_id} {requested.format()} araliginda satisa kapali.",
                context={"room_id": room_id, "reason": block.reason},
            )

    conflicts = find_conflicting_bookings(
        requested,
        existing_bookings,
        room_id=room_id,
        exclude_reservation_room_id=exclude_reservation_room_id,
    )
    if conflicts:
        first = conflicts[0]
        reference = first.confirmation_number or f"#{first.reservation_id}"
        raise OverlappingReservationError(
            f"Bu odada {first.date_range.format()} tarihlerinde {reference} numarali "
            "rezervasyon bulunuyor.",
            detail=f"{len(conflicts)} cakisan kayit bulundu.",
            context={
                "room_id": room_id,
                "requested": requested.format(),
                "conflict_count": len(conflicts),
            },
        )


def is_room_available(
    requested: DateRange,
    *,
    room_id: int,
    existing_bookings: Iterable[Booking] = (),
    blocks: Iterable[RoomBlock] = (),
    exclude_reservation_room_id: int | None = None,
) -> bool:
    """:func:`check_availability`'nin hata firlatmayan, ``bool`` donen surumu."""
    try:
        check_availability(
            requested,
            room_id=room_id,
            existing_bookings=existing_bookings,
            blocks=blocks,
            exclude_reservation_room_id=exclude_reservation_room_id,
        )
    except (OverlappingReservationError, RoomOutOfServiceError):
        return False
    return True


def available_room_ids(
    requested: DateRange,
    *,
    candidate_room_ids: Sequence[int],
    existing_bookings: Iterable[Booking] = (),
    blocks: Iterable[RoomBlock] = (),
) -> list[int]:
    """Aday odalar arasindan istenen tarihlerde musait olanlari dondurur.

    Sonuc, aday listesindeki sirayi korur; boylece cagiran taraf kendi
    onceligini (or. kat, manzara) uygulayabilir.
    """
    bookings = list(existing_bookings)
    block_list = list(blocks)
    return [
        room_id
        for room_id in candidate_room_ids
        if is_room_available(
            requested,
            room_id=room_id,
            existing_bookings=bookings,
            blocks=block_list,
        )
    ]


def free_gaps(
    room_bookings: Iterable[Booking],
    *,
    window: DateRange,
    room_id: int,
) -> list[DateRange]:
    """Bir odanin verilen pencere icindeki bos tarih araliklarini dondurur.

    Oda planı takviminde "bu odaya kac gecelik bosluk sigar" sorusuna yanit
    verir ve bekleme listesi eslestirmesinde kullanilir.

    >>> from datetime import date
    >>> b = [Booking.of(1, date(2026, 8, 5), date(2026, 8, 8))]
    >>> pencere = DateRange(date(2026, 8, 1), date(2026, 8, 15))
    >>> [g.format() for g in free_gaps(b, window=pencere, room_id=1)]
    ['01.08.2026 - 05.08.2026 (4 gece)', '08.08.2026 - 15.08.2026 (7 gece)']
    """
    relevant = sorted(
        (b for b in room_bookings if b.room_id == room_id and b.date_range.overlaps(window)),
        key=lambda b: b.date_range.start,
    )
    gaps: list[DateRange] = []
    cursor = window.start
    for booking in relevant:
        busy = booking.date_range
        if busy.start > cursor:
            gaps.append(DateRange(cursor, min(busy.start, window.end)))
        cursor = max(cursor, busy.end)
        if cursor >= window.end:
            break
    if cursor < window.end:
        gaps.append(DateRange(cursor, window.end))
    return gaps


def compute_occupancy(
    days: Iterable[date],
    *,
    bookings: Iterable[Booking],
    total_rooms: int,
    out_of_order_by_day: dict[date, int] | None = None,
) -> list[OccupancyStats]:
    """Gun bazinda doluluk istatistikleri hesaplar.

    Parameters
    ----------
    days:
        Hesaplanacak gunler.
    bookings:
        Envanteri bloke eden rezervasyonlar.
    total_rooms:
        Tesisin toplam oda sayisi.
    out_of_order_by_day:
        Gun bazinda envanterden dusulecek arizali oda sayisi.
    """
    booking_list = list(bookings)
    ooo = out_of_order_by_day or {}
    results: list[OccupancyStats] = []

    for day in days:
        occupied = sum(1 for b in booking_list if day in b.date_range)
        blocked = ooo.get(day, 0)
        results.append(
            OccupancyStats(
                day=day,
                total_rooms=max(total_rooms - blocked, 0),
                occupied_rooms=occupied,
                out_of_order_rooms=blocked,
            )
        )
    return results


@dataclass(slots=True)
class ArrivalDepartureSummary:
    """Bir gunun giris/cikis/otelde ozeti - yonetim panelinin kaynagi."""

    day: date
    arrivals: list[Booking] = field(default_factory=list)
    departures: list[Booking] = field(default_factory=list)
    stayovers: list[Booking] = field(default_factory=list)
    """Ne giris ne cikis yapan, otelde kalmaya devam edenler."""

    @property
    def arrival_count(self) -> int:
        return len(self.arrivals)

    @property
    def departure_count(self) -> int:
        return len(self.departures)

    @property
    def in_house_count(self) -> int:
        """Gun sonunda otelde olacak oda sayisi."""
        return len(self.arrivals) + len(self.stayovers)


def summarize_day(day: date, bookings: Iterable[Booking]) -> ArrivalDepartureSummary:
    """Verilen gun icin giris, cikis ve devam eden konaklamalari ayirir.

    >>> from datetime import date
    >>> b = [
    ...     Booking.of(1, date(2026, 8, 10), date(2026, 8, 12)),
    ...     Booking.of(2, date(2026, 8, 8), date(2026, 8, 10)),
    ...     Booking.of(3, date(2026, 8, 9), date(2026, 8, 14)),
    ... ]
    >>> ozet = summarize_day(date(2026, 8, 10), b)
    >>> ozet.arrival_count, ozet.departure_count, len(ozet.stayovers)
    (1, 1, 1)
    """
    summary = ArrivalDepartureSummary(day=day)
    for booking in bookings:
        rng = booking.date_range
        if rng.start == day:
            summary.arrivals.append(booking)
        elif rng.end == day:
            summary.departures.append(booking)
        elif day in rng:
            summary.stayovers.append(booking)
    return summary


__all__ = [
    "ArrivalDepartureSummary",
    "Booking",
    "OccupancyStats",
    "RoomBlock",
    "available_room_ids",
    "check_availability",
    "compute_occupancy",
    "find_conflicting_bookings",
    "free_gaps",
    "is_room_available",
    "summarize_day",
]
