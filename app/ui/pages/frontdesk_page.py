"""On buro ekrani: bugunku girisler, cikislar ve otelde olanlar.

Ekran gunun uc temel sorusunu uc sekmede yanitlar:

1. **Bugunku Girisler** - kim gelecek, odasi atandi mi, giris yapildi mi?
2. **Bugunku Cikislar** - kim cikacak, hesabinda acik bakiye var mi?
3. **Otelde** - su anda kimler kaliyor, folyolari ne durumda?

Veri erisimi ilkesi
-------------------
ORM nesneleri ``service_context`` blogunun disina TASINMAZ. Blok bitince
nesneler oturumdan kopar (detached) ve iliskilere erisim
``DetachedInstanceError`` firlatir. Bu yuzden :meth:`FrontdeskPage.load_data`
tum satirlari blok icinde :class:`ArrivalRow` / :class:`StayRow` gibi duz veri
yapilarina cevirir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.services.frontdesk_service import FrontdeskService
from app.core.log import get_logger
from app.domain.enums import Currency
from app.domain.value_objects import Money
from app.infrastructure.db.base import utcnow
from app.security.permissions import Perm
from app.ui.formatting import format_date, format_short_date
from app.ui.pages.base import BasePage
from app.ui.theme import active_palette
from app.ui.widgets.common import (
    Card,
    EmptyState,
    KpiCard,
    SearchBox,
    SectionTitle,
    StatusBadge,
    ToastLevel,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

if TYPE_CHECKING:  # pragma: no cover - yalnizca tip denetimi icin
    from app.infrastructure.db.models.billing import Folio
    from app.infrastructure.db.models.reservations import ReservationRoom

log = get_logger(__name__)


# --------------------------------------------------------------------------
#  Duz veri yapilari
# --------------------------------------------------------------------------
@dataclass(slots=True)
class ArrivalRow:
    """Bugun giris yapacak tek bir oda satiri."""

    reservation_room_id: int
    confirmation_number: str = "-"
    guest_name: str = "-"
    room_type_name: str = "-"
    room_number: str = "-"
    nights: int = 0
    guest_count: int = 1
    checked_in: bool = False

    @property
    def status_text(self) -> str:
        if self.checked_in:
            return "Giris yapildi"
        return "Bekliyor" if self.room_number != "-" else "Oda atanmadi"


@dataclass(slots=True)
class StayRow:
    """Cikis ve otelde sekmelerinin ortak satiri.

    Iki sekme ayni alanlari gosterir (yalnizca sutun basliklari farklidir),
    bu yuzden tek bir yapi kullaniliyor.
    """

    reservation_room_id: int
    stay_id: int | None = None
    folio_id: int | None = None
    room_number: str = "-"
    guest_name: str = "-"
    confirmation_number: str = "-"
    check_in: date | None = None
    check_out: date | None = None
    balance: Money = field(default_factory=Money.zero)
    checked_in: bool = False
    checked_out: bool = False

    @property
    def has_open_balance(self) -> bool:
        return self.balance.amount > 0

    @property
    def status_text(self) -> str:
        """Satirin konaklama durumu.

        ``FrontdeskService.in_house()`` sozlesmesi geregi bugun giris yapacak
        ama henuz GELMEMIS satirlari da dondurur. Durum sutunu olmadan bu
        satirlar "Otelde" basligi altinda gercekten otelde olanlarla ayni
        gorunuyordu; bakiyenin ``-`` olmasi tek basina yeterli ipucu degil.
        """
        if self.checked_out:
            return "Cikis yapildi"
        if self.checked_in:
            return "Otelde"
        return "Bekleniyor"


@dataclass(slots=True)
class FrontdeskSnapshot:
    """Ekranin tek seferde yukledigi tum veri."""

    day: date
    arrivals: list[ArrivalRow] = field(default_factory=list)
    departures: list[StayRow] = field(default_factory=list)
    in_house: list[StayRow] = field(default_factory=list)
    open_balance: Money = field(default_factory=Money.zero)


def _balance_value(row: StayRow) -> Money | None:
    """Siralama ve gosterim icin bakiye degeri.

    Folyosu olmayan satirda ``0,00`` yazmak yaniltici olurdu ("hesap kapali"
    sanilir); bu satirlarda deger ``None`` doner ve tabloda ``-`` gorunur.
    """
    return row.balance if row.folio_id is not None else None


def _format_balance(value: Money | None) -> str:
    """Bakiyeyi gosterir; acik bakiyede renk TEK BASINA bilgi tasimaz.

    Uyari rengine ek olarak metne de "acik" yazilir; renk korlugu olan
    kullanici da durumu ayirt edebilmelidir.
    """
    if value is None:
        return "-"
    if value.amount > 0:
        return f"{value.format()}  (acik)"
    if value.amount < 0:
        return f"{value.format()}  (fazla odeme)"
    return value.format()


def _balance_color(row: StayRow) -> str | None:
    palette = active_palette()
    if row.folio_id is None:
        return None
    if row.balance.amount > 0:
        return palette.warning
    if row.balance.amount < 0:
        return palette.info
    return None


def _arrival_status_color(row: ArrivalRow) -> str | None:
    palette = active_palette()
    if row.checked_in:
        return palette.success
    return palette.warning if row.room_number == "-" else None


def _stay_status_color(row: StayRow) -> str | None:
    """Durum sutununun rengi; renk TEK BASINA bilgi tasimaz (metin de yazar)."""
    palette = active_palette()
    if row.checked_out:
        return palette.success
    if not row.checked_in:
        return palette.warning
    return None


def _stay_status_column() -> Column:
    """Cikis ve otelde sekmelerinin ortak durum sutunu."""
    return Column(
        "status",
        "Durum",
        getter=lambda row: row.status_text,
        width=130,
        color_getter=_stay_status_color,
    )


# --------------------------------------------------------------------------
#  Sayfa
# --------------------------------------------------------------------------
class FrontdeskPage(BasePage):
    """Giris, cikis ve otelde olan misafirlerin tek ekranda yonetimi."""

    required_permission = Perm.FRONTDESK_CHECKIN
    title = "On Buro"
    icon = "\U0001f6ce"

    def build(self) -> None:
        self.snapshot = FrontdeskSnapshot(day=utcnow().date())

        # --- Baslik satiri ---
        header = QHBoxLayout()
        self._title_label = SectionTitle("On Buro")
        self._date_label = QLabel()
        self._date_label.setObjectName("Muted")
        self._refresh_button = QPushButton("Yenile")
        self._refresh_button.clicked.connect(lambda: self.refresh(force=True))

        header.addWidget(self._title_label)
        header.addSpacing(12)
        header.addWidget(self._date_label)
        header.addStretch(1)
        header.addWidget(self._refresh_button)
        self.root_layout.addLayout(header)

        # --- KPI satiri ---
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self._kpis: dict[str, KpiCard] = {
            "pending_arrivals": KpiCard("Bekleyen Giris", "-"),
            "pending_departures": KpiCard("Bekleyen Cikis", "-"),
            "in_house": KpiCard("Otelde", "-"),
            "open_balance": KpiCard("Acik Bakiye", "-"),
        }
        # Esit genislik: kartlar farkli uzunlukta metin tasidiginda esnek
        # genislik olculeri kartlari farkli boyda gosterip satiri egri kilar.
        for card in self._kpis.values():
            kpi_row.addWidget(card, 1)
        self.root_layout.addLayout(kpi_row)

        # --- Sekmeler ---
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_arrivals_tab(), "Bugunku Girisler")
        self._tabs.addTab(self._build_departures_tab(), "Bugunku Cikislar")
        self._tabs.addTab(self._build_in_house_tab(), "Otelde")
        self.root_layout.addWidget(self._tabs, 1)

    # ----------------------------------------------------------------- #
    #  Sekme kurulumu
    # ----------------------------------------------------------------- #
    def _build_arrivals_tab(self) -> QWidget:
        columns = [
            Column("confirmation_number", "Onay No", width=140),
            Column("guest_name", "Misafir", stretch=True),
            Column("room_type_name", "Oda Tipi", width=150),
            Column("room_number", "Oda", width=70),
            Column("nights", "Gece", width=62, align=Qt.AlignmentFlag.AlignCenter),
            Column("guest_count", "Kisi", width=62, align=Qt.AlignmentFlag.AlignCenter),
            Column(
                "status",
                "Durum",
                getter=lambda row: row.status_text,
                width=130,
                color_getter=_arrival_status_color,
            ),
        ]
        self._arrivals_table = FilterableTableView(columns, parent=self)
        self._arrivals_table.selection_changed.connect(lambda _: self._update_actions())
        self._arrivals_table.row_activated.connect(lambda _: self._on_check_in())

        self._arrivals_empty = EmptyState(
            "Bugun icin giris bekleyen rezervasyon yok.",
            hint="Farkli bir gune bakmak icin Rezervasyonlar ekranini kullanabilirsiniz.",
            icon="\U0001f6cf",
            parent=self,
        )

        self._arrivals_search = SearchBox("Onay no, misafir veya oda ara")
        self._arrivals_search.search_triggered.connect(self._arrivals_table.set_query)

        self._arrivals_badge = StatusBadge("Satir secilmedi", "info", self)
        self._check_in_button = QPushButton("Giris Yap")
        self._check_in_button.setObjectName("Primary")
        self._check_in_button.clicked.connect(self._on_check_in)

        return self._compose_tab(
            self._arrivals_search,
            [self._arrivals_badge, self._check_in_button],
            self._arrivals_table,
            self._arrivals_empty,
            "Bugunku Girisler",
        )

    def _build_departures_tab(self) -> QWidget:
        columns = [
            Column("room_number", "Oda", width=80),
            Column("guest_name", "Misafir", stretch=True),
            Column(
                "check_in",
                "Giris",
                formatter=format_short_date,
                width=115,
            ),
            Column(
                "check_out",
                "Cikis",
                formatter=format_short_date,
                width=115,
            ),
            Column(
                "balance",
                "Bakiye",
                getter=_balance_value,
                formatter=_format_balance,
                width=210,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color_getter=_balance_color,
            ),
            _stay_status_column(),
        ]
        self._departures_table = FilterableTableView(columns, parent=self)
        self._departures_table.selection_changed.connect(lambda _: self._update_actions())
        self._departures_table.row_activated.connect(lambda _: self._on_check_out())

        self._departures_empty = EmptyState(
            "Bugun cikis yapacak misafir yok.",
            hint="Erken cikis icin misafiri 'Otelde' sekmesinden bulabilirsiniz.",
            icon="\U0001f9f3",
            parent=self,
        )

        self._departures_search = SearchBox("Oda veya misafir ara")
        self._departures_search.search_triggered.connect(self._departures_table.set_query)

        self._departures_badge = StatusBadge("Satir secilmedi", "info", self)
        self._check_out_button = QPushButton("Cikis Yap")
        self._check_out_button.setObjectName("Primary")
        self._check_out_button.clicked.connect(self._on_check_out)

        return self._compose_tab(
            self._departures_search,
            [self._departures_badge, self._check_out_button],
            self._departures_table,
            self._departures_empty,
            "Bugunku Cikislar",
        )

    def _build_in_house_tab(self) -> QWidget:
        columns = [
            Column("room_number", "Oda", width=80),
            Column("guest_name", "Misafir", stretch=True),
            Column("check_in", "Giris", formatter=format_short_date, width=115),
            Column(
                "check_out",
                "Planlanan Cikis",
                formatter=format_short_date,
                width=140,
            ),
            Column(
                "balance",
                "Bakiye",
                getter=_balance_value,
                formatter=_format_balance,
                width=210,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color_getter=_balance_color,
            ),
            _stay_status_column(),
        ]
        self._in_house_table = FilterableTableView(columns, parent=self)
        self._in_house_table.selection_changed.connect(lambda _: self._update_actions())
        self._in_house_table.row_activated.connect(lambda _: self._on_open_folio())

        self._in_house_empty = EmptyState(
            "Su anda otelde konaklayan misafir yok.",
            hint="Girisler yapildikca bu liste dolar.",
            icon="\U0001f3e8",
            parent=self,
        )

        self._in_house_search = SearchBox("Oda veya misafir ara")
        self._in_house_search.search_triggered.connect(self._in_house_table.set_query)

        self._in_house_badge = StatusBadge("Satir secilmedi", "info", self)
        self._folio_button = QPushButton("Folyo")
        self._folio_button.setObjectName("Primary")
        self._folio_button.clicked.connect(self._on_open_folio)

        return self._compose_tab(
            self._in_house_search,
            [self._in_house_badge, self._folio_button],
            self._in_house_table,
            self._in_house_empty,
            "Otelde",
        )

    def _compose_tab(
        self,
        search: SearchBox,
        actions: list[QWidget],
        table: FilterableTableView,
        empty: EmptyState,
        card_title: str,
    ) -> QWidget:
        """Arama + eylem cubugu + tablo/bos durum duzenini kurar."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        # Alt sinir olmadan QLineEdit kendi (dar) boyut ipucunda kalir ve
        # yer tutucu metin "Oda veya misafi..." diye kirpilir.
        search.setMinimumWidth(300)
        search.setMaximumWidth(360)
        toolbar.addWidget(search)
        toolbar.addStretch(1)
        for widget in actions:
            toolbar.addWidget(widget)
        layout.addLayout(toolbar)

        card = Card(card_title, page)
        card.add_widget(table)
        card.add_widget(empty)
        empty.setVisible(False)
        layout.addWidget(card, 1)
        return page

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        self.snapshot = self._load()
        self._render()

    def _load(self) -> FrontdeskSnapshot:
        """Uc listeyi ve acik bakiye toplamini tek oturumda hazirlar."""
        from sqlalchemy import select

        from app.domain.enums import FolioStatus
        from app.infrastructure.db.models.billing import Folio
        from app.infrastructure.db.repositories import FolioRepository

        with self.ui.service_context(commit=False) as ctx:
            service = FrontdeskService(ctx)
            day = utcnow().date()
            snapshot = FrontdeskSnapshot(day=day)

            arrivals = service.arrivals_today(day)
            departures = service.departures_today(day)
            in_house = service.in_house(day)

            # Folyolar TEK sorguda okunur; satir basina sorgu (N+1) yuksek
            # sezonda onlarca gereksiz gidis-donus demektir.
            reservation_ids = {row.reservation_id for row in [*departures, *in_house]}
            folios: dict[int, Folio] = {}
            if reservation_ids:
                rows = ctx.session.scalars(
                    select(Folio)
                    .where(
                        Folio.reservation_id.in_(reservation_ids),
                        Folio.status == FolioStatus.OPEN,
                    )
                    .order_by(Folio.id)
                ).all()
                for folio in rows:
                    if folio.reservation_id is not None:
                        folios.setdefault(folio.reservation_id, folio)

            snapshot.arrivals = [self._to_arrival(row) for row in arrivals]
            snapshot.departures = [self._to_stay_row(row, folios) for row in departures]
            snapshot.in_house = [self._to_stay_row(row, folios) for row in in_house]

            unsettled = FolioRepository(ctx.session).unsettled_folios(ctx.require_property())
            total = sum((folio.balance for folio in unsettled), start=Decimal("0.00"))
            snapshot.open_balance = Money.of(total, Currency.TRY)
            return snapshot

    @staticmethod
    def _to_arrival(row: ReservationRoom) -> ArrivalRow:
        """``ReservationRoom`` satirini duz veriye cevirir (oturum icinde)."""
        reservation = row.reservation
        guest = reservation.primary_guest if reservation is not None else None
        return ArrivalRow(
            reservation_room_id=row.id,
            confirmation_number=(
                reservation.confirmation_number if reservation is not None else "-"
            ),
            guest_name=guest.full_name if guest is not None else "-",
            room_type_name=row.room_type.name if row.room_type is not None else "-",
            room_number=row.room.number if row.room is not None else "-",
            nights=row.nights,
            guest_count=row.total_guests,
            checked_in=row.stay is not None,
        )

    @staticmethod
    def _to_stay_row(row: ReservationRoom, folios: dict[int, Folio]) -> StayRow:
        """``ReservationRoom`` satirini cikis/otelde satirina cevirir."""
        reservation = row.reservation
        guest = reservation.primary_guest if reservation is not None else None
        stay = row.stay
        folio = folios.get(row.reservation_id)
        currency = reservation.currency if reservation is not None else Currency.TRY

        return StayRow(
            reservation_room_id=row.id,
            stay_id=stay.id if stay is not None else None,
            folio_id=folio.id if folio is not None else None,
            room_number=row.room.number if row.room is not None else "-",
            guest_name=guest.full_name if guest is not None else "-",
            confirmation_number=(
                reservation.confirmation_number if reservation is not None else "-"
            ),
            check_in=row.check_in_date,
            check_out=row.check_out_date,
            balance=Money.of(folio.balance if folio is not None else Decimal("0.00"), currency),
            checked_in=stay is not None,
            checked_out=stay is not None and not stay.is_in_house,
        )

    # ----------------------------------------------------------------- #
    #  Cizim
    # ----------------------------------------------------------------- #
    def _render(self) -> None:
        snapshot = self.snapshot
        # strftime("%B") Windows'ta Ingilizce ay adi dondurur; kendi
        # bicimlendiricimizi kullaniyoruz.
        self._date_label.setText(format_date(snapshot.day, with_day_name=True))

        pending_arrivals = sum(1 for row in snapshot.arrivals if not row.checked_in)
        pending_departures = sum(1 for row in snapshot.departures if not row.checked_out)
        unpaid = sum(1 for row in snapshot.departures if row.has_open_balance)

        self._kpis["pending_arrivals"].set_value(str(pending_arrivals))
        self._kpis["pending_arrivals"].set_delta(
            f"Toplam {len(snapshot.arrivals)} giris", direction=0
        )
        self._kpis["pending_departures"].set_value(str(pending_departures))
        if unpaid:
            self._kpis["pending_departures"].set_delta(f"{unpaid} acik hesap", direction=-1)
        else:
            self._kpis["pending_departures"].set_delta(
                f"Toplam {len(snapshot.departures)} cikis", direction=0
            )
        # "Otelde" sayisi GERCEKTEN giris yapmis satirlari sayar.
        # FrontdeskService.in_house() bugun gelecek ama henuz gelmemis satirlari
        # da dondurur; hepsini saymak karti oldugundan buyuk gosterirdi.
        in_house_now = sum(1 for row in snapshot.in_house if row.checked_in)
        awaited = len(snapshot.in_house) - in_house_now
        in_house_unpaid = sum(
            1 for row in snapshot.in_house if row.checked_in and row.has_open_balance
        )
        self._kpis["in_house"].set_value(str(in_house_now))
        # Her KPI kartinda alt satir bulunmali; biri bos kalirsa o kart
        # digerlerinden kisa cizilir ve satir hizasi bozulur.
        if awaited:
            self._kpis["in_house"].set_delta(f"{awaited} misafir bekleniyor", direction=0)
        elif in_house_unpaid:
            self._kpis["in_house"].set_delta(f"{in_house_unpaid} acik hesap", direction=-1)
        else:
            self._kpis["in_house"].set_delta("Tum hesaplar kapali", direction=0)
        self._kpis["in_house"].setToolTip(
            f"Giris yapmis {in_house_now} konaklama, {in_house_unpaid} tanesinde acik hesap. "
            f"Bugun gelmesi beklenen {awaited} satir 'Otelde' sekmesinde 'Bekleniyor' "
            "durumuyla listelenir."
        )
        self._kpis["open_balance"].set_value(snapshot.open_balance.format())
        self._kpis["open_balance"].set_delta(
            "Tahsil edilmemis folyo bakiyesi",
            direction=-1 if snapshot.open_balance.amount > 0 else 0,
        )

        self._arrivals_table.set_rows(snapshot.arrivals)
        self._departures_table.set_rows(snapshot.departures)
        self._in_house_table.set_rows(snapshot.in_house)

        for table, empty, rows in (
            (self._arrivals_table, self._arrivals_empty, snapshot.arrivals),
            (self._departures_table, self._departures_empty, snapshot.departures),
            (self._in_house_table, self._in_house_empty, snapshot.in_house),
        ):
            table.setVisible(bool(rows))
            empty.setVisible(not rows)

        self._update_actions()

    def _update_actions(self) -> None:
        """Secime ve yetkiye gore dugmeleri ayarlar.

        Arayuz tek savunma hatti degildir: servis katmani ayni yetkileri
        tekrar kontrol eder. Buradaki amac kullaniciya yapamayacagi bir islemi
        denetmemek ve nedenini gostermektir.
        """
        self._update_arrival_actions()
        self._update_departure_actions()
        self._update_in_house_actions()

    def _update_arrival_actions(self) -> None:
        from app.ui.dialogs.folio_dialog import set_action_state

        row = self._arrivals_table.selected_row()
        can_check_in = self.ui.can(Perm.FRONTDESK_CHECKIN)

        if row is None:
            self._arrivals_badge.set_status("Satir secilmedi", "info")
            enabled, tooltip = False, "Once giris yapilacak rezervasyonu secin."
        elif row.checked_in:
            self._arrivals_badge.set_status("Giris yapildi", "success")
            enabled, tooltip = False, "Bu rezervasyon icin giris zaten yapilmis."
        else:
            self._arrivals_badge.set_status(row.status_text, "warning")
            enabled = can_check_in
            tooltip = (
                "Giris ekranini acar."
                if can_check_in
                else "Bu islem icin 'Giris islemi' yetkisi gerekiyor."
            )
        set_action_state(self._check_in_button, enabled=enabled, tooltip=tooltip)

    def _update_departure_actions(self) -> None:
        from app.ui.dialogs.folio_dialog import set_action_state

        row = self._departures_table.selected_row()
        can_check_out = self.ui.can(Perm.FRONTDESK_CHECKOUT)

        if row is None:
            self._departures_badge.set_status("Satir secilmedi", "info")
            enabled, tooltip = False, "Once cikis yapilacak konaklamayi secin."
        elif row.checked_out:
            self._departures_badge.set_status("Cikis yapildi", "success")
            enabled, tooltip = False, "Bu konaklama icin cikis zaten yapilmis."
        elif not row.checked_in:
            self._departures_badge.set_status("Giris yapilmadi", "warning")
            enabled = False
            tooltip = (
                "Bu oda satiri icin giris yapilmamis; once 'Bugunku Girisler' sekmesini kullanin."
            )
        else:
            if row.has_open_balance:
                self._departures_badge.set_status(f"Acik bakiye: {row.balance.format()}", "warning")
            else:
                self._departures_badge.set_status("Hesap kapali", "success")
            enabled = can_check_out
            tooltip = (
                "Cikis ekranini acar."
                if can_check_out
                else "Bu islem icin 'Cikis islemi' yetkisi gerekiyor."
            )
        set_action_state(self._check_out_button, enabled=enabled, tooltip=tooltip)

    def _update_in_house_actions(self) -> None:
        from app.ui.dialogs.folio_dialog import set_action_state

        row = self._in_house_table.selected_row()
        can_view = self.ui.can(Perm.FOLIO_VIEW)

        if row is None:
            self._in_house_badge.set_status("Satir secilmedi", "info")
            set_action_state(
                self._folio_button,
                enabled=False,
                tooltip="Once folyosu acilacak konaklamayi secin.",
            )
            return

        if row.has_open_balance:
            self._in_house_badge.set_status(f"Acik bakiye: {row.balance.format()}", "warning")
        elif row.folio_id is None:
            self._in_house_badge.set_status("Folyo yok", "info")
        else:
            self._in_house_badge.set_status("Hesap kapali", "success")

        if not can_view:
            enabled, tooltip = False, "Bu islem icin 'Folyo goruntuleme' yetkisi gerekiyor."
        elif row.folio_id is None:
            enabled = False
            tooltip = "Bu konaklama icin acik folyo yok; folyo giris yapildiginda acilir."
        else:
            enabled, tooltip = True, "Ucret, odeme ve bakiye dokumunu acar."
        set_action_state(self._folio_button, enabled=enabled, tooltip=tooltip)

    # ----------------------------------------------------------------- #
    #  Eylemler
    # ----------------------------------------------------------------- #
    def _on_check_in(self) -> None:
        row = self._arrivals_table.selected_row()
        if row is None or row.checked_in or not self.ui.can(Perm.FRONTDESK_CHECKIN):
            return

        from app.ui.dialogs.checkin_dialog import CheckinDialog

        dialog = CheckinDialog(self.ui, row.reservation_room_id, self)
        if dialog.exec():
            show_toast(self, f"{row.guest_name} icin giris yapildi.", ToastLevel.SUCCESS)
            self.refresh(force=True)

    def _on_check_out(self) -> None:
        row = self._departures_table.selected_row()
        if row is None or row.stay_id is None or row.checked_out:
            return
        if not self.ui.can(Perm.FRONTDESK_CHECKOUT):
            return

        from app.ui.dialogs.checkout_dialog import CheckoutDialog

        dialog = CheckoutDialog(self.ui, row.stay_id, self)
        accepted = dialog.exec()
        if accepted:
            show_toast(self, f"{row.guest_name} icin cikis yapildi.", ToastLevel.SUCCESS)
        if accepted or dialog.changed:
            self.refresh(force=True)

    def _on_open_folio(self) -> None:
        row = self._in_house_table.selected_row()
        if row is None or row.folio_id is None or not self.ui.can(Perm.FOLIO_VIEW):
            return

        from app.ui.dialogs.folio_dialog import FolioDialog

        dialog = FolioDialog(self.ui, row.folio_id, self)
        dialog.exec()
        if dialog.changed:
            self.refresh(force=True)


__all__ = ["ArrivalRow", "FrontdeskPage", "FrontdeskSnapshot", "StayRow"]
