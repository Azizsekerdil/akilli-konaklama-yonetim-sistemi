"""Servis baglami: oturum, kullanici ve tesis.

Her servis cagrisinin uc seye ihtiyaci vardir: bir veritabani oturumu,
islemi yapan kullanici (yetki ve denetim icin) ve uzerinde calisilan tesis.
Bunlari her metoda ayri ayri gecirmek yerine tek bir baglam nesnesinde
toplariz; boylece imzalar sade kalir ve yetki kontrolu unutulmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ValidationError
from app.domain.enums import AuditAction
from app.infrastructure.db.models.security import User
from app.security import audit


@dataclass(slots=True)
class ServiceContext:
    """Bir servis cagrisinin calisma baglami."""

    session: Session
    user: User | None = None
    property_id: int | None = None
    ip_address: str | None = None

    #: Yetki kontrollerini atlar. **Yalnizca** sistem gorevleri (demo veri
    #: uretimi, goc sonrasi bakim) icin kullanilir; arayuzden ASLA True
    #: gecilmez.
    system: bool = False

    _extras: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---------------- Yetki ----------------
    def require(self, permission: str) -> None:
        """Kullanicinin izni yoksa hata firlatir ve denetime yazar."""
        if self.system:
            return

        if self.user is None:
            raise AuthorizationError(
                permission,
                user_message="Bu islem icin giris yapmalisiniz.",
            )

        if not self.user.has_permission(permission):
            audit.record(
                self.session,
                action=AuditAction.PERMISSION_DENIED,
                description=f"'{permission}' yetkisi reddedildi.",
                user=self.user,
                property_id=self.property_id,
                ip_address=self.ip_address,
                is_success=False,
            )
            raise AuthorizationError(permission)

    def can(self, permission: str) -> bool:
        """Yetki var mi? Arayuzde dugme etkinligi icin."""
        if self.system:
            return True
        return self.user is not None and self.user.has_permission(permission)

    # ---------------- Tesis ----------------
    def require_property(self) -> int:
        """Tesis kimligini dondurur; tanimli degilse hata firlatir."""
        if self.property_id is None:
            raise ValidationError(
                "Islem icin bir tesis secilmelidir.",
                field="property_id",
            )
        return self.property_id

    # ---------------- Denetim ----------------
    def audit(
        self,
        action: AuditAction,
        description: str,
        *,
        entity_type: str | None = None,
        entity_id: int | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        is_success: bool = True,
    ) -> None:
        """Denetim kaydi olusturur (baglamdaki kullanici ve tesis ile)."""
        audit.record(
            self.session,
            action=action,
            description=description,
            user=self.user,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            property_id=self.property_id,
            ip_address=self.ip_address,
            is_success=is_success,
        )

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None

    @classmethod
    def system_context(cls, session: Session, property_id: int | None = None) -> ServiceContext:
        """Yetki kontrolu yapmayan baglam - yalnizca sistem gorevleri icin."""
        return cls(session=session, property_id=property_id, system=True)


__all__ = ["ServiceContext"]
