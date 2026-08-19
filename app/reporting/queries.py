"""Rapor sorgulari - veritabanindan :class:`ReportTable` ve KPI uretir.

Katman notu
-----------
Bu modul repository katmanina **bagimli degildir**; dogrudan SQLAlchemy
``select()`` kullanir. Neden? Raporlar, is nesnelerini tek tek yuklemek
yerine veritabaninda gruplayip toplamak zorundadir. Bir repository'nin
"tum rezervasyonlari getir, sonra Python'da topla" yaklasimi, birkac bin
kayitta bile kabul edilemez hale gelir. Toplama isi veritabaninin isidir.

Zaman dilimi tuzagi
-------------------
``charge_date``, ``entry_date`` gibi alanlar ``Date``'tir ve dogrudan
karsilastirilir. Buna karsin ``paid_at`` ve ``reported_at`` ``TZDateTime``
(UTC) alanlaridir; bir "gun" suzgeci icin UTC gun sinirlarina cevrilir.
Tesis yerel saatiyle gun sonu almak isteyen bir isletme icin bu sinirlarin
kaydirilmasi gerekir: :func:`_range_bounds` tesisin saat dilimini alacak
sekilde genisletilmelidir. Turkiye (UTC+3) icin gece 03:00'ten once islenen
tahsilatlar su an bir onceki gune duser.

Gelir tabani
------------
Gelir toplamlari ``Charge.total_amount`` (**vergi dahil**) uzerindendir.
ADR/RevPAR'i vergi haric isteyen isletmeler ``Charge.net_amount``
kullanmalidir; ``revenue_by_*`` raporlari net ve vergi sutunlarini zaten
ayri gosterir. Ayrica TAX / CITY_TAX ayri satir olarak isleniyorsa bu
tutarlar "diger gelir" icinde gorunur - vergi gelir degildir, net/brut
ayrimi isteyen isletme icin ek suzgec gerekir.

Tarih araligi semantigi
-----------------------
Tum aralik suzgecleri :class:`~app.domain.value_objects.DateRange` ile
uyumlu **[baslangic, bitis)** yari aciktir: cikis gunu dahil degildir.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session, aliased

from app.core.exceptions import NotFoundError
from app.domain.enums import (
    BLOCKING_RESERVATION_STATUSES,
    ChargeType,
    Currency,
    ReservationStatus,
    RoomHousekeepingStatus,
    TransactionDirection,
)
from app.domain.value_objects import DateRange, Money
from app.infrastructure.db.models import (
    CashRegisterEntry,
    Charge,
    Employee,
    Folio,
    Guest,
    HousekeepingTask,
    InventoryItem,
    MaintenanceTicket,
    Payment,
    Property,
    Reservation,
    ReservationRoom,
    Room,
    RoomType,
)
from app.reporting import kpi
from app.reporting.models import (
    KPISet,
    ReportColumn,
    ReportTable,
    decimal_or_zero,
)

#: Raporlarda "gerceklesmis ya da gerceklesecek konaklama" sayilan durumlar.
#:
#: Envanteri bloke eden durumlara (:data:`BLOCKING_RESERVATION_STATUSES`)
#: ``CHECKED_OUT`` eklenir. **Bu ayrim raporlamanin en kritik noktasidir:**
#: bloke etme kavrami *gelecege* bakar - cikis yapmis bir rezervasyon artik
#: oda tutmaz, bu yuzden musaitlik hesabinda yer almaz. Raporlar ise
#: *gecmise* bakar; gecen ayin butun konaklamalari ``CHECKED_OUT``
#: durumundadir. Yalnizca bloke eden durumlara bakan bir rapor, gecmis her
#: donem icin doluluk ``%0`` ve ADR ``0`` uretirdi - gelir satirlari
#: dolu goruncuken.
#:
#: ``CANCELLED`` ve ``NO_SHOW`` bilincli olarak **disaridadir**: iptal ya da
#: gelmeme durumunda oda satilmamistir; bunlari saymak dolulugu sisirir.
#: Bu iki durum yalnizca iptal/no-show oranlarinin payinda kullanilir.
OPERATIONAL_RESERVATION_STATUSES: frozenset[ReservationStatus] = frozenset(
    BLOCKING_RESERVATION_STATUSES | {ReservationStatus.CHECKED_OUT}
)


# ==========================================================================
#  Ortak yardimcilar
# ==========================================================================
def _property(session: Session, property_id: int) -> Property | None:
    """Tesisi getirir. Kimlik haritasi sayesinde tekrar cagri ucuzdur."""
    return session.get(Property, property_id)


def _property_name(session: Session, property_id: int) -> str:
    prop = _property(session, property_id)
    return prop.name if prop is not None else f"Tesis #{property_id}"


def _property_currency(session: Session, property_id: int) -> Currency:
    prop = _property(session, property_id)
    return prop.default_currency if prop is not None else Currency.TRY


def _range_bounds(date_range: DateRange) -> tuple[datetime, datetime]:
    """Tarih araliginin UTC zaman damgasi sinirlari - bitis haric."""
    return (
        datetime.combine(date_range.start, time.min, tzinfo=UTC),
        datetime.combine(date_range.end, time.min, tzinfo=UTC),
    )


def _occupied_room_rows(property_id: int, date_range: DateRange) -> Select[Any]:
    """Donemle kesisen, odanin gercekten satildigi oda satirlarini secer.

    Durum suzgeci :data:`OPERATIONAL_RESERVATION_STATUSES`'tir,
    ``BLOCKING_RESERVATION_STATUSES`` **degil**. Gerekce oradaki notta
    aciklanmistir: cikis yapmis konaklamalar envanteri bloke etmez ama
    gecmis donem raporunun tamamini olustururlar.

    Cakisma kosulu :meth:`DateRange.overlaps` ile ayni yari acik mantiktir:
    ``giris < donem_bitisi AND cikis > donem_baslangici``. Esitlik
    kullanilsaydi, cikis gunu donem baslangicina denk gelen rezervasyonlar
    yanlislikla sayilirdi.
    """
    return (
        select(ReservationRoom)
        .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
        .where(
            Reservation.property_id == property_id,
            Reservation.is_deleted.is_(False),
            Reservation.status.in_(tuple(OPERATIONAL_RESERVATION_STATUSES)),
            ReservationRoom.is_cancelled.is_(False),
            ReservationRoom.check_in_date < date_range.end,
            ReservationRoom.check_out_date > date_range.start,
        )
    )


def _charge_filters(property_id: int, date_range: DateRange) -> list[Any]:
    """Gecerli (gecersiz kilinmamis) ucret satirlarinin ortak suzgeci."""
    return [
        Folio.property_id == property_id,
        Charge.is_void.is_(False),
        Charge.charge_date >= date_range.start,
        Charge.charge_date < date_range.end,
    ]


def _active_rooms(session: Session, property_id: int) -> list[Room]:
    return list(
        session.scalars(
            select(Room).where(Room.property_id == property_id, Room.is_active.is_(True))
        ).all()
    )


def _out_of_order_room_nights(rooms: list[Room], date_range: DateRange) -> int:
    """Arizali odalarin donem icindeki toplam gece sayisi.

    Yalnizca ``OUT_OF_ORDER`` sayilir; ``OUT_OF_SERVICE`` odalar envanterde
    kalir (bkz. :class:`app.domain.enums.RoomHousekeepingStatus`).
    """
    total = 0
    for room in rooms:
        if room.housekeeping_status is not RoomHousekeepingStatus.OUT_OF_ORDER:
            continue
        total += sum(1 for day in date_range if room.is_out_of_service_on(day))
    return total


# ==========================================================================
#  Doluluk
# ==========================================================================
def occupancy_report(session: Session, property_id: int, date_range: DateRange) -> ReportTable:
    """Gun bazinda doluluk raporu.

    Her gun icin toplam oda, arizali oda, satilabilir oda, dolu oda ve
    doluluk yuzdesi hesaplanir. Doluluk paydasi **satilabilir** odadir;
    gerekcesi :func:`app.reporting.kpi.occupancy_rate` icinde aciklanmistir.
    """
    columns = [
        ReportColumn("gun", "Tarih", align="left", format="date"),
        ReportColumn("toplam_oda", "Toplam Oda", align="right", format="integer"),
        ReportColumn("arizali_oda", "Arizali", align="right", format="integer"),
        ReportColumn("satilabilir_oda", "Satilabilir", align="right", format="integer"),
        ReportColumn("dolu_oda", "Dolu", align="right", format="integer"),
        ReportColumn("bos_oda", "Bos", align="right", format="integer"),
        ReportColumn("doluluk", "Doluluk", align="right", format="percent"),
    ]

    rooms = _active_rooms(session, property_id)
    total_rooms = len(rooms)
    room_rows = list(session.scalars(_occupied_room_rows(property_id, date_range)).all())

    rows: list[dict[str, Any]] = []
    for day in date_range:
        out_of_order = sum(
            1
            for room in rooms
            if room.housekeeping_status is RoomHousekeepingStatus.OUT_OF_ORDER
            and room.is_out_of_service_on(day)
        )
        sellable = max(total_rooms - out_of_order, 0)
        occupied = sum(1 for row in room_rows if row.check_in_date <= day < row.check_out_date)
        rows.append(
            {
                "gun": day,
                "toplam_oda": total_rooms,
                "arizali_oda": out_of_order,
                "satilabilir_oda": sellable,
                "dolu_oda": occupied,
                "bos_oda": max(sellable - occupied, 0),
                "doluluk": round(kpi.occupancy_rate(occupied, sellable) * 100, 2),
            }
        )

    return ReportTable(
        title="Doluluk Raporu",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=date_range.format(),
    )


# ==========================================================================
#  Gelir raporlari
# ==========================================================================
def revenue_by_channel(session: Session, property_id: int, date_range: DateRange) -> ReportTable:
    """Rezervasyon kanaline gore gelir dagilimi.

    Folyosu rezervasyona bagli olmayan ucretler (or. gecici bar hesabi)
    ``outerjoin`` sayesinde kaybolmaz; "Belirtilmemis" kanalinda toplanir.
    Ic birlestirme kullanilsaydi rapor toplami folyo toplamini tutmazdi.
    """
    columns = [
        ReportColumn("kanal", "Kanal", align="left"),
        ReportColumn("adet", "Kalem", align="right", format="integer"),
        ReportColumn("net", "Net Tutar", align="right", format="money"),
        ReportColumn("vergi", "Vergi", align="right", format="money"),
        ReportColumn("toplam", "Toplam", align="right", format="money"),
    ]
    currency = _property_currency(session, property_id)

    stmt = (
        select(
            Reservation.source,
            func.count(Charge.id),
            func.sum(Charge.net_amount),
            func.sum(Charge.tax_amount),
            func.sum(Charge.total_amount),
        )
        .select_from(Charge)
        .join(Folio, Charge.folio_id == Folio.id)
        .outerjoin(Reservation, Folio.reservation_id == Reservation.id)
        .where(*_charge_filters(property_id, date_range))
        .group_by(Reservation.source)
        .order_by(func.sum(Charge.total_amount).desc())
    )

    rows = [
        {
            "kanal": source if source is not None else "Belirtilmemis",
            "adet": count,
            "net": Money.of(decimal_or_zero(net), currency),
            "vergi": Money.of(decimal_or_zero(tax), currency),
            "toplam": Money.of(decimal_or_zero(total), currency),
        }
        for source, count, net, tax, total in session.execute(stmt).all()
    ]

    return ReportTable(
        title="Kanal Bazinda Gelir",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=date_range.format(),
    )


def revenue_by_room_type(session: Session, property_id: int, date_range: DateRange) -> ReportTable:
    """Oda tipine gore gelir dagilimi.

    .. note::
       **Tuzak 1:** Folyo her zaman bir oda satirina bagli degildir; tek
       folyolu (rezervasyon duzeyinde) calisan tesislerde
       ``Folio.reservation_room_id`` bostur. Bu durumda rezervasyonun **ilk**
       oda satiri varsayilir. Cok odali ve tek folyolu bir rezervasyonda tum
       gelir ilk odanin tipine yazilir; oda tipi kirilimi isteyen isletmeler
       oda bazli folyo kullanmalidir.

    .. note::
       **Tuzak 2:** Hicbir rezervasyona bagli olmayan folyolar (gecici bar
       veya restoran hesabi) da vardir. Ic birlestirme kullanilsaydi bu
       ucretler tumuyle **dusup giderdi** ve ayni donemin oda tipi raporu ile
       kanal/ucret turu raporlari farkli toplam verirdi - mali mutabakati
       imkansiz kilan sessiz bir fark. Bu yuzden birlestirme disaridandir ve
       eslesmeyen satirlar "Belirtilmemis" satirinda toplanir.
    """
    columns = [
        ReportColumn("oda_tipi", "Oda Tipi", align="left"),
        ReportColumn("adet", "Kalem", align="right", format="integer"),
        ReportColumn("oda_geliri", "Oda Geliri", align="right", format="money"),
        ReportColumn("diger_gelir", "Diger Gelir", align="right", format="money"),
        ReportColumn("toplam", "Toplam", align="right", format="money"),
    ]
    currency = _property_currency(session, property_id)

    first_room = (
        select(func.min(ReservationRoom.id))
        .where(ReservationRoom.reservation_id == Folio.reservation_id)
        .correlate(Folio)
        .scalar_subquery()
    )
    linked_room = aliased(ReservationRoom)
    room_amount = case((Charge.charge_type == ChargeType.ROOM, Charge.total_amount), else_=0)
    other_amount = case((Charge.charge_type != ChargeType.ROOM, Charge.total_amount), else_=0)

    stmt = (
        select(
            RoomType.name,
            func.count(Charge.id),
            func.sum(room_amount),
            func.sum(other_amount),
            func.sum(Charge.total_amount),
        )
        .select_from(Charge)
        .join(Folio, Charge.folio_id == Folio.id)
        .outerjoin(
            linked_room,
            linked_room.id == func.coalesce(Folio.reservation_room_id, first_room),
        )
        .outerjoin(RoomType, linked_room.room_type_id == RoomType.id)
        .where(*_charge_filters(property_id, date_range))
        .group_by(RoomType.id, RoomType.name)
        .order_by(func.sum(Charge.total_amount).desc())
    )

    rows = [
        {
            "oda_tipi": name if name is not None else "Belirtilmemis",
            "adet": count,
            "oda_geliri": Money.of(decimal_or_zero(room_total), currency),
            "diger_gelir": Money.of(decimal_or_zero(other_total), currency),
            "toplam": Money.of(decimal_or_zero(total), currency),
        }
        for name, count, room_total, other_total, total in session.execute(stmt).all()
    ]

    return ReportTable(
        title="Oda Tipi Bazinda Gelir",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=date_range.format(),
    )


def revenue_by_charge_type(
    session: Session, property_id: int, date_range: DateRange
) -> ReportTable:
    """Ucret turune gore gelir dagilimi (oda, restoran, spa, vergi...)."""
    columns = [
        ReportColumn("ucret_turu", "Ucret Turu", align="left"),
        ReportColumn("adet", "Kalem", align="right", format="integer"),
        ReportColumn("net", "Net Tutar", align="right", format="money"),
        ReportColumn("vergi", "Vergi", align="right", format="money"),
        ReportColumn("toplam", "Toplam", align="right", format="money"),
    ]
    currency = _property_currency(session, property_id)

    stmt = (
        select(
            Charge.charge_type,
            func.count(Charge.id),
            func.sum(Charge.net_amount),
            func.sum(Charge.tax_amount),
            func.sum(Charge.total_amount),
        )
        .select_from(Charge)
        .join(Folio, Charge.folio_id == Folio.id)
        .where(*_charge_filters(property_id, date_range))
        .group_by(Charge.charge_type)
        .order_by(func.sum(Charge.total_amount).desc())
    )

    rows = [
        {
            "ucret_turu": charge_type,
            "adet": count,
            "net": Money.of(decimal_or_zero(net), currency),
            "vergi": Money.of(decimal_or_zero(tax), currency),
            "toplam": Money.of(decimal_or_zero(total), currency),
        }
        for charge_type, count, net, tax, total in session.execute(stmt).all()
    ]

    return ReportTable(
        title="Ucret Turu Bazinda Gelir",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=date_range.format(),
    )


# ==========================================================================
#  Gunluk kapanis
# ==========================================================================
def daily_closing_report(session: Session, property_id: int, day: date) -> ReportTable:
    """Gun sonu kapanis raporu: gelir, tahsilat ve kasa hareketleri.

    Uc bolum tek tabloda "Grup" sutunu ile birlestirilir; boylece ayni
    tablo hem ekranda hem CSV/Excel/PDF ciktisinda tek parca kalir.

    Tahsilat suzgeci ``paid_at`` uzerinden **UTC gun sinirlariyla** yapilir
    (bkz. modul docstring'i).
    """
    columns = [
        ReportColumn("grup", "Grup", align="left"),
        ReportColumn("kalem", "Kalem", align="left"),
        ReportColumn("adet", "Adet", align="right", format="integer"),
        ReportColumn("tutar", "Tutar", align="right", format="money"),
    ]
    currency = _property_currency(session, property_id)
    single_day = DateRange.single_night(day)
    start_dt, end_dt = _range_bounds(single_day)

    rows: list[dict[str, Any]] = []

    charge_stmt = (
        select(Charge.charge_type, func.count(Charge.id), func.sum(Charge.total_amount))
        .select_from(Charge)
        .join(Folio, Charge.folio_id == Folio.id)
        .where(*_charge_filters(property_id, single_day))
        .group_by(Charge.charge_type)
        .order_by(func.sum(Charge.total_amount).desc())
    )
    revenue_total = Money.zero(currency)
    for charge_type, count, total in session.execute(charge_stmt).all():
        amount = Money.of(decimal_or_zero(total), currency)
        revenue_total = revenue_total + amount
        rows.append({"grup": "Gelir", "kalem": charge_type.label, "adet": count, "tutar": amount})

    payment_stmt = (
        select(Payment.method, func.count(Payment.id), func.sum(Payment.amount))
        .select_from(Payment)
        .join(Folio, Payment.folio_id == Folio.id)
        .where(
            Folio.property_id == property_id,
            Payment.is_refund.is_(False),
            Payment.paid_at >= start_dt,
            Payment.paid_at < end_dt,
        )
        .group_by(Payment.method)
        .order_by(func.sum(Payment.amount).desc())
    )
    payment_total = Money.zero(currency)
    for method, count, total in session.execute(payment_stmt).all():
        amount = Money.of(decimal_or_zero(total), currency)
        payment_total = payment_total + amount
        rows.append({"grup": "Tahsilat", "kalem": method.label, "adet": count, "tutar": amount})

    refund_stmt = (
        select(func.count(Payment.id), func.sum(Payment.amount))
        .select_from(Payment)
        .join(Folio, Payment.folio_id == Folio.id)
        .where(
            Folio.property_id == property_id,
            Payment.is_refund.is_(True),
            Payment.paid_at >= start_dt,
            Payment.paid_at < end_dt,
        )
    )
    refund_count, refund_sum = session.execute(refund_stmt).one()
    refund_total = Money.of(decimal_or_zero(refund_sum), currency)
    if refund_count:
        rows.append(
            {
                "grup": "Tahsilat",
                "kalem": "Iade",
                "adet": refund_count,
                "tutar": -refund_total,
            }
        )

    cash_stmt = (
        select(
            CashRegisterEntry.direction,
            func.count(CashRegisterEntry.id),
            func.sum(CashRegisterEntry.amount),
        )
        .where(
            CashRegisterEntry.property_id == property_id,
            CashRegisterEntry.entry_date == day,
        )
        .group_by(CashRegisterEntry.direction)
    )
    cash_net = Money.zero(currency)
    for direction, count, total in session.execute(cash_stmt).all():
        amount = Money.of(decimal_or_zero(total), currency)
        signed = amount if direction is TransactionDirection.INCOME else -amount
        cash_net = cash_net + signed
        rows.append({"grup": "Kasa", "kalem": direction.label, "adet": count, "tutar": signed})

    if rows:
        # Ozet satirlari yalnizca veri varsa eklenir; bos bir gunde tek satirlik
        # "Kayit bulunamadi" ciktisi, sifirlarla dolu bir tablodan daha nettir.
        rows.extend(
            [
                {
                    "grup": "Ozet",
                    "kalem": "Toplam Gelir",
                    "adet": None,
                    "tutar": revenue_total,
                },
                {
                    "grup": "Ozet",
                    "kalem": "Net Tahsilat",
                    "adet": None,
                    "tutar": payment_total - refund_total,
                },
                {"grup": "Ozet", "kalem": "Kasa Net", "adet": None, "tutar": cash_net},
            ]
        )

    return ReportTable(
        title="Gun Sonu Kapanis Raporu",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=day.strftime("%d.%m.%Y"),
    )


# ==========================================================================
#  On buro
# ==========================================================================
def arrivals_departures_report(session: Session, property_id: int, day: date) -> ReportTable:
    """Gunun giris, cikis ve devam eden konaklama listesi.

    Siniflandirma :func:`app.domain.rules.availability.summarize_day` ile
    ayni mantiktir: giris gunu ``check_in_date``, cikis gunu
    ``check_out_date``; ikisi de degilse "Konaklama".
    """
    columns = [
        ReportColumn("tur", "Tur", align="left"),
        ReportColumn("onay_no", "Onay No", align="left"),
        ReportColumn("misafir", "Misafir", align="left"),
        ReportColumn("oda", "Oda", align="left"),
        ReportColumn("oda_tipi", "Oda Tipi", align="left"),
        ReportColumn("giris", "Giris", align="center", format="date"),
        ReportColumn("cikis", "Cikis", align="center", format="date"),
        ReportColumn("kisi", "Kisi", align="right", format="integer"),
        ReportColumn("durum", "Durum", align="left"),
        ReportColumn("tutar", "Tutar", align="right", format="money"),
    ]
    currency = _property_currency(session, property_id)

    stmt = (
        select(ReservationRoom, Reservation, Guest, Room, RoomType)
        .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
        .join(Guest, Reservation.primary_guest_id == Guest.id)
        .join(RoomType, ReservationRoom.room_type_id == RoomType.id)
        .outerjoin(Room, ReservationRoom.room_id == Room.id)
        .where(
            Reservation.property_id == property_id,
            Reservation.is_deleted.is_(False),
            Reservation.status.in_(tuple(OPERATIONAL_RESERVATION_STATUSES)),
            ReservationRoom.is_cancelled.is_(False),
            ReservationRoom.check_in_date <= day,
            ReservationRoom.check_out_date >= day,
        )
    )

    #: Rapor icinde giris-cikis-konaklama sirasini sabitler.
    order = {"Giris": 0, "Cikis": 1, "Konaklama": 2}
    rows: list[dict[str, Any]] = []
    for res_room, reservation, guest, room, room_type in session.execute(stmt).all():
        if res_room.check_in_date == day:
            kind = "Giris"
        elif res_room.check_out_date == day:
            kind = "Cikis"
        else:
            kind = "Konaklama"
        rows.append(
            {
                "tur": kind,
                "onay_no": reservation.confirmation_number,
                "misafir": guest.full_name,
                "oda": room.number if room is not None else "Atanmadi",
                "oda_tipi": room_type.name,
                "giris": res_room.check_in_date,
                "cikis": res_room.check_out_date,
                "kisi": res_room.total_guests,
                "durum": reservation.status,
                "tutar": Money.of(res_room.total_amount, currency),
            }
        )
    rows.sort(key=lambda row: (order[row["tur"]], str(row["oda"])))

    return ReportTable(
        title="Giris - Cikis Raporu",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=day.strftime("%d.%m.%Y"),
    )


def guest_ledger(session: Session, folio_id: int) -> ReportTable:
    """Misafir hesap ekstresi - ucretler, odemeler ve yuruyen bakiye.

    Satirlar tarihe gore siralanir; ayni tarihli kayitlarda kimlik (``id``)
    sirasi kullanilir. Boylece ayni gun icinde islenen ucret ve odemenin
    sirasi kayit anina sadik kalir ve bakiye sutunu tutarli olur.

    Gecersiz kilinmis (``is_void``) ucretler ekstreye **girmez**; ancak
    veritabaninda korunur (mali denetim izi).
    """
    folio = session.get(Folio, folio_id)
    if folio is None:
        raise NotFoundError("Folyo", folio_id)

    columns = [
        ReportColumn("tarih", "Tarih", align="left", format="date"),
        ReportColumn("aciklama", "Aciklama", align="left"),
        ReportColumn("tur", "Tur", align="left"),
        ReportColumn("borc", "Borc", align="right", format="money"),
        ReportColumn("alacak", "Alacak", align="right", format="money"),
        ReportColumn("bakiye", "Bakiye", align="right", format="money"),
    ]
    currency = folio.currency

    entries: list[tuple[date, int, str, str, Money, Money]] = []
    for charge in folio.charges:
        if charge.is_void:
            continue
        entries.append(
            (
                charge.charge_date,
                charge.id or 0,
                charge.description,
                charge.charge_type.label,
                Money.of(charge.total_amount, currency),
                Money.zero(currency),
            )
        )
    for payment in folio.payments:
        amount = Money.of(payment.amount, currency)
        # Iade, misafirin borcunu artirir; bu yuzden borc sutununa yazilir.
        entries.append(
            (
                payment.paid_at.date(),
                payment.id or 0,
                "Iade" if payment.is_refund else "Tahsilat",
                payment.method.label,
                amount if payment.is_refund else Money.zero(currency),
                Money.zero(currency) if payment.is_refund else amount,
            )
        )

    entries.sort(key=lambda item: (item[0], item[1]))

    balance = Money.zero(currency)
    rows: list[dict[str, Any]] = []
    for entry_date, _entry_id, description, kind, debit, credit in entries:
        balance = balance + debit - credit
        rows.append(
            {
                "tarih": entry_date,
                "aciklama": description,
                "tur": kind,
                "borc": debit,
                "alacak": credit,
                "bakiye": balance,
            }
        )

    guest_name = folio.guest.full_name if folio.guest is not None else "-"
    return ReportTable(
        title="Misafir Hesap Ekstresi",
        subtitle=f"Folyo {folio.folio_number} - {guest_name}",
        columns=columns,
        rows=rows,
        filters_description=f"Durum: {folio.status.label}",
    )


# ==========================================================================
#  Operasyon
# ==========================================================================
def housekeeping_report(session: Session, property_id: int, day: date) -> ReportTable:
    """Gunun kat hizmetleri gorev listesi."""
    columns = [
        ReportColumn("oda", "Oda", align="left"),
        ReportColumn("gorev", "Gorev", align="left"),
        ReportColumn("durum", "Durum", align="left"),
        ReportColumn("oncelik", "Oncelik", align="left"),
        ReportColumn("personel", "Personel", align="left"),
        ReportColumn("tahmini", "Tahmini (dk)", align="right", format="integer"),
        ReportColumn("gercek", "Gercek (dk)", align="right", format="integer"),
        ReportColumn("kontrol", "Kontrol", align="left"),
    ]

    stmt = (
        select(HousekeepingTask, Room, Employee)
        .join(Room, HousekeepingTask.room_id == Room.id)
        .outerjoin(Employee, HousekeepingTask.assigned_employee_id == Employee.id)
        .where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.scheduled_date == day,
        )
        .order_by(Room.number)
    )

    rows: list[dict[str, Any]] = []
    for task, room, employee in session.execute(stmt).all():
        rows.append(
            {
                "oda": room.number,
                "gorev": task.task_type,
                "durum": task.status,
                "oncelik": task.priority,
                "personel": employee.full_name if employee is not None else "Atanmadi",
                "tahmini": task.estimated_minutes,
                "gercek": task.actual_minutes,
                "kontrol": (
                    "-"
                    if task.inspection_passed is None
                    else ("Gecti" if task.inspection_passed else "Kaldi")
                ),
            }
        )

    return ReportTable(
        title="Kat Hizmetleri Raporu",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=day.strftime("%d.%m.%Y"),
    )


def maintenance_report(session: Session, property_id: int, date_range: DateRange) -> ReportTable:
    """Donem icinde acilan ariza/bakim kayitlari.

    Suzgec ``reported_at`` (UTC) uzerindedir: raporun konusu arizanin ne
    zaman **bildirildigidir**. Cozum tarihine gore suzmek, henuz cozulmemis
    kayitlari tumuyle gorunmez kilardi.
    """
    columns = [
        ReportColumn("fis_no", "Fis No", align="left"),
        ReportColumn("oda", "Oda", align="left"),
        ReportColumn("kategori", "Kategori", align="left"),
        ReportColumn("oncelik", "Oncelik", align="left"),
        ReportColumn("durum", "Durum", align="left"),
        ReportColumn("baslik", "Baslik", align="left"),
        ReportColumn("bildirim", "Bildirim", align="left", format="datetime"),
        ReportColumn("cozum_saat", "Cozum (saat)", align="right", format="decimal"),
        ReportColumn("maliyet", "Maliyet", align="right", format="money"),
    ]
    currency = _property_currency(session, property_id)
    start_dt, end_dt = _range_bounds(date_range)

    stmt = (
        select(MaintenanceTicket, Room)
        .outerjoin(Room, MaintenanceTicket.room_id == Room.id)
        .where(
            MaintenanceTicket.property_id == property_id,
            MaintenanceTicket.reported_at >= start_dt,
            MaintenanceTicket.reported_at < end_dt,
        )
        .order_by(MaintenanceTicket.reported_at)
    )

    rows: list[dict[str, Any]] = []
    for ticket, room in session.execute(stmt).all():
        rows.append(
            {
                "fis_no": ticket.ticket_number,
                "oda": room.number if room is not None else (ticket.location_description or "-"),
                "kategori": ticket.category,
                "oncelik": ticket.priority,
                "durum": ticket.status,
                "baslik": ticket.title,
                "bildirim": ticket.reported_at,
                "cozum_saat": ticket.resolution_hours,
                "maliyet": Money.of(ticket.total_cost, currency),
            }
        )

    return ReportTable(
        title="Teknik Servis Raporu",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description=date_range.format(),
    )


def stock_report(session: Session, property_id: int) -> ReportTable:
    """Guncel stok durumu ve kritik seviye uyarilari.

    Kritik satirlar en uste alinir: bir stok raporunun ilk isi, biten
    urunleri gostermektir.
    """
    columns = [
        ReportColumn("sku", "Stok Kodu", align="left"),
        ReportColumn("urun", "Urun", align="left"),
        ReportColumn("kategori", "Kategori", align="left"),
        ReportColumn("birim", "Birim", align="left"),
        ReportColumn("mevcut", "Mevcut", align="right", format="decimal"),
        ReportColumn("asgari", "Asgari", align="right", format="decimal"),
        ReportColumn("durum", "Durum", align="left"),
        ReportColumn("birim_maliyet", "Birim Maliyet", align="right", format="money"),
        ReportColumn("stok_degeri", "Stok Degeri", align="right", format="money"),
    ]

    items = list(
        session.scalars(
            select(InventoryItem)
            .where(
                InventoryItem.property_id == property_id,
                InventoryItem.is_active.is_(True),
            )
            .order_by(InventoryItem.category, InventoryItem.name)
        ).all()
    )

    rows = [
        {
            "sku": item.sku,
            "urun": item.name,
            "kategori": item.category,
            "birim": item.unit,
            "mevcut": item.current_stock,
            "asgari": item.minimum_stock,
            "durum": "Kritik" if item.is_below_minimum else "Normal",
            "birim_maliyet": Money.of(item.unit_cost, item.currency),
            "stok_degeri": Money.of(item.stock_value, item.currency),
        }
        for item in items
    ]
    rows.sort(key=lambda row: (row["durum"] != "Kritik", str(row["kategori"]), str(row["urun"])))

    return ReportTable(
        title="Stok Durum Raporu",
        subtitle=_property_name(session, property_id),
        columns=columns,
        rows=rows,
        filters_description="Aktif stok kartlari",
    )


# ==========================================================================
#  KPI
# ==========================================================================
def kpi_report(session: Session, property_id: int, date_range: DateRange) -> KPISet:
    """Donemin temel performans gostergelerini hesaplar.

    Oda geliri, ``Charge.charge_type == ChargeType.ROOM`` suzgeciyle diger
    gelirlerden **ayrilir**; ADR'nin dogru olmasi buna baglidir
    (bkz. :func:`app.reporting.kpi.adr`).

    Satilan oda gecesi, rezervasyonun donemle kesisen gece sayisidir:
    donem disina tasan konaklamalarin yalnizca donem icindeki gecelerini
    saymak icin :meth:`DateRange.overlapping_nights` kullanilir. Aksi halde
    ay basinda biten uzun konaklamalar o ayin doluluk sayisini sisirirdi.
    """
    currency = _property_currency(session, property_id)

    room_amount = case((Charge.charge_type == ChargeType.ROOM, Charge.total_amount), else_=0)
    revenue_stmt = (
        select(func.sum(room_amount), func.sum(Charge.total_amount))
        .select_from(Charge)
        .join(Folio, Charge.folio_id == Folio.id)
        .where(*_charge_filters(property_id, date_range))
    )
    room_sum, total_sum = session.execute(revenue_stmt).one()
    room_revenue = Money.of(decimal_or_zero(room_sum), currency)
    total_revenue = Money.of(decimal_or_zero(total_sum), currency)
    other_revenue = total_revenue - room_revenue

    room_rows = list(session.scalars(_occupied_room_rows(property_id, date_range)).all())
    nights_sold = 0
    stay_count = 0
    for row in room_rows:
        overlap = row.date_range.overlapping_nights(date_range)
        if overlap > 0:
            nights_sold += overlap
            stay_count += 1

    rooms = _active_rooms(session, property_id)

    status_stmt = (
        select(Reservation.status, func.count(Reservation.id))
        .where(
            Reservation.property_id == property_id,
            Reservation.is_deleted.is_(False),
            Reservation.check_in_date >= date_range.start,
            Reservation.check_in_date < date_range.end,
        )
        .group_by(Reservation.status)
    )
    counts = dict(session.execute(status_stmt).all())
    total_reservations = sum(counts.values())

    return kpi.calculate_kpis(
        date_range=date_range,
        room_revenue=room_revenue,
        other_revenue=other_revenue,
        room_nights_sold=nights_sold,
        total_rooms=len(rooms),
        out_of_order_room_nights=_out_of_order_room_nights(rooms, date_range),
        stay_count=stay_count,
        total_reservations=total_reservations,
        cancelled_reservations=counts.get(ReservationStatus.CANCELLED, 0),
        no_show_reservations=counts.get(ReservationStatus.NO_SHOW, 0),
    )


__all__ = [
    "OPERATIONAL_RESERVATION_STATUSES",
    "arrivals_departures_report",
    "daily_closing_report",
    "guest_ledger",
    "housekeeping_report",
    "kpi_report",
    "maintenance_report",
    "occupancy_report",
    "revenue_by_channel",
    "revenue_by_charge_type",
    "revenue_by_room_type",
    "stock_report",
]
