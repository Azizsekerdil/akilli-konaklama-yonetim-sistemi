"""Kat hizmetleri ve teknik servis veri erisimi.

Bu modul ayni zamanda "acik gorev" ve "acik ariza kaydi" kumelerinin tek
dogruluk kaynagidir; oda musaitligi hesabi da (bkz.
:mod:`app.infrastructure.db.repositories.room_repository`) buradaki
:data:`OPEN_MAINTENANCE_STATUSES` kumesini kullanir.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select

from app.domain.enums import (
    BLOCKING_RESERVATION_STATUSES,
    UNSELLABLE_ROOM_STATUSES,
    HousekeepingStatus,
    MaintenanceStatus,
    Priority,
    RoomHousekeepingStatus,
)
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.operations import HousekeepingTask, MaintenanceTicket
from app.infrastructure.db.models.reservations import Reservation, ReservationRoom
from app.infrastructure.db.models.rooms import Room
from app.infrastructure.db.repositories.base import BaseRepository, next_sequence_number

#: Henuz kapanmamis kat hizmetleri gorevleri.
#: :attr:`HousekeepingTask.is_open` ile ayni kume - orada tek tek yazmak
#: yerine burada tanimlanir ki SQL suzgeci ile Python kontrolu ayrisamasin.
OPEN_HOUSEKEEPING_STATUSES: frozenset[HousekeepingStatus] = frozenset(
    {
        HousekeepingStatus.PENDING,
        HousekeepingStatus.ASSIGNED,
        HousekeepingStatus.IN_PROGRESS,
    }
)

#: Henuz cozulmemis ariza kayitlari (:attr:`MaintenanceTicket.is_open`).
OPEN_MAINTENANCE_STATUSES: frozenset[MaintenanceStatus] = frozenset(
    {
        MaintenanceStatus.OPEN,
        MaintenanceStatus.ASSIGNED,
        MaintenanceStatus.IN_PROGRESS,
        MaintenanceStatus.WAITING_PARTS,
    }
)

#: Ariza kaydi numarasi oneki.
TICKET_PREFIX = "ARZ"


class OperationsRepository(BaseRepository[HousekeepingTask]):
    """Kat hizmetleri gorevleri ve ariza kayitlari.

    Iki tabloyu tek repository'de toplamak bilincli bir tercihtir: gunluk
    operasyon ekrani ikisini birlikte gosterir ve "oda temizlige hazir mi"
    sorusu her ikisine de bakmayi gerektirir.
    """

    model = HousekeepingTask
    entity_label = "Kat hizmetleri gorevi"

    # ------------------------------------------------------------------
    #  Kat hizmetleri
    # ------------------------------------------------------------------
    def housekeeping_tasks(
        self,
        property_id: int,
        *,
        day: date | None = None,
        status: HousekeepingStatus | None = None,
        employee_id: int | None = None,
    ) -> list[HousekeepingTask]:
        """Kat hizmetleri gorevlerini suzerek listeler.

        Tum suzgecler opsiyoneldir; hicbiri verilmezse tesisin tum gorevleri
        doner. Siralama plan tarihi ve oda numarasina goredir - kat gorevlisi
        listesi bu sirayla basilir.
        """
        stmt = (
            select(HousekeepingTask)
            .join(Room, HousekeepingTask.room_id == Room.id)
            .where(HousekeepingTask.property_id == property_id)
        )
        if day is not None:
            stmt = stmt.where(HousekeepingTask.scheduled_date == day)
        if status is not None:
            stmt = stmt.where(HousekeepingTask.status == status)
        if employee_id is not None:
            stmt = stmt.where(HousekeepingTask.assigned_employee_id == employee_id)
        stmt = stmt.order_by(HousekeepingTask.scheduled_date, Room.number, HousekeepingTask.id)
        return list(self.session.scalars(stmt).all())

    def rooms_needing_cleaning(self, property_id: int, day: date) -> list[Room]:
        """Verilen gun temizlenmesi gereken odalari dondurur.

        Iki kaynak birlestirilir:

        * Halihazirda **kirli** isaretli odalar,
        * O gun **cikis** yapilacak odalar (cikis temizligi gerekir).

        Uc onemli ayrinti:

        1. Satisa kapali (servis disi / arizali) odalar listeye girmez;
           onlarin isi kat hizmetlerinde degil teknik serviste.
        2. O gun icin zaten **acik bir gorev** olusturulmus odalar dislanir.
           Aksi halde gun icinde ikinci kez calistirilan gorev uretici ayni
           oda icin mukerrer kayit acardi.
        3. Cikis tarihi suzgeci ``check_out_date == day`` seklindedir; yari
           acik aralik semantiginde cikis gunu konaklamaya dahil degildir,
           yani oda o gun bosalir.
        """
        departing_rooms = (
            select(ReservationRoom.room_id)
            .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
            .where(
                Reservation.property_id == property_id,
                Reservation.is_deleted.is_(False),
                Reservation.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
                ReservationRoom.is_cancelled.is_(False),
                ReservationRoom.room_id.is_not(None),
                ReservationRoom.check_out_date == day,
            )
        )
        already_scheduled = select(HousekeepingTask.room_id).where(
            HousekeepingTask.property_id == property_id,
            HousekeepingTask.scheduled_date == day,
            HousekeepingTask.status.in_(list(OPEN_HOUSEKEEPING_STATUSES)),
        )
        stmt = (
            select(Room)
            .where(
                Room.property_id == property_id,
                Room.is_active.is_(True),
                Room.housekeeping_status.not_in(list(UNSELLABLE_ROOM_STATUSES)),
                or_(
                    Room.housekeeping_status == RoomHousekeepingStatus.DIRTY,
                    Room.id.in_(departing_rooms),
                ),
                Room.id.not_in(already_scheduled),
            )
            .order_by(Room.number)
        )
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    #  Teknik servis
    # ------------------------------------------------------------------
    def open_maintenance_tickets(
        self,
        property_id: int,
        *,
        priority: Priority | None = None,
    ) -> list[MaintenanceTicket]:
        """Acik ariza kayitlarini oncelik sirasiyla dondurur.

        Siralama neden Python tarafinda?
        --------------------------------
        Oncelik veritabaninda metin olarak saklanir (``"urgent"``,
        ``"low"``...). ``ORDER BY priority`` alfabetik siralar ve
        ``critical`` en acil olmasina ragmen listenin basina gelmez.
        Dogru siralama :attr:`Priority.weight` agirligiyla yapilir; acik
        kayit sayisi bir tesiste onlarla olculdugu icin bellekte siralamak
        guvenlidir.
        """
        stmt = select(MaintenanceTicket).where(
            MaintenanceTicket.property_id == property_id,
            MaintenanceTicket.status.in_(list(OPEN_MAINTENANCE_STATUSES)),
        )
        if priority is not None:
            stmt = stmt.where(MaintenanceTicket.priority == priority)
        tickets = list(self.session.scalars(stmt).all())
        tickets.sort(key=lambda t: (-t.priority.weight, t.reported_at, t.id))
        return tickets

    def next_ticket_number(self, property_id: int) -> str:
        """Sonraki ariza kaydi numarasini uretir, or. ``ARZ-2026-000123``.

        ``property_id`` su an numaralandirmayi etkilemez: ``ticket_number``
        sutunu **veritabani genelinde** benzersizdir, bu yuzden sayac yil
        bazinda global tutulur. Parametre imzada tutulur cunku cok tesisli
        kurulumda onek tesis koduyla zenginlestirilecektir ve o degisiklik
        cagiran taraflari etkilememelidir.

        Es zamanlilik uyarisi icin bkz.
        :func:`~app.infrastructure.db.repositories.base.next_sequence_number`.
        """
        return next_sequence_number(
            self.session,
            MaintenanceTicket.ticket_number,
            prefix=f"{TICKET_PREFIX}-{utcnow().year}-",
        )


__all__ = [
    "OPEN_HOUSEKEEPING_STATUSES",
    "OPEN_MAINTENANCE_STATUSES",
    "TICKET_PREFIX",
    "OperationsRepository",
]
