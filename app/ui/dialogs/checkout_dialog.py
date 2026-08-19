"""Cikis (check-out) diyalogu: folyo ozeti, tahsilat, gec cikis ve hasar.

Ekranin tasarim amaci tek bir soruyu her zaman gorunur kilmaktir:
**"Bu misafirden alinacak para kaldi mi?"** Bakiye buyuk punto ile ve
renk + metin birlikte gosterilir; acik bakiye varken cikis denendiginde
servis :class:`~app.core.exceptions.PaymentError` firlatir ve kullaniciya
"once tahsilat yapin" yonlendirmesi gosterilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.application.services.folio_service import FolioService
from app.application.services.frontdesk_service import FrontdeskService
from app.core.exceptions import HotelError, PaymentError, ValidationError
from app.core.log import get_logger
from app.domain.enums import Currency, PaymentMethod
from app.domain.value_objects import Money
from app.security.permissions import Perm
from app.ui.dialogs.folio_dialog import (
    PERMISSION_HINT,
    fit_dialog_to_content,
    parse_amount,
    set_action_state,
)
from app.ui.formatting import format_nights, format_short_date
from app.ui.session import UiSession
from app.ui.theme import active_palette
from app.ui.widgets.common import (
    Card,
    SectionTitle,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)

log = get_logger(__name__)


@dataclass(slots=True)
class CheckoutSummary:
    """Cikis ekraninin ihtiyac duydugu tum veriler - ORM'den bagimsiz."""

    stay_id: int
    reservation_room_id: int | None = None
    folio_id: int | None = None
    confirmation_number: str = "-"
    guest_name: str = "-"
    room_number: str = "-"
    check_in: date | None = None
    check_out: date | None = None
    nights: int = 0
    key_card_count: int = 1
    currency: Currency = Currency.TRY
    total_charges: Money = field(default_factory=Money.zero)
    total_payments: Money = field(default_factory=Money.zero)
    balance: Money = field(default_factory=Money.zero)


