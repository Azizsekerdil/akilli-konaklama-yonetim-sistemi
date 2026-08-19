"""Misafir servisi testleri.

Odak noktalari:

* Arama ad, e-posta ve telefon uzerinde calisir (telefon bicimi degisse bile).
* Kimlik numarasi **varsayilan olarak maskelidir**; acik goruntuleme ayri
  yetki ister ve her defasinda denetim kaydi uretir.
* Kara liste gerekcesiz yapilamaz.
* KVKK izinleri uzerine yazilmaz; verme ve geri alma ayri satirlardir.

Tum test verileri uydurmadir; gercek kisilere ait bilgi kullanilmaz.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.context import ServiceContext
from app.application.services.guest_service import GuestService
from app.core.exceptions import AuthorizationError, ConflictError, ValidationError
from app.domain.enums import AuditAction, ConsentType, GuestTitle, VIPLevel
from app.infrastructure.db.models.guests import ConsentRecord, Guest
from app.infrastructure.db.models.security import AuditLog, Role, User
from app.security.passwords import hash_password
from app.security.permissions import Perm


# --------------------------------------------------------------------------
#  Fiksturler
# --------------------------------------------------------------------------
@pytest.fixture
def service(admin_ctx: ServiceContext) -> GuestService:
    """Tum yetkilere sahip servis."""
    return GuestService(admin_ctx)


@pytest.fixture
def limited_ctx(secured_session: Session, sample_property) -> ServiceContext:
    """Misafiri gorebilen ama kimligi ACIK goremeyen kullanici.

    ``frontdesk`` rolu ``guest.view`` iznine sahiptir,
    ``guest.view_identity`` iznine sahip DEGILDIR - tam olarak test etmek
    istedigimiz ayrim budur.
    """
    role = secured_session.scalars(select(Role).where(Role.code == "frontdesk")).one()
    user = User(
        username="kimliksiz",
        full_name="Yetkisiz Gorevli",
        password_hash=hash_password("KimlikTest2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    secured_session.add(user)
    secured_session.commit()
    return ServiceContext(
        session=secured_session,
        user=user,
        property_id=sample_property.id,
    )


@pytest.fixture
def crm_guest(service: GuestService, secured_session: Session) -> Guest:
    """Kimlik numarasi tanimli bir test misafiri."""
    summary = service.create(
        first_name="Deniz",
        last_name="Yildizli",
        title=GuestTitle.MR,
        email="deniz.yildizli@ornek-test.local",
        phone="+90 555 000 00 01",
        identity_number="11111111110",
        vip_level=VIPLevel.GOLD,
        birth_date=date(1985, 4, 12),
    )
    secured_session.commit()
    return secured_session.get(Guest, summary.guest_id)


def _audit_reads(session: Session) -> list[AuditLog]:
    return list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.action == AuditAction.READ,
                AuditLog.entity_type == "Guest",
            )
        )
    )


# --------------------------------------------------------------------------
#  Arama
# --------------------------------------------------------------------------
def test_search_finds_guest_by_name(service: GuestService, crm_guest: Guest) -> None:
    results = service.search("Yildizli")

    assert [row.guest_id for row in results] == [crm_guest.id]
    assert results[0].full_name == "Deniz Yildizli"


def test_search_finds_guest_by_email(service: GuestService, crm_guest: Guest) -> None:
    results = service.search("deniz.yildizli@ornek-test.local")

    assert [row.guest_id for row in results] == [crm_guest.id]


def test_search_finds_guest_by_phone_without_formatting(
    service: GuestService, crm_guest: Guest
) -> None:
    """Kullanici numarayi bosluksuz yazsa da kayit bulunmalidir."""
    results = service.search("5550000001")

    assert [row.guest_id for row in results] == [crm_guest.id]


def test_empty_search_lists_recent_guests(service: GuestService, crm_guest: Guest) -> None:
    """Bos sorgu bos tablo birakmaz; son misafirler listelenir."""
    results = service.search("")

    assert crm_guest.id in [row.guest_id for row in results]


def test_search_requires_permission(limited_ctx: ServiceContext, crm_guest: Guest) -> None:
    limited_ctx.user.roles.clear()
    limited_ctx.session.flush()

    with pytest.raises(AuthorizationError):
        GuestService(limited_ctx).search("Yildizli")


# --------------------------------------------------------------------------
#  Profil
# --------------------------------------------------------------------------
def test_profile_masks_identity_by_default(service: GuestService, crm_guest: Guest) -> None:
    """Profil cagrisi kimlik numarasini ASLA acik dondurmez."""
    profile = service.get_profile(crm_guest.id)

    assert profile.has_identity is True
    assert profile.identity_masked == "111*****110"
    assert "11111111110" != profile.identity_masked


def test_profile_returns_plain_data_usable_after_session(
    service: GuestService, crm_guest: Guest
) -> None:
    """Profil duz veri yapisidir; ORM iliskisi tasimaz."""
    profile = service.get_profile(crm_guest.id)

    assert profile.summary.full_name == "Deniz Yildizli"
    assert profile.summary.vip_level == "Altin"
    assert isinstance(profile.stays, list)
    assert isinstance(profile.consents, list)


# --------------------------------------------------------------------------
#  Kimlik goruntuleme
# --------------------------------------------------------------------------
def test_reveal_identity_returns_masked_for_unauthorized_user(
    limited_ctx: ServiceContext, crm_guest: Guest
) -> None:
    """Yetkisiz kullanici acik deger yerine maskeli deger alir."""
    view = GuestService(limited_ctx).reveal_identity(crm_guest.id)

    assert view.is_revealed is False
    assert view.value == "111*****110"
    assert _audit_reads(limited_ctx.session) == []


def test_reveal_identity_returns_plain_value_and_writes_audit(
    service: GuestService, admin_ctx: ServiceContext, crm_guest: Guest
) -> None:
    view = service.reveal_identity(crm_guest.id)

    assert view.is_revealed is True
    assert view.value == "11111111110"

    entries = _audit_reads(admin_ctx.session)
    assert len(entries) == 1
    assert entries[0].entity_id == crm_guest.id
    # Denetim aciklamasina numaranin kendisi YAZILMAZ.
    assert "11111111110" not in entries[0].description


def test_every_reveal_creates_a_separate_audit_entry(
    service: GuestService, admin_ctx: ServiceContext, crm_guest: Guest
) -> None:
    """Her goruntuleme ayri kayit uretir - tek bir 'ilk erisim' kaydi yetmez."""
    service.reveal_identity(crm_guest.id)
    service.reveal_identity(crm_guest.id)

    assert len(_audit_reads(admin_ctx.session)) == 2


# --------------------------------------------------------------------------
#  Kimlik yazma
# --------------------------------------------------------------------------
def test_set_identity_updates_blind_index(
    service: GuestService, admin_ctx: ServiceContext, crm_guest: Guest
) -> None:
    service.set_identity(crm_guest.id, "22222222220")

    found = GuestService(admin_ctx).guests.find_by_identity("22222222220")
    assert found is not None
    assert found.id == crm_guest.id


def test_duplicate_identity_is_rejected(
    service: GuestService, secured_session: Session, crm_guest: Guest
) -> None:
    other = service.create(first_name="Kerem", last_name="Aksoy")
    secured_session.flush()

    with pytest.raises(ConflictError):
        service.set_identity(other.guest_id, "11111111110")


# --------------------------------------------------------------------------
#  Kara liste
# --------------------------------------------------------------------------
def test_blacklist_requires_reason(service: GuestService, crm_guest: Guest) -> None:
    with pytest.raises(ValidationError):
        service.set_blacklist(crm_guest.id, True, reason="   ")


def test_blacklist_marks_guest_and_leaves_alert_note(
    service: GuestService, crm_guest: Guest
) -> None:
    summary = service.set_blacklist(crm_guest.id, True, reason="Odeme yapmadan ayrildi")

    assert summary.is_blacklisted is True
    assert summary.blacklist_reason == "Odeme yapmadan ayrildi"
    assert summary.has_alert is True

    profile = service.get_profile(crm_guest.id)
    assert any(note.is_alert for note in profile.notes)


def test_removing_from_blacklist_clears_flag(service: GuestService, crm_guest: Guest) -> None:
    service.set_blacklist(crm_guest.id, True, reason="Gecici kayit")
    summary = service.set_blacklist(crm_guest.id, False)

    assert summary.is_blacklisted is False
    assert summary.blacklist_reason is None


def test_blacklist_requires_blacklist_permission(
    limited_ctx: ServiceContext, crm_guest: Guest
) -> None:
    with pytest.raises(AuthorizationError):
        GuestService(limited_ctx).set_blacklist(crm_guest.id, True, reason="Deneme")


# --------------------------------------------------------------------------
#  KVKK izinleri
# --------------------------------------------------------------------------
def test_consent_grant_and_revoke_are_recorded_separately(
    service: GuestService, secured_session: Session, crm_guest: Guest
) -> None:
    """Geri alma, mevcut satiri degistirmez; YENI bir satir yazar."""
    service.record_consent(crm_guest.id, ConsentType.MARKETING_EMAIL, True, source="giris formu")
    service.record_consent(crm_guest.id, ConsentType.MARKETING_EMAIL, False, source="telefon")

    records = list(
        secured_session.scalars(
            select(ConsentRecord).where(
                ConsentRecord.guest_id == crm_guest.id,
                ConsentRecord.consent_type == ConsentType.MARKETING_EMAIL,
            )
        )
    )

    assert len(records) == 2
    granted = [r for r in records if r.is_granted]
    revoked = [r for r in records if not r.is_granted]
    assert len(granted) == 1 and granted[0].granted_at is not None
    assert len(revoked) == 1 and revoked[0].revoked_at is not None


def test_current_consents_reflects_latest_record(service: GuestService, crm_guest: Guest) -> None:
    service.record_consent(crm_guest.id, ConsentType.DATA_PROCESSING, True)
    service.record_consent(crm_guest.id, ConsentType.MARKETING_SMS, True)
    service.record_consent(crm_guest.id, ConsentType.MARKETING_SMS, False)

    current = service.current_consents(crm_guest.id)

    assert current[ConsentType.DATA_PROCESSING.value] is True
    assert current[ConsentType.MARKETING_SMS.value] is False


# --------------------------------------------------------------------------
#  Mukerrer kayit
# --------------------------------------------------------------------------
def test_find_duplicates_matches_same_name(
    service: GuestService, secured_session: Session, crm_guest: Guest
) -> None:
    twin = service.create(first_name="Deniz", last_name="Yildizli")
    secured_session.flush()

    duplicates = service.find_duplicates(crm_guest.id)

    assert [row.guest_id for row in duplicates] == [twin.guest_id]


def test_find_duplicates_matches_same_email(
    service: GuestService, secured_session: Session, crm_guest: Guest
) -> None:
    twin = service.create(
        first_name="Baska",
        last_name="Kisi",
        email="deniz.yildizli@ornek-test.local",
    )
    secured_session.flush()

    duplicates = service.find_possible_duplicates(
        first_name="Baska",
        last_name="Kisi",
        email="deniz.yildizli@ornek-test.local",
        exclude_guest_id=twin.guest_id,
    )

    assert crm_guest.id in [row.guest_id for row in duplicates]


def test_duplicates_do_not_block_creation(
    service: GuestService, secured_session: Session, crm_guest: Guest
) -> None:
    """Ayni isimde iki farkli kisi olabilir; servis engellemez."""
    twin = service.create(first_name="Deniz", last_name="Yildizli")
    secured_session.flush()

    assert twin.guest_id != crm_guest.id


# --------------------------------------------------------------------------
#  Olusturma / duzenleme / not
# --------------------------------------------------------------------------
def test_create_requires_name(service: GuestService) -> None:
    with pytest.raises(ValidationError):
        service.create(first_name="  ", last_name="Yilmaz")


def test_create_requires_permission(limited_ctx: ServiceContext) -> None:
    limited_ctx.user.roles.clear()
    limited_ctx.session.flush()

    with pytest.raises(AuthorizationError):
        GuestService(limited_ctx).create(first_name="Test", last_name="Kisi")


def test_update_rejects_unknown_field(service: GuestService, crm_guest: Guest) -> None:
    """Beyaz liste disindaki alan sessizce yok sayilmaz."""
    with pytest.raises(ValidationError):
        service.update(crm_guest.id, is_blacklisted=True)


def test_update_changes_fields_and_normalizes_empty_text(
    service: GuestService, crm_guest: Guest
) -> None:
    summary = service.update(crm_guest.id, email="  ", vip_level=VIPLevel.PLATINUM)

    assert summary.email is None
    assert summary.vip_level == "Platin"


def test_add_note_rejects_empty_content(service: GuestService, crm_guest: Guest) -> None:
    with pytest.raises(ValidationError):
        service.add_note(crm_guest.id, "   ")


def test_add_alert_note_appears_in_profile(service: GuestService, crm_guest: Guest) -> None:
    service.add_note(crm_guest.id, "Sessiz oda tercih ediyor.", is_alert=True)

    profile = service.get_profile(crm_guest.id)
    assert profile.notes[0].is_alert is True
    assert profile.notes[0].content == "Sessiz oda tercih ediyor."


def test_permission_catalog_contains_identity_permission() -> None:
    """Ayri kimlik yetkisi katalogda tanimli ve tehlikeli olarak isaretli."""
    from app.security.permissions import PERMISSION_BY_CODE

    spec = PERMISSION_BY_CODE[Perm.GUEST_VIEW_IDENTITY]
    assert spec.is_dangerous is True
