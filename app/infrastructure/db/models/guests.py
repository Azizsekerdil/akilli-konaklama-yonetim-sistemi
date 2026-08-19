"""Misafir CRM: misafir, kurumsal musteri, acente, tercihler, notlar, KVKK izinleri.

Kisisel veri notu
-----------------
Kimlik/pasaport numarasi :class:`~app.infrastructure.db.types.EncryptedString`
ile **sifrelenerek** saklanir. Esitlik aramasi yapabilmek icin ayrica
deterministik bir "kor indeks" (:func:`~app.infrastructure.db.types.blind_index`)
sutunu tutulur. Bu alanlar loglara duz metin yazilmaz
(bkz. :mod:`app.core.log`).
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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    ConsentType,
    Currency,
    GuestTitle,
    IdentityDocumentType,
    VIPLevel,
)
from app.infrastructure.db.base import (
    ActiveMixin,
    Base,
    NotesMixin,
    SoftDeleteMixin,
    TimestampMixin,
    enum_column,
)
from app.infrastructure.db.types import EncryptedString, TZDateTime, blind_index

if TYPE_CHECKING:
    from app.infrastructure.db.models.reservations import Reservation, ReservationGuest
    from app.infrastructure.db.models.security import User


class Company(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Kurumsal musteri (sozlesmeli sirket)."""

    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    tax_office: Mapped[str | None] = mapped_column(String(120), default=None)
    tax_number: Mapped[str | None] = mapped_column(String(30), default=None, index=True)

    contact_person: Mapped[str | None] = mapped_column(String(150), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    address_line: Mapped[str | None] = mapped_column(String(300), default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    country: Mapped[str] = mapped_column(String(100), default="Turkiye")

    # ---- Ticari kosullar ----
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), doc="Cari hesap limiti."
    )
    payment_terms_days: Mapped[int] = mapped_column(default=0, doc="Vade (gun).")
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )

    guests: Mapped[list[Guest]] = relationship(back_populates="company")
    reservations: Mapped[list[Reservation]] = relationship(back_populates="company")


