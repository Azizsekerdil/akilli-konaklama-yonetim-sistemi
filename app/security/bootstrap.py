"""Guvenlik verilerinin ilk kurulumu ve senkronizasyonu.

Bu modul her uygulama acilisinda calisacak sekilde tasarlanmistir
(**idempotent**): izin katalogu koddan veritabanina senkronlanir, eksik roller
olusturulur, mevcut olanlar guncellenir. Boylece yeni bir surumde izin
eklendiginde ayrica goc yazmak gerekmez.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.log import get_logger
from app.infrastructure.db.models.security import Permission, Role, User
from app.security.passwords import (
    hash_password,
    validate_password_strength,
)
from app.security.permissions import (
    DEFAULT_ROLES,
    PERMISSIONS,
    validate_catalog,
)

log = get_logger(__name__)


@dataclass(slots=True)
class BootstrapResult:
    """Kurulum sonucunun ozeti - kurulum sihirbazi bunu kullaniciya gosterir."""

    permissions_created: int = 0
    permissions_updated: int = 0
    roles_created: int = 0
    roles_updated: int = 0
    admin_created: bool = False
    admin_username: str | None = None
    generated_password: str | None = None
    """Yeni yonetici olusturulduysa uretilen parola.

    **Yalnizca bir kez** gosterilir; hicbir yerde saklanmaz ve loglanmaz.
    """

    @property
    def any_change(self) -> bool:
        return bool(
            self.permissions_created
            or self.permissions_updated
            or self.roles_created
            or self.roles_updated
            or self.admin_created
        )


def sync_permissions(session: Session) -> tuple[int, int]:
    """Izin katalogunu veritabaniyla senkronlar.

    Katalogda olmayan izinler **silinmez**: ozel olarak tanimlanmis izinler
    varsa kaybolmamalidir. Yalnizca eklenir ve guncellenir.

    Returns
    -------
    tuple[int, int]
        (olusturulan, guncellenen) sayilari.
    """
    existing = {p.code: p for p in session.scalars(select(Permission))}
    created = updated = 0

    for spec in PERMISSIONS:
        current = existing.get(spec.code)
        if current is None:
            session.add(
                Permission(
                    code=spec.code,
                    name=spec.name,
                    category=spec.category,
                    description=spec.description or None,
                    is_dangerous=spec.is_dangerous,
                )
            )
            created += 1
        elif (
            current.name != spec.name
            or current.category != spec.category
            or current.is_dangerous != spec.is_dangerous
        ):
            current.name = spec.name
            current.category = spec.category
            current.description = spec.description or None
            current.is_dangerous = spec.is_dangerous
            updated += 1

    session.flush()
    return created, updated


def sync_roles(session: Session, *, update_existing: bool = True) -> tuple[int, int]:
    """Varsayilan rolleri olusturur ve izinlerini gunceller.

    Parameters
    ----------
    update_existing:
        ``False`` ise mevcut rollerin izinlerine dokunulmaz. Yonetici arayuzden
        bir rolu ozellestirmisse, surum yukseltmesi bunu ezmemelidir.
        Varsayilan ``True``'dur cunku sistem rolleri koddan yonetilir; kullanici
        tanimli roller zaten ``is_system=False`` olur ve buraya girmez.
    """
    permissions = {p.code: p for p in session.scalars(select(Permission))}
    existing = {r.code: r for r in session.scalars(select(Role))}
    created = updated = 0

    for spec in DEFAULT_ROLES:
        role = existing.get(spec.code)
        desired = [permissions[c] for c in spec.permissions if c in permissions]

        if role is None:
            role = Role(
                code=spec.code,
                name=spec.name,
                description=spec.description,
                is_system=spec.is_system,
            )
            role.permissions = desired
            session.add(role)
            created += 1
            continue

        if not update_existing or not role.is_system:
            continue

        current_codes = {p.code for p in role.permissions}
        desired_codes = {p.code for p in desired}
        if current_codes != desired_codes or role.name != spec.name:
            role.name = spec.name
            role.description = spec.description
            role.permissions = desired
            updated += 1

    session.flush()
    return created, updated


def ensure_admin_user(
    session: Session,
    *,
    username: str = "admin",
    password: str | None = None,
    full_name: str = "Sistem Yoneticisi",
    email: str | None = None,
) -> tuple[User, str | None]:
    """Yonetici hesabi yoksa olusturur.

    Parola verilmezse tek kullanimlik ``admin`` bootstrap parolasi kullanilir.
    Bu masaustu urununde ag giris yuzeyi yoktur; ana pencere acilmadan once
    parola degisimi zorlanir ve eski parola kalici olarak gecersizlesir.

    Tek kullanimlik bootstrap
    -------------------------
    Yeni kurulum ``admin`` / ``admin`` ile baslar. Parola Argon2id ile
    hash'lenerek saklanir ve
    ``must_change_password`` isaretiyle ilk giriste degistirilmesi zorunlu
    kilinir (bkz. ``app/main.py`` - ana pencere acilmadan once
    ``ChangePasswordDialog`` calisir).

    Acikca bir parola verilirse (``hotel bootstrap --admin-password ...``)
    parola **guc denetiminden gecirilir**: "admin", "sifre123" gibi sozluk
    parolalari reddedilir. Boylece "elle zayif parola koyma" yolu da kapalidir.

    Raises
    ------
    ValidationError
        Acikca verilen parola guc kurallarini karsilamiyorsa.

    Returns
    -------
    tuple[User, str | None]
        (kullanici, uretilen parola). Kullanici zaten varsa parola ``None``.
    """
    existing = session.scalars(select(User).where(User.username == username)).one_or_none()
    if existing is not None:
        return existing, None

    generated = password is None
    if not generated:
        # Operatorun elle verdigi parola da kurallara tabidir; aksi halde
        # "--admin-password admin" ile varsayilan-parola sinifi geri gelirdi.
        validate_password_strength(password or "", username=username)
    effective_password = password or "admin"

    admin_role = session.scalars(select(Role).where(Role.code == "admin")).one_or_none()

    user = User(
        username=username,
        full_name=full_name,
        email=email,
        password_hash=hash_password(effective_password),
        is_superuser=True,
        is_active=True,
        must_change_password=True,
    )
    if admin_role is not None:
        user.roles.append(admin_role)

    session.add(user)
    session.flush()

    log.warning(
        "yonetici_hesabi_olusturuldu",
        username=username,
        parola_uretildi=generated,
        uyari="Ilk giriste parolayi degistirin.",
    )
    return user, (effective_password if generated else None)


def bootstrap_security(
    session: Session,
    *,
    create_admin: bool = True,
    admin_username: str = "admin",
    admin_password: str | None = None,
) -> BootstrapResult:
    """Tum guvenlik kurulumunu tek cagrida yapar (idempotent)."""
    validate_catalog()

    result = BootstrapResult()
    result.permissions_created, result.permissions_updated = sync_permissions(session)
    result.roles_created, result.roles_updated = sync_roles(session)

    if create_admin:
        admin, generated = ensure_admin_user(
            session, username=admin_username, password=admin_password
        )
        result.admin_username = admin.username
        result.admin_created = generated is not None
        result.generated_password = generated

    session.commit()

    if result.any_change:
        log.info(
            "guvenlik_kurulumu_tamam",
            izin_eklendi=result.permissions_created,
            izin_guncellendi=result.permissions_updated,
            rol_eklendi=result.roles_created,
            rol_guncellendi=result.roles_updated,
        )
    return result


__all__ = [
    "BootstrapResult",
    "bootstrap_security",
    "ensure_admin_user",
    "sync_permissions",
    "sync_roles",
]
