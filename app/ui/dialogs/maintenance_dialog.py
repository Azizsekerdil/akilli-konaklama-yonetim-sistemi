"""Ariza kaydi diyaloglari: yeni kayit ve cozum.

Diyaloglar **is kurali icermez**; dogrulama ve kayit
:mod:`app.application.services.maintenance_service` uzerinden yapilir.
Buradaki tek "akil" cakisma uyarisinin sunumudur:

Odayi satisa kapatirken o tarihlerde aktif rezervasyon varsa servis
``BusinessRuleError`` firlatir. Diyalog bunu hata olarak gostermek yerine
**karar noktasina** cevirir: uyariyi metinle acar ve yalnizca
:data:`~app.security.permissions.Perm.RESERVATION_OVERRIDE` yetkisi olan
kullaniciya "yine de kapat" secenegi sunar. Yetkisiz kullanici uyariyi gorur
ama gecemez.

Para birimi notu
----------------
``QDoubleSpinBox`` degeri ``float`` dondurur. Tutar hicbir yerde ``float``
olarak tasinmaz: okunur okunmaz ``Decimal(str(...))`` ile cevrilir.
``Decimal(0.1)`` ikilik yuvarlama hatasi tasir, ``Decimal("0.1")`` tasimaz -
aradaki fark kurus kaybi demektir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import BusinessRuleError, HotelError, ValidationError
from app.core.log import get_logger
from app.domain.enums import MaintenanceCategory, Priority
from app.security.permissions import Perm
from app.ui.session import UiSession
from app.ui.widgets.common import confirm, show_error

log = get_logger(__name__)


def parse_decimal(text: str, *, field: str) -> Decimal:
    """Kullanici metnini :class:`Decimal`'e cevirir.

    Turkce klavyede ondalik ayirici virguldur; "12,50" girdisi
    ``Decimal("12,50")`` icin gecersizdir. Once nokta bicimine cevrilir ve
    binlik ayiricilari atilir.
    """
    raw = (text or "").strip().replace(" ", "")
    if not raw:
        return Decimal("0.00")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValidationError(f"'{text}' gecerli bir sayi degil.", field=field) from exc
    return value


#: Tutar alaninin artir/azalt dugmeleri icin yerel duzeltme.
#:
#: Genel stil sayfasi ``QDoubleSpinBox``a yuvarlak kenar ve ``padding``
#: veriyor ama alt denetimleri (``up-button`` / ``down-button``) hic
#: konumlandirmiyor. Sonuc: iki ok yan yana, alanin sag kenarinin DISINDA,
#: yuvarlatilmis cerceveyi tasarak ciziliyor - kullanici bunu bozuk bir
#: bilesen olarak gorur. Kural oklari cercevenin icine, ust ve alt saga
#: yerlestirir. Kalici cozum ``app/ui/theme.py`` icindedir; orasi tum
#: ekranlari ilgilendirdigi icin bu duzeltme diyalogla sinirli tutuldu.
SPINBOX_BUTTONS = """
QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    margin: 3px 4px 0 0;
}
QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    margin: 0 4px 3px 0;
}
"""


def make_primary(button: QPushButton) -> None:
    """Dugmeyi birincil eylem gorunumune cevirir.

    ``objectName`` bilesen olusturulduktan **sonra** degistirildiginde Qt
    stil sayfasini yeniden uygulamaz; dugme sade gorunumde kalir.
    ``unpolish``/``polish`` cifti stili zorla yeniler.
    """
    button.setObjectName("Primary")
    button.style().unpolish(button)
    button.style().polish(button)


@dataclass(slots=True)
class RoomChoice:
    """Acilir listede gosterilen oda secenegi."""

    room_id: int
    label: str


class MaintenanceDialog(QDialog):
    """Yeni ariza kaydi olusturma diyalogu."""

    def __init__(self, ui_session: UiSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui = ui_session
        self.created_ticket_id: int | None = None

        self.setWindowTitle("Yeni Ariza Kaydi")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self._room_combo = QComboBox()
        self._room_combo.addItem("Ortak alan (oda disi)", None)
        form.addRow("Oda", self._room_combo)

        self._location_edit = QLineEdit()
        self._location_edit.setPlaceholderText("Or. Lobi - 2. asansor")
        self._location_edit.setToolTip("Yalnizca oda disi (ortak alan) arizalarinda doldurulur.")
        form.addRow("Konum", self._location_edit)
        # Oda secildiginde konum alani anlamsizdir; acik birakmak kullaniciyi
        # iki kez konum yazmaya davet ederdi.
        self._room_combo.currentIndexChanged.connect(self._on_room_changed)

        # Enum'un KENDISI degil ``value``'su saklanir. Qt kullanici verisini
        # QVariant'a cevirir; ``str`` tabanli bir enum geri okundugunda duz
        # ``str`` olur ve enum sanip ``.value`` cagirmak calisma aninda
        # AttributeError uretir. Servis katmani degeri enum'a geri cevirir.
        self._category_combo = QComboBox()
        for category in MaintenanceCategory:
            self._category_combo.addItem(category.label, category.value)
        form.addRow("Kategori", self._category_combo)

        self._priority_combo = QComboBox()
        for priority in Priority:
            self._priority_combo.addItem(priority.label, priority.value)
        self._priority_combo.setCurrentIndex(self._priority_combo.findData(Priority.NORMAL.value))
        form.addRow("Oncelik", self._priority_combo)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Kisa baslik, or. 'Klima sogutmuyor'")
        form.addRow("Baslik", self._title_edit)

        self._description_edit = QPlainTextEdit()
        self._description_edit.setPlaceholderText("Sorunu ayrintili anlatin.")
        self._description_edit.setMinimumHeight(90)
        self._description_edit.setMaximumHeight(120)
        form.addRow("Aciklama", self._description_edit)

        layout.addLayout(form)

        # --- Satisa kapatma ---
        self._block_check = QCheckBox("Odayi satisa kapat (servis disi)")
        self._block_check.toggled.connect(self._on_block_toggled)
        layout.addWidget(self._block_check)

        self._block_row = QWidget()
        block_layout = QHBoxLayout(self._block_row)
        block_layout.setContentsMargins(22, 0, 0, 0)
        block_layout.setSpacing(8)

        # Varsayilan genislik "15.08.2026" metnini takvim okuyla birlikte
        # kirpiyordu; tarihin tamami her zaman okunabilir olmalidir.
        self._block_from = QDateEdit()
        self._block_from.setCalendarPopup(True)
        self._block_from.setDisplayFormat("dd.MM.yyyy")
        self._block_from.setMinimumWidth(140)
        self._block_from.setDate(QDate.currentDate())

        self._block_until = QDateEdit()
        self._block_until.setCalendarPopup(True)
        self._block_until.setDisplayFormat("dd.MM.yyyy")
        self._block_until.setMinimumWidth(140)
        self._block_until.setDate(QDate.currentDate().addDays(1))

        block_layout.addWidget(QLabel("Baslangic"))
        block_layout.addWidget(self._block_from)
        block_layout.addWidget(QLabel("Bitis (dahil)"))
        block_layout.addWidget(self._block_until)
        block_layout.addStretch(1)
        self._block_row.setEnabled(False)
        layout.addWidget(self._block_row)

        self._warning_label = QLabel(
            "Satisa kapatma, o tarihlerde rezervasyonu olan odalarda yetkili onayi ister."
        )
        self._warning_label.setObjectName("Muted")
        self._warning_label.setWordWrap(True)
        layout.addWidget(self._warning_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        make_primary(buttons.button(QDialogButtonBox.StandardButton.Save))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgec")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if not self.ui.can(Perm.ROOM_BLOCK):
            self._block_check.setEnabled(False)
            self._block_check.setToolTip("Odayi satisa kapatma yetkiniz bulunmuyor.")

        self._load_rooms()

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def _load_rooms(self) -> None:
        """Oda listesini doldurur; ORM nesnesi diyalogda tutulmaz."""
        from app.infrastructure.db.repositories import RoomRepository

        try:
            with self.ui.service_context(commit=False) as ctx:
                choices = [
                    RoomChoice(room.id, f"{room.number} - {room.room_type.name}")
                    for room in RoomRepository(ctx.session).list_rooms(ctx.require_property())
                ]
        except HotelError as exc:
            show_error(self, exc)
            return

        for choice in choices:
            self._room_combo.addItem(choice.label, choice.room_id)

    def _on_room_changed(self, _index: int) -> None:
        is_common_area = self._room_combo.currentData() is None
        self._location_edit.setEnabled(is_common_area)
        if not is_common_area:
            self._location_edit.clear()

    def _on_block_toggled(self, checked: bool) -> None:
        self._block_row.setEnabled(checked)
        if checked and self._room_combo.currentData() is None and self._room_combo.count() > 1:
            # Satisa kapatma icin oda zorunludur; ilk gercek odayi secelim ki
            # kullanici dogrulama hatasiyla karsilasmasin.
            self._room_combo.setCurrentIndex(1)

    # ----------------------------------------------------------------- #
    #  Kaydetme
    # ----------------------------------------------------------------- #
    def _submit(self) -> None:
        from app.application.services.maintenance_service import MaintenanceService

        room_id = self._room_combo.currentData()
        blocks_room = self._block_check.isChecked()
        block_from: date | None = None
        block_until: date | None = None
        if blocks_room:
            block_from = self._block_from.date().toPython()
            block_until = self._block_until.date().toPython()

        payload = {
            "room_id": room_id,
            "category": self._category_combo.currentData(),
            "title": self._title_edit.text(),
            "description": self._description_edit.toPlainText(),
            "priority": self._priority_combo.currentData(),
            "blocks_room": blocks_room,
            "block_from": block_from,
            "block_until": block_until,
            "location_description": self._location_edit.text() or None,
        }

        try:
            with self.ui.service_context() as ctx:
                ticket = MaintenanceService(ctx).create_ticket(**payload)
                self.created_ticket_id = ticket.id
        except BusinessRuleError as exc:
            if exc.code == "room_has_reservation" and self._offer_override(exc):
                self._submit_forced(payload)
            else:
                show_error(self, exc)
            return
        except HotelError as exc:
            show_error(self, exc)
            return

        self.accept()

    def _offer_override(self, error: BusinessRuleError) -> bool:
        """Cakisma uyarisini gosterir ve asma iznini sorar.

        Yetkisi olmayan kullaniciya secenek **sunulmaz**; yalnizca uyari
        gosterilir. Aksi halde kullanici onaylar, servis reddeder ve ekranda
        anlamsiz bir "yetkiniz yok" hatasi belirirdi.
        """
        if not self.ui.can(Perm.RESERVATION_OVERRIDE):
            show_error(self, error, title="Oda satisa kapatilamaz")
            return False

        return confirm(
            self,
            error.user_message,
            title="Cakisan rezervasyon var",
            detail=(
                "Yine de kapatmak icin onaylayin. Misafirin baska bir odaya "
                "alinmasi sizin sorumlulugunuzdadir; islem denetim gunlugune yazilir."
            ),
            dangerous=True,
        )

    def _submit_forced(self, payload: dict) -> None:
        from app.application.services.maintenance_service import MaintenanceService

        try:
            with self.ui.service_context() as ctx:
                ticket = MaintenanceService(ctx).create_ticket(**payload, force=True)
                self.created_ticket_id = ticket.id
        except HotelError as exc:
            show_error(self, exc)
            return
        self.accept()


class ResolveMaintenanceDialog(QDialog):
    """Ariza cozme diyalogu: cozum notu, iscilik maliyeti ve parca listesi."""

    PART_COLUMNS = ("Parca / Malzeme", "Miktar", "Birim Maliyet")

    def __init__(
        self,
        ui_session: UiSession,
        ticket_id: int,
        ticket_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = ui_session
        self.ticket_id = ticket_id

        self.setWindowTitle("Arizayi Coz")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = QLabel(ticket_label)
        header.setObjectName("SectionTitle")
        header.setWordWrap(True)
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)

        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlaceholderText("Ne yapildi? Hangi parca degisti?")
        self._notes_edit.setMinimumHeight(90)
        self._notes_edit.setMaximumHeight(120)
        form.addRow("Cozum notu", self._notes_edit)

        self._labor_spin = QDoubleSpinBox()
        self._labor_spin.setDecimals(2)
        self._labor_spin.setMaximum(1_000_000.0)
        self._labor_spin.setSingleStep(50.0)
        self._labor_spin.setSuffix(" TL")
        self._labor_spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Tutar alani formun tamamini kaplamamali; sayi alanlari sagda
        # hizalanip dar durdugunda okunmasi kolaylasir.
        self._labor_spin.setMaximumWidth(220)
        self._labor_spin.setStyleSheet(SPINBOX_BUTTONS)
        form.addRow("Iscilik maliyeti", self._labor_spin)

        layout.addLayout(form)

        parts_header = QHBoxLayout()
        parts_label = QLabel("KULLANILAN PARCALAR")
        parts_label.setObjectName("CardTitle")
        parts_header.addWidget(parts_label)
        parts_header.addStretch(1)

        add_button = QPushButton("Satir Ekle")
        add_button.clicked.connect(self._add_part_row)
        parts_header.addWidget(add_button)

        remove_button = QPushButton("Satiri Sil")
        remove_button.clicked.connect(self._remove_part_row)
        parts_header.addWidget(remove_button)
        layout.addLayout(parts_header)

        self._parts_table = QTableWidget(0, len(self.PART_COLUMNS))
        self._parts_table.setHorizontalHeaderLabels(list(self.PART_COLUMNS))
        self._parts_table.verticalHeader().setVisible(False)
        self._parts_table.setMinimumHeight(140)
        self._parts_table.horizontalHeader().setStretchLastSection(True)
        self._parts_table.setColumnWidth(0, 260)
        self._parts_table.setColumnWidth(1, 90)
        layout.addWidget(self._parts_table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Cozuldu Olarak Kaydet")
        make_primary(buttons.button(QDialogButtonBox.StandardButton.Save))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgec")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ----------------------------------------------------------------- #
    #  Parca satirlari
    # ----------------------------------------------------------------- #
    def _add_part_row(self) -> None:
        row = self._parts_table.rowCount()
        self._parts_table.insertRow(row)
        for column, default in enumerate(("", "1", "0,00")):
            item = QTableWidgetItem(default)
            if column:
                item.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )
            self._parts_table.setItem(row, column, item)

    def _remove_part_row(self) -> None:
        row = self._parts_table.currentRow()
        if row >= 0:
            self._parts_table.removeRow(row)

    def collect_parts(self) -> list:
        """Tablodaki satirlari :class:`PartUsage` listesine cevirir.

        Aciklamasi bos satirlar sessizce atlanir - kullanici "Satir Ekle"ye
        fazladan basmis olabilir ve bu bir hata degildir.
        """
        from app.application.services.maintenance_service import PartUsage

        parts = []
        for row in range(self._parts_table.rowCount()):
            description = self._cell_text(row, 0).strip()
            if not description:
                continue
            parts.append(
                PartUsage(
                    description=description,
                    quantity=parse_decimal(self._cell_text(row, 1), field="quantity"),
                    unit_cost=parse_decimal(self._cell_text(row, 2), field="unit_cost"),
                )
            )
        return parts

    def _cell_text(self, row: int, column: int) -> str:
        item = self._parts_table.item(row, column)
        return item.text() if item is not None else ""

    # ----------------------------------------------------------------- #
    #  Kaydetme
    # ----------------------------------------------------------------- #
    def _submit(self) -> None:
        from app.application.services.maintenance_service import MaintenanceService

        try:
            parts = self.collect_parts()
            # float -> Decimal donusumu str uzerinden yapilir (bkz. modul basligi).
            labor_cost = Decimal(str(self._labor_spin.value()))
            with self.ui.service_context() as ctx:
                MaintenanceService(ctx).resolve(
                    self.ticket_id,
                    resolution_notes=self._notes_edit.toPlainText(),
                    labor_cost=labor_cost,
                    parts=parts,
                )
        except HotelError as exc:
            show_error(self, exc)
            return
        self.accept()


__all__ = [
    "SPINBOX_BUTTONS",
    "MaintenanceDialog",
    "ResolveMaintenanceDialog",
    "RoomChoice",
    "make_primary",
    "parse_decimal",
]
