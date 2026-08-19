"""Folyo, ucretler, odemeler, faturalar, vergi oranlari ve kasa hareketleri.

Muhasebe ilkesi
---------------
Folyo satirlari **silinmez**. Yanlis islenen bir ucret ``is_void`` ile
gecersiz kilinir ve gerekcesi yazilir; boylece mali denetim izi korunur.
Bakiye her zaman ``toplam ucret - toplam odeme`` olarak hesaplanir ve
:meth:`Folio.recalculate` ile guncellenir.
"""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    ChargeType,
    Currency,
    FolioStatus,
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
    TransactionDirection,
)
from app.infrastructure.db.base import (
    ActiveMixin,
    Base,
    NotesMixin,
    TimestampMixin,
    enum_column,
)
from app.infrastructure.db.types import TZDateTime

if TYPE_CHECKING:
    from app.infrastructure.db.models.guests import Company, Guest
    from app.infrastructure.db.models.reservations import Reservation, ReservationRoom
    from app.infrastructure.db.models.system import Service


class Folio(Base, TimestampMixin, NotesMixin):
    """Misafir hesabi. Tum ucret ve odemeler buraya islenir."""

    # Not: Bilesik indeks adi, ``status`` sutununun kendi ``index=True``
    # indeksinden farkli olmalidir; isimlendirme kurali ikisine de
    # ``ix_folio_status`` verirdi ve SQLite "index already exists" hatasi verir.
    __table_args__ = (Index("ix_folio_property_status", "property_id", "status"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    folio_number: Mapped[str] = mapped_column(String(24), unique=True, index=True)

    reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservation.id", ondelete="SET NULL"), default=None, index=True
    )
    reservation_room_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservation_room.id", ondelete="SET NULL"),
        default=None,
        doc="Oda bazli ayri folyo tutuluyorsa.",
    )
    guest_id: Mapped[int | None] = mapped_column(
        ForeignKey("guest.id", ondelete="SET NULL"), default=None, index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("company.id", ondelete="SET NULL"),
        default=None,
        doc="Cari hesaba (city ledger) aktarilan folyolar icin.",
    )

    status: Mapped[FolioStatus] = mapped_column(
        enum_column(FolioStatus), default=FolioStatus.OPEN, index=True
    )
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )

    total_charges: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    total_payments: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), doc="Pozitif = misafir borclu."
    )

    opened_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    closed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    reservation: Mapped[Reservation | None] = relationship(back_populates="folios")
    reservation_room: Mapped[ReservationRoom | None] = relationship()
    guest: Mapped[Guest | None] = relationship()
    company: Mapped[Company | None] = relationship()
    charges: Mapped[list[Charge]] = relationship(
        back_populates="folio", cascade="all, delete-orphan"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="folio", cascade="all, delete-orphan"
    )
    invoices: Mapped[list[Invoice]] = relationship(back_populates="folio")

    # ---- Hesaplama ----
    def recalculate(self) -> None:
        """Toplamlari ve bakiyeyi satirlardan yeniden hesaplar.

        Gecersiz kilinmis (``is_void``) satirlar hesaba katilmaz.
        """
        self.total_charges = sum(
            (c.total_amount for c in self.charges if not c.is_void), start=Decimal("0.00")
        )
        self.total_payments = sum(
            (
                p.amount if not p.is_refund else -p.amount
                for p in self.payments
                if p.status in {PaymentStatus.PAID, PaymentStatus.PARTIAL}
            ),
            start=Decimal("0.00"),
        )
        self.balance = self.total_charges - self.total_payments

    @property
    def is_settled(self) -> bool:
        """Hesap kapatilabilir mi (bakiye sifir veya lehte)?"""
        return self.balance <= Decimal("0.00")

    @property
    def is_open(self) -> bool:
        return self.status is FolioStatus.OPEN


