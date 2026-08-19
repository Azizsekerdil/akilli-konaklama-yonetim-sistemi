"""Oda tipi, oda, oda ozellikleri, fotograflar ve fiyat planlari."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    BedType,
    Currency,
    MealPlan,
    RatePlanType,
    RoomHousekeepingStatus,
    RoomOccupancyStatus,
    RoomView,
)
from app.infrastructure.db.base import (
    ActiveMixin,
    Base,
    NotesMixin,
    TimestampMixin,
    enum_column,
)

if TYPE_CHECKING:
    from app.infrastructure.db.models.operations import HousekeepingTask, MaintenanceTicket
    from app.infrastructure.db.models.organization import Floor, Property
    from app.infrastructure.db.models.reservations import ReservationRoom

# --------------------------------------------------------------------------
#  Cok-cok baglanti tablolari
# --------------------------------------------------------------------------
room_type_feature = Table(
    "room_type_feature",
    Base.metadata,
    Column("room_type_id", ForeignKey("room_type.id", ondelete="CASCADE"), primary_key=True),
    Column("room_feature_id", ForeignKey("room_feature.id", ondelete="CASCADE"), primary_key=True),
    comment="Oda tipinin standart ozellikleri.",
)

room_extra_feature = Table(
    "room_extra_feature",
    Base.metadata,
    Column("room_id", ForeignKey("room.id", ondelete="CASCADE"), primary_key=True),
    Column("room_feature_id", ForeignKey("room_feature.id", ondelete="CASCADE"), primary_key=True),
    comment="Tek bir odaya ozel ek ozellikler (tip genelinde olmayan).",
)


class RoomFeature(Base, TimestampMixin, ActiveMixin):
    """Oda ozelligi (klima, balkon, jakuzi, deniz manzarasi...)."""

    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    icon: Mapped[str | None] = mapped_column(
        String(60), default=None, doc="Arayuzde gosterilecek ikon adi."
    )
    description: Mapped[str | None] = mapped_column(String(300), default=None)

    room_types: Mapped[list[RoomType]] = relationship(
        secondary=room_type_feature, back_populates="features"
    )
    rooms: Mapped[list[Room]] = relationship(
        secondary=room_extra_feature, back_populates="extra_features"
    )


class RoomType(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Oda tipi (Standart, Deluxe, Suit...).

    Fiyatlandirma ve musaitlik hesaplari oda tipi duzeyinde yapilir; tek tek
    odalar ayni tipin birbirinin yerine gecebilen ornekleridir.
    """

    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_room_type_property_code"),)

    property_id: Mapped[int] = mapped_column(
        ForeignKey("property.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    # ---- Kapasite ----
    base_occupancy: Mapped[int] = mapped_column(default=2, doc="Temel fiyata dahil kisi sayisi.")
    max_occupancy: Mapped[int] = mapped_column(default=2, doc="Toplam azami kisi (bebek haric).")
    max_adults: Mapped[int] = mapped_column(default=2)
    max_children: Mapped[int] = mapped_column(default=0)
    bed_type: Mapped[BedType] = mapped_column(enum_column(BedType), default=BedType.DOUBLE)
    bed_count: Mapped[int] = mapped_column(default=1)
    size_sqm: Mapped[int | None] = mapped_column(default=None, doc="Metrekare.")

    # ---- Fiyat ----
    base_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        doc="Fiyat plani bulunamazsa kullanilacak varsayilan gecelik ucret.",
    )
    extra_adult_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    extra_child_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    hotel_property: Mapped[Property] = relationship(back_populates="room_types")
    rooms: Mapped[list[Room]] = relationship(back_populates="room_type")
    features: Mapped[list[RoomFeature]] = relationship(
        secondary=room_type_feature, back_populates="room_types"
    )
    photos: Mapped[list[RoomPhoto]] = relationship(
        back_populates="room_type", cascade="all, delete-orphan"
    )
    rates: Mapped[list[RatePlanRate]] = relationship(back_populates="room_type")

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.code})"


