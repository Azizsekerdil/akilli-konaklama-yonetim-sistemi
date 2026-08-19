"""Yeni rezervasyon diyalogu.

Akis tek bir pencerede, yukaridan asagiya numarali bolumler halinde ilerler:

1. Tarih araligi ve kisi sayisi
2. Musaitlik sonuclari + oda tipi ve istege bagli belirli oda secimi
3. Misafir secimi (mevcut kayit veya hizli yeni kayit)
4. Kanal, ozel istekler, depozito

Fiyat dokumu bu siranin **disindadir**: kaydirma alaninin altina sabitlenmis
bir serittir ve her zaman gorunur. Numarali bir adim olarak dizildiginde
1020x760'lik pencerede goruntulenen alanin altinda kaliyor, kullanici toplami
hic gormeden Kaydet'e basabiliyordu.

Iki nokta ozellikle onemlidir:

* **Musait olmayan oda tipleri gizlenmez.** Listeden dusurulen bir tip,
  kullaniciya "sistem bozuk" hissi verir. Bunun yerine satir kalir ve neden
  secilemedigi ("Musait degil" / "Kapasite yetersiz") yazilir.
* **Is kurali burada tekrarlanmaz.** Cakisma, kapasite ve kara liste
  kontrollerini :class:`~app.application.services.reservation_service.ReservationService`
  yapar; diyalog yalnizca hatayi anlasilir bicimde gosterir ve gecersiz alani
  isaretler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.context import ServiceContext
from app.application.services.reservation_service import (
    AvailabilityResult,
    ReservationService,
    RoomRequest,
)
from app.core.exceptions import HotelError, ValidationError
from app.core.log import get_logger
from app.domain.enums import ReservationSource
from app.domain.rules.pricing import PriceBreakdown
from app.domain.value_objects import DateRange, Money, to_decimal
from app.infrastructure.db.base import utcnow
from app.security.permissions import Perm
from app.ui.formatting import format_number
from app.ui.i18n import t
from app.ui.session import UiSession
from app.ui.theme import active_palette
from app.ui.widgets.common import Card, SearchBox, show_error
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)

#: Depozito gibi tutarlarin kurus hassasiyeti.
_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class AvailabilityOption:
    """Musaitlik tablosunun tek satiri.

    ``unavailable_reason`` bos degilse satir secilemez; kullanici nedenini
    okur (satir listeden **dusurulmez**).
    """

    room_type_id: int
    room_type_name: str
    available_count: int
    room_choices: tuple[tuple[int, str], ...]
    """``(oda_id, oda_numarasi)`` ciftleri - belirli oda secimi icin."""

    nightly: Money | None
    total: Money | None
    breakdown: PriceBreakdown | None
    unavailable_reason: str = ""

    @property
    def is_selectable(self) -> bool:
        return not self.unavailable_reason and self.available_count > 0

    def availability_text(self) -> str:
        if self.unavailable_reason:
            return self.unavailable_reason
        return f"{format_number(self.available_count)} oda musait"


def plain_label(
    text: str = "", *, name: str | None = None, parent: QWidget | None = None
) -> QLabel:
    """Kart uzerinde dogru gorunen duz metin etiketi.

    Genel ``QWidget`` stil kurali arka plani sayfa zemini yapar; QLabel bu
    arka plani fiilen boyadigi icin bir kartin uzerindeki etiket koyu bir
    dikdortgen olarak gorunur. Yalnizca saydamlik veriyoruz - metin rengi
    stil sayfasindan gelmeye devam eder.

    (Ayni yardimci :mod:`app.ui.pages.reservations_page` icinde de vardir;
    diyalogun bir sayfa moduluna bagimli olmamasi icin bilerek
    tekrarlanmistir.)
    """
    label = QLabel(text, parent)
    if name:
        label.setObjectName(name)
    label.setStyleSheet("background: transparent;")
    return label


def transparent_panel(widget: QWidget, name: str) -> QWidget:
    """Kart uzerine oturan duz kapsayici bileseni saydam yapar.

    Genel ``QWidget { background-color: ... }`` kurali etiketleri degil, **her
    duz kapsayiciyi** de boyar; kartin uzerindeki bir sekme sayfasi bu yuzden
    sayfa zemini renginde koyu bir dikdortgen olarak gorunur (olculen fark
    #12171E'ye karsi #1A2029).

    Kural bilerek nesne adiyla sinirlandirilir: secicisiz bir ``setStyleSheet``
    alt bilesenlere de miras kalir ve arka plani anlam tasiyan bilesenleri de
    saydamlastirirdi.
    """
    widget.setObjectName(name)
    widget.setStyleSheet(f"#{name} {{ background: transparent; }}")
    return widget


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


def parse_amount(text: str, *, field: str) -> Decimal:
    """Kullanicinin yazdigi tutari ``Decimal``'e cevirir.

    Para ``float`` uzerinden gecmez: ``QDoubleSpinBox`` yerine metin girdisi
    kullanmamizin nedeni budur. Turkce yazimda binlik ayirici nokta, ondalik
    ayirici virguldur ("1.250,50").

    >>> str(parse_amount("1.250,50", field="deposit_amount"))
    '1250.50'
    >>> str(parse_amount("", field="deposit_amount"))
    '0.00'
    """
    cleaned = (text or "").strip().replace(" ", "").replace("₺", "")
    if not cleaned:
        return Decimal("0.00")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        value = to_decimal(cleaned)
    except ValueError as exc:
        raise ValidationError("Tutar sayisal olmalidir.", field=field) from exc
    if value < 0:
        raise ValidationError("Tutar negatif olamaz.", field=field)
    return value.quantize(_CENT)


class ReservationDialog(QDialog):
    """Yeni rezervasyon olusturma diyalogu."""

    def __init__(self, ui_session: UiSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui = ui_session

        #: Kayit basarili olduysa doldurulur; cagiran ekran listeyi tazeler.
        self.created_reservation_id: int | None = None
        self.created_confirmation: str | None = None

        self._selected_option: AvailabilityOption | None = None
        self._selected_guest_id: int | None = None
        self._invalid_widgets: list[QWidget] = []

        self.setWindowTitle(t("reservation.new"))
        self.setMinimumSize(940, 640)
        self.resize(1020, 760)

        self._build()

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        body = QVBoxLayout(container)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        scroll.setWidget(container)

        body.addWidget(self._build_dates_card())
        body.addWidget(self._build_availability_card())
        body.addWidget(self._build_guest_card())
        body.addWidget(self._build_details_card())
        body.addStretch(1)

        root.addWidget(scroll, 1)

        # Fiyat dokumu kaydirma alaninin **disinda** durur. Bolumleri yan yana
        # dizmek yetmiyordu: 1020x760'lik pencerede icerik ~990 piksele
        # ulasiyor ve dokum goruntulenen alanin altinda kaliyordu; kullanici
        # toplami hic gormeden Kaydet'e basabiliyordu. Sabitlenmis serit,
        # pencere ne kadar kaydirilirsa kaydirilsin toplami gorunur tutar.
        root.addWidget(self._build_price_card())

        self._error_label = QLabel("")
        self._error_label.setObjectName("BadgeDanger")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        buttons = QDialogButtonBox(self)
        self._save_button = buttons.addButton("Kaydet", QDialogButtonBox.ButtonRole.AcceptRole)
        self._set_save_enabled(False)
        cancel_button = buttons.addButton(
            t("common.cancel"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self._save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)
        root.addWidget(buttons)

        # Alan adi -> gecersiz isaretlenecek bilesen.
        self._field_widgets: dict[str, QWidget] = {
            "check_out": self._check_out,
            "check_in": self._check_in,
            "adults": self._adults,
            "children": self._children,
            "deposit_amount": self._deposit,
            "first_name": self._first_name,
            "last_name": self._last_name,
            "guest_id": self._guest_search,
        }

    def _build_dates_card(self) -> QWidget:
        card = flat_card("1. Tarih ve Kisi Sayisi", self)
        today = utcnow().date()

        # Not: genislik acikca veriliyor. Varsayilan boyut ipucu, stil
        # sayfasindaki ic bosluk ve acilir takvim okuyla birlikte tarihi
        # kirpiyor ("29.08.202..."); yil son hanesi okunamaz hale geliyor.
        self._check_in = QDateEdit(self)
        self._check_in.setCalendarPopup(True)
        self._check_in.setDisplayFormat("dd.MM.yyyy")
        self._check_in.setDate(QDate(today.year, today.month, today.day))
        self._check_in.setMinimumWidth(150)

        checkout_default = today + timedelta(days=2)
        self._check_out = QDateEdit(self)
        self._check_out.setCalendarPopup(True)
        self._check_out.setDisplayFormat("dd.MM.yyyy")
        self._check_out.setDate(
            QDate(checkout_default.year, checkout_default.month, checkout_default.day)
        )
        self._check_out.setMinimumWidth(150)

        self._adults = QSpinBox(self)
        self._adults.setRange(1, 12)
        self._adults.setValue(2)

        self._children = QSpinBox(self)
        self._children.setRange(0, 8)

        self._search_button = QPushButton("Musaitlik Ara", self)
        self._search_button.setObjectName("Primary")  # her zaman etkin
        self._search_button.clicked.connect(self.search_availability)

        line = QHBoxLayout()
        line.setSpacing(10)
        line.addWidget(self._caption("Giris"))
        line.addWidget(self._check_in)
        line.addWidget(self._caption("Cikis"))
        line.addWidget(self._check_out)
        line.addWidget(self._caption("Yetiskin"))
        line.addWidget(self._adults)
        line.addWidget(self._caption("Cocuk"))
        line.addWidget(self._children)
        line.addStretch(1)
        line.addWidget(self._search_button)
        card.add_layout(line)

        self._nights_label = plain_label("", name="Muted")
        card.add_widget(self._nights_label)
        self._check_in.dateChanged.connect(lambda _: self._update_nights_label())
        self._check_out.dateChanged.connect(lambda _: self._update_nights_label())
        self._update_nights_label()
        return card

    def _build_availability_card(self) -> QWidget:
        card = flat_card("2. Musaitlik ve Oda Secimi", self)

        palette = active_palette()
        self._availability_table = FilterableTableView(
            [
                Column("room_type_name", "Oda Tipi", stretch=True),
                Column(
                    "available",
                    "Musait Oda",
                    getter=lambda option: option.availability_text(),
                    color_getter=lambda option: (
                        palette.success if option.is_selectable else palette.text_muted
                    ),
                    width=230,
                ),
                Column(
                    "nightly",
                    "Gecelik",
                    getter=lambda option: option.nightly,
                    width=130,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column(
                    "total",
                    "Toplam",
                    getter=lambda option: option.total,
                    width=140,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
            ],
            parent=self,
        )
        self._availability_table.setMinimumHeight(150)
        self._availability_table.selection_changed.connect(self._on_option_selected)
        card.add_widget(self._availability_table)

        room_line = QHBoxLayout()
        room_line.addWidget(self._caption("Belirli oda (istege bagli)"))
        self._room_combo = QComboBox(self)
        self._room_combo.setMinimumWidth(220)
        self._room_combo.addItem("Farketmez - girise kadar atanacak", None)
        self._room_combo.setEnabled(False)
        room_line.addWidget(self._room_combo)
        room_line.addStretch(1)
        card.add_layout(room_line)

        self._availability_hint = plain_label(
            "Once tarih secip 'Musaitlik Ara' dugmesine basin.", name="Muted"
        )
        self._availability_hint.setWordWrap(True)
        card.add_widget(self._availability_hint)
        return card

    def _build_guest_card(self) -> QWidget:
        card = flat_card("3. Misafir", self)
        self._guest_tabs = QTabWidget(self)

        # --- Mevcut misafir ---
        existing = transparent_panel(QWidget(self), "GuestPickExisting")
        existing_layout = QVBoxLayout(existing)
        existing_layout.setContentsMargins(10, 10, 10, 10)
        existing_layout.setSpacing(8)

        search_line = QHBoxLayout()
        self._guest_search = SearchBox("Ad, soyad, telefon veya e-posta")
        self._guest_search.search_triggered.connect(self.search_guests)
        guest_search_button = QPushButton(t("common.search"), self)
        guest_search_button.clicked.connect(lambda: self.search_guests(self._guest_search.text()))
        search_line.addWidget(self._guest_search, 1)
        search_line.addWidget(guest_search_button)
        existing_layout.addLayout(search_line)

        self._guest_list = QListWidget(self)
        self._guest_list.setMaximumHeight(112)
        self._guest_list.itemSelectionChanged.connect(self._on_guest_selected)
        existing_layout.addWidget(self._guest_list)

        self._guest_hint = plain_label("Aramak icin en az iki karakter yazin.", name="Muted")
        self._guest_hint.setWordWrap(True)
        existing_layout.addWidget(self._guest_hint)

        # --- Hizli yeni misafir ---
        fresh = transparent_panel(QWidget(self), "GuestPickNew")
        form = QFormLayout(fresh)
        form.setContentsMargins(10, 10, 10, 10)
        form.setSpacing(8)
        self._first_name = QLineEdit(self)
        self._last_name = QLineEdit(self)
        self._phone = QLineEdit(self)
        self._phone.setPlaceholderText("+90 ...")
        self._email = QLineEdit(self)
        # Etiketler metin yerine bilesen olarak veriliyor: QFormLayout metinden
        # kendi QLabel'ini uretir ve o etiket kart uzerinde koyu bir kutu
        # olarak gorunur (bkz. plain_label).
        form.addRow(plain_label("Ad *"), self._first_name)
        form.addRow(plain_label("Soyad *"), self._last_name)
        form.addRow(plain_label("Telefon"), self._phone)
        form.addRow(plain_label("E-posta"), self._email)

        self._guest_tabs.addTab(existing, "Mevcut Misafir")
        self._guest_tabs.addTab(fresh, "Yeni Misafir")
        card.add_widget(self._guest_tabs)
        return card

    def _build_details_card(self) -> QWidget:
        card = flat_card("4. Rezervasyon Bilgileri", self)
        form = QFormLayout()
        form.setSpacing(8)

        self._source_combo = QComboBox(self)
        for value, label in ReservationSource.choices():
            self._source_combo.addItem(label, value)
        self._source_combo.setCurrentIndex(
            self._source_combo.findData(ReservationSource.DIRECT.value)
        )

        self._special_requests = QPlainTextEdit(self)
        self._special_requests.setMaximumHeight(64)
        self._special_requests.setPlaceholderText("Ust kat, sessiz oda, bebek karyolasi...")

        self._deposit = QLineEdit(self)
        self._deposit.setPlaceholderText("0,00")
        self._deposit.setMaximumWidth(180)

        requests_label = plain_label("Ozel istekler")
        requests_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.addRow(plain_label(t("reservation.source")), self._source_combo)
        form.addRow(requests_label, self._special_requests)
        form.addRow(plain_label("Depozito"), self._deposit)
        card.add_layout(form)
        return card

    def _build_price_card(self) -> QWidget:
        # Numarasiz baslik: serit artik kaydirilarak ulasilan bir adim degil,
        # her zaman gorunen ozet. "5." yazmak sirali bir adim izlenimi verirdi.
        card = flat_card("Fiyat Dokumu", self)
        self._price_layout = QVBoxLayout()
        self._price_layout.setSpacing(4)
        card.add_layout(self._price_layout)
        self._render_breakdown(None)
        return card

    def _caption(self, text: str) -> QLabel:
        return plain_label(text, name="Muted")

    # ----------------------------------------------------------------- #
    #  Musaitlik
    # ----------------------------------------------------------------- #
    def search_availability(self) -> None:
        """Secilen tarihler icin musait oda tiplerini ve fiyatlari getirir."""
        self._clear_invalid()
        try:
            date_range = self.date_range()
            adults = self._adults.value()
            children = self._children.value()
        except ValidationError as exc:
            self._fail(exc)
            return

        try:
            with self.ui.service_context(commit=False) as ctx:
                results = ReservationService(ctx).search_availability(
                    date_range, adults=adults, children=children
                )
                options = self._build_options(ctx, results)
        except HotelError as exc:
            self._fail(exc)
            return

        log.debug("musaitlik_arandi", nights=date_range.nights, options=len(options))
        self._availability_table.set_rows(options)
        self._selected_option = None
        self._room_combo.clear()
        self._room_combo.addItem("Farketmez - girise kadar atanacak", None)
        self._room_combo.setEnabled(False)
        self._set_save_enabled(False)
        self._render_breakdown(None)

        sellable = [option for option in options if option.is_selectable]
        if not options:
            self._availability_hint.setText(
                "Tesiste tanimli aktif oda tipi bulunamadi. Oda tiplerini Odalar "
                "ekranindan tanimlayabilirsiniz."
            )
        elif not sellable:
            self._availability_hint.setText(
                f"{date_range.format()} icin musait oda bulunamadi. "
                "Tarihleri degistirin veya bekleme listesine alin."
            )
        else:
            self._availability_hint.setText(
                f"{date_range.format()} - secilebilir {len(sellable)} oda tipi. "
                "Devam etmek icin bir satir secin."
            )

    def _build_options(
        self, ctx: ServiceContext, results: list[AvailabilityResult]
    ) -> list[AvailabilityOption]:
        """Servis sonucunu tabloya hazir satirlara cevirir.

        ``search_availability`` kapasitesi yetmeyen oda tipini hic dondurmez.
        Kullanicinin "neden bu tip listede yok?" sorusunu sormamasi icin o
        tipler de satir olarak eklenir ve nedeni yazilir.
        """
        from sqlalchemy import select

        from app.infrastructure.db.models.rooms import RoomType
        from app.infrastructure.db.repositories import RoomRepository

        property_id = ctx.require_property()
        numbers = {
            room.id: room.number for room in RoomRepository(ctx.session).list_rooms(property_id)
        }
        by_type = {result.room_type_id: result for result in results}

        room_types = ctx.session.scalars(
            select(RoomType)
            .where(RoomType.property_id == property_id, RoomType.is_active.is_(True))
            .order_by(RoomType.name)
        ).all()

        options: list[AvailabilityOption] = []
        for room_type in room_types:
            result = by_type.get(room_type.id)
            if result is None:
                options.append(
                    AvailabilityOption(
                        room_type_id=room_type.id,
                        room_type_name=room_type.name,
                        available_count=0,
                        room_choices=(),
                        nightly=None,
                        total=None,
                        breakdown=None,
                        unavailable_reason=(
                            f"Kapasite yetersiz (en fazla {room_type.max_occupancy} kisi)"
                        ),
                    )
                )
                continue

            price = result.price
            options.append(
                AvailabilityOption(
                    room_type_id=result.room_type_id,
                    room_type_name=result.room_type_name,
                    available_count=result.available_count,
                    room_choices=tuple(
                        (room_id, numbers.get(room_id, str(room_id)))
                        for room_id in result.available_room_ids
                    ),
                    nightly=price.average_nightly_rate if price else None,
                    total=price.total if price else None,
                    breakdown=price,
                    unavailable_reason="" if result.is_available else "Musait degil",
                )
            )
        return options

    def _on_option_selected(self, option: object) -> None:
        self._room_combo.clear()
        self._room_combo.addItem("Farketmez - girise kadar atanacak", None)

        if not isinstance(option, AvailabilityOption) or not option.is_selectable:
            self._selected_option = None
            self._room_combo.setEnabled(False)
            self._set_save_enabled(False)
            self._render_breakdown(None)
            if isinstance(option, AvailabilityOption):
                self._availability_hint.setText(
                    f"{option.room_type_name}: {option.unavailable_reason or 'Musait degil'}"
                )
            return

        self._selected_option = option
        for room_id, number in option.room_choices:
            self._room_combo.addItem(f"Oda {number}", room_id)
        self._room_combo.setEnabled(True)
        self._set_save_enabled(True)
        self._render_breakdown(option.breakdown)
        self._availability_hint.setText(
            f"{option.room_type_name} secildi - {option.availability_text()}."
        )

    # ----------------------------------------------------------------- #
    #  Misafir
    # ----------------------------------------------------------------- #
    def search_guests(self, text: str) -> None:
        """Mevcut misafir kayitlarinda arama yapar."""
        from app.infrastructure.db.repositories import GuestRepository

        query = (text or "").strip()
        self._guest_list.clear()
        self._selected_guest_id = None

        if len(query) < 2:
            self._guest_hint.setText("Aramak icin en az iki karakter yazin.")
            return

        try:
            with self.ui.service_context(commit=False) as ctx:
                ctx.require(Perm.GUEST_VIEW)
                found = [
                    (
                        guest.id,
                        guest.full_name,
                        guest.phone or guest.mobile or "",
                        guest.email or "",
                        guest.is_blacklisted,
                    )
                    for guest in GuestRepository(ctx.session).search(query, limit=25)
                ]
        except HotelError as exc:
            self._fail(exc)
            return

        for guest_id, full_name, phone, email, blacklisted in found:
            parts = [part for part in (phone, email) if part]
            text_line = full_name + (f"  ({' | '.join(parts)})" if parts else "")
            if blacklisted:
                text_line += "  [KARA LISTE]"
            item = QListWidgetItem(text_line)
            item.setData(Qt.ItemDataRole.UserRole, guest_id)
            self._guest_list.addItem(item)

        self._guest_hint.setText(
            f"{format_number(len(found))} misafir bulundu."
            if found
            else "Eslesen misafir yok. 'Yeni Misafir' sekmesinden hizlica ekleyebilirsiniz."
        )

    def _on_guest_selected(self) -> None:
        items = self._guest_list.selectedItems()
        self._selected_guest_id = items[0].data(Qt.ItemDataRole.UserRole) if items else None

    # ----------------------------------------------------------------- #
    #  Fiyat dokumu
    # ----------------------------------------------------------------- #
    def _render_breakdown(self, breakdown: PriceBreakdown | None) -> None:
        while self._price_layout.count():
            item = self._price_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # ``deleteLater`` tek basina yetmez: silme olay dongusune
                # ertelenir, o ana kadar bilesen hala ust bilesenin cocugudur
                # ve eski konumunda cizilmeye devam eder. Sonuc, eski ipucu
                # metninin yeni fiyat satirinin uzerine binmesidir.
                widget.setParent(None)
                widget.deleteLater()

        if breakdown is None:
            hint = plain_label(
                "Musaitlik arayip bir oda tipi sectiginizde fiyat dokumu burada cikar.",
                name="Muted",
            )
            hint.setWordWrap(True)
            self._price_layout.addWidget(hint)
            return

        # Serit kaydirma alaninin disinda durdugu icin dusey yer kisitlidir:
        # ara kalemler tek satirda yan yana dizilir, toplam saga vurgulu yazilir.
        lines = breakdown.as_lines()
        row = QHBoxLayout()
        row.setSpacing(16)
        for label_text, amount in lines[:-1]:
            row.addWidget(plain_label(f"{label_text}: {amount.format()}", name="Muted"))
        row.addStretch(1)

        total_text, total_amount = lines[-1]
        total_label = plain_label(f"{total_text}  {total_amount.format()}")
        font = total_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        total_label.setFont(font)
        row.addWidget(total_label)

        holder = transparent_panel(QWidget(self), "PriceStripRow")
        holder.setLayout(row)
        self._price_layout.addWidget(holder)

        average = plain_label(
            f"Ortalama gecelik ucret: {breakdown.average_nightly_rate.format()} "
            f"({breakdown.night_count} gece)",
            name="Muted",
        )
        self._price_layout.addWidget(average)

    # ----------------------------------------------------------------- #
    #  Kayit
    # ----------------------------------------------------------------- #
    def date_range(self) -> DateRange:
        """Secilen tarih araligini dogrular ve dondurur.

        ``DateRange`` gecersiz aralikta ham bir ``ValueError`` firlatir; onu
        kullaniciya gostermek teknik bir mesaj olurdu. Bu yuzden once biz
        dogruluyor ve anlasilir bir :class:`ValidationError` uretiyoruz.
        """
        start: date = self._check_in.date().toPython()
        end: date = self._check_out.date().toPython()
        if end <= start:
            raise ValidationError(
                "Cikis tarihi giris tarihinden sonra olmalidir.",
                field="check_out",
            )
        return DateRange(start, end)

    def _save(self) -> None:
        self._clear_invalid()

        option = self._selected_option
        if option is None:
            self._fail(
                ValidationError(
                    "Once musaitlik arayip bir oda tipi secin.",
                    field="room_requests",
                )
            )
            return

        try:
            date_range = self.date_range()
            deposit = parse_amount(self._deposit.text(), field="deposit_amount")
            new_guest = self._collect_new_guest()
        except ValidationError as exc:
            self._fail(exc)
            return

        if new_guest is None and self._selected_guest_id is None:
            self._fail(
                ValidationError(
                    "Bir misafir secin veya 'Yeni Misafir' sekmesini doldurun.",
                    field="guest_id",
                )
            )
            return

        request = RoomRequest(
            room_type_id=option.room_type_id,
            check_in=date_range.start,
            check_out=date_range.end,
            adults=self._adults.value(),
            children=self._children.value(),
            room_id=self._room_combo.currentData(),
        )
        source = ReservationSource(self._source_combo.currentData())
        requests_text = self._special_requests.toPlainText().strip()

        try:
            with self.ui.service_context() as ctx:
                guest_id = self._selected_guest_id
                if guest_id is None and new_guest is not None:
                    guest_id = self._create_guest(ctx, new_guest)

                reservation = ReservationService(ctx).create_reservation(
                    guest_id=guest_id,
                    room_requests=[request],
                    source=source,
                    special_requests=requests_text or None,
                    deposit_amount=deposit,
                )
                self.created_reservation_id = reservation.id
                self.created_confirmation = reservation.confirmation_number
        except HotelError as exc:
            self._fail(exc)
            return

        self.accept()

    def _collect_new_guest(self) -> tuple[str, str, str, str] | None:
        """Yeni misafir sekmesi doluysa alanlari dogrular ve dondurur."""
        if self._guest_tabs.currentIndex() != 1:
            return None

        first = self._first_name.text().strip()
        last = self._last_name.text().strip()
        if not first:
            raise ValidationError("Misafir adi zorunludur.", field="first_name")
        if not last:
            raise ValidationError("Misafir soyadi zorunludur.", field="last_name")
        return first, last, self._phone.text().strip(), self._email.text().strip()

    def _create_guest(self, ctx: ServiceContext, data: tuple[str, str, str, str]) -> int:
        """Hizli misafir kaydini **servis katmanina** yaptirir.

        Kayit bir zamanlar burada elle yazilirdi (ayri bir misafir servisi
        yoktu). Artik :class:`~app.application.services.guest_service.GuestService`
        var; ORM nesnesini arayuzde kurmak yetki kontrolunu, ad/soyad
        dogrulamasini ve denetim kaydinin bicimini iki yerde tekrarlamak
        demekti. Servis bunlarin hepsini tek noktada yapar.
        """
        from app.application.services.guest_service import GuestService

        first, last, phone, email = data
        summary = GuestService(ctx).create(
            first_name=first,
            last_name=last,
            phone=phone or None,
            email=email or None,
        )
        return summary.guest_id

    # ----------------------------------------------------------------- #
    #  Hata gosterimi
    # ----------------------------------------------------------------- #
    def _fail(self, error: HotelError) -> None:
        """Hatayi gosterir ve varsa ilgili alani gecersiz olarak isaretler."""
        field = getattr(error, "field", None)
        if field:
            self._mark_invalid(field)
        self._error_label.setText(error.user_message)
        self._error_label.setVisible(True)
        show_error(self, error)

    def _mark_invalid(self, field: str) -> None:
        widget = self._field_widgets.get(field)
        if widget is None:
            return
        widget.setProperty("invalid", True)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        self._invalid_widgets.append(widget)

    def _clear_invalid(self) -> None:
        for widget in self._invalid_widgets:
            widget.setProperty("invalid", False)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._invalid_widgets.clear()
        self._error_label.setVisible(False)
        self._error_label.setText("")

    # ----------------------------------------------------------------- #
    #  Yardimcilar
    # ----------------------------------------------------------------- #
    def _set_save_enabled(self, enabled: bool) -> None:
        """Kaydet dugmesini etkinlestirir ve gorunumunu esitler.

        Stil sayfasinda ``QPushButton#Primary`` kuralinin ``:disabled``
        karsiligi yoktur; nesne adi pasif durumda birakilirsa dugme dolu
        renkte gorunur ve kullanici tiklanabilir sanir.
        """
        self._save_button.setEnabled(enabled)
        self._save_button.setObjectName("Primary" if enabled else "")
        self._save_button.style().unpolish(self._save_button)
        self._save_button.style().polish(self._save_button)

    def _update_nights_label(self) -> None:
        start: date = self._check_in.date().toPython()
        end: date = self._check_out.date().toPython()
        if end <= start:
            self._nights_label.setText("Cikis tarihi giris tarihinden sonra olmalidir.")
            return
        self._nights_label.setText(f"{(end - start).days} gece")


__all__ = ["AvailabilityOption", "ReservationDialog", "parse_amount"]
