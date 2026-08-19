"""Yonetim paneli verilerini toplayan servis.

Panel, uygulamanin en sik acilan ekranidir; bu yuzden **tek bir cagriyla**
tum veriyi doner ve arayuz her kart icin ayri sorgu calistirmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.application.context import ServiceContext
from app.core.log import get_logger
from app.domain.enums import (
    UNSELLABLE_ROOM_STATUSES,
    ChargeType,
    HousekeepingStatus,
    MaintenanceStatus,
    Priority,
    ReservationStatus,
    RoomHousekeepingStatus,
    RoomOccupancyStatus,
)
from app.domain.rules.availability import compute_occupancy
from app.domain.value_objects import DateRange, Money
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.billing import Charge, Folio
from app.infrastructure.db.models.inventory import InventoryItem
from app.infrastructure.db.models.operations import HousekeepingTask, MaintenanceTicket
from app.infrastructure.db.models.reservations import Reservation, ReservationRoom
from app.infrastructure.db.models.rooms import Room
from app.infrastructure.db.repositories import ReservationRepository, RoomRepository
from app.security.permissions import Perm

log = get_logger(__name__)


@dataclass(slots=True)
class Alert:
    """Panelde gosterilecek kritik uyari."""

    level: str
    """``warning`` | ``danger`` | ``info``"""

    title: str
    detail: str = ""
    action_key: str | None = None
    """Arayuzun hangi ekrana yonlendirecegi (or. ``maintenance``)."""


@dataclass(slots=True)
class DashboardSnapshot:
    """Panelin tek seferde ihtiyac duydugu tum veriler."""

    day: date

    # Doluluk
    total_rooms: int = 0
    sellable_rooms: int = 0
    occupied_rooms: int = 0
    vacant_rooms: int = 0
    dirty_rooms: int = 0
    out_of_service_rooms: int = 0
    occupancy_percent: float = 0.0

    # Hareketler
    arrivals_count: int = 0
    departures_count: int = 0
    in_house_count: int = 0
    pending_arrivals: int = 0
    """Bugun gelmesi gereken ama henuz giris yapmamislar."""

    # Gelir
    revenue_today: Money = field(default_factory=lambda: Money.zero())
    room_revenue_today: Money = field(default_factory=lambda: Money.zero())
    revenue_week: Money = field(default_factory=lambda: Money.zero())
    revenue_month: Money = field(default_factory=lambda: Money.zero())
    adr: Money = field(default_factory=lambda: Money.zero())
    revpar: Money = field(default_factory=lambda: Money.zero())

    # Gorevler
    pending_housekeeping: int = 0
    open_maintenance: int = 0
    urgent_maintenance: int = 0
    low_stock_items: int = 0

    # Uyarilar
    alerts: list[Alert] = field(default_factory=list)

    # Gelecek 14 gun doluluk egrisi (grafik icin)
    occupancy_forecast: list[tuple[date, float]] = field(default_factory=list)

    @property
    def available_rooms(self) -> int:
        """Satilabilir ve bos oda sayisi."""
        return max(self.sellable_rooms - self.occupied_rooms, 0)


class DashboardService:
    """Yonetim paneli verilerini hazirlar."""

    FORECAST_DAYS = 14

    def __init__(self, context: ServiceContext) -> None:
        self.ctx = context
        self.session = context.session
        self.reservations = ReservationRepository(context.session)
        self.rooms = RoomRepository(context.session)

    def get_snapshot(self, day: date | None = None) -> DashboardSnapshot:
        """Panel verilerini tek seferde toplar."""
        self.ctx.require(Perm.DASHBOARD_VIEW)
        property_id = self.ctx.require_property()
        target_day = day or utcnow().date()

        snapshot = DashboardSnapshot(day=target_day)

        self._fill_rooms(snapshot, property_id)
        self._fill_movements(snapshot, property_id, target_day)
        self._fill_revenue(snapshot, property_id, target_day)
        self._fill_tasks(snapshot, property_id, target_day)
        self._fill_forecast(snapshot, property_id, target_day)
        self._fill_alerts(snapshot, property_id)

        return snapshot

    # ----------------------------------------------------------------- #
    def _fill_rooms(self, snapshot: DashboardSnapshot, property_id: int) -> None:
        rows = self.session.execute(
            select(
                Room.occupancy_status,
                Room.housekeeping_status,
                func.count(Room.id),
            )
            .where(Room.property_id == property_id, Room.is_active.is_(True))
            .group_by(Room.occupancy_status, Room.housekeeping_status)
        ).all()

        for occupancy, housekeeping, count in rows:
            snapshot.total_rooms += count
            if housekeeping in UNSELLABLE_ROOM_STATUSES:
                snapshot.out_of_service_rooms += count
                continue
            snapshot.sellable_rooms += count
            if occupancy is RoomOccupancyStatus.OCCUPIED:
                snapshot.occupied_rooms += count
            else:
                snapshot.vacant_rooms += count
            if housekeeping is RoomHousekeepingStatus.DIRTY:
                snapshot.dirty_rooms += count

        if snapshot.sellable_rooms:
            snapshot.occupancy_percent = round(
                snapshot.occupied_rooms / snapshot.sellable_rooms * 100, 1
            )

    def _fill_movements(self, snapshot: DashboardSnapshot, property_id: int, day: date) -> None:
        arrivals = self.reservations.arrivals_on(property_id, day)
        snapshot.arrivals_count = len(arrivals)
        snapshot.pending_arrivals = sum(1 for row in arrivals if row.stay is None)
        snapshot.departures_count = len(self.reservations.departures_on(property_id, day))
        snapshot.in_house_count = len(self.reservations.in_house_on(property_id, day))

    def _fill_revenue(self, snapshot: DashboardSnapshot, property_id: int, day: date) -> None:
        def revenue_between(start: date, end: date, *, only_room: bool = False) -> Decimal:
            stmt = (
                select(func.coalesce(func.sum(Charge.total_amount), 0))
                .join(Folio, Charge.folio_id == Folio.id)
                .where(
                    Folio.property_id == property_id,
                    Charge.is_void.is_(False),
                    Charge.charge_date >= start,
                    Charge.charge_date <= end,
                )
            )
            if only_room:
                stmt = stmt.where(Charge.charge_type == ChargeType.ROOM)
            return Decimal(str(self.session.scalar(stmt) or 0))

        snapshot.revenue_today = Money.of(revenue_between(day, day))
        snapshot.room_revenue_today = Money.of(revenue_between(day, day, only_room=True))
        snapshot.revenue_week = Money.of(revenue_between(day - timedelta(days=6), day))
        snapshot.revenue_month = Money.of(revenue_between(day.replace(day=1), day))

        # ADR: yalnizca ODA geliri / satilan oda gecesi.
        # Restoran, spa, minibar gelirleri ADR'ye GIRMEZ - sektor standardi.
        if snapshot.occupied_rooms:
            snapshot.adr = snapshot.room_revenue_today / snapshot.occupied_rooms
        if snapshot.sellable_rooms:
            snapshot.revpar = snapshot.room_revenue_today / snapshot.sellable_rooms

    def _fill_tasks(self, snapshot: DashboardSnapshot, property_id: int, day: date) -> None:
        snapshot.pending_housekeeping = (
            self.session.scalar(
                select(func.count(HousekeepingTask.id)).where(
                    HousekeepingTask.property_id == property_id,
                    HousekeepingTask.scheduled_date <= day,
                    HousekeepingTask.status.in_(
                        [
                            HousekeepingStatus.PENDING,
                            HousekeepingStatus.ASSIGNED,
                            HousekeepingStatus.IN_PROGRESS,
                        ]
                    ),
                )
            )
            or 0
        )

        open_statuses = [
            MaintenanceStatus.OPEN,
            MaintenanceStatus.ASSIGNED,
            MaintenanceStatus.IN_PROGRESS,
            MaintenanceStatus.WAITING_PARTS,
        ]
        snapshot.open_maintenance = (
            self.session.scalar(
                select(func.count(MaintenanceTicket.id)).where(
                    MaintenanceTicket.property_id == property_id,
                    MaintenanceTicket.status.in_(open_statuses),
                )
            )
            or 0
        )
        snapshot.urgent_maintenance = (
            self.session.scalar(
                select(func.count(MaintenanceTicket.id)).where(
                    MaintenanceTicket.property_id == property_id,
                    MaintenanceTicket.status.in_(open_statuses),
                    MaintenanceTicket.priority.in_([Priority.URGENT, Priority.CRITICAL]),
                )
            )
            or 0
        )
        snapshot.low_stock_items = (
            self.session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.property_id == property_id,
                    InventoryItem.is_active.is_(True),
                    InventoryItem.current_stock < InventoryItem.minimum_stock,
                )
            )
            or 0
        )

    def _fill_forecast(self, snapshot: DashboardSnapshot, property_id: int, day: date) -> None:
        """Gelecek gunlerin doluluk tahmini (mevcut rezervasyonlara gore)."""
        window = DateRange(day, day + timedelta(days=self.FORECAST_DAYS))
        bookings = self.reservations.bookings_for_range(property_id, window)

        stats = compute_occupancy(
            window.days,
            bookings=bookings,
            total_rooms=snapshot.sellable_rooms or snapshot.total_rooms,
        )
        snapshot.occupancy_forecast = [(s.day, s.occupancy_percent) for s in stats]

    def _fill_alerts(self, snapshot: DashboardSnapshot, property_id: int) -> None:
        """Yoneticinin dikkat etmesi gereken durumlari toplar."""
        alerts: list[Alert] = []

        if snapshot.urgent_maintenance:
            alerts.append(
                Alert(
                    level="danger",
                    title=f"{snapshot.urgent_maintenance} acil ariza kaydi var",
                    detail="Teknik servis ekranindan inceleyin.",
                    action_key="maintenance",
                )
            )

        if snapshot.out_of_service_rooms:
            alerts.append(
                Alert(
                    level="warning",
                    title=f"{snapshot.out_of_service_rooms} oda satisa kapali",
                    detail="Bu odalar doluluk hesabinda envanterden dusulur.",
                    action_key="rooms",
                )
            )

        if snapshot.low_stock_items:
            alerts.append(
                Alert(
                    level="warning",
                    title=f"{snapshot.low_stock_items} urun kritik stok seviyesinde",
                    detail="Satin alma talebi olusturmayi degerlendirin.",
                    action_key="inventory",
                )
            )

        if snapshot.pending_arrivals:
            alerts.append(
                Alert(
                    level="info",
                    title=f"{snapshot.pending_arrivals} misafir henuz giris yapmadi",
                    detail="Gun sonunda gelmeyenleri 'no-show' olarak isaretleyin.",
                    action_key="frontdesk",
                )
            )

        # Gecmis tarihli, hala 'onaylandi' durumunda kalan rezervasyonlar:
        # buyuk olasilikla no-show olarak isaretlenmeyi bekliyor.
        stale = (
            self.session.scalar(
                select(func.count(Reservation.id)).where(
                    Reservation.property_id == property_id,
                    Reservation.status == ReservationStatus.CONFIRMED,
                    Reservation.check_in_date < snapshot.day,
                    Reservation.is_deleted.is_(False),
                )
            )
            or 0
        )
        if stale:
            alerts.append(
                Alert(
                    level="warning",
                    title=f"{stale} gecmis tarihli rezervasyon islem bekliyor",
                    detail="Giris yapilmamis eski rezervasyonlari kapatin.",
                    action_key="reservations",
                )
            )

        if snapshot.dirty_rooms and snapshot.pending_arrivals:
            alerts.append(
                Alert(
                    level="info",
                    title=f"{snapshot.dirty_rooms} kirli oda, {snapshot.pending_arrivals} giris bekliyor",
                    detail="Kat hizmetleri onceliklendirmesi gerekebilir.",
                    action_key="housekeeping",
                )
            )

        snapshot.alerts = alerts

    # ----------------------------------------------------------------- #
    def upcoming_arrivals(self, days: int = 7) -> list[ReservationRoom]:
        """Onumuzdeki gunlerde beklenen girisler."""
        self.ctx.require(Perm.RESERVATION_VIEW)
        property_id = self.ctx.require_property()
        today = utcnow().date()

        return list(
            self.session.scalars(
                select(ReservationRoom)
                .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
                .where(
                    Reservation.property_id == property_id,
                    Reservation.is_deleted.is_(False),
                    Reservation.status.in_(
                        [ReservationStatus.CONFIRMED, ReservationStatus.TENTATIVE]
                    ),
                    ReservationRoom.is_cancelled.is_(False),
                    ReservationRoom.check_in_date >= today,
                    ReservationRoom.check_in_date <= today + timedelta(days=days),
                )
                .order_by(ReservationRoom.check_in_date)
            )
        )


__all__ = ["Alert", "DashboardService", "DashboardSnapshot"]