class Room(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Fiziksel oda."""

    __table_args__ = (
        UniqueConstraint("property_id", "number", name="uq_room_property_number"),
        Index("ix_room_status", "housekeeping_status", "occupancy_status"),
    )

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_type.id"), index=True)
    floor_id: Mapped[int | None] = mapped_column(
        ForeignKey("floor.id", ondelete="SET NULL"), default=None, index=True
    )

    number: Mapped[str] = mapped_column(String(20), doc="Oda numarasi, or. '101', 'A-12'.")
    name: Mapped[str | None] = mapped_column(String(120), default=None)
    view: Mapped[RoomView] = mapped_column(enum_column(RoomView), default=RoomView.NONE)

    # ---- Durum ----
    occupancy_status: Mapped[RoomOccupancyStatus] = mapped_column(
        enum_column(RoomOccupancyStatus), default=RoomOccupancyStatus.VACANT, index=True
    )
    housekeeping_status: Mapped[RoomHousekeepingStatus] = mapped_column(
        enum_column(RoomHousekeepingStatus), default=RoomHousekeepingStatus.CLEAN, index=True
    )
    out_of_service_from: Mapped[date | None] = mapped_column(Date, default=None)
    out_of_service_until: Mapped[date | None] = mapped_column(
        Date, default=None, doc="Bu tarihe kadar satisa kapali."
    )
    out_of_service_reason: Mapped[str | None] = mapped_column(String(300), default=None)

    # ---- Ozellikler ----
    is_smoking: Mapped[bool] = mapped_column(default=False)
    is_accessible: Mapped[bool] = mapped_column(default=False, doc="Engelli erisimine uygun.")
    is_connecting: Mapped[bool] = mapped_column(default=False, doc="Ara kapili oda.")
    connecting_room_id: Mapped[int | None] = mapped_column(
        ForeignKey("room.id", ondelete="SET NULL"), default=None
    )

    hotel_property: Mapped[Property] = relationship(back_populates="rooms")
    room_type: Mapped[RoomType] = relationship(back_populates="rooms")
    floor: Mapped[Floor | None] = relationship(back_populates="rooms")
    extra_features: Mapped[list[RoomFeature]] = relationship(
        secondary=room_extra_feature, back_populates="rooms"
    )
    photos: Mapped[list[RoomPhoto]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    reservation_rooms: Mapped[list[ReservationRoom]] = relationship(back_populates="room")
    housekeeping_tasks: Mapped[list[HousekeepingTask]] = relationship(back_populates="room")
    maintenance_tickets: Mapped[list[MaintenanceTicket]] = relationship(back_populates="room")

    # ---- Turetilmis ----
    @property
    def is_sellable(self) -> bool:
        """Oda satilabilir durumda mi?

        Not: Bu yalnizca odanin **kendi** durumunu kontrol eder. Belirli
        tarihlerde musaitlik icin rezervasyon cakismasi da bakilmalidir -
        bkz. :mod:`app.domain.rules.availability`.
        """
        from app.domain.enums import UNSELLABLE_ROOM_STATUSES

        return self.is_active and self.housekeeping_status not in UNSELLABLE_ROOM_STATUSES

    def is_out_of_service_on(self, day: date) -> bool:
        """Verilen gunde bakim nedeniyle satisa kapali mi?"""
        from app.domain.enums import UNSELLABLE_ROOM_STATUSES

        if self.housekeeping_status not in UNSELLABLE_ROOM_STATUSES:
            return False
        start = self.out_of_service_from
        end = self.out_of_service_until
        if start is None and end is None:
            return True  # sinirsiz kapali
        if start is not None and day < start:
            return False
        if end is not None and day > end:
            return False
        return True

    @property
    def display_name(self) -> str:
        return f"{self.number}" + (f" - {self.name}" if self.name else "")


class RoomPhoto(Base, TimestampMixin):
    """Oda veya oda tipi fotografi.

    Dosyanin kendisi ``uploads/`` altinda tutulur; veritabaninda yalnizca
    goreli yol saklanir (bkz. :mod:`app.core.paths`).
    """

    __table_args__ = (Index("ix_room_photo_owner", "room_id", "room_type_id"),)

    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("room.id", ondelete="CASCADE"), default=None
    )
    room_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("room_type.id", ondelete="CASCADE"), default=None
    )
    file_path: Mapped[str] = mapped_column(String(400), doc="uploads/ altinda goreli yol.")
    caption: Mapped[str | None] = mapped_column(String(200), default=None)
    is_primary: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)

    room: Mapped[Room | None] = relationship(back_populates="photos")
    room_type: Mapped[RoomType | None] = relationship(back_populates="photos")


class RatePlan(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Fiyat plani (Standart, Erken Rezervasyon, Kurumsal...).

    Konaklama kurallarini (min/max gece, iptal politikasi) tasir; fiili
    tutarlar :class:`RatePlanRate` satirlarinda tarih araligina gore tutulur.
    """

    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_rate_plan_property_code"),)

    property_id: Mapped[int] = mapped_column(
        ForeignKey("property.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    plan_type: Mapped[RatePlanType] = mapped_column(
        enum_column(RatePlanType), default=RatePlanType.STANDARD
    )
    meal_plan: Mapped[MealPlan] = mapped_column(
        enum_column(MealPlan), default=MealPlan.BED_BREAKFAST
    )
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )

    # ---- Konaklama kurallari ----
    min_nights: Mapped[int] = mapped_column(default=1, doc="Asgari konaklama gecesi.")
    max_nights: Mapped[int | None] = mapped_column(default=None, doc="Azami konaklama gecesi.")
    min_advance_days: Mapped[int] = mapped_column(
        default=0, doc="Girise en az kac gun kala rezervasyon yapilabilir."
    )
    max_advance_days: Mapped[int | None] = mapped_column(
        default=None, doc="Girise en fazla kac gun kala rezervasyon yapilabilir."
    )

    # ---- Iptal politikasi ----
    is_refundable: Mapped[bool] = mapped_column(default=True)
    free_cancellation_hours: Mapped[int] = mapped_column(
        default=24, doc="Girise kac saat kalaya kadar ucretsiz iptal."
    )
    cancellation_fee_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), doc="Ucretsiz iptal suresi sonrasi ceza yuzdesi."
    )
    no_show_fee_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("100.00"))

    # ---- Gecerlilik ----
    valid_from: Mapped[date | None] = mapped_column(Date, default=None)
    valid_to: Mapped[date | None] = mapped_column(Date, default=None)
    priority: Mapped[int] = mapped_column(
        default=0, doc="Ayni tarihte birden fazla plan varsa buyuk olan kazanir."
    )

    hotel_property: Mapped[Property] = relationship(back_populates="rate_plans")
    rates: Mapped[list[RatePlanRate]] = relationship(
        back_populates="rate_plan", cascade="all, delete-orphan"
    )

    def is_valid_on(self, day: date) -> bool:
        """Plan verilen tarihte gecerli mi?"""
        if not self.is_active:
            return False
        if self.valid_from and day < self.valid_from:
            return False
        if self.valid_to and day > self.valid_to:
            return False
        return True


