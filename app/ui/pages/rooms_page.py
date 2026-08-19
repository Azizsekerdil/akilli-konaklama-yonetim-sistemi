"""Oda plani ve oda listesi ekrani.

Iki gorunum tek ekranda toplanir:

* **Izgara (oda plani)** - odalar kat kat kartlar halinde. Resepsiyonun
  "hangi oda bos" sorusuna bir bakista yanit verir.
* **Liste** - suzulebilir, siralanabilir tablo. Toplu inceleme ve arama icin.

Erisilebilirlik karari
----------------------
Kart rengi :func:`~app.ui.theme.room_status_color` ile belirlenir ama durum
**metni de kartin uzerinde yazar**. Renk tek basina bilgi tasimaz; renk
korlugu olan bir kullanici da "Dolu / Kirli / Servis Disi" ayrimini yapabilir.
Ustteki renk aciklamasi (legend) esleme kurallarini gorunur kilar.

Oturum tuzagi
-------------
``service_context`` blogu bitince ORM nesneleri detached olur ve iliskilere
erisim ``DetachedInstanceError`` firlatir. Bu yuzden :meth:`RoomsPage.load_data`
tum veriyi blok icinde :class:`RoomInfo` veri siniflarina cevirir; arayuz
katmani ORM nesnesi gormez.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import BusinessRuleError, HotelError
from app.core.log import get_logger
from app.domain.enums import RoomHousekeepingStatus, RoomOccupancyStatus
from app.security.permissions import Perm
from app.ui.formatting import format_short_date
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.theme import Palette, active_palette, room_status_color
from app.ui.widgets.common import (
    Card,
    EmptyState,
    SearchBox,
    SectionTitle,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)

#: Izgarada bir satira sigan oda karti sayisi ve kart genisligi.
#: 6 x 132 + bosluklar + kart kenarlari = 874 piksel; 1250 piksellik pencerede
#: 260 piksellik ayrinti paneliyle birlikte yatay kaydirma cubugu olusmadan
#: sigar. Kart genisligi arttirilirsa bu hesap yeniden yapilmalidir.
GRID_COLUMNS = 6
TILE_WIDTH = 132
TILE_HEIGHT = 92
DETAIL_PANEL_WIDTH = 260

#: Etiketler genel stil sayfasindaki ``QWidget { background-color }`` kuralini
#: devralir ve kart yuzeyinin uzerine koyu bir serit cizer. Kural yalnizca ad
#: verilmis metin etiketlerini hedefler; rozetler (``BadgeDanger`` vb.) kendi
#: arka planini korumalidir, aksi halde renk kodlu uyari kaybolurdu.
TRANSPARENT_LABELS = """
QLabel#CardTitle, QLabel#KpiValue, QLabel#KpiDelta, QLabel#SectionTitle,
QLabel#Muted, QLabel#FieldValue {
    background: transparent;
}
"""


def operations_style() -> str:
    """Operasyon ekranlarinin ortak yerel stil parcasi.

    Iki duzeltmeyi tasir:

    1. :data:`TRANSPARENT_LABELS` - etiket arkasindaki koyu seritler.
    2. **Devre disi birincil dugme.** Genel stil sayfasinda
       ``QPushButton:disabled`` var ama ``QPushButton#Primary`` kuralindaki
       kimlik secicisi daha ozeldir; devre disi birakilmis "Tamamla" / "Coz"
       dugmesi tam parlak birincil renkte kalir ve kullaniciya tiklanabilir
       gorunur. Tiklar, hicbir sey olmaz. Burada ayni durum icin acik bir
       kural veriliyor.

    Renkler paletten okunur, sabit yazilmaz. Stil ``build()`` icinde bir kez
    uygulanir; calisma sirasinda tema degistirilirse ekran yenilendiginde
    yeniden kurulur (bkz. :meth:`RoomsPage.load_data`).
    """
    p = active_palette()
    return TRANSPARENT_LABELS + f"""
