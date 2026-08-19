"""Tesis, bina, kat, departman ve personel modelleri.

Veri modeli bastan **cok tesisli** (multi-property) kurgulanmistir: tum
operasyonel kayitlar bir :class:`Property` altinda toplanir. Tek otel
kullanan bir isletme icin bu yalnizca tek bir satir demektir; ancak zincir
otele buyume durumunda sema degisikligi gerekmez.
"""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    Currency,
    EmploymentStatus,
    PropertyType,
    ShiftType,
)
from app.infrastructure.db.base import (
    ActiveMixin,
    Base,
    NotesMixin,
    TimestampMixin,
    enum_column,
)

if TYPE_CHECKING:
    from app.infrastructure.db.models.rooms import RatePlan, Room, RoomType
    from app.infrastructure.db.models.security import User


class Property(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Konaklama tesisi (otel, pansiyon, apart, tatil koyu...)."""

    code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, doc="Kisa tesis kodu, or. 'MRK01'."
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    property_type: Mapped[PropertyType] = mapped_column(
        enum_column(PropertyType), default=PropertyType.HOTEL
    )
    star_rating: Mapped[int | None] = mapped_column(default=None, doc="1-5 yildiz.")

    # ---- Iletisim / adres ----
    address_line: Mapped[str | None] = mapped_column(String(300), default=None)
    district: Mapped[str | None] = mapped_column(String(100), default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), default=None)
    country: Mapped[str] = mapped_column(String(100), default="Turkiye")
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    website: Mapped[str | None] = mapped_column(String(200), default=None)

    # ---- Mali ----
    tax_office: Mapped[str | None] = mapped_column(String(120), default=None)
    tax_number: Mapped[str | None] = mapped_column(String(30), default=None)
    default_currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )

    # ---- Operasyon kurallari ----
    check_in_time: Mapped[time] = mapped_column(
        Time, default=time(14, 0), doc="Standart giris saati."
    )
    check_out_time: Mapped[time] = mapped_column(
        Time, default=time(12, 0), doc="Standart cikis saati."
    )
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Istanbul")
    logo_path: Mapped[str | None] = mapped_column(String(400), default=None)

    # ---- Iliskiler ----
    buildings: Mapped[list[Building]] = relationship(
        back_populates="hotel_property", cascade="all, delete-orphan"
    )
    departments: Mapped[list[Department]] = relationship(
        back_populates="hotel_property", cascade="all, delete-orphan"
    )
    employees: Mapped[list[Employee]] = relationship(back_populates="hotel_property")
    room_types: Mapped[list[RoomType]] = relationship(
        back_populates="hotel_property", cascade="all, delete-orphan"
    )
    rooms: Mapped[list[Room]] = relationship(back_populates="hotel_property")
    rate_plans: Mapped[list[RatePlan]] = relationship(
        back_populates="hotel_property", cascade="all, delete-orphan"
    )


class Building(Base, TimestampMixin, ActiveMixin):
    """Tesis icindeki bina/blok."""

    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_building_property_code"),)

    property_id: Mapped[int] = mapped_column(
        ForeignKey("property.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(400), default=None)

    hotel_property: Mapped[Property] = relationship(back_populates="buildings")
    floors: Mapped[list[Floor]] = relationship(
        back_populates="building", cascade="all, delete-orphan"
    )


class Floor(Base, TimestampMixin, ActiveMixin):
    """Bina icindeki kat."""

    __table_args__ = (UniqueConstraint("building_id", "number", name="uq_floor_building_number"),)

    building_id: Mapped[int] = mapped_column(
        ForeignKey("building.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(doc="Kat numarasi; bodrum icin negatif olabilir.")
    name: Mapped[str | None] = mapped_column(String(80), default=None)

    building: Mapped[Building] = relationship(back_populates="floors")
    rooms: Mapped[list[Room]] = relationship(back_populates="floor")


class Department(Base, TimestampMixin, ActiveMixin):
    """Departman (On Buro, Kat Hizmetleri, Teknik Servis, Muhasebe...)."""

    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_department_property_code"),)

    property_id: Mapped[int] = mapped_column(
        ForeignKey("property.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(400), default=None)

    hotel_property: Mapped[Property] = relationship(back_populates="departments")
    employees: Mapped[list[Employee]] = relationship(back_populates="department")


class Employee(Base, TimestampMixin, NotesMixin):
    """Calisan kaydi.

    :class:`~app.infrastructure.db.models.security.User` ile **bire bir
    baglanabilir ama zorunlu degildir**: her calisanin sisteme girisi olmak
    zorunda degildir (or. kat gorevlisi yalnizca gorev listesinde gorunur).
    """

    __table_args__ = (
        UniqueConstraint("property_id", "employee_code", name="uq_employee_property_code"),
        Index("ix_employee_name", "last_name", "first_name"),
    )

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"), default=None, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        default=None,
        unique=True,
        doc="Sisteme giris yapabilen kullanici hesabi (varsa).",
    )

    employee_code: Mapped[str] = mapped_column(String(30))
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    position: Mapped[str | None] = mapped_column(String(120), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)

    employment_status: Mapped[EmploymentStatus] = mapped_column(
        enum_column(EmploymentStatus), default=EmploymentStatus.ACTIVE, index=True
    )
    hire_date: Mapped[date | None] = mapped_column(Date, default=None)
    termination_date: Mapped[date | None] = mapped_column(Date, default=None)

    hotel_property: Mapped[Property] = relationship(back_populates="employees")
    department: Mapped[Department | None] = relationship(back_populates="employees")
    user: Mapped[User | None] = relationship(back_populates="employee")
    shifts: Mapped[list[Shift]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_available(self) -> bool:
        """Gorev atanabilir durumda mi?"""
        return self.employment_status is EmploymentStatus.ACTIVE


class Shift(Base, TimestampMixin, NotesMixin):
    """Vardiya plani kaydi."""

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "shift_date", "shift_type", name="uq_shift_employee_date_type"
        ),
        Index("ix_shift_date", "shift_date"),
    )

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employee.id", ondelete="CASCADE"), index=True
    )
    shift_date: Mapped[date] = mapped_column(Date)
    shift_type: Mapped[ShiftType] = mapped_column(enum_column(ShiftType), default=ShiftType.MORNING)
    start_time: Mapped[time | None] = mapped_column(Time, default=None)
    end_time: Mapped[time | None] = mapped_column(Time, default=None)

    employee: Mapped[Employee] = relationship(back_populates="shifts")


__all__ = ["Building", "Department", "Employee", "Floor", "Property", "Shift"]