class TaxRate(Base, TimestampMixin, ActiveMixin):
    """Vergi orani tanimi.

    Oranlar koda gomulmez; ayarlardan yonetilir. Boylece KDV veya konaklama
    vergisi orani degistiginde yazilim guncellemesi gerekmez.
    """

    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_tax_rate_property_code"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    code: Mapped[str] = mapped_column(String(30), doc="Or. 'KDV10', 'KONAKLAMA2'.")
    name: Mapped[str] = mapped_column(String(120))
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), doc="Yuzde olarak oran.")
    is_included_in_price: Mapped[bool] = mapped_column(
        default=True, doc="True ise fiyat vergi dahildir."
    )
    is_default: Mapped[bool] = mapped_column(default=False)
    applies_to_charge_type: Mapped[ChargeType | None] = mapped_column(
        enum_column(ChargeType), default=None, doc="Bos ise tum ucret turlerine uygulanabilir."
    )
    valid_from: Mapped[date | None] = mapped_column(Date, default=None)
    valid_to: Mapped[date | None] = mapped_column(Date, default=None)


class Charge(Base, TimestampMixin):
    """Folyoya islenen tek bir ucret satiri."""

    __table_args__ = (
        Index("ix_charge_folio_date", "folio_id", "charge_date"),
        Index("ix_charge_type_date", "charge_type", "charge_date"),
    )

    folio_id: Mapped[int] = mapped_column(ForeignKey("folio.id", ondelete="CASCADE"), index=True)
    charge_type: Mapped[ChargeType] = mapped_column(enum_column(ChargeType), index=True)
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("service.id", ondelete="SET NULL"), default=None
    )

    description: Mapped[str] = mapped_column(String(300))
    charge_date: Mapped[date] = mapped_column(Date, index=True)

    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("1.000"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), doc="Vergi haric tutar."
    )
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), doc="Vergi dahil toplam."
    )

    # ---- Gecersiz kilma (silme yerine) ----
    is_void: Mapped[bool] = mapped_column(default=False, index=True)
    void_reason: Mapped[str | None] = mapped_column(String(300), default=None)
    voided_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    voided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    posted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    reference: Mapped[str | None] = mapped_column(
        String(80), default=None, doc="Restoran adisyon no, minibar fisi vb."
    )

    folio: Mapped[Folio] = relationship(back_populates="charges")
    service: Mapped[Service | None] = relationship()

    def compute_totals(self) -> None:
        """Miktar, birim fiyat ve vergi oranindan tutarlari hesaplar.

        ``is_included_in_price`` mantigi cagiran servis tarafindan uygulanir;
        burada ``net_amount`` her zaman vergi haric kabul edilir.
        """
        self.net_amount = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        self.tax_amount = (self.net_amount * self.tax_rate_percent / 100).quantize(Decimal("0.01"))
        self.total_amount = self.net_amount + self.tax_amount

    def void(self, reason: str, user_id: int | None = None) -> None:
        """Ucreti gecersiz kilar (kaydi silmeden)."""
        from app.infrastructure.db.base import utcnow

        self.is_void = True
        self.void_reason = reason
        self.voided_at = utcnow()
        self.voided_by_user_id = user_id


class Payment(Base, TimestampMixin, NotesMixin):
    """Folyoya yapilan odeme veya iade."""

    __table_args__ = (Index("ix_payment_folio_date", "folio_id", "paid_at"),)

    folio_id: Mapped[int] = mapped_column(ForeignKey("folio.id", ondelete="CASCADE"), index=True)
    method: Mapped[PaymentMethod] = mapped_column(enum_column(PaymentMethod), index=True)
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus), default=PaymentStatus.PAID, index=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("1.000000"), doc="Tesis para birimine cevrim kuru."
    )

    paid_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    reference: Mapped[str | None] = mapped_column(
        String(120), default=None, doc="Islem/dekont numarasi. Kart numarasi YAZILMAZ."
    )
    card_last_four: Mapped[str | None] = mapped_column(
        String(4), default=None, doc="Yalnizca son 4 hane; tam kart numarasi asla saklanmaz."
    )

    is_refund: Mapped[bool] = mapped_column(default=False, index=True)
    refund_of_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="SET NULL"), default=None
    )
    is_deposit: Mapped[bool] = mapped_column(default=False)

    received_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    folio: Mapped[Folio] = relationship(back_populates="payments")
    refund_of: Mapped[Payment | None] = relationship(remote_side="Payment.id")


