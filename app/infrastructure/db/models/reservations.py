"""Rezervasyon, oda satirlari, misafir baglantilari, fiili konaklama ve bekleme listesi.

Tasarim karari: neden ``ReservationRoom``?
------------------------------------------
Bir rezervasyon birden fazla oda icerebilir ve bu odalarin tarihleri
**farkli olabilir** (or. grup rezervasyonunda bazi odalar bir gun once
gelir). Bu yuzden tarih araligi ve fiyat, rezervasyonun kendisinde degil,
:class:`ReservationRoom` satirlarinda tutulur.

Bunun dogrudan sonucu: **cakisma kontrolu oda satiri duzeyinde yapilir.**
Rezervasyon baslik satirindaki ``check_in_date``/``check_out_date`` yalnizca
turetilmis bir ozettir (en erken giris / en gec cikis) ve listeleme
kolayligi icin tutulur.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    Currency,
    GuestRelation,
    MealPlan,
    ReservationSource,
    ReservationStatus,
    StayStatus,
)
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import (
    Base,
    NotesMixin,
    SoftDeleteMixin,
    TimestampMixin,
    enum_column,
)
from app.infrastructure.db.types import TZDateTime

if TYPE_CHECKING:
    from app.infrastructure.db.models.billing import Folio
    from app.infrastructure.db.models.guests import Agency, Company, Guest
    from app.infrastructure.db.models.organization import Property
    from app.infrastructure.db.models.rooms import RatePlan, Room, RoomType
    from app.infrastructure.db.models.security import User


class Reservation(Base, TimestampMixin, SoftDeleteMixin, NotesMixin):
    """Rezervasyon baslik kaydi."""

    __table_args__ = (
        Index("ix_reservation_dates", "check_in_date", "check_out_date"),
        Index("ix_reservation_status_property", "property_id", "status"),
    )

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    confirmation_number: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, doc="Misafire verilen onay numarasi."
    )

    status: Mapped[ReservationStatus] = mapped_column(
        enum_column(ReservationStatus), default=ReservationStatus.DRAFT, index=True
    )
    source: Mapped[ReservationSource] = mapped_column(
        enum_column(ReservationSource), default=ReservationSource.DIRECT, index=True
    )
    source_reference: Mapped[str | None] = mapped_column(
        String(80), default=None, doc="Kanal tarafindaki rezervasyon numarasi."
    )

    # ---- Taraflar ----
    primary_guest_id: Mapped[int] = mapped_column(ForeignKey("guest.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("company.id", ondelete="SET NULL"), default=None, index=True
    )
    agency_id: Mapped[int | None] = mapped_column(
        ForeignKey("agency.id", ondelete="SET NULL"), default=None, index=True
    )

    # ---- Ozet tarihler (oda satirlarindan turetilir) ----
    check_in_date: Mapped[date] = mapped_column(Date, index=True)
    check_out_date: Mapped[date] = mapped_column(Date, index=True)
    expected_arrival_time: Mapped[time | None] = mapped_column(Time, default=None)
    expected_departure_time: Mapped[time | None] = mapped_column(Time, default=None)

    # ---- Kisi sayilari (ozet) ----
    adults: Mapped[int] = mapped_column(default=1)
    children: Mapped[int] = mapped_column(default=0)
    infants: Mapped[int] = mapped_column(default=0)

    # ---- Mali ozet ----
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), doc="Oda satirlarinin toplami (vergi dahil)."
    )
    deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), doc="Talep edilen depozito."
    )
    deposit_paid: Mapped[bool] = mapped_column(default=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))

    # ---- Grup rezervasyonu ----
    group_name: Mapped[str | None] = mapped_column(String(150), default=None, index=True)
    group_master_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservation.id", ondelete="SET NULL"),
        default=None,
        doc="Grup ana rezervasyonu; alt rezervasyonlar buna baglanir.",
    )

    # ---- Talepler ve iptal ----
    special_requests: Mapped[str | None] = mapped_column(Text, default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    cancellation_reason: Mapped[str | None] = mapped_column(String(400), default=None)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    no_show_marked_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    # ---- Iliskiler ----
    hotel_property: Mapped[Property] = relationship()
    primary_guest: Mapped[Guest] = relationship(
        back_populates="reservations", foreign_keys=[primary_guest_id]
    )
    company: Mapped[Company | None] = relationship(back_populates="reservations")
    agency: Mapped[Agency | None] = relationship(back_populates="reservations")
    rooms: Mapped[list[ReservationRoom]] = relationship(
        back_populates="reservation", cascade="all, delete-orphan"
    )
    folios: Mapped[list[Folio]] = relationship(back_populates="reservation")
    group_master: Mapped[Reservation | None] = relationship(
        remote_side="Reservation.id", back_populates="group_members"
    )
    group_members: Mapped[list[Reservation]] = relationship(back_populates="group_master")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])

    # ---- Turetilmis ----
    @property
    def date_range(self) -> DateRange:
        """Rezervasyonun ozet tarih araligi."""
        return DateRange(self.check_in_date, self.check_out_date)

    @property
    def nights(self) -> int:
        return (self.check_out_date - self.check_in_date).days

    @property
    def total_guests(self) -> int:
        return self.adults + self.children

    @property
    def balance(self) -> Decimal:
        """Kalan borc (negatif ise fazla odeme)."""
        return self.total_amount - self.paid_amount

    @property
    def is_paid(self) -> bool:
        return self.balance <= 0

    @property
    def is_group_master(self) -> bool:
        return bool(self.group_name) and self.group_master_id is None

    @property
    def blocks_inventory(self) -> bool:
        """Bu rezervasyon oda envanterini bloke ediyor mu?"""
        from app.domain.enums import BLOCKING_RESERVATION_STATUSES

        return self.status in BLOCKING_RESERVATION_STATUSES and not self.is_deleted

    def recalculate_summary(self) -> None:
        """Ozet alanlari oda satirlarindan yeniden hesaplar.

        Oda satiri eklendiginde/degistiginde cagrilmalidir; boylece baslik
        satirindaki tarih ve tutar ozetleri gercekle uyumlu kalir.
        """
        active_rooms = [r for r in self.rooms if not r.is_cancelled]
        if not active_rooms:
            return
        self.check_in_date = min(r.check_in_date for r in active_rooms)
        self.check_out_date = max(r.check_out_date for r in active_rooms)
        self.total_amount = sum((r.total_amount for r in active_rooms), start=Decimal("0.00"))
        self.adults = sum(r.adults for r in active_rooms)
        self.children = sum(r.children for r in active_rooms)


class ReservationRoom(Base, TimestampMixin):
    """Rezervasyonun tek bir oda satiri - musaitlik ve fiyatin gercek tasiyicisi."""

    __table_args__ = (
        # Cakisma sorgusunun temel indeksi: belirli bir odanin tarih araliklari.
        Index("ix_resroom_room_dates", "room_id", "check_in_date", "check_out_date"),
        Index("ix_resroom_type_dates", "room_type_id", "check_in_date", "check_out_date"),
    )

    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservation.id", ondelete="CASCADE"), index=True
    )
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_type.id"), index=True)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("room.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="Atanan fiziksel oda. Oda tipi bazli rezervasyonlarda giris anina kadar bos olabilir.",
    )
    rate_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("rate_plan.id", ondelete="SET NULL"), default=None
    )

    check_in_date: Mapped[date] = mapped_column(Date, index=True)
    check_out_date: Mapped[date] = mapped_column(Date, index=True)

    adults: Mapped[int] = mapped_column(default=1)
    children: Mapped[int] = mapped_column(default=0)
    infants: Mapped[int] = mapped_column(default=0)
    meal_plan: Mapped[MealPlan] = mapped_column(
        enum_column(MealPlan), default=MealPlan.BED_BREAKFAST
    )

    nightly_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), doc="Ortalama gecelik ucret (bilgi amacli)."
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), doc="Bu oda satirinin toplam tutari."
    )
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))

    is_cancelled: Mapped[bool] = mapped_column(
        default=False, index=True, doc="Yalnizca bu oda satiri iptal edildi."
    )
    guest_name_override: Mapped[str | None] = mapped_column(
        String(150), default=None, doc="Oda karti icin farkli isim yazdirilacaksa."
    )

    reservation: Mapped[Reservation] = relationship(back_populates="rooms")
    room: Mapped[Room | None] = relationship(back_populates="reservation_rooms")
    room_type: Mapped[RoomType] = relationship()
    rate_plan: Mapped[RatePlan | None] = relationship()
    reservation_guests: Mapped[list[ReservationGuest]] = relationship(
        back_populates="reservation_room", cascade="all, delete-orphan"
    )
    stay: Mapped[Stay | None] = relationship(
        back_populates="reservation_room", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def date_range(self) -> DateRange:
        return DateRange(self.check_in_date, self.check_out_date)

    @property
    def nights(self) -> int:
        return (self.check_out_date - self.check_in_date).days

    @property
    def total_guests(self) -> int:
        return self.adults + self.children

    def overlaps_with(self, other: ReservationRoom) -> bool:
        """Ayni fiziksel odada tarih cakismasi var mi?

        Oda atanmamis satirlar (``room_id is None``) fiziksel envanteri
        bloke etmez, bu yuzden cakisma uretmez.
        """
        if self.room_id is None or other.room_id is None:
            return False
        if self.room_id != other.room_id:
            return False
        return self.date_range.overlaps(other.date_range)


class ReservationGuest(Base, TimestampMixin):
    """Bir oda satirinda konaklayan misafir (asil misafir + refakatciler)."""

    __table_args__ = (Index("ix_resguest_unique", "reservation_room_id", "guest_id", unique=True),)

    reservation_room_id: Mapped[int] = mapped_column(
        ForeignKey("reservation_room.id", ondelete="CASCADE"), index=True
    )
    guest_id: Mapped[int] = mapped_column(ForeignKey("guest.id"), index=True)
    relation: Mapped[GuestRelation] = mapped_column(
        enum_column(GuestRelation), default=GuestRelation.ACCOMPANYING
    )
    is_primary: Mapped[bool] = mapped_column(default=False)

    reservation_room: Mapped[ReservationRoom] = relationship(back_populates="reservation_guests")
    guest: Mapped[Guest] = relationship(back_populates="reservation_guests")


class Stay(Base, TimestampMixin, NotesMixin):
    """Fiili konaklama kaydi - check-in ile olusur, check-out ile kapanir.

    Rezervasyon *planlanani*, Stay *gerceklesen'i* temsil eder. Erken cikis
    veya gec cikis gibi sapmalar burada gorunur.
    """

    reservation_room_id: Mapped[int] = mapped_column(
        ForeignKey("reservation_room.id", ondelete="CASCADE"), unique=True, index=True
    )
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), index=True)

    status: Mapped[StayStatus] = mapped_column(
        enum_column(StayStatus), default=StayStatus.IN_HOUSE, index=True
    )
    actual_check_in: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    actual_check_out: Mapped[datetime | None] = mapped_column(TZDateTime, default=None, index=True)

    key_card_count: Mapped[int] = mapped_column(default=1)
    key_cards_returned: Mapped[int] = mapped_column(default=0)

    is_early_check_in: Mapped[bool] = mapped_column(default=False)
    is_late_check_out: Mapped[bool] = mapped_column(default=False)
    early_check_in_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    late_check_out_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    damage_reported: Mapped[bool] = mapped_column(default=False)
    damage_description: Mapped[str | None] = mapped_column(Text, default=None)
    damage_charge: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    checked_in_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    checked_out_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    reservation_room: Mapped[ReservationRoom] = relationship(back_populates="stay")
    room: Mapped[Room] = relationship()

    @property
    def is_in_house(self) -> bool:
        return self.status is StayStatus.IN_HOUSE and self.actual_check_out is None

    @property
    def actual_nights(self) -> int | None:
        """Fiilen konaklanan gece sayisi; henuz cikis yapilmadiysa ``None``."""
        if self.actual_check_out is None:
            return None
        return max((self.actual_check_out.date() - self.actual_check_in.date()).days, 0)


class WaitlistEntry(Base, TimestampMixin, NotesMixin):
    """Bekleme listesi kaydi - istenen tarihte oda bulunamadiginda."""

    __table_args__ = (Index("ix_waitlist_dates", "requested_check_in", "requested_check_out"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    guest_id: Mapped[int | None] = mapped_column(
        ForeignKey("guest.id", ondelete="SET NULL"), default=None, index=True
    )
    room_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("room_type.id", ondelete="SET NULL"), default=None
    )

    contact_name: Mapped[str] = mapped_column(String(150))
    contact_phone: Mapped[str | None] = mapped_column(String(40), default=None)
    contact_email: Mapped[str | None] = mapped_column(String(200), default=None)

    requested_check_in: Mapped[date] = mapped_column(Date, index=True)
    requested_check_out: Mapped[date] = mapped_column(Date)
    adults: Mapped[int] = mapped_column(default=1)
    children: Mapped[int] = mapped_column(default=0)

    priority: Mapped[int] = mapped_column(default=0, doc="Buyuk deger once aranir.")
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    converted_reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservation.id", ondelete="SET NULL"),
        default=None,
        doc="Bekleme kaydi rezervasyona donustuyse baglanti.",
    )
    notified_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    guest: Mapped[Guest | None] = relationship()
    room_type: Mapped[RoomType | None] = relationship()

    @property
    def date_range(self) -> DateRange:
        return DateRange(self.requested_check_in, self.requested_check_out)


__all__ = [
    "Reservation",
    "ReservationGuest",
    "ReservationRoom",
    "Stay",
    "WaitlistEntry",
]
