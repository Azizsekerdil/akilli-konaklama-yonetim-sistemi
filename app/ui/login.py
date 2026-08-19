"""Giris ekrani ve parola degistirme diyalogu."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import AuthenticationError, HotelError, ValidationError
from app.core.log import get_logger
from app.infrastructure.db.models.security import User
from app.security import auth
from app.ui.i18n import t
from app.ui.widgets.common import show_error

log = get_logger(__name__)


class LoginDialog(QDialog):
    """Kullanici girisi.

    Guvenlik notu: hatali giris denemelerinde ekranda **her zaman ayni**
    mesaj gosterilir ("Kullanici adi veya parola hatali"). Kullanicinin var
    olup olmadigi bilgisi sizdirilmaz - bu, kullanici adi listesi cikarmayi
    (user enumeration) onler.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("auth.login"))
        self.setMinimumWidth(400)
        self.setModal(True)

        self._session_token: str | None = None
        self._user: User | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)

        # --- Baslik ---
        title = QLabel(t("app.name"))
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        subtitle = QLabel("Devam etmek icin giris yapin")
        subtitle.setObjectName("Muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        # --- Form ---
        form = QFormLayout()
        form.setSpacing(10)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("admin")
        self.username_input.setMinimumHeight(34)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMinimumHeight(34)

        form.addRow(t("auth.username"), self.username_input)
        form.addRow(t("auth.password"), self.password_input)
        layout.addLayout(form)

        self.remember_checkbox = QCheckBox(t("auth.remember"))
        self.remember_checkbox.setToolTip(
            "Kullanici adiniz hatirlanir. Parola HICBIR ZAMAN saklanmaz."
        )
        layout.addWidget(self.remember_checkbox)

        # --- Hata alani ---
        self.error_label = QLabel()
        self.error_label.setObjectName("BadgeDanger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # --- Dugmeler ---
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton(t("common.cancel"))
        self.login_button = QPushButton(t("auth.login"))
        self.login_button.setObjectName("Primary")
        self.login_button.setMinimumHeight(36)
        self.login_button.setDefault(True)

        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.login_button)
        layout.addLayout(buttons)

        self.login_button.clicked.connect(self._attempt_login)
        self.cancel_button.clicked.connect(self.reject)

        self.username_input.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt imzasi
        """Enter ile giris; Esc ile iptal."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._attempt_login()
            return
        super().keyPressEvent(event)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _attempt_login(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            self._show_error("Kullanici adi ve parola giriniz.")
            return

        self.login_button.setEnabled(False)
        self.login_button.setText(t("common.loading"))

        try:
            from app.infrastructure.db.session import session_scope

            with session_scope(commit=False) as session:
                result = auth.authenticate(session, username, password)
                self._session_token = result.token
                self._user = result.user

            log.info("arayuz_giris_basarili", username=username)
            self.accept()

        except AuthenticationError as exc:
            # Kullanici sayimini onlemek icin ayrintiya girilmez.
            self._show_error(exc.user_message)
            self.password_input.clear()
            self.password_input.setFocus()
        except HotelError as exc:
            show_error(self, exc)
        finally:
            self.login_button.setEnabled(True)
            self.login_button.setText(t("auth.login"))

    @property
    def session_token(self) -> str | None:
        return self._session_token

    @property
    def user(self) -> User | None:
        return self._user


class ChangePasswordDialog(QDialog):
    """Parola degistirme."""

    def __init__(
        self,
        user: User,
        *,
        forced: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("auth.change_password"))
        self.setMinimumWidth(420)
        self.setModal(True)
        self._user = user
        self._forced = forced

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        if forced:
            notice = QLabel("Guvenlik nedeniyle ilk giriste parolanizi degistirmeniz gerekiyor.")
            notice.setObjectName("BadgeWarning")
            notice.setWordWrap(True)
            layout.addWidget(notice)
            # Zorunlu degisimde kapatma dugmesi kaldirilir.
            self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        form = QFormLayout()
        form.setSpacing(10)

        self.current_input = QLineEdit()
        self.current_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_input = QLineEdit()
        self.new_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.repeat_input = QLineEdit()
        self.repeat_input.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("Mevcut parola", self.current_input)
        form.addRow("Yeni parola", self.new_input)
        form.addRow("Yeni parola (tekrar)", self.repeat_input)
        layout.addLayout(form)

        rules = QLabel(
            "En az 10 karakter, en az bir harf ve bir rakam icermeli; "
            "yaygin parolalar kabul edilmez."
        )
        rules.setObjectName("Muted")
        rules.setWordWrap(True)
        layout.addWidget(rules)

        self.error_label = QLabel()
        self.error_label.setObjectName("BadgeDanger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        if not forced:
            cancel = QPushButton(t("common.cancel"))
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)

        save = QPushButton(t("common.save"))
        save.setObjectName("Primary")
        save.setMinimumHeight(34)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        current = self.current_input.text()
        new_password = self.new_input.text()
        repeat = self.repeat_input.text()

        if new_password != repeat:
            self.error_label.setText("Yeni parolalar birbiriyle uyusmuyor.")
            self.error_label.setVisible(True)
            return

        try:
            from app.infrastructure.db.session import session_scope

            with session_scope(commit=False) as session:
                merged = session.merge(self._user)
                auth.change_password(
                    session,
                    merged,
                    current_password=current,
                    new_password=new_password,
                )
            self.accept()
        except (AuthenticationError, ValidationError) as exc:
            self.error_label.setText(exc.user_message)
            self.error_label.setVisible(True)
        except HotelError as exc:
            show_error(self, exc)

    def reject(self) -> None:
        """Zorunlu degisimde iptal edilemez."""
        if self._forced:
            return
        super().reject()


__all__ = ["ChangePasswordDialog", "LoginDialog"]
