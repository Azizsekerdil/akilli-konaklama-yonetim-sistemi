"""Ilk calistirma sihirbazi.

Neden gerekli?
--------------
Kaynak koddan calistiran gelistirici ``setup.ps1`` ile kurulumu yapar. Ancak
paketlenmis ``.exe``'yi cift tiklayan kullanicida o betik **yoktur**. Uygulama
"veritabani hazir degil, setup.ps1 calistirin" deyip kapanirsa kullanabilir
bir urun degildir.

Bu sihirbaz o boslugu kapatir: veritabanini kurar, izin/rol/yonetici
hesabini olusturur, istege bagli demo veri ekler ve **yonetici parolasini
bir kez gosterir**.

Kurulum arka plan is parcaciginda calisir; goc ve demo veri uretimi
saniyeler surebilir ve arayuz donmamalidir.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.log import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class SetupResult:
    """Kurulum sonucu."""

    success: bool
    admin_username: str = ""
    admin_password: str = ""
    demo_created: bool = False
    demo_users: list[tuple[str, str, str]] | None = None
    """(kullanici adi, parola, rol) uclulari."""

    message: str = ""


class _SetupWorker(QObject):
    """Kurulumu arka planda yapar."""

    progress = Signal(str)
    finished = Signal(object)

    def __init__(self, *, with_demo: bool) -> None:
        super().__init__()
        self._with_demo = with_demo

    def run(self) -> None:
        try:
            result = self._setup()
        except Exception as exc:
            log.error("ilk_kurulum_hatasi", error=str(exc), exc_info=True)
            result = SetupResult(
                success=False,
                message=f"Kurulum tamamlanamadi.\n\nTeknik ayrinti: {exc}",
            )
        self.finished.emit(result)

    def _setup(self) -> SetupResult:
        from app.core import paths

        self.progress.emit("Klasorler hazirlaniyor...")
        paths.ensure_writable_dirs()

        # --- Veritabani semasi ---
        self.progress.emit("Veritabani olusturuluyor...")
        self._run_migrations()

        # --- Izin, rol, yonetici ---
        self.progress.emit("Izinler ve roller kuruluyor...")
        from app.infrastructure.db.session import reset_engine, session_scope
        from app.security.bootstrap import bootstrap_security

        reset_engine()  # goc sonrasi motoru tazele

        with session_scope() as session:
            bootstrap = bootstrap_security(session, create_admin=True)

        result = SetupResult(
            success=True,
            admin_username=bootstrap.admin_username or "admin",
            admin_password=bootstrap.generated_password or "",
        )

        # --- Demo veri ---
        if self._with_demo:
            self.progress.emit("Demo veri olusturuluyor... (bir dakika surebilir)")
            try:
                from app.infrastructure.seed.demo_data import create_demo_data

                with session_scope() as session:
                    summary = create_demo_data(session)
                result.demo_created = True
                result.demo_users = [
                    (user.username, user.password, user.role_code)
                    for user in getattr(summary, "users", [])
                ]
            except Exception as exc:
                log.warning("demo_veri_olusturulamadi", error=str(exc))
                result.message = (
                    "Kurulum tamamlandi ancak demo veri olusturulamadi. "
                    "Uygulamayi bos veriyle kullanabilirsiniz."
                )

        return result

    @staticmethod
    def _run_migrations() -> None:
        """Alembic goclerini programatik olarak uygular.

        Komut satiri yerine Alembic API'si kullanilir: paketlenmis uygulamada
        ``alembic.exe`` bulunmaz, yalnizca kutuphane vardir.
        """
        from alembic.config import Config

        from alembic import command
        from app.core import paths
        from app.core.config import get_settings

        ini_path = paths.RESOURCE_ROOT / "alembic.ini"
        script_path = paths.RESOURCE_ROOT / "alembic"

        config = Config(str(ini_path) if ini_path.exists() else None)
        config.set_main_option("script_location", str(script_path))
        config.set_main_option("sqlalchemy.url", get_settings().database.resolved_url())

        command.upgrade(config, "head")


class FirstRunDialog(QDialog):
    """Ilk calistirmada gosterilen kurulum sihirbazi."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ilk Kurulum")
        self.setMinimumWidth(560)
        self.setModal(True)

        self._result: SetupResult | None = None
        self._thread: QThread | None = None
        self._worker: _SetupWorker | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)

        title = QLabel("Akilli Konaklama Yonetim Sistemi")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        subtitle = QLabel("Uygulama ilk kez calistiriliyor")
        subtitle.setObjectName("Muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        self._info = QLabel(
            "Baslamadan once veritabani olusturulacak ve bir yonetici hesabi "
            "hazirlanacak. Bu islem birkac saniye surer.\n\n"
            "Verileriniz uygulamanin bulundugu klasorde saklanir."
        )
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        self._demo_checkbox = QCheckBox("Ornek (demo) veri olustur")
        self._demo_checkbox.setChecked(True)
        self._demo_checkbox.setToolTip(
            "40 oda, 80 rezervasyon ve 60 misafirden olusan tamamen hayali bir "
            "veri kumesi olusturur. Sistemi denemek icin onerilir; gercek "
            "kullanimda once bu veriyi temizleyin."
        )
        layout.addWidget(self._demo_checkbox)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel()
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._cancel_button = QPushButton("Cikis")
        self._cancel_button.clicked.connect(self.reject)

        self._start_button = QPushButton("Kurulumu Baslat")
        self._start_button.setObjectName("Primary")
        self._start_button.setMinimumHeight(36)
        self._start_button.setDefault(True)
        self._start_button.clicked.connect(self._start_setup)

        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._start_button)
        layout.addLayout(buttons)

    # ----------------------------------------------------------------- #
    def _start_setup(self) -> None:
        self._start_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._demo_checkbox.setEnabled(False)
        self._progress.setVisible(True)
        self._status.setVisible(True)
        self._status.setText("Kurulum basliyor...")

        self._thread = QThread(self)
        self._worker = _SetupWorker(with_demo=self._demo_checkbox.isChecked())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._status.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_finished(self, result: SetupResult) -> None:
        self._progress.setVisible(False)
        self._result = result

        if not result.success:
            self._status.setText(result.message)
            self._status.setObjectName("BadgeDanger")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
            self._cancel_button.setEnabled(True)
            self._cancel_button.setText("Kapat")
            return

        self._show_credentials(result)

    def _show_credentials(self, result: SetupResult) -> None:
        """Kurulum sonucunu ve yonetici parolasini gosterir."""
        self._info.setText("Kurulum tamamlandi.")
        self._demo_checkbox.setVisible(False)
        self._status.setVisible(False)

        layout: QVBoxLayout = self.layout()  # type: ignore[assignment]

        warning = QLabel("BU PAROLA BIR DAHA GOSTERILMEYECEK")
        warning.setObjectName("BadgeWarning")
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.insertWidget(layout.count() - 1, warning)

        credentials = QLabel(
            f"Kullanici adi:  {result.admin_username}\n" f"Parola:         {result.admin_password}"
        )
        credentials.setFont(QFont("Consolas", 11))
        credentials.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        credentials.setObjectName("Card")
        credentials.setMargin(12)
        layout.insertWidget(layout.count() - 1, credentials)

        copy_button = QPushButton("Parolayi Kopyala")
        copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(result.admin_password)
        )
        layout.insertWidget(layout.count() - 1, copy_button)

        note = QLabel("Ilk giriste parolanizi degistirmeniz istenecek.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.insertWidget(layout.count() - 1, note)

        if result.demo_created and result.demo_users:
            demo_lines = "\n".join(
                f"  {username}  /  {password}  ({role})"
                for username, password, role in result.demo_users
            )
            demo_label = QLabel(
                "Demo hesaplari (yalnizca deneme icin, gercek kullanimda silin):\n" + demo_lines
            )
            demo_label.setFont(QFont("Consolas", 9))
            demo_label.setObjectName("Muted")
            demo_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.insertWidget(layout.count() - 1, demo_label)

        if result.message:
            extra = QLabel(result.message)
            extra.setObjectName("BadgeWarning")
            extra.setWordWrap(True)
            layout.insertWidget(layout.count() - 1, extra)

        self._cancel_button.setVisible(False)
        self._start_button.setText("Devam Et")
        self._start_button.setEnabled(True)
        try:
            self._start_button.clicked.disconnect()
        except RuntimeError:  # pragma: no cover - baglanti yoksa
            pass
        self._start_button.clicked.connect(self.accept)

        self.adjustSize()

    @property
    def result_data(self) -> SetupResult | None:
        return self._result


__all__ = ["FirstRunDialog", "SetupResult"]
