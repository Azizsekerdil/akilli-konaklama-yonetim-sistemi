"""Rezervasyon use-case servisi.

Bu servis, sistemin en kritik is akisini yonetir. Tasarim ilkesi:
**kurallar burada tekrarlanmaz.** Musaitlik ve fiyat hesabi
:mod:`app.domain.rules` icindeki saf fonksiyonlara birakilir; servis
yalnizca veriyi toplar, kurali cagirir ve sonucu kalici hale getirir.

Cakisma kontrolu iki asamalidir:

1. **Yazmadan once** (:func:`~app.domain.rules.availability.check_availability`)
   - kullaniciya anlamli bir hata mesaji gostermek icin.
2. **Yazarken** - ayni anda iki kullanici ayni odayi ayni tarihe satmaya
   calisirsa ilk asama ikisini de geciririr. Bu yuzden kayit eklendikten
   sonra ``flush`` ile veritabanina yazilir ve kontrol **tekrarlanir**;
   cakisma varsa islem geri alinir. Buna "iyimser kilitleme" denir ve
   masaustu bir PMS icin uygun maliyetli cozumdur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.application.context import ServiceContext
from app.core.exceptions import (
    BusinessRuleError,
    InvalidStateTransitionError,
    NotFoundError,
    OverlappingReservationError,
    ValidationError,
)
from app.core.log import get_logger
from app.domain.enums import (
    AuditAction,
    Currency,
    MealPlan,
    ReservationSource,
    ReservationStatus,
)
from app.domain.rules.availability import (
    Booking,
    available_room_ids,
    check_availability,
)
from app.domain.rules.pricing import (
    PriceBreakdown,
    RateRule,
    calculate_cancellation_fee,
    calculate_stay_price,
)
from app.domain.rules.reservation_state import assert_transition_allowed
from app.domain.value_objects import DateRange, Money
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.guests import Guest
from app.infrastructure.db.models.reservations import Reservation, ReservationRoom
from app.infrastructure.db.models.rooms import RatePlan, RatePlanRate, Room, RoomType
from app.infrastructure.db.repositories import (
    ReservationRepository,
    RoomRepository,
)
from app.security.permissions import Perm

log = get_logger(__name__)


@dataclass(slots=True)
class RoomRequest:
    """Rezervasyona eklenecek tek bir oda satiri talebi."""

    room_type_id: int
    check_in: date
    check_out: date
    adults: int = 2
    children: int = 0
    infants: int = 0
    room_id: int | None = None
    """Belirli bir oda isteniyorsa. ``None`` ise oda tipi bazli rezervasyon."""

    rate_plan_id: int | None = None
    meal_plan: MealPlan = MealPlan.BED_BREAKFAST
    discount_percent: Decimal = Decimal("0.00")

    @property
    def date_range(self) -> DateRange:
        return DateRange(self.check_in, self.check_out)


@dataclass(slots=True)
class AvailabilityResult:
    """Bir oda tipi icin musaitlik sonucu."""

    room_type_id: int
    room_type_name: str
    available_room_ids: list[int] = field(default_factory=list)
    price: PriceBreakdown | None = None

    @property
    def available_count(self) -> int:
        return len(self.available_room_ids)

    @property
    def is_available(self) -> bool:
        return bool(self.available_room_ids)


class ReservationService:
    """Rezervasyon olusturma, degistirme ve iptal islemleri."""

    def __init__(self, context: ServiceContext) -> None:
        self.ctx = context
        self.session = context.session
        self.reservations = ReservationRepository(context.session)
        self.rooms = RoomRepository(context.session)

    # ----------------------------------------------------------------- #
    #  Musaitlik ve fiyat
    # ----------------------------------------------------------------- #
    def search_availability(
        self,
        date_range: DateRange,
        *,
        adults: int = 2,
        children: int = 0,
        room_type_id: int | None = None,
        rate_plan_id: int | None = None,
    ) -> list[AvailabilityResult]:
        """Verilen tarihlerde musait oda tiplerini ve fiyatlarini dondurur."""
        self.ctx.require(Perm.RESERVATION_VIEW)
        property_id = self.ctx.require_property()

        bookings = self.reservations.bookings_for_range(property_id, date_range)
        blocks = self.rooms.blocks_for_range(property_id, date_range)

        stmt = select(RoomType).where(
            RoomType.property_id == property_id,
            RoomType.is_active.is_(True),
        )
        if room_type_id is not None:
            stmt = stmt.where(RoomType.id == room_type_id)

        results: list[AvailabilityResult] = []
        total_guests = adults + children

        for room_type in self.session.scalars(stmt):
            # Kapasitesi yetmeyen oda tipini hic degerlendirme.
            if total_guests > room_type.max_occupancy:
                continue

            candidates = [
                room.id
                for room in self.rooms.list_rooms(
                    property_id, room_type_id=room_type.id, only_sellable=True
                )
            ]
            free = available_room_ids(
                date_range,
                candidate_room_ids=candidates,
                existing_bookings=bookings,
                blocks=blocks,
            )

            price = self.quote_price(
                date_range,
                room_type=room_type,
                adults=adults,
                children=children,
                rate_plan_id=rate_plan_id,
            )
            results.append(
                AvailabilityResult(
                    room_type_id=room_type.id,
                    room_type_name=room_type.name,
                    available_room_ids=free,
                    price=price,
                )
            )

        return results

    def quote_price(
        self,
        date_range: DateRange,
        *,
        room_type: RoomType,
        adults: int = 2,
        children: int = 0,
        rate_plan_id: int | None = None,
        discount_percent: Decimal = Decimal("0.00"),
    ) -> PriceBreakdown:
        """Konaklama fiyatini hesaplar (gece gece).

        Fiyat plani belirtilmezse tesisin o tarihte gecerli, en yuksek
        oncelikli aktif plani secilir.
        """
        plan = self._resolve_rate_plan(room_type.property_id, rate_plan_id, date_range.start)
        rules = self._rate_rules(plan, room_type.id) if plan else []

        tax_rate, tax_included = self._room_tax(room_type.property_id)

        return calculate_stay_price(
            date_range,
            rules=rules,
            base_rate=room_type.base_rate,
            currency=plan.currency if plan else Currency.TRY,
            adults=adults,
            children=children,
            base_occupancy=room_type.base_occupancy,
            extra_adult_rate=room_type.extra_adult_rate,
            extra_child_rate=room_type.extra_child_rate,
            discount_percent=discount_percent,
            tax_rate_percent=tax_rate,
            tax_included_in_rate=tax_included,
        )

    def _resolve_rate_plan(
        self, property_id: int, rate_plan_id: int | None, day: date
    ) -> RatePlan | None:
        if rate_plan_id is not None:
            plan = self.session.get(RatePlan, rate_plan_id)
            if plan is None:
                raise NotFoundError("Fiyat plani", rate_plan_id)
            return plan

        candidates = self.session.scalars(
            select(RatePlan)
            .where(RatePlan.property_id == property_id, RatePlan.is_active.is_(True))
            .order_by(RatePlan.priority.desc())
        ).all()
        for plan in candidates:
            if plan.is_valid_on(day):
                return plan
        return None

    def _rate_rules(self, plan: RatePlan, room_type_id: int) -> list[RateRule]:
        """Fiyat plani satirlarini domain kurallarina cevirir."""
        rows = self.session.scalars(
            select(RatePlanRate).where(
                RatePlanRate.rate_plan_id == plan.id,
                RatePlanRate.room_type_id == room_type_id,
            )
        ).all()
        return [
            RateRule(
                amount=row.amount,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                weekday_mask=row.weekday_mask,
                min_nights=row.min_nights,
                max_nights=row.max_nights,
                priority=plan.priority,
                season_name=row.season_name,
                rate_plan_code=plan.code,
            )
            for row in rows
        ]

    def _room_tax(self, property_id: int) -> tuple[Decimal, bool]:
        """Oda ucretine uygulanacak varsayilan vergi oranini bulur."""
        from app.domain.enums import ChargeType
        from app.infrastructure.db.models.billing import TaxRate

        rate = self.session.scalars(
            select(TaxRate)
            .where(
                TaxRate.property_id == property_id,
                TaxRate.is_active.is_(True),
            )
            .order_by(TaxRate.is_default.desc())
        ).first()

        if rate is None:
            return Decimal("0.00"), True
        if rate.applies_to_charge_type not in (None, ChargeType.ROOM):
            return Decimal("0.00"), True
        return rate.rate_percent, rate.is_included_in_price

    # ----------------------------------------------------------------- #
    #  Olusturma
    # ----------------------------------------------------------------- #
    def create_reservation(
        self,
        *,
        guest_id: int,
        room_requests: list[RoomRequest],
        source: ReservationSource = ReservationSource.DIRECT,
        status: ReservationStatus = ReservationStatus.CONFIRMED,
        company_id: int | None = None,
        agency_id: int | None = None,
        special_requests: str | None = None,
        group_name: str | None = None,
        deposit_amount: Decimal = Decimal("0.00"),
        allow_blacklisted: bool = False,
    ) -> Reservation:
        """Yeni rezervasyon olusturur.

        Raises
        ------
        ValidationError
            Oda talebi yoksa veya tarihler gecersizse.
        BusinessRuleError
            Misafir kara listedeyse (``allow_blacklisted=False`` iken).
        OverlappingReservationError
            Herhangi bir oda satirinda tarih cakismasi varsa.
        """
        self.ctx.require(Perm.RESERVATION_CREATE)
        property_id = self.ctx.require_property()

        if not room_requests:
            raise ValidationError("En az bir oda secilmelidir.", field="room_requests")

        guest = self.session.get(Guest, guest_id)
        if guest is None:
            raise NotFoundError("Misafir", guest_id)

        if guest.is_blacklisted and not allow_blacklisted:
            raise BusinessRuleError(
                f"{guest.full_name} kara listede. Rezervasyon icin yetkili onayi gerekir.",
                detail=guest.blacklist_reason,
                code="guest_blacklisted",
                context={"guest_id": guest_id, "reason": guest.blacklist_reason},
            )

        # Kara liste asimi ayri bir yetki gerektirir.
        if guest.is_blacklisted and allow_blacklisted:
            self.ctx.require(Perm.RESERVATION_OVERRIDE)

        # Tek tek dogrulama, pencere hesabindan ONCE yapilmalidir: gecersiz
        # bir tarih araligi (or. check_in == check_out) dogrudan DateRange'e
        # verilirse ham bir ValueError firlar ve kullaniciya teknik bir mesaj
        # gosterilir. Once dogrulayip anlasilir bir ValidationError uretiyoruz.
        for request in room_requests:
            self._validate_request(request)

        # --- Musaitlik kontrolu (yazmadan once) ---
        window = DateRange(
            min(r.check_in for r in room_requests),
            max(r.check_out for r in room_requests),
        )
        bookings = self.reservations.bookings_for_range(property_id, window)
        blocks = self.rooms.blocks_for_range(property_id, window)

        # Ayni istek icindeki satirlarin birbiriyle cakismasini da yakalamak
        # icin dogrulanan satirlari calisma listesine ekliyoruz.
        working: list[Booking] = list(bookings)

        for request in room_requests:
            if request.room_id is not None:
                check_availability(
                    request.date_range,
                    room_id=request.room_id,
                    existing_bookings=working,
                    blocks=blocks,
                )
                working.append(Booking(request.room_id, request.date_range))

        # --- Kayitlari olustur ---
        confirmation = self.reservations.next_confirmation_number(property_id)
        currency = Currency.TRY

        reservation = Reservation(
            property_id=property_id,
            confirmation_number=confirmation,
            status=ReservationStatus.DRAFT,
            source=source,
            primary_guest_id=guest_id,
            company_id=company_id,
            agency_id=agency_id,
            check_in_date=window.start,
            check_out_date=window.end,
            currency=currency,
            special_requests=special_requests,
            group_name=group_name,
            deposit_amount=deposit_amount,
            created_by_user_id=self.ctx.user_id,
        )
        self.session.add(reservation)
        self.session.flush()

        for request in room_requests:
            room_type = self.session.get(RoomType, request.room_type_id)
            if room_type is None:
                raise NotFoundError("Oda tipi", request.room_type_id)

            self._validate_occupancy(room_type, request)

            price = self.quote_price(
                request.date_range,
                room_type=room_type,
                adults=request.adults,
                children=request.children,
                rate_plan_id=request.rate_plan_id,
                discount_percent=request.discount_percent,
            )

            self.session.add(
                ReservationRoom(
                    reservation_id=reservation.id,
                    room_type_id=request.room_type_id,
                    room_id=request.room_id,
                    rate_plan_id=request.rate_plan_id,
                    check_in_date=request.check_in,
                    check_out_date=request.check_out,
                    adults=request.adults,
                    children=request.children,
                    infants=request.infants,
                    meal_plan=request.meal_plan,
                    nightly_rate=price.average_nightly_rate.amount,
                    total_amount=price.total.amount,
                    discount_percent=request.discount_percent,
                )
            )

        self.session.flush()
        self.session.refresh(reservation)
        reservation.recalculate_summary()

        # --- Durumu hedefe tasi (durum makinesi uzerinden) ---
        if status is not ReservationStatus.DRAFT:
            assert_transition_allowed(ReservationStatus.DRAFT, status)
            reservation.status = status

        # --- Yazma sonrasi cakisma dogrulamasi (yaris kosulu korumasi) ---
        self._assert_no_conflicts_after_write(reservation)

        self.ctx.audit(
            AuditAction.CREATE,
            f"{confirmation} numarali rezervasyon olusturuldu "
            f"({guest.full_name}, {window.format()}).",
            entity_type="Reservation",
            entity_id=reservation.id,
            after={
                "confirmation_number": confirmation,
                "status": reservation.status.value,
                "total_amount": str(reservation.total_amount),
                "rooms": len(room_requests),
            },
        )
        log.info(
            "rezervasyon_olusturuldu",
            confirmation=confirmation,
            guest_id=guest_id,
            nights=window.nights,
            rooms=len(room_requests),
        )
        return reservation

    def _validate_request(self, request: RoomRequest) -> None:
        """Tek bir oda talebinin tutarliligini denetler."""
        if request.check_out <= request.check_in:
            raise ValidationError(
                "Cikis tarihi giris tarihinden sonra olmalidir.",
                field="check_out",
            )
        if request.adults < 1:
            raise ValidationError("En az bir yetiskin olmalidir.", field="adults")
        if request.children < 0 or request.infants < 0:
            raise ValidationError("Kisi sayilari negatif olamaz.", field="children")
        if request.discount_percent < 0 or request.discount_percent > 100:
            raise ValidationError(
                "Indirim orani 0-100 arasinda olmalidir.", field="discount_percent"
            )

    def _validate_occupancy(self, room_type: RoomType, request: RoomRequest) -> None:
        """Kisi sayisinin oda tipi kapasitesine uydugunu denetler."""
        guests = request.adults + request.children
        if guests > room_type.max_occupancy:
            raise BusinessRuleError(
                f"{room_type.name} en fazla {room_type.max_occupancy} kisiliktir "
                f"(talep: {guests}).",
                code="occupancy_exceeded",
                context={"room_type_id": room_type.id, "requested": guests},
            )
        if request.adults > room_type.max_adults:
            raise BusinessRuleError(
                f"{room_type.name} en fazla {room_type.max_adults} yetiskin alabilir.",
                code="adult_limit_exceeded",
            )

    def _assert_no_conflicts_after_write(self, reservation: Reservation) -> None:
        """Yazma sonrasi cakisma dogrulamasi.

        Iki kullanici ayni anda ayni odayi ayni tarihe satmaya calisirsa,
        yazmadan onceki kontrol ikisini de geciririr (her ikisi de digerinin
        heniz yazilmamis kaydini goremez). Bu ikinci kontrol, kayit
        veritabanina yazildiktan sonra calisir ve cakisma varsa islemi
        reddeder.
        """
        for row in reservation.rooms:
            if row.room_id is None or row.is_cancelled:
                continue
            others = [
                booking
                for booking in self.reservations.bookings_for_room(row.room_id, row.date_range)
                if booking.reservation_room_id != row.id
            ]
            if others:
                self.session.rollback()
                raise OverlappingReservationError(
                    "Bu oda islem sirasinda baska bir rezervasyona atandi. "
                    "Lutfen musaitligi yeniden kontrol edin.",
                    detail=f"room_id={row.room_id}, {row.date_range.format()}",
                    context={"room_id": row.room_id},
                )

    # ----------------------------------------------------------------- #
    #  Degistirme
    # ----------------------------------------------------------------- #
    def assign_room(self, reservation_room_id: int, room_id: int) -> ReservationRoom:
        """Oda tipi bazli bir satira fiziksel oda atar."""
        self.ctx.require(Perm.RESERVATION_EDIT)

        row = self.session.get(ReservationRoom, reservation_room_id)
        if row is None:
            raise NotFoundError("Rezervasyon oda satiri", reservation_room_id)

        room = self.session.get(Room, room_id)
        if room is None:
            raise NotFoundError("Oda", room_id)
        if room.room_type_id != row.room_type_id:
            raise BusinessRuleError(
                "Atanan oda, rezervasyondaki oda tipiyle uyusmuyor.",
                code="room_type_mismatch",
            )

        property_id = self.ctx.require_property()
        bookings = self.reservations.bookings_for_range(property_id, row.date_range)
        blocks = self.rooms.blocks_for_range(property_id, row.date_range)

        check_availability(
            row.date_range,
            room_id=room_id,
            existing_bookings=bookings,
            blocks=blocks,
            exclude_reservation_room_id=row.id,
        )

        previous = row.room_id
        row.room_id = room_id
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"Oda atandi: {room.number}",
            entity_type="ReservationRoom",
            entity_id=row.id,
            before={"room_id": previous},
            after={"room_id": room_id},
        )
        return row

    def change_dates(
        self,
        reservation_room_id: int,
        *,
        check_in: date,
        check_out: date,
    ) -> ReservationRoom:
        """Bir oda satirinin tarihlerini degistirir ve fiyati yeniden hesaplar."""
        self.ctx.require(Perm.RESERVATION_EDIT)

        row = self.session.get(ReservationRoom, reservation_room_id)
        if row is None:
            raise NotFoundError("Rezervasyon oda satiri", reservation_room_id)

        new_range = DateRange(check_in, check_out)
        property_id = self.ctx.require_property()

        if row.room_id is not None:
            bookings = self.reservations.bookings_for_range(property_id, new_range)
            blocks = self.rooms.blocks_for_range(property_id, new_range)
            check_availability(
                new_range,
                room_id=row.room_id,
                existing_bookings=bookings,
                blocks=blocks,
                exclude_reservation_room_id=row.id,  # kendisiyle cakismasin
            )

        before = {"check_in": str(row.check_in_date), "check_out": str(row.check_out_date)}

        room_type = self.session.get(RoomType, row.room_type_id)
        if room_type is None:  # pragma: no cover - FK garantisi
            raise NotFoundError("Oda tipi", row.room_type_id)

        price = self.quote_price(
            new_range,
            room_type=room_type,
            adults=row.adults,
            children=row.children,
            rate_plan_id=row.rate_plan_id,
            discount_percent=row.discount_percent,
        )

        row.check_in_date = check_in
        row.check_out_date = check_out
        row.nightly_rate = price.average_nightly_rate.amount
        row.total_amount = price.total.amount
        self.session.flush()

        reservation = self.session.get(Reservation, row.reservation_id)
        if reservation is not None:
            reservation.recalculate_summary()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"Tarihler degistirildi: {new_range.format()}",
            entity_type="ReservationRoom",
            entity_id=row.id,
            before=before,
            after={"check_in": str(check_in), "check_out": str(check_out)},
        )
        return row

    # ----------------------------------------------------------------- #
    #  Durum gecisleri
    # ----------------------------------------------------------------- #
    def confirm(self, reservation_id: int) -> Reservation:
        """Taslak/opsiyonlu rezervasyonu onaylar."""
        self.ctx.require(Perm.RESERVATION_EDIT)
        reservation = self._get(reservation_id)
        assert_transition_allowed(reservation.status, ReservationStatus.CONFIRMED)

        previous = reservation.status
        reservation.status = ReservationStatus.CONFIRMED
        self.session.flush()
        self._assert_no_conflicts_after_write(reservation)

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{reservation.confirmation_number} onaylandi.",
            entity_type="Reservation",
            entity_id=reservation.id,
            before={"status": previous.value},
            after={"status": reservation.status.value},
        )
        return reservation

    def cancel(
        self,
        reservation_id: int,
        *,
        reason: str,
        apply_fee: bool = True,
    ) -> tuple[Reservation, Money]:
        """Rezervasyonu iptal eder ve varsa iptal ucretini hesaplar.

        Returns
        -------
        tuple[Reservation, Money]
            Guncellenen rezervasyon ve hesaplanan iptal ucreti.
        """
        self.ctx.require(Perm.RESERVATION_CANCEL)
        reservation = self._get(reservation_id)

        # Durum makinesi "ayni duruma gecis" i islemsiz kabul eder (or. onayli
        # bir rezervasyonu tekrar onaylamak zararsizdir). Ancak iptal boyle
        # degildir: ikinci kez iptal, ikinci bir iptal ucreti hesaplar ve
        # misafirin iptal sayacini haksiz yere artirirdi.
        if reservation.status is ReservationStatus.CANCELLED:
            raise InvalidStateTransitionError(
                "Bu rezervasyon zaten iptal edilmis.",
                detail=f"reservation_id={reservation_id}",
                context={"current": reservation.status.value},
            )
        assert_transition_allowed(reservation.status, ReservationStatus.CANCELLED)

        if not reason or not reason.strip():
            raise ValidationError("Iptal gerekcesi zorunludur.", field="reason")

        fee = self._cancellation_fee(reservation) if apply_fee else Money.zero(reservation.currency)

        previous = reservation.status
        reservation.status = ReservationStatus.CANCELLED
        reservation.cancelled_at = utcnow()
        reservation.cancellation_reason = reason.strip()
        reservation.cancelled_by_user_id = self.ctx.user_id

        # Odalar serbest kalir.
        for row in reservation.rooms:
            row.is_cancelled = True

        # CRM ozeti
        guest = self.session.get(Guest, reservation.primary_guest_id)
        if guest is not None:
            guest.cancellation_count += 1

        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{reservation.confirmation_number} iptal edildi. Gerekce: {reason.strip()}",
            entity_type="Reservation",
            entity_id=reservation.id,
            before={"status": previous.value},
            after={"status": "cancelled", "fee": str(fee.amount)},
        )
        log.info(
            "rezervasyon_iptal",
            confirmation=reservation.confirmation_number,
            fee=str(fee.amount),
        )
        return reservation, fee

    def mark_no_show(self, reservation_id: int) -> tuple[Reservation, Money]:
        """Misafir gelmedi olarak isaretler ve ceza ucretini hesaplar."""
        self.ctx.require(Perm.RESERVATION_CANCEL)
        reservation = self._get(reservation_id)

        # Iptal ile ayni gerekce: tekrar isaretleme sayaci sisirir.
        if reservation.status is ReservationStatus.NO_SHOW:
            raise InvalidStateTransitionError(
                "Bu rezervasyon zaten 'gelmedi' olarak isaretlenmis.",
                detail=f"reservation_id={reservation_id}",
            )
        assert_transition_allowed(reservation.status, ReservationStatus.NO_SHOW)

        plan = self._first_rate_plan(reservation)
        fee = calculate_cancellation_fee(
            Money.of(reservation.total_amount, reservation.currency),
            hours_before_arrival=-1,
            is_no_show=True,
            no_show_fee_percent=plan.no_show_fee_percent if plan else Decimal("100.00"),
        )

        previous = reservation.status
        reservation.status = ReservationStatus.NO_SHOW
        reservation.no_show_marked_at = utcnow()
        for row in reservation.rooms:
            row.is_cancelled = True

        guest = self.session.get(Guest, reservation.primary_guest_id)
        if guest is not None:
            guest.no_show_count += 1

        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{reservation.confirmation_number} 'gelmedi' olarak isaretlendi.",
            entity_type="Reservation",
            entity_id=reservation.id,
            before={"status": previous.value},
            after={"status": "no_show", "fee": str(fee.amount)},
        )
        return reservation, fee

    # ----------------------------------------------------------------- #
    #  Yardimcilar
    # ----------------------------------------------------------------- #
    def _get(self, reservation_id: int) -> Reservation:
        reservation = self.session.get(Reservation, reservation_id)
        if reservation is None or reservation.is_deleted:
            raise NotFoundError("Rezervasyon", reservation_id)
        return reservation

    def _first_rate_plan(self, reservation: Reservation) -> RatePlan | None:
        for row in reservation.rooms:
            if row.rate_plan_id:
                return self.session.get(RatePlan, row.rate_plan_id)
        return None

    def _cancellation_fee(self, reservation: Reservation) -> Money:
        """Iptal ucretini fiyat planinin politikasina gore hesaplar."""
        plan = self._first_rate_plan(reservation)
        arrival = reservation.check_in_date
        hours_before = (date.fromordinal(arrival.toordinal()) - utcnow().date()).days * 24

        return calculate_cancellation_fee(
            Money.of(reservation.total_amount, reservation.currency),
            hours_before_arrival=hours_before,
            is_refundable=plan.is_refundable if plan else True,
            free_cancellation_hours=plan.free_cancellation_hours if plan else 24,
            cancellation_fee_percent=plan.cancellation_fee_percent if plan else Decimal("0"),
        )


__all__ = ["AvailabilityResult", "ReservationService", "RoomRequest"]
