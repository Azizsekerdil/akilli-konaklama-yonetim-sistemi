"""Henuz tamamlanmamis ekranlar icin durum sayfasi.

Bu sayfa **bilincli olarak durustur**: ekranin hazir olmadigini acikca
soyler, ne zaman/nasil tamamlanacagini belirtir ve kullanicinin ayni isi
su anda nasil yapabilecegini gosterir. Bos bir ekran birakmak veya
calismayan dugmeler koymak kullaniciyi yaniltir.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.pages.base import BasePage
from app.ui.session import UiSession
from app.ui.widgets.common import Card, SectionTitle


class PlaceholderPage(BasePage):
    """Tamamlanmamis modul bildirimi."""

    def __init__(
        self,
        ui_session: UiSession,
        *,
        title: str,
        description: str,
        planned_features: list[str] | None = None,
        workaround: str | None = None,
        required_permission: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        self.title = title
        self._description = description
        self._features = planned_features or []
        self._workaround = workaround
        self.required_permission = required_permission
        super().__init__(ui_session, parent)

    def build(self) -> None:
        self.root_layout.addWidget(SectionTitle(self.title))

        card = Card(parent=self)
        body: QVBoxLayout = card.body

        status = QLabel("BU MODUL HENUZ TAMAMLANMADI")
        status.setObjectName("BadgeWarning")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setMaximumWidth(280)
        body.addWidget(status)

        description = QLabel(self._description)
        description.setWordWrap(True)
        body.addWidget(description)

        if self._features:
            planned = QLabel("Planlanan ozellikler:")
            planned.setObjectName("CardTitle")
            body.addWidget(planned)
            for feature in self._features:
                item = QLabel(f"  •  {feature}")
                item.setObjectName("Muted")
                item.setWordWrap(True)
                body.addWidget(item)

        if self._workaround:
            hint_title = QLabel("Su anda ne yapabilirsiniz:")
            hint_title.setObjectName("CardTitle")
            body.addWidget(hint_title)

            hint = QLabel(self._workaround)
            hint.setWordWrap(True)
            body.addWidget(hint)

        self.root_layout.addWidget(card)
        self.root_layout.addStretch(1)


__all__ = ["PlaceholderPage"]
