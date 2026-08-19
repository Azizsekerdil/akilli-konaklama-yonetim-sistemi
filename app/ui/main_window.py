"""Ana pencere: sol gezinme, ust cubuk ve sayfa yigini.

Gezinme menusu **yetkiye gore** olusturulur: kullanicinin izni olmayan
ekranlar menude hic gorunmez. Bu, hem arayuzu sadelestirir hem de
"tiklayinca yetki hatasi" deneyimini onler. Yetki kontrolu ayrica servis
katmaninda da yapilir; menuyu gizlemek tek basina bir guvenlik onlemi
degildir.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.core.log import get_logger
from app.infrastructure.db.models.security import User
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.pages.registry import PageSpec, build_page_specs
from app.ui.session import UiSession
from app.ui.widgets.common import confirm, show_toast

log = get_logger(__name__)


class MainWindow(QMainWindow):
    """Uygulamanin ana penceresi."""

    def __init__(self, *, user: User, session_token: str) -> None:
        super().__init__()

        self.ui_session = UiSession(user=user, token=session_token)

        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1100, 700))

        if not self.ui_session.ensure_property():
            self._show_no_property_state()
            return

        self._pages: dict[str, BasePage] = {}
        self._build_ui()
        self._register_shortcuts()
        self._show_page("dashboard")

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setFixedWidth(232)
        self.nav.currentItemChanged.connect(self._on_nav_changed)
        body.addWidget(self.nav)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self._build_pages()

        status = QStatusBar()
        status.showMessage(
            f"{self.ui_session.user.full_name}  •  {self.ui_session.user.role_names}"
        )
        self.setStatusBar(status)

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(56)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        # Uygulama adi
        brand = QLabel(t("app.short_name"))
        brand.setStyleSheet("font-weight: 700; font-size: 12pt;")
        layout.addWidget(brand)

        # Tesis secici
        self.property_combo = QComboBox()
        self.property_combo.setMinimumWidth(220)
        for property_id, name in self.ui_session.available_properties():
            self.property_combo.addItem(name, property_id)
        index = self.property_combo.findData(self.ui_session.property_id)
        if index >= 0:
            self.property_combo.setCurrentIndex(index)
        self.property_combo.currentIndexChanged.connect(self._on_property_changed)
        layout.addWidget(self.property_combo)

        layout.addStretch(1)

        # Not: "Yenile" dugmesi ust cubukta DEGIL, her sayfanin kendi
        # basliginda yer alir; iki yerde birden bulunmasi gereksiz tekrardi.
        # Klavye kisayolu (F5) her ekranda calisir.

        # Kullanici menusu
        self.user_button = QToolButton()
        self.user_button.setText(f"  {self.ui_session.user.full_name}  ")
        self.user_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(self.user_button)
        change_password = QAction(t("auth.change_password"), self)
        change_password.triggered.connect(self._change_password)
        menu.addAction(change_password)
        menu.addSeparator()
        logout = QAction(t("auth.logout"), self)
        logout.triggered.connect(self._logout)
        menu.addAction(logout)
        self.user_button.setMenu(menu)
        layout.addWidget(self.user_button)

        return bar

    def _build_pages(self) -> None:
        """Sayfalari kayit defterinden olusturur.

        Yetkisi olmayan ekranlar menude hic gorunmez. Sayfa siniflari
        :mod:`app.ui.pages.registry` icinde tembel yuklenir; boylece acilista
        yalnizca panel modulu import edilir.
        """
        self._specs: dict[str, PageSpec] = {}

        for spec in build_page_specs():
            if spec.permission and not self.ui_session.can(spec.permission):
                continue

            try:
                page = spec.build(self.ui_session)
            except Exception as exc:
                log.error(
                    "sayfa_olusturulamadi",
                    page=spec.key,
                    error=str(exc),
                    exc_info=True,
                )
                continue

            self._pages[spec.key] = page
            self._specs[spec.key] = spec
            self.stack.addWidget(page)

            item = QListWidgetItem(f"  {spec.icon}   {spec.title}")
            item.setData(Qt.ItemDataRole.UserRole, spec.key)
            if not spec.is_ready:
                item.setToolTip("Bu ekran henuz tamamlanmadi")
            self.nav.addItem(item)

    def _register_shortcuts(self) -> None:
        """Klavye kisayollari.

        Ekran kisayollari kayit defterinden gelir; yeni bir ekran eklendiginde
        burasi degistirilmez.
        """
        QShortcut(QKeySequence("F5"), self, self._refresh_current)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)

        for key, spec in self._specs.items():
            if spec.shortcut:
                QShortcut(
                    QKeySequence(spec.shortcut),
                    self,
                    lambda page_key=key: self._show_page(page_key),
                )

    # ----------------------------------------------------------------- #
    #  Gezinme
    # ----------------------------------------------------------------- #
    def _show_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        for index in range(self.nav.count()):
            item = self.nav.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.nav.setCurrentItem(item)
                break
        page.on_shown()

    def _on_nav_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        page = self._pages.get(key)
        if page is not None:
            self.stack.setCurrentWidget(page)
            page.on_shown()

    def _refresh_current(self) -> None:
        page = self.stack.currentWidget()
        if isinstance(page, BasePage):
            page.refresh(force=True)
            show_toast(self, "Veriler yenilendi.")

    def _on_property_changed(self, index: int) -> None:
        property_id = self.property_combo.itemData(index)
        if property_id is None:
            return
        self.ui_session.set_property(property_id, self.property_combo.itemText(index))
        for page in self._pages.values():
            page.invalidate()
        self._refresh_current()

    # ----------------------------------------------------------------- #
    #  Kullanici islemleri
    # ----------------------------------------------------------------- #
    def _change_password(self) -> None:
        from app.ui.login import ChangePasswordDialog

        dialog = ChangePasswordDialog(self.ui_session.user, parent=self)
        if dialog.exec() == ChangePasswordDialog.DialogCode.Accepted:
            QMessageBox.information(
                self,
                t("common.success"),
                "Parolaniz degistirildi. Guvenlik nedeniyle yeniden giris yapmalisiniz.",
            )
            self.close()

    def _logout(self) -> None:
        if not confirm(self, "Cikis yapmak istediginize emin misiniz?"):
            return
        self.ui_session.logout()
        self.close()

    # ----------------------------------------------------------------- #
    #  Ozel durumlar
    # ----------------------------------------------------------------- #
    def _show_no_property_state(self) -> None:
        """Hic tesis tanimli degilse kullaniciya ne yapacagini soyler."""
        from app.ui.widgets.common import EmptyState

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(
            EmptyState(
                "Sistemde tanimli bir tesis bulunamadi.",
                hint=(
                    "Demo veri olusturmak icin PowerShell'de:\n"
                    "    .\\scripts\\setup.ps1 -DemoData\n\n"
                    "veya:\n"
                    "    .\\.venv\\Scripts\\python.exe -m app.cli seed-demo"
                ),
                icon="\U0001f3e8",
            )
        )
        self.setCentralWidget(central)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt imzasi
        log.info("arayuz_kapaniyor", username=self.ui_session.user.username)
        event.accept()


__all__ = ["MainWindow"]