class Invoice(Base, TimestampMixin, NotesMixin):
    """Fatura basligi.

    .. warning::
       e-Fatura / e-Arsiv alanlari (``uuid``, ``ettn``, ``gib_status``)
       yalnizca **veri modeli** olarak hazirdir. Gercek GIB entegrasyonu
       yapilmamistir; bkz. ``docs/ROADMAP.md``. Bu alanlar bir entegratör
       eklendiginde doldurulacaktir.
    """

    folio_id: Mapped[int | None] = mapped_column(
        ForeignKey("folio.id", ondelete="SET NULL"), default=None, index=True
    )
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    status: Mapped[InvoiceStatus] = mapped_column(
        enum_column(InvoiceStatus), default=InvoiceStatus.DRAFT, index=True
    )

    issue_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)

    # ---- Alici bilgileri (fatura aninda dondurulur) ----
    customer_name: Mapped[str] = mapped_column(String(250))
    customer_tax_office: Mapped[str | None] = mapped_column(String(120), default=None)
    customer_tax_number: Mapped[str | None] = mapped_column(String(30), default=None)
    customer_address: Mapped[str | None] = mapped_column(String(400), default=None)
    customer_email: Mapped[str | None] = mapped_column(String(200), default=None)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )

    # ---- e-Fatura alanlari (HENUZ ENTEGRE DEGIL) ----
    einvoice_uuid: Mapped[str | None] = mapped_column(String(64), default=None)
    einvoice_ettn: Mapped[str | None] = mapped_column(String(64), default=None)
    einvoice_status: Mapped[str | None] = mapped_column(
        String(40), default=None, doc="Entegratör tarafindan doldurulur; su an kullanilmiyor."
    )
    einvoice_sent_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    folio: Mapped[Folio | None] = relationship(back_populates="invoices")
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    def recalculate(self) -> None:
        """Toplamlari satirlardan hesaplar."""
        self.subtotal = sum((line.net_amount for line in self.lines), start=Decimal("0.00"))
        self.tax_total = sum((line.tax_amount for line in self.lines), start=Decimal("0.00"))
        self.grand_total = self.subtotal + self.tax_total


class InvoiceLine(Base, TimestampMixin):
    """Fatura kalemi."""

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("1.000"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    sort_order: Mapped[int] = mapped_column(default=0)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class CashRegisterEntry(Base, TimestampMixin, NotesMixin):
    """Kasa hareketi - gunluk kapanis ve nakit akisi raporlarinin kaynagi."""

    __table_args__ = (Index("ix_cash_entry_date", "property_id", "entry_date"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    direction: Mapped[TransactionDirection] = mapped_column(
        enum_column(TransactionDirection), index=True
    )
    method: Mapped[PaymentMethod] = mapped_column(
        enum_column(PaymentMethod), default=PaymentMethod.CASH
    )

    category: Mapped[str] = mapped_column(
        String(80), doc="Or. 'Oda Geliri', 'Personel Avansi', 'Temizlik Malzemesi'."
    )
    description: Mapped[str] = mapped_column(String(300))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )

    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="SET NULL"), default=None
    )
    folio_id: Mapped[int | None] = mapped_column(
        ForeignKey("folio.id", ondelete="SET NULL"), default=None
    )
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    is_day_close: Mapped[bool] = mapped_column(default=False, doc="Gun sonu kapanis kaydi mi?")

    @property
    def signed_amount(self) -> Decimal:
        """Gelir icin pozitif, gider icin negatif tutar."""
        return self.amount if self.direction is TransactionDirection.INCOME else -self.amount


__all__ = [
    "CashRegisterEntry",
    "Charge",
    "Folio",
    "Invoice",
    "InvoiceLine",
    "Payment",
    "TaxRate",
]
