"""Sayfa kayit defteri.

Ana pencere, ekranlari burada tanimli listeden olusturur. Yeni bir ekran
eklemek icin yalnizca bu listeye bir :class:`PageSpec` eklemek yeterlidir;
``main_window.py`` degistirilmez.

Bir sayfa iki bicimde tanimlanabilir:

* **Hazir sayfa** - ``factory`` verilir, gercek ekran olusturulur.
* **Tamamlanmamis sayfa** - ``placeholder`` verilir; kullaniciya modulun
  durumu ve ne zaman tamamlanacagi DURUSTCE gosterilir.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.ui.pages.base import BasePage
from app.ui.session import UiSession


@dataclass(frozen=True, slots=True)
class PlaceholderSpec:
    """Tamamlanmamis bir ekranin kullaniciya gosterilecek bilgisi."""

    description: str
    planned_features: tuple[str, ...] = ()
    workaround: str | None = None


@dataclass(frozen=True, slots=True)
class PageSpec:
    """Sol menude yer alan bir ekranin tanimi."""

    key: str
    icon: str
    title: str
    permission: str | None = None
    factory: Callable[[UiSession], BasePage] | None = None
    placeholder: PlaceholderSpec | None = None
    shortcut: str | None = None
    """Or. ``"Ctrl+2"``."""

    def build(self, ui_session: UiSession) -> BasePage:
        """Sayfayi olusturur."""
        if self.factory is not None:
            return self.factory(ui_session)

        from app.ui.pages.placeholder_page import PlaceholderPage

        spec = self.placeholder or PlaceholderSpec(description="Bu ekran hazirlaniyor.")
        return PlaceholderPage(
            ui_session,
            title=self.title,
            description=spec.description,
            planned_features=list(spec.planned_features),
            workaround=spec.workaround,
            required_permission=self.permission,
        )

    @property
    def is_ready(self) -> bool:
        return self.factory is not None


def _lazy(module: str, attribute: str) -> Callable[[UiSession], BasePage]:
    """Sayfa sinifini **ilk kullanimda** yukler.

    Tum sayfa modullerini acilista import etmek, kullanicinin hic acmayacagi
    ekranlarin da baslangic suresine eklenmesi demektir. Tembel yukleme ile
    yalnizca acilan ekranin modulu yuklenir.
    """

    def factory(ui_session: UiSession) -> BasePage:
        import importlib

        page_class = getattr(importlib.import_module(module), attribute)
        return page_class(ui_session)

    return factory


def build_page_specs() -> list[PageSpec]:
    """Uygulamadaki tum ekranlarin tanimi (menu sirasiyla)."""
    from app.security.permissions import Perm

    return [
        PageSpec(
            key="dashboard",
            icon="\U0001f4ca",
            title="Yonetim Paneli",
            permission=Perm.DASHBOARD_VIEW,
            factory=_lazy("app.ui.pages.dashboard_page", "DashboardPage"),
            shortcut="Ctrl+1",
        ),
        PageSpec(
            key="reservations",
            icon="\U0001f4c5",
            title="Rezervasyonlar",
            permission=Perm.RESERVATION_VIEW,
            factory=_lazy("app.ui.pages.reservations_page", "ReservationsPage"),
            shortcut="Ctrl+2",
        ),
        PageSpec(
            key="frontdesk",
            icon="\U0001f6ce",
            title="On Buro",
            permission=Perm.FRONTDESK_CHECKIN,
            factory=_lazy("app.ui.pages.frontdesk_page", "FrontdeskPage"),
            shortcut="Ctrl+3",
        ),
        PageSpec(
            key="rooms",
            icon="\U0001f6cf",
            title="Odalar",
            permission=Perm.ROOM_VIEW,
            factory=_lazy("app.ui.pages.rooms_page", "RoomsPage"),
            shortcut="Ctrl+4",
        ),
        PageSpec(
            key="guests",
            icon="\U0001f465",
            title="Misafirler",
            permission=Perm.GUEST_VIEW,
            factory=_lazy("app.ui.pages.guests_page", "GuestsPage"),
            shortcut="Ctrl+5",
        ),
        PageSpec(
            key="housekeeping",
            icon="\U0001f9f9",
            title="Kat Hizmetleri",
            permission=Perm.HOUSEKEEPING_VIEW,
            factory=_lazy("app.ui.pages.housekeeping_page", "HousekeepingPage"),
        ),
        PageSpec(
            key="maintenance",
            icon="\U0001f527",
            title="Teknik Servis",
            permission=Perm.MAINTENANCE_VIEW,
            factory=_lazy("app.ui.pages.maintenance_page", "MaintenancePage"),
        ),
        PageSpec(
            key="finance",
            icon="\U0001f4b0",
            title="Finans",
            permission=Perm.FINANCE_VIEW,
            placeholder=PlaceholderSpec(
                description="Kasa hareketleri, tahsilat ozeti ve gun sonu kapanisi.",
                planned_features=(
                    "Gelir-gider kaydi ve kasa defteri",
                    "Gun sonu kapanisi",
                    "Fatura duzenleme (e-Fatura entegrasyonu ayri)",
                ),
                workaround=(
                    "Tahsilat ve folyo islemleri On Buro ekranindan yapilabiliyor; "
                    "mali ozetler Raporlar ekraninda mevcut."
                ),
            ),
        ),
        PageSpec(
            key="inventory",
            icon="\U0001f4e6",
            title="Stok",
            permission=Perm.INVENTORY_VIEW,
            placeholder=PlaceholderSpec(
                description="Stok kartlari, depo hareketleri ve satin alma talepleri.",
                planned_features=(
                    "Stok karti ve minimum seviye uyarisi",
                    "Depo giris/cikis hareketleri",
                    "Satin alma talebi ve onay akisi",
                ),
                workaround=(
                    "Kritik stok uyarilari Yonetim Paneli'nde gorunuyor; "
                    "stok raporu Raporlar ekranindan alinabiliyor."
                ),
            ),
        ),
        PageSpec(
            key="reports",
            icon="\U0001f4c8",
            title="Raporlar",
            permission=Perm.REPORT_VIEW,
            factory=_lazy("app.ui.pages.reports_page", "ReportsPage"),
            shortcut="Ctrl+R",
        ),
        PageSpec(
            key="ai_center",
            icon="\U0001f916",
            title="Yapay Zeka Merkezi",
            permission=Perm.AI_USE,
            factory=_lazy("app.ui.pages.ai_center_page", "AICenterPage"),
        ),
        PageSpec(
            key="dev_center",
            icon="\U0001f6e0",
            title="AI Gelistirme Merkezi",
            permission=Perm.DEVCENTER_USE,
            factory=_lazy("app.ui.pages.dev_center_page", "DevCenterPage"),
        ),
        PageSpec(
            key="settings",
            icon="⚙",
            title="Ayarlar",
            permission=Perm.SETTINGS_VIEW,
            factory=_lazy("app.ui.pages.settings_page", "SettingsPage"),
        ),
    ]


__all__ = ["PageSpec", "PlaceholderSpec", "build_page_specs"]
