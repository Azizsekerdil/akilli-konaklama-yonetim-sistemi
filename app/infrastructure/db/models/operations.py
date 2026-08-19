"""Kat hizmetleri, teknik servis, kayip esya ve minibar tuketimi."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    HousekeepingStatus,
    HousekeepingTaskType,
    LostItemStatus,
    MaintenanceCategory,
    MaintenanceStatus,
    Priority,
)
from app.infrastructure.db.base import (
    Base,
    NotesMixin,
    TimestampMixin,
    enum_column,
)
from app.infrastructure.db.types import TZDateTime

if TYPE_CHECKING:
    from app.infrastructure.db.models.guests import Guest
    from app.infrastructure.db.models.inventory import InventoryItem
    from app.infrastructure.db.models.organization import Employee
    from app.infrastructure.db.models.rooms import Room
    from app.infrastructure.db.models.security import User


class HousekeepingTask(Base, TimestampMixin, NotesMixin):
    """Kat hizmetleri gorevi."""

    __table_args__ = (
        Index("ix_hk_task_date_status", "scheduled_date", "status"),
        Index("ix_hk_task_assignee", "assigned_employee_id", "status"),
    )

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id", ondelete="CASCADE"), index=True)

    task_type: Mapped[HousekeepingTaskType] = mapped_column(
        enum_column(HousekeepingTaskType), default=HousekeepingTaskType.DAILY_CLEANING
    )
    status: Mapped[HousekeepingStatus] = mapped_column(
        enum_column(HousekeepingStatus), default=HousekeepingStatus.PENDING, index=True
    )
    priority: Mapped[Priority] = mapped_column(enum_column(Priority), default=Priority.NORMAL)

    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    assigned_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employee.id", ondelete="SET NULL"), default=None, index=True
    )

    started_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    inspected_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    inspected_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employee.id", ondelete="SET NULL"), default=None
    )

    estimated_minutes: Mapped[int] = mapped_column(default=30)
    actual_minutes: Mapped[int | None] = mapped_column(default=None)
    inspection_passed: Mapped[bool | None] = mapped_column(default=None)
    issues_found: Mapped[str | None] = mapped_column(Text, default=None)

    room: Mapped[Room] = relationship(back_populates="housekeeping_tasks")
    assigned_employee: Mapped[Employee | None] = relationship(foreign_keys=[assigned_employee_id])
    inspected_by: Mapped[Employee | None] = relationship(foreign_keys=[inspected_by_employee_id])

    @property
    def is_open(self) -> bool:
        return self.status in {
            HousekeepingStatus.PENDING,
            HousekeepingStatus.ASSIGNED,
            HousekeepingStatus.IN_PROGRESS,
        }

    @property
    def duration_minutes(self) -> int | None:
        """Baslangictan bitise gecen sure."""
        if self.started_at is None or self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at).total_seconds() // 60)


class MaintenanceTicket(Base, TimestampMixin, NotesMixin):
    """Ariza / bakim kaydi."""

    __table_args__ = (
        Index("ix_maint_status_priority", "status", "priority"),
        Index("ix_maint_room", "room_id", "status"),
    )

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    ticket_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("room.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="Ortak alan arizalarinda bos olabilir.",
    )
    location_description: Mapped[str | None] = mapped_column(
        String(200), default=None, doc="Oda disi konum, or. 'Lobi - 2. asansor'."
    )

    category: Mapped[MaintenanceCategory] = mapped_column(
        enum_column(MaintenanceCategory), default=MaintenanceCategory.OTHER, index=True
    )
    status: Mapped[MaintenanceStatus] = mapped_column(
        enum_column(MaintenanceStatus), default=MaintenanceStatus.OPEN, index=True
    )
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority), default=Priority.NORMAL, index=True
    )

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)

    reported_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    reported_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    assigned_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employee.id", ondelete="SET NULL"), default=None, index=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    # ---- Odayi satisa kapatma ----
    blocks_room: Mapped[bool] = mapped_column(
        default=False, doc="True ise oda satisa kapatilir (out of service)."
    )
    block_from: Mapped[date | None] = mapped_column(Date, default=None)
    block_until: Mapped[date | None] = mapped_column(Date, default=None)

    # ---- Periyodik bakim ----
    is_preventive: Mapped[bool] = mapped_column(default=False, doc="Periyodik/onleyici bakim.")
    recurrence_days: Mapped[int | None] = mapped_column(
        default=None, doc="Kac gunde bir tekrarlanacak."
    )
    next_due_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)

    labor_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    parts_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    resolution_notes: Mapped[str | None] = mapped_column(Text, default=None)

    room: Mapped[Room | None] = relationship(back_populates="maintenance_tickets")
    assigned_employee: Mapped[Employee | None] = relationship()
    reported_by: Mapped[User | None] = relationship()
    parts: Mapped[list[MaintenancePart]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )

    @property
    def total_cost(self) -> Decimal:
        return self.labor_cost + self.parts_cost

    @property
    def is_open(self) -> bool:
        return self.status not in {
            MaintenanceStatus.RESOLVED,
            MaintenanceStatus.CLOSED,
            MaintenanceStatus.CANCELLED,
        }

    @property
    def resolution_hours(self) -> float | None:
        """Bildirimden cozume kadar gecen saat."""
        if self.resolved_at is None:
            return None
        return round((self.resolved_at - self.reported_at).total_seconds() / 3600, 1)


class MaintenancePart(Base, TimestampMixin):
    """Bakimda kullanilan parca ve maliyeti."""

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_ticket.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_item.id", ondelete="SET NULL"), default=None
    )
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("1.000"))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    ticket: Mapped[MaintenanceTicket] = relationship(back_populates="parts")
    inventory_item: Mapped[InventoryItem | None] = relationship()


class LostAndFoundItem(Base, TimestampMixin, NotesMixin):
    """Kayip esya kaydi."""

    __table_args__ = (Index("ix_lost_found_status", "status", "found_date"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("room.id", ondelete="SET NULL"), default=None
    )
    guest_id: Mapped[int | None] = mapped_column(
        ForeignKey("guest.id", ondelete="SET NULL"),
        default=None,
        doc="Sahibi tespit edilebildiyse.",
    )

    item_description: Mapped[str] = mapped_column(String(300))
    found_location: Mapped[str | None] = mapped_column(String(200), default=None)
    found_date: Mapped[date] = mapped_column(Date, index=True)
    found_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employee.id", ondelete="SET NULL"), default=None
    )

    status: Mapped[LostItemStatus] = mapped_column(
        enum_column(LostItemStatus), default=LostItemStatus.FOUND, index=True
    )
    storage_location: Mapped[str | None] = mapped_column(String(120), default=None)
    returned_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    returned_to: Mapped[str | None] = mapped_column(String(200), default=None)
    photo_path: Mapped[str | None] = mapped_column(String(400), default=None)

    room: Mapped[Room | None] = relationship()
    guest: Mapped[Guest | None] = relationship()


class MinibarConsumption(Base, TimestampMixin):
    """Minibar tuketim kaydi - hem folyoya ucret hem stoktan dusum uretir."""

    __table_args__ = (Index("ix_minibar_room_date", "room_id", "consumption_date"),)

    room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), index=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), index=True)
    stay_id: Mapped[int | None] = mapped_column(
        ForeignKey("stay.id", ondelete="SET NULL"), default=None
    )
    folio_id: Mapped[int | None] = mapped_column(
        ForeignKey("folio.id", ondelete="SET NULL"), default=None
    )
    charge_id: Mapped[int | None] = mapped_column(
        ForeignKey("charge.id", ondelete="SET NULL"),
        default=None,
        doc="Folyoya islenen ucret satiri (varsa).",
    )

    consumption_date: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("1.000"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    recorded_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employee.id", ondelete="SET NULL"), default=None
    )
    is_charged: Mapped[bool] = mapped_column(default=False, doc="Folyoya islendi mi?")

    room: Mapped[Room] = relationship()
    inventory_item: Mapped[InventoryItem] = relationship()


__all__ = [
    "HousekeepingTask",
    "LostAndFoundItem",
    "MaintenancePart",
    "MaintenanceTicket",
    "MinibarConsumption",
]
