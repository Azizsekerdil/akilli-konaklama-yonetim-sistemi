"""On buro servisi: check-in, check-out, erken giris, gec cikis.

Check-in akisi
--------------
1. Rezervasyon durumu kontrol edilir (durum makinesi)
2. Oda atanmamissa atanir; atanmissa musaitligi son kez dogrulanir
3. Odanin temiz ve satilabilir oldugu kontrol edilir
4. :class:`Stay` kaydi acilir, oda "dolu" isaretlenir
5. Folyo acilir ve **konaklama ucretleri gece gece islenir**
6. Erken giris ucreti varsa folyoya eklenir

Check-out akisi bunun tersidir; ek olarak bakiye kontrolu yapilir ve oda
kat hizmetleri icin "kirli" isaretlenerek temizlik gorevi olusturulur.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.application.context import ServiceContext
from app.application.services.folio_service import FolioService
from app.core.exceptions import (
    BusinessRuleError,
    NotFoundError,
    PaymentError,
    RoomNotAvailableError,
    ValidationError,
)
from app.core.log import get_logger
from app.domain.enums import (
    UNSELLABLE_ROOM_STATUSES,
    AuditAction,
    ChargeType,
    HousekeepingStatus,
    HousekeepingTaskType,
    Priority,
    ReservationStatus,
    RoomHousekeepingStatus,
    RoomOccupancyStatus,
    StayStatus,
)
from app.domain.rules.availability import check_availability
from app.domain.rules.pricing import calculate_early_late_fee
from app.domain.rules.reservation_state import assert_transition_allowed
from app.domain.value_objects import Money
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.operations import HousekeepingTask
from app.infrastructure.db.models.reservations import (
    Reservation,
    ReservationRoom,
    Stay,
)
from app.infrastructure.db.models.rooms import Room
from app.infrastructure.db.repositories import ReservationRepository, RoomRepository
from app.security.permissions import Perm

log = get_logger(__name__)


class FrontdeskService:
    """Giris-cikis islemleri."""

    def __init__(self, context: ServiceContext) -> None:
        self.ctx = context
        self.session = context.session
        self.reservations = ReservationRepository(context.session)
        self.rooms = RoomRepository(context.session)
        self.folios = FolioService(context)

    # ----------------------------------------------------------------- #
    #  Check-in
    # ----------------------------------------------------------------- #
    def check_in(
        self,
        reservation_room_id: int,
        *,
        room_id: int | None = None,
        key_card_count: int = 1,
        early_check_in_hours: int = 0,
        notes: str | None = None,
        allow_dirty_room: bool = False,
    ) -> Stay:
        """Misafir girisi yapar.

        Parameters
        ----------
        room_id:
            Oda atanmamissa hangi odaya yerlestirilecegi.
        early_check_in_hours:
            Standart giris saatinden kac saat once giris yapiliyor.
            Sifirdan buyukse ucret hesaplanip folyoya islenir.
        allow_dirty_room:
            Kirli odaya giris yalnizca bilincli onayla yapilabilir.
        """
        self.ctx.require(Perm.FRONTDESK_CHECKIN)

        row = self.session.get(ReservationRoom, reservation_room_id)
        if row is None:
            raise NotFoundError("Rezervasyon oda satiri", reservation_room_id)
        if row.is_cancelled:
            raise BusinessRuleError(
                "Iptal edilmis bir oda satirina giris yapilamaz.",
                code="room_row_cancelled",
            )
        if row.stay is not None:
            raise BusinessRuleError(
                "Bu oda satiri icin zaten giris yapilmis.",
                code="already_checked_in",
            )

        reservation = self.session.get(Reservation, row.reservation_id)
        if reservation is None:  # pragma: no cover - FK garantisi
            raise NotFoundError("Rezervasyon", row.reservation_id)

        assert_transition_allowed(reservation.status, ReservationStatus.CHECKED_IN)

        # --- Oda secimi ---
        target_room_id = room_id or row.room_id
        if target_room_id is None:
            raise ValidationError("Giris icin bir oda secilmelidir.", field="room_id")

        room = self.session.get(Room, target_room_id)
        if room is None:
            raise NotFoundError("Oda", target_room_id)

        if room.room_type_id != row.room_type_id:
            # Ust sinifa yerlestirme (upgrade) bilincli bir karardir;
            # yetkili onayi gerektirir.
            self.ctx.require(Perm.RESERVATION_OVERRIDE)

        # --- Oda durumu ---
        if room.housekeeping_status in UNSELLABLE_ROOM_STATUSES:
            raise RoomNotAvailableError(
                f"{room.number} numarali oda bakim nedeniyle kullanilamaz.",
                code="room_out_of_service",
                context={"room_id": room.id, "status": room.housekeeping_status.value},
            )
        if room.occupancy_status is RoomOccupancyStatus.OCCUPIED:
            raise RoomNotAvailableError(
                f"{room.number} numarali oda su anda dolu.",
                code="room_occupied",
            )
        if room.housekeeping_status is RoomHousekeepingStatus.DIRTY and not allow_dirty_room:
            raise BusinessRuleError(
                f"{room.number} numarali oda henuz temizlenmemis. "
                "Yine de giris yapmak icin onay gerekir.",
                code="room_dirty",
                context={"room_id": room.id},
            )

        # --- Musaitlik son kontrolu ---
        property_id = self.ctx.require_property()
        bookings = self.reservations.bookings_for_range(property_id, row.date_range)
        blocks = self.rooms.blocks_for_range(property_id, row.date_range)
        check_availability(
            row.date_range,
            room_id=room.id,
            existing_bookings=bookings,
            blocks=blocks,
            exclude_reservation_room_id=row.id,
        )

        # --- Kayitlar ---
        row.room_id = room.id
        room.occupancy_status = RoomOccupancyStatus.OCCUPIED

        stay = Stay(
            reservation_room_id=row.id,
            room_id=room.id,
            status=StayStatus.IN_HOUSE,
            actual_check_in=utcnow(),
            key_card_count=max(key_card_count, 0),
            is_early_check_in=early_check_in_hours > 0,
            notes=notes,
            checked_in_by_user_id=self.ctx.user_id,
        )
        # Iliski uzerinden atiyoruz: ``session.add`` ile eklenseydi
        # ``row.stay`` bayat kalir ve ayni satira ikinci kez giris yapilmasini
        # engelleyen kontrol calismazdi.
        row.stay = stay

        reservation.status = ReservationStatus.CHECKED_IN
        self.session.flush()

        # --- Folyo ve oda ucretleri ---
        folio = self.folios.open_folio(
            reservation_id=reservation.id,
            reservation_room_id=row.id,
            guest_id=reservation.primary_guest_id,
        )
        self._post_room_charges(folio.id, row)

        # --- Erken giris ucreti ---
        if early_check_in_hours > 0:
            self.ctx.require(Perm.FRONTDESK_EARLY_LATE)
            fee = calculate_early_late_fee(
                Money.of(row.nightly_rate, reservation.currency),
                hours=early_check_in_hours,
            )
            if not fee.is_zero:
                stay.early_check_in_fee = fee.amount
                self.folios.post_charge(
                    folio.id,
                    charge_type=ChargeType.EARLY_CHECKIN,
                    description=f"Erken giris ({early_check_in_hours} saat)",
                    unit_price=fee.amount,
                )

        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{reservation.confirmation_number}: {room.number} numarali odaya giris yapildi.",
            entity_type="Stay",
            entity_id=stay.id,
            after={
                "room": room.number,
                "key_cards": stay.key_card_count,
                "early_hours": early_check_in_hours,
            },
        )
        log.info(
            "check_in",
            confirmation=reservation.confirmation_number,
            room=room.number,
        )
        return stay

    def _post_room_charges(self, folio_id: int, row: ReservationRoom) -> None:
        """Konaklama ucretini folyoya isler.

        Ucret **gece basina ayri satir** olarak islenir. Nedeni: erken cikis
        durumunda kalan geceleri tek tek iptal edebilmek ve misafire gun gun
        dokum gosterebilmektir. Tek kalemde islenirse kismi iade karmasiklasir.
        """
        nights = row.nights
        if nights <= 0:  # pragma: no cover - DateRange bunu zaten engeller
            return

        per_night = (row.total_amount / nights).quantize(Decimal("0.01"))
        # Yuvarlama farki son geceye eklenir; toplam her zaman tutar.
        remainder = row.total_amount - (per_night * nights)

        for index, day in enumerate(row.date_range):
            amount = per_night + (remainder if index == nights - 1 else Decimal("0"))
            self.folios.post_charge(
                folio_id,
                charge_type=ChargeType.ROOM,
                description=f"Oda ucreti - {day.strftime('%d.%m.%Y')}",
                unit_price=amount,
                charge_date=day,
                tax_rate_percent=Decimal("0.00"),  # fiyat vergi dahil hesaplandi
            )

    # ----------------------------------------------------------------- #
    #  Check-out
    # ----------------------------------------------------------------- #
    def check_out(
        self,
        stay_id: int,
        *,
        late_check_out_hours: int = 0,
        key_cards_returned: int | None = None,
        damage_description: str | None = None,
        damage_charge: Decimal = Decimal("0.00"),
        allow_open_balance: bool = False,
    ) -> Stay:
        """Misafir cikisi yapar.

        Bakiye acikken cikis varsayilan olarak **engellenir**; bilincli olarak
        cari hesaba devredilecekse ``allow_open_balance=True`` ve
        ``finance.manage`` yetkisi gerekir.
        """
        self.ctx.require(Perm.FRONTDESK_CHECKOUT)

        stay = self.session.get(Stay, stay_id)
        if stay is None:
            raise NotFoundError("Konaklama", stay_id)
        if not stay.is_in_house:
            raise BusinessRuleError(
                "Bu konaklama icin zaten cikis yapilmis.",
                code="already_checked_out",
            )

        row = self.session.get(ReservationRoom, stay.reservation_room_id)
        reservation = self.session.get(Reservation, row.reservation_id) if row is not None else None
        if row is None or reservation is None:  # pragma: no cover
            raise NotFoundError("Rezervasyon", stay.reservation_room_id)

        assert_transition_allowed(reservation.status, ReservationStatus.CHECKED_OUT)

        folio = self.folios.folio_for_room(row.id)

        # --- Gec cikis ucreti ---
        if late_check_out_hours > 0:
            self.ctx.require(Perm.FRONTDESK_EARLY_LATE)
            fee = calculate_early_late_fee(
                Money.of(row.nightly_rate, reservation.currency),
                hours=late_check_out_hours,
            )
            if not fee.is_zero and folio is not None:
                stay.late_check_out_fee = fee.amount
                stay.is_late_check_out = True
                self.folios.post_charge(
                    folio.id,
                    charge_type=ChargeType.LATE_CHECKOUT,
                    description=f"Gec cikis ({late_check_out_hours} saat)",
                    unit_price=fee.amount,
                )

        # --- Hasar ---
        if damage_charge > 0:
            if not damage_description or not damage_description.strip():
                raise ValidationError(
                    "Hasar ucreti icin aciklama zorunludur.", field="damage_description"
                )
            stay.damage_reported = True
            stay.damage_description = damage_description.strip()
            stay.damage_charge = damage_charge
            if folio is not None:
                self.folios.post_charge(
                    folio.id,
                    charge_type=ChargeType.DAMAGE,
                    description=f"Hasar: {damage_description.strip()}",
                    unit_price=damage_charge,
                )

        # --- Bakiye kontrolu ---
        if folio is not None:
            folio.recalculate()
            self.session.flush()
            if not folio.is_settled and not allow_open_balance:
                raise PaymentError(
                    f"Folyo bakiyesi {Money.of(folio.balance, folio.currency)} acik. "
                    "Cikis oncesi tahsilat yapilmalidir.",
                    code="checkout_open_balance",
                    context={"balance": str(folio.balance), "folio_id": folio.id},
                )
            if not folio.is_settled:
                self.ctx.require(Perm.FINANCE_MANAGE)
            self.folios.close_folio(folio.id, allow_balance=allow_open_balance)

        # --- Konaklamayi kapat ---
        now = utcnow()
        stay.actual_check_out = now
        stay.key_cards_returned = (
            key_cards_returned if key_cards_returned is not None else stay.key_card_count
        )
        stay.checked_out_by_user_id = self.ctx.user_id
        stay.status = (
            StayStatus.EARLY_DEPARTURE if now.date() < row.check_out_date else StayStatus.DEPARTED
        )

        # --- Oda durumu ve temizlik gorevi ---
        room = self.session.get(Room, stay.room_id)
        if room is not None:
            room.occupancy_status = RoomOccupancyStatus.VACANT
            room.housekeeping_status = RoomHousekeepingStatus.DIRTY
            self.session.add(
                HousekeepingTask(
                    property_id=room.property_id,
                    room_id=room.id,
                    task_type=HousekeepingTaskType.CHECKOUT_CLEANING,
                    status=HousekeepingStatus.PENDING,
                    priority=Priority.HIGH,
                    scheduled_date=now.date(),
                    estimated_minutes=45,
                )
            )

        # --- Rezervasyon durumu ---
        # Coklu odali rezervasyonlarda TUM odalar cikis yapmadan rezervasyon
        # kapanmaz; aksi halde otelde kalan misafirler "cikmis" gorunurdu.
        remaining = [
            r
            for r in reservation.rooms
            if not r.is_cancelled and r.id != row.id and (r.stay is None or r.stay.is_in_house)
        ]
        if not remaining:
            reservation.status = ReservationStatus.CHECKED_OUT

        # --- CRM ozeti ---
        guest = reservation.primary_guest
        if guest is not None:
            guest.total_stays += 1
            guest.total_nights += row.nights
            guest.total_revenue = (guest.total_revenue or Decimal("0")) + row.total_amount
            guest.last_stay_date = now.date()
            if guest.first_stay_date is None:
                guest.first_stay_date = now.date()

        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{reservation.confirmation_number}: cikis yapildi "
            f"({room.number if room else '-'}).",
            entity_type="Stay",
            entity_id=stay.id,
            after={
                "status": stay.status.value,
                "late_hours": late_check_out_hours,
                "damage": str(damage_charge),
            },
        )
        log.info("check_out", confirmation=reservation.confirmation_number)
        return stay

    # ----------------------------------------------------------------- #
    #  Gunluk operasyon listeleri
    # ----------------------------------------------------------------- #
    def arrivals_today(self, day: date | None = None) -> list[ReservationRoom]:
        """Bugun giris yapacaklar."""
        self.ctx.require(Perm.RESERVATION_VIEW)
        return self.reservations.arrivals_on(self.ctx.require_property(), day or utcnow().date())

    def departures_today(self, day: date | None = None) -> list[ReservationRoom]:
        """Bugun cikis yapacaklar."""
        self.ctx.require(Perm.RESERVATION_VIEW)
        return self.reservations.departures_on(self.ctx.require_property(), day or utcnow().date())

    def in_house(self, day: date | None = None) -> list[ReservationRoom]:
        """Su anda otelde olanlar."""
        self.ctx.require(Perm.RESERVATION_VIEW)
        return self.reservations.in_house_on(self.ctx.require_property(), day or utcnow().date())


__all__ = ["FrontdeskService"]
