"""Ayarlar ekrani: gorunum, tesis, vergi, yapay zeka ve yedekleme.

Ayarlarin iki farkli omru vardir ve ekran bunu **gizlemez**:

* **Anlik uygulanan** ayarlar - tema. Secildigi anda tum ekranlara yansir.
* **Kalici olmayan** ayarlar - yapay zeka saglayici adresleri, zaman asimi,
  sicaklik. Bunlar ``.env`` dosyasindan okunur; ekrandan yapilan degisiklik
  calisan uygulamada gecerlidir ancak yeniden baslatildiginda ``.env``
  degerine doner. Kullaniciya bu durum acikca yazilir - "kaydettim ama
  gitmis" sasirmasi, sessiz basarisizligin en yaygin bicimidir.
* **Kalici** ayarlar - vergi oranlari (veritabani) ve API anahtarlari
  (Windows Credential Manager).

API anahtari
------------
Anahtar arayuzde **hicbir zaman acik gosterilmez**. Girdi alani parola
kipindedir, kayitli deger yalnizca maskeli ozet olarak gorunur ve deger
keyring'e yazilir. Keyring kullanilamiyorsa kullanici ``.env`` dosyasina
yonlendirilir; sessizce "kaydedildi" denmez.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.core.config import ProviderName, Settings, get_settings
from app.core.exceptions import HotelError, ValidationError
from app.core.log import get_logger
from app.core.secret_store import SecretBackend, is_keyring_available, mask_secret, set_secret
from app.domain.enums import AuditAction
from app.infrastructure.backup import create_backup, list_backups, restore_backup
from app.infrastructure.db.models.billing import TaxRate
from app.infrastructure.db.models.organization import Property
from app.security.permissions import Perm
from app.ui.formatting import format_datetime, format_number
from app.ui.i18n import SUPPORTED_LANGUAGES, get_language, set_language, t
from app.ui.pages.base import BasePage
from app.ui.theme import ThemeMode, apply_theme
from app.ui.widgets.common import (
    Card,
    EmptyState,
    SectionTitle,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)

#: Geri yuklemeyi onaylamak icin yazilmasi gereken metin.
RESTORE_PHRASE = "GERI YUKLE"

#: Sayi alanlarinin artir/azalt dugmeleri icin yerel duzeltme.
#:
#: Genel stil sayfasi ``QSpinBox``/``QDoubleSpinBox`` icin yuvarlak kenar ve
#: ``padding`` tanimlar ama alt denetimleri (``up-button`` / ``down-button``)
#: hic konumlandirmaz. Sonuc: iki ok YAN YANA ve alanin sag kenarinin
#: DISINDA, yuvarlatilmis cerceveyi tasarak cizilir - kullanici bunu bozuk
#: bir bilesen olarak gorur. Asagidaki kural oklari cercevenin icine, ust ve
#: alt saga yerlestirir. Kalici cozum ``app/ui/theme.py`` icindedir; orasi
#: butun ekranlari ilgilendirdigi icin duzeltme bu ekranla sinirli tutuldu
#: (ayni gecici cozum ``app/ui/dialogs/maintenance_dialog.py`` icinde de var).
SPINBOX_BUTTONS = """
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    margin: 3px 4px 0 0;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    margin: 0 4px 3px 0;
}
"""

#: Form agirlikli sekmelerin azami genisligi. Genis ekranda bir formun 1200
#: piksele yayilmasi okunaksizdir: goz, etiket ile alan arasindaki boslugu
#: takip edemez. Tablo agirlikli sekmelere UYGULANMAZ - orada sinir yalnizca
#: sagda anlamsiz bir bos sutun birakirdi.
_FORM_MAX_WIDTH = 1000

#: Ayarlar ekraninda yapilandirilabilen saglayicilar. ``MOCK`` disaridadir:
#: yapilandirilacak bir adresi veya anahtari yoktur.
_CONFIGURABLE_PROVIDERS: tuple[ProviderName, ...] = (
    ProviderName.LMSTUDIO,
    ProviderName.NVIDIA,
    ProviderName.OPENAI,
    ProviderName.ANTHROPIC,
)


# ==========================================================================
#  Tablo satirlari - ORM nesnesi arayuze CIKMAZ
# ==========================================================================
def _format_time(value: time) -> str:
    """``14:00`` bicimi."""
    return f"{value.hour:02d}:{value.minute:02d}"


def _parse_time(text: str, label: str) -> time:
    """``SS:DD`` metnini saate cevirir.

    Gecersiz deger sessizce yok sayilmaz: kullanicinin yazdigi saatin kabul
    edilmedigini fark etmesi gerekir.
    """
    hour, _, minute = text.strip().partition(":")
    try:
        return time(int(hour), int(minute))
    except ValueError as exc:
        raise ValidationError(
            f"{label} 'SS:DD' biciminde olmalidir (or. 14:00).",
            detail=f"gecersiz saat: {text!r}",
            field="check_time",
        ) from exc


def _format_rate(value: Decimal | float | None) -> str:
    """``%20,00`` bicimi - Turkce ondalik ayiricisi ile."""
    if value is None:
        return "-"
    return f"%{format_number(float(value), decimals=2)}"


@dataclass(slots=True)
class _TaxRow:
    """Vergi orani listesi satiri."""

    tax_id: int
    code: str
    name: str
    rate_percent: Decimal
    is_included_in_price: bool
    is_default: bool
    is_active: bool


@dataclass(slots=True)
class _ProviderRow:
    """Yapay zeka saglayici listesi satiri."""

    provider: str
    name: str
    base_url: str
    chat_model: str
    key_state: str
    role: str
    status: str = "Denenmedi"


@dataclass(slots=True)
class _BackupRow:
    """Yedek dosyasi satiri."""

    path: Path
    file_name: str
    size_mb: float
    created_at: datetime


@dataclass(slots=True)
class _PropertyInfo:
    """Tesis bilgisi - duz veri."""

    property_id: int
    code: str
    name: str
    address_line: str
    city: str
    country: str
    phone: str
    email: str
    website: str
    tax_office: str
    tax_number: str
    currency: str
    star_rating: str
    check_in_time: time
    check_out_time: time


# ==========================================================================
#  Ekran
# ==========================================================================
class SettingsPage(BasePage):
    """Isletme ve uygulama ayarlari."""

    required_permission = Perm.SETTINGS_VIEW
    title = "Ayarlar"
    icon = "⚙"

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._property_info: _PropertyInfo | None = None
        self._provider_rows: list[_ProviderRow] = []

        header = QHBoxLayout()
        header.addWidget(SectionTitle(t("settings.title")))
        header.addStretch(1)
        refresh = QPushButton(t("common.refresh"))
        refresh.clicked.connect(lambda: self.refresh(force=True))
        header.addWidget(refresh)
        self.root_layout.addLayout(header)

        tabs = QTabWidget()
        # Genislik siniri yalnizca FORM sekmelerine uygulanir. Vergi ve
        # yedekleme sekmeleri bastan sona tablodur; onlarda sinir, sagda
        # gerekcesiz genis bir bos sutun birakip tabloyu daraltiyordu.
        tabs.addTab(self._scrollable(self._build_general_tab()), t("settings.general"))
        tabs.addTab(self._scrollable(self._build_tax_tab(), limit_width=False), "Vergi ve Fiyat")
        tabs.addTab(self._scrollable(self._build_ai_tab()), t("settings.ai"))
        tabs.addTab(
            self._scrollable(self._build_backup_tab(), limit_width=False),
            t("settings.backup"),
        )
        self.root_layout.addWidget(tabs, 1)

    @staticmethod
    def _scrollable(widget: QWidget, *, limit_width: bool = True) -> QScrollArea:
        """Sekme icerigini kaydirilabilir yapar.

        Kucuk ekranlarda (1366x768 dizustu, resepsiyonda yaygin) form
        alanlarinin alt kismi kirpiliyordu; kaydirma bunu onler.

        ``limit_width`` yalnizca form sekmeleri icin ``True`` olmalidir;
        bkz. :data:`_FORM_MAX_WIDTH`.
        """
        if limit_width:
            widget.setMaximumWidth(_FORM_MAX_WIDTH)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    # ---------------- Sekme: Genel ----------------
    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # --- Gorunum ---
        appearance = Card(t("settings.appearance"), self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem(t("settings.theme_light"), ThemeMode.LIGHT.value)
        self._theme_combo.addItem(t("settings.theme_dark"), ThemeMode.DARK.value)
        self._theme_combo.addItem(t("settings.theme_system"), ThemeMode.SYSTEM.value)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self._theme_combo.setMaximumWidth(260)
        form.addRow(t("settings.theme"), self._theme_combo)

        self._language_combo = QComboBox()
        for code, label in SUPPORTED_LANGUAGES.items():
            self._language_combo.addItem(label, code)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._language_combo.setMaximumWidth(260)
        form.addRow(t("settings.language"), self._language_combo)

        appearance.add_layout(form)

        theme_note = QLabel("Tema secimi aninda uygulanir.")
        theme_note.setObjectName("Muted")
        appearance.add_widget(theme_note)

        self._language_note = QLabel(
            "Dil degisikligi menuler ve etiketler icin uygulamanin yeniden "
            "baslatilmasini gerektirir."
        )
        self._language_note.setObjectName("BadgeWarning")
        self._language_note.setWordWrap(True)
        appearance.add_widget(self._language_note)

        layout.addWidget(appearance)

        # --- Tesis ---
        can_manage = self.ui.can(Perm.PROPERTY_MANAGE)
        facility = Card("Tesis Bilgileri", self)

        self._property_summary = QLabel("-")
        self._property_summary.setObjectName("Muted")
        self._property_summary.setWordWrap(True)
        facility.add_widget(self._property_summary)

        property_form = QFormLayout()
        property_form.setSpacing(8)
        property_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        property_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._property_fields: dict[str, QLineEdit] = {}
        for key, label, width in (
            ("name", "Tesis Adi", 420),
            ("phone", "Telefon", 220),
            ("email", "E-posta", 320),
            ("website", "Web Sitesi", 320),
            ("address_line", "Adres", 460),
            ("city", "Sehir", 220),
            ("tax_office", "Vergi Dairesi", 320),
            ("tax_number", "Vergi No", 220),
        ):
            field = QLineEdit()
            field.setReadOnly(not can_manage)
            field.setMaximumWidth(width)
            property_form.addRow(label, field)
            self._property_fields[key] = field

        # QTimeEdit stil sayfasinda tanimli degildir (QLineEdit/QComboBox/
        # QDateEdit/QSpinBox var, QTimeEdit yok) ve cercevesiz, farkli
        # yukseklikte cizilerek formu bozuyordu. Maskeli QLineEdit hem tema ile
        # tutarli gorunur hem de "14:00" disinda bir sey yazilmasini engeller.
        self._check_in_time = self._time_field(can_manage)
        property_form.addRow("Standart Giris Saati", self._check_in_time)

        self._check_out_time = self._time_field(can_manage)
        property_form.addRow("Standart Cikis Saati", self._check_out_time)

        facility.add_layout(property_form)

        if can_manage:
            actions = QHBoxLayout()
            actions.addStretch(1)
            save = QPushButton(t("common.save"))
            save.setObjectName("Primary")
            save.clicked.connect(self._save_property)
            actions.addWidget(save)
            facility.add_layout(actions)
        else:
            hint = QLabel("Tesis bilgilerini duzenlemek icin 'Tesis yonetimi' yetkisi gerekir.")
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            facility.add_widget(hint)

        layout.addWidget(facility)
        layout.addStretch(1)
        return page

    @staticmethod
    def _time_field(editable: bool) -> QLineEdit:
        """``SS:DD`` bicimli, tema ile uyumlu saat alani."""
        field = QLineEdit()
        field.setInputMask("00:00")
        field.setMaximumWidth(90)
        field.setReadOnly(not editable)
        return field

    # ---------------- Sekme: Vergi ----------------
    def _build_tax_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        warning = QLabel(
            "SORUMLULUK: Buradaki oranlar ornek/varsayilan degerlerdir. "
            "Gecerli mevzuata (KDV, konaklama vergisi) uygunlugundan ve "
            "guncelliginden ISLETME sorumludur. Degisiklik oncesi mali "
            "musavirinize danisin."
        )
        warning.setObjectName("BadgeWarning")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        card = Card("Vergi Oranlari", self)

        actions = QHBoxLayout()
        actions.addStretch(1)
        can_manage = self.ui.can(Perm.SETTINGS_MANAGE)

        self._tax_add_button = QPushButton(t("common.add"))
        self._tax_add_button.setObjectName("Primary")
        self._tax_add_button.clicked.connect(lambda: self._edit_tax_rate(None))
        self._tax_add_button.setEnabled(can_manage)
        actions.addWidget(self._tax_add_button)

        self._tax_edit_button = QPushButton(t("common.edit"))
        self._tax_edit_button.clicked.connect(self._edit_selected_tax_rate)
        self._tax_edit_button.setEnabled(can_manage)
        actions.addWidget(self._tax_edit_button)

        if not can_manage:
            for button in (self._tax_add_button, self._tax_edit_button):
                button.setToolTip(t("auth.no_permission"))
        card.add_layout(actions)

        self._tax_table = FilterableTableView(
            [
                Column("code", "Kod", width=110),
                Column("name", "Ad", stretch=True),
                Column("rate_percent", "Oran", formatter=_format_rate, width=90),
                Column("is_included_in_price", "Fiyata Dahil", width=120),
                Column("is_default", "Varsayilan", width=110),
                Column("is_active", "Aktif", width=80),
            ],
            parent=self,
        )
        self._tax_table.row_activated.connect(self._edit_selected_tax_rate)

        self._tax_stack = QStackedWidget()
        self._tax_stack.addWidget(self._tax_table)
        self._tax_stack.addWidget(
            EmptyState(
                "Tanimli vergi orani yok.",
                hint="'Ekle' ile KDV ve konaklama vergisi oranlarini tanimlayin.",
                icon="\U0001f9fe",
                parent=self,
            )
        )
        self._tax_stack.setMinimumHeight(240)
        card.add_widget(self._tax_stack)

        layout.addWidget(card, 1)
        return page

    # ---------------- Sekme: Yapay zeka ----------------
    def _build_ai_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # --- Saglayici listesi ---
        providers = Card("Saglayicilar", self)
        self._provider_table = FilterableTableView(
            [
                Column("name", "Saglayici", width=130),
                Column("role", "Rol", width=100),
                Column("base_url", "Adres", stretch=True),
                Column("chat_model", "Model", width=200),
                Column("key_state", "Anahtar", width=110),
                Column("status", "Durum", width=140),
            ],
            parent=self,
        )
        self._provider_table.setMinimumHeight(170)
        providers.add_widget(self._provider_table)

        test_row = QHBoxLayout()
        self._health_label = QLabel("Baglanti henuz test edilmedi.")
        self._health_label.setObjectName("Muted")
        self._health_label.setWordWrap(True)
        test_row.addWidget(self._health_label, 1)

        self._test_button = QPushButton(t("ai.test_connection"))
        self._test_button.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_button)
        providers.add_layout(test_row)

        layout.addWidget(providers)

        # --- Saglayici ayarlari ---
        can_configure = self.ui.can(Perm.AI_CONFIGURE)

        config = Card("Saglayici Ayarlari", self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._provider_combo = QComboBox()
        for provider in _CONFIGURABLE_PROVIDERS:
            self._provider_combo.addItem(provider.value, provider.value)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._provider_combo.setMaximumWidth(220)
        form.addRow(t("ai.provider"), self._provider_combo)

        self._base_url = QLineEdit()
        self._base_url.setReadOnly(not can_configure)
        self._base_url.setMinimumWidth(360)
        self._base_url.setMaximumWidth(460)
        form.addRow("Base URL", self._base_url)

        self._chat_model = QLineEdit()
        self._chat_model.setReadOnly(not can_configure)
        self._chat_model.setMinimumWidth(360)
        self._chat_model.setMaximumWidth(460)
        form.addRow(t("ai.model"), self._chat_model)

        self._timeout = QSpinBox()
        self._timeout.setRange(5, 1800)
        self._timeout.setSuffix(" sn")
        self._timeout.setReadOnly(not can_configure)
        self._timeout.setMaximumWidth(140)
        form.addRow("Zaman Asimi", self._timeout)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setDecimals(2)
        self._temperature.setReadOnly(not can_configure)
        self._temperature.setMaximumWidth(140)
        form.addRow("Sicaklik (temperature)", self._temperature)

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(64, 200_000)
        self._max_tokens.setSingleStep(256)
        self._max_tokens.setReadOnly(not can_configure)
        self._max_tokens.setMaximumWidth(140)
        form.addRow("Azami Jeton (max_tokens)", self._max_tokens)

        for spin in (self._timeout, self._temperature, self._max_tokens):
            spin.setStyleSheet(SPINBOX_BUTTONS)

        config.add_layout(form)

        self._ai_scope_note = QLabel(
            "Bu degerler calisan uygulamada hemen gecerli olur ancak KALICI DEGILDIR: "
            "uygulama yeniden baslatildiginda '.env' dosyasindaki degerlere doner. "
            "Kalici yapmak icin ilgili satiri '.env' dosyasina yazin."
        )
        self._ai_scope_note.setObjectName("BadgeWarning")
        self._ai_scope_note.setWordWrap(True)
        config.add_widget(self._ai_scope_note)

        if can_configure:
            actions = QHBoxLayout()
            actions.addStretch(1)
            apply_button = QPushButton("Uygula")
            apply_button.setObjectName("Primary")
            apply_button.clicked.connect(self._apply_ai_settings)
            actions.addWidget(apply_button)
            config.add_layout(actions)

        layout.addWidget(config)

        # --- API anahtari ---
        key_card = Card("API Anahtari", self)

        key_form = QFormLayout()
        key_form.setSpacing(8)
        key_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        key_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._current_key_label = QLabel("-")
        self._current_key_label.setObjectName("Muted")
        key_form.addRow("Kayitli Anahtar", self._current_key_label)

        self._api_key_input = QLineEdit()
        # Anahtar hicbir kosulda ekranda okunabilir olmamalidir.
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("Yeni anahtar (girildiginde keyring'e yazilir)")
        self._api_key_input.setEnabled(can_configure)
        self._api_key_input.setMinimumWidth(360)
        self._api_key_input.setMaximumWidth(460)
        key_form.addRow("Yeni Anahtar", self._api_key_input)

        key_card.add_layout(key_form)

        self._keyring_note = QLabel()
        self._keyring_note.setObjectName("Muted")
        self._keyring_note.setWordWrap(True)
        key_card.add_widget(self._keyring_note)

        if can_configure:
            key_actions = QHBoxLayout()
            key_actions.addStretch(1)
            save_key = QPushButton("Anahtari Kaydet")
            save_key.setObjectName("Primary")
            save_key.clicked.connect(self._save_api_key)
            key_actions.addWidget(save_key)
            key_card.add_layout(key_actions)
        else:
            hint = QLabel("Anahtar yonetimi icin 'Saglayici/model yapilandirma' yetkisi gerekir.")
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            key_card.add_widget(hint)

        layout.addWidget(key_card)
        layout.addStretch(1)
        return page

    # ---------------- Sekme: Yedekleme ----------------
    def _build_backup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        danger = QLabel(
            "DIKKAT - GERI YUKLEME GERI ALINAMAZ.\n"
            "Bir yedegi geri yuklemek, mevcut veritabaninin UZERINE YAZAR. "
            "Yedek alindiktan sonra girilen tum rezervasyon, tahsilat ve "
            "misafir kayitlari KAYBOLUR. Islemden once mutlaka yeni bir yedek alin."
        )
        danger.setObjectName("BadgeDanger")
        danger.setWordWrap(True)
        layout.addWidget(danger)

        card = Card("Yedekler", self)

        actions = QHBoxLayout()
        self._backup_dir_label = QLabel("-")
        self._backup_dir_label.setObjectName("Muted")
        self._backup_dir_label.setWordWrap(True)
        actions.addWidget(self._backup_dir_label, 1)

        self._create_backup_button = QPushButton("Yedek Al")
        self._create_backup_button.setObjectName("Primary")
        self._create_backup_button.clicked.connect(self._create_backup)
        self._create_backup_button.setEnabled(self.ui.can(Perm.BACKUP_RUN))
        actions.addWidget(self._create_backup_button)

        self._restore_button = QPushButton("Secili Yedegi Geri Yukle")
        self._restore_button.setObjectName("Danger")
        self._restore_button.clicked.connect(self._restore_backup)
        self._restore_button.setEnabled(self.ui.can(Perm.BACKUP_RESTORE))
        actions.addWidget(self._restore_button)

        for button in (self._create_backup_button, self._restore_button):
            if not button.isEnabled():
                button.setToolTip(t("auth.no_permission"))
        card.add_layout(actions)

        self._backup_table = FilterableTableView(
            [
                Column("file_name", "Dosya", stretch=True),
                Column(
                    "size_mb",
                    "Boyut",
                    formatter=lambda value: f"{format_number(value, decimals=2)} MB",
                    width=110,
                ),
                Column("created_at", "Tarih", formatter=format_datetime, width=160),
            ],
            parent=self,
        )
        self._backup_stack = QStackedWidget()
        self._backup_stack.addWidget(self._backup_table)
        self._backup_stack.addWidget(
            EmptyState(
                "Henuz yedek alinmamis.",
                hint="'Yedek Al' dugmesi veritabaninin tutarli bir kopyasini olusturur.",
                icon="\U0001f4be",
                parent=self,
            )
        )
        self._backup_stack.setMinimumHeight(240)
        card.add_widget(self._backup_stack)

        layout.addWidget(card, 1)
        return page

    # ----------------------------------------------------------------- #
    #  Veri yukleme
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        settings = get_settings()

        self._load_appearance(settings.theme)
        self._load_property()
        self._load_tax_rates()
        self._load_ai(settings)
        self._load_backups()

    def _load_appearance(self, theme: str) -> None:
        # Programatik doldurma sinyal uretmemelidir; aksi halde ekran her
        # acildiginda tema yeniden uygulanir ve kullanicinin calisma sirasinda
        # yaptigi secim ezilir.
        self._theme_combo.blockSignals(True)
        index = self._theme_combo.findData(theme)
        self._theme_combo.setCurrentIndex(index if index >= 0 else 1)
        self._theme_combo.blockSignals(False)

        self._language_combo.blockSignals(True)
        index = self._language_combo.findData(get_language())
        self._language_combo.setCurrentIndex(max(index, 0))
        self._language_combo.blockSignals(False)

    def _load_property(self) -> None:
        with self.ui.service_context(commit=False) as ctx:
            hotel = ctx.session.get(Property, ctx.require_property())
            if hotel is None:  # pragma: no cover - tesis silinmis olabilir
                self._property_info = None
                return
            info = _PropertyInfo(
                property_id=hotel.id,
                code=hotel.code,
                name=hotel.name,
                address_line=hotel.address_line or "",
                city=hotel.city or "",
                country=hotel.country or "",
                phone=hotel.phone or "",
                email=hotel.email or "",
                website=hotel.website or "",
                tax_office=hotel.tax_office or "",
                tax_number=hotel.tax_number or "",
                currency=hotel.default_currency.value,
                star_rating=str(hotel.star_rating) if hotel.star_rating else "-",
                check_in_time=hotel.check_in_time,
                check_out_time=hotel.check_out_time,
            )

        self._property_info = info
        self._property_summary.setText(
            f"Kod: {info.code}  -  {info.star_rating} yildiz  -  "
            f"Para birimi: {info.currency}  -  {info.city or 'sehir belirtilmemis'}"
        )
        for key, field in self._property_fields.items():
            field.setText(str(getattr(info, key, "") or ""))
            # ``setText`` imleci sona birakir; alandan uzun bir deger (adres,
            # web sitesi) bastan kirpilmis gorunurdu.
            field.setCursorPosition(0)
        self._check_in_time.setText(_format_time(info.check_in_time))
        self._check_out_time.setText(_format_time(info.check_out_time))

    def _load_tax_rates(self) -> None:
        with self.ui.service_context(commit=False) as ctx:
            rows = ctx.session.scalars(
                select(TaxRate)
                .where(TaxRate.property_id == ctx.require_property())
                .order_by(TaxRate.code)
            ).all()
            data = [
                _TaxRow(
                    tax_id=row.id,
                    code=row.code,
                    name=row.name,
                    rate_percent=row.rate_percent,
                    is_included_in_price=row.is_included_in_price,
                    is_default=row.is_default,
                    is_active=row.is_active,
                )
                for row in rows
            ]

        self._tax_table.set_rows(data)
        # Siralama acikca verilir; aksi halde tablo ilk sutunda AZALAN
        # siralamayla acilir ve liste rastgele gorunur.
        self._tax_table.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._tax_stack.setCurrentIndex(0 if data else 1)

    def _load_ai(self, settings: Settings) -> None:
        ai = settings.ai
        roles = {ai.primary_provider: "Birincil"}
        if ai.fallback_provider is not None:
            roles.setdefault(ai.fallback_provider, "Yedek")

        rows: list[_ProviderRow] = []
        for provider in _CONFIGURABLE_PROVIDERS:
            provider_settings = ai.provider_settings(provider)
            if provider_settings is None:  # pragma: no cover - katalog disi
                continue
            rows.append(
                _ProviderRow(
                    provider=provider.value,
                    name=provider.value,
                    base_url=provider_settings.base_url,
                    chat_model=provider_settings.chat_model or "(varsayilan)",
                    key_state="Kayitli" if provider_settings.has_api_key else "Yok",
                    role=roles.get(provider, "-"),
                )
            )
        self._provider_rows = rows
        self._provider_table.set_rows(rows)
        self._provider_table.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self._timeout.setValue(ai.default_timeout)
        self._temperature.setValue(ai.default_temperature)
        self._max_tokens.setValue(ai.default_max_tokens)

        # Yapay zeka kapaliyken saglayici cagrilari hic yapilmaz; test dugmesini
        # etkin birakmak, calismayacak bir islemi vaat etmek olurdu.
        if ai.enabled:
            self._test_button.setEnabled(True)
            self._test_button.setToolTip("")
            self._health_label.setText("Baglanti henuz test edilmedi.")
        else:
            self._test_button.setEnabled(False)
            self._test_button.setToolTip("Yapay zeka kapali.")
            self._health_label.setText(
                "Yapay zeka kapali (HOTEL_AI_ENABLED=false). Saglayici cagrilari yapilmaz."
            )

        self._on_provider_changed()

        if is_keyring_available():
            self._keyring_note.setText(
                "Anahtar Windows Credential Manager'a yazilir; veritabaninda "
                "veya ayar dosyalarinda saklanmaz."
            )
        else:
            self._keyring_note.setText(
                "Bu sistemde anahtar deposu (keyring) kullanilamiyor. Anahtari "
                "proje kokundeki '.env' dosyasina elle ekleyin."
            )

    def _load_backups(self) -> None:
        settings = get_settings()
        self._backup_dir_label.setText(f"Yedek klasoru: {settings.backup.directory}")

        rows: list[_BackupRow] = []
        for path in list_backups():
            stat = path.stat()
            rows.append(
                _BackupRow(
                    path=path,
                    file_name=path.name,
                    size_mb=round(stat.st_size / (1024 * 1024), 2),
                    # Dosya zaman damgasi UTC olarak okunup yerel saate cevrilir;
                    # tz verilmezse isletim sistemi yerel ayarina gore belirsiz
                    # (naive) bir deger uretilirdi.
                    created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).astimezone(),
                )
            )

        self._backup_table.set_rows(rows)
        self._backup_stack.setCurrentIndex(0 if rows else 1)

    # ----------------------------------------------------------------- #
    #  Genel sekmesi eylemleri
    # ----------------------------------------------------------------- #
    def _on_theme_changed(self, _index: int) -> None:
        """Temayi aninda uygular."""
        mode = ThemeMode(self._theme_combo.currentData())
        app = QApplication.instance()
        if app is None:  # pragma: no cover - QApplication olmadan cagrilmaz
            return
        apply_theme(app, mode)
        show_toast(self, "Tema uygulandi.", ToastLevel.SUCCESS)

    def _on_language_changed(self, _index: int) -> None:
        code = self._language_combo.currentData()
        set_language(code)
        self._language_note.setText(
            f"Dil '{SUPPORTED_LANGUAGES.get(code, code)}' olarak ayarlandi. "
            "Acik ekranlarin tamamen cevrilmesi icin uygulamayi yeniden baslatin."
        )
        show_toast(self, "Dil ayari degisti. Yeniden baslatma gerekir.", ToastLevel.WARNING)

    def _save_property(self) -> None:
        if self._property_info is None:
            return

        name = self._property_fields["name"].text().strip()
        if not name:
            show_error(
                self,
                ValidationError("Tesis adi bos birakilamaz.", field="name"),
                title=t("common.warning"),
            )
            return

        try:
            with self.ui.service_context() as ctx:
                ctx.require(Perm.PROPERTY_MANAGE)
                hotel = ctx.session.get(Property, self._property_info.property_id)
                if hotel is None:  # pragma: no cover
                    raise ValidationError("Tesis kaydi bulunamadi.")

                before = {"name": hotel.name, "city": hotel.city, "phone": hotel.phone}

                hotel.name = name
                hotel.phone = self._property_fields["phone"].text().strip() or None
                hotel.email = self._property_fields["email"].text().strip() or None
                hotel.website = self._property_fields["website"].text().strip() or None
                hotel.address_line = self._property_fields["address_line"].text().strip() or None
                hotel.city = self._property_fields["city"].text().strip() or None
                hotel.tax_office = self._property_fields["tax_office"].text().strip() or None
                hotel.tax_number = self._property_fields["tax_number"].text().strip() or None
                hotel.check_in_time = _parse_time(
                    self._check_in_time.text(), "Standart giris saati"
                )
                hotel.check_out_time = _parse_time(
                    self._check_out_time.text(), "Standart cikis saati"
                )

                ctx.audit(
                    AuditAction.SETTINGS_CHANGED,
                    f"Tesis bilgileri guncellendi: {hotel.name}",
                    entity_type="Property",
                    entity_id=hotel.id,
                    before=before,
                    after={"name": hotel.name, "city": hotel.city, "phone": hotel.phone},
                )
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, "Tesis bilgileri kaydedildi.", ToastLevel.SUCCESS)
        self.refresh(force=True)

    # ----------------------------------------------------------------- #
    #  Vergi sekmesi eylemleri
    # ----------------------------------------------------------------- #
    def _edit_selected_tax_rate(self, *_args: object) -> None:
        row = self._tax_table.selected_row()
        if isinstance(row, _TaxRow):
            self._edit_tax_rate(row)

    def _edit_tax_rate(self, row: _TaxRow | None) -> None:
        if not self.ui.can(Perm.SETTINGS_MANAGE):
            return

        dialog = _TaxRateDialog(row, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.values
        try:
            with self.ui.service_context() as ctx:
                ctx.require(Perm.SETTINGS_MANAGE)
                property_id = ctx.require_property()

                duplicate = ctx.session.scalars(
                    select(TaxRate).where(
                        TaxRate.property_id == property_id,
                        TaxRate.code == values["code"],
                    )
                ).one_or_none()
                if duplicate is not None and (row is None or duplicate.id != row.tax_id):
                    raise ValidationError(
                        f"'{values['code']}' kodlu bir vergi orani zaten var.",
                        field="code",
                    )

                if row is None:
                    record = TaxRate(property_id=property_id, code=values["code"])
                    ctx.session.add(record)
                else:
                    record = ctx.session.get(TaxRate, row.tax_id)
                    if record is None:  # pragma: no cover - silinmis olabilir
                        raise ValidationError("Vergi orani kaydi bulunamadi.")
                    record.code = values["code"]

                before = {"code": record.code, "rate_percent": str(record.rate_percent or "")}
                record.name = values["name"]
                record.rate_percent = values["rate_percent"]
                record.is_included_in_price = values["is_included_in_price"]
                record.is_default = values["is_default"]
                record.is_active = values["is_active"]
                ctx.session.flush()

                if record.is_default:
                    # Varsayilan tek olmalidir; aksi halde ucret islerken hangi
                    # oranin secilecegi belirsiz kalir.
                    others = ctx.session.scalars(
                        select(TaxRate).where(
                            TaxRate.property_id == property_id,
                            TaxRate.id != record.id,
                            TaxRate.is_default.is_(True),
                        )
                    ).all()
                    for other in others:
                        other.is_default = False

                ctx.audit(
                    AuditAction.SETTINGS_CHANGED,
                    f"Vergi orani kaydedildi: {record.code} (%{record.rate_percent})",
                    entity_type="TaxRate",
                    entity_id=record.id,
                    before=before,
                    after={"code": record.code, "rate_percent": str(record.rate_percent)},
                )
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, "Vergi orani kaydedildi.", ToastLevel.SUCCESS)
        self._load_tax_rates()

    # ----------------------------------------------------------------- #
    #  Yapay zeka sekmesi eylemleri
    # ----------------------------------------------------------------- #
    def _on_provider_changed(self, *_args: object) -> None:
        """Secili saglayicinin adres, model ve anahtar ozetini gosterir."""
        selected = self._provider_combo.currentData()
        provider_settings = get_settings().ai.provider_settings(ProviderName(selected))
        if provider_settings is None:  # pragma: no cover
            return

        self._base_url.setText(provider_settings.base_url)
        self._chat_model.setText(provider_settings.chat_model)
        self._api_key_input.clear()
        # Anahtarin kendisi degil, yalnizca maskeli ozeti gosterilir.
        self._current_key_label.setText(mask_secret(provider_settings.resolve_api_key()))

    def _apply_ai_settings(self) -> None:
        selected = ProviderName(self._provider_combo.currentData())
        settings = get_settings()
        provider_settings = settings.ai.provider_settings(selected)
        if provider_settings is None:  # pragma: no cover
            return

        provider_settings.base_url = self._base_url.text().strip()
        provider_settings.chat_model = self._chat_model.text().strip()
        settings.ai.default_timeout = self._timeout.value()
        settings.ai.default_temperature = self._temperature.value()
        settings.ai.default_max_tokens = self._max_tokens.value()

        # Kayit onbellege alinmis saglayici ornekleri tutar; eski adresle
        # calismaya devam etmemesi icin sifirlanir.
        from app.ai.registry import reset_registry

        reset_registry()

        prefix = f"HOTEL_{selected.value.upper()}_"
        self._ai_scope_note.setText(
            "Degisiklikler uygulandi (calisan oturum icin). Kalici olmasi icin "
            f"'.env' dosyasina ekleyin:\n{prefix}BASE_URL={provider_settings.base_url}\n"
            f"{prefix}CHAT_MODEL={provider_settings.chat_model}"
        )
        log.info("ai_ayarlari_uygulandi", provider=selected.value)
        show_toast(self, "Yapay zeka ayarlari uygulandi.", ToastLevel.SUCCESS)
        self._load_ai(settings)

    def _save_api_key(self) -> None:
        value = self._api_key_input.text().strip()
        if not value:
            show_error(
                self,
                ValidationError("Anahtar alani bos olamaz.", field="api_key"),
                title=t("common.warning"),
            )
            return

        selected = ProviderName(self._provider_combo.currentData())
        secret_name = f"{selected.value}_api_key"

        try:
            backend = set_secret(secret_name, value)
        except ValueError as exc:  # pragma: no cover - bos deger yukarida elendi
            show_error(self, ValidationError(str(exc), field="api_key"))
            return
        finally:
            # Deger bellekte gereksiz yere durmamalidir.
            self._api_key_input.clear()

        if backend is SecretBackend.KEYRING:
            show_toast(self, "Anahtar guvenli depoya kaydedildi.", ToastLevel.SUCCESS)
        else:
            self._keyring_note.setText(
                "Anahtar deposu kullanilamadi; anahtar KAYDEDILMEDI. "
                f"'.env' dosyasina su satiri ekleyin: HOTEL_{secret_name.upper()}=..."
            )
            show_toast(self, "Anahtar kaydedilemedi - '.env' kullanin.", ToastLevel.WARNING)

        from app.ai.registry import reset_registry

        reset_registry()
        self._load_ai(get_settings())

    def _test_connection(self) -> None:
        """Yapilandirilmis saglayicilarin durumunu yoklar.

        Saglik kontrolu ag cagrisi yapar ve birkac saniye surebilir; bu yuzden
        ekran acilirken degil, yalnizca kullanici istediginde calisir.
        """
        self._health_label.setText("Baglanti deneniyor...")
        QApplication.processEvents()

        try:
            from app.ai.registry import get_registry

            report = get_registry().health_report()
        except Exception as exc:
            log.warning("ai_saglik_kontrolu_basarisiz", error=str(exc))
            self._health_label.setText(
                "Saglik kontrolu calistirilamadi. Yapay zeka ayarlarini kontrol edin."
            )
            return

        summary: list[str] = []
        for row in self._provider_rows:
            status = report.get(row.provider)
            if status is None:
                row.status = "Yapilandirilmamis"
                continue
            row.status = status.label
            summary.append(f"{row.name}: {status.label}")
        self._provider_table.set_rows(list(self._provider_rows))

        self._health_label.setText(
            " | ".join(summary) if summary else "Yapilandirilmis saglayici bulunamadi."
        )

    # ----------------------------------------------------------------- #
    #  Yedekleme sekmesi eylemleri
    # ----------------------------------------------------------------- #
    def _create_backup(self) -> None:
        if not self.ui.can(Perm.BACKUP_RUN):
            return
        try:
            result = create_backup()
        except HotelError as exc:
            show_error(self, exc)
            return

        with self.ui.service_context() as ctx:
            ctx.audit(
                AuditAction.BACKUP,
                f"Veritabani yedegi alindi: {result.path.name} ({result.size_mb} MB)",
            )

        show_toast(
            self,
            f"Yedek alindi: {result.path.name} ({format_number(result.size_mb, decimals=2)} MB)",
            ToastLevel.SUCCESS,
        )
        self._load_backups()

    def _restore_backup(self) -> None:
        if not self.ui.can(Perm.BACKUP_RESTORE):
            return

        row = self._backup_table.selected_row()
        if not isinstance(row, _BackupRow):
            show_toast(self, "Once listeden bir yedek secin.", ToastLevel.WARNING)
            return

        if not confirm(
            self,
            f"'{row.file_name}' yedegi geri yuklensin mi?",
            detail=(
                "MEVCUT VERITABANININ UZERINE YAZILIR VE ISLEM GERI ALINAMAZ.\n"
                "Yedek tarihinden sonraki tum kayitlar kaybolur."
            ),
            title="Geri Yukleme",
            dangerous=True,
        ):
            return

        phrase = _PhraseDialog(RESTORE_PHRASE, self)
        if phrase.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            target = restore_backup(row.path, confirm=True)
        except HotelError as exc:
            show_error(self, exc)
            return

        with self.ui.service_context() as ctx:
            ctx.audit(
                AuditAction.RESTORE,
                f"Yedek geri yuklendi: {row.file_name}",
            )

        log.warning("yedek_geri_yuklendi_arayuz", source=row.file_name, target=str(target))
        show_toast(
            self,
            "Geri yukleme tamamlandi. Uygulamayi kapatip yeniden baslatin.",
            ToastLevel.WARNING,
            duration_ms=8000,
        )


# ==========================================================================
#  Yardimci diyaloglar
# ==========================================================================
class _TaxRateDialog(QDialog):
    """Vergi orani ekleme / duzenleme."""

    def __init__(self, row: _TaxRow | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vergi Orani Duzenle" if row else "Yeni Vergi Orani")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self._code = QLineEdit(row.code if row else "")
        self._code.setMaxLength(30)
        self._code.setPlaceholderText("Or. KDV10")
        form.addRow("Kod *", self._code)

        self._name = QLineEdit(row.name if row else "")
        self._name.setMaxLength(120)
        form.addRow("Ad *", self._name)

        self._rate = QDoubleSpinBox()
        self._rate.setRange(0.0, 100.0)
        self._rate.setDecimals(2)
        self._rate.setSuffix(" %")
        self._rate.setValue(float(row.rate_percent) if row else 20.0)
        self._rate.setStyleSheet(SPINBOX_BUTTONS)
        form.addRow("Oran", self._rate)

        self._included = QCheckBox("Fiyat vergi dahildir")
        self._included.setChecked(row.is_included_in_price if row else True)
        form.addRow("", self._included)

        self._default = QCheckBox("Varsayilan oran")
        self._default.setChecked(row.is_default if row else False)
        form.addRow("", self._default)

        self._active = QCheckBox("Aktif")
        self._active.setChecked(row.is_active if row else True)
        form.addRow("", self._active)

        layout.addLayout(form)

        note = QLabel(
            "Oranin mevzuata uygunlugundan isletme sorumludur. Degisiklik "
            "gecmise donuk faturalari etkilemez."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._warning = QLabel("Kod ve ad alanlari zorunludur.")
        self._warning.setObjectName("BadgeWarning")
        self._warning.setVisible(False)
        layout.addWidget(self._warning)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton(t("common.save"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _accept(self) -> None:
        if not self._code.text().strip() or not self._name.text().strip():
            self._warning.setVisible(True)
            return
        self.accept()

    @property
    def values(self) -> dict[str, object]:
        return {
            "code": self._code.text().strip().upper(),
            "name": self._name.text().strip(),
            # Para/oran degerleri Decimal olarak saklanir; float ile yuvarlama
            # hatasi birikirdi.
            "rate_percent": Decimal(str(round(self._rate.value(), 2))),
            "is_included_in_price": self._included.isChecked(),
            "is_default": self._default.isChecked(),
            "is_active": self._active.isChecked(),
        }


class _PhraseDialog(QDialog):
    """Yikici islemler icin metin yazdirarak onay alan diyalog.

    "Evet/Hayir" kutusu refleksle onaylanabilir; belirli bir metni yazmak
    kullaniciyi ne yaptigini okumaya zorlar.
    """

    def __init__(self, phrase: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phrase = phrase
        self.setWindowTitle("Son Onay")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        warning = QLabel(
            "BU ISLEM GERI ALINAMAZ.\n"
            f"Devam etmek icin asagiya buyuk harflerle '{phrase}' yazin."
        )
        warning.setObjectName("BadgeDanger")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self._input = QLineEdit()
        self._input.setPlaceholderText(phrase)
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self._confirm_button = QPushButton("Geri Yukle")
        self._confirm_button.setObjectName("Danger")
        self._confirm_button.setEnabled(False)
        self._confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self._confirm_button)
        layout.addLayout(buttons)

    def _on_text_changed(self, text: str) -> None:
        self._confirm_button.setEnabled(text.strip() == self._phrase)


__all__ = ["RESTORE_PHRASE", "SettingsPage"]
