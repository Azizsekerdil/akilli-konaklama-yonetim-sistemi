"""Denetim gunlugu servisi.

Denetim gunlugu **yalnizca eklenir** (append-only). Kayitlar guncellenmez ve
silinmez; mali denetim ve KVKK sorumluluk izleri icin gereklidir.

Hassas veri, veritabanina yazilmadan once
:func:`app.core.log.mask_value` ile maskelenir; boylece "denetim izi tutalim"
derken kimlik numarasi veya API anahtari kalici olarak diske yazilmaz.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.log import get_logger, mask_value
from app.domain.enums import AuditAction
from app.infrastructure.db.models.security import AuditLog, User

log = get_logger(__name__)

#: Denetim kaydina hicbir kosulda yazilmayacak alanlar.
_NEVER_LOG = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "token_hash",
        "api_key",
        "secret",
        "identity_number",
        "card_number",
    }
)


def _sanitize(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Denetim kaydina yazilmadan once sozlugu temizler ve maskeler."""
    if not data:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        normalized = str(key).lower()
        if normalized in _NEVER_LOG:
            continue
        masked = mask_value(str(key), value)
        # JSON'a serilestirilemeyen tipleri (date, Decimal, Enum) metne cevir.
        if not isinstance(masked, (str, int, float, bool, type(None), list, dict)):
            masked = str(masked)
        cleaned[str(key)] = masked
    return cleaned or None


def record(
    session: Session,
    *,
    action: AuditAction,
    description: str,
    user: User | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    property_id: int | None = None,
    ip_address: str | None = None,
    is_success: bool = True,
    flush: bool = True,
) -> AuditLog:
    """Denetim kaydi olusturur ve oturuma ekler.

    ``commit`` **yapilmaz**; cagiran islemin (transaction) parcasi olarak
    kalir. Boylece asil islem geri alinirsa denetim kaydi da geri alinir ve
    "yapilmamis bir islem yapilmis gibi" gorunmez.

    Tek istisna basarisiz giris denemeleridir: onlar kendi islemlerinde
    kaydedilir (bkz. :mod:`app.security.auth`), cunku asil islem zaten
    reddedilmistir ama iz birakilmasi gerekir.
    """
    entry = AuditLog(
        action=action,
        description=description[:2000],
        user_id=user.id if user else None,
        username=user.username if user else None,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=_sanitize(before),
        after_data=_sanitize(after),
        property_id=property_id,
        ip_address=ip_address,
        is_success=is_success,
    )
    session.add(entry)
    if flush:
        session.flush()

    log.info(
        "denetim_kaydi",
        action=action.value,
        entity=entity_type,
        entity_id=entity_id,
        username=user.username if user else None,
        success=is_success,
    )
    return entry


def record_change(
    session: Session,
    *,
    instance: Any,
    action: AuditAction,
    description: str,
    user: User | None = None,
    before: dict[str, Any] | None = None,
    **kwargs: Any,
) -> AuditLog:
    """Bir ORM nesnesi uzerindeki degisikligi kaydeder.

    ``entity_type`` ve ``entity_id`` nesneden otomatik cikarilir; ``after``
    degerleri nesnenin guncel sutunlarindan alinir.
    """
    after = instance.to_dict() if hasattr(instance, "to_dict") else None
    return record(
        session,
        action=action,
        description=description,
        user=user,
        entity_type=type(instance).__name__,
        entity_id=getattr(instance, "id", None),
        before=before,
        after=after,
        **kwargs,
    )


def recent(
    session: Session,
    *,
    limit: int = 100,
    user_id: int | None = None,
    action: AuditAction | None = None,
    entity_type: str | None = None,
) -> list[AuditLog]:
    """Son denetim kayitlarini dondurur (en yeni once)."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    return list(session.scalars(stmt.limit(limit)))


def entity_history(session: Session, entity_type: str, entity_id: int) -> list[AuditLog]:
    """Belirli bir kaydin tum degisiklik gecmisi (eskiden yeniye)."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    return list(session.scalars(stmt))


__all__ = ["entity_history", "recent", "record", "record_change"]
