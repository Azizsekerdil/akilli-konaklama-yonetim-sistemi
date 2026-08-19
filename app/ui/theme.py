"""Uygulama temasi: renk paleti ve stil sayfasi.

Tasarim ilkeleri
----------------
* **Iki tema**: acik ve koyu. Renkler tek bir yerde tanimlanir; bilesenler
  sabit renk kodu icermez.
* **Erisilebilirlik**: metin/arka plan kontrast oranlari WCAG AA esigini
  (normal metin icin 4.5:1) karsilayacak sekilde secilmistir.
* **Anlam renkleri tutarlidir**: yesil = musait/basarili, kirmizi = dolu/hata,
  sari = uyari/kirli, mavi = bilgi. Oda durumu gostergeleri bu esleme uzerine
  kuruludur ve tum ekranlarda ayni anlami tasir.
* **Renk tek basina bilgi tasimaz**: durum gostergelerinde renk her zaman bir
  metin etiketiyle birlikte kullanilir (renk korlugu icin).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class ThemeMode(str, Enum):
    """Tema kipi."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Palette:
    """Bir temanin renk paleti."""

    name: str

    # Yuzeyler
    background: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str

    # Metin
    text: str
    text_muted: str
    text_disabled: str
    text_inverse: str

    # Marka
    primary: str
    primary_hover: str
    primary_pressed: str
    primary_soft: str

    # Anlam renkleri
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    info: str
    info_soft: str

    # Oda durumu (kat hizmetleri gorunumu)
    room_vacant_clean: str
    room_vacant_dirty: str
    room_occupied: str
    room_out_of_service: str

    # Grafik serileri (siralamasi anlamli - once en cok kullanilan)
    chart_series: tuple[str, ...]


LIGHT_PALETTE: Final[Palette] = Palette(
    name="light",
    background="#F5F7FA",
    surface="#FFFFFF",
    surface_alt="#EEF2F7",
    surface_hover="#E4EAF2",
    border="#D8DFE8",
    border_strong="#B6C2D1",
    text="#16202C",
    text_muted="#5A6B7F",
    text_disabled="#9AA8B8",
    text_inverse="#FFFFFF",
    primary="#1B5E9E",
    primary_hover="#17517F",
    primary_pressed="#123F65",
    primary_soft="#DCE9F6",
    success="#1B7A4C",
    success_soft="#D9F0E2",
    warning="#9A6700",
    warning_soft="#FBEFD2",
    danger="#B02A2A",
    danger_soft="#F8DEDE",
    info="#0F6C94",
    info_soft="#D7EDF6",
    room_vacant_clean="#1B7A4C",
    room_vacant_dirty="#9A6700",
    room_occupied="#1B5E9E",
    room_out_of_service="#7A7A7A",
    chart_series=(
        "#1B5E9E",
        "#1B7A4C",
        "#9A6700",
        "#8B3E8F",
        "#0F6C94",
        "#B02A2A",
        "#5C6BC0",
        "#00796B",
    ),
)

DARK_PALETTE: Final[Palette] = Palette(
    name="dark",
    background="#12171E",
    surface="#1A2029",
    surface_alt="#222A35",
    surface_hover="#2B3542",
    border="#333E4C",
    border_strong="#4A5867",
    text="#E8EDF3",
    text_muted="#9FB0C3",
    text_disabled="#6B7A8B",
    text_inverse="#12171E",
    primary="#4A9EE0",
    primary_hover="#63B0EA",
    primary_pressed="#3A87C4",
    primary_soft="#1E344A",
    success="#4CC38A",
    success_soft="#173A2A",
    warning="#E0A73B",
    warning_soft="#3D2F11",
    danger="#E06A6A",
    danger_soft="#3D1E1E",
    info="#4EB8DD",
    info_soft="#12333F",
    room_vacant_clean="#4CC38A",
    room_vacant_dirty="#E0A73B",
    room_occupied="#4A9EE0",
    room_out_of_service="#7C8794",
    chart_series=(
        "#4A9EE0",
        "#4CC38A",
        "#E0A73B",
        "#C77DD0",
        "#4EB8DD",
        "#E06A6A",
        "#8C9EFF",
        "#4DB6AC",
    ),
)


#: Uygulamaya en son uygulanan palet.
#: Stil sayfasi ile cizilemeyen bilesenler (or. QtCharts grafikleri renklerini
#: kod icinde alir) aktif temayi buradan okur; aksi halde tema degistiginde
#: grafik eski renklerde kalir.
_active_palette: Palette | None = None


def set_active_palette(palette: Palette) -> None:
    """Uygulanan paleti kaydeder."""
    global _active_palette
    _active_palette = palette


def active_palette() -> Palette:
    """Su anda uygulanan paleti dondurur (ayarlanmadiysa koyu tema)."""
    return _active_palette or DARK_PALETTE


