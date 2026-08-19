"""Giris (check-in) diyalogu.

Diyalogun sorumlulugu veriyi **toplamak** ve
:meth:`~app.application.services.frontdesk_service.FrontdeskService.check_in`
cagirmaktir. Musaitlik, oda durumu ve durum makinesi kontrolleri servis
katmanindadir; buradaki kontroller yalnizca kullaniciyi erken uyarmak icindir.

Kisisel veri notu
-----------------
Kimlik/pasaport numarasi :meth:`Guest.set_identity` ile yazilir; boylece
sifreli alan ve arama icin kullanilan kor indeks birlikte guncellenir.
Alanin yaninda KVKK uyarisi gosterilir ve numara ekranda saklanmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

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

from app.application.services.frontdesk_service import FrontdeskService
from app.core.exceptions import HotelError
from app.core.log import get_logger
from app.domain.enums import Currency, RoomHousekeepingStatus, RoomOccupancyStatus
from app.domain.value_objects import Money
from app.security.permissions import Perm
from app.ui.dialogs.folio_dialog import fit_dialog_to_content, set_action_state
from app.ui.formatting import format_nights, format_short_date
from app.ui.session import UiSession
from app.ui.widgets.common import Card, SectionTitle, show_error

log = get_logger(__name__)

#: Kimlik alaninin altinda gosterilen KVKK uyarisi.
KVKK_NOTICE = (
    "KVKK: Kimlik numarasi sifreli saklanir ve yalnizca yetkili personel "
    "tarafindan gorulebilir. Yalnizca konaklama bildirimi icin gerekli oldugunda girin."
)


@dataclass(slots=True)
class RoomOption:
    """Giriste secilebilecek bir fiziksel oda."""

    room_id: int
    number: str
    room_type_name: str
    is_dirty: bool = False
    status_label: str = ""

    @property
    def display(self) -> str:
        suffix = f" - {self.status_label}" if self.status_label else ""
        return f"{self.number} ({self.room_type_name}){suffix}"


@dataclass(slots=True)
class CheckinSummary:
    """Diyalogun ihtiyac duydugu tum veriler - ORM'den bagimsiz."""

    reservation_room_id: int
    confirmation_number: str = "-"
    guest_id: int | None = None
    guest_name: str = "-"
    guest_has_identity: bool = False
    room_type_name: str = "-"
    meal_plan: str = "-"
    assigned_room_id: int | None = None
    check_in: date | None = None
    check_out: date | None = None
    nights: int = 0
    adults: int = 1
    children: int = 0
    total_amount: Money = field(default_factory=Money.zero)
    special_requests: str = ""
    rooms: list[RoomOption] = field(default_factory=list)


