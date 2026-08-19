"""Yonetim paneli ekrani."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.application.services.dashboard_service import (
    Alert,
    DashboardService,
    DashboardSnapshot,
)
from app.core.log import get_logger
from app.security.permissions import Perm
from app.ui.formatting import format_date
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.theme import active_palette
from app.ui.widgets.common import Card, EmptyState, KpiCard, SectionTitle
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)


class DashboardPage(BasePage):
    """Isletmenin gunluk durumunu tek ekranda gosterir."""

    required_permission = Perm.DASHBOARD_VIEW
    title = "Yonetim Paneli"
    icon = "\U0001f4ca"

    def build(self) -> None:
        # --- Baslik satiri ---
        header = QHBoxLayout()
        self._title_label = SectionTitle(t("dashboard.title"))
        self._date_label = QLabel()
        self._date_label.setObjectName("Muted")

        self._refresh_button = QPushButton(t("common.refresh"))
        self._refresh_button.clicked.connect(lambda: self.refresh(force=True))

        header.addWidget(self._title_label)
        header.addSpacing(12)
        header.addWidget(self._date_label)
        header.addStretch(1)
        header.addWidget(self._refresh_button)
        self.root_layout.addLayout(header)

        # --- Kaydirilabilir govde ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        self._body = QVBoxLayout(container)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(14)
        scroll.setWidget(container)
        self.root_layout.addWidget(scroll, 1)

        # --- KPI kartlari ---
        self._kpi_grid = QGridLayout()
        self._kpi_grid.setSpacing(12)

        self._kpis: dict[str, KpiCard] = {
            "occupancy": KpiCard(t("dashboard.occupancy"), "-"),
            "available": KpiCard(t("dashboard.available_rooms"), "-"),
            "arrivals": KpiCard(t("dashboard.arrivals"), "-"),
            "departures": KpiCard(t("dashboard.departures"), "-"),
            "in_house": KpiCard(t("dashboard.in_house"), "-"),
            "revenue": KpiCard(t("dashboard.revenue_today"), "-"),
            "adr": KpiCard(t("dashboard.adr"), "-"),
            "revpar": KpiCard(t("dashboard.revpar"), "-"),
        }
        for index, card in enumerate(self._kpis.values()):
            self._kpi_grid.addWidget(card, index // 4, index % 4)
        self._body.addLayout(self._kpi_grid)

        # --- Uyarilar ---
        self._alerts_card = Card(t("dashboard.alerts"), self)
        self._alerts_container = QVBoxLayout()
        self._alerts_container.setSpacing(6)
        self._alerts_card.add_layout(self._alerts_container)
        self._body.addWidget(self._alerts_card)

        # --- Operasyon durumu ---
        ops_row = QHBoxLayout()
        ops_row.setSpacing(12)

        self._ops_card = Card("Operasyon", self)
        self._ops_labels: dict[str, QLabel] = {}
        for key, label in (
            ("dirty", t("dashboard.dirty_rooms")),
            ("oos", t("dashboard.out_of_service")),
            ("housekeeping", t("dashboard.pending_tasks")),
            ("maintenance", "Acik Ariza"),
            ("stock", "Kritik Stok"),
        ):
            line = QHBoxLayout()
            name = QLabel(label)
            name.setObjectName("Muted")
            value = QLabel("-")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(name)
            line.addStretch(1)
            line.addWidget(value)
            self._ops_card.add_layout(line)
            self._ops_labels[key] = value

        # --- Doluluk grafigi ---
        self._chart_card = Card("14 Gunluk Doluluk Tahmini", self)
        self._chart_holder = QVBoxLayout()
        self._chart_card.add_layout(self._chart_holder)

        ops_row.addWidget(self._ops_card, 1)
        ops_row.addWidget(self._chart_card, 2)
        self._body.addLayout(ops_row)

        # --- Bugunku girisler ---
        self._arrivals_card = Card("Bugunku Girisler", self)
        self._arrivals_table = FilterableTableView(
            [
                Column("room", "Oda", getter=self._room_number, width=80),
                Column("guest", "Misafir", getter=self._guest_name, stretch=True),
                Column("nights", "Gece", getter=lambda r: r.nights, width=70),
                Column("status", "Durum", getter=self._arrival_status, width=130),
            ],
            parent=self,
        )
        self._arrivals_table.setMinimumHeight(180)
        self._arrivals_card.add_widget(self._arrivals_table)
        self._body.addWidget(self._arrivals_card)

        self._body.addStretch(1)

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        from app.infrastructure.db.repositories import ReservationRepository

        with self.ui.service_context(commit=False) as ctx:
            snapshot = DashboardService(ctx).get_snapshot()

            arrival_rows = ReservationRepository(ctx.session).arrivals_on(
                ctx.require_property(), snapshot.day
            )
            # Oturum kapanmadan gosterilecek alanlari duz veriye cevir.
            rows = [
                {
                    "room": row.room.number if row.room else "-",
                    "guest": (
                        row.reservation.primary_guest.full_name
                        if row.reservation and row.reservation.primary_guest
                        else "-"
                    ),
                    "nights": row.nights,
                    "checked_in": row.stay is not None,
                }
                for row in arrival_rows
            ]

        self._apply_snapshot(snapshot)
        self._arrivals_table.set_rows(rows)

    def _apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        # strftime("%B") isletim sistemi yerel ayarina baglidir ve Windows'ta
        # "August" dondurur; Turkce ay adi icin kendi bicimlendiricimizi
        # kullaniyoruz.
        self._date_label.setText(format_date(snapshot.day, with_day_name=True))

        self._kpis["occupancy"].set_value(f"%{snapshot.occupancy_percent:.0f}")
        self._kpis["occupancy"].set_delta(
            f"{snapshot.occupied_rooms}/{snapshot.sellable_rooms} oda", direction=0
        )
        self._kpis["available"].set_value(str(snapshot.available_rooms))
        self._kpis["arrivals"].set_value(str(snapshot.arrivals_count))
        if snapshot.pending_arrivals:
            self._kpis["arrivals"].set_delta(f"{snapshot.pending_arrivals} bekliyor", direction=-1)
        self._kpis["departures"].set_value(str(snapshot.departures_count))
        self._kpis["in_house"].set_value(str(snapshot.in_house_count))
        self._kpis["revenue"].set_value(snapshot.revenue_today.format())
        self._kpis["revenue"].set_delta(f"Hafta: {snapshot.revenue_week.format()}", direction=0)
        self._kpis["adr"].set_value(snapshot.adr.format())
        self._kpis["revpar"].set_value(snapshot.revpar.format())

        self._ops_labels["dirty"].setText(str(snapshot.dirty_rooms))
        self._ops_labels["oos"].setText(str(snapshot.out_of_service_rooms))
        self._ops_labels["housekeeping"].setText(str(snapshot.pending_housekeeping))
        self._ops_labels["maintenance"].setText(
            f"{snapshot.open_maintenance}"
            + (f" ({snapshot.urgent_maintenance} acil)" if snapshot.urgent_maintenance else "")
        )
        self._ops_labels["stock"].setText(str(snapshot.low_stock_items))

        self._render_alerts(snapshot.alerts)
        self._render_chart(snapshot.occupancy_forecast)

    def _render_alerts(self, alerts: list[Alert]) -> None:
        while self._alerts_container.count():
            item = self._alerts_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not alerts:
            ok = QLabel("Kritik uyari yok.")
            ok.setObjectName("Muted")
            self._alerts_container.addWidget(ok)
            return

        badge_names = {
            "danger": "BadgeDanger",
            "warning": "BadgeWarning",
            "info": "BadgeInfo",
        }
        # Isaretler dil bagimsiz semboller: Ingilizce bas harf ("D"/"W"/"I")
        # Turkce arayuzde hicbir sey ifade etmiyordu.
        markers = {"danger": "!", "warning": "!", "info": "i"}
        for alert in alerts:
            line = QHBoxLayout()
            marker = QLabel(markers.get(alert.level, "i"))
            marker.setObjectName(badge_names.get(alert.level, "BadgeInfo"))
            marker.setFixedWidth(26)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setToolTip(
                {"danger": "Acil", "warning": "Uyari", "info": "Bilgi"}.get(alert.level, "Bilgi")
            )

            text = QLabel(f"<b>{alert.title}</b>" + (f" — {alert.detail}" if alert.detail else ""))
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.RichText)

            line.addWidget(marker)
            line.addWidget(text, 1)

            holder = QWidget()
            holder.setLayout(line)
            self._alerts_container.addWidget(holder)

    def _render_chart(self, forecast: list[tuple[date, float]]) -> None:
        """Doluluk tahmini grafigini cizer.

        QtCharts kullanilamayan bir kurulumda (ozel PySide6 paketleri
        QtCharts icermeyebilir) grafik yerine metin tablosu gosterilir;
        ekran cokmez.
        """
        while self._chart_holder.count():
            item = self._chart_holder.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not forecast:
            self._chart_holder.addWidget(EmptyState("Tahmin verisi yok", parent=self))
            return

        try:
            from PySide6.QtCharts import (
                QBarCategoryAxis,
                QBarSeries,
                QBarSet,
                QChart,
                QChartView,
                QValueAxis,
            )
            from PySide6.QtGui import QColor, QPainter
        except ImportError:  # pragma: no cover - QtCharts olmayan kurulum
            log.warning("qtcharts_yok", detail="Grafik yerine metin gosteriliyor.")
            for day, percent in forecast[:7]:
                self._chart_holder.addWidget(QLabel(f"{day.strftime('%d.%m')}  —  %{percent:.0f}"))
            return

        # Grafik renkleri stil sayfasindan gelmez; uygulamaya EN SON uygulanan
        # paleti okuyoruz. Ayarlardaki temayi okumak yanlis olurdu: kullanici
        # calisma sirasinda temayi degistirdiginde grafik eski renkte kalirdi.
        palette = active_palette()

        bar_set = QBarSet("Doluluk %")
        bar_set.setColor(QColor(palette.primary))
        bar_set.setBorderColor(QColor(palette.primary))
        for _, percent in forecast:
            bar_set.append(percent)

        series = QBarSeries()
        series.append(bar_set)

        chart = QChart()
        chart.addSeries(series)
        chart.legend().setVisible(False)
        chart.setBackgroundBrush(QColor(palette.surface))
        chart.setPlotAreaBackgroundVisible(False)
        chart.setMargins(chart.margins().__class__(0, 0, 0, 0))

        axis_x = QBarCategoryAxis()
        # 14 sutunluk dar eksende "15 Agu" kirpiliyor ("15 A..."); sayisal
        # gun.ay bicimi hem sigar hem belirsizlik yaratmaz.
        axis_x.append([day.strftime("%d.%m") for day, _ in forecast])
        axis_x.setLabelsColor(QColor(palette.text_muted))
        axis_x.setGridLineVisible(False)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, 100)
        axis_y.setTickCount(5)
        axis_y.setLabelFormat("%d")
        axis_y.setLabelsColor(QColor(palette.text_muted))
        axis_y.setGridLineColor(QColor(palette.border))
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(200)
        self._chart_holder.addWidget(view)

    # ----------------------------------------------------------------- #
    #  Sutun yardimcilari
    # ----------------------------------------------------------------- #
    @staticmethod
    def _room_number(row: dict) -> str:
        return row.get("room", "-")

    @staticmethod
    def _guest_name(row: dict) -> str:
        return row.get("guest", "-")

    @staticmethod
    def _arrival_status(row: dict) -> str:
        return "Giris yapildi" if row.get("checked_in") else "Bekliyor"


__all__ = ["DashboardPage"]