def get_palette(mode: ThemeMode | str) -> Palette:
    """Tema kipine gore paleti dondurur.

    ``SYSTEM`` kipinde isletim sisteminin koyu tema tercihi okunur; okunamazsa
    koyu tema varsayilir (otel resepsiyonu genellikle dusuk isikli ortamdir).
    """
    if isinstance(mode, str):
        mode = ThemeMode(mode)

    if mode is ThemeMode.SYSTEM:
        mode = ThemeMode.DARK if _system_prefers_dark() else ThemeMode.LIGHT

    return DARK_PALETTE if mode is ThemeMode.DARK else LIGHT_PALETTE


def _system_prefers_dark() -> bool:
    """Windows'ta uygulama temasi tercihini okur."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        finally:
            winreg.CloseKey(key)
    except Exception:
        return True


def build_stylesheet(palette: Palette) -> str:
    """Palete gore uygulama genelinde gecerli Qt stil sayfasi uretir."""
    p = palette
    return f"""
/* ===================== Genel ===================== */
QWidget {{
    background-color: {p.background};
    color: {p.text};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}

QMainWindow, QDialog {{
    background-color: {p.background};
}}

/* Saydam olmasi gereken bilesenler.
   Yukaridaki QWidget arka plan kurali Qt'de TUM alt siniflara iner -
   QLabel dahil. Bu yuzden bir kartin (surface rengi) icindeki her etiket,
   kartin degil pencerenin daha koyu arka planini boyar ve metinlerin
   arkasinda koyu dikdortgenler gorunur. Asagidaki kural bu bilesenleri
   saydam kilarak sorunu tek yerde cozer; aksi halde her ekranda ayri ayri
   yerel duzeltme gerekir. */
QLabel,
QCheckBox,
QRadioButton,
QStackedWidget,
QScrollArea,
QScrollArea > QWidget > QWidget,
QSplitter,
QTabWidget,
QGroupBox {{
    background-color: transparent;
}}

/* ===================== Kartlar / paneller ===================== */
QFrame#Card, QFrame#KpiCard {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
}}

QFrame#Card:hover {{
    border-color: {p.border_strong};
}}

QLabel#CardTitle {{
    color: {p.text_muted};
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 0.3px;
}}

QLabel#KpiValue {{
    color: {p.text};
    font-size: 22pt;
    font-weight: 700;
}}

QLabel#KpiDelta {{
    font-size: 9pt;
}}

QLabel#SectionTitle {{
    font-size: 14pt;
    font-weight: 700;
    color: {p.text};
}}

QLabel#Muted {{
    color: {p.text_muted};
}}

/* ===================== Sol gezinme ===================== */
QListWidget#NavList {{
    background-color: {p.surface};
    border: none;
    border-right: 1px solid {p.border};
    outline: none;
    padding: 8px 6px;
}}

QListWidget#NavList::item {{
    padding: 10px 14px;
    border-radius: 8px;
    margin: 2px 4px;
    color: {p.text_muted};
}}

QListWidget#NavList::item:hover {{
    background-color: {p.surface_hover};
    color: {p.text};
}}

QListWidget#NavList::item:selected {{
    background-color: {p.primary_soft};
    color: {p.primary};
    font-weight: 600;
}}

/* ===================== Ust cubuk ===================== */
QWidget#TopBar {{
    background-color: {p.surface};
    border-bottom: 1px solid {p.border};
}}

/* ===================== Dugmeler ===================== */
QPushButton {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 7px 16px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {p.surface_hover};
    border-color: {p.border_strong};
}}

QPushButton:disabled {{
    color: {p.text_disabled};
    background-color: {p.surface};
    border-color: {p.border};
}}

QPushButton#Primary {{
    background-color: {p.primary};
    color: {p.text_inverse};
    border: none;
    font-weight: 600;
}}

QPushButton#Primary:hover {{
    background-color: {p.primary_hover};
}}

QPushButton#Primary:pressed {{
    background-color: {p.primary_pressed};
}}

QPushButton#Danger {{
    background-color: {p.danger};
    color: #FFFFFF;
    border: none;
    font-weight: 600;
}}

/* ===================== Girdiler ===================== */
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 7px 10px;
    selection-background-color: {p.primary};
    selection-color: {p.text_inverse};
}}

QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {p.primary};
    padding: 6px 9px;
}}

QLineEdit[invalid="true"], QComboBox[invalid="true"], QSpinBox[invalid="true"] {{
    border: 2px solid {p.danger};
    padding: 6px 9px;
}}

QLineEdit:disabled, QComboBox:disabled {{
    background-color: {p.surface_alt};
    color: {p.text_disabled};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
    background: transparent;
}}

/* Acilir liste oku.
   Qt, ``image`` verilmediginde HICBIR ok cizmez; yalnizca genislik ayirmak
   bos bir alan birakir ve bilesen "bozuk" gorunur. Harici bir simge dosyasi
   yerine kenarliklardan ucgen uretiyoruz - boylece tema rengiyle uyumlu
   kalir ve paketlemede ek dosya gerekmez. */
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_muted};
    margin-right: 6px;
}}

QComboBox::down-arrow:hover {{
    border-top-color: {p.text};
}}

