"""Kimlik dogrulama ve oturum yonetimi.

Guvenlik onlemleri
------------------
* **Kullanici sayimi engellenir**: kullanici bulunamasa da parola dogrulamasi
  yapilir (kukla hash uzerinde) ve ayni hata mesaji dondurulur. Aksi halde
  yanit suresi farki, gecerli kullanici adlarinin tespitine izin verirdi.
* **Kaba kuvvet sinirlamasi**: ardisik basarisiz denemeler sayilir, esik
  asilinca hesap gecici olarak kilitlenir.
* **Oturum jetonu hash'lenerek saklanir**; veritabani sizsa bile aktif
  oturumlar ele gecirilemez.
* **Parola yeniden hash'leme**: maliyet parametreleri yukseltildiginde,
  kullanicinin bir sonraki basarili girisinde parolasi sessizce guncellenir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.exceptions import (
    AccountLockedError,
    AuthenticationError,
    AuthorizationError,
    SessionExpiredError,
)
from app.core.log import bind_context, clear_context, get_logger
from app.domain.enums import AuditAction
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.security import Role, User, UserSession
from app.security import audit
from app.security.passwords import (
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)

log = get_logger(__name__)

#: Kullanici bulunamadiginda bile parola dogrulamasi yapmak icin kullanilan
#: sabit hash. Zamanlama farkini ortadan kaldirir.
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("zamanlama-saldirisi-onleyici-kukla-deger")
    return _DUMMY_HASH


@dataclass(slots=True)
class AuthenticatedSession:
    """Basarili girisin sonucu."""

    user: User
    token: str
    """Ham oturum jetonu - **yalnizca burada** goruntulenir, saklanmaz."""

    session_id: int
    expires_at_iso: str

    @property
    def permissions(self) -> set[str]:
        return self.user.permission_codes


def authenticate(
    session: Session,
    username: str,
    password: str,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuthenticatedSession:
    """Kullaniciyi dogrular ve yeni bir oturum acar.

    Raises
    ------
    AccountLockedError
        Cok sayida basarisiz denemeden sonra hesap kilitliyse.
    AuthenticationError
        Kullanici adi/parola hatali veya hesap pasif ise.
    """
    settings = get_settings().security
    normalized_username = (username or "").strip()

    stmt = (
        select(User)
        .where(User.username == normalized_username)
        .options(selectinload(User.roles).selectinload(Role.permissions))
    )
    user = session.scalars(stmt).one_or_none()

    # --- Hesap kilitli mi? ---
    if user is not None and user.is_locked:
        remaining = int((user.locked_until - utcnow()).total_seconds() // 60) + 1
        _record_failed_login(session, normalized_username, ip_address, "hesap kilitli", user=user)
        raise AccountLockedError(
            f"Hesabiniz gecici olarak kilitlendi. {remaining} dakika sonra tekrar deneyin.",
            context={"username": normalized_username},
        )

    # --- Parola dogrulamasi (kullanici yoksa da calisir) ---
    stored_hash = user.password_hash if user is not None else _dummy_hash()
    password_ok = verify_password(password, stored_hash)

    if user is None or not password_ok or not user.is_active:
        if user is not None and not password_ok:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.max_failed_logins:
                user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
                log.warning(
                    "hesap_kilitlendi",
                    username=user.username,
                    failed_count=user.failed_login_count,
                )
        reason = (
            "kullanici bulunamadi"
            if user is None
            else ("hesap pasif" if not user.is_active else "parola hatali")
        )
        _record_failed_login(session, normalized_username, ip_address, reason, user=user)
        # Ayni mesaj: kullanici adinin varligi disari sizmasin.
        raise AuthenticationError(context={"username": normalized_username})

    # --- Basarili giris ---
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    user.last_login_ip = ip_address

    # Maliyet parametreleri degistiyse parolayi sessizce yeniden hash'le.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        log.info("parola_yeniden_hashlendi", username=user.username)

    token = generate_token()
    expires_at = utcnow() + timedelta(minutes=settings.session_timeout_minutes)
    user_session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:300] or None,
    )
    session.add(user_session)
    session.flush()

    audit.record(
        session,
        action=AuditAction.LOGIN,
        description=f"'{user.username}' sisteme giris yapti.",
        user=user,
        entity_type="User",
        entity_id=user.id,
        ip_address=ip_address,
    )
    session.commit()

    bind_context(user_id=user.id, username=user.username)
    log.info("giris_basarili", username=user.username)

    return AuthenticatedSession(
        user=user,
        token=token,
        session_id=user_session.id,
        expires_at_iso=expires_at.isoformat(),
    )


def _record_failed_login(
    session: Session,
    username: str,
    ip_address: str | None,
    reason: str,
    *,
    user: User | None = None,
) -> None:
    """Basarisiz giris denemesini kendi isleminde kaydeder.

    Asil islem reddedildigi icin normal denetim akisina giremez; ancak
    guvenlik acisindan iz birakilmasi zorunludur.
    """
    audit.record(
        session,
        action=AuditAction.LOGIN_FAILED,
        description=f"Basarisiz giris denemesi: '{username}' ({reason}).",
        user=user,
        entity_type="User",
        entity_id=user.id if user else None,
        ip_address=ip_address,
        is_success=False,
    )
    session.commit()
    log.warning("giris_basarisiz", username=username, reason=reason, ip=ip_address)


def resolve_session(session: Session, token: str) -> User:
    """Oturum jetonundan kullaniciyi cozer ve son aktiflik zamanini gunceller.

    Raises
    ------
    SessionExpiredError
        Oturum yoksa, iptal edilmisse veya suresi dolmussa.
    """
    if not token:
        raise SessionExpiredError()

    stmt = (
        select(UserSession)
        .where(UserSession.token_hash == hash_token(token))
        .options(
            selectinload(UserSession.user).selectinload(User.roles).selectinload(Role.permissions)
        )
    )
    user_session = session.scalars(stmt).one_or_none()

    if user_session is None or not user_session.is_valid:
        raise SessionExpiredError()
    if not user_session.user.is_active:
        raise AuthenticationError("Hesabiniz devre disi birakilmis.")

    # Kayan zaman asimi: her etkinlikte sure uzar.
    settings = get_settings().security
    user_session.last_activity_at = utcnow()
    user_session.expires_at = utcnow() + timedelta(minutes=settings.session_timeout_minutes)
    session.commit()

    return user_session.user


def logout(session: Session, token: str, *, user: User | None = None) -> bool:
    """Oturumu iptal eder. Iptal edilen bir oturum varsa ``True`` doner."""
    stmt = select(UserSession).where(UserSession.token_hash == hash_token(token))
    user_session = session.scalars(stmt).one_or_none()
    if user_session is None:
        return False

    user_session.is_revoked = True
    user_session.revoked_at = utcnow()

    audit.record(
        session,
        action=AuditAction.LOGOUT,
        description=f"'{user_session.user.username}' cikis yapti.",
        user=user or user_session.user,
        entity_type="User",
        entity_id=user_session.user_id,
    )
    session.commit()
    clear_context()
    return True


def revoke_all_sessions(session: Session, user_id: int) -> int:
    """Bir kullanicinin tum aktif oturumlarini iptal eder.

    Parola degisikligi, rol degisikligi veya hesap devre disi birakildiginda
    cagrilir. Iptal edilen oturum sayisini dondurur.
    """
    stmt = select(UserSession).where(
        UserSession.user_id == user_id, UserSession.is_revoked.is_(False)
    )
    sessions = list(session.scalars(stmt))
    now = utcnow()
    for user_session in sessions:
        user_session.is_revoked = True
        user_session.revoked_at = now
    session.commit()
    return len(sessions)


def purge_expired_sessions(session: Session) -> int:
    """Suresi dolmus oturum kayitlarini siler; silinen sayiyi dondurur.

    Uygulama acilisinda calisir; oturum tablosunun sonsuza kadar buyumesini
    onler.
    """
    stmt = select(UserSession).where(UserSession.expires_at < utcnow())
    expired = list(session.scalars(stmt))
    for user_session in expired:
        session.delete(user_session)
    session.commit()
    return len(expired)


def change_password(
    session: Session,
    user: User,
    *,
    current_password: str | None,
    new_password: str,
    require_current: bool = True,
    changed_by: User | None = None,
) -> None:
    """Parolayi degistirir ve diger tum oturumlari kapatir.

    Parameters
    ----------
    require_current:
        ``False`` yalnizca yonetici sifirlamasi icindir; bu durumda
        ``changed_by`` kullanicinin ``user.manage`` yetkisi olmalidir.
    """
    from app.security.passwords import validate_password_strength

    if require_current:
        if not current_password or not verify_password(current_password, user.password_hash):
            raise AuthenticationError("Mevcut parolaniz hatali.")
    elif changed_by is not None and not changed_by.has_permission("user.manage"):
        raise AuthorizationError("user.manage")

    validate_password_strength(new_password, username=user.username)

    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.must_change_password = False

    audit.record(
        session,
        action=AuditAction.UPDATE,
        description=f"'{user.username}' kullanicisinin parolasi degistirildi.",
        user=changed_by or user,
        entity_type="User",
        entity_id=user.id,
    )
    session.commit()
    revoke_all_sessions(session, user.id)


def require_permission(user: User | None, permission: str) -> None:
    """Kullanicinin izni yoksa :class:`AuthorizationError` firlatir.

    Servis katmaninda veri degistiren her islemin basinda cagrilir.
    """
    if user is None:
        raise AuthenticationError("Bu islem icin giris yapmalisiniz.")
    if not user.has_permission(permission):
        log.warning("yetki_reddedildi", username=user.username, required_permission=permission)
        raise AuthorizationError(permission)


__all__ = [
    "AuthenticatedSession",
    "authenticate",
    "change_password",
    "logout",
    "purge_expired_sessions",
    "require_permission",
    "resolve_session",
    "revoke_all_sessions",
]
