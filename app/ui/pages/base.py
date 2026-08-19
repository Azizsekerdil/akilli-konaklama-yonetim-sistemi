"""Sayfa taban sinifi.

Her ekran :class:`BasePage`'den turer. Taban sinif iki sorunu cozer:

1. **Tembel yukleme** - sayfa ilk kez goruntulendiginde veri yuklenir.
   Uygulama acilisinda 12 ekranin tamami sorgu calistirsaydi baslangic
   saniyeler surerdi.
2. **Guvenli yenileme** - veri yukleme hatasi ekrani bos birakmak yerine
   anlasilir bir mesaj gosterir ve uygulama calismaya devam eder.
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.core.exceptions import HotelError
from app.core.log import get_logger
from app.ui.session import UiSession

log = get_logger(__name__)


class BasePage(QWidget):
    """Tum ekranlarin taban sinifi."""

    #: Bu sayfayi gormek icin gereken izin. ``None`` ise herkese acik.
    required_permission: str | None = None

    #: Sol menude gorunecek ad ve simge.
    title: str = ""
    icon: str = ""

    def __init__(self, ui_session: UiSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui = ui_session
        self._loaded = False

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(20, 18, 20, 18)
        self.root_layout.setSpacing(14)

        self.build()

    # ---------------- Alt siniflarin dolduracagi ----------------
    def build(self) -> None:
        """Arayuz bilesenlerini olusturur. Veri YUKLEMEZ."""

    def load_data(self) -> None:
        """Veriyi yukler. Sayfa her goruntulendiginde cagrilir."""

    # ---------------- Yasam dongusu ----------------
    def refresh(self, *, force: bool = False) -> None:
        """Veriyi yeniden yukler.

        Hata durumunda sayfa cokmez; kullaniciya anlasilir bir mesaj gosterilir
        ve ayrinti loglanir.
        """
        if self._loaded and not force:
            return
        try:
            self.load_data()
            self._loaded = True
        except HotelError as exc:
            log.warning(
                "sayfa_yuklenemedi",
                page=type(self).__name__,
                code=exc.code,
                detail=exc.detail,
            )
            self._show_load_error(exc.user_message)
        except Exception as exc:
            log.error(
                "sayfa_yukleme_hatasi",
                page=type(self).__name__,
                error=str(exc),
                exc_info=True,
            )
            self._show_load_error("Veriler yuklenirken beklenmeyen bir hata olustu.")

    def on_shown(self) -> None:
        """Sayfa goruntulendiginde cagrilir."""
        self.refresh()

    def invalidate(self) -> None:
        """Veriyi bayatlamis olarak isaretler; sonraki gosterimde yenilenir."""
        self._loaded = False

    def _show_load_error(self, message: str) -> None:
        from app.ui.widgets.common import EmptyState

        # Mevcut icerigi temizleyip hata durumunu goster.
        while self.root_layout.count():
            item = self.root_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.root_layout.addWidget(
            EmptyState(
                message,
                hint="Yenile dugmesine basarak tekrar deneyebilirsiniz.",
                icon="⚠",
                parent=self,
            )
        )


__all__ = ["BasePage"]