QComboBox::down-arrow:disabled {{
    border-top-color: {p.text_disabled};
}}

/* Sayi girdisi oklari.
   Varsayilan Qt yerlesimi bu oklari cercevenin DISINA, yan yana koyar ve
   bilesen bozuk gorunur. Ust-sag ve alt-saga yerlestirip kendi uclarimizi
   ciziyoruz. */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QDateEdit::up-button, QTimeEdit::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    background: transparent;
}}

QSpinBox::down-button, QDoubleSpinBox::down-button,
QDateEdit::down-button, QTimeEdit::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    background: transparent;
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QDateEdit::up-arrow, QTimeEdit::up-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {p.text_muted};
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow,
QDateEdit::down-arrow, QTimeEdit::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {p.text_muted};
}}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {p.surface_hover};
    border-radius: 3px;
}}

QComboBox QAbstractItemView {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.primary_soft};
    selection-color: {p.text};
    outline: none;
}}

/* ===================== Tablolar ===================== */
QTableView, QTreeView {{
    background-color: {p.surface};
    alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 8px;
    gridline-color: {p.border};
    selection-background-color: {p.primary_soft};
    selection-color: {p.text};
    outline: none;
}}

QTableView::item, QTreeView::item {{
    padding: 5px 8px;
}}

QHeaderView::section {{
    background-color: {p.surface_alt};
    color: {p.text_muted};
    border: none;
    border-bottom: 1px solid {p.border};
    border-right: 1px solid {p.border};
    padding: 8px;
    font-weight: 600;
}}

QHeaderView::section:hover {{
    background-color: {p.surface_hover};
    color: {p.text};
}}

/* ===================== Sekmeler ===================== */
QTabWidget::pane {{
    border: 1px solid {p.border};
    border-radius: 8px;
    background-color: {p.surface};
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {p.text_muted};
    padding: 9px 18px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

QTabBar::tab:selected {{
    background-color: {p.surface};
    color: {p.text};
    border-color: {p.border};
    border-bottom-color: {p.surface};
    font-weight: 600;
}}

QTabBar::tab:hover:!selected {{
    color: {p.text};
}}

/* ===================== Kaydirma cubuklari ===================== */
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 5px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: {p.text_muted};
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
}}

QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 5px;
    min-width: 28px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}

/* ===================== Durum rozetleri ===================== */
QLabel#BadgeSuccess {{
    background-color: {p.success_soft};
    color: {p.success};
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 600;
}}

QLabel#BadgeWarning {{
    background-color: {p.warning_soft};
    color: {p.warning};
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 600;
}}

QLabel#BadgeDanger {{
    background-color: {p.danger_soft};
    color: {p.danger};
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 600;
}}

QLabel#BadgeInfo {{
    background-color: {p.info_soft};
    color: {p.info};
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 600;
}}

/* Yapay zeka tarafindan uretilen icerik rozeti - HER ZAMAN gorunur olmali */
QLabel#AiBadge {{
    background-color: {p.info_soft};
    color: {p.info};
    border: 1px solid {p.info};
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 8pt;
    font-weight: 700;
}}

/* ===================== Diger ===================== */
QToolTip {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: 6px;
    padding: 6px 9px;
}}

QMenu {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 5px;
}}

QMenu::item {{
    padding: 7px 22px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background-color: {p.primary_soft};
    color: {p.primary};
}}

QStatusBar {{
    background-color: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.text_muted};
}}

QProgressBar {{
    background-color: {p.surface_alt};
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {p.primary};
    border-radius: 6px;
}}

QSplitter::handle {{
    background-color: {p.border};
}}

QGroupBox {{
    border: 1px solid {p.border};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {p.text_muted};
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
}}
"""


def room_status_color(palette: Palette, occupancy: str, housekeeping: str) -> str:
    """Oda plani hucresinin rengini belirler.

    Oncelik sirasi bilincli: servis disi durum her seyin onunde gelir, cunku
    o oda satilamaz. Sonra doluluk, en son temizlik durumu gelir.
    """
    if housekeeping in {"out_of_service", "out_of_order"}:
        return palette.room_out_of_service
    if occupancy == "occupied":
        return palette.room_occupied
    if housekeeping == "dirty":
        return palette.room_vacant_dirty
    return palette.room_vacant_clean


def apply_theme(app, mode: ThemeMode | str) -> Palette:
    """Temayi uygulamaya uygular ve aktif palet olarak kaydeder.

    Tema degisiminde tek giris noktasi budur; ``setStyleSheet`` ile
    ``set_active_palette`` in birlikte cagrilmasini garanti eder.
    """
    palette = get_palette(mode)
    app.setStyleSheet(build_stylesheet(palette))
    set_active_palette(palette)
    return palette


__all__ = [
    "DARK_PALETTE",
    "LIGHT_PALETTE",
    "Palette",
    "ThemeMode",
    "active_palette",
    "apply_theme",
    "build_stylesheet",
    "get_palette",
    "room_status_color",
    "set_active_palette",
]
