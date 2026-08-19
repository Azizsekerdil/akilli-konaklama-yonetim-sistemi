"""Teknik servis (ariza/bakim) servisi.

En kritik kural: **satilmis bir odayi sessizce kapatmak yasaktir.**

Bir ariza kaydi ``blocks_room=True`` ile acildiginda oda satisa kapatilir.
Eger o odada blok tarihleriyle cakisan aktif bir rezervasyon varsa islem
:class:`~app.core.exceptions.BusinessRuleError` ile **durdurulur**. Aksi halde
teknik servis odayi kapatir, kimse fark etmez ve misafir giris gunu kapida
kalir. Bilincli olarak devam edilmek istenirse ``force=True`` gecilir; bu da
:data:`~app.security.permissions.Perm.RESERVATION_OVERRIDE` yetkisi ister ve
denetim gunlugune ayrica yazilir. Odayi bosaltmak (misafiri baska odaya
almak) cagiran tarafin isidir - servis yalnizca kararin bilincli
alinmasini garanti eder.

Blokenin kaldirilmasi
---------------------
:meth:`MaintenanceService.resolve` odayi otomatik olarak yeniden satilabilir
hale getirir ama **DIRTY** yapar: teknik servis geldigi icin oda temizlik
ister. Ayni odada baska bir acik blokeli ariza varsa blok kaldirilmaz.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.application.context import ServiceContext
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.core.log import get_logger
from app.domain.enums import (
    UNSELLABLE_ROOM_STATUSES,
    AuditAction,
    EmploymentStatus,
    MaintenanceCategory,
    MaintenanceStatus,
    Priority,
    RoomHousekeepingStatus,
)
from app.domain.rules.availability import Booking
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.operations import MaintenancePart, MaintenanceTicket
from app.infrastructure.db.models.organization import Department, Employee
from app.infrastructure.db.models.rooms import Room
from app.infrastructure.db.repositories import OperationsRepository, ReservationRepository
from app.infrastructure.db.repositories.operations_repository import OPEN_MAINTENANCE_STATUSES
from app.security.permissions import Perm

log = get_logger(__name__)

#: Teknik servis departmani icin aranan kodlar (bkz. HousekeepingService.staff).
MAINTENANCE_DEPARTMENT_CODES: tuple[str, ...] = ("TEKNIK", "MAINTENANCE")

#: Bitis tarihi verilmemis (ucu acik) bir blokede cakisma taramasinin
#: kapsayacagi gun sayisi. Sonsuza kadar taramak mumkun degildir; bir yil
#: otel rezervasyon ufkunun cok otesindedir ve pratikte tum riski yakalar.
OPEN_BLOCK_HORIZON_DAYS = 365


@dataclass(frozen=True, slots=True)
class PartUsage:
    """Bakimda kullanilan bir parca.

    Tutarlar :class:`~decimal.Decimal`'dir; arayuz katmani kullaniciya
    gosterilen degeri ``Decimal(str(...))`` ile cevirmelidir - ``float``
    aritmetigi kurus kaybettirir.
    """

    description: str
    quantity: Decimal = Decimal("1")
    unit_cost: Decimal = Decimal("0.00")
    inventory_item_id: int | None = None

    @property
    def total_cost(self) -> Decimal:
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"))


class MaintenanceService:
    """Ariza kayitlari, teknisyen atamasi ve oda blokeleri."""

    def __init__(self, context: ServiceContext) -> None:
        self.ctx = context
        self.session = context.session
        self.operations = OperationsRepository(context.session)
        self.reservations = ReservationRepository(context.session)

    # ----------------------------------------------------------------- #
    #  Listeleme
    # ----------------------------------------------------------------- #
    def open_tickets(self, priority: Priority | None = None) -> list[MaintenanceTicket]:
        """Henuz cozulmemis ariza kayitlari - en acil olan basta."""
        self.ctx.require(Perm.MAINTENANCE_VIEW)
        return self.operations.open_maintenance_tickets(
            self.ctx.require_property(), priority=priority
        )

    def all_tickets(
        self,
        *,
        status: MaintenanceStatus | None = None,
        priority: Priority | None = None,
        room_id: int | None = None,
    ) -> list[MaintenanceTicket]:
        """Tum ariza kayitlarini (kapatilanlar dahil) suzerek dondurur.

        Siralama neden Python tarafinda?
        --------------------------------
        Oncelik veritabaninda metin olarak saklanir; ``ORDER BY priority``
        alfabetik siralar ve ``critical`` listenin basina gelmez. Dogru sira
        :attr:`Priority.weight` agirligiyla kurulur.
        """
        self.ctx.require(Perm.MAINTENANCE_VIEW)
        property_id = self.ctx.require_property()

        stmt = select(MaintenanceTicket).where(MaintenanceTicket.property_id == property_id)
        if status is not None:
            stmt = stmt.where(MaintenanceTicket.status == status)
        if priority is not None:
            stmt = stmt.where(MaintenanceTicket.priority == priority)
        if room_id is not None:
            stmt = stmt.where(MaintenanceTicket.room_id == room_id)

        tickets = list(self.session.scalars(stmt).all())
        tickets.sort(key=lambda t: (-t.priority.weight, t.reported_at, t.id))
        return tickets

    def technicians(self) -> list[Employee]:
        """Ariza atanabilecek aktif teknik servis personeli."""
        self.ctx.require(Perm.MAINTENANCE_VIEW)
        property_id = self.ctx.require_property()

        stmt = select(Employee).where(
            Employee.property_id == property_id,
            Employee.employment_status == EmploymentStatus.ACTIVE,
        )
        department_ids = list(
            self.session.scalars(
                select(Department.id).where(
                    Department.property_id == property_id,
                    Department.code.in_(MAINTENANCE_DEPARTMENT_CODES),
                )
            ).all()
        )
        if department_ids:
            stmt = stmt.where(Employee.department_id.in_(department_ids))
        return list(
            self.session.scalars(stmt.order_by(Employee.last_name, Employee.first_name)).all()
        )

    # ----------------------------------------------------------------- #
    #  Kayit acma
    # ----------------------------------------------------------------- #
    def create_ticket(
        self,
        *,
        room_id: int | None,
        category: MaintenanceCategory,
        title: str,
        description: str,
        priority: Priority = Priority.NORMAL,
        blocks_room: bool = False,
        block_from: date | None = None,
        block_until: date | None = None,
        location_description: str | None = None,
        force: bool = False,
    ) -> MaintenanceTicket:
        """Yeni ariza kaydi acar; istenirse odayi satisa kapatir.

        Parameters
        ----------
        room_id:
            Ariza bir odada degilse ``None`` (ortak alan). O durumda
            ``location_description`` doldurulmalidir.
        blocks_room:
            ``True`` ise oda ``OUT_OF_SERVICE`` yapilir. Bu **ayri bir
            yetkidir** (:data:`Perm.ROOM_BLOCK`): ariza kaydi acabilen
            herkes odayi satistan cekemez.
        block_from / block_until:
            Blokenin baslangici ve **dahil** son gunu. ``block_until``
            bossa bloke ucu aciktir.
        force:
            Cakisan rezervasyon uyarisini asar.
            :data:`Perm.RESERVATION_OVERRIDE` yetkisi gerekir.

        Raises
        ------
        BusinessRuleError
            Blok tarihleriyle cakisan aktif rezervasyon varsa ve
            ``force=False`` ise (``code="room_has_reservation"``).
        """
        self.ctx.require(Perm.MAINTENANCE_CREATE)
        property_id = self.ctx.require_property()

        # Enum'lar ``str`` tabanlidir; arayuz (QComboBox userData) ve HTTP
        # katmani bunlari duz metne cevirebilir. Girdiyi burada normallestirmek,
        # ``priority.value`` gibi erisimlerin sessizce ``AttributeError``
        # firlatmasini onler ve gecersiz degeri anlasilir bir hataya cevirir.
        try:
            category = MaintenanceCategory(category)
            priority = Priority(priority)
        except ValueError as exc:
            raise ValidationError(
                "Gecersiz ariza kategorisi veya oncelik degeri.",
                field="category",
                detail=str(exc),
            ) from exc

        if not title or not title.strip():
            raise ValidationError("Ariza basligi zorunludur.", field="title")
        if not description or not description.strip():
            raise ValidationError("Ariza aciklamasi zorunludur.", field="description")

        room = self._room_or_none(room_id, property_id)
        if blocks_room and room is None:
            raise ValidationError(
                "Oda secilmeden satisa kapatma yapilamaz.",
                field="room_id",
            )
        if room is None and not (location_description and location_description.strip()):
            raise ValidationError(
                "Oda disi ariza icin konum aciklamasi zorunludur.",
                field="location_description",
            )
        if block_from is not None and block_until is not None and block_until < block_from:
            raise ValidationError(
                "Bloke bitis tarihi baslangictan once olamaz.",
                field="block_until",
            )

        conflicts: list[Booking] = []
        if blocks_room and room is not None:
            # Odayi satistan cekmek yikici bir islemdir; ayri yetki ister.
            self.ctx.require(Perm.ROOM_BLOCK)
            conflicts = self._conflicting_bookings(room.id, block_from, block_until)
            if conflicts and not force:
                raise BusinessRuleError(
                    self._conflict_message(room, conflicts),
                    code="room_has_reservation",
                    detail=f"{len(conflicts)} cakisan rezervasyon bulundu.",
                    context={
                        "cozum": (
                            "Once misafiri baska bir odaya alin ya da yetkili onayiyla "
                            "devam edin."
                        ),
                        "room_id": room.id,
                        "conflict_count": len(conflicts),
                    },
                )
            if conflicts:
                # Bilincli asim: yetki kontrolu + kalici iz.
                self.ctx.require(Perm.RESERVATION_OVERRIDE)

        ticket = MaintenanceTicket(
            property_id=property_id,
            ticket_number=self.operations.next_ticket_number(property_id),
            room_id=room.id if room is not None else None,
            location_description=(location_description.strip() if location_description else None),
            category=category,
            status=MaintenanceStatus.OPEN,
            priority=priority,
            title=title.strip(),
            description=description.strip(),
            reported_at=utcnow(),
            reported_by_user_id=self.ctx.user_id,
            blocks_room=blocks_room,
            block_from=block_from,
            block_until=block_until,
        )
        self.session.add(ticket)
        self.session.flush()

        if blocks_room and room is not None:
            room.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
            room.out_of_service_from = block_from
            room.out_of_service_until = block_until
            room.out_of_service_reason = f"{ticket.ticket_number} - {ticket.title}"
            self.session.flush()

        self.ctx.audit(
            AuditAction.CREATE,
            f"{ticket.ticket_number} ariza kaydi acildi: {ticket.title}"
            + (f" ({room.number} numarali oda satisa kapatildi)" if blocks_room and room else ""),
            entity_type="MaintenanceTicket",
            entity_id=ticket.id,
            after={
                "priority": priority.value,
                "blocks_room": blocks_room,
                "forced": bool(conflicts),
            },
        )
        if conflicts:
            log.warning(
                "satilmis_oda_bloke_edildi",
                ticket=ticket.ticket_number,
                room=room.number if room else None,
                conflicts=[b.confirmation_number for b in conflicts],
            )
        return ticket

    # ----------------------------------------------------------------- #
    #  Yasam dongusu
    # ----------------------------------------------------------------- #
    def assign(self, ticket_id: int, employee_id: int) -> MaintenanceTicket:
        """Arizayi bir teknisyene atar."""
        self.ctx.require(Perm.MAINTENANCE_ASSIGN)
        ticket = self._get_ticket(ticket_id)
        if not ticket.is_open:
            raise BusinessRuleError(
                "Kapanmis bir arizaya teknisyen atanamaz.",
                code="ticket_closed",
                context={"status": ticket.status.value},
            )

        employee = self.session.get(Employee, employee_id)
        if employee is None:
            raise NotFoundError("Personel", employee_id)
        if employee.property_id != ticket.property_id:
            raise ValidationError("Personel bu tesise bagli degil.", field="employee_id")
        if not employee.is_available:
            raise BusinessRuleError(
                f"{employee.full_name} su anda gorev alamaz "
                f"({employee.employment_status.label}).",
                code="employee_unavailable",
            )

        before = {"employee_id": ticket.assigned_employee_id, "status": ticket.status.value}
        # Iliskiyi atiyoruz, yalnizca yabanci anahtari degil: daha once
        # yuklenmis ``ticket.assigned_employee`` bayat kalir ve ekran atamadan
        # sonra hala "Atanmadi" gosterirdi (bkz. HousekeepingService.assign).
        ticket.assigned_employee = employee
        ticket.assigned_at = utcnow()
        if ticket.status is MaintenanceStatus.OPEN:
            ticket.status = MaintenanceStatus.ASSIGNED
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{ticket.ticket_number} kaydi {employee.full_name} kisisine atandi.",
            entity_type="MaintenanceTicket",
            entity_id=ticket.id,
            before=before,
            after={"employee_id": employee.id, "status": ticket.status.value},
        )
        return ticket

    def resolve(
        self,
        ticket_id: int,
        resolution_notes: str,
        labor_cost: Decimal = Decimal("0.00"),
        parts: Sequence[PartUsage] = (),
    ) -> MaintenanceTicket:
        """Arizayi cozer, blokeyi kaldirir ve odayi temizlige gonderir."""
        self.ctx.require(Perm.MAINTENANCE_RESOLVE)
        ticket = self._get_ticket(ticket_id)

        if not ticket.is_open:
            raise BusinessRuleError(
                "Bu ariza kaydi zaten kapanmis.",
                code="ticket_closed",
                context={"status": ticket.status.value},
            )
        if not resolution_notes or not resolution_notes.strip():
            raise ValidationError("Cozum aciklamasi zorunludur.", field="resolution_notes")
        if labor_cost < 0:
            raise ValidationError("Iscilik maliyeti negatif olamaz.", field="labor_cost")

        parts_cost = Decimal("0.00")
        for part in parts:
            if not part.description or not part.description.strip():
                raise ValidationError("Parca aciklamasi zorunludur.", field="parts")
            if part.quantity <= 0:
                raise ValidationError("Parca miktari sifirdan buyuk olmalidir.", field="parts")
            if part.unit_cost < 0:
                raise ValidationError("Parca birim maliyeti negatif olamaz.", field="parts")
            line_total = part.total_cost
            parts_cost += line_total
            # Iliskiye ekliyoruz: ``session.add`` ile eklenen satir daha once
            # yuklenmis ``ticket.parts`` koleksiyonuna yansimaz ve maliyet
            # dokumu bayat kalirdi.
            ticket.parts.append(
                MaintenancePart(
                    inventory_item_id=part.inventory_item_id,
                    description=part.description.strip(),
                    quantity=part.quantity,
                    unit_cost=part.unit_cost,
                    total_cost=line_total,
                )
            )

        ticket.status = MaintenanceStatus.RESOLVED
        ticket.resolved_at = utcnow()
        ticket.resolution_notes = resolution_notes.strip()
        ticket.labor_cost = labor_cost
        ticket.parts_cost = parts_cost
        self.session.flush()

        released = self._release_room_block(ticket)

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{ticket.ticket_number} cozuldu. Toplam maliyet: {ticket.total_cost}",
            entity_type="MaintenanceTicket",
            entity_id=ticket.id,
            after={
                "status": ticket.status.value,
                "labor_cost": str(labor_cost),
                "parts_cost": str(parts_cost),
                "room_released": released,
            },
        )
        return ticket

    def close(self, ticket_id: int) -> MaintenanceTicket:
        """Cozulmus bir arizayi kapatir (kayit arsive gecer)."""
        self.ctx.require(Perm.MAINTENANCE_RESOLVE)
        ticket = self._get_ticket(ticket_id)

        if ticket.status is MaintenanceStatus.CLOSED:
            raise BusinessRuleError("Bu kayit zaten kapatilmis.", code="already_closed")
        if ticket.status is not MaintenanceStatus.RESOLVED:
            raise BusinessRuleError(
                "Yalnizca cozulmus bir ariza kapatilabilir.",
                code="ticket_not_resolved",
                context={"status": ticket.status.value},
            )

        ticket.status = MaintenanceStatus.CLOSED
        ticket.closed_at = utcnow()
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{ticket.ticket_number} kaydi kapatildi.",
            entity_type="MaintenanceTicket",
            entity_id=ticket.id,
            after={"status": ticket.status.value},
        )
        return ticket

    # ----------------------------------------------------------------- #
    #  Yardimcilar
    # ----------------------------------------------------------------- #
    def _get_ticket(self, ticket_id: int) -> MaintenanceTicket:
        ticket = self.session.get(MaintenanceTicket, ticket_id)
        if ticket is None:
            raise NotFoundError("Ariza kaydi", ticket_id)
        return ticket

    def _room_or_none(self, room_id: int | None, property_id: int) -> Room | None:
        if room_id is None:
            return None
        room = self.session.get(Room, room_id)
        if room is None:
            raise NotFoundError("Oda", room_id)
        if room.property_id != property_id:
            raise ValidationError("Oda bu tesise ait degil.", field="room_id")
        return room

    def _conflicting_bookings(
        self,
        room_id: int,
        block_from: date | None,
        block_until: date | None,
    ) -> list[Booking]:
        """Blok penceresiyle cakisan aktif rezervasyonlari dondurur.

        Tarih donusumu tuzagi: ``block_until`` **dahil** bir son gundur
        ("3 Agustos'a kadar kapali" 3 Agustos'u kapsar),
        :class:`DateRange` ise yari aciktir. Bu yuzden bitise bir gun
        eklenir; eklenmezse blogun son gecesindeki rezervasyon gorulmez.
        """
        start = block_from or utcnow().date()
        if block_until is not None:
            end = block_until + timedelta(days=1)
        else:
            end = start + timedelta(days=OPEN_BLOCK_HORIZON_DAYS)
        if end <= start:  # pragma: no cover - dogrulama zaten engelliyor
            end = start + timedelta(days=1)
        return self.reservations.bookings_for_room(room_id, DateRange(start, end))

    @staticmethod
    def _conflict_message(room: Room, conflicts: Sequence[Booking]) -> str:
        first = conflicts[0]
        reference = first.confirmation_number or f"#{first.reservation_id}"
        extra = f" (+{len(conflicts) - 1} kayit daha)" if len(conflicts) > 1 else ""
        return (
            f"{room.number} numarali odada {first.date_range.format()} tarihlerinde "
            f"{reference} numarali rezervasyon var{extra}. "
            "Oda satisa kapatilirsa misafir kapida kalir."
        )

    def _release_room_block(self, ticket: MaintenanceTicket) -> bool:
        """Ariza cozuldugunde oda blokesini kaldirir.

        Ayni odada **baska** bir acik blokeli ariza varsa blok kaldirilmaz;
        aksi halde iki arizadan biri cozuldugunde oda satilabilir gorunur ve
        digeri hala devam ederken misafir kabul edilirdi.

        Returns
        -------
        bool
            Oda fiilen yeniden satilabilir hale getirildiyse ``True``.
        """
        if not ticket.blocks_room or ticket.room_id is None:
            return False
        room = self.session.get(Room, ticket.room_id)
        if room is None:  # pragma: no cover - FK garantisi
            return False

        remaining = (
            self.session.scalar(
                select(func.count(MaintenanceTicket.id)).where(
                    MaintenanceTicket.room_id == room.id,
                    MaintenanceTicket.id != ticket.id,
                    MaintenanceTicket.blocks_room.is_(True),
                    MaintenanceTicket.status.in_(list(OPEN_MAINTENANCE_STATUSES)),
                )
            )
            or 0
        )
        if remaining:
            log.info(
                "oda_blokesi_korundu",
                room=room.number,
                remaining_tickets=remaining,
            )
            return False

        if room.housekeeping_status in UNSELLABLE_ROOM_STATUSES:
            # Teknik servis odada calisti; temizlik gerekir.
            room.housekeeping_status = RoomHousekeepingStatus.DIRTY
        room.out_of_service_from = None
        room.out_of_service_until = None
        room.out_of_service_reason = None
        self.session.flush()
        return True


__all__ = [
    "MAINTENANCE_DEPARTMENT_CODES",
    "OPEN_BLOCK_HORIZON_DAYS",
    "MaintenanceService",
    "PartUsage",
]
