"""Teknik servis ekrani: ariza kayitlari, atama ve cozum.

Siralama karari
---------------
Liste **oncelige gore** gelir (:attr:`~app.domain.enums.Priority.weight`),
alfabetik degil. Oncelik veritabaninda metindir; alfabetik sirada "critical"
en acil olmasina ragmen listenin ortasinda kalirdi. Tablo sutunu da ham
agirligi tasir, boylece kullanici basliga tikladiginda dogru sira olusur.

Varsayilan gorunum yalnizca **acik** kayitlardir. Kapatilmis kayitlar
operasyonel dikkat gerektirmez; gecmisi gormek isteyen kullanici durum
suzgecinden "Tumu" secer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from app.core.exceptions import HotelError
from app.core.log import get_logger
from app.domain.enums import MaintenanceStatus, Priority
from app.security.permissions import Perm
from app.ui.formatting import format_datetime, format_number
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.pages.rooms_page import operations_style
from app.ui.widgets.common import (
    Card,
    EmptyState,
    KpiCard,
    SearchBox,
    SectionTitle,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)

#: Kapanmis (uzerinde islem yapilamayan) kayit durumlari.
CLOSED_STATUSES: frozenset[str] = frozenset(
    {
        MaintenanceStatus.RESOLVED.value,
        MaintenanceStatus.CLOSED.value,
        MaintenanceStatus.CANCELLED.value,
    }
)


@dataclass(slots=True)
class TicketInfo:
    """Bir ariza kaydinin ekranda gosterilen bilgileri (ORM'den bagimsiz)."""

    ticket_id: int
    ticket_number: str
    room_label: str
    location: str | None
    category_label: str
    priority: str
    priority_label: str
    priority_weight: int
    status: str
    status_label: str
    title: str
    reported_at: datetime
    technician: str
    blocks_room: bool
    total_cost: Decimal

    @property
    def is_open(self) -> bool:
        return self.status not in CLOSED_STATUSES

    @property
    def summary(self) -> str:
        """Tabloda gosterilen baslik - konum ve bloke bilgisiyle birlikte.

        Ortak alan arizalarinda konum dar "Oda" sutununa sigmaz ("Lobi - ana
        asansor" -> "Lobi - ana..."); bilgi kaybolmasin diye genis Ariza
        sutununda gosterilir.
        """
        text = f"{self.location} - {self.title}" if self.location else self.title
        return f"{text} [SATISA KAPALI]" if self.blocks_room else text


class MaintenancePage(BasePage):
    """Ariza kayitlari ve teknik servis operasyonu."""

    required_permission = Perm.MAINTENANCE_VIEW
    title = "Teknik Servis"
    icon = "\U0001f527"

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._tickets: list[TicketInfo] = []
        self.setStyleSheet(operations_style())

        self.root_layout.addLayout(self._build_header())
        self.root_layout.addLayout(self._build_summary())
        self.root_layout.addLayout(self._build_filters())
        self.root_layout.addWidget(self._build_table_card(), 1)
        self.root_layout.addLayout(self._build_actions())

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.addWidget(SectionTitle(t("nav.maintenance")))
        header.addStretch(1)

        self._new_button = QPushButton("Yeni Ariza")
        self._new_button.setObjectName("Primary")
        self._new_button.clicked.connect(self._open_new_dialog)
        self._new_button.setEnabled(self.ui.can(Perm.MAINTENANCE_CREATE))
        if not self.ui.can(Perm.MAINTENANCE_CREATE):
            self._new_button.setToolTip("Ariza kaydi olusturma yetkiniz bulunmuyor.")
        header.addWidget(self._new_button)

        self._refresh_button = QPushButton(t("common.refresh"))
        self._refresh_button.clicked.connect(lambda: self.refresh(force=True))
        header.addWidget(self._refresh_button)
        return header

    def _build_summary(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self._kpis: dict[str, KpiCard] = {
            "open": KpiCard("Acik Kayit", "-"),
            "urgent": KpiCard("Acil / Kritik", "-"),
            "blocking": KpiCard("Satisa Kapali Oda", "-"),
            "cost": KpiCard("Toplam Maliyet", "-"),
        }
        for card in self._kpis.values():
            row.addWidget(card)
        return row

    def _build_filters(self) -> QHBoxLayout:
        filters = QHBoxLayout()
        filters.setSpacing(8)

        self._search = SearchBox("Kayit no, oda veya baslik ara")
        self._search.search_triggered.connect(lambda _text: self._apply_filters())
        filters.addWidget(self._search, 1)

        self._priority_filter = QComboBox()
        self._priority_filter.addItem("Tum oncelikler", None)
        for priority in sorted(Priority, key=lambda p: -p.weight):
            self._priority_filter.addItem(priority.label, priority.value)
        self._priority_filter.currentIndexChanged.connect(lambda _i: self._apply_filters())
        filters.addWidget(self._priority_filter)

        self._status_filter = QComboBox()
        self._status_filter.addItem("Yalnizca acik kayitlar", "open")
        self._status_filter.addItem("Tumu", None)
        for status in MaintenanceStatus:
            self._status_filter.addItem(status.label, status.value)
        self._status_filter.currentIndexChanged.connect(lambda _i: self._apply_filters())
        filters.addWidget(self._status_filter)
        return filters

    def _build_table_card(self) -> QWidget:
        self._card = Card("Ariza Kayitlari", self)

        self._table = FilterableTableView(
            [
                Column("ticket_number", "No", width=130),
                Column("room_label", t("room.number"), width=100),
                Column("category_label", "Kategori", width=120),
                Column(
                    "priority",
                    "Oncelik",
                    getter=lambda info: info.priority_weight,
                    formatter=lambda weight: _PRIORITY_TEXT.get(weight, "-"),
                    width=90,
                ),
                Column("status_label", "Durum", width=110),
                Column("summary", "Ariza", getter=lambda info: info.summary, stretch=True),
                Column(
                    "reported_at",
                    "Bildirim",
                    getter=lambda info: info.reported_at,
                    formatter=format_datetime,
                    width=140,
                ),
                Column("technician", "Teknisyen", width=160),
            ],
            parent=self,
        )
        # Varsayilan sira ONCELIGE gore azalandir - en acil kayit en ustte.
        # Sutun ham agirligi tasidigi icin siralama dogru calisir; etiket
        # uzerinden siralansaydi "Acil" alfabetik olarak "Kritik"ten once
        # gelir ve liste yaniltici olurdu.
        self._table.table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self._table.selection_changed.connect(lambda _row: self._update_action_state())
        self._card.add_widget(self._table)

        self._empty = EmptyState(
            "Kayit bulunamadi",
            hint="Suzgecleri genisletin veya 'Yeni Ariza' ile kayit acin.",
            parent=self,
        )
        self._empty.setVisible(False)
        self._card.add_widget(self._empty)

        self._count_label = QLabel("-")
        self._count_label.setObjectName("Muted")
        self._card.add_widget(self._count_label)
        return self._card

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(8)

        actions.addWidget(QLabel("Teknisyen:"))
        self._technician_combo = QComboBox()
        self._technician_combo.setMinimumWidth(220)
        actions.addWidget(self._technician_combo)

        self._assign_button = QPushButton("Ata")
        self._assign_button.clicked.connect(self._assign_selected)
        actions.addWidget(self._assign_button)

        actions.addStretch(1)

        self._resolve_button = QPushButton("Coz")
        self._resolve_button.setObjectName("Primary")
        self._resolve_button.clicked.connect(self._resolve_selected)
        actions.addWidget(self._resolve_button)

        self._close_button = QPushButton("Kaydi Kapat")
        self._close_button.clicked.connect(self._close_selected)
        actions.addWidget(self._close_button)
        return actions

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        from app.application.services.maintenance_service import MaintenanceService

        with self.ui.service_context(commit=False) as ctx:
            service = MaintenanceService(ctx)
            # ORM nesneleri oturum disinda kullanilamaz - duz veriye ceviriyoruz.
            tickets = [
                TicketInfo(
                    ticket_id=ticket.id,
                    ticket_number=ticket.ticket_number,
                    room_label=(ticket.room.number if ticket.room is not None else "Ortak alan"),
                    location=(ticket.location_description if ticket.room is None else None),
                    category_label=ticket.category.label,
                    priority=ticket.priority.value,
                    priority_label=ticket.priority.label,
                    priority_weight=ticket.priority.weight,
                    status=ticket.status.value,
                    status_label=ticket.status.label,
                    title=ticket.title,
                    reported_at=ticket.reported_at,
                    technician=(
                        ticket.assigned_employee.full_name
                        if ticket.assigned_employee is not None
                        else "Atanmadi"
                    ),
                    blocks_room=ticket.blocks_room and ticket.is_open,
                    total_cost=ticket.total_cost,
                )
                for ticket in service.all_tickets()
            ]
            technicians = [(employee.id, employee.full_name) for employee in service.technicians()]

        # Tema calisma sirasinda degistirilmis olabilir (bkz. operations_style).
        self.setStyleSheet(operations_style())
        self._tickets = tickets
        self._table.set_rows(tickets)
        self._reload_technicians(technicians)
        self._apply_filters()
        self._update_summary()
        self._update_action_state()

    def _reload_technicians(self, technicians: list[tuple[int, str]]) -> None:
        previous = self._technician_combo.currentData()
        self._technician_combo.blockSignals(True)
        self._technician_combo.clear()
        if technicians:
            for employee_id, name in technicians:
                self._technician_combo.addItem(name, employee_id)
            position = self._technician_combo.findData(previous)
            self._technician_combo.setCurrentIndex(position if position >= 0 else 0)
        else:
            self._technician_combo.addItem("Tanimli personel yok", None)
        self._technician_combo.blockSignals(False)

    def _apply_filters(self) -> None:
        priority = self._priority_filter.currentData()
        status = self._status_filter.currentData()

        def matches(info: TicketInfo) -> bool:
            if priority is not None and info.priority != priority:
                return False
            if status == "open":
                return info.is_open
            return not (status is not None and info.status != status)

        self._table.set_predicate(matches)
        self._table.set_query(self._search.text().strip())

        visible = self._table.visible_count
        self._table.setVisible(visible > 0)
        self._empty.setVisible(visible == 0)
        self._count_label.setText(f"{visible} / {len(self._tickets)} kayit gosteriliyor")

    def _update_summary(self) -> None:
        open_tickets = [info for info in self._tickets if info.is_open]
        urgent = sum(1 for info in open_tickets if info.priority_weight >= Priority.URGENT.weight)
        blocking = sum(1 for info in open_tickets if info.blocks_room)
        total_cost = sum((info.total_cost for info in self._tickets), start=Decimal("0.00"))

        # Dort kartin da alt satiri doldurulur; biri bos kalirsa o kart digerlerinden
        # kisa olur ve KPI seridi hizasini kaybeder.
        self._kpis["open"].set_value(str(len(open_tickets)))
        self._kpis["open"].set_delta(f"toplam {len(self._tickets)} kayit", direction=0)
        self._kpis["urgent"].set_value(str(urgent))
        self._kpis["urgent"].set_delta(
            "hemen mudahale" if urgent else "acil kayit yok",
            direction=-1 if urgent else 0,
        )
        self._kpis["blocking"].set_value(str(blocking))
        self._kpis["blocking"].set_delta(
            "satisa kapali oda var" if blocking else "tum odalar satista",
            direction=-1 if blocking else 0,
        )
        # Turkce bicim: binlik ayirici nokta, ondalik ayirici VIRGUL.
        # f"{x:,.2f}" Ingilizce bicim uretir ve tek basina replace(",", ".")
        # "10.352.75" gibi anlamsiz bir tutar yazar.
        self._kpis["cost"].set_value(f"{format_number(total_cost, decimals=2)} TL")
        self._kpis["cost"].set_delta("iscilik + parca", direction=0)

    # ----------------------------------------------------------------- #
    #  Dugme durumlari
    # ----------------------------------------------------------------- #
    def selected_ticket(self) -> TicketInfo | None:
        row = self._table.selected_row()
        return row if isinstance(row, TicketInfo) else None

    def _update_action_state(self) -> None:
        """Dugmeleri yetki ve kayit durumuna gore etkinlestirir."""
        info = self.selected_ticket()
        can_assign = self.ui.can(Perm.MAINTENANCE_ASSIGN)
        can_resolve = self.ui.can(Perm.MAINTENANCE_RESOLVE)
        has_technician = self._technician_combo.currentData() is not None

        self._assign_button.setEnabled(
            info is not None and info.is_open and can_assign and has_technician
        )
        self._resolve_button.setEnabled(info is not None and info.is_open and can_resolve)
        self._close_button.setEnabled(
            info is not None and info.status == MaintenanceStatus.RESOLVED.value and can_resolve
        )

        if not can_assign:
            self._assign_button.setToolTip("Teknisyen atama yetkiniz bulunmuyor.")
        if not can_resolve:
            self._resolve_button.setToolTip("Ariza cozme yetkiniz bulunmuyor.")
            self._close_button.setToolTip("Ariza kapatma yetkiniz bulunmuyor.")

    # ----------------------------------------------------------------- #
    #  Islemler
    # ----------------------------------------------------------------- #
    def _open_new_dialog(self) -> None:
        from app.ui.dialogs.maintenance_dialog import MaintenanceDialog

        dialog = MaintenanceDialog(self.ui, self)
        if dialog.exec():
            show_toast(self, "Ariza kaydi olusturuldu.", ToastLevel.SUCCESS)
            self.refresh(force=True)

    def _assign_selected(self) -> None:
        from app.application.services.maintenance_service import MaintenanceService

        info = self.selected_ticket()
        employee_id = self._technician_combo.currentData()
        if info is None or employee_id is None:
            return

        name = self._technician_combo.currentText()
        try:
            with self.ui.service_context() as ctx:
                MaintenanceService(ctx).assign(info.ticket_id, employee_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, f"{info.ticket_number} -> {name}", ToastLevel.SUCCESS)
        self.refresh(force=True)

    def _resolve_selected(self) -> None:
        from app.ui.dialogs.maintenance_dialog import ResolveMaintenanceDialog

        info = self.selected_ticket()
        if info is None:
            return

        dialog = ResolveMaintenanceDialog(
            self.ui,
            info.ticket_id,
            f"{info.ticket_number} - {info.title}",
            self,
        )
        if dialog.exec():
            message = f"{info.ticket_number} cozuldu."
            if info.blocks_room:
                message += " Oda temizlik icin acildi."
            show_toast(self, message, ToastLevel.SUCCESS)
            self.refresh(force=True)

    def _close_selected(self) -> None:
        from app.application.services.maintenance_service import MaintenanceService

        info = self.selected_ticket()
        if info is None:
            return
        if not confirm(
            self,
            f"{info.ticket_number} kaydi kapatilsin mi?",
            detail="Kapatilan kayit operasyon listesinden cikar; gecmiste gorunmeye devam eder.",
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                MaintenanceService(ctx).close(info.ticket_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, f"{info.ticket_number} kapatildi.", ToastLevel.SUCCESS)
        self.refresh(force=True)


#: Oncelik agirligindan gosterim metnine esleme (bkz. tablo sutunu aciklamasi).
_PRIORITY_TEXT: dict[int, str] = {1: "Dusuk", 2: "Normal", 3: "Yuksek", 4: "Acil", 5: "Kritik"}


__all__ = ["CLOSED_STATUSES", "MaintenancePage", "TicketInfo"]
