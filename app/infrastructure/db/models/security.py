"""Kullanici, rol, izin, oturum ve denetim gunlugu modelleri.

Yetkilendirme modeli
--------------------
Kullanici -> Rol(ler) -> Izin(ler) seklinde iki asamali bir RBAC kullanilir.
Izinler ``modul.eylem`` bicimindedir (or. ``reservation.create``,
``finance.view``). Kod icinde izin **kodu** kontrol edilir, rol adi degil;
boylece yeni bir rol tanimlandiginda kod degistirmek gerekmez.

Parola guvenligi
----------------
Parolalar Argon2id ile hash'lenir (bkz. :mod:`app.security.passwords`).
Bu tabloda yalnizca hash tutulur; duz parola hicbir yerde saklanmaz veya
loglanmaz.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import AuditAction
from app.infrastructure.db.base import (
    ActiveMixin,
    Base,
    NotesMixin,
    TimestampMixin,
    enum_column,
    utcnow,
)
from app.infrastructure.db.types import TZDateTime

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import Employee, Property

# --------------------------------------------------------------------------
#  Cok-cok baglantilari
# --------------------------------------------------------------------------
user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permission.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base, TimestampMixin):
    """Tekil yetki tanimi, or. ``reservation.create``."""

    code: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, doc="modul.eylem bicimi."
    )
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(
        String(50), index=True, doc="Arayuzde gruplama icin, or. 'Rezervasyon'."
    )
    description: Mapped[str | None] = mapped_column(String(300), default=None)
    is_dangerous: Mapped[bool] = mapped_column(
        default=False, doc="Silme, fiyat degistirme gibi yuksek etkili yetkiler."
    )

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permission, back_populates="permissions"
    )


class Role(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Rol - izin demeti."""

    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(300), default=None)
    is_system: Mapped[bool] = mapped_column(default=False, doc="Sistem rolu - arayuzden silinemez.")

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permission, back_populates="roles", lazy="selectin"
    )
    users: Mapped[list[User]] = relationship(secondary=user_role, back_populates="roles")

    def has_permission(self, code: str) -> bool:
        return any(p.code == code for p in self.permissions)


class User(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Sisteme giris yapabilen kullanici."""

    __table_args__ = (Index("ix_user_login", "username", "is_active"),)

    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200), default=None, unique=True)
    full_name: Mapped[str] = mapped_column(String(150))

    password_hash: Mapped[str] = mapped_column(
        String(255), doc="Argon2id hash. Duz parola ASLA saklanmaz."
    )
    must_change_password: Mapped[bool] = mapped_column(
        default=False, doc="Ilk giriste veya yonetici sifirlamasindan sonra True."
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    is_superuser: Mapped[bool] = mapped_column(
        default=False, doc="Tum izinlere sahip; yalnizca kurulum yoneticisi icin."
    )
    default_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("property.id", ondelete="SET NULL"), default=None
    )

    # ---- Giris guvenligi ----
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), default=None)
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        TZDateTime, default=None, doc="Bu ana kadar giris denemeleri reddedilir."
    )

    # ---- Tercihler ----
    language: Mapped[str] = mapped_column(String(5), default="tr")
    theme: Mapped[str] = mapped_column(String(10), default="dark")

    roles: Mapped[list[Role]] = relationship(
        secondary=user_role, back_populates="users", lazy="selectin"
    )
    employee: Mapped[Employee | None] = relationship(back_populates="user")
    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    default_property: Mapped[Property | None] = relationship()

    # ---- Yetki sorgulama ----
    @property
    def permission_codes(self) -> set[str]:
        """Kullanicinin tum rollerinden gelen izin kodlari."""
        codes: set[str] = set()
        for role in self.roles:
            if role.is_active:
                codes.update(p.code for p in role.permissions)
        return codes

    def has_permission(self, code: str) -> bool:
        """Belirli bir izne sahip mi?

        Superuser her zaman ``True`` doner. Joker destegi vardir:
        ``reservation.*`` izni ``reservation.create`` kontrolunu gecirir.
        """
        if self.is_superuser:
            return True
        codes = self.permission_codes
        if code in codes:
            return True
        module = code.split(".", 1)[0]
        return f"{module}.*" in codes or "*" in codes

    def has_any_permission(self, *codes: str) -> bool:
        return any(self.has_permission(code) for code in codes)

    @property
    def is_locked(self) -> bool:
        """Hesap su anda kilitli mi?"""
        return self.locked_until is not None and self.locked_until > utcnow()

    @property
    def role_names(self) -> str:
        return ", ".join(role.name for role in self.roles) or "-"


class UserSession(Base, TimestampMixin):
    """Aktif oturum kaydi.

    Oturum jetonunun kendisi degil, **hash'i** saklanir; veritabani sizsa
    bile mevcut oturumlar ele gecirilemez.
    """

    __table_args__ = (Index("ix_session_active", "user_id", "is_revoked", "expires_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    last_activity_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(300), default=None)

    is_revoked: Mapped[bool] = mapped_column(default=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    user: Mapped[User] = relationship(back_populates="sessions")

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and self.expires_at > utcnow()


class AuditLog(Base):
    """Denetim gunlugu - kim, ne zaman, neyi degistirdi.

    Bu tablo **yalnizca eklenir** (append-only): kayitlar guncellenmez veya
    silinmez. ``TimestampMixin`` yerine kendi ``created_at`` alanini tutar,
    cunku ``updated_at`` kavrami burada anlamsizdir.
    """

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_user_time", "user_id", "created_at"),
        Index("ix_audit_action_time", "action", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=utcnow, index=True, nullable=False
    )

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None, index=True
    )
    username: Mapped[str | None] = mapped_column(
        String(60), default=None, doc="Kullanici silinse bile kim oldugu kalsin diye kopyalanir."
    )
    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("property.id", ondelete="SET NULL"), default=None, index=True
    )

    action: Mapped[AuditAction] = mapped_column(enum_column(AuditAction), index=True)
    entity_type: Mapped[str | None] = mapped_column(
        String(60), default=None, doc="Or. 'Reservation', 'Room'."
    )
    entity_id: Mapped[int | None] = mapped_column(default=None)
    description: Mapped[str] = mapped_column(Text)

    before_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=None, doc="Degisiklik oncesi degerler (hassas alanlar maskeli)."
    )
    after_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=None, doc="Degisiklik sonrasi degerler (hassas alanlar maskeli)."
    )

    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)
    is_success: Mapped[bool] = mapped_column(default=True, index=True)

    user: Mapped[User | None] = relationship()


__all__ = [
    "AuditLog",
    "Permission",
    "Role",
    "User",
    "UserSession",
    "role_permission",
    "user_role",
]
