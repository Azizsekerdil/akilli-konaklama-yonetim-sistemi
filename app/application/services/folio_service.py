"""Folyo (misafir hesabi) servisi: ucret isleme, gecersiz kilma, tahsilat.

Muhasebe ilkesi
---------------
Folyo satirlari **silinmez**. Yanlis islenen bir ucret ``void`` edilir ve
gerekcesi kaydedilir; denetim izi korunur. Bakiye her islemden sonra
:meth:`~app.infrastructure.db.models.billing.Folio.recalculate` ile
satirlardan yeniden hesaplanir - elle guncellenmez, boylece "toplam tutmuyor"
durumu olusamaz.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.application.context import ServiceContext
from app.core.exceptions import (
    BusinessRuleError,
    NotFoundError,
    PaymentError,
    ValidationError,
)
from app.core.log import get_logger
from app.domain.enums import (
    AuditAction,
    ChargeType,
    Currency,
    FolioStatus,
    PaymentMethod,
    PaymentStatus,
    TransactionDirection,
)
from app.domain.value_objects import Money
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.billing import (
    CashRegisterEntry,
    Charge,
    Folio,
    Payment,
    TaxRate,
)
from app.infrastructure.db.models.reservations import Reservation, ReservationRoom
from app.infrastructure.db.repositories import FolioRepository
from app.security.permissions import Perm

log = get_logger(__name__)


class FolioService:
    """Misafir hesabi islemleri."""

    def __init__(self, context: ServiceContext) -> None:
        self.ctx = context
        self.session = context.session
        self.folios = FolioRepository(context.session)

    # ----------------------------------------------------------------- #
    #  Folyo yasam dongusu
    # ----------------------------------------------------------------- #
    def open_folio(
        self,
        *,
        reservation_id: int | None = None,
        reservation_room_id: int | None = None,
        guest_id: int | None = None,
        company_id: int | None = None,
    ) -> Folio:
        """Yeni bir folyo acar.

        Ayni rezervasyon icin acik folyo varsa yenisi olusturulmaz; mevcut
        olan dondurulur. Boylece cift hesap acilmasi engellenir.
        """
        self.ctx.require(Perm.FOLIO_VIEW)
        property_id = self.ctx.require_property()

        if reservation_id is not None:
            existing = self.folios.open_folio_for_reservation(reservation_id)
            if existing is not None:
                return existing

        if reservation_id is None and guest_id is None and company_id is None:
            raise ValidationError(
                "Folyo icin rezervasyon, misafir veya firma belirtilmelidir.",
                field="reservation_id",
            )

        currency = Currency.TRY
        if reservation_id is not None:
            reservation = self.session.get(Reservation, reservation_id)
            if reservation is None:
                raise NotFoundError("Rezervasyon", reservation_id)
            currency = reservation.currency
            guest_id = guest_id or reservation.primary_guest_id

        folio = Folio(
            property_id=property_id,
            folio_number=self.folios.next_folio_number(property_id),
            reservation_id=reservation_id,
            reservation_room_id=reservation_room_id,
            guest_id=guest_id,
            company_id=company_id,
            status=FolioStatus.OPEN,
            currency=currency,
            opened_at=utcnow(),
        )
        self.session.add(folio)
        self.session.flush()

        self.ctx.audit(
            AuditAction.CREATE,
            f"{folio.folio_number} numarali folyo acildi.",
            entity_type="Folio",
            entity_id=folio.id,
        )
        return folio

    def close_folio(self, folio_id: int, *, allow_balance: bool = False) -> Folio:
        """Folyoyu kapatir.

        Bakiye sifirlanmadan kapatmak yalnizca ``allow_balance=True`` ile ve
        ``finance.manage`` yetkisiyle mumkundur (or. cari hesaba devir).
        """
        self.ctx.require(Perm.FOLIO_VIEW)
        folio = self._get(folio_id)
        folio.recalculate()

        if not folio.is_settled and not allow_balance:
            raise PaymentError(
                f"Folyo bakiyesi {Money.of(folio.balance, folio.currency)} olarak acik. "
                "Once tahsilat yapin.",
                code="folio_has_balance",
                context={"balance": str(folio.balance)},
            )

        if not folio.is_settled:
            self.ctx.require(Perm.FINANCE_MANAGE)

        folio.status = FolioStatus.CLOSED
        folio.closed_at = utcnow()
        folio.closed_by_user_id = self.ctx.user_id
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{folio.folio_number} kapatildi (bakiye: {folio.balance}).",
            entity_type="Folio",
            entity_id=folio.id,
        )
        return folio

    # ----------------------------------------------------------------- #
    #  Ucretler
    # ----------------------------------------------------------------- #
    def post_charge(
        self,
        folio_id: int,
        *,
        charge_type: ChargeType,
        description: str,
        unit_price: Decimal,
        quantity: Decimal = Decimal("1"),
        charge_date: date | None = None,
        tax_rate_percent: Decimal | None = None,
        service_id: int | None = None,
        reference: str | None = None,
    ) -> Charge:
        """Folyoya ucret isler."""
        self.ctx.require(Perm.FOLIO_POST_CHARGE)
        folio = self._get(folio_id)

        if folio.status is not FolioStatus.OPEN:
            raise BusinessRuleError(
                "Kapali bir folyoya ucret islenemez.",
                code="folio_closed",
            )
        if quantity <= 0:
            raise ValidationError("Miktar sifirdan buyuk olmalidir.", field="quantity")
        if unit_price < 0:
            raise ValidationError(
                "Birim fiyat negatif olamaz. Indirim icin 'discount' ucret turunu kullanin.",
                field="unit_price",
            )

        if tax_rate_percent is None:
            tax_rate_percent = self._default_tax_rate(folio.property_id, charge_type)

        charge = Charge(
            folio_id=folio.id,
            charge_type=charge_type,
            service_id=service_id,
            description=description.strip(),
            charge_date=charge_date or utcnow().date(),
            quantity=quantity,
            unit_price=unit_price,
            tax_rate_percent=tax_rate_percent,
            reference=reference,
            posted_by_user_id=self.ctx.user_id,
        )
        charge.compute_totals()

        # ONEMLI: ``session.add(charge)`` yerine iliskiye ekliyoruz.
        # ``folio.charges`` koleksiyonu daha once yuklendiyse, session.add ile
        # eklenen satir o koleksiyona YANSIMAZ ve ardindan cagrilan
        # ``folio.recalculate()`` bayat listeyi okuyarak bakiyeyi EKSIK
        # hesaplar. Iliskiye eklemek hem koleksiyonu gunceller hem de
        # cascade ile kaydi oturuma ekler.
        folio.charges.append(charge)
        self.session.flush()

        folio.recalculate()
        self.session.flush()

        self.ctx.audit(
            AuditAction.CREATE,
            f"{folio.folio_number}: {description} - {charge.total_amount}",
            entity_type="Charge",
            entity_id=charge.id,
            after={
                "charge_type": charge_type.value,
                "total": str(charge.total_amount),
            },
        )
        return charge

    def void_charge(self, charge_id: int, *, reason: str) -> Charge:
        """Ucreti gecersiz kilar (silmez).

        Yuksek etkili bir islemdir; ``folio.void_charge`` yetkisi gerekir.
        """
        self.ctx.require(Perm.FOLIO_VOID_CHARGE)

        charge = self.session.get(Charge, charge_id)
        if charge is None:
            raise NotFoundError("Ucret kaydi", charge_id)
        if charge.is_void:
            raise BusinessRuleError("Bu ucret zaten gecersiz kilinmis.", code="already_void")
        if not reason or not reason.strip():
            raise ValidationError("Gecersiz kilma gerekcesi zorunludur.", field="reason")

        before = {"total": str(charge.total_amount), "is_void": False}
        charge.void(reason.strip(), self.ctx.user_id)
        self.session.flush()

        folio = self._get(charge.folio_id)
        folio.recalculate()
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"Ucret gecersiz kilindi: {charge.description} - Gerekce: {reason.strip()}",
            entity_type="Charge",
            entity_id=charge.id,
            before=before,
            after={"is_void": True, "reason": reason.strip()},
        )
        log.warning(
            "ucret_gecersiz_kilindi",
            charge_id=charge_id,
            amount=str(charge.total_amount),
            reason=reason.strip(),
        )
        return charge

    def apply_discount(
        self,
        folio_id: int,
        *,
        amount: Decimal,
        description: str = "Indirim",
    ) -> Charge:
        """Folyoya indirim satiri ekler (negatif tutar)."""
        self.ctx.require(Perm.FOLIO_DISCOUNT)
        folio = self._get(folio_id)

        if amount <= 0:
            raise ValidationError("Indirim tutari pozitif olmalidir.", field="amount")
        folio.recalculate()
        if amount > folio.total_charges:
            raise BusinessRuleError(
                "Indirim, toplam ucretten buyuk olamaz.",
                code="discount_exceeds_total",
            )

        charge = Charge(
            folio_id=folio.id,
            charge_type=ChargeType.DISCOUNT,
            description=description.strip(),
            charge_date=utcnow().date(),
            quantity=Decimal("1"),
            unit_price=-amount,
            posted_by_user_id=self.ctx.user_id,
        )
        charge.compute_totals()
        folio.charges.append(charge)  # bkz. post_charge - bayat koleksiyon tuzagi
        self.session.flush()

        folio.recalculate()
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{folio.folio_number}: {amount} tutarinda indirim uygulandi.",
            entity_type="Charge",
            entity_id=charge.id,
        )
        return charge

    # ----------------------------------------------------------------- #
    #  Odemeler
    # ----------------------------------------------------------------- #
    def add_payment(
        self,
        folio_id: int,
        *,
        amount: Decimal,
        method: PaymentMethod,
        reference: str | None = None,
        card_last_four: str | None = None,
        is_deposit: bool = False,
        allow_overpayment: bool = False,
    ) -> Payment:
        """Folyoya odeme kaydeder.

        Fazla odeme varsayilan olarak **reddedilir**: genellikle bir yazim
        hatasidir (or. 1500 yerine 15000). Bilincli fazla odeme icin
        ``allow_overpayment=True`` gecilmelidir.
        """
        self.ctx.require(Perm.PAYMENT_RECEIVE)
        folio = self._get(folio_id)

        if amount <= 0:
            raise ValidationError("Odeme tutari sifirdan buyuk olmalidir.", field="amount")

        folio.recalculate()
        if not allow_overpayment and amount > folio.balance and folio.balance > 0:
            raise PaymentError(
                f"Odeme tutari ({amount}) kalan bakiyeden ({folio.balance}) buyuk. "
                "Fazla odeme icin onay gerekir.",
                code="overpayment",
                context={"balance": str(folio.balance), "amount": str(amount)},
            )
        if amount > folio.balance and folio.balance <= 0 and not allow_overpayment:
            raise PaymentError(
                "Folyoda odenecek bakiye bulunmuyor.",
                code="no_balance",
            )

        # Kart numarasi ASLA saklanmaz; yalnizca son 4 hane.
        if card_last_four is not None:
            card_last_four = card_last_four.strip()[-4:]
            if not card_last_four.isdigit():
                raise ValidationError(
                    "Kart son 4 hanesi yalnizca rakam olmalidir.", field="card_last_four"
                )

        payment = Payment(
            folio_id=folio.id,
            method=method,
            status=PaymentStatus.PAID,
            amount=amount,
            currency=folio.currency,
            paid_at=utcnow(),
            reference=reference,
            card_last_four=card_last_four,
            is_deposit=is_deposit,
            received_by_user_id=self.ctx.user_id,
        )
        folio.payments.append(payment)  # bkz. post_charge - bayat koleksiyon tuzagi
        self.session.flush()

        folio.recalculate()

        # Kasa hareketi (gunluk kapanis raporunun kaynagi)
        self.session.add(
            CashRegisterEntry(
                property_id=folio.property_id,
                entry_date=utcnow().date(),
                direction=TransactionDirection.INCOME,
                method=method,
                category="Konaklama Geliri",
                description=f"{folio.folio_number} tahsilat",
                amount=amount,
                currency=folio.currency,
                payment_id=payment.id,
                folio_id=folio.id,
                recorded_by_user_id=self.ctx.user_id,
            )
        )

        # Rezervasyon ozeti
        if folio.reservation_id:
            reservation = self.session.get(Reservation, folio.reservation_id)
            if reservation is not None:
                reservation.paid_amount = (reservation.paid_amount or Decimal("0")) + amount
                if is_deposit:
                    reservation.deposit_paid = True

        self.session.flush()

        self.ctx.audit(
            AuditAction.CREATE,
            f"{folio.folio_number}: {amount} {folio.currency.value} tahsil edildi "
            f"({method.label}).",
            entity_type="Payment",
            entity_id=payment.id,
            after={"amount": str(amount), "method": method.value},
        )
        return payment

    def refund(
        self,
        payment_id: int,
        *,
        amount: Decimal | None = None,
        reason: str,
    ) -> Payment:
        """Odemeyi kismen veya tamamen iade eder."""
        self.ctx.require(Perm.PAYMENT_REFUND)

        original = self.session.get(Payment, payment_id)
        if original is None:
            raise NotFoundError("Odeme", payment_id)
        if original.is_refund:
            raise BusinessRuleError("Iade kaydi tekrar iade edilemez.", code="already_refund")
        if not reason or not reason.strip():
            raise ValidationError("Iade gerekcesi zorunludur.", field="reason")

        refund_amount = amount if amount is not None else original.amount
        if refund_amount <= 0:
            raise ValidationError("Iade tutari pozitif olmalidir.", field="amount")
        if refund_amount > original.amount:
            raise PaymentError(
                "Iade tutari, orijinal odemeden buyuk olamaz.",
                code="refund_exceeds_payment",
            )

        folio = self._get(original.folio_id)

        refund_payment = Payment(
            folio_id=folio.id,
            method=original.method,
            status=PaymentStatus.REFUNDED,
            amount=refund_amount,
            currency=original.currency,
            paid_at=utcnow(),
            reference=f"Iade: {reason.strip()}",
            is_refund=True,
            refund_of_payment_id=original.id,
            received_by_user_id=self.ctx.user_id,
        )
        folio.payments.append(refund_payment)  # bkz. post_charge
        self.session.flush()

        folio.recalculate()

        self.session.add(
            CashRegisterEntry(
                property_id=folio.property_id,
                entry_date=utcnow().date(),
                direction=TransactionDirection.EXPENSE,
                method=original.method,
                category="Iade",
                description=f"{folio.folio_number} iade: {reason.strip()}",
                amount=refund_amount,
                currency=folio.currency,
                payment_id=refund_payment.id,
                folio_id=folio.id,
                recorded_by_user_id=self.ctx.user_id,
            )
        )
        self.session.flush()

        self.ctx.audit(
            AuditAction.CREATE,
            f"{folio.folio_number}: {refund_amount} iade edildi. Gerekce: {reason.strip()}",
            entity_type="Payment",
            entity_id=refund_payment.id,
        )
        log.warning("iade_yapildi", folio=folio.folio_number, amount=str(refund_amount))
        return refund_payment

    # ----------------------------------------------------------------- #
    #  Yardimcilar
    # ----------------------------------------------------------------- #
    def _get(self, folio_id: int) -> Folio:
        folio = self.session.get(Folio, folio_id)
        if folio is None:
            raise NotFoundError("Folyo", folio_id)
        return folio

    def _default_tax_rate(self, property_id: int, charge_type: ChargeType) -> Decimal:
        """Ucret turune uygun varsayilan vergi oranini bulur.

        Once o ucret turune ozel tanimli oran aranir; yoksa varsayilan oran
        kullanilir. Hicbiri yoksa 0 doner (vergi tanimlanmamis kurulum).
        """
        specific = self.session.scalars(
            select(TaxRate).where(
                TaxRate.property_id == property_id,
                TaxRate.is_active.is_(True),
                TaxRate.applies_to_charge_type == charge_type,
            )
        ).first()
        if specific is not None:
            return specific.rate_percent

        default = self.session.scalars(
            select(TaxRate).where(
                TaxRate.property_id == property_id,
                TaxRate.is_active.is_(True),
                TaxRate.is_default.is_(True),
            )
        ).first()
        return default.rate_percent if default is not None else Decimal("0.00")

    def folio_for_room(self, reservation_room_id: int) -> Folio | None:
        """Bir oda satirina bagli acik folyoyu dondurur."""
        row = self.session.get(ReservationRoom, reservation_room_id)
        if row is None:
            return None
        return self.folios.open_folio_for_reservation(row.reservation_id)


__all__ = ["FolioService"]
