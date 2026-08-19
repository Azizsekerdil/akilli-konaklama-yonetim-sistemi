"""Rezervasyon listesi ekrani.

Ekran uc bolumden olusur:

* **Suzgecler** - serbest metin aramasi, durum ve hizli tarih araligi.
* **Liste** - onay numarasi, misafir, oda, tarihler, durum ve tutar.
* **Ayrinti** - secili rezervasyonun misafir/oda/tutar bilgisi ve eylemleri.

Iki tasarim karari acikca belgelenmeye deger:

1. **ORM nesnesi ekrana tasinmaz.** Veriler ``service_context`` blogu
   icinde :class:`ReservationRow` / :class:`RoomLine` gibi duz veri
   yapilarina cevrilir. Aksi halde blok bitince nesneler detached olur ve
   ``reservation.rooms`` gibi bir iliskiye erisim ``DetachedInstanceError``
   firlatir - hem de tam kullanici satira tikladiginda.
2. **Dugme etkinligi elle hesaplanmaz.** Onayla / Iptal Et / Gelmedi
   dugmeleri :func:`~app.domain.rules.reservation_state.available_actions`
   sonucundan turetilir. Durum makinesi tek dogruluk kaynagidir; arayuzde
   ikinci bir kopya tutmak, kural degistiginde sessizce yanlis dugme
   gostermek demektir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.services.reservation_service import ReservationService
from app.core.exceptions import HotelError, ValidationError
from app.core.log import get_logger
from app.domain.enums import ReservationSource, ReservationStatus
from app.domain.rules.reservation_state import available_actions
from app.domain.value_objects import Money
from app.infrastructure.db.base import utcnow
from app.security.permissions import Perm
from app.ui.formatting import format_number, format_short_date
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.theme import active_palette
from app.ui.widgets.common import (
    Card,
    EmptyState,
    SearchBox,
    SectionTitle,
    StatusBadge,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

if TYPE_CHECKING:
    from app.infrastructure.db.models.reservations import Reservation

log = get_logger(__name__)


# --------------------------------------------------------------------------
#  Ekrana tasinan duz veri yapilari
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RoomLine:
    """Rezervasyonun tek bir oda satiri - gosterime hazir hali."""

    room_number: str
    room_type_name: str
    check_in: date
    check_out: date
    nights: int
    adults: int
    children: int
    meal_plan: str
    total: Money
    is_cancelled: bool

    def describe(self) -> str:
        """Ayrinti panelinde tek satirlik ozet."""
        people = f"{self.adults} yetiskin"
        if self.children:
            people += f" + {self.children} cocuk"
        text = (
            f"{self.room_number} - {self.room_type_name} - "
            f"{format_short_date(self.check_in)} / {format_short_date(self.check_out)} "
            f"({self.nights} gece, {people}) - {self.total.format()}"
        )
        if self.is_cancelled:
            text += "  [iptal]"
        return text


@dataclass(frozen=True, slots=True)
class ReservationRow:
    """Tablo satiri - hicbir ORM baglantisi tasimaz."""

    reservation_id: int
    confirmation_number: str
    guest_name: str
    guest_phone: str
    guest_email: str
    guest_vip: str
    is_blacklisted: bool
    rooms_text: str
    check_in: date
    check_out: date
    nights: int
    status: ReservationStatus
    source: ReservationSource
    total: Money
    paid: Money
    deposit: Money
    balance: Money
    special_requests: str
    cancellation_reason: str
    room_lines: tuple[RoomLine, ...]


#: Durum -> rozet seviyesi. Renk tek basina anlam tasimaz; rozet her zaman
#: durumun Turkce etiketini de yazar (erisilebilirlik gerekliligi).
_BADGE_LEVELS: dict[ReservationStatus, str] = {
    ReservationStatus.DRAFT: "info",
    ReservationStatus.TENTATIVE: "warning",
    ReservationStatus.CONFIRMED: "success",
    ReservationStatus.CHECKED_IN: "info",
    ReservationStatus.CHECKED_OUT: "info",
    ReservationStatus.CANCELLED: "danger",
    ReservationStatus.NO_SHOW: "danger",
    ReservationStatus.WAITLIST: "warning",
}

#: Hizli tarih suzgeci secenekleri: ``(anahtar, etiket)``.
_PERIODS: tuple[tuple[str, str], ...] = (
    ("all", "Tumu"),
    ("today", "Bugun"),
    ("week", "Bu hafta"),
    ("month", "Bu ay"),
    ("future", "Gelecek"),
)


def plain_label(
    text: str = "", *, name: str | None = None, parent: QWidget | None = None
) -> QLabel:
    """Kart uzerinde dogru gorunen duz metin etiketi.

    Stil sayfasindaki genel ``QWidget`` kurali arka plani **sayfa zemini**
    yapar. QLabel arka planini fiilen boyadigi icin, bir kartin (yuzey rengi)
    uzerindeki etiket koyu bir dikdortgen olarak gorunur ve arayuz kirli
    durur. Burada yalnizca saydamlik veriliyor - hicbir renk kodu
    sabitlenmiyor, metin rengi stil sayfasindan gelmeye devam ediyor.
    """
    label = QLabel(text, parent)
    if name:
        label.setObjectName(name)
    label.setStyleSheet("background: transparent;")
    return label


def transparent_panel(widget: QWidget, name: str) -> QWidget:
    """Kart uzerine oturan duz kapsayici bileseni saydam yapar.

    Stil sayfasindaki genel ``QWidget { background-color: ... }`` kurali
    yalnizca etiketleri degil, **her duz kapsayiciyi** da boyar. Kartin
    (yuzey rengi) uzerinde duran bir ``QWidget``, sayfa zemini renginde koyu
    bir dikdortgen olarak gorunur; olculen fark #12171E'ye karsi #1A2029'dur.

    Kural bilerek nesne adiyla sinirlandirilir: secicisiz bir
    ``setStyleSheet`` cagrisi alt bilesenlere de miras kalir ve arka plani
    anlam tasiyan bilesenleri (durum rozeti gibi) de saydamlastirirdi.
    """
    widget.setObjectName(name)
    widget.setStyleSheet(f"#{name} {{ background: transparent; }}")
    return widget


def flat_empty_state(state: EmptyState, name: str) -> EmptyState:
    """Bos durum panelini kart yuzeyine oturtur.

    :class:`~app.ui.widgets.common.EmptyState` duz bir ``QWidget`` ve icindeki
    ikon/mesaj/ipucu duz ``QLabel``'lerdir; hepsi genel kuraldan sayfa zeminini
    alir. Kartin ortasinda kocaman koyu bir dikdortgen olarak gorunur - tam
    olarak "bos tablo birakma" kuralinin onlemek istedigi izlenim.
    """
    transparent_panel(state, name)
    for label in state.findChildren(QLabel):
        label.setStyleSheet("background: transparent;")
    return state


def flat_card(title: str | None = None, parent: QWidget | None = None) -> Card:
    """Baslik etiketi kart yuzeyine oturan :class:`Card`.

    :class:`~app.ui.widgets.common.Card` baslik etiketini ``QLabel#CardTitle``
    olarak olusturur; o etiketin arka plani genel ``QWidget`` kuralindan
    (sayfa zemini) gelir ve kartin ustunde koyu bir serit olarak gorunur.
    Ortak bileseni degistirmeden, uretilen etiketi saydam yapiyoruz.
    """
    card = Card(title, parent)
    for label in card.findChildren(QLabel):
        label.setStyleSheet("background: transparent;")
    return card


def apply_action_style(button: QPushButton, *, enabled: bool, accent: str) -> None:
    """Dugmeyi etkinlestirir ve gorunumunu durumuyla tutarli tutar.

    Stil sayfasinda ``QPushButton#Primary`` / ``#Danger`` kurallarinin
    ``:disabled`` karsiligi yoktur. Nesne adi pasif durumda da birakilirsa
    dugme dolu renkte gorunur; kullanici tiklanabilir sanip bosuna dener.
    Bu yuzden vurgu adi yalnizca dugme etkinken verilir.
    """
    button.setEnabled(enabled)
    button.setObjectName(accent if enabled else "")
    button.style().unpolish(button)
    button.style().polish(button)


def status_color(status: ReservationStatus) -> str:
    """Durum metninin rengi - **etiketin yerine gecmez**, yalnizca destekler.

    Renk kod icinde sabitlenmez; etkin paletten okunur ki tema degistiginde
    liste de degissin.
    """
    palette = active_palette()
    mapping = {
        ReservationStatus.DRAFT: palette.text_muted,
        ReservationStatus.TENTATIVE: palette.warning,
        ReservationStatus.CONFIRMED: palette.success,
        ReservationStatus.CHECKED_IN: palette.info,
        ReservationStatus.CHECKED_OUT: palette.text_muted,
        ReservationStatus.CANCELLED: palette.danger,
        ReservationStatus.NO_SHOW: palette.danger,
        ReservationStatus.WAITLIST: palette.warning,
    }
    return mapping.get(status, palette.text)


class ReservationsPage(BasePage):
    """Rezervasyonlari listeler, suzer ve durum gecislerini yonetir."""

    required_permission = Perm.RESERVATION_VIEW
    title = "Rezervasyonlar"
    icon = "\U0001f4c5"

    #: Tek seferde cekilen azami kayit. Suzgecler istemci tarafinda
    #: calistigi icin liste bellekte tutulur; sinir, cok yillik arsivde
    #: acilis suresinin patlamasini onler.
    ROW_LIMIT = 500

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._selected: ReservationRow | None = None

        self._build_header()
        self._build_filters()
        self._build_body()

    def _build_header(self) -> None:
        header = QHBoxLayout()

        self._title_label = SectionTitle(t("reservation.title"))
        self._summary_label = plain_label("-", name="Muted")

        self._refresh_button = QPushButton(t("common.refresh"))
        self._refresh_button.clicked.connect(lambda: self.refresh(force=True))

        self._new_button = QPushButton(t("reservation.new"))
        self._new_button.clicked.connect(self._open_new_reservation)
        # Arayuz tek savunma degildir: servis katmani ayni izni yeniden
        # kontrol eder. Dugmeyi kapatmak yalnizca kullaniciyi bosuna
        # ugrastirmamak icindir.
        can_create = self.ui.can(Perm.RESERVATION_CREATE)
        apply_action_style(self._new_button, enabled=can_create, accent="Primary")
        if not can_create:
            self._new_button.setToolTip("Rezervasyon olusturma yetkiniz bulunmuyor.")

        header.addWidget(self._title_label)
        header.addSpacing(12)
        header.addWidget(self._summary_label)
        header.addStretch(1)
        header.addWidget(self._refresh_button)
        header.addWidget(self._new_button)
        self.root_layout.addLayout(header)

    def _build_filters(self) -> None:
        card = flat_card(parent=self)
        line = QHBoxLayout()
        line.setSpacing(10)

        self._search = SearchBox("Onay no, misafir adi veya oda numarasi ara")
        self._search.search_triggered.connect(self.set_search_query)
        self._search.setMinimumWidth(280)

        status_label = plain_label(t("reservation.status") + ":", name="Muted")
        self._status_combo = QComboBox()
        self._status_combo.addItem("Tumu", None)
        for value, label in ReservationStatus.choices():
            self._status_combo.addItem(label, value)
        self._status_combo.currentIndexChanged.connect(lambda _: self._apply_filters())

        period_label = plain_label("Tarih:", name="Muted")
        self._period_combo = QComboBox()
        for key, label in _PERIODS:
            self._period_combo.addItem(label, key)
        self._period_combo.currentIndexChanged.connect(lambda _: self._apply_filters())

        line.addWidget(self._search, 1)
        line.addWidget(status_label)
        line.addWidget(self._status_combo)
        line.addWidget(period_label)
        line.addWidget(self._period_combo)

        card.add_layout(line)
        self.root_layout.addWidget(card)

    def _build_body(self) -> None:
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_table_card())
        splitter.addWidget(self._build_detail_card())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([460, 300])
        self.root_layout.addWidget(splitter, 1)

    def _build_table_card(self) -> QWidget:
        card = flat_card("Rezervasyon Listesi", self)

        self._table = FilterableTableView(
            [
                Column("confirmation_number", "Onay No", width=130),
                Column("guest_name", t("reservation.guest"), stretch=True),
                Column("rooms_text", t("reservation.room"), width=110),
                Column(
                    "check_in",
                    t("reservation.check_in"),
                    formatter=format_short_date,
                    width=100,
                ),
                Column(
                    "check_out",
                    t("reservation.check_out"),
                    formatter=format_short_date,
                    width=100,
                ),
                Column(
                    "nights",
                    t("reservation.nights"),
                    width=60,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column(
                    "status",
                    t("reservation.status"),
                    formatter=lambda value: value.label,
                    color_getter=lambda row: status_color(row.status),
                    width=120,
                ),
                Column(
                    "total",
                    t("reservation.total"),
                    width=120,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column(
                    "balance",
                    t("reservation.balance"),
                    width=120,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
            ],
            parent=self,
        )
        self._table.selection_changed.connect(self._show_detail)
        self._table.row_activated.connect(self._on_row_activated)

        # Bos tablo birakmak yerine ne oldugunu anlatan bir durum gosterilir.
        # Yigin da duz bir QWidget'tir: saydamlastirilmazsa uzerindeki bos
        # durum paneli saydam olsa bile altindan sayfa zemini gorunur.
        self._stack = transparent_panel(QStackedWidget(self), "ReservationTableStack")
        self._stack.addWidget(self._table)
        self._stack.addWidget(
            flat_empty_state(
                EmptyState(
                    "Suzgeclerle eslesen rezervasyon yok",
                    hint="Arama metnini veya durum/tarih suzgecini genisletmeyi deneyin.",
                    icon="\U0001f50d",
                    parent=self,
                ),
                "ReservationNoMatch",
            )
        )
        self._stack.addWidget(
            flat_empty_state(
                EmptyState(
                    "Bu tesiste henuz rezervasyon yok",
                    hint="Yeni Rezervasyon dugmesi ile ilk kaydi olusturabilirsiniz.",
                    icon="\U0001f4c5",
                    parent=self,
                ),
                "ReservationNone",
            )
        )
        card.add_widget(self._stack)
        return card

    def _build_detail_card(self) -> QWidget:
        card = flat_card("Rezervasyon Ayrintisi", self)

        self._detail_stack = transparent_panel(QStackedWidget(self), "ReservationDetailStack")
        self._detail_stack.addWidget(
            flat_empty_state(
                EmptyState(
                    "Ayrinti icin bir rezervasyon secin",
                    hint="Listeden bir satira tiklayin veya cift tiklayin.",
                    icon="\U0001f446",
                    parent=self,
                ),
                "ReservationDetailEmpty",
            )
        )

        content = transparent_panel(QWidget(self), "ReservationDetailBody")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        # --- Baslik satiri ---
        title_row = QHBoxLayout()
        self._detail_number = plain_label("-", name="SectionTitle")
        self._detail_badge = StatusBadge("-", "info", self)
        self._detail_source = plain_label("-", name="Muted")
        title_row.addWidget(self._detail_number)
        title_row.addWidget(self._detail_badge)
        title_row.addWidget(self._detail_source)
        title_row.addStretch(1)
        body.addLayout(title_row)

        # --- Uc sutun: misafir / odalar / tutar ---
        columns = QHBoxLayout()
        columns.setSpacing(18)

        guest_box = QVBoxLayout()
        guest_box.setSpacing(3)
        guest_box.addWidget(self._section_caption("Misafir"))
        self._detail_guest = plain_label("-")
        self._detail_guest.setWordWrap(True)
        self._detail_contact = plain_label("-", name="Muted")
        self._detail_contact.setWordWrap(True)
        self._detail_alert = QLabel("")
        self._detail_alert.setObjectName("BadgeDanger")
        self._detail_alert.setVisible(False)
        guest_box.addWidget(self._detail_guest)
        guest_box.addWidget(self._detail_contact)
        guest_box.addWidget(self._detail_alert)
        guest_box.addStretch(1)

        rooms_box = QVBoxLayout()
        rooms_box.setSpacing(3)
        rooms_box.addWidget(self._section_caption("Odalar"))
        self._detail_rooms = plain_label("-")
        self._detail_rooms.setWordWrap(True)
        self._detail_requests = plain_label("", name="Muted")
        self._detail_requests.setWordWrap(True)
        rooms_box.addWidget(self._detail_rooms)
        rooms_box.addWidget(self._detail_requests)
        rooms_box.addStretch(1)

        money_box = QVBoxLayout()
        money_box.setSpacing(3)
        money_box.addWidget(self._section_caption("Tutar"))
        self._detail_amounts = plain_label("-")
        self._detail_amounts.setWordWrap(True)
        money_box.addWidget(self._detail_amounts)
        money_box.addStretch(1)

        columns.addLayout(guest_box, 3)
        columns.addLayout(rooms_box, 4)
        columns.addLayout(money_box, 2)
        body.addLayout(columns, 1)

        # --- Eylemler ---
        actions = QHBoxLayout()
        self._confirm_button = QPushButton("Onayla")
        self._confirm_button.clicked.connect(self._on_confirm)

        self._cancel_button = QPushButton("Iptal Et")
        self._cancel_button.clicked.connect(self._on_cancel)

        self._no_show_button = QPushButton("Gelmedi Isaretle")
        self._no_show_button.clicked.connect(self._on_no_show)

        self._action_hint = plain_label("", name="Muted")
        self._action_hint.setWordWrap(True)

        actions.addWidget(self._action_hint, 1)
        actions.addWidget(self._confirm_button)
        actions.addWidget(self._cancel_button)
        actions.addWidget(self._no_show_button)
        body.addLayout(actions)

        self._detail_stack.addWidget(content)
        card.add_widget(self._detail_stack)

        self._show_detail(None)
        return card

    def _section_caption(self, text: str) -> QLabel:
        return plain_label(text.upper(), name="CardTitle")

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        from app.infrastructure.db.repositories import ReservationRepository

        with self.ui.service_context(commit=False) as ctx:
            ctx.require(Perm.RESERVATION_VIEW)
            reservations = ReservationRepository(ctx.session).search(
                ctx.require_property(), limit=self.ROW_LIMIT
            )
            # Oturum kapanmadan tum iliskiler duz veriye cevrilir.
            rows = [_to_row(reservation) for reservation in reservations]

        log.debug("rezervasyon_listesi_yuklendi", count=len(rows))
        self._table.set_rows(rows)
        self._apply_filters()
        self._show_detail(None)

    # ----------------------------------------------------------------- #
    #  Suzgecler
    # ----------------------------------------------------------------- #
    def set_search_query(self, text: str) -> None:
        """Serbest metin aramasini uygular.

        :class:`~app.ui.widgets.common.SearchBox` tus vuruslarini geciktirir;
        bu yontem hem o sinyale hem de programatik cagrilara acik kapidir.
        """
        self._table.set_query(text)
        self._update_view_state()

    def _apply_filters(self) -> None:
        self._table.set_predicate(self._row_matches)
        self._update_view_state()

    def _row_matches(self, row: ReservationRow) -> bool:
        """Durum ve tarih suzgeclerini birlikte uygular."""
        selected = self._status_combo.currentData()
        if selected is not None and row.status.value != selected:
            return False
        return self._matches_period(row)

    def _matches_period(self, row: ReservationRow) -> bool:
        period = self._period_combo.currentData() or "all"
        if period == "all":
            return True

        # ``date.today()`` yerel saat dilimine baglidir; kayitlarin tamami
        # UTC oldugu icin gun sinirini da UTC'den turetiyoruz.
        today = utcnow().date()
        if period == "future":
            return row.check_in > today

        if period == "today":
            window = (today, today + timedelta(days=1))
        elif period == "week":
            start = today - timedelta(days=today.weekday())
            window = (start, start + timedelta(days=7))
        else:  # month
            start = today.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1)
            window = (start, end)

        # Yari acik aralik kurali: cikis gunu konaklamaya dahil degildir.
        return row.check_in < window[1] and row.check_out > window[0]

    def _update_view_state(self) -> None:
        visible = self._table.visible_count
        total = self._table.total_count
        self._summary_label.setText(
            f"{format_number(visible)} rezervasyon gosteriliyor "
            f"(toplam {format_number(total)})."
        )
        if total == 0:
            self._stack.setCurrentIndex(2)
        elif visible == 0:
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)

    # ----------------------------------------------------------------- #
    #  Ayrinti paneli
    # ----------------------------------------------------------------- #
    def _on_row_activated(self, row: ReservationRow) -> None:
        """Cift tiklama - ayrinti panelini acar ve one getirir."""
        self._show_detail(row)
        self._detail_stack.setFocus()

    def _show_detail(self, row: object) -> None:
        if not isinstance(row, ReservationRow):
            self._selected = None
            self._detail_stack.setCurrentIndex(0)
            self._update_actions(None)
            return

        self._selected = row
        self._detail_stack.setCurrentIndex(1)

        self._detail_number.setText(row.confirmation_number)
        self._detail_badge.set_status(row.status.label, _BADGE_LEVELS.get(row.status, "info"))
        self._detail_source.setText(f"Kanal: {row.source.label}")

        self._detail_guest.setText(row.guest_name)
        contact = " | ".join(part for part in (row.guest_phone, row.guest_email) if part)
        if row.guest_vip:
            contact = f"{row.guest_vip} | {contact}" if contact else row.guest_vip
        self._detail_contact.setText(contact or "Iletisim bilgisi girilmemis.")
        self._detail_alert.setVisible(row.is_blacklisted)
        if row.is_blacklisted:
            self._detail_alert.setText("Misafir kara listede")

        lines = [line.describe() for line in row.room_lines]
        self._detail_rooms.setText("\n".join(lines) if lines else "Oda satiri bulunmuyor.")

        notes = []
        if row.special_requests:
            notes.append(f"Ozel istek: {row.special_requests}")
        if row.cancellation_reason:
            notes.append(f"Iptal gerekcesi: {row.cancellation_reason}")
        self._detail_requests.setText("\n".join(notes))
        self._detail_requests.setVisible(bool(notes))

        self._detail_amounts.setText(
            f"Toplam: {row.total.format()}\n"
            f"Depozito: {row.deposit.format()}\n"
            f"Tahsil edilen: {row.paid.format()}\n"
            f"Bakiye: {row.balance.format()}"
        )
        self._update_actions(row)

    def _update_actions(self, row: ReservationRow | None) -> None:
        """Dugme etkinliklerini **durum makinesinden** turetir."""
        if row is None:
            apply_action_style(self._confirm_button, enabled=False, accent="Primary")
            apply_action_style(self._cancel_button, enabled=False, accent="Danger")
            apply_action_style(self._no_show_button, enabled=False, accent="")
            self._action_hint.setText("")
            return

        actions = available_actions(row.status)
        apply_action_style(
            self._confirm_button,
            enabled=actions["confirm"] and self.ui.can(Perm.RESERVATION_EDIT),
            accent="Primary",
        )
        apply_action_style(
            self._cancel_button,
            enabled=actions["cancel"] and self.ui.can(Perm.RESERVATION_CANCEL),
            accent="Danger",
        )
        apply_action_style(
            self._no_show_button,
            enabled=actions["mark_no_show"] and self.ui.can(Perm.RESERVATION_CANCEL),
            accent="",
        )

        if not any((actions["confirm"], actions["cancel"], actions["mark_no_show"])):
            self._action_hint.setText(
                f"'{row.status.label}' durumundaki bir rezervasyon uzerinde "
                "durum degisikligi yapilamaz."
            )
        else:
            self._action_hint.setText("")

    # ----------------------------------------------------------------- #
    #  Eylemler
    # ----------------------------------------------------------------- #
    def _open_new_reservation(self) -> None:
        from app.ui.dialogs.reservation_dialog import ReservationDialog

        dialog = ReservationDialog(self.ui, parent=self)
        if dialog.exec() != ReservationDialog.DialogCode.Accepted:
            return

        number = dialog.created_confirmation or ""
        show_toast(self, t("reservation.created", number=number), ToastLevel.SUCCESS)
        self.refresh(force=True)
        if dialog.created_reservation_id is not None:
            self._select_reservation(dialog.created_reservation_id)

    def _on_confirm(self) -> None:
        row = self._selected
        if row is None:
            return
        if not confirm(
            self,
            f"{row.confirmation_number} numarali rezervasyon onaylansin mi?",
            detail=f"{row.guest_name} - {format_short_date(row.check_in)}",
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                ReservationService(ctx).confirm(row.reservation_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, f"{row.confirmation_number} onaylandi.", ToastLevel.SUCCESS)
        self._reload_keeping_selection(row.reservation_id)

    def _on_cancel(self) -> None:
        row = self._selected
        if row is None:
            return

        reason = self._ask_cancellation_reason(row)
        if reason is None:  # kullanici vazgecti
            return
        reason = reason.strip()
        if not reason:
            # Servis de ayni kurali uygular; burada yakalamak kullaniciya
            # bosuna bir sunucu turu attirmamak icindir.
            show_error(self, ValidationError("Iptal gerekcesi zorunludur.", field="reason"))
            return

        if not confirm(
            self,
            f"{row.confirmation_number} numarali rezervasyon iptal edilsin mi?",
            detail=f"Gerekce: {reason}\nIptal ucreti tarifeye gore hesaplanacaktir.",
            dangerous=True,
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                _, fee = ReservationService(ctx).cancel(row.reservation_id, reason=reason)
                fee_text = fee.format()
        except HotelError as exc:
            show_error(self, exc)
            return

        self._show_fee_notice(
            "Rezervasyon iptal edildi",
            f"{row.confirmation_number} iptal edildi.\n\nHesaplanan iptal ucreti: {fee_text}",
        )
        self._reload_keeping_selection(row.reservation_id)

    def _on_no_show(self) -> None:
        row = self._selected
        if row is None:
            return
        if not confirm(
            self,
            f"{row.confirmation_number} 'gelmedi' olarak isaretlensin mi?",
            detail="Bu islem odalari serbest birakir ve tarifeye gore ceza ucreti hesaplar.",
            dangerous=True,
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                _, fee = ReservationService(ctx).mark_no_show(row.reservation_id)
                fee_text = fee.format()
        except HotelError as exc:
            show_error(self, exc)
            return

        self._show_fee_notice(
            "Gelmedi olarak isaretlendi",
            f"{row.confirmation_number} 'gelmedi' olarak isaretlendi.\n\n"
            f"Hesaplanan ceza ucreti: {fee_text}",
        )
        self._reload_keeping_selection(row.reservation_id)

    # ----------------------------------------------------------------- #
    #  Kullanici etkilesimi (testlerde degistirilebilir olsun diye ayri)
    # ----------------------------------------------------------------- #
    def _ask_cancellation_reason(self, row: ReservationRow) -> str | None:
        """Iptal gerekcesini sorar; kullanici vazgecerse ``None`` doner."""
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Iptal Gerekcesi",
            f"{row.confirmation_number} neden iptal ediliyor?",
        )
        return text if accepted else None

    def _show_fee_notice(self, title: str, message: str) -> None:
        """Hesaplanan ucreti kalici bir kutuda gosterir.

        Bildirim (toast) yerine kutu kullaniliyor: iptal/ceza ucreti mali bir
        sonuctur, kullanicinin gormeden kaybetmemesi gerekir.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(message)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    # ----------------------------------------------------------------- #
    #  Yardimcilar
    # ----------------------------------------------------------------- #
    def _reload_keeping_selection(self, reservation_id: int) -> None:
        self.refresh(force=True)
        self._select_reservation(reservation_id)

    def _select_reservation(self, reservation_id: int) -> None:
        """Yenileme sonrasi ayni kaydi yeniden secer."""
        for position, row in enumerate(self._table.visible_rows()):
            if isinstance(row, ReservationRow) and row.reservation_id == reservation_id:
                self._table.table.selectRow(position)
                return
        self._show_detail(None)


