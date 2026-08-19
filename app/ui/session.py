"""Arayuz oturum baglami.

Arayuzun her yerinde "su an kim giris yapmis, hangi tesiste calisiyoruz"
bilgisine ihtiyac duyulur. Bu modul o bilgiyi tek yerde tutar ve servis
baglami (:class:`~app.application.context.ServiceContext`) uretmeyi
kolaylastirir.

Oturum kullanimi::

    with ui_session.service_context() as ctx:
        snapshot = DashboardService(ctx).get_snapshot()

Baglam yoneticisi cikista **commit** eder; hata durumunda geri alir.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from app.application.context import ServiceContext
from app.core.log import bind_context, clear_context, get_logger
from app.infrastructure.db.models.organization import Property
from app.infrastructure.db.models.security import User
from app.infrastructure.db.session import session_scope

log = get_logger(__name__)


@dataclass(slots=True)
class UiSession:
    """Arayuzde etkin oturum."""

    user: User
    token: str
    property_id: int | None = None
    property_name: str = ""

    def __post_init__(self) -> None:
        bind_context(user_id=self.user.id, username=self.user.username)

    # ---------------- Baglam ----------------
    @contextmanager
    def service_context(self, *, commit: bool = True) -> Iterator[ServiceContext]:
        """Servis cagrilari icin oturum + baglam uretir.

        Kullanici nesnesi her baglamda yeniden yuklenir. Nedeni: SQLAlchemy
        nesneleri kendi oturumlarina baglidir; giristen kalan nesneyi baska
        bir oturumda kullanmak "DetachedInstanceError" uretir.
        """
        with session_scope(commit=commit) as session:
            user = session.get(User, self.user.id)
            if user is None:  # pragma: no cover - hesap silinmis olabilir
                raise RuntimeError("Oturum acan kullanici bulunamadi.")
            yield ServiceContext(
                session=session,
                user=user,
                property_id=self.property_id,
            )

    # ---------------- Tesis ----------------
    def set_property(self, property_id: int, name: str = "") -> None:
        self.property_id = property_id
        self.property_name = name
        log.info("tesis_secildi", property_id=property_id, name=name)

    def ensure_property(self) -> bool:
        """Tesis secili degilse ilk aktif tesisi secer.

        Returns
        -------
        bool
            Bir tesis secilebildiyse ``True``.
        """
        if self.property_id is not None:
            return True

        with session_scope(commit=False) as session:
            from sqlalchemy import select

            prop = session.scalars(
                select(Property).where(Property.is_active.is_(True)).order_by(Property.id)
            ).first()
            if prop is None:
                return False
            self.set_property(prop.id, prop.name)
            return True

    def available_properties(self) -> list[tuple[int, str]]:
        """Kullanicinin erisebilecegi tesisler."""
        from sqlalchemy import select

        with session_scope(commit=False) as session:
            rows = session.scalars(
                select(Property).where(Property.is_active.is_(True)).order_by(Property.name)
            ).all()
            return [(p.id, p.name) for p in rows]

    # ---------------- Yetki ----------------
    def can(self, permission: str) -> bool:
        """Etkin kullanicinin yetkisi var mi?"""
        return self.user.has_permission(permission)

    # ---------------- Kapanis ----------------
    def logout(self) -> None:
        """Oturumu sonlandirir."""
        from app.security import auth

        try:
            with session_scope(commit=False) as session:
                auth.logout(session, self.token)
        except Exception as exc:
            log.warning("cikis_hatasi", error=str(exc))
        finally:
            clear_context()


__all__ = ["UiSession"]
