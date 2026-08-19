"""Raporlar ekrani.

Ekran :mod:`app.reporting` motorunun onune ince bir arayuz koyar: rapor
turunu ve tarih araligini secer, motorun urettigi
:class:`~app.reporting.models.ReportTable` nesnesini gosterir ve ayni nesneyi
CSV/Excel/PDF ihracatcilarina verir. Rapor mantigi burada **tekrarlanmaz**;
tek dogruluk kaynagi :mod:`app.reporting.queries`'tir.

Tarih araligi semantigi
-----------------------
Rapor motoru **[baslangic, bitis)** yari acik araligi kullanir (cikis gunu
dahil degildir). Kullanicilar ise "1-31 Agustos" derken 31'i de kastederler.
Bu yuzden ekranda **bitis tarihi dahildir** ve motora verilirken bir gun
eklenir (:meth:`ReportsPage._selected_range`). Bu donusum tek bir yerde
yapilir; aksi halde her rapor turunde bir gunluk kayma hatasi olusurdu.

Yetki
-----
Mali raporlar (gelir, gun sonu, KPI) :data:`Perm.REPORT_FINANCIAL` ister ve
bu yetkisi olmayan kullanicinin **listesinde hic gorunmez**: gorunup de
tiklaninca hata veren bir secenek, kullaniciya yalnizca engellendigini
hatirlatir. ADR/RevPAR gibi mali gostergeler de ayni yetkiye baglidir ve
yetkisiz kullaniciya ``-`` gosterilir.

Disa aktarma :data:`Perm.REPORT_EXPORT` ister; yetki yoksa dugmeler pasiftir.
Arayuz tek savunma degildir - dosya yolu
:func:`app.reporting.models.resolve_export_path` ile disa aktarma klasorune
kilitlenir ve islem denetim gunlugune yazilir.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.application.context import ServiceContext
from app.core.exceptions import HotelError, ValidationError
from app.core.log import get_logger
from app.domain.enums import AuditAction
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import utcnow
from app.reporting import queries
from app.reporting.models import KPISet, ReportTable, format_cell
from app.security.permissions import Perm
from app.ui.formatting import format_date, format_number, format_percent
from app.ui.pages.base import BasePage
from app.ui.widgets.common import (
    Card,
    EmptyState,
    KpiCard,
    SearchBox,
    SectionTitle,
    ToastLevel,
    show_error,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)


class ReportScope(str, Enum):
    """Rapor turunun tarih ihtiyaci."""

    RANGE = "range"
    """Tarih araligi ister (doluluk, gelir, teknik servis)."""

    DAY = "day"
    """Tek gun ister; baslangic tarihi kullanilir (gun sonu, giris-cikis)."""

    NONE = "none"
    """Tarihten bagimsizdir (anlik stok durumu)."""


@dataclass(frozen=True, slots=True)
class ReportKind:
    """Sol listedeki bir rapor turunun tanimi.

    ``builder`` oturum ve tesis kimligini alip bir :class:`ReportTable`
    uretir. Tarih parametreleri ``scope``'a gore doldurulur; boylece ekran
    her rapor icin ayri bir dal yazmak zorunda kalmaz.
    """

    key: str
    title: str
    scope: ReportScope
    builder: Callable[..., ReportTable]
    financial: bool = False
    hint: str = ""


def _kpi_table(session, property_id: int, date_range: DateRange) -> ReportTable:
    """KPI kumesini rapor tablosuna cevirir (ihracatcilar tablo bekler).

    ``KPISet.to_table()`` donemi motorun **yari acik** araligiyla yazar
    ("01.08.2026 - 16.08.2026"); ekranin basligi ise kullanicinin sectigi
    **dahil edici** araligi ("1 Agustos 2026 - 15 Agustos 2026") gosterir.
    Ayni ekranda iki farkli bitis tarihi gormek kullaniciyi raporun bir gun
    fazlasini kapsadigina inandirir. Bu yuzden "Donem" satiri da dahil edici
    metinle yeniden yazilir. Rapor motoru degistirilmez - duzeltme yalnizca
    sunum katmanindadir ve disa aktarilan dosyaya da ayni metin gider.
    """
    table = queries.kpi_report(session, property_id, date_range).to_table()
    period = format_period(date_range)
    table.filters_description = period
    for row in table.rows:
        if row.get("gosterge") == "Donem":
            row["deger"] = period
    return table


#: Ekrandaki tum rapor turleri (menu sirasiyla).
REPORT_KINDS: tuple[ReportKind, ...] = (
    ReportKind(
        key="doluluk",
        title="Doluluk",
        scope=ReportScope.RANGE,
        builder=queries.occupancy_report,
        hint="Gun bazinda toplam, arizali, satilabilir ve dolu oda sayilari.",
    ),
    ReportKind(
        key="gelir-kanal",
        title="Gelir (Kanal)",
        scope=ReportScope.RANGE,
        builder=queries.revenue_by_channel,
        financial=True,
        hint="Rezervasyon kanalina gore net, vergi ve toplam gelir.",
    ),
    ReportKind(
        key="gelir-oda-tipi",
        title="Gelir (Oda Tipi)",
        scope=ReportScope.RANGE,
        builder=queries.revenue_by_room_type,
        financial=True,
        hint="Oda tipine gore oda geliri ve diger gelir dagilimi.",
    ),
    ReportKind(
        key="gun-sonu",
        title="Gun Sonu Kapanis",
        scope=ReportScope.DAY,
        builder=queries.daily_closing_report,
        financial=True,
        hint="Secilen gunun geliri, tahsilati ve kasa hareketleri.",
    ),
    ReportKind(
        key="giris-cikis",
        title="Giris - Cikis",
        scope=ReportScope.DAY,
        builder=queries.arrivals_departures_report,
        hint="Secilen gunun giris, cikis ve devam eden konaklamalari.",
    ),
    ReportKind(
        key="kat-hizmetleri",
        title="Kat Hizmetleri",
        scope=ReportScope.DAY,
        builder=queries.housekeeping_report,
        hint="Secilen gunun temizlik gorevleri ve kontrol sonuclari.",
    ),
    ReportKind(
        key="teknik-servis",
        title="Teknik Servis",
        scope=ReportScope.RANGE,
        builder=queries.maintenance_report,
        hint="Donem icinde bildirilen ariza ve bakim kayitlari.",
    ),
    ReportKind(
        key="stok",
        title="Stok",
        scope=ReportScope.NONE,
        builder=queries.stock_report,
        hint="Anlik stok durumu; kritik seviyedeki kalemler en ustte.",
    ),
    ReportKind(
        key="kpi",
        title="KPI Ozeti",
        scope=ReportScope.RANGE,
        builder=_kpi_table,
        financial=True,
        hint="Donemin doluluk, ADR, RevPAR, ALOS ve iptal gostergeleri.",
    ),
)

#: Hazir tarih araliklari: etiket -> (baslangic, bitis) ureten fonksiyon.
#: Bitis tarihi **dahildir** (ekran semantigi).
QUICK_RANGES: tuple[tuple[str, Callable[[date], tuple[date, date]]], ...] = (
    ("Bugun", lambda today: (today, today)),
    ("Son 7 Gun", lambda today: (today - timedelta(days=6), today)),
    ("Bu Ay", lambda today: (today.replace(day=1), today)),
    (
        "Gecen Ay",
        lambda today: (
            (today.replace(day=1) - timedelta(days=1)).replace(day=1),
            today.replace(day=1) - timedelta(days=1),
        ),
    ),
    ("Son 90 Gun", lambda today: (today - timedelta(days=89), today)),
)

#: Disa aktarma dugmeleri: etiket -> bicim adi.
EXPORT_FORMATS: tuple[tuple[str, str], ...] = (("PDF", "pdf"), ("Excel", "xlsx"), ("CSV", "csv"))

#: Bir sutunun daralabilecegi asgari genislik (piksel).
#: Qt'nin varsayilan alt siniri cok kucuktur; iki karakterlik sutunlar
#: tabloyu okunmaz hale getiriyordu.
MIN_COLUMN_WIDTH: int = 80

#: Esnetilecek sutunu secerken taranan azami satir sayisi.
#: Binlerce satirli bir raporda her hucreyi olcmek ekrani gereksiz yavaslatir;
#: ilk satirlar sutun genisligi icin yeterli temsilcidir.
STRETCH_SAMPLE_ROWS: int = 200

#: Sayisal sutunlarin hizalama esleme tablosu.
_ALIGNMENTS: dict[str, Qt.AlignmentFlag] = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
}


class ReportsPage(BasePage):
    """Rapor uretme, goruntuleme ve disa aktarma ekrani."""

    required_permission = Perm.REPORT_VIEW
    title = "Raporlar"
    icon = "\U0001f4c8"

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._kinds: list[ReportKind] = []
        self._table: ReportTable | None = None
        self._table_view: FilterableTableView | None = None
        self._last_export_dir: Path | None = None

        self._build_header()
        self._build_body()
        self._build_footer()

    def _build_header(self) -> None:
        header = QHBoxLayout()
        header.addWidget(SectionTitle(self.title))
        header.addSpacing(16)

        self._quick_combo = QComboBox()
        self._quick_combo.addItem("Ozel aralik", userData=None)
        for label, _factory in QUICK_RANGES:
            self._quick_combo.addItem(label, userData=label)
        self._quick_combo.setToolTip("Hazir tarih araligi secin.")
        self._quick_combo.currentIndexChanged.connect(self._on_quick_range)

        self._start_edit = self._make_date_edit("Baslangic tarihi")
        self._end_edit = self._make_date_edit("Bitis tarihi (dahil)")

        self._generate_button = QPushButton("Raporu Olustur")
        self._generate_button.setObjectName("Primary")
        self._generate_button.clicked.connect(self._on_generate_clicked)

        self._end_label = QLabel("Bitis")

        header.addWidget(self._quick_combo)
        header.addWidget(QLabel("Baslangic"))
        header.addWidget(self._start_edit)
        header.addWidget(self._end_label)
        header.addWidget(self._end_edit)
        header.addStretch(1)
        header.addWidget(self._generate_button)
        self.root_layout.addLayout(header)

    def _make_date_edit(self, tooltip: str) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        # Yerel bicimi isletim sistemine birakmak, ayni ekranda iki farkli
        # tarih gosterimi uretebiliyor; bicim acikca sabitlenir.
        edit.setDisplayFormat("dd.MM.yyyy")
        edit.setToolTip(tooltip)
        edit.setMinimumWidth(120)
        return edit

    def _build_body(self) -> None:
        body = QHBoxLayout()
        body.setSpacing(14)

        # --- Sol: rapor turleri ---
        list_card = Card("Rapor Turu", self)
        self._kind_list = QListWidget()
        # Sol gezinme listesiyle ayni gorunumu paylasir: secili satir dolgulu
        # ve belirgin olur. Varsayilan QListWidget seciminde koyu temada
        # yalnizca ince bir cerceve ciziliyor ve hangi raporun secili oldugu
        # ekrana bakinca anlasilmiyordu.
        self._kind_list.setObjectName("NavList")
        self._kind_list.setMinimumWidth(210)
        self._kind_list.setMaximumWidth(250)
        self._kind_list.currentRowChanged.connect(self._on_kind_changed)
        list_card.add_widget(self._kind_list)

        self._hint_label = QLabel()
        self._hint_label.setObjectName("Muted")
        self._hint_label.setWordWrap(True)
        list_card.add_widget(self._hint_label)
        body.addWidget(list_card, 0)

        # --- Sag: KPI kartlari + tablo ---
        right = QVBoxLayout()
        right.setSpacing(12)

        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(12)
        self._kpis: dict[str, KpiCard] = {
            "occupancy": KpiCard("Doluluk", "-"),
            "adr": KpiCard("ADR", "-"),
            "revpar": KpiCard("RevPAR", "-"),
            "alos": KpiCard("ALOS", "-"),
            "cancellation": KpiCard("Iptal Orani", "-"),
        }
        for index, card in enumerate(self._kpis.values()):
            kpi_grid.addWidget(card, 0, index)
        right.addLayout(kpi_grid)

        self._table_card = Card("Rapor", self)

        table_header = QHBoxLayout()
        self._table_title = QLabel("-")
        self._table_title.setObjectName("Muted")
        self._table_title.setWordWrap(True)
        self._search = SearchBox("Rapor icinde ara")
        self._search.setMaximumWidth(260)
        self._search.search_triggered.connect(self._on_search)
        table_header.addWidget(self._table_title, 1)
        table_header.addWidget(self._search, 0)
        self._table_card.add_layout(table_header)

        self._table_holder = QVBoxLayout()
        self._table_holder.setContentsMargins(0, 0, 0, 0)
        self._table_card.add_layout(self._table_holder)
        right.addWidget(self._table_card, 1)

        body.addLayout(right, 1)
        self.root_layout.addLayout(body, 1)

    def _build_footer(self) -> None:
        footer = QHBoxLayout()

        self._row_count_label = QLabel("-")
        self._row_count_label.setObjectName("Muted")
        footer.addWidget(self._row_count_label)
        footer.addStretch(1)

        can_export = self.ui.can(Perm.REPORT_EXPORT)
        footer.addWidget(QLabel("Disa aktar:"))
        self._export_buttons: list[QPushButton] = []
        for label, fmt in EXPORT_FORMATS:
            button = QPushButton(label)
            button.setEnabled(can_export)
            if not can_export:
                button.setToolTip("Rapor disa aktarma yetkiniz bulunmuyor.")
            button.clicked.connect(lambda _checked=False, f=fmt: self._on_export(f))
            footer.addWidget(button)
            self._export_buttons.append(button)

        self._open_folder_button = QPushButton("Klasoru Ac")
        self._open_folder_button.setEnabled(False)
        self._open_folder_button.setToolTip("Son olusturulan dosyanin klasorunu acar.")
        self._open_folder_button.clicked.connect(self._on_open_folder)
        footer.addWidget(self._open_folder_button)

        self.root_layout.addLayout(footer)

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        """Rapor listesini kurar ve varsayilan raporu uretir."""
        if not self._kinds:
            self._populate_kinds()
            self._apply_default_dates()
        self._generate()

    def _populate_kinds(self) -> None:
        """Kullanicinin yetkisine gore rapor turlerini listeler.

        Mali rapor yetkisi olmayan kullanici bu turleri **hic gormez**.
        """
        allow_financial = self.ui.can(Perm.REPORT_FINANCIAL)
        self._kinds = [k for k in REPORT_KINDS if allow_financial or not k.financial]

        self._kind_list.blockSignals(True)
        self._kind_list.clear()
        for kind in self._kinds:
            item = QListWidgetItem(kind.title)
            item.setToolTip(kind.hint)
            self._kind_list.addItem(item)
        if self._kinds:
            self._kind_list.setCurrentRow(0)
        self._kind_list.blockSignals(False)
        self._update_hint()

    def _apply_default_dates(self) -> None:
        """Varsayilan aralik: iceren ayin basindan bugune."""
        today = utcnow().date()
        self._set_dates(today.replace(day=1), today)

    def _set_dates(self, start: date, end: date) -> None:
        self._start_edit.setDate(QDate(start.year, start.month, start.day))
        self._end_edit.setDate(QDate(end.year, end.month, end.day))

    def _selected_kind(self) -> ReportKind | None:
        row = self._kind_list.currentRow()
        if 0 <= row < len(self._kinds):
            return self._kinds[row]
        return None

    def _selected_range(self) -> DateRange:
        """Ekrandaki (bitis **dahil**) araligi motorun yari acik araligina cevirir."""
        start = self._start_edit.date().toPython()
        end = self._end_edit.date().toPython()
        if end < start:
            raise ValidationError(
                "Bitiş tarihi başlangıçtan önce olamaz.",
                field="date_range",
                detail=f"start={start} end={end}",
            )
        return DateRange(start, end + timedelta(days=1))

    # ----------------------------------------------------------------- #
    #  Rapor uretimi
    # ----------------------------------------------------------------- #
    def _generate(self) -> None:
        """Secili rapor turunu uretip ekrana yansitir."""
        kind = self._selected_kind()
        if kind is None:
            self._show_empty("Goruntuleyebileceginiz bir rapor turu yok.")
            return

        date_range = self._report_range(kind)
        with self.ui.service_context(commit=False) as ctx:
            table = self._build_table(ctx, kind, date_range)
            kpis = queries.kpi_report(ctx.session, ctx.require_property(), date_range)

        if kind.scope is ReportScope.RANGE:
            # Motor donemi yari acik yazar ("01.08 - 16.08"); kullanici 15.08'i
            # secmisti ve raporun 16'sini de kapsadigini sanirdi. Ekranda ve
            # disa aktarilan dosyada AYNI, dahil edici metin gorunmelidir.
            table.filters_description = format_period(date_range)

        # ReportTable duz veri tasir (Money, date, enum); ORM nesnesi icermez,
        # bu yuzden oturum kapandiktan sonra guvenle kullanilabilir.
        self._table = table
        self._apply_kpis(kpis)
        self._render_table(table)

    def _report_range(self, kind: ReportKind) -> DateRange:
        """Rapor turune uygun donemi dondurur.

        Tek gunluk raporlarda bitis tarihi kullanilmaz ve alan pasiftir; bu
        durumda bitis alanindaki (belki eski, belki gecersiz) deger
        **hic okunmaz**. Aksi halde kullanici, kullanilmayan bir alan
        yuzunden "Bitis tarihi baslangictan once olamaz" hatasi alirdi.
        """
        if kind.scope is ReportScope.DAY:
            return DateRange.single_night(self._start_edit.date().toPython())
        return self._selected_range()

    def _build_table(
        self, ctx: ServiceContext, kind: ReportKind, date_range: DateRange
    ) -> ReportTable:
        """Rapor turune gore dogru sorguyu cagirir."""
        property_id = ctx.require_property()
        if kind.scope is ReportScope.RANGE:
            return kind.builder(ctx.session, property_id, date_range)
        if kind.scope is ReportScope.DAY:
            return kind.builder(ctx.session, property_id, date_range.start)
        return kind.builder(ctx.session, property_id)

    def _apply_kpis(self, kpis: KPISet) -> None:
        """KPI kartlarini doldurur; mali gostergeler yetkiye baglidir."""
        self._kpis["occupancy"].set_value(format_percent(kpis.occupancy_percent))
        self._kpis["occupancy"].set_delta(
            f"{format_number(kpis.room_nights_sold)} / "
            f"{format_number(kpis.available_room_nights)} oda gecesi",
            direction=0,
        )
        self._kpis["alos"].set_value(f"{format_number(kpis.alos, decimals=2)} gece")
        self._kpis["alos"].set_delta("Ortalama konaklama suresi", direction=0)
        self._kpis["cancellation"].set_value(format_percent(kpis.cancellation_rate * 100))
        self._kpis["cancellation"].set_delta(
            f"Gelmeme: {format_percent(kpis.no_show_rate * 100)}", direction=0
        )

        if self.ui.can(Perm.REPORT_FINANCIAL):
            self._kpis["adr"].set_value(kpis.adr.format())
            self._kpis["adr"].set_delta("Yalnizca oda geliri", direction=0)
            self._kpis["revpar"].set_value(kpis.revpar.format())
            self._kpis["revpar"].set_delta(f"Toplam: {kpis.total_revenue.format()}", direction=0)
        else:
            for key in ("adr", "revpar"):
                self._kpis[key].set_value("-")
                self._kpis[key].set_delta("Mali rapor yetkisi gerekli", direction=0)
                self._kpis[key].setToolTip(
                    "Bu gostergeyi gormek icin 'Mali raporlari goruntuleme' yetkisi gerekir."
                )

    def _render_table(self, table: ReportTable) -> None:
        """Rapor tablosunu ekrana cizer; bos raporda EmptyState gosterir."""
        self._clear_table_holder()
        self._table_view = None

        subtitle = " - ".join(part for part in (table.subtitle, table.filters_description) if part)
        self._table_title.setText(f"{table.title}  ({subtitle})" if subtitle else table.title)

        if table.is_empty:
            self._row_count_label.setText("0 satir")
            self._search.setEnabled(False)
            self._table_holder.addWidget(
                _expanding(
                    EmptyState(
                        "Bu kriterlerde kayit bulunamadi.",
                        hint="Tarih araligini genisletin veya baska bir rapor turu secin.",
                        parent=self,
                    )
                )
            )
            return

        self._search.setEnabled(True)
        view = FilterableTableView(_build_columns(table), parent=self)
        view.table.horizontalHeader().setMinimumSectionSize(MIN_COLUMN_WIDTH)
        view.set_rows(table.rows)
        view.setMinimumHeight(260)
        self._table_holder.addWidget(view)
        self._table_view = view
        self._update_row_count()

        # Esnetme olcum gerektirir; yerlesim oturduktan sonra uygulanir.
        index = _stretch_column_index(table)
        QTimer.singleShot(0, lambda: self._apply_stretch(view, index))

    def _apply_stretch(self, view: FilterableTableView, index: int | None) -> None:
        """Tabloya **yer kaliyorsa** bir sutunu esnetir; kalmiyorsa hicbirini.

        ``QHeaderView.ResizeMode.Stretch`` sutuna artan yeri verir; artan yer
        yoksa sutunu icerigin altina kadar **sikistirir**. Giris-Cikis
        raporunda esnetilen sutun 40 piksele dusuyor ve basligi "Tu..." diye
        kirpiliyordu; Stok raporunda "Kahve Cekirdegi" "Kahve ..." oluyordu.
        Bu yuzden esnetme, sutunlarin dogal genisligi olculdukten SONRA ve
        yalnizca tabloya sigiyorsa uygulanir. Sigmiyorsa tum sutunlar icerige
        gore boyutlanir ve yatay kaydirma cubugu cikar - kaydirmak, kirpilmis
        basliktan iyidir.

        Olcum, yerlesim oturmadan dogru sonuc vermez; bu yuzden olay
        dongusune birakilir. O arada kullanici baska bir rapor uretmis
        olabilecegi icin gorunumun hala guncel oldugu dogrulanir (aksi halde
        silinmis bir bilesene erisilir ve ``RuntimeError`` alinir).
        """
        if index is None or self._table_view is not view:
            return
        header = view.table.horizontalHeader()
        if header.length() >= view.table.viewport().width():
            return
        header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)

    def _clear_table_holder(self) -> None:
        """Onceki tabloyu/bos durumu kaldirir.

        ``setParent(None)`` zorunludur: ``takeAt`` bileseni yalnizca
        yerlesimden cikarir, ust bilesenin cocugu olarak kalir ve eski
        geometrisinde cizilmeye devam eder. ``deleteLater`` tek basina
        yetmez; olay dongusune donulene kadar islenmez.
        """
        while self._table_holder.count():
            item = self._table_holder.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _update_row_count(self) -> None:
        if self._table_view is None:
            self._row_count_label.setText("-")
            return
        visible = self._table_view.visible_count
        total = self._table_view.total_count
        if visible == total:
            self._row_count_label.setText(f"{format_number(total)} satir")
        else:
            self._row_count_label.setText(
                f"{format_number(visible)} / {format_number(total)} satir (suzuldu)"
            )

    def _show_empty(self, message: str) -> None:
        self._clear_table_holder()
        self._table_view = None
        self._table = None
        self._row_count_label.setText("-")
        self._table_holder.addWidget(_expanding(EmptyState(message, parent=self)))

    def _update_hint(self) -> None:
        kind = self._selected_kind()
        if kind is None:
            self._hint_label.setText("")
            return
        self._hint_label.setText(kind.hint)
        # Tek gun isteyen raporlarda bitis tarihi hic kullanilmaz; alan
        # **gizlenir**. Yalnizca pasiflestirmek yetmiyordu: stil sayfasinda
        # QDateEdit icin ayri bir "disabled" gorunumu yok, dolayisiyla pasif
        # alan aktif olandan ayirt edilemiyordu. Tarihten bagimsiz raporlarda
        # (stok) ise alanlar acik kalir; ustteki gostergeler donemi kullanir.
        single_day = kind.scope is ReportScope.DAY
        self._end_edit.setEnabled(not single_day)
        self._end_edit.setVisible(not single_day)
        self._end_label.setVisible(not single_day)
        if single_day:
            self._end_edit.setToolTip(
                "Bu rapor tek gunluktur; yalnizca baslangic tarihi kullanilir."
            )
        elif kind.scope is ReportScope.NONE:
            self._end_edit.setToolTip(
                "Bu rapor anlik durumu gosterir; tarihler yalnizca ustteki gostergeleri etkiler."
            )
        else:
            self._end_edit.setToolTip("Bitis tarihi (dahil)")

    # ----------------------------------------------------------------- #
    #  Olaylar
    # ----------------------------------------------------------------- #
    def _on_kind_changed(self, _row: int) -> None:
        self._update_hint()

    def _on_quick_range(self, index: int) -> None:
        label = self._quick_combo.itemData(index)
        if label is None:
            return
        today = utcnow().date()
        for name, factory in QUICK_RANGES:
            if name == label:
                start, end = factory(today)
                self._set_dates(start, end)
                break

    def _on_generate_clicked(self) -> None:
        try:
            self._generate()
        except HotelError as exc:
            show_error(self, exc)
        except Exception as exc:  # pragma: no cover - beklenmeyen sorgu hatasi
            log.error("rapor_uretilemedi", error=str(exc), exc_info=True)
            show_error(self, exc)

    def _on_search(self, text: str) -> None:
        if self._table_view is not None:
            self._table_view.set_query(text)
            self._update_row_count()

    def _on_export(self, fmt: str) -> None:
        """Raporu dosyaya yazar ve yolunu bildirir."""
        if self._table is None:
            show_toast(self, "Once bir rapor olusturun.", ToastLevel.WARNING)
            return
        if not self.ui.can(Perm.REPORT_EXPORT):
            show_toast(self, "Rapor disa aktarma yetkiniz bulunmuyor.", ToastLevel.WARNING)
            return

        table = self._table
        try:
            # Ihracatcilar reportlab/openpyxl yukler; bu maliyet yalnizca
            # gercekten disa aktarilirken odenir (bkz. app.reporting.__init__).
            from app.reporting.exporters import EXTENSIONS, get_exporter

            exporter = get_exporter(fmt)
            filename = self._export_filename(fmt, EXTENSIONS.get(fmt, f".{fmt}"))
            path = exporter(table, filename)

            with self.ui.service_context() as ctx:
                ctx.require(Perm.REPORT_EXPORT)
                ctx.audit(
                    AuditAction.EXPORT,
                    f"Rapor disa aktarildi: {table.title} ({fmt})",
                    entity_type="ReportTable",
                )
        except HotelError as exc:
            show_error(self, exc)
            return
        except OSError as exc:
            log.error("rapor_yazilamadi", error=str(exc), exc_info=True)
            show_error(self, exc)
            return

        self._last_export_dir = path.parent
        self._open_folder_button.setEnabled(True)
        self._open_folder_button.setToolTip(str(path.parent))
        show_toast(self, f"Rapor kaydedildi: {path}", ToastLevel.SUCCESS, duration_ms=6000)

    def _export_filename(self, fmt: str, extension: str) -> str:
        """Dosya adini uretir - yalnizca ASCII ve tarih damgasi.

        Turkce karakterli rapor basligini dosya adina koymak, farkli kod
        sayfalarinda okunamayan dosya adlari uretiyordu; bu yuzden ad rapor
        **anahtarindan** turetilir.
        """
        kind = self._selected_kind()
        key = kind.key if kind else "rapor"
        start = self._start_edit.date().toPython()
        end = self._end_edit.date().toPython()
        stamp = (
            start.strftime("%Y%m%d")
            if kind is not None and kind.scope is not ReportScope.RANGE
            else f"{start:%Y%m%d}-{end:%Y%m%d}"
        )
        return f"{key}-{stamp}{extension}"

    def _on_open_folder(self) -> None:
        if self._last_export_dir is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_export_dir)))


# --------------------------------------------------------------------------
#  Yerlesim yardimcilari
# --------------------------------------------------------------------------
def _expanding(widget: QWidget) -> QWidget:
    """Bileseni dikeyde bos alanin tamamini kaplayacak sekilde ayarlar.

    Bos durum bileseni varsayilan ``Preferred`` politikasiyla eklendiginde,
    kartin fazla yuksekligi baslik ve alt basliga da dagitiliyor; "RAPOR"
    yazisi kartin ortasina kayip ekran bozuk gorunuyordu. Tabloda ayni sorun
    yok cunku ``QTableView`` zaten genisleyen bir bilesendir.
    """
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    return widget


# --------------------------------------------------------------------------
#  Sutun donusumu
# --------------------------------------------------------------------------
def _build_columns(table: ReportTable) -> list[Column]:
    """Rapor sutunlarini tablo bileseninin sutunlarina cevirir.

    ``getter`` ham degeri dondurur, ``formatter`` gosterimi uretir. Ayrimin
    korunmasi onemlidir: siralama ham deger uzerinden yapilir, ``1.234,56 TL``
    metnini siralamak yanlis sonuc verirdi (bkz. app.ui.widgets.table.Column).

    Hicbir sutun burada esnetilmez: esnetme kararinin verilebilmesi icin
    sutunlarin dogal genisligi olculmelidir (bkz.
    :meth:`ReportsPage._apply_stretch`).
    """
    return [
        Column(
            key=column.key,
            title=column.title,
            getter=(lambda row, k=column.key: row.get(k)),
            formatter=(lambda value, c=column: format_cell(value, c)),
            align=_ALIGNMENTS.get(column.align, _ALIGNMENTS["left"]),
        )
        for column in table.columns
    ]


def _stretch_column_index(table: ReportTable) -> int | None:
    """Esnetilecek sutunun sira numarasi: **icerigi en uzun** metin sutunu.

    Once "ilk metin sutunu" esnetiliyordu ve bu yaniltici sonuc veriyordu:
    Gun Sonu raporunda "Grup" sutunu ("Ozet" / "Gelir") ekranin yarisini
    kaplarken asil bilgiyi tasiyan "Kalem" sutunu sikisiyor; Giris-Cikis
    raporunda ise dar "Tur" sutunu esnetildigi icin ona artan yer kalmiyor ve
    basligi kirpiliyordu. Icerigi en uzun sutunu secmek hem sagda bos alan
    birakmaz hem de en genis yeri en cok metne verir.

    Sayisal **ve saga hizali** sutunlar disarida birakilir: icerik sag kenara
    yapistigi icin esnetme yalnizca ortada anlamsiz bir bosluk acar. (KPI
    raporunda "Deger" sutunu metin bicimlidir ama saga hizalidir; esnetildiginde
    "Toplam Gelir" ile tutari arasinda ekranin yarisi kadar bosluk kaliyordu.)
    Hicbir aday sutun yoksa ``None`` doner ve hicbir sutun esnetilmez.
    """
    best_index: int | None = None
    best_width = -1
    for index, column in enumerate(table.columns):
        if column.is_numeric or column.align == "right":
            continue
        width = len(column.title)
        for row in table.rows[:STRETCH_SAMPLE_ROWS]:
            width = max(width, len(format_cell(row.get(column.key), column)))
        if width > best_width:
            best_width = width
            best_index = index
    return best_index


def format_period(date_range: DateRange) -> str:
    """Donemi kullaniciya gosterilecek bicimde yazar (bitis **dahil**).

    >>> from datetime import date
    >>> format_period(DateRange(date(2026, 8, 1), date(2026, 8, 16)))
    '1 Agustos 2026 - 15 Agustos 2026 (15 gece)'
    """
    last_day = date_range.end - timedelta(days=1)
    return f"{format_date(date_range.start)} - {format_date(last_day)} ({date_range.nights} gece)"


__all__ = [
    "EXPORT_FORMATS",
    "MIN_COLUMN_WIDTH",
    "REPORT_KINDS",
    "STRETCH_SAMPLE_ROWS",
    "ReportKind",
    "ReportScope",
    "ReportsPage",
    "format_period",
]