class Agency(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Seyahat acentesi / tur operatoru."""

    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    tax_office: Mapped[str | None] = mapped_column(String(120), default=None)
    tax_number: Mapped[str | None] = mapped_column(String(30), default=None)

    contact_person: Mapped[str | None] = mapped_column(String(150), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)

    commission_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("10.00"), doc="Acente komisyon orani (%)."
    )
    contract_start: Mapped[date | None] = mapped_column(Date, default=None)
    contract_end: Mapped[date | None] = mapped_column(Date, default=None)

    guests: Mapped[list[Guest]] = relationship(back_populates="agency")
    reservations: Mapped[list[Reservation]] = relationship(back_populates="agency")


class Guest(Base, TimestampMixin, SoftDeleteMixin, NotesMixin):
    """Misafir profili.

    Misafirler tesisten bagimsizdir: ayni misafir zincirin farkli tesislerinde
    konaklayabilir ve CRM gecmisi butunlesik kalir.
    """

    __table_args__ = (
        Index("ix_guest_name", "last_name", "first_name"),
        Index("ix_guest_contact", "email", "phone"),
        UniqueConstraint("identity_index", name="uq_guest_identity_index"),
    )

    # ---- Kimlik bilgileri ----
    title: Mapped[GuestTitle] = mapped_column(enum_column(GuestTitle), default=GuestTitle.NONE)
    first_name: Mapped[str] = mapped_column(String(80), index=True)
    last_name: Mapped[str] = mapped_column(String(80), index=True)
    birth_date: Mapped[date | None] = mapped_column(Date, default=None)
    nationality: Mapped[str] = mapped_column(String(100), default="Turkiye")
    preferred_language: Mapped[str] = mapped_column(String(5), default="tr")

    identity_document_type: Mapped[IdentityDocumentType] = mapped_column(
        enum_column(IdentityDocumentType), default=IdentityDocumentType.NATIONAL_ID
    )
    identity_number: Mapped[str | None] = mapped_column(
        EncryptedString(512),
        default=None,
        doc="SIFRELI saklanir. Duz metin olarak loglanmaz veya disa aktarilmaz.",
    )
    identity_index: Mapped[str | None] = mapped_column(
        String(44),
        default=None,
        index=True,
        doc="Kimlik numarasinin kor indeksi - esitlik aramasi icin (HMAC-SHA256).",
    )
    identity_expiry: Mapped[date | None] = mapped_column(Date, default=None)
    identity_issuing_country: Mapped[str | None] = mapped_column(String(100), default=None)

    # ---- Iletisim ----
    email: Mapped[str | None] = mapped_column(String(200), default=None, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    mobile: Mapped[str | None] = mapped_column(String(40), default=None)
    address_line: Mapped[str | None] = mapped_column(String(300), default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(20), default=None)
    country: Mapped[str] = mapped_column(String(100), default="Turkiye")

    # ---- CRM ----
    vip_level: Mapped[VIPLevel] = mapped_column(
        enum_column(VIPLevel), default=VIPLevel.NONE, index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("company.id", ondelete="SET NULL"), default=None, index=True
    )
    agency_id: Mapped[int | None] = mapped_column(
        ForeignKey("agency.id", ondelete="SET NULL"), default=None, index=True
    )

    is_blacklisted: Mapped[bool] = mapped_column(
        default=False, index=True, doc="Kara listede - yeni rezervasyon uyarisi verir."
    )
    blacklist_reason: Mapped[str | None] = mapped_column(String(400), default=None)
    blacklisted_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    # ---- Denormalize CRM ozetleri (rapor performansi icin) ----
    total_stays: Mapped[int] = mapped_column(default=0)
    total_nights: Mapped[int] = mapped_column(default=0)
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    first_stay_date: Mapped[date | None] = mapped_column(Date, default=None)
    last_stay_date: Mapped[date | None] = mapped_column(Date, default=None)
    no_show_count: Mapped[int] = mapped_column(default=0)
    cancellation_count: Mapped[int] = mapped_column(default=0)

    # ---- Iliskiler ----
    company: Mapped[Company | None] = relationship(back_populates="guests")
    agency: Mapped[Agency | None] = relationship(back_populates="guests")
    preferences: Mapped[list[GuestPreference]] = relationship(
        back_populates="guest", cascade="all, delete-orphan"
    )
    guest_notes: Mapped[list[GuestNote]] = relationship(
        back_populates="guest", cascade="all, delete-orphan"
    )
    consents: Mapped[list[ConsentRecord]] = relationship(
        back_populates="guest", cascade="all, delete-orphan"
    )
    reservations: Mapped[list[Reservation]] = relationship(
        back_populates="primary_guest", foreign_keys="Reservation.primary_guest_id"
    )
    reservation_guests: Mapped[list[ReservationGuest]] = relationship(back_populates="guest")

    # ---- Yardimcilar ----
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self) -> str:
        prefix = self.title.label if self.title is not GuestTitle.NONE else ""
        return f"{prefix} {self.full_name}".strip()

    @property
    def is_vip(self) -> bool:
        return self.vip_level is not VIPLevel.NONE

    @property
    def age(self) -> int | None:
        """Dogum tarihinden yasi hesaplar."""
        if self.birth_date is None:
            return None
        # Yas, misafirin bulundugu yerin takvim gunune gore hesaplanir;
        # burada yerel tarih dogru olandir (UTC degil).
        today = date.today()  # noqa: DTZ011
        return (
            today.year
            - self.birth_date.year
            - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        )

    def set_identity(self, number: str | None) -> None:
        """Kimlik numarasini sifreli alana ve kor indekse birlikte yazar.

        Ikisini elle ayri ayri yazmak, indeksin sessizce eskimesine yol acar;
        bu yuzden tek bir yardimci uzerinden guncellenir.
        """
        cleaned = number.strip() if number else None
        self.identity_number = cleaned
        self.identity_index = blind_index(cleaned)

    @property
    def has_active_alerts(self) -> bool:
        """Uyari niteliginde bir not veya kara liste kaydi var mi?"""
        return self.is_blacklisted or any(note.is_alert for note in self.guest_notes)


class GuestPreference(Base, TimestampMixin):
    """Misafir tercihi (yastik tipi, kat, sigara, alerjen...)."""

    __table_args__ = (UniqueConstraint("guest_id", "category", "value", name="uq_guest_pref"),)

    guest_id: Mapped[int] = mapped_column(ForeignKey("guest.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(60), doc="Or. 'oda', 'yemek', 'yatak'.")
    value: Mapped[str] = mapped_column(String(200))
    is_critical: Mapped[bool] = mapped_column(
        default=False, doc="Alerji gibi kritik tercihler ozellikle vurgulanir."
    )

    guest: Mapped[Guest] = relationship(back_populates="preferences")


class GuestNote(Base, TimestampMixin):
    """Misafir hakkinda personel notu."""

    guest_id: Mapped[int] = mapped_column(ForeignKey("guest.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    content: Mapped[str] = mapped_column(Text)
    is_alert: Mapped[bool] = mapped_column(
        default=False, index=True, doc="True ise rezervasyon ekraninda uyari olarak gosterilir."
    )

    guest: Mapped[Guest] = relationship(back_populates="guest_notes")
    author: Mapped[User | None] = relationship()


class ConsentRecord(Base, TimestampMixin):
    """KVKK kapsaminda alinan acik riza kaydi.

    Her izin turu icin ayri satir tutulur ve **geri alma** da kaydedilir;
    boylece "hangi tarihte hangi izin verildi/geri alindi" sorusu denetimde
    yanitlanabilir.
    """

    __table_args__ = (Index("ix_consent_guest_type", "guest_id", "consent_type"),)

    guest_id: Mapped[int] = mapped_column(ForeignKey("guest.id", ondelete="CASCADE"), index=True)
    consent_type: Mapped[ConsentType] = mapped_column(enum_column(ConsentType))
    is_granted: Mapped[bool] = mapped_column(default=False)
    granted_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    source: Mapped[str | None] = mapped_column(
        String(100), default=None, doc="Or. 'check-in formu', 'web sitesi'."
    )
    document_reference: Mapped[str | None] = mapped_column(
        String(200), default=None, doc="Imzali aydinlatma metni/onam belgesi referansi."
    )
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    guest: Mapped[Guest] = relationship(back_populates="consents")

    @property
    def is_currently_valid(self) -> bool:
        """Izin su anda gecerli mi?"""
        return self.is_granted and self.revoked_at is None


__all__ = ["Agency", "Company", "ConsentRecord", "Guest", "GuestNote", "GuestPreference"]