# --------------------------------------------------------------------------
#  ORM -> duz veri donusumu
# --------------------------------------------------------------------------
def _to_row(reservation: Reservation) -> ReservationRow:
    """Rezervasyonu tablo satirina cevirir.

    **Yalnizca acik bir oturum icinde cagrilmalidir**; iliskilere burada
    erisilir ki ekran katmani detached nesnelerle ugrasmasin.
    """
    guest = reservation.primary_guest
    currency = reservation.currency

    room_lines = tuple(
        RoomLine(
            room_number=row.room.number if row.room else "Atanmadi",
            room_type_name=row.room_type.name if row.room_type else "-",
            check_in=row.check_in_date,
            check_out=row.check_out_date,
            nights=row.nights,
            adults=row.adults,
            children=row.children,
            meal_plan=row.meal_plan.label,
            total=Money.of(row.total_amount, currency),
            is_cancelled=row.is_cancelled,
        )
        for row in reservation.rooms
    )

    numbers = [line.room_number for line in room_lines if line.room_number != "Atanmadi"]
    if numbers:
        rooms_text = ", ".join(numbers)
    elif room_lines:
        rooms_text = "Atanmadi"
    else:
        rooms_text = "-"

    return ReservationRow(
        reservation_id=reservation.id,
        confirmation_number=reservation.confirmation_number,
        guest_name=guest.full_name if guest else "-",
        guest_phone=(guest.phone or guest.mobile or "") if guest else "",
        guest_email=(guest.email or "") if guest else "",
        guest_vip=(guest.vip_level.label if guest and guest.is_vip else ""),
        is_blacklisted=bool(guest and guest.is_blacklisted),
        rooms_text=rooms_text,
        check_in=reservation.check_in_date,
        check_out=reservation.check_out_date,
        nights=reservation.nights,
        status=reservation.status,
        source=reservation.source,
        total=Money.of(reservation.total_amount, currency),
        paid=Money.of(reservation.paid_amount, currency),
        deposit=Money.of(reservation.deposit_amount, currency),
        balance=Money.of(reservation.balance, currency),
        special_requests=reservation.special_requests or "",
        cancellation_reason=reservation.cancellation_reason or "",
        room_lines=room_lines,
    )


__all__ = ["ReservationRow", "ReservationsPage", "RoomLine", "status_color"]