QPushButton#Primary:disabled {{
    background-color: {p.surface};
    color: {p.text_disabled};
    border: 1px solid {p.border};
}}
"""


#: Sag tik menusunden ayarlanabilen durumlar. Silme gibi geri alinamaz bir
#: islem menude YOKTUR; oda durumu her zaman geri alinabilir olmalidir.
QUICK_STATUSES: tuple[tuple[RoomHousekeepingStatus, str], ...] = (
    (RoomHousekeepingStatus.CLEAN, "Temiz yap"),
    (RoomHousekeepingStatus.DIRTY, "Kirli yap"),
    (RoomHousekeepingStatus.OUT_OF_SERVICE, "Servis disi yap"),
)


@dataclass(slots=True)
class RoomInfo:
    """Bir odanin ekranda gosterilen tum bilgileri (ORM'den bagimsiz)."""

    room_id: int
    number: str
    room_type_id: int
    room_type_name: str
    floor_label: str
    floor_order: int
    occupancy: str
    occupancy_label: str
    housekeeping: str
    housekeeping_label: str
    building_name: str | None = None
    features: list[str] = field(default_factory=list)
    guest_name: str | None = None
    guest_check_out: date | None = None
    ticket_label: str | None = None
    is_active: bool = True

    @property
    def location_label(self) -> str:
        """Izgara basligi, suzgec ve tabloda kullanilan **tam** konum.

        Kat adi tek basina benzersiz DEGILDIR: bir tesiste iki bina varsa
        her ikisinin de "1. Kat"i olur. Yalnizca kat adiyla gruplayan bir
        oda plani iki binanin odalarini tek bir kartta birlestirir ve
        "101, B101, 102, B102..." gibi ic ice gecmis, taranamayan bir liste
        uretir. Bina adi ile birlestirmek hem grubu hem siralamayi duzeltir.
        """
        if self.building_name:
            return f"{self.building_name} - {self.floor_label}"
        return self.floor_label

    @property
    def sort_key(self) -> tuple[str, int, int, str]:
        """Bina, kat ve oda numarasina gore dogal siralama anahtari.

        Oda numarasi metindir ("101", "A-12"); duz metin siralamasi "10"u
        "9"dan once koyar. Sayisal kismi ayirarak dogal sira elde edilir.
        """
        digits = "".join(ch for ch in self.number if ch.isdigit())
        return (
            self.building_name or "",
            self.floor_order,
            int(digits) if digits else 0,
            self.number,
        )

    @property
    def status_text(self) -> str:
        """Kart uzerinde gorunen kisa durum metni."""
        return f"{self.occupancy_label} - {self.housekeeping_label}"

    @property
    def features_text(self) -> str:
        return ", ".join(self.features) if self.features else "-"


class RoomTile(QFrame):
    """Oda plani izgarasindaki tek bir oda karti."""

    clicked = Signal(object)
    menu_requested = Signal(object, QPoint)

    def __init__(self, info: RoomInfo, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self._palette = palette
        self._selected = False

        self.setObjectName("RoomTile")
        self.setFixedSize(TILE_WIDTH, TILE_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda point: self.menu_requested.emit(self.info, self.mapToGlobal(point))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        number = QLabel(info.number)
        number.setObjectName("RoomTileNumber")

        room_type = QLabel(info.room_type_name)
        room_type.setObjectName("RoomTileType")
        room_type.setWordWrap(False)

        status = QLabel(info.status_text)
        status.setObjectName("RoomTileStatus")
        status.setWordWrap(True)

        layout.addWidget(number)
        layout.addWidget(room_type)
        layout.addWidget(status)
        layout.addStretch(1)

        tooltip = [f"{info.number} - {info.room_type_name}", info.status_text]
        if info.guest_name:
            tooltip.append(f"Misafir: {info.guest_name}")
        if info.ticket_label:
            tooltip.append(f"Ariza: {info.ticket_label}")
        self.setToolTip("\n".join(tooltip))

        self._apply_style()

    # ---------------- Gorunum ----------------
    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        """Kart stilini **paletten** kurar.

        Renkler kod icinde sabit yazilmaz; oda durumu rengi
        :func:`room_status_color`'dan, yuzey/metin renkleri etkin paletten
        gelir. Boylece tema degistiginde izgara da degisir.
        """
        p = self._palette
        accent = room_status_color(p, self.info.occupancy, self.info.housekeeping)
        border = f"2px solid {p.primary}" if self._selected else f"1px solid {p.border}"
        surface = p.surface_alt if self._selected else p.surface
        self.setStyleSheet(f"""
            QFrame#RoomTile {{
                background-color: {surface};
                border: {border};
                border-left: 6px solid {accent};
                border-radius: 8px;
            }}
            QFrame#RoomTile:hover {{
                background-color: {p.surface_hover};
            }}
            QFrame#RoomTile QLabel {{
                background: transparent;
            }}
            QLabel#RoomTileNumber {{
                font-size: 15pt;
                font-weight: 700;
                color: {p.text};
            }}
            QLabel#RoomTileType {{
                font-size: 8pt;
                color: {p.text_muted};
            }}
            QLabel#RoomTileStatus {{
                font-size: 8pt;
                font-weight: 600;
                color: {accent};
            }}
            """)

    # ---------------- Olaylar ----------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt imzasi
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.info)
        super().mousePressEvent(event)


class RoomsPage(BasePage):
    """Oda plani (izgara) ve oda listesi."""

    required_permission = Perm.ROOM_VIEW
    title = "Odalar"
    icon = "\U0001f6cf"

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._rooms: list[RoomInfo] = []
        self._tiles: dict[int, RoomTile] = {}
        self._selected_room_id: int | None = None
        self.setStyleSheet(operations_style())

        header = QHBoxLayout()
        header.addWidget(SectionTitle(t("nav.rooms")))
        header.addSpacing(12)
        self._summary_label = QLabel("-")
        self._summary_label.setObjectName("Muted")
        header.addWidget(self._summary_label)
        header.addStretch(1)

        self._refresh_button = QPushButton(t("common.refresh"))
        self._refresh_button.clicked.connect(lambda: self.refresh(force=True))
        header.addWidget(self._refresh_button)
        self.root_layout.addLayout(header)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_grid_tab(), "Oda Plani")
        self._tabs.addTab(self._build_list_tab(), "Liste")
        self.root_layout.addWidget(self._tabs, 1)

    # ---------------- Gorunum 1: izgara ----------------
    def _build_grid_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_legend())

        body = QHBoxLayout()
        body.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        self._grid_body = QVBoxLayout(container)
        self._grid_body.setContentsMargins(0, 0, 0, 0)
        self._grid_body.setSpacing(12)
        scroll.setWidget(container)
        body.addWidget(scroll, 1)

        body.addWidget(self._build_detail_panel())
        layout.addLayout(body, 1)
        return page

    def _build_legend(self) -> QWidget:
        """Renk aciklamasi - hangi rengin ne anlama geldigini gosterir."""
        palette = active_palette()
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        entries = (
            (palette.room_vacant_clean, "Bos - Temiz"),
            (palette.room_vacant_dirty, "Bos - Kirli"),
            (palette.room_occupied, "Dolu"),
            (palette.room_out_of_service, "Servis Disi"),
        )
        for color, label in entries:
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(f"background-color: {color}; border-radius: 3px;")
            text = QLabel(label)
            text.setObjectName("Muted")

            item = QHBoxLayout()
            item.setSpacing(6)
            item.setContentsMargins(0, 0, 0, 0)
            item.addWidget(swatch)
            item.addWidget(text)

            wrapper = QWidget()
            wrapper.setLayout(item)
            layout.addWidget(wrapper)

        layout.addStretch(1)
        return holder

    def _build_detail_panel(self) -> QWidget:
        self._detail_card = Card("Oda Ayrintisi", self)
        self._detail_card.setFixedWidth(DETAIL_PANEL_WIDTH)

        self._detail_title = QLabel("Bir oda secin")
        self._detail_title.setObjectName("SectionTitle")
        self._detail_card.add_widget(self._detail_title)

        self._detail_fields: dict[str, QLabel] = {}
        for key, label in (
            ("type", t("room.type")),
            ("floor", "Bina / Kat"),
            ("occupancy", "Doluluk"),
            ("housekeeping", "Temizlik"),
            ("guest", "Misafir"),
            ("checkout", t("reservation.check_out")),
            ("ticket", "Acik Ariza"),
            ("features", "Ozellikler"),
        ):
            row = QVBoxLayout()
            row.setSpacing(1)
            name = QLabel(label.upper())
            name.setObjectName("CardTitle")
            value = QLabel("-")
            value.setObjectName("FieldValue")
            value.setWordWrap(True)
            row.addWidget(name)
            row.addWidget(value)
            self._detail_card.add_layout(row)
            self._detail_fields[key] = value

        self._detail_card.body.addSpacing(6)
        self._status_buttons: list[QPushButton] = []
        for status, caption in QUICK_STATUSES:
            button = QPushButton(caption)
            button.clicked.connect(
                lambda _checked=False, s=status: self._change_status_of_selected(s)
            )
            self._detail_card.add_widget(button)
            self._status_buttons.append(button)

        self._detail_card.body.addStretch(1)

        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._detail_card)
        return wrapper

    # ---------------- Gorunum 2: liste ----------------
    def _build_list_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        filters = QHBoxLayout()
        filters.setSpacing(8)

        self._search = SearchBox("Oda no, tip veya ozellik ara")
        self._search.search_triggered.connect(self._apply_filters)
        filters.addWidget(self._search, 1)

        self._floor_filter = QComboBox()
        self._floor_filter.addItem("Tum katlar", None)
        self._floor_filter.currentIndexChanged.connect(lambda _index: self._apply_filters())
        filters.addWidget(self._floor_filter)

        self._type_filter = QComboBox()
        self._type_filter.addItem("Tum oda tipleri", None)
        self._type_filter.currentIndexChanged.connect(lambda _index: self._apply_filters())
        filters.addWidget(self._type_filter)

        self._status_filter = QComboBox()
        self._status_filter.addItem("Tum durumlar", None)
        for status in RoomHousekeepingStatus:
            self._status_filter.addItem(status.label, status.value)
        self._status_filter.currentIndexChanged.connect(lambda _index: self._apply_filters())
        filters.addWidget(self._status_filter)

        layout.addLayout(filters)

        self._table = FilterableTableView(
            [
                Column("number", t("room.number"), width=90),
                Column("room_type_name", t("room.type"), stretch=True),
                Column(
                    "location_label",
                    "Bina / Kat",
                    getter=lambda info: info.location_label,
                    width=150,
                ),
                Column(
                    "occupancy_label",
                    "Doluluk",
                    getter=lambda info: info.occupancy_label,
                    width=90,
                ),
                Column(
                    "housekeeping_label",
                    "Temizlik",
                    getter=lambda info: info.housekeeping_label,
                    width=130,
                ),
                Column(
                    "features",
                    "Ozellikler",
                    getter=lambda info: info.features_text,
                    stretch=True,
                ),
            ],
            parent=self,
        )
        # Oda listesi numaraya gore ARTAN sirada baslar. Qt'nin varsayilani
        # ilk sutunda azalandir ve liste son odadan baslardi.
        self._table.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._table.selection_changed.connect(self._on_table_selection)
        layout.addWidget(self._table, 1)

        self._list_empty = EmptyState(
            "Suzgeclere uyan oda yok",
            hint="Kat, oda tipi veya durum suzgecini genisletin.",
            parent=self,
        )
        self._list_empty.setVisible(False)
        layout.addWidget(self._list_empty)

        self._list_count = QLabel("-")
        self._list_count.setObjectName("Muted")
        layout.addWidget(self._list_count)
        return page

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload, selectinload

        from app.application.services.maintenance_service import MaintenanceService
        from app.infrastructure.db.base import utcnow
        from app.infrastructure.db.models.organization import Floor
        from app.infrastructure.db.models.rooms import Room, RoomType
        from app.infrastructure.db.repositories import ReservationRepository

        with self.ui.service_context(commit=False) as ctx:
            property_id = ctx.require_property()
            today = utcnow().date()

            # Iliskiler onceden yuklenir; aksi halde her oda icin ayri sorgu
            # calisir (40 odada 160 sorgu) ve ekran gorunur sekilde yavaslar.
            rooms = (
                ctx.session.scalars(
                    select(Room)
                    .options(
                        joinedload(Room.room_type).selectinload(RoomType.features),
                        joinedload(Room.floor).joinedload(Floor.building),
                        selectinload(Room.extra_features),
                    )
                    .where(Room.property_id == property_id)
                )
                .unique()
                .all()
            )

            guests: dict[int, tuple[str, date]] = {}
            if ctx.can(Perm.RESERVATION_VIEW):
                for row in ReservationRepository(ctx.session).in_house_on(property_id, today):
                    if row.room_id is None:
                        continue
                    guest = row.reservation.primary_guest if row.reservation else None
                    guests[row.room_id] = (
                        guest.full_name if guest is not None else "-",
                        row.check_out_date,
                    )

            tickets: dict[int, str] = {}
            if ctx.can(Perm.MAINTENANCE_VIEW):
                for ticket in MaintenanceService(ctx).open_tickets():
                    if ticket.room_id is None or ticket.room_id in tickets:
                        continue
                    tickets[ticket.room_id] = (
                        f"{ticket.ticket_number} - {ticket.title} ({ticket.priority.label})"
                    )

            infos = [
                self._to_info(room, guests.get(room.id), tickets.get(room.id)) for room in rooms
            ]

        # Tema calisma sirasinda degistirilmis olabilir; yerel stil parcasi
        # palet renkleri tasidigi icin her yenilemede yeniden kurulur.
        self.setStyleSheet(operations_style())
        self._rooms = sorted(infos, key=lambda info: info.sort_key)

        # Ayrinti paneli bos acilmasin: secim yoksa (ya da secili oda silinmisse)
        # ilk oda secilir. Bos bir panel kullaniciya panelin ne ise yaradigini
        # anlatmaz; dolu bir panel anlatir.
        known = {info.room_id for info in self._rooms}
        if self._selected_room_id not in known:
            self._selected_room_id = self._rooms[0].room_id if self._rooms else None

        self._refresh_filter_options()
        self._render_grid()
        self._apply_filters()
        self._update_summary()
        self._update_detail()

    @staticmethod
    def _to_info(
        room,
        guest: tuple[str, date] | None,
        ticket_label: str | None,
    ) -> RoomInfo:
        """ORM odasini ekran veri yapisina cevirir - **oturum icinde** cagrilir."""
        features = [feature.name for feature in room.room_type.features]
        features += [feature.name for feature in room.extra_features]
        if room.view.value != "none":
            features.append(room.view.label)
        if room.is_smoking:
            features.append("Sigara Icilebilir")
        if room.is_accessible:
            features.append("Engelli Erisimine Uygun")

        floor = room.floor
        if floor is not None:
            floor_label = floor.name or f"{floor.number}. Kat"
            floor_order = floor.number
            building_name = floor.building.name if floor.building is not None else None
        else:
            floor_label = "Kat Atanmamis"
            floor_order = 999
            building_name = None

        return RoomInfo(
            room_id=room.id,
            number=room.number,
            room_type_id=room.room_type_id,
            room_type_name=room.room_type.name,
            floor_label=floor_label,
            floor_order=floor_order,
            building_name=building_name,
            occupancy=room.occupancy_status.value,
            occupancy_label=room.occupancy_status.label,
            housekeeping=room.housekeeping_status.value,
            housekeeping_label=room.housekeeping_status.label,
            features=features,
            guest_name=guest[0] if guest else None,
            guest_check_out=guest[1] if guest else None,
            ticket_label=ticket_label,
            is_active=room.is_active,
        )

    # ----------------------------------------------------------------- #
    #  Izgara cizimi
    # ----------------------------------------------------------------- #
    def _render_grid(self) -> None:
        self._clear_layout(self._grid_body)
        self._tiles.clear()

        if not self._rooms:
            self._grid_body.addWidget(
                EmptyState(
                    "Bu tesiste tanimli oda yok",
                    hint="Ayarlar ekranindan oda ve oda tipi tanimlayabilirsiniz.",
                    parent=self,
                )
            )
            return

        palette = active_palette()
        current_floor: str | None = None
        grid: QGridLayout | None = None
        index = 0

        for info in self._rooms:
            # Gruplama bina + kat birlesimine gore yapilir; yalnizca kat adi
            # kullanilsaydi iki binanin "1. Kat"i tek kartta birleserdi.
            if info.location_label != current_floor:
                current_floor = info.location_label
                card = Card(current_floor, self)
                grid = QGridLayout()
                grid.setSpacing(10)
                grid.setContentsMargins(0, 0, 0, 0)
                card.add_layout(grid)
                self._grid_body.addWidget(card)
                index = 0

            tile = RoomTile(info, palette, self)
            tile.clicked.connect(self._select_room)
            tile.menu_requested.connect(self._show_tile_menu)
            if grid is not None:
                grid.addWidget(tile, index // GRID_COLUMNS, index % GRID_COLUMNS)
            self._tiles[info.room_id] = tile
            index += 1

        self._grid_body.addStretch(1)

        if self._selected_room_id in self._tiles:
            self._tiles[self._selected_room_id].set_selected(True)

    @staticmethod
    def _clear_layout(layout) -> None:
        """Yerlesimi ve icindeki tum bilesenleri temizler."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                RoomsPage._clear_layout(child)

    # ----------------------------------------------------------------- #
    #  Secim ve ayrinti
    # ----------------------------------------------------------------- #
    def _select_room(self, info: RoomInfo) -> None:
        previous = self._tiles.get(self._selected_room_id or -1)
        if previous is not None:
            previous.set_selected(False)

        self._selected_room_id = info.room_id
        tile = self._tiles.get(info.room_id)
        if tile is not None:
            tile.set_selected(True)
        self._update_detail()

    def _on_table_selection(self, info: object) -> None:
        if isinstance(info, RoomInfo):
            self._select_room(info)

    def _selected_info(self) -> RoomInfo | None:
        for info in self._rooms:
            if info.room_id == self._selected_room_id:
                return info
        return None

    def _update_detail(self) -> None:
        info = self._selected_info()
        can_change = self.ui.can(Perm.ROOM_STATUS_CHANGE)

        for button in self._status_buttons:
            button.setEnabled(info is not None and can_change)
            if not can_change:
                button.setToolTip("Oda durumu degistirme yetkiniz bulunmuyor.")

        if info is None:
            self._detail_title.setText("Bir oda secin")
            for value in self._detail_fields.values():
                value.setText("-")
            return

        self._detail_title.setText(f"{info.number} numarali oda")
        self._detail_fields["type"].setText(info.room_type_name)
        self._detail_fields["floor"].setText(info.location_label)
        self._detail_fields["occupancy"].setText(info.occupancy_label)
        self._detail_fields["housekeeping"].setText(info.housekeeping_label)
        self._detail_fields["guest"].setText(info.guest_name or "-")
        self._detail_fields["checkout"].setText(format_short_date(info.guest_check_out))
        self._detail_fields["ticket"].setText(info.ticket_label or "Acik ariza kaydi yok")
        self._detail_fields["features"].setText(info.features_text)

    # ----------------------------------------------------------------- #
    #  Suzgecler
    # ----------------------------------------------------------------- #
    def _refresh_filter_options(self) -> None:
        """Kat ve oda tipi suzgeclerini mevcut veriden yeniden kurar.

        Kat suzgeci **bina + kat** birlesimini tasir. Yalnizca kat numarasi
        tasisaydi "1. Kat" secimi iki binanin birinci katlarini birlikte
        gosterir ve suzgec ise yaramazdi.
        """
        floors: dict[tuple[str, int], str] = {}
        types: dict[int, str] = {}
        for info in self._rooms:
            floors.setdefault((info.building_name or "", info.floor_order), info.location_label)
            types.setdefault(info.room_type_id, info.room_type_name)

        self._reload_combo(
            self._floor_filter,
            "Tum katlar",
            [(label, label) for _key, label in sorted(floors.items())],
        )
        self._reload_combo(
            self._type_filter,
            "Tum oda tipleri",
            sorted(types.items(), key=lambda pair: pair[1]),
        )

    @staticmethod
    def _reload_combo(combo: QComboBox, all_caption: str, entries) -> None:
        """Secimi koruyarak acilir listeyi yeniden doldurur."""
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_caption, None)
        for value, label in entries:
            combo.addItem(label, value)
        position = combo.findData(previous)
        combo.setCurrentIndex(position if position >= 0 else 0)
        combo.blockSignals(False)

    def _apply_filters(self, _query: str | None = None) -> None:
        location = self._floor_filter.currentData()
        room_type_id = self._type_filter.currentData()
        status = self._status_filter.currentData()

        def matches(info: RoomInfo) -> bool:
            if location is not None and info.location_label != location:
                return False
            if room_type_id is not None and info.room_type_id != room_type_id:
                return False
            return not (status is not None and info.housekeeping != status)

        self._table.set_rows(self._rooms)
        self._table.set_predicate(matches)
        self._table.set_query(self._search.text().strip())

        visible = self._table.visible_count
        self._list_empty.setVisible(visible == 0)
        self._table.setVisible(visible > 0)
        self._list_count.setText(f"{visible} / {len(self._rooms)} oda gosteriliyor")

    def _update_summary(self) -> None:
        total = len(self._rooms)
        occupied = sum(
            1 for info in self._rooms if info.occupancy == RoomOccupancyStatus.OCCUPIED.value
        )
        dirty = sum(
            1 for info in self._rooms if info.housekeeping == RoomHousekeepingStatus.DIRTY.value
        )
        out_of_service = sum(
            1
            for info in self._rooms
            if info.housekeeping
            in {
                RoomHousekeepingStatus.OUT_OF_SERVICE.value,
                RoomHousekeepingStatus.OUT_OF_ORDER.value,
            }
        )
        self._summary_label.setText(
            f"{total} oda - {occupied} dolu, {dirty} kirli, {out_of_service} servis disi"
        )

    # ----------------------------------------------------------------- #
    #  Durum degisimi
    # ----------------------------------------------------------------- #
    def _show_tile_menu(self, info: RoomInfo, position: QPoint) -> None:
        self._select_room(info)
        can_change = self.ui.can(Perm.ROOM_STATUS_CHANGE)

        menu = QMenu(self)
        for status, caption in QUICK_STATUSES:
            action = menu.addAction(caption)
            action.setEnabled(can_change and info.housekeeping != status.value)
            action.triggered.connect(
                lambda _checked=False, s=status, i=info: self._change_status(i, s)
            )
        if not can_change:
            menu.setToolTip("Oda durumu degistirme yetkiniz bulunmuyor.")
        menu.exec(position)

    def _change_status_of_selected(self, status: RoomHousekeepingStatus) -> None:
        info = self._selected_info()
        if info is not None:
            self._change_status(info, status)

    def _change_status(self, info: RoomInfo, status: RoomHousekeepingStatus) -> None:
        """Oda durumunu degistirir.

        Odayi satisa kapatmak yikici bir islemdir (o gece oda satilamaz),
        bu yuzden ayrica onay istenir. Odada bu gece aktif bir rezervasyon
        varsa servis islemi durdurur; uyari burada **karar noktasina**
        cevrilir ve yalnizca :data:`Perm.RESERVATION_OVERRIDE` yetkisi olan
        kullaniciya "yine de kapat" secenegi sunulur.
        """
        from app.application.services.housekeeping_service import HousekeepingService

        dangerous = status is RoomHousekeepingStatus.OUT_OF_SERVICE
        if dangerous and not confirm(
            self,
            f"{info.number} numarali oda satisa kapatilsin mi?",
            detail="Bu odaya yeni rezervasyon alinamaz. Islem geri alinabilir.",
            dangerous=True,
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                HousekeepingService(ctx).set_room_status(info.room_id, status)
        except BusinessRuleError as exc:
            if exc.code == "room_has_reservation" and self._offer_override(exc):
                if not self._force_status(info, status):
                    return
            else:
                show_error(self, exc)
                return
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(
            self,
            f"{info.number} numarali oda '{status.label}' yapildi.",
            ToastLevel.SUCCESS,
        )
        self.refresh(force=True)

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

    def _force_status(self, info: RoomInfo, status: RoomHousekeepingStatus) -> bool:
        """Cakismaya ragmen durumu degistirir. Basarili ise ``True``."""
        from app.application.services.housekeeping_service import HousekeepingService

        try:
            with self.ui.service_context() as ctx:
                HousekeepingService(ctx).set_room_status(info.room_id, status, force=True)
        except HotelError as exc:
            show_error(self, exc)
            return False
        return True


__all__ = [
    "DETAIL_PANEL_WIDTH",
    "GRID_COLUMNS",
    "TILE_HEIGHT",
    "TILE_WIDTH",
    "TRANSPARENT_LABELS",
    "RoomInfo",
    "RoomTile",
    "RoomsPage",
    "operations_style",
]
