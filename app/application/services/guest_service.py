"""Misafir (CRM) servisi: arama, profil, kimlik, kara liste ve KVKK izinleri.

Kisisel veri notu
-----------------
Bu servis, uygulamanin **en hassas** verisiyle calisir. Iki kural her metotta
gecerlidir:

1. **Kimlik numarasi asla serbestce donmez.** :meth:`GuestService.get_profile`
   her zaman maskelenmis deger uretir. Acik deger yalnizca
   :meth:`GuestService.reveal_identity` ile ve
   :data:`~app.security.permissions.Perm.GUEST_VIEW_IDENTITY` izniyle alinir;
   her acik goruntuleme denetim gunlugune ``AuditAction.READ`` olarak yazilir.
2. **ORM nesnesi disari cikmaz.** Arayuz katmani, servis baglami kapandiktan
   sonra iliskilere eristiginde ``DetachedInstanceError`` alirdi. Bu yuzden tum
   metotlar bu moduldeki dondurulmus (frozen) veri siniflarini dondurur.

KVKK izinleri
-------------
Izin kayitlari **guncellenmez, eklenir**. Bir izni geri almak, mevcut satiri
degistirmek degil, ``is_granted=False`` ve ``revoked_at`` dolu YENI bir satir
yazmaktir. Boylece "hangi tarihte izin verildi, hangi tarihte geri alindi"
sorusu denetimde eksiksiz yanitlanabilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select

from app.application.context import ServiceContext
from app.core.exceptions import ConflictError, ValidationError
from app.core.log import get_logger
from app.domain.enums import (
    AuditAction,
    ConsentType,
    GuestTitle,
    IdentityDocumentType,
    LabeledEnum,
    VIPLevel,
)
from app.domain.value_objects import Money
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.guests import ConsentRecord, Guest, GuestNote
from app.infrastructure.db.models.reservations import (
    Reservation,
    ReservationGuest,
    ReservationRoom,
    Stay,
)
from app.infrastructure.db.models.rooms import Room
from app.infrastructure.db.models.security import User
from app.infrastructure.db.repositories import GuestRepository
from app.infrastructure.db.types import mask_identity
from app.security.permissions import Perm

log = get_logger(__name__)

#: ``update`` icinde "bu alan verilmedi" anlamina gelen isaret.
#: ``None`` kullanilamaz cunku ``None`` gecerli bir deger ("alani bosalt")
#: anlamina gelir.
_MISSING: Any = object()


# ==========================================================================
#  Duz veri yapilari - servis baglami kapandiktan sonra da guvenle okunur
# ==========================================================================
@dataclass(frozen=True, slots=True)
class GuestSummary:
    """Misafir listesi satiri."""

    guest_id: int
    full_name: str
    display_name: str
    phone: str | None
    email: str | None
    vip_level: str
    """Turkce etiket, or. ``Altin``."""

    vip_level_value: str
    is_vip: bool
    total_stays: int
    last_stay_date: date | None
    is_blacklisted: bool
    blacklist_reason: str | None
    has_alert: bool
    """Kara liste veya uyari notu var mi?"""


@dataclass(frozen=True, slots=True)
class StayHistoryEntry:
    """Konaklama gecmisi satiri (planlanan + gerceklesen)."""

    check_in: date
    check_out: date
    room_number: str
    nights: int
    amount: Money
    status: str
    is_cancelled: bool


@dataclass(frozen=True, slots=True)
class PreferenceEntry:
    """Misafir tercihi."""

    category: str
    value: str
    is_critical: bool


@dataclass(frozen=True, slots=True)
class NoteEntry:
    """Personel notu."""

    note_id: int
    content: str
    is_alert: bool
    author: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConsentEntry:
    """KVKK izin kaydi (tek satir - verme veya geri alma)."""

    consent_type: str
    """Turkce etiket."""

    consent_value: str
    """Enum degeri - arayuzde gruplama icin."""

    is_granted: bool
    is_valid: bool
    recorded_at: datetime
    granted_at: datetime | None
    revoked_at: datetime | None
    source: str | None


@dataclass(frozen=True, slots=True)
class IdentityView:
    """Kimlik numarasinin gosterime hazir hali."""

    value: str
    is_revealed: bool
    """``True`` ise deger ACIK gosterildi ve denetime yazildi."""

    document_type: str


@dataclass(slots=True)
class GuestProfile:
    """Misafir profilinin tamami - arayuzun tek cagriyla ihtiyac duydugu her sey."""

    summary: GuestSummary

    title: str = ""
    title_value: str = GuestTitle.NONE.value
    first_name: str = ""
    last_name: str = ""
    birth_date: date | None = None
    age: int | None = None
    nationality: str = ""
    preferred_language: str = "tr"

    identity_document_type: str = ""
    identity_document_value: str = IdentityDocumentType.NATIONAL_ID.value
    identity_masked: str = "-"
    has_identity: bool = False

    mobile: str | None = None
    address_line: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str = ""

    company_name: str | None = None
    company_id: int | None = None
    agency_name: str | None = None
    agency_id: int | None = None

    total_nights: int = 0
    total_revenue: Money = field(default_factory=Money.zero)
    first_stay_date: date | None = None
    no_show_count: int = 0
    cancellation_count: int = 0

    stays: list[StayHistoryEntry] = field(default_factory=list)
    preferences: list[PreferenceEntry] = field(default_factory=list)
    notes: list[NoteEntry] = field(default_factory=list)
    consents: list[ConsentEntry] = field(default_factory=list)


# ==========================================================================
#  Servis
# ==========================================================================
class GuestService:
    """Misafir kayitlari uzerindeki tum kullanim senaryolari."""

    #: ``update`` ile degistirilebilecek alanlar. Beyaz liste bilinclidir:
    #: ``is_blacklisted`` veya ``total_revenue`` gibi alanlarin sirf bir sozluk
    #: anahtari gecirilerek degistirilmesini engeller.
    EDITABLE_FIELDS: frozenset[str] = frozenset(
        {
            "title",
            "first_name",
            "last_name",
            "birth_date",
            "nationality",
            "preferred_language",
            "identity_document_type",
            "identity_number",
            "email",
            "phone",
            "mobile",
            "address_line",
            "city",
            "postal_code",
            "country",
            "vip_level",
            "company_id",
            "agency_id",
            "notes",
        }
    )

    #: Bos birakildiginda ``None`` yazilacak metin alanlari. Bos dizge ile
    #: ``None`` arasindaki farki korumak, "e-postasi var ama bos" gibi anlamsiz
    #: kayitlar uretirdi ve mukerrer tespitini bozardi.
    _NULLABLE_TEXT: frozenset[str] = frozenset(
        {
            "email",
            "phone",
            "mobile",
            "address_line",
            "city",
            "postal_code",
            "notes",
        }
    )

    def __init__(self, context: ServiceContext) -> None:
        self.ctx = context
        self.session = context.session
        self.guests = GuestRepository(context.session)

    # ----------------------------------------------------------------- #
    #  Arama
    # ----------------------------------------------------------------- #
    def search(self, query: str = "", *, limit: int = 100) -> list[GuestSummary]:
        """Ad, e-posta ve telefon uzerinde arama yapar.

        Bos sorgu **bos liste dondurmez**: en son konaklayan misafirler
        listelenir. Arayuz acildiginda bos bir tablo gormek, kullanicinin
        "kayit yok mu?" diye dusunmesine yol acardi.

        Telefon aramasi iki asamalidir. Once ham metin denenir; sonuc yoksa
        sorgudaki rakamlar cikarilip aralarina joker konur ("555000" ->
        ``%5%5%5%0%0%0%``). Boylece kullanici numarayi bosluksuz yazsa da
        "+90 555 000 00 01" kaydi bulunur.
        """
        self.ctx.require(Perm.GUEST_VIEW)

        cleaned = (query or "").strip()
        if not cleaned:
            return [_summarize(guest) for guest in self._recent_guests(limit)]

        guests = self.guests.search(cleaned, limit=limit)
        if not guests:
            guests = self._search_by_digits(cleaned, limit=limit)
        return [_summarize(guest) for guest in guests]

    def _recent_guests(self, limit: int) -> list[Guest]:
        """En son konaklayanlar once; hic konaklamamis olanlar sona."""
        stmt = (
            select(Guest)
            .where(Guest.is_deleted.is_(False))
            # NULLS LAST yerine bir bayrak sutunu ile siraliyoruz: eski SQLite
            # surumleri NULLS LAST sozdizimini tanimaz.
            .order_by(
                Guest.last_stay_date.is_(None),
                Guest.last_stay_date.desc(),
                Guest.id.desc(),
            )
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def _search_by_digits(self, query: str, *, limit: int) -> list[Guest]:
        """Bicimden bagimsiz telefon aramasi."""
        digits = "".join(char for char in query if char.isdigit())
        if len(digits) < 4:
            return []
        pattern = "%" + "%".join(digits) + "%"
        stmt = (
            select(Guest)
            .where(
                Guest.is_deleted.is_(False),
                or_(Guest.phone.like(pattern), Guest.mobile.like(pattern)),
            )
            .order_by(Guest.last_name, Guest.first_name, Guest.id)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    # ----------------------------------------------------------------- #
    #  Profil
    # ----------------------------------------------------------------- #
    def get_profile(self, guest_id: int) -> GuestProfile:
        """Misafirin tam profilini duz veri yapisi olarak dondurur.

        Kimlik numarasi burada **her zaman maskelidir**; acik deger icin
        :meth:`reveal_identity` kullanilir.
        """
        self.ctx.require(Perm.GUEST_VIEW)
        guest = self.guests.get_or_404(guest_id)

        return GuestProfile(
            summary=_summarize(guest),
            title=guest.title.label,
            title_value=guest.title.value,
            first_name=guest.first_name,
            last_name=guest.last_name,
            birth_date=guest.birth_date,
            age=guest.age,
            nationality=guest.nationality,
            preferred_language=guest.preferred_language,
            identity_document_type=guest.identity_document_type.label,
            identity_document_value=guest.identity_document_type.value,
            identity_masked=mask_identity(guest.identity_number),
            has_identity=bool(guest.identity_number),
            mobile=guest.mobile,
            address_line=guest.address_line,
            city=guest.city,
            postal_code=guest.postal_code,
            country=guest.country,
            company_name=guest.company.name if guest.company is not None else None,
            company_id=guest.company_id,
            agency_name=guest.agency.name if guest.agency is not None else None,
            agency_id=guest.agency_id,
            total_nights=guest.total_nights,
            total_revenue=Money.of(guest.total_revenue or 0),
            first_stay_date=guest.first_stay_date,
            no_show_count=guest.no_show_count,
            cancellation_count=guest.cancellation_count,
            stays=self._stay_history(guest_id),
            preferences=[
                PreferenceEntry(
                    category=preference.category,
                    value=preference.value,
                    is_critical=preference.is_critical,
                )
                for preference in sorted(
                    guest.preferences, key=lambda p: (not p.is_critical, p.category)
                )
            ],
            notes=self._notes(guest_id),
            consents=self._consents(guest_id),
        )

    def _stay_history(self, guest_id: int) -> list[StayHistoryEntry]:
        """Misafirin asil misafir VEYA refakatci oldugu tum oda satirlari.

        Refakatciler de dahil edilir: ayni odada kalan es veya is arkadasi,
        kendi profilinde konaklama gecmisi gormelidir.
        """
        companion_rows = select(ReservationGuest.reservation_room_id).where(
            ReservationGuest.guest_id == guest_id
        )
        stmt = (
            select(ReservationRoom, Reservation, Stay, Room)
            .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
            .outerjoin(Stay, Stay.reservation_room_id == ReservationRoom.id)
            .outerjoin(Room, ReservationRoom.room_id == Room.id)
            .where(
                Reservation.is_deleted.is_(False),
                or_(
                    Reservation.primary_guest_id == guest_id,
                    ReservationRoom.id.in_(companion_rows),
                ),
            )
            .order_by(ReservationRoom.check_in_date.desc(), ReservationRoom.id.desc())
        )

        entries: list[StayHistoryEntry] = []
        for row, reservation, stay, room in self.session.execute(stmt).all():
            if row.is_cancelled:
                status = "Iptal"
            elif stay is None:
                status = reservation.status.label
            elif stay.is_in_house:
                status = "Otelde"
            else:
                status = stay.status.label

            entries.append(
                StayHistoryEntry(
                    check_in=row.check_in_date,
                    check_out=row.check_out_date,
                    room_number=room.number if room is not None else "-",
                    nights=row.nights,
                    amount=Money.of(row.total_amount, reservation.currency),
                    status=status,
                    is_cancelled=row.is_cancelled,
                )
            )
        return entries

    def _notes(self, guest_id: int) -> list[NoteEntry]:
        stmt = (
            select(GuestNote, User)
            .outerjoin(User, GuestNote.author_user_id == User.id)
            # Uyari notlari once: personelin ilk gordugu satir kritik olan
            # olmalidir.
            .where(GuestNote.guest_id == guest_id)
            .order_by(GuestNote.is_alert.desc(), GuestNote.created_at.desc())
        )
        return [
            NoteEntry(
                note_id=note.id,
                content=note.content,
                is_alert=note.is_alert,
                author=author.full_name if author is not None else "Sistem",
                created_at=note.created_at,
            )
            for note, author in self.session.execute(stmt).all()
        ]

    def _consents(self, guest_id: int) -> list[ConsentEntry]:
        stmt = (
            select(ConsentRecord)
            .where(ConsentRecord.guest_id == guest_id)
            .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
        )
        return [
            ConsentEntry(
                consent_type=record.consent_type.label,
                consent_value=record.consent_type.value,
                is_granted=record.is_granted,
                is_valid=record.is_currently_valid,
                recorded_at=record.created_at,
                granted_at=record.granted_at,
                revoked_at=record.revoked_at,
                source=record.source,
            )
            for record in self.session.scalars(stmt).all()
        ]

    # ----------------------------------------------------------------- #
    #  Olusturma / duzenleme
    # ----------------------------------------------------------------- #
    def create(
        self,
        *,
        first_name: str,
        last_name: str,
        title: GuestTitle = GuestTitle.NONE,
        birth_date: date | None = None,
        nationality: str = "Turkiye",
        preferred_language: str = "tr",
        identity_document_type: IdentityDocumentType = IdentityDocumentType.NATIONAL_ID,
        identity_number: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        mobile: str | None = None,
        address_line: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        country: str = "Turkiye",
        vip_level: VIPLevel = VIPLevel.NONE,
        company_id: int | None = None,
        agency_id: int | None = None,
        notes: str | None = None,
    ) -> GuestSummary:
        """Yeni misafir kaydi olusturur.

        Mukerrer kayit **engellenmez**; ayni isimde iki farkli kisi olabilir.
        Uyari gostermek arayuzun isidir (bkz. :meth:`find_possible_duplicates`).
        Kimlik numarasi ise benzersizdir ve cakisirsa hata verilir.
        """
        self.ctx.require(Perm.GUEST_CREATE)

        first = _require_text(first_name, "Ad", "first_name")
        last = _require_text(last_name, "Soyad", "last_name")

        guest = Guest(
            title=title,
            first_name=first,
            last_name=last,
            birth_date=birth_date,
            nationality=_clean(nationality) or "Turkiye",
            preferred_language=_clean(preferred_language) or "tr",
            identity_document_type=identity_document_type,
            email=_clean(email),
            phone=_clean(phone),
            mobile=_clean(mobile),
            address_line=_clean(address_line),
            city=_clean(city),
            postal_code=_clean(postal_code),
            country=_clean(country) or "Turkiye",
            vip_level=vip_level,
            company_id=company_id,
            agency_id=agency_id,
            notes=_clean(notes),
        )

        cleaned_identity = _clean(identity_number)
        if cleaned_identity:
            self._assert_identity_free(cleaned_identity, exclude_guest_id=None)
            guest.set_identity(cleaned_identity)

        self.guests.add(guest)

        # Denetim kaydina kimlik numarasi YAZILMAZ; yalnizca varligi belirtilir.
        self.ctx.audit(
            AuditAction.CREATE,
            f"Misafir kaydi olusturuldu: {guest.full_name}",
            entity_type="Guest",
            entity_id=guest.id,
            after={"vip_level": guest.vip_level.value, "kimlik_var": bool(cleaned_identity)},
        )
        log.info("misafir_olusturuldu", guest_id=guest.id)
        return _summarize(guest)

    def update(self, guest_id: int, **changes: Any) -> GuestSummary:
        """Misafir kaydini gunceller.

        Yalnizca :attr:`EDITABLE_FIELDS` icindeki alanlar kabul edilir;
        taninmayan bir alan sessizce yok sayilmaz, hata uretir. Sessiz yok
        sayma, arayuzdeki bir yazim hatasinin "kaydettim ama degismedi"
        seklinde fark edilmemesine yol acardi.
        """
        self.ctx.require(Perm.GUEST_EDIT)
        guest = self.guests.get_or_404(guest_id)

        unknown = set(changes) - self.EDITABLE_FIELDS
        if unknown:
            raise ValidationError(
                "Bu alan misafir kaydinda guncellenemez.",
                detail=f"Bilinmeyen alanlar: {sorted(unknown)}",
                field=sorted(unknown)[0],
            )

        identity = changes.pop("identity_number", _MISSING)

        before = {
            "full_name": guest.full_name,
            "email": guest.email,
            "vip_level": guest.vip_level.value,
        }

        for key, value in changes.items():
            if key in {"first_name", "last_name"}:
                label = "Ad" if key == "first_name" else "Soyad"
                setattr(guest, key, _require_text(value, label, key))
            # LabeledEnum ``str`` turevidir; once o kontrol edilmezse enum
            # degerleri metin gibi islenir ve sutuna duz dizge yazilirdi.
            elif isinstance(value, LabeledEnum) or not isinstance(value, str):
                setattr(guest, key, value)
            else:
                cleaned = _clean(value)
                setattr(guest, key, cleaned if key in self._NULLABLE_TEXT else (cleaned or ""))

        if identity is not _MISSING:
            cleaned_identity = _clean(identity)
            if cleaned_identity:
                self._assert_identity_free(cleaned_identity, exclude_guest_id=guest.id)
            guest.set_identity(cleaned_identity)

        self.session.flush()
        self.ctx.audit(
            AuditAction.UPDATE,
            f"Misafir kaydi guncellendi: {guest.full_name}",
            entity_type="Guest",
            entity_id=guest.id,
            before=before,
            after={
                "full_name": guest.full_name,
                "email": guest.email,
                "vip_level": guest.vip_level.value,
                "kimlik_degisti": identity is not _MISSING,
            },
        )
        log.info("misafir_guncellendi", guest_id=guest.id)
        return _summarize(guest)

    def set_identity(self, guest_id: int, number: str | None) -> None:
        """Kimlik numarasini yazar.

        :meth:`Guest.set_identity` kullanilir; sifreli alan ile kor indeks
        birlikte guncellenir. Numara denetim kaydina **yazilmaz**.
        """
        self.ctx.require(Perm.GUEST_EDIT)
        guest = self.guests.get_or_404(guest_id)

        cleaned = _clean(number)
        if cleaned:
            self._assert_identity_free(cleaned, exclude_guest_id=guest.id)

        guest.set_identity(cleaned)
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{guest.full_name} kaydinin kimlik bilgisi guncellendi.",
            entity_type="Guest",
            entity_id=guest.id,
            after={"kimlik_var": bool(cleaned)},
        )

    def _assert_identity_free(self, number: str, *, exclude_guest_id: int | None) -> None:
        """Ayni kimlik numarasi baska bir misafirde kayitli mi?

        ``identity_index`` benzersizdir; onceden kontrol etmezsek kullanici
        anlasilmaz bir veritabani butunluk hatasi gorurdu.
        """
        existing = self.guests.find_by_identity(number)
        if existing is not None and existing.id != exclude_guest_id:
            raise ConflictError(
                "Bu kimlik numarasi baska bir misafir kaydinda tanimli.",
                code="duplicate_identity",
                context={
                    "cozum": "Mevcut kaydi arayip guncelleyin; ayni kisi iki kez acilmamalidir.",
                    "existing_guest_id": existing.id,
                },
            )

    # ----------------------------------------------------------------- #
    #  Kimlik goruntuleme
    # ----------------------------------------------------------------- #
    def reveal_identity(self, guest_id: int) -> IdentityView:
        """Kimlik numarasini gosterime hazirlar.

        Yetki yoksa **maskelenmis** deger doner ve denetim kaydi olusmaz.
        Yetki varsa acik deger doner ve HER goruntuleme
        ``AuditAction.READ`` olarak denetim gunlugune yazilir - KVKK
        kapsaminda "kim, ne zaman, kimin kimligini gordu" sorusunun yaniti
        budur.

        .. warning::
           Denetim kaydinin kalici olmasi icin bu metot **commit eden** bir
           baglamda cagrilmalidir. ``service_context(commit=False)`` icinde
           cagrilirsa kayit geri alinir ve iz kaybolur.
        """
        self.ctx.require(Perm.GUEST_VIEW)
        guest = self.guests.get_or_404(guest_id)
        document_type = guest.identity_document_type.label

        if not self.ctx.can(Perm.GUEST_VIEW_IDENTITY):
            log.info("kimlik_maskeli_gosterildi", guest_id=guest_id)
            return IdentityView(
                value=mask_identity(guest.identity_number),
                is_revealed=False,
                document_type=document_type,
            )

        self.ctx.audit(
            AuditAction.READ,
            f"{guest.full_name} kaydinin kimlik numarasi acik goruntulendi.",
            entity_type="Guest",
            entity_id=guest.id,
        )
        log.warning("kimlik_acik_goruntulendi", guest_id=guest_id)
        return IdentityView(
            value=guest.identity_number or "-",
            is_revealed=True,
            document_type=document_type,
        )

    # ----------------------------------------------------------------- #
    #  Notlar
    # ----------------------------------------------------------------- #
    def add_note(self, guest_id: int, content: str, *, is_alert: bool = False) -> NoteEntry:
        """Misafire personel notu ekler.

        ``is_alert=True`` notlar rezervasyon ve giris ekranlarinda vurgulanir;
        bu yuzden bos icerik kabul edilmez.
        """
        self.ctx.require(Perm.GUEST_EDIT)
        guest = self.guests.get_or_404(guest_id)

        cleaned = _require_text(content, "Not icerigi", "content")
        note = GuestNote(
            guest_id=guest.id,
            author_user_id=self.ctx.user_id,
            content=cleaned,
            is_alert=is_alert,
        )
        self.session.add(note)
        self.session.flush()

        self.ctx.audit(
            AuditAction.CREATE,
            f"{guest.full_name} kaydina not eklendi.",
            entity_type="GuestNote",
            entity_id=note.id,
            after={"is_alert": is_alert},
        )
        author = self.ctx.user.full_name if self.ctx.user is not None else "Sistem"
        return NoteEntry(
            note_id=note.id,
            content=note.content,
            is_alert=note.is_alert,
            author=author,
            created_at=note.created_at,
        )

    # ----------------------------------------------------------------- #
    #  Kara liste
    # ----------------------------------------------------------------- #
    def set_blacklist(
        self,
        guest_id: int,
        blacklisted: bool,
        reason: str | None = None,
    ) -> GuestSummary:
        """Misafiri kara listeye alir veya listeden cikarir.

        Kara listeye alirken **gerekce zorunludur**: gerekcesiz bir kayit,
        aylar sonra bakan personel icin anlamsizdir ve haksiz bir engellemeye
        itiraz edilmesini imkansiz kilar. Gerekce ayrica uyari notu olarak
        saklanir; boylece kara listeden cikarilsa bile iz kalir.
        """
        self.ctx.require(Perm.GUEST_BLACKLIST)
        guest = self.guests.get_or_404(guest_id)

        cleaned = _clean(reason)
        if blacklisted and not cleaned:
            raise ValidationError(
                "Kara listeye almak icin gerekce yazmalisiniz.",
                field="reason",
            )

        before = {
            "is_blacklisted": guest.is_blacklisted,
            "blacklist_reason": guest.blacklist_reason,
        }

        guest.is_blacklisted = blacklisted
        guest.blacklist_reason = cleaned
        guest.blacklisted_at = utcnow() if blacklisted else None

        note_text = (
            f"Kara listeye alindi: {cleaned}"
            if blacklisted
            else f"Kara listeden cikarildi.{f' Gerekce: {cleaned}' if cleaned else ''}"
        )
        self.session.add(
            GuestNote(
                guest_id=guest.id,
                author_user_id=self.ctx.user_id,
                content=note_text,
                is_alert=blacklisted,
            )
        )
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{guest.full_name}: {note_text}",
            entity_type="Guest",
            entity_id=guest.id,
            before=before,
            after={"is_blacklisted": blacklisted, "blacklist_reason": cleaned},
        )
        log.warning("kara_liste_degisti", guest_id=guest.id, blacklisted=blacklisted)
        return _summarize(guest)

    # ----------------------------------------------------------------- #
    #  KVKK izinleri
    # ----------------------------------------------------------------- #
    def record_consent(
        self,
        guest_id: int,
        consent_type: ConsentType,
        granted: bool,
        *,
        source: str | None = None,
        document_reference: str | None = None,
    ) -> ConsentEntry:
        """Izin verme veya geri alma kaydi olusturur.

        Her cagri **yeni bir satir** yazar; mevcut kayit guncellenmez. Izin
        gecmisi KVKK denetiminde ispat niteligindedir ve uzerine yazilamaz.
        """
        self.ctx.require(Perm.GUEST_EDIT)
        guest = self.guests.get_or_404(guest_id)

        now = utcnow()
        record = ConsentRecord(
            guest_id=guest.id,
            consent_type=consent_type,
            is_granted=granted,
            granted_at=now if granted else None,
            revoked_at=None if granted else now,
            source=_clean(source),
            document_reference=_clean(document_reference),
            recorded_by_user_id=self.ctx.user_id,
        )
        self.session.add(record)
        self.session.flush()

        action = "verildi" if granted else "geri alindi"
        self.ctx.audit(
            AuditAction.UPDATE,
            f"{guest.full_name}: '{consent_type.label}' izni {action}.",
            entity_type="ConsentRecord",
            entity_id=record.id,
            after={
                "consent_type": consent_type.value,
                "is_granted": granted,
                "source": record.source,
            },
        )
        log.info(
            "kvkk_izin_kaydi",
            guest_id=guest.id,
            consent_type=consent_type.value,
            granted=granted,
        )
        return ConsentEntry(
            consent_type=consent_type.label,
            consent_value=consent_type.value,
            is_granted=record.is_granted,
            is_valid=record.is_currently_valid,
            recorded_at=record.created_at,
            granted_at=record.granted_at,
            revoked_at=record.revoked_at,
            source=record.source,
        )

    def current_consents(self, guest_id: int) -> dict[str, bool]:
        """Her izin turu icin **en son** kaydin gecerlilik durumu."""
        self.ctx.require(Perm.GUEST_VIEW)
        latest: dict[str, bool] = {}
        # Kayitlar en yeniden eskiye gelir; ilk gorulen tur kazanir.
        for entry in self._consents(guest_id):
            latest.setdefault(entry.consent_value, entry.is_valid)
        return latest

    # ----------------------------------------------------------------- #
    #  Mukerrer kayit
    # ----------------------------------------------------------------- #
    def find_duplicates(self, guest_id: int) -> list[GuestSummary]:
        """Mevcut bir kayitla ayni kisi olmasi muhtemel diger kayitlar."""
        self.ctx.require(Perm.GUEST_VIEW)
        guest = self.guests.get_or_404(guest_id)
        return self.find_possible_duplicates(
            first_name=guest.first_name,
            last_name=guest.last_name,
            email=guest.email,
            exclude_guest_id=guest.id,
        )

    def find_possible_duplicates(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str | None = None,
        exclude_guest_id: int | None = None,
        limit: int = 20,
    ) -> list[GuestSummary]:
        """Kaydetmeden **once** mukerrer kayit uyarisi uretir.

        Olcut: ayni ad + soyad **veya** ayni e-posta. Sonuc bir engel degil,
        bir uyaridir - ayni isimde iki farkli misafir gercekten olabilir.

        .. note::
           SQLite'in ``lower()`` islevi yalnizca ASCII harfleri kucultur;
           "İSMAİL" gibi Turkce buyuk harf iceren yazimlar eslesmeyebilir.
           Uyari mekanizmasi icin kabul edilebilir bir sinirlamadir.
        """
        self.ctx.require(Perm.GUEST_VIEW)

        criteria: list[ColumnElement[bool]] = []
        first = _clean(first_name)
        last = _clean(last_name)
        if first and last:
            criteria.append(
                (func.lower(Guest.first_name) == first.lower())
                & (func.lower(Guest.last_name) == last.lower())
            )
        cleaned_email = _clean(email)
        if cleaned_email:
            criteria.append(func.lower(Guest.email) == cleaned_email.lower())
        if not criteria:
            return []

        stmt = select(Guest).where(Guest.is_deleted.is_(False), or_(*criteria))
        if exclude_guest_id is not None:
            stmt = stmt.where(Guest.id != exclude_guest_id)
        stmt = stmt.order_by(Guest.id).limit(limit)

        return [_summarize(guest) for guest in self.session.scalars(stmt).all()]


# ==========================================================================
#  Yardimcilar
# ==========================================================================
def _clean(value: Any) -> str | None:
    """Metni kirpar; bos ise ``None`` doner."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_text(value: Any, label: str, field_name: str) -> str:
    """Zorunlu metin alani."""
    text = _clean(value)
    if not text:
        raise ValidationError(f"{label} alani bos birakilamaz.", field=field_name)
    return text


def _summarize(guest: Guest) -> GuestSummary:
    """ORM nesnesini liste satirina cevirir (oturum ICINDE cagrilmalidir)."""
    return GuestSummary(
        guest_id=guest.id,
        full_name=guest.full_name,
        display_name=guest.display_name,
        phone=guest.phone or guest.mobile,
        email=guest.email,
        vip_level=guest.vip_level.label,
        vip_level_value=guest.vip_level.value,
        is_vip=guest.is_vip,
        total_stays=guest.total_stays,
        last_stay_date=guest.last_stay_date,
        is_blacklisted=guest.is_blacklisted,
        blacklist_reason=guest.blacklist_reason,
        has_alert=guest.has_active_alerts,
    )


__all__ = [
    "ConsentEntry",
    "GuestProfile",
    "GuestService",
    "GuestSummary",
    "IdentityView",
    "NoteEntry",
    "PreferenceEntry",
    "StayHistoryEntry",
]
