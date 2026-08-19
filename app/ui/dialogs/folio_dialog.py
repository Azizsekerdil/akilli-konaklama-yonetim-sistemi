"""Folyo (misafir hesabi) diyalogu: ucret satirlari, odemeler ve bakiye.

Muhasebe ilkesi arayuze de yansir
---------------------------------
Gecersiz kilinmis (``is_void``) ucret satirlari **gizlenmez**: ustu cizili ve
soluk gosterilir, gerekcesi ipucu (tooltip) olarak okunur. Satiri listeden
dusurmek, kullaniciya "kayit silindi" izlenimi verir ve denetim izinin
gorunurlugunu yok ederdi.

Neden ``QTableWidget``?
-----------------------
Sayfalarda kullanilan :class:`~app.ui.widgets.table.FilterableTableView`
yalnizca metin, hizalama ve on plan rengi rollerini destekler. Burada
**yazi tipi** (ustu cizili) ve **ipucu** rollerine ihtiyac var; folyo satir
sayisi da onlarla olculdugu icin model/gorunum ayriminin performans kazanci
gecerli degil. Bu yuzden dogrudan ``QTableWidget`` kullaniliyor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.application.services.folio_service import FolioService
from app.core.exceptions import HotelError, ValidationError
from app.core.log import get_logger
from app.domain.enums import ChargeType, Currency, PaymentMethod
from app.domain.value_objects import Money
from app.security.permissions import Perm
from app.ui.formatting import format_datetime, format_number, format_short_date
from app.ui.session import UiSession
from app.ui.theme import active_palette
from app.ui.widgets.common import (
    Card,
    EmptyState,
    SectionTitle,
    StatusBadge,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)

log = get_logger(__name__)

#: Yetkisi olmayan dugmelerin ipucu kalibi. Dugme gizlenmez; kullanici neden
#: yapamadigini gorebilmelidir.
PERMISSION_HINT = "Bu islem icin '{name}' yetkisi gerekiyor. Yoneticinize basvurun."


def set_action_state(
    button: QPushButton,
    *,
    enabled: bool,
    tooltip: str = "",
    accent: str = "Primary",
) -> None:
    """Dugmenin etkinligini, ipucunu ve vurgu stilini birlikte ayarlar.

    Vurgu (``#Primary`` / ``#Danger``) yalnizca **etkin** dugmede kalir.
    Nedeni Qt stil sayfasi onceligidir: kimlik secicisi (``#Primary``) durum
    secicisinden (``QPushButton:disabled``) daha baskindir; vurgu birakilirsa
    pasif dugme de canli mavi/kirmizi gorunur ve kullanici tiklanabilir sanir.
    """
    button.setEnabled(enabled)
    button.setToolTip(tooltip)
    target = accent if enabled else ""
    if button.objectName() != target:
        button.setObjectName(target)
        button.style().unpolish(button)
        button.style().polish(button)


def fit_dialog_to_content(dialog: QDialog, scroll: QScrollArea, *, width: int) -> None:
    """Diyalogu, kaydirilabilir govdesini kirpmayacak yukseklige getirir.

    Kaydirma alani KALIR - kucuk ekranli on buro terminallerinde gereklidir -
    ancak ekran yeterliyse kullanici hicbir seyi kaydirmak zorunda kalmaz.
    Sabit bir acilis yuksekligi vermek yetmiyor: icerik kosullu bolumlerle
    (kirli oda uyarisi, hasar alanlari) degisiyor ve son satir yarim kirpilmis
    gorunuyordu.

    Yukseklik, kullanilabilir ekran alaninin %92'si ile SINIRLANIR; aksi halde
    uzun icerikli diyalog gorev cubugunun altina tasar ve dugmeleri erisilmez
    kilardi.
    """
    body = scroll.widget()
    if body is None:  # pragma: no cover - govde her zaman kurulu
        return

    # Yerlesimi zorla hesaplat: gosterilmemis bir diyalogda olculer aksi halde
    # bayat kalir ve sizeHint sifir doner.
    dialog.ensurePolished()
    layout = dialog.layout()
    if layout is not None:
        layout.activate()

    # Kaydirma disinda kalan yukseklik (baslik, dugmeler, kenar bosluklari).
    chrome = max(dialog.sizeHint().height() - scroll.sizeHint().height(), 0)
    target = body.sizeHint().height() + chrome + 2 * scroll.frameWidth()

    screen = dialog.screen() or QGuiApplication.primaryScreen()
    if screen is not None:
        target = min(target, int(screen.availableGeometry().height() * 0.92))
    dialog.resize(width, max(target, dialog.minimumHeight()))


def parse_amount(text: str, *, field_name: str = "amount", allow_zero: bool = False) -> Decimal:
    """Kullanicinin yazdigi para tutarini ``Decimal``'e cevirir.

    Hem Turkce yerel bicim (``1.250,75``) hem de nokta ondalikli bicim
    (``1250.75``) kabul edilir. Ara adimda **float kullanilmaz**: ``float``
    uzerinden gecen bir tutar 0,1 + 0,2 = 0,30000000000000004 gibi ikili
    gosterim hatalarini kasaya tasir.

    >>> parse_amount("1.250,75")
    Decimal('1250.75')
    >>> parse_amount("1250.75")
    Decimal('1250.75')
    """
    raw = (text or "").strip().replace(" ", "").replace("₺", "")
    if not raw:
        raise ValidationError("Tutar girilmelidir.", field=field_name)
    if "," in raw:
        # Turkce bicim: nokta binlik ayiraci, virgul ondalik ayiraci.
        raw = raw.replace(".", "").replace(",", ".")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValidationError(
            "Tutar sayisal olmalidir. Ornek: 1.250,00",
            field=field_name,
        ) from exc
    if value < 0 or (value == 0 and not allow_zero):
        raise ValidationError("Tutar sifirdan buyuk olmalidir.", field=field_name)
    return value.quantize(Decimal("0.01"))


# --------------------------------------------------------------------------
#  Duz veri yapilari
# --------------------------------------------------------------------------
@dataclass(slots=True)
class ChargeRow:
    """Tek bir ucret satirinin gosterime hazir hali."""

    charge_id: int
    charge_date: date
    description: str
    charge_type_label: str
    quantity: Decimal
    total: Money
    is_void: bool = False
    void_reason: str = ""


@dataclass(slots=True)
class PaymentRow:
    """Tek bir odeme/iade satiri."""

    payment_id: int
    paid_at: datetime | None
    method_label: str
    amount: Money
    reference: str = ""
    is_refund: bool = False


@dataclass(slots=True)
class FolioSnapshot:
    """Folyo ekraninin tek seferde ihtiyac duydugu tum veriler.

    ORM nesneleri oturum disina cikarilmaz; :meth:`FolioDialog._load` bu
    yapiyi ``service_context`` blogu icinde doldurur.
    """

    folio_id: int
    folio_number: str = ""
    status_label: str = ""
    is_open: bool = True
    guest_name: str = "-"
    room_number: str = "-"
    currency: Currency = Currency.TRY
    charges: list[ChargeRow] = field(default_factory=list)
    payments: list[PaymentRow] = field(default_factory=list)
    total_charges: Money = field(default_factory=Money.zero)
    total_payments: Money = field(default_factory=Money.zero)
    balance: Money = field(default_factory=Money.zero)


# --------------------------------------------------------------------------
#  Yardimci alt diyaloglar
# --------------------------------------------------------------------------
class ChargeEntryDialog(QDialog):
    """Folyoya yeni ucret eklemek icin kucuk giris formu."""

    def __init__(self, currency: Currency, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ucret Ekle")
        self.setMinimumWidth(430)
        self._currency = currency

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(9)
        grid.setColumnStretch(1, 1)

        self.type_combo = QComboBox()
        for value, label in ChargeType.choices():
            self.type_combo.addItem(label, value)
        self.type_combo.setCurrentIndex(
            max(self.type_combo.findData(ChargeType.FOOD_BEVERAGE.value), 0)
        )

        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Ornek: Restoran adisyon no 412")

        # Miktar tam sayidir: kesirli miktar (0,5 sise) otelcilikte adisyona
        # ayri satir olarak yazilir; boylece Decimal'e float ara adimi girmez.
        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 999)
        self.quantity_spin.setValue(1)

        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("0,00")

        for row_index, (title, widget) in enumerate(
            (
                ("Ucret Turu", self.type_combo),
                ("Aciklama", self.description_edit),
                ("Miktar", self.quantity_spin),
                (f"Birim Fiyat ({currency.symbol})", self.price_edit),
            )
        ):
            label = QLabel(title)
            label.setObjectName("Muted")
            grid.addWidget(label, row_index, 0)
            grid.addWidget(widget, row_index, 1)
        layout.addLayout(grid)

        self._error_label = QLabel()
        self._error_label.setObjectName("BadgeDanger")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Iptal")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Ekle")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._on_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.charge_type: ChargeType = ChargeType.FOOD_BEVERAGE
        self.description: str = ""
        self.quantity: Decimal = Decimal("1")
        self.unit_price: Decimal = Decimal("0.00")

    def _on_accept(self) -> None:
        description = self.description_edit.text().strip()
        if not description:
            self._show_error("Aciklama zorunludur; misafir folyosunda ne oldugu okunmalidir.")
            return
        try:
            self.unit_price = parse_amount(self.price_edit.text(), field_name="unit_price")
        except ValidationError as exc:
            self._show_error(exc.user_message)
            return

        self.charge_type = ChargeType(self.type_combo.currentData())
        self.description = description
        self.quantity = Decimal(self.quantity_spin.value())
        self.accept()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)


class PaymentEntryDialog(QDialog):
    """Folyoya tahsilat girmek icin kucuk form."""

    def __init__(
        self,
        balance: Money,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tahsilat")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        info = QLabel(f"Kalan bakiye: <b>{balance.format()}</b>")
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        grid = QGridLayout()
        grid.setSpacing(9)
        grid.setColumnStretch(1, 1)

        self.amount_edit = QLineEdit()
        # Varsayilan olarak kalan bakiye onerilir: en sik yapilan islem
        # bakiyenin tamamini tahsil etmektir.
        self.amount_edit.setText(balance.format(with_symbol=False) if balance.amount > 0 else "")

        self.method_combo = QComboBox()
        for value, label in PaymentMethod.choices():
            self.method_combo.addItem(label, value)

        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText("Dekont / islem numarasi (istege bagli)")

        for row_index, (title, widget) in enumerate(
            (
                (f"Tutar ({balance.currency.symbol})", self.amount_edit),
                ("Odeme Yontemi", self.method_combo),
                ("Referans", self.reference_edit),
            )
        ):
            label = QLabel(title)
            label.setObjectName("Muted")
            grid.addWidget(label, row_index, 0)
            grid.addWidget(widget, row_index, 1)
        layout.addLayout(grid)

        note = QLabel("Kart numarasi kaydedilmez; yalnizca odeme yontemi ve tutar saklanir.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._error_label = QLabel()
        self._error_label.setObjectName("BadgeDanger")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Iptal")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Tahsil Et")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._on_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.amount: Decimal = Decimal("0.00")
        self.method: PaymentMethod = PaymentMethod.CASH
        self.reference: str = ""

    def _on_accept(self) -> None:
        try:
            self.amount = parse_amount(self.amount_edit.text(), field_name="amount")
        except ValidationError as exc:
            self._error_label.setText(exc.user_message)
            self._error_label.setVisible(True)
            return
        self.method = PaymentMethod(self.method_combo.currentData())
        self.reference = self.reference_edit.text().strip()
        self.accept()


class VoidReasonDialog(QDialog):
    """Ucret gecersiz kilma gerekcesini alir - gerekce ZORUNLUDUR."""

    def __init__(self, description: str, amount: Money, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ucreti Gecersiz Kil")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QLabel(f"<b>{description}</b> — {amount.format()}")
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setWordWrap(True)
        layout.addWidget(header)

        info = QLabel(
            "Kayit silinmez; gecersiz olarak isaretlenir ve folyoda ustu cizili gorunmeye "
            "devam eder. Gerekce denetim gunlugune yazilir."
        )
        info.setObjectName("Muted")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.reason_edit = QPlainTextEdit()
        self.reason_edit.setPlaceholderText("Gerekce (zorunlu)")
        self.reason_edit.setFixedHeight(84)
        layout.addWidget(self.reason_edit)

        self._error_label = QLabel()
        self._error_label.setObjectName("BadgeDanger")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Vazgec")
        cancel.clicked.connect(self.reject)
        confirm_button = QPushButton("Gecersiz Kil")
        confirm_button.setObjectName("Danger")
        confirm_button.clicked.connect(self._on_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm_button)
        layout.addLayout(buttons)

        self.reason: str = ""

    def _on_accept(self) -> None:
        reason = self.reason_edit.toPlainText().strip()
        if not reason:
            self._error_label.setText("Gerekce zorunludur.")
            self._error_label.setVisible(True)
            return
        self.reason = reason
        self.accept()


# --------------------------------------------------------------------------
#  Ana diyalog
# --------------------------------------------------------------------------
class FolioDialog(QDialog):
    """Bir folyonun ucret/odeme dokumu ve islemleri."""

    def __init__(
        self,
        ui_session: UiSession,
        folio_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = ui_session
        self.folio_id = folio_id
        self.snapshot = FolioSnapshot(folio_id=folio_id)
        #: Islem yapildi mi? Cagiran ekran buna bakarak listesini yeniler.
        self.changed = False

        self.setWindowTitle("Folyo")
        self.setMinimumSize(880, 660)

        self._build()
        self._reload()

    # ----------------------------------------------------------------- #
    #  Arayuz
    # ----------------------------------------------------------------- #
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self._title = SectionTitle("Folyo")
        self._subtitle = QLabel()
        self._subtitle.setObjectName("Muted")
        self._status_badge = StatusBadge("-", "info", self)
        header.addWidget(self._title)
        header.addSpacing(10)
        header.addWidget(self._subtitle)
        header.addStretch(1)
        header.addWidget(self._status_badge)
        layout.addLayout(header)

        # --- Ucretler ---
        charges_card = Card("Ucretler", self)
        self._charges_table = self._make_table(
            ["Tarih", "Aciklama", "Tur", "Miktar", "Tutar"],
            stretch_column=1,
        )
        self._charges_table.setMinimumHeight(210)
        self._charges_empty = EmptyState(
            "Bu folyoda henuz ucret yok.",
            hint="'Ucret Ekle' ile minibar, restoran veya diger hizmetleri isleyebilirsiniz.",
            parent=self,
        )
        self._charges_empty.setVisible(False)
        charges_card.add_widget(self._charges_table)
        charges_card.add_widget(self._charges_empty)
        layout.addWidget(charges_card, 3)

        # --- Odemeler ---
        payments_card = Card("Odemeler", self)
        self._payments_table = self._make_table(
            ["Tarih", "Yontem", "Referans", "Tutar"],
            stretch_column=2,
        )
        self._payments_table.setMinimumHeight(130)
        self._payments_empty = EmptyState(
            "Henuz tahsilat yapilmamis.",
            hint="Bakiye acikken cikis yapilamaz; 'Tahsilat' dugmesini kullanin.",
            parent=self,
        )
        self._payments_empty.setVisible(False)
        payments_card.add_widget(self._payments_table)
        payments_card.add_widget(self._payments_empty)
        layout.addWidget(payments_card, 2)

        # --- Toplamlar ---
        totals_card = Card("Ozet", self)
        totals = QGridLayout()
        totals.setSpacing(6)
        totals.setColumnStretch(1, 1)

        self._total_charges_label = QLabel("-")
        self._total_payments_label = QLabel("-")
        self._balance_label = QLabel("-")
        self._balance_label.setObjectName("KpiValue")
        self._balance_note = QLabel()
        self._balance_note.setObjectName("Muted")
        self._balance_note.setWordWrap(True)

        for row_index, (title, widget) in enumerate(
            (
                ("Toplam Ucret", self._total_charges_label),
                ("Toplam Odeme", self._total_payments_label),
            )
        ):
            name = QLabel(title)
            name.setObjectName("Muted")
            widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            totals.addWidget(name, row_index, 0)
            totals.addWidget(widget, row_index, 1)

        balance_title = QLabel("BAKIYE")
        balance_title.setObjectName("CardTitle")
        self._balance_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        totals.addWidget(balance_title, 2, 0)
        totals.addWidget(self._balance_label, 2, 1)
        totals.addWidget(self._balance_note, 3, 0, 1, 2)
        totals_card.add_layout(totals)
        layout.addWidget(totals_card)

        # --- Dugmeler ---
        buttons = QHBoxLayout()
        self._add_charge_button = QPushButton("Ucret Ekle")
        self._add_charge_button.clicked.connect(self._on_add_charge)
        self._void_button = QPushButton("Gecersiz Kil")
        self._void_button.setObjectName("Danger")
        self._void_button.clicked.connect(self._on_void_charge)
        self._payment_button = QPushButton("Tahsilat")
        self._payment_button.setObjectName("Primary")
        self._payment_button.clicked.connect(self._on_add_payment)

        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.accept)

        buttons.addWidget(self._add_charge_button)
        buttons.addWidget(self._void_button)
        buttons.addWidget(self._payment_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._charges_table.itemSelectionChanged.connect(self._update_actions)

    def _make_table(self, headers: list[str], *, stretch_column: int) -> QTableWidget:
        """Ortak bicimde bir tablo olusturur."""
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)

        header = table.horizontalHeader()
        for index in range(len(headers)):
            if index == stretch_column:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        return table

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def _reload(self) -> None:
        """Veriyi yeniden okur ve ekrani cizer."""
        try:
            self.snapshot = self._load()
        except HotelError as exc:
            show_error(self, exc)
            return
        self._render()

    def _load(self) -> FolioSnapshot:
        """Folyoyu duz veri yapisina cevirir.

        ORM nesneleri ``service_context`` blogunun disina TASINMAZ; blok
        bitince iliskilere erisim ``DetachedInstanceError`` firlatir.
        """
        from app.infrastructure.db.repositories import FolioRepository

        with self.ui.service_context(commit=False) as ctx:
            ctx.require(Perm.FOLIO_VIEW)
            folio = FolioRepository(ctx.session).get_with_lines(self.folio_id)
            folio.recalculate()

            currency = folio.currency
            snapshot = FolioSnapshot(
                folio_id=folio.id,
                folio_number=folio.folio_number,
                status_label=folio.status.label,
                is_open=folio.is_open,
                guest_name=folio.guest.full_name if folio.guest is not None else "-",
                room_number=(
                    folio.reservation_room.room.number
                    if folio.reservation_room is not None and folio.reservation_room.room
                    else "-"
                ),
                currency=currency,
                total_charges=Money.of(folio.total_charges, currency),
                total_payments=Money.of(folio.total_payments, currency),
                balance=Money.of(folio.balance, currency),
            )
            snapshot.charges = [
                ChargeRow(
                    charge_id=charge.id,
                    charge_date=charge.charge_date,
                    description=charge.description,
                    charge_type_label=charge.charge_type.label,
                    quantity=charge.quantity,
                    total=Money.of(charge.total_amount, currency),
                    is_void=charge.is_void,
                    void_reason=charge.void_reason or "",
                )
                for charge in sorted(folio.charges, key=lambda c: (c.charge_date, c.id))
            ]
            snapshot.payments = [
                PaymentRow(
                    payment_id=payment.id,
                    paid_at=payment.paid_at,
                    method_label=payment.method.label,
                    amount=Money.of(payment.amount, currency),
                    reference=payment.reference or "",
                    is_refund=payment.is_refund,
                )
                for payment in sorted(folio.payments, key=lambda p: p.id)
            ]
            return snapshot

    # ----------------------------------------------------------------- #
    #  Cizim
    # ----------------------------------------------------------------- #
    def _render(self) -> None:
        snapshot = self.snapshot
        palette = active_palette()

        self._title.setText(f"Folyo {snapshot.folio_number}")
        self._subtitle.setText(f"{snapshot.guest_name} · Oda {snapshot.room_number}")
        self._status_badge.set_status(
            snapshot.status_label, "success" if snapshot.is_open else "info"
        )

        # --- Ucret satirlari ---
        table = self._charges_table
        table.setRowCount(len(snapshot.charges))
        for index, row in enumerate(snapshot.charges):
            cells = [
                format_short_date(row.charge_date),
                row.description,
                row.charge_type_label,
                format_number(row.quantity),
                row.total.format(),
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column >= 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.charge_id)
                if row.is_void:
                    # Gecersiz satir SILINMIS gibi gizlenmez: ustu cizilir,
                    # soluklastirilir ve gerekcesi ipucunda gosterilir.
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
                    item.setForeground(QColor(palette.text_disabled))
                    item.setToolTip(
                        f"Gecersiz kilindi. Gerekce: {row.void_reason or 'belirtilmemis'}"
                        "\nTutar toplama dahil edilmez."
                    )
                table.setItem(index, column, item)

        has_charges = bool(snapshot.charges)
        table.setVisible(has_charges)
        self._charges_empty.setVisible(not has_charges)

        # --- Odeme satirlari ---
        payments = self._payments_table
        payments.setRowCount(len(snapshot.payments))
        for index, payment in enumerate(snapshot.payments):
            amount_text = payment.amount.format()
            if payment.is_refund:
                amount_text = f"-{amount_text}"
            cells = [
                format_datetime(payment.paid_at),
                payment.method_label + (" (iade)" if payment.is_refund else ""),
                payment.reference or "-",
                amount_text,
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                    if payment.is_refund:
                        item.setForeground(QColor(palette.danger))
                payments.setItem(index, column, item)

        has_payments = bool(snapshot.payments)
        payments.setVisible(has_payments)
        self._payments_empty.setVisible(not has_payments)

        # --- Toplamlar ---
        self._total_charges_label.setText(snapshot.total_charges.format())
        self._total_payments_label.setText(snapshot.total_payments.format())
        self._balance_label.setText(snapshot.balance.format())
        if snapshot.balance.amount > 0:
            self._balance_label.setStyleSheet(f"color: {palette.danger};")
            self._balance_note.setText("Bakiye acik - cikis oncesi tahsilat yapilmalidir.")
        elif snapshot.balance.amount < 0:
            self._balance_label.setStyleSheet(f"color: {palette.warning};")
            self._balance_note.setText("Fazla odeme var - iade gerekebilir.")
        else:
            self._balance_label.setStyleSheet(f"color: {palette.success};")
            self._balance_note.setText("Hesap kapali; odenecek tutar yok.")

        voided = [c for c in snapshot.charges if c.is_void]
        if voided:
            self._balance_note.setText(
                self._balance_note.text()
                + f"  ({len(voided)} gecersiz satir toplama dahil edilmedi.)"
            )

        self._update_actions()

    def _update_actions(self) -> None:
        """Dugme etkinligini yetki ve secime gore ayarlar.

        Yetkisi olmayan dugme **gizlenmez**, devre disi birakilir ve ipucu
        nedeni acikca yazar; kullanici neden yapamadigini anlar.
        """
        can_post = self.ui.can(Perm.FOLIO_POST_CHARGE)
        can_void = self.ui.can(Perm.FOLIO_VOID_CHARGE)
        can_pay = self.ui.can(Perm.PAYMENT_RECEIVE)
        is_open = self.snapshot.is_open

        set_action_state(
            self._add_charge_button,
            enabled=can_post and is_open,
            tooltip=(
                PERMISSION_HINT.format(name="Folyoya ucret isleme")
                if not can_post
                else (
                    "Kapali folyoya ucret islenemez."
                    if not is_open
                    else "Folyoya yeni ucret ekler."
                )
            ),
            accent="",
        )
        set_action_state(
            self._payment_button,
            enabled=can_pay,
            tooltip=(
                PERMISSION_HINT.format(name="Odeme alma")
                if not can_pay
                else "Folyoya tahsilat isler."
            ),
        )

        selected = self._selected_charge()
        if not can_void:
            void_enabled, void_tip = False, PERMISSION_HINT.format(name="Ucret gecersiz kilma")
        elif selected is None:
            void_enabled, void_tip = False, "Once gecersiz kilinacak ucret satirini secin."
        elif selected.is_void:
            void_enabled, void_tip = False, "Bu satir zaten gecersiz kilinmis."
        else:
            void_enabled, void_tip = True, "Secili ucreti gerekce ile gecersiz kilar (silmez)."
        set_action_state(self._void_button, enabled=void_enabled, tooltip=void_tip, accent="Danger")

    def _selected_charge(self) -> ChargeRow | None:
        rows = self._charges_table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self.snapshot.charges):
            return self.snapshot.charges[index]
        return None

    # ----------------------------------------------------------------- #
    #  Islemler
    # ----------------------------------------------------------------- #
    def _on_add_charge(self) -> None:
        dialog = ChargeEntryDialog(self.snapshot.currency, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            with self.ui.service_context() as ctx:
                FolioService(ctx).post_charge(
                    self.folio_id,
                    charge_type=dialog.charge_type,
                    description=dialog.description,
                    unit_price=dialog.unit_price,
                    quantity=dialog.quantity,
                )
        except HotelError as exc:
            show_error(self, exc)
            return

        self.changed = True
        show_toast(self, "Ucret folyoya islendi.", ToastLevel.SUCCESS)
        self._reload()

    def _on_void_charge(self) -> None:
        charge = self._selected_charge()
        if charge is None:
            return

        dialog = VoidReasonDialog(charge.description, charge.total, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not confirm(
            self,
            f"'{charge.description}' ucreti gecersiz kilinsin mi?",
            detail=(
                "Kayit silinmez, gecersiz olarak isaretlenir ve bakiyeden dusulur. "
                "Islem denetim gunlugune yazilir."
            ),
            dangerous=True,
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                FolioService(ctx).void_charge(charge.charge_id, reason=dialog.reason)
        except HotelError as exc:
            show_error(self, exc)
            return

        self.changed = True
        show_toast(self, "Ucret gecersiz kilindi.", ToastLevel.WARNING)
        self._reload()

    def _on_add_payment(self) -> None:
        dialog = PaymentEntryDialog(self.snapshot.balance, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            with self.ui.service_context() as ctx:
                FolioService(ctx).add_payment(
                    self.folio_id,
                    amount=dialog.amount,
                    method=dialog.method,
                    reference=dialog.reference or None,
                )
        except HotelError as exc:
            show_error(self, exc)
            return

        self.changed = True
        show_toast(self, "Tahsilat kaydedildi.", ToastLevel.SUCCESS)
        self._reload()


__all__ = [
    "PERMISSION_HINT",
    "ChargeEntryDialog",
    "ChargeRow",
    "FolioDialog",
    "FolioSnapshot",
    "PaymentEntryDialog",
    "PaymentRow",
    "VoidReasonDialog",
    "fit_dialog_to_content",
    "parse_amount",
    "set_action_state",
]
