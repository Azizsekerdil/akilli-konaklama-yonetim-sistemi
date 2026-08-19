"""Arama, filtreleme ve siralama destekli tablo bilesenleri.

Neden ``QAbstractTableModel``?
------------------------------
``QTableWidget`` her hucre icin bir nesne olusturur; birkac bin satirda
bellek ve cizim maliyeti hizla artar. Model/gorunum ayrimi ile yalnizca
ekranda gorunen hucreler cizilir ve 50.000 satirlik bir rezervasyon listesi
bile akici kalir.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.domain.value_objects import Money


@dataclass(slots=True)
class Column:
    """Tablo sutunu tanimi.

    ``getter`` satir nesnesinden degeri cikarir; ``formatter`` onu gosterime
    cevirir. Ikisini ayirmak, **siralamanin ham deger uzerinden** yapilmasini
    saglar: "1.234,56 ₺" metnini siralamak yanlis sonuc verirdi.
    """

    key: str
    title: str
    getter: Callable[[Any], Any] | None = None
    formatter: Callable[[Any], str] | None = None
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    width: int | None = None
    stretch: bool = False
    color_getter: Callable[[Any], str | None] | None = None
    """Satira/hucreye renk verir (or. oda durumu). ``None`` ise varsayilan."""

    def value_of(self, row: Any) -> Any:
        if self.getter is not None:
            return self.getter(row)
        if isinstance(row, dict):
            return row.get(self.key)
        return getattr(row, self.key, None)

    def display(self, row: Any) -> str:
        value = self.value_of(row)
        if self.formatter is not None:
            return self.formatter(value)
        return default_format(value)


def default_format(value: Any) -> str:
    """Yaygin tipleri Turkce yerel bicimde gosterir."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Evet" if value else "Hayir"
    if isinstance(value, Money):
        return value.format()
    if isinstance(value, Decimal):
        raw = f"{value:,.2f}"
        return raw.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if hasattr(value, "label"):  # LabeledEnum
        return str(value.label)
    return str(value)


class SimpleTableModel(QAbstractTableModel):
    """Nesne listesini tabloya baglayan genel model."""

    def __init__(
        self,
        columns: Sequence[Column],
        rows: Sequence[Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[Any] = list(rows or [])

    # ---------------- Qt arayuzu ----------------
    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row_obj = self._rows[index.row()]
        column = self._columns[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return column.display(row_obj)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(column.align)

        if role == Qt.ItemDataRole.ForegroundRole and column.color_getter is not None:
            color = column.color_getter(row_obj)
            return QColor(color) if color else None

        # Siralama ve filtreleme HAM deger uzerinden yapilir.
        if role == Qt.ItemDataRole.UserRole:
            return _sortable(column.value_of(row_obj))

        if role == Qt.ItemDataRole.UserRole + 1:
            return row_obj

        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section].title
        return section + 1

    # ---------------- Veri yonetimi ----------------
    def set_rows(self, rows: Sequence[Any]) -> None:
        """Tum satirlari degistirir."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, proxy_or_source_row: int) -> Any | None:
        if 0 <= proxy_or_source_row < len(self._rows):
            return self._rows[proxy_or_source_row]
        return None

    @property
    def rows(self) -> list[Any]:
        return self._rows

    @property
    def columns(self) -> list[Column]:
        return self._columns


def _sortable(value: Any) -> Any:
    """Siralanabilir bir anahtara cevirir.

    ``None`` degerler her zaman **sona** gitmelidir; aksi halde bos hucreler
    listenin basini doldurur ve kullanici veriyi goremez.
    """
    if value is None:
        return ""
    if isinstance(value, Money):
        return value.amount
    if hasattr(value, "value"):  # enum
        return str(value.value)
    return value


class MultiColumnFilterProxy(QSortFilterProxyModel):
    """Tum sutunlarda metin arayan, ek suzgec destekli ara model."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._query = ""
        self._predicate: Callable[[Any], bool] | None = None

    def set_query(self, text: str) -> None:
        self._query = (text or "").strip().lower()
        self.invalidateFilter()

    def set_predicate(self, predicate: Callable[[Any], bool] | None) -> None:
        """Satir nesnesi uzerinde calisan ek suzgec (durum, tarih vb.)."""
        self._predicate = predicate
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return True

        if self._predicate is not None:
            index = model.index(source_row, 0, source_parent)
            row_obj = model.data(index, Qt.ItemDataRole.UserRole + 1)
            if row_obj is not None and not self._predicate(row_obj):
                return False

        if not self._query:
            return True

        # Turkce buyuk/kucuk harf: "I" ve "i" esleme sorununu onlemek icin
        # casefold kullaniyoruz.
        query = self._query.casefold()
        for column in range(model.columnCount()):
            index = model.index(source_row, column, source_parent)
            text = str(model.data(index, Qt.ItemDataRole.DisplayRole) or "")
            if query in text.casefold():
                return True
        return False


class FilterableTableView(QWidget):
    """Model + siralama + arama birlestiren hazir tablo bileseni."""

    row_activated = Signal(object)
    """Satira cift tiklandiginda satir nesnesini yayar."""

    selection_changed = Signal(object)

    def __init__(
        self,
        columns: Sequence[Column],
        *,
        rows: Sequence[Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.model = SimpleTableModel(columns, rows, self)
        self.proxy = MultiColumnFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setHighlightSections(False)

        header = self.table.horizontalHeader()
        for i, column in enumerate(columns):
            if column.stretch:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            elif column.width:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(i, column.width)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

        self.table.doubleClicked.connect(self._on_double_click)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    # ---------------- Genel arayuz ----------------
    def set_rows(self, rows: Sequence[Any]) -> None:
        self.model.set_rows(rows)

    def set_query(self, text: str) -> None:
        self.proxy.set_query(text)

    def set_predicate(self, predicate: Callable[[Any], bool] | None) -> None:
        self.proxy.set_predicate(predicate)

    def selected_row(self) -> Any | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self._row_from_proxy_index(indexes[0])

    def visible_rows(self) -> list[Any]:
        """Suzgecten gecen satirlari (gorunen sirayla) dondurur.

        Disa aktarma islemleri bunu kullanir: kullanici ekranda ne goruyorsa
        onu almalidir, tum veri kumesini degil.
        """
        result = []
        for proxy_row in range(self.proxy.rowCount()):
            index = self.proxy.index(proxy_row, 0)
            row_obj = self._row_from_proxy_index(index)
            if row_obj is not None:
                result.append(row_obj)
        return result

    @property
    def visible_count(self) -> int:
        return self.proxy.rowCount()

    @property
    def total_count(self) -> int:
        return self.model.rowCount()

    # ---------------- Ic ----------------
    def _row_from_proxy_index(self, index: QModelIndex) -> Any | None:
        source_index = self.proxy.mapToSource(index)
        return self.model.data(source_index, Qt.ItemDataRole.UserRole + 1)

    def _on_double_click(self, index: QModelIndex) -> None:
        row_obj = self._row_from_proxy_index(index)
        if row_obj is not None:
            self.row_activated.emit(row_obj)

    def _on_selection_changed(self, *_args) -> None:
        self.selection_changed.emit(self.selected_row())


__all__ = [
    "Column",
    "FilterableTableView",
    "MultiColumnFilterProxy",
    "SimpleTableModel",
    "default_format",
]