class CheckoutDialog(QDialog):
    """Misafir cikisi: bakiye kapatma, gec cikis, hasar ve oda karti iadesi."""

    def __init__(
        self,
        ui_session: UiSession,
        stay_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = ui_session
        self.stay_id = stay_id
        self.summary = CheckoutSummary(stay_id=stay_id)
        #: Tahsilat yapildiysa cagiran ekran listesini yenilemelidir.
        self.changed = False

        self.setWindowTitle("Cikis Yap")
        # Alt sinir kucuk tutulur (kucuk ekranli on buro terminalleri),
        # acilis boyutu ise dort karti da kaydirmadan gosterecek kadar buyuk.
        self.setMinimumSize(660, 520)
        self.resize(720, 880)

        self._build()
        self._reload()
        # Boyutlandirma veri YUKLENDIKTEN sonra yapilir: tahsilat karti yalnizca
        # acik bakiyede gorunur, icerik yuksekligini degistirir.
        fit_dialog_to_content(self, self._scroll, width=720)

    # ----------------------------------------------------------------- #
    #  Arayuz
    # ----------------------------------------------------------------- #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)
        outer.addWidget(SectionTitle("Cikis Islemi"))

        # Govde kaydirilabilir: hasar ve tahsilat bolumleri kosullu olarak
        # acilip kapandigi icin icerik yuksekligi degisir. Kaydirma alani
        # olmadan kucuk ekranlarda kartlar sikisir ve girdi kutularinin metni
        # kirpilir (gercekten yasandi, bkz. gorsel dogrulama).
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self._scroll = scroll

        # --- Konaklama ozeti ---
        stay_card = Card("Konaklama", self)
        stay_grid = QGridLayout()
        stay_grid.setSpacing(7)
        stay_grid.setColumnStretch(1, 1)
        self._stay_labels: dict[str, QLabel] = {}
        for row_index, (key, title) in enumerate(
            (
                ("confirmation", "Onay No"),
                ("guest", "Misafir"),
                ("room", "Oda"),
                ("dates", "Tarihler"),
            )
        ):
            name = QLabel(title)
            name.setObjectName("Muted")
            value = QLabel("-")
            value.setWordWrap(True)
            stay_grid.addWidget(name, row_index, 0)
            stay_grid.addWidget(value, row_index, 1)
            self._stay_labels[key] = value
        stay_card.add_layout(stay_grid)
        layout.addWidget(stay_card)

        # --- Folyo ozeti ---
        folio_card = Card("Folyo Ozeti", self)
        folio_grid = QGridLayout()
        folio_grid.setSpacing(6)
        folio_grid.setColumnStretch(1, 1)

        self._charges_label = QLabel("-")
        self._payments_label = QLabel("-")
        self._balance_label = QLabel("-")
        self._balance_label.setObjectName("KpiValue")

        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for row_index, (title, widget) in enumerate(
            (("Toplam Ucret", self._charges_label), ("Odenen", self._payments_label))
        ):
            name = QLabel(title)
            name.setObjectName("Muted")
            widget.setAlignment(right)
            folio_grid.addWidget(name, row_index, 0)
            folio_grid.addWidget(widget, row_index, 1)

        balance_title = QLabel("KALAN BAKIYE")
        balance_title.setObjectName("CardTitle")
        self._balance_label.setAlignment(right)
        folio_grid.addWidget(balance_title, 2, 0)
        folio_grid.addWidget(self._balance_label, 2, 1)

        self._balance_note = QLabel()
        self._balance_note.setWordWrap(True)
        folio_grid.addWidget(self._balance_note, 3, 0, 1, 2)
        folio_card.add_layout(folio_grid)
        layout.addWidget(folio_card)

        # --- Tahsilat ---
        self._payment_card = Card("Tahsilat Al", self)
        payment_row = QGridLayout()
        payment_row.setSpacing(9)
        payment_row.setColumnStretch(1, 1)

        self._amount_edit = QLineEdit()
        self._amount_edit.setPlaceholderText("0,00")
        self._method_combo = QComboBox()
        for value, label in PaymentMethod.choices():
            self._method_combo.addItem(label, value)

        for row_index, (title, widget) in enumerate(
            (("Tutar", self._amount_edit), ("Odeme Yontemi", self._method_combo))
        ):
            name = QLabel(title)
            name.setObjectName("Muted")
            payment_row.addWidget(name, row_index, 0)
            payment_row.addWidget(widget, row_index, 1)
        self._payment_card.add_layout(payment_row)

        payment_buttons = QHBoxLayout()
        payment_buttons.addStretch(1)
        self._collect_button = QPushButton("Tahsilat Yap")
        self._collect_button.setObjectName("Primary")
        self._collect_button.clicked.connect(self._on_collect)
        payment_buttons.addWidget(self._collect_button)
        self._payment_card.add_layout(payment_buttons)
        layout.addWidget(self._payment_card)

        # --- Cikis bilgileri ---
        details_card = Card("Cikis Bilgileri", self)
        details = QGridLayout()
        details.setSpacing(9)
        details.setColumnStretch(1, 1)

        self._late_spin = QSpinBox()
        self._late_spin.setRange(0, 12)
        self._late_spin.setSuffix(" saat")
        self._late_spin.setSpecialValueText("Yok (ucretsiz)")

        self._key_return_spin = QSpinBox()
        self._key_return_spin.setRange(0, 8)
        self._key_return_spin.setSuffix(" adet")

        self._damage_edit = QLineEdit()
        self._damage_edit.setPlaceholderText("Hasar aciklamasi (ornek: kirik lamba)")
        self._damage_edit.textChanged.connect(self._update_damage_state)

        self._damage_amount_edit = QLineEdit()
        self._damage_amount_edit.setPlaceholderText("0,00")
        self._damage_amount_edit.setEnabled(False)
        self._damage_amount_edit.setToolTip(
            "Tutar girebilmek icin once hasar aciklamasi yazilmalidir."
        )

        for row_index, (title, widget) in enumerate(
            (
                ("Gec Cikis", self._late_spin),
                ("Iade Edilen Oda Karti", self._key_return_spin),
                ("Hasar Aciklamasi", self._damage_edit),
                ("Hasar Tutari", self._damage_amount_edit),
            )
        ):
            name = QLabel(title)
            name.setObjectName("Muted")
            details.addWidget(name, row_index, 0)
            details.addWidget(widget, row_index, 1)
        details_card.add_layout(details)
        layout.addWidget(details_card)

        layout.addStretch(1)

        # --- Acik bakiye devri (kaydirma alaninin DISINDA) ---
        # Acik bakiyeli cikisi mumkun kilan TEK kontrol budur; kaydirilabilir
        # govdede dururken diyalogun acilis yuksekliginin altinda kaliyordu.
        # Kullanici "Cikis Yap" -> "once tahsilat alin" hatasini aliyor, cozumun
        # ekranda oldugunu goremiyordu. Engelin cozumu eylemin yaninda durmali.
        self._open_balance_check = QCheckBox("Kalan bakiyeyi cari hesaba devret (yonetici onayi)")
        outer.addWidget(self._open_balance_check)

        # --- Dugmeler (kaydirma alaninin DISINDA; her zaman gorunur) ---
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Iptal")
        cancel.clicked.connect(self.reject)
        self._checkout_button = QPushButton("Cikis Yap")
        self._checkout_button.setObjectName("Primary")
        self._checkout_button.setDefault(True)
        self._checkout_button.clicked.connect(self._on_checkout)
        buttons.addWidget(cancel)
        buttons.addWidget(self._checkout_button)
        outer.addLayout(buttons)

        # --- Yetki kisitlari ---
        if not self.ui.can(Perm.FRONTDESK_EARLY_LATE):
            self._late_spin.setEnabled(False)
            self._late_spin.setToolTip(
                "Gec cikis ucreti islemek icin 'Erken giris / gec cikis onayi' yetkisi gerekiyor."
            )
            # Stil sayfasinda QSpinBox icin ayri bir "devre disi" gorunumu yok;
            # kisit metinle yazilmazsa alan etkin sanilir ve kullanici neden
            # yazamadigini ancak fareyi ustunde bekleterek anlar.
            self._late_spin.setSpecialValueText("Yetkiniz yok")
        can_receive = self.ui.can(Perm.PAYMENT_RECEIVE)
        set_action_state(
            self._collect_button,
            enabled=can_receive,
            tooltip=(
                "Girilen tutari folyoya tahsilat olarak isler."
                if can_receive
                else PERMISSION_HINT.format(name="Odeme alma")
            ),
        )
        can_finance = self.ui.can(Perm.FINANCE_MANAGE)
        self._open_balance_check.setEnabled(can_finance)
        if not can_finance:
            # QCheckBox'in da devre disi gorunumu stil sayfasinda tanimli degil.
            self._open_balance_check.setText(
                "Kalan bakiyeyi cari hesaba devret (yetkiniz yok - yoneticiye basvurun)"
            )
        self._open_balance_check.setToolTip(
            "Bakiye kapanmadan cikis yapilmasini saglar; islem denetim gunlugune yazilir."
            if can_finance
            else PERMISSION_HINT.format(name="Gelir/gider kaydi yonetimi")
        )

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def _reload(self) -> None:
        try:
            self.summary = self._load()
        except HotelError as exc:
            show_error(self, exc)
            set_action_state(
                self._checkout_button,
                enabled=False,
                tooltip="Konaklama bilgisi okunamadi; pencereyi kapatip yeniden deneyin.",
            )
            return
        self._render()

    def _load(self) -> CheckoutSummary:
        """Konaklama ve folyo bilgisini duz veri yapisina cevirir."""
        from app.infrastructure.db.models.reservations import Stay

        with self.ui.service_context(commit=False) as ctx:
            ctx.require(Perm.RESERVATION_VIEW)

            stay = ctx.session.get(Stay, self.stay_id)
            if stay is None:
                from app.core.exceptions import NotFoundError

                raise NotFoundError("Konaklama", self.stay_id)

            row = stay.reservation_room
            reservation = row.reservation if row is not None else None
            guest = reservation.primary_guest if reservation is not None else None
            currency = reservation.currency if reservation is not None else Currency.TRY

            summary = CheckoutSummary(
                stay_id=stay.id,
                reservation_room_id=row.id if row is not None else None,
                confirmation_number=(
                    reservation.confirmation_number if reservation is not None else "-"
                ),
                guest_name=guest.full_name if guest is not None else "-",
                room_number=stay.room.number if stay.room is not None else "-",
                check_in=row.check_in_date if row is not None else None,
                check_out=row.check_out_date if row is not None else None,
                nights=row.nights if row is not None else 0,
                key_card_count=stay.key_card_count,
                currency=currency,
            )

            folio = FolioService(ctx).folio_for_room(row.id) if row is not None else None
            if folio is not None:
                folio.recalculate()
                summary.folio_id = folio.id
                summary.currency = folio.currency
                summary.total_charges = Money.of(folio.total_charges, folio.currency)
                summary.total_payments = Money.of(folio.total_payments, folio.currency)
                summary.balance = Money.of(folio.balance, folio.currency)
            return summary

    # ----------------------------------------------------------------- #
    #  Cizim
    # ----------------------------------------------------------------- #
    def _render(self) -> None:
        summary = self.summary
        palette = active_palette()

        self._stay_labels["confirmation"].setText(summary.confirmation_number)
        self._stay_labels["guest"].setText(summary.guest_name)
        self._stay_labels["room"].setText(summary.room_number)
        self._stay_labels["dates"].setText(
            f"{format_short_date(summary.check_in)} - {format_short_date(summary.check_out)}"
            f"  ({format_nights(summary.nights)})"
        )

        self._charges_label.setText(summary.total_charges.format())
        self._payments_label.setText(summary.total_payments.format())
        self._balance_label.setText(summary.balance.format())

        has_balance = summary.balance.amount > 0
        if summary.folio_id is None:
            self._balance_label.setStyleSheet(f"color: {palette.text_muted};")
            self._balance_note.setObjectName("Muted")
            self._balance_note.setText("Bu konaklama icin acik folyo bulunmuyor.")
        elif has_balance:
            self._balance_label.setStyleSheet(f"color: {palette.danger};")
            self._balance_note.setObjectName("BadgeDanger")
            self._balance_note.setText("Bakiye acik. Cikis yapabilmek icin once tahsilat alin.")
        else:
            self._balance_label.setStyleSheet(f"color: {palette.success};")
            self._balance_note.setObjectName("BadgeSuccess")
            self._balance_note.setText("Hesap kapali; cikis yapilabilir.")
        self._balance_note.style().unpolish(self._balance_note)
        self._balance_note.style().polish(self._balance_note)

        self._payment_card.setVisible(has_balance and summary.folio_id is not None)
        if has_balance:
            self._amount_edit.setText(summary.balance.format(with_symbol=False))

        self._key_return_spin.setMaximum(max(summary.key_card_count, 8))
        self._key_return_spin.setValue(summary.key_card_count)

        self._open_balance_check.setVisible(has_balance)

    def _update_damage_state(self) -> None:
        """Aciklama olmadan hasar tutari girilemez.

        Servis katmani da ayni kurali uygular (``ValidationError``); buradaki
        kilit, kullanicinin tutar yazip sonra reddedilmesini onler.
        """
        has_description = bool(self._damage_edit.text().strip())
        self._damage_amount_edit.setEnabled(has_description)
        if not has_description:
            self._damage_amount_edit.clear()

    # ----------------------------------------------------------------- #
    #  Islemler
    # ----------------------------------------------------------------- #
    def _on_collect(self) -> None:
        if self.summary.folio_id is None:
            return
        try:
            amount = parse_amount(self._amount_edit.text(), field_name="amount")
        except ValidationError as exc:
            show_error(self, exc, title="Tahsilat yapilamadi")
            return

        method = PaymentMethod(self._method_combo.currentData())
        try:
            with self.ui.service_context() as ctx:
                FolioService(ctx).add_payment(
                    self.summary.folio_id,
                    amount=amount,
                    method=method,
                )
        except PaymentError as exc:
            if exc.code == "overpayment":
                exc.context["cozum"] = (
                    "Tutari kalan bakiyeye esitleyin. Bilincli fazla odeme icin folyo "
                    "ekranindan islem yapin."
                )
            show_error(self, exc, title="Tahsilat yapilamadi")
            return
        except HotelError as exc:
            show_error(self, exc, title="Tahsilat yapilamadi")
            return

        self.changed = True
        show_toast(self, "Tahsilat kaydedildi.", ToastLevel.SUCCESS)
        self._reload()

    def _on_checkout(self) -> None:
        damage_description = self._damage_edit.text().strip()
        damage_charge = Decimal("0.00")
        if damage_description and self._damage_amount_edit.text().strip():
            try:
                damage_charge = parse_amount(
                    self._damage_amount_edit.text(), field_name="damage_charge"
                )
            except ValidationError as exc:
                show_error(self, exc, title="Cikis yapilamadi")
                return

        # Cikis GERI ALINAMAZ: folyo kapanir, konaklama sonlanir ve oda kirliye
        # duser. dangerous=True varsayilan dugmeyi "Hayir" yapar; Enter'a basan
        # kullanici islemi kazara onaylayamaz.
        if not confirm(
            self,
            f"{self.summary.room_number} numarali odadan cikis yapilsin mi?",
            detail=(
                "Folyo kapatilir, oda kirli olarak isaretlenir ve temizlik gorevi olusturulur. "
                "Bu islem geri alinamaz."
            ),
            dangerous=True,
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                FrontdeskService(ctx).check_out(
                    self.stay_id,
                    late_check_out_hours=self._late_spin.value(),
                    key_cards_returned=self._key_return_spin.value(),
                    damage_description=damage_description or None,
                    damage_charge=damage_charge,
                    allow_open_balance=self._open_balance_check.isChecked(),
                )
        except PaymentError as exc:
            cozum = (
                "Once tahsilat yapin: yukaridaki 'Tahsilat Al' bolumunden kalan bakiyeyi "
                "tahsil edin, sonra cikis yapin."
            )
            # Devir secenegi yalnizca yetkisi olana onerilir; yoksa kullaniciyi
            # yapamayacagi bir cozume yonlendirmis oluruz.
            if self._open_balance_check.isEnabled():
                cozum += (
                    " Tahsilat mumkun degilse 'Kalan bakiyeyi cari hesaba devret' kutusunu "
                    "isaretleyerek acik bakiyeyle cikis yapabilirsiniz."
                )
            exc.context["cozum"] = cozum
            show_error(self, exc, title="Cikis yapilamadi")
            self._reload()
            return
        except HotelError as exc:
            if exc.code == "already_checked_out":
                exc.context["cozum"] = "Bu konaklama icin cikis zaten yapilmis; listeyi yenileyin."
            show_error(self, exc, title="Cikis yapilamadi")
            return

        self.changed = True
        self.accept()


__all__ = ["CheckoutDialog", "CheckoutSummary"]