class RatePlanRate(Base, TimestampMixin):
    """Belirli bir tarih araligi ve oda tipi icin gecelik ucret (sezonluk fiyat).

    Haftanin gunlerine gore farklilastirma ``weekday_mask`` ile yapilir:
    bit 0 = Pazartesi ... bit 6 = Pazar. Varsayilan 127 = tum gunler.
    Ornegin yalnizca hafta sonu (Cuma-Cumartesi) icin: ``0b1010000`` = 80.
    """

    __table_args__ = (
        Index("ix_rate_lookup", "rate_plan_id", "room_type_id", "valid_from", "valid_to"),
    )

    rate_plan_id: Mapped[int] = mapped_column(
        ForeignKey("rate_plan.id", ondelete="CASCADE"), index=True
    )
    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_type.id", ondelete="CASCADE"), index=True
    )

    valid_from: Mapped[date] = mapped_column(Date, doc="Sezon baslangici (dahil).")
    valid_to: Mapped[date] = mapped_column(Date, doc="Sezon bitisi (dahil).")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), doc="Gecelik ucret.")
    weekday_mask: Mapped[int] = mapped_column(
        default=127, doc="Gecerli haftanin gunleri; bit 0=Pazartesi, bit 6=Pazar."
    )
    min_nights: Mapped[int | None] = mapped_column(default=None)
    max_nights: Mapped[int | None] = mapped_column(default=None)
    season_name: Mapped[str | None] = mapped_column(
        String(80), default=None, doc="Or. 'Yuksek Sezon', 'Bayram'."
    )

    rate_plan: Mapped[RatePlan] = relationship(back_populates="rates")
    room_type: Mapped[RoomType] = relationship(back_populates="rates")

    def applies_on(self, day: date, *, nights: int | None = None) -> bool:
        """Bu fiyat satiri verilen gun (ve konaklama uzunlugu) icin gecerli mi?"""
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


__all__ = [
    "RatePlan",
    "RatePlanRate",
    "Room",
    "RoomFeature",
    "RoomPhoto",
    "RoomType",
    "room_extra_feature",
    "room_type_feature",
]