class CheckinDialog(QDialog):
    """Misafir girisi: oda secimi, kimlik, oda karti, erken giris."""

    def __init__(
        self,
        ui_session: UiSession,
        reservation_room_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = ui_session
        self.reservation_room_id = reservation_room_id
        self.summary = CheckinSummary(reservation_room_id=reservation_room_id)
        #: Giris yapildiginda olusan konaklama kaydinin kimligi.
        self.stay_id: int | None = None

        self.setWindowTitle("Giris Yap")
        # Alt sinir kucuk tutulur (kucuk ekranli on buro terminalleri),
        # acilis boyutu ise tipik icerigi kaydirmadan gosterecek kadar buyuk.
        self.setMinimumSize(620, 480)
        self.resize(680, 700)

        self._build()
        self._reload()
        # Boyutlandirma veri YUKLENDIKTEN sonra yapilir: ozel talep notu ve
        # kirli oda uyarisi kosullu bolumlerdir, icerik yuksekligini degistirir.
        fit_dialog_to_content(self, self._scroll, width=680)

    # ----------------------------------------------------------------- #
    #  Arayuz
    # ----------------------------------------------------------------- #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)
        outer.addWidget(SectionTitle("Giris Islemi"))

        # Govde kaydirilabilir: ozel talep ve kirli oda uyarisi kosullu
        # gorundugu icin icerik yuksekligi degisir. Kaydirma alani olmadan
        # kucuk ekranlarda kartlar sikisir ve girdi metinleri kirpilir.
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

        # --- Rezervasyon ozeti (salt okunur) ---
        summary_card = Card("Rezervasyon Ozeti", self)
        summary_grid = QGridLayout()
        summary_grid.setSpacing(7)
        summary_grid.setColumnStretch(1, 1)

        self._summary_labels: dict[str, QLabel] = {}
        for row_index, (key, title) in enumerate(
            (
                ("confirmation", "Onay No"),
                ("guest", "Misafir"),
                ("room_type", "Oda Tipi"),
                ("dates", "Tarihler"),
                ("guests", "Kisi"),
                ("meal_plan", "Pansiyon"),
                ("amount", "Tutar"),
            )
        ):
            name = QLabel(title)
            name.setObjectName("Muted")
            value = QLabel("-")
            value.setWordWrap(True)
            summary_grid.addWidget(name, row_index, 0)
            summary_grid.addWidget(value, row_index, 1)
            self._summary_labels[key] = value
        summary_card.add_layout(summary_grid)
        layout.addWidget(summary_card)

        self._requests_label = QLabel()
        self._requests_label.setObjectName("BadgeInfo")
        self._requests_label.setWordWrap(True)
        self._requests_label.setVisible(False)
        layout.addWidget(self._requests_label)

        # --- Giris bilgileri ---
        form_card = Card("Giris Bilgileri", self)
        form = QGridLayout()
        form.setSpacing(9)
        form.setColumnStretch(1, 1)

        self._room_combo = QComboBox()
        self._room_combo.currentIndexChanged.connect(self._update_room_warning)

        self._identity_edit = QLineEdit()
        self._identity_edit.setPlaceholderText("Kimlik / pasaport numarasi")
        self._identity_edit.setMaxLength(40)

        self._key_card_spin = QSpinBox()
        self._key_card_spin.setRange(0, 8)
        self._key_card_spin.setValue(1)
        self._key_card_spin.setSuffix(" adet")

        self._early_spin = QSpinBox()
        self._early_spin.setRange(0, 12)
        self._early_spin.setValue(0)
        self._early_spin.setSuffix(" saat")
        self._early_spin.setSpecialValueText("Yok (ucretsiz)")

        for row_index, (title, widget) in enumerate(
            (
                ("Oda", self._room_combo),
                ("Kimlik No", self._identity_edit),
                ("Oda Karti", self._key_card_spin),
                ("Erken Giris", self._early_spin),
            )
        ):
            name = QLabel(title)
            name.setObjectName("Muted")
            form.addWidget(name, row_index, 0)
            form.addWidget(widget, row_index, 1)
        form_card.add_layout(form)

        kvkk = QLabel(KVKK_NOTICE)
        kvkk.setObjectName("Muted")
        kvkk.setWordWrap(True)
        form_card.add_widget(kvkk)
        layout.addWidget(form_card)

        layout.addStretch(1)

        # --- Kirli oda uyarisi (kaydirma alaninin DISINDA) ---
        # Bu uyari ve onay kutusu "Giris Yap" dugmesini KILITLEYEN kosuldur.
        # Kaydirilabilir govdede dururken diyalogun acilis yuksekliginin altina
        # dusuyordu: kullanici pasif bir dugme goruyor, nedenini goremiyordu
        # (yalnizca ipucunda yaziyordu). Engelin kendisi eylemin yaninda,
        # her zaman gorunur olmalidir.
        self._dirty_warning = QLabel()
        self._dirty_warning.setObjectName("BadgeWarning")
        self._dirty_warning.setWordWrap(True)
        self._dirty_warning.setVisible(False)
        outer.addWidget(self._dirty_warning)

        self._dirty_check = QCheckBox("Odanin temizlenmedigini biliyorum, yine de giris yapilsin")
        self._dirty_check.setVisible(False)
        self._dirty_check.stateChanged.connect(lambda _: self._update_save_state())
        outer.addWidget(self._dirty_check)

        # --- Dugmeler (kaydirma alaninin DISINDA; her zaman gorunur) ---
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Iptal")
        cancel.clicked.connect(self.reject)
        self._save_button = QPushButton("Giris Yap")
        self._save_button.setObjectName("Primary")
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(self._save_button)
        outer.addLayout(buttons)

        # Erken giris ucretini isleyebilmek icin ayri yetki gerekir.
        if not self.ui.can(Perm.FRONTDESK_EARLY_LATE):
            self._early_spin.setEnabled(False)
            self._early_spin.setToolTip(
                "Erken giris ucreti islemek icin 'Erken giris / gec cikis onayi' yetkisi gerekiyor."
            )
            # Stil sayfasinda QSpinBox icin ayri bir "devre disi" gorunumu yok;
            # kisit metinle yazilmazsa alan etkin sanilir.
            self._early_spin.setSpecialValueText("Yetkiniz yok")
        if not self.ui.can(Perm.GUEST_EDIT):
            self._identity_edit.setEnabled(False)
            self._identity_edit.setPlaceholderText("Kimlik girmek icin yetkiniz yok")
            self._identity_edit.setToolTip(
                "Kimlik bilgisi girmek icin 'Misafir kaydi duzenleme' yetkisi gerekiyor."
            )

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def _reload(self) -> None:
        try:
            self.summary = self._load()
        except HotelError as exc:
            show_error(self, exc)
            self._save_button.setEnabled(False)
            self._save_button.setToolTip("Rezervasyon bilgisi okunamadi; listeyi yenileyin.")
            return
        self._render()

    def _load(self) -> CheckinSummary:
        """Rezervasyon satirini ve musait odalari duz veriye cevirir."""
        from app.domain.rules.availability import is_room_available
        from app.infrastructure.db.models.reservations import ReservationRoom
        from app.infrastructure.db.repositories import ReservationRepository, RoomRepository

        with self.ui.service_context(commit=False) as ctx:
            ctx.require(Perm.RESERVATION_VIEW)
            property_id = ctx.require_property()

            row = ctx.session.get(ReservationRoom, self.reservation_room_id)
            if row is None:
                from app.core.exceptions import NotFoundError

                raise NotFoundError("Rezervasyon oda satiri", self.reservation_room_id)

            reservation = row.reservation
            guest = reservation.primary_guest if reservation is not None else None
            currency = reservation.currency if reservation is not None else Currency.TRY

            summary = CheckinSummary(
                reservation_room_id=row.id,
                confirmation_number=(
                    reservation.confirmation_number if reservation is not None else "-"
                ),
                guest_id=guest.id if guest is not None else None,
                guest_name=guest.full_name if guest is not None else "-",
                guest_has_identity=bool(guest is not None and guest.identity_index),
                room_type_name=row.room_type.name if row.room_type is not None else "-",
                meal_plan=row.meal_plan.label,
                assigned_room_id=row.room_id,
                check_in=row.check_in_date,
                check_out=row.check_out_date,
                nights=row.nights,
                adults=row.adults,
                children=row.children,
                total_amount=Money.of(row.total_amount, currency),
                special_requests=(
                    (reservation.special_requests or "") if reservation is not None else ""
                ),
            )

            # --- Aday odalar ---
            rooms_repo = RoomRepository(ctx.session)
            reservations_repo = ReservationRepository(ctx.session)
            date_range = row.date_range
            bookings = reservations_repo.bookings_for_range(property_id, date_range)
            blocks = rooms_repo.blocks_for_range(property_id, date_range)

            options: list[RoomOption] = []
            for room in rooms_repo.list_rooms(
                property_id, room_type_id=row.room_type_id, only_sellable=True
            ):
                if room.occupancy_status is RoomOccupancyStatus.OCCUPIED:
                    continue
                if not is_room_available(
                    date_range,
                    room_id=room.id,
                    existing_bookings=bookings,
                    blocks=blocks,
                    exclude_reservation_room_id=row.id,
                ):
                    continue
                options.append(
                    RoomOption(
                        room_id=room.id,
                        number=room.number,
                        room_type_name=(room.room_type.name if room.room_type is not None else "-"),
                        is_dirty=room.housekeeping_status is RoomHousekeepingStatus.DIRTY,
                        status_label=room.housekeeping_status.label,
                    )
                )

            # Atanmis oda listede yoksa (or. servis disi isaretlenmis) yine de
            # gosterilir; aksi halde kullanici odanin neden kayboldugunu anlamaz.
            assigned = row.room
            if assigned is not None and all(o.room_id != assigned.id for o in options):
                options.insert(
                    0,
                    RoomOption(
                        room_id=assigned.id,
                        number=assigned.number,
                        room_type_name=(
                            assigned.room_type.name if assigned.room_type is not None else "-"
                        ),
                        is_dirty=assigned.housekeeping_status is RoomHousekeepingStatus.DIRTY,
                        status_label=assigned.housekeeping_status.label,
                    ),
                )

            summary.rooms = options
            return summary

    # ----------------------------------------------------------------- #
    #  Cizim
    # ----------------------------------------------------------------- #
    def _render(self) -> None:
        summary = self.summary
        labels = self._summary_labels

        labels["confirmation"].setText(summary.confirmation_number)
        labels["guest"].setText(
            summary.guest_name + ("" if summary.guest_has_identity else "  (kimlik bilgisi eksik)")
        )
        labels["room_type"].setText(summary.room_type_name)
        labels["dates"].setText(
            f"{format_short_date(summary.check_in)} - {format_short_date(summary.check_out)}"
            f"  ({format_nights(summary.nights)})"
        )
        children = f" + {summary.children} cocuk" if summary.children else ""
        labels["guests"].setText(f"{summary.adults} yetiskin{children}")
        labels["meal_plan"].setText(summary.meal_plan)
        labels["amount"].setText(summary.total_amount.format())

        if summary.special_requests:
            self._requests_label.setText(f"Ozel talep: {summary.special_requests}")
            self._requests_label.setVisible(True)

        self._room_combo.blockSignals(True)
        self._room_combo.clear()
        for option in summary.rooms:
            self._room_combo.addItem(option.display, option.room_id)
        if summary.assigned_room_id is not None:
            index = self._room_combo.findData(summary.assigned_room_id)
            if index >= 0:
                self._room_combo.setCurrentIndex(index)
        self._room_combo.blockSignals(False)

        if not summary.rooms:
            self._room_combo.addItem("Musait oda yok", None)
            self._room_combo.setEnabled(False)

        self._update_room_warning()

    def _selected_room(self) -> RoomOption | None:
        room_id = self._room_combo.currentData()
        if room_id is None:
            return None
        for option in self.summary.rooms:
            if option.room_id == room_id:
                return option
        return None

    def _update_room_warning(self) -> None:
        """Secili oda kirliyse uyari ve onay kutusunu gosterir."""
        option = self._selected_room()
        is_dirty = option is not None and option.is_dirty

        self._dirty_warning.setVisible(is_dirty)
        self._dirty_check.setVisible(is_dirty)
        if is_dirty and option is not None:
            self._dirty_warning.setText(
                f"Uyari: {option.number} numarali oda henuz temizlenmemis "
                f"({option.status_label}). Girisin yapilabilmesi icin asagidaki kutuyu "
                "isaretleyerek onay vermelisiniz."
            )
        else:
            self._dirty_check.setChecked(False)

        self._update_save_state()

    def _update_save_state(self) -> None:
        option = self._selected_room()
        if option is None:
            enabled = False
            tooltip = (
                "Bu oda tipinde secilen tarihlerde musait oda yok. "
                "Oda tipini degistirin veya bir blokeyi kaldirin."
            )
        elif option.is_dirty and not self._dirty_check.isChecked():
            enabled = False
            tooltip = "Kirli odaya giris icin onay kutusunu isaretleyin."
        else:
            enabled = True
            tooltip = "Girisi tamamlar, folyoyu acar ve oda ucretlerini isler."
        set_action_state(self._save_button, enabled=enabled, tooltip=tooltip)

    # ----------------------------------------------------------------- #
    #  Kayit
    # ----------------------------------------------------------------- #
    def _on_save(self) -> None:
        option = self._selected_room()
        if option is None:
            return

        identity = self._identity_edit.text().strip()
        early_hours = self._early_spin.value()

        try:
            with self.ui.service_context() as ctx:
                if identity:
                    from app.infrastructure.db.models.guests import Guest

                    ctx.require(Perm.GUEST_EDIT)
                    guest = (
                        ctx.session.get(Guest, self.summary.guest_id)
                        if self.summary.guest_id is not None
                        else None
                    )
                    if guest is not None:
                        # set_identity sifreli alani ve kor indeksi BIRLIKTE
                        # gunceller; ikisini elle yazmak indeksi bayatlatirdi.
                        guest.set_identity(identity)

                stay = FrontdeskService(ctx).check_in(
                    self.reservation_room_id,
                    room_id=option.room_id,
                    key_card_count=self._key_card_spin.value(),
                    early_check_in_hours=early_hours,
                    allow_dirty_room=self._dirty_check.isChecked(),
                )
                self.stay_id = stay.id
        except HotelError as exc:
            self._explain(exc)
            return

        self.accept()

    def _explain(self, exc: HotelError) -> None:
        """Sik gorulen hatalara somut bir cozum onerisi ekler."""
        remedies = {
            "room_dirty": (
                "Odanin temizlenmedigini onaylayan kutuyu isaretleyin veya baska bir oda secin."
            ),
            "already_checked_in": "Bu oda satiri icin giris zaten yapilmis; listeyi yenileyin.",
            "room_occupied": "Oda su anda dolu. Listeden bos bir oda secin.",
            "room_out_of_service": (
                "Oda bakim nedeniyle kullanilamiyor. Teknik servisle gorusun veya baska oda secin."
            ),
            "room_row_cancelled": "Iptal edilmis oda satirina giris yapilamaz.",
        }
        remedy = remedies.get(exc.code)
        if remedy:
            exc.context["cozum"] = remedy
        show_error(self, exc, title="Giris yapilamadi")


__all__ = ["KVKK_NOTICE", "CheckinDialog", "CheckinSummary", "RoomOption"]
