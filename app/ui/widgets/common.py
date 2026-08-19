"""Ortak arayuz bilesenleri: kart, KPI karti, rozet, arama kutusu, bildirim.

Bu bilesenler **sabit renk kodu icermez**; renkler
:mod:`app.ui.theme` stil sayfasindan nesne adi (``objectName``) uzerinden
gelir. Boylece tema degistiginde tum ekranlar tutarli sekilde degisir.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import HotelError
from app.ui.i18n import t


class Card(QFrame):
    """Golgeli/cerceveli icerik karti."""

    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)

        if title:
            label = QLabel(title.upper())
            label.setObjectName("CardTitle")
            self._layout.addWidget(label)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class KpiCard(QFrame):
    """Tek bir olcutu gosteren kart: baslik, buyuk deger, degisim bilgisi.

    Degisim (delta) gostergesi renk **ve** ok isaretiyle birlikte verilir;
    renk korlugu olan kullanicilar icin renk tek basina bilgi tasimaz.
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        value: str = "-",
        *,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.setMinimumWidth(170)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self._title = QLabel(title.upper())
        self._title.setObjectName("CardTitle")
        self._title.setWordWrap(True)

        self._value = QLabel(value)
        self._value.setObjectName("KpiValue")

        self._delta = QLabel(subtitle or "")
        self._delta.setObjectName("KpiDelta")
        self._delta.setVisible(bool(subtitle))

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._delta)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_delta(self, text: str, *, direction: int = 0) -> None:
        """Degisim bilgisini ayarlar.

        Parameters
        ----------
        direction:
            +1 artis, -1 azalis, 0 notr. Ok isareti buradan turetilir.
        """
        arrow = {1: "▲ ", -1: "▼ ", 0: ""}[max(-1, min(1, direction))]
        self._delta.setText(f"{arrow}{text}")
        self._delta.setVisible(bool(text))

        role = {1: "BadgeSuccess", -1: "BadgeDanger", 0: "Muted"}[max(-1, min(1, direction))]
        self._delta.setObjectName("KpiDelta" if role == "Muted" else role)
        self._delta.style().unpolish(self._delta)
        self._delta.style().polish(self._delta)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt imzasi
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class StatusBadge(QLabel):
    """Durum rozeti - renk **ve** metin birlikte.

    Renk tek basina anlam tasimaz; rozet her zaman okunabilir bir etiket
    gosterir (erisilebilirlik gerekliligi).
    """

    #: Ortak (ClassVar) esleme: ornek basina kopyalanmaz. ``ClassVar`` isareti
    #: olmadan bu sozluk degistirilebilir bir ornek varsayilani gibi gorunur ve
    #: bir ornekten yapilan degisiklik tum rozetleri etkilerdi.
    LEVELS: ClassVar[dict[str, str]] = {
        "success": "BadgeSuccess",
        "warning": "BadgeWarning",
        "danger": "BadgeDanger",
        "info": "BadgeInfo",
    }

    def __init__(self, text: str, level: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName(self.LEVELS.get(level, "BadgeInfo"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)

    def set_status(self, text: str, level: str = "info") -> None:
        self.setText(text)
        self.setObjectName(self.LEVELS.get(level, "BadgeInfo"))
        self.style().unpolish(self)
        self.style().polish(self)


class AiBadge(QLabel):
    """ "AI tarafindan olusturuldu" rozeti.

    Yapay zeka tarafindan uretilen HER icerigin yaninda gorunmelidir. Bu bir
    urun gereksinimidir: kullanici hangi bilginin model ciktisi oldugunu her
    zaman ayirt edebilmelidir.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(t("ai.generated_badge"), parent)
        self.setObjectName("AiBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.setToolTip(t("ai.verify_notice"))


class SectionTitle(QLabel):
    """Ekran basligi."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


class SearchBox(QLineEdit):
    """Gecikmeli arama kutusu.

    Her tus vurusunda sorgu calistirmak, buyuk tablolarda arayuzu kilitler.
    Bu bilesen son tus vurusundan ``delay_ms`` sonra tek bir sinyal yayar.
    """

    search_triggered = Signal(str)

    def __init__(
        self,
        placeholder: str | None = None,
        *,
        delay_ms: int = 300,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder or t("common.search"))
        self.setClearButtonEnabled(True)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._emit_search)
        self.textChanged.connect(lambda _: self._timer.start())

    def _emit_search(self) -> None:
        self.search_triggered.emit(self.text().strip())


class EmptyState(QWidget):
    """Veri olmadiginda gosterilen bilgilendirme.

    Bos bir tablo yerine ne yapilmasi gerektigini soyleyen bir mesaj
    gostermek, kullanicinin "sistem bozuk mu?" diye dusunmesini onler.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        hint: str | None = None,
        icon: str = "\U0001f4c4",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon_label = QLabel(icon)
        icon_font = QFont()
        icon_font.setPointSize(32)
        icon_label.setFont(icon_font)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_label = QLabel(message or t("common.no_data"))
        text_label.setObjectName("Muted")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(icon_label)
        layout.addWidget(text_label)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("Muted")
            hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)


class ToastLevel(str, Enum):
    """Bildirim seviyesi."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "danger"


class Toast(QLabel):
    """Kisa sureli, ekranin ustunde beliren bildirim."""

    def __init__(self, text: str, level: ToastLevel, parent: QWidget) -> None:
        super().__init__(text, parent)
        self.setObjectName(StatusBadge.LEVELS.get(level.value, "BadgeInfo"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.adjustSize()

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.98)

    def show_for(self, milliseconds: int = 3000) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.adjustSize()
            x = max((parent.width() - self.width()) // 2, 8)
            self.move(x, 18)
        self.show()
        self.raise_()
        QTimer.singleShot(milliseconds, self.close)


def show_toast(
    parent: QWidget,
    message: str,
    level: ToastLevel = ToastLevel.INFO,
    *,
    duration_ms: int = 3000,
) -> None:
    """Kisa bildirim gosterir (islem basarili, kaydedildi vb.)."""
    Toast(message, level, parent).show_for(duration_ms)


def show_error(parent: QWidget | None, error: Exception, *, title: str | None = None) -> None:
    """Hatayi kullaniciya **guvenli** bicimde gosterir.

    :class:`~app.core.exceptions.HotelError` icin yalnizca ``user_message``
    ve varsa cozum onerisi gosterilir; teknik ayrinti (``detail``, yigin izi)
    yalnizca loga yazilir. Boylece dosya yollari, SQL parcalari veya baglanti
    dizgeleri son kullaniciya sizmaz.
    """
    from app.core.log import get_logger

    log = get_logger(__name__)

    if isinstance(error, HotelError):
        message = error.user_message
        remedy = error.context.get("cozum") or getattr(error, "remedy", None)
        log.warning(
            "arayuz_hatasi",
            code=error.code,
            detail=error.detail,
            **{k: v for k, v in error.context.items() if k != "cozum"},
        )
    else:
        message = "Beklenmeyen bir hata olustu."
        remedy = "Ayrinti icin logs/error.log dosyasina bakabilirsiniz."
        log.error("beklenmeyen_arayuz_hatasi", error=str(error), exc_info=True)

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title or t("common.error"))
    box.setText(message)
    if remedy:
        box.setInformativeText(str(remedy))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def confirm(
    parent: QWidget | None,
    message: str,
    *,
    title: str | None = None,
    detail: str | None = None,
    dangerous: bool = False,
) -> bool:
    """Onay kutusu gosterir; kullanici onaylarsa ``True`` doner.

    ``dangerous=True`` ise varsayilan dugme **Hayir**'dir; boylece Enter'a
    basan kullanici yikici bir islemi kazara onaylamaz.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question if not dangerous else QMessageBox.Icon.Warning)
    box.setWindowTitle(title or t("common.confirm"))
    box.setText(message)
    if detail:
        box.setInformativeText(detail)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(
        QMessageBox.StandardButton.No if dangerous else QMessageBox.StandardButton.Yes
    )
    box.button(QMessageBox.StandardButton.Yes).setText(t("common.yes"))
    box.button(QMessageBox.StandardButton.No).setText(t("common.no"))
    return box.exec() == QMessageBox.StandardButton.Yes


def horizontal_spacer() -> QWidget:
    """Yatay bosluk dolgusu."""
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return widget


def row(*widgets: QWidget, spacing: int = 8) -> QHBoxLayout:
    """Verilen bilesenleri yatay yerlesime koyar."""
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


__all__ = [
    "AiBadge",
    "Card",
    "EmptyState",
    "KpiCard",
    "SearchBox",
    "SectionTitle",
    "StatusBadge",
    "Toast",
    "ToastLevel",
    "confirm",
    "horizontal_spacer",
    "row",
    "show_error",
    "show_toast",
]
