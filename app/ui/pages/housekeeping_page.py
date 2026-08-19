"""Kat hizmetleri ekrani: gunluk gorev listesi, atama ve kontrol.

Ekranin merkezinde **bir gun** vardir. Tarih secici degistirildiginde tum
liste o gune gore yeniden yuklenir; gecmis bir gunun performansi da ayni
ekrandan incelenebilir.

"Gunun Gorevlerini Olustur" dugmesi
-----------------------------------
:meth:`~app.application.services.housekeeping_service.HousekeepingService.generate_daily_tasks`
idempotenttir: dugmeye ikinci kez basmak gorev tekrarlamaz. Kullaniciya kac
gorev uretildigi bildirilir; "0 gorev uretildi" mesaji "zaten hazir" anlamina
gelir ve bu bilincli olarak gosterilir - sessiz kalmak kullaniciya dugmenin
calismadigini dusundururdu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from app.core.exceptions import HotelError
from app.core.log import get_logger
from app.domain.enums import HousekeepingStatus
from app.security.permissions import Perm
from app.ui.formatting import format_date
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.pages.rooms_page import operations_style
from app.ui.widgets.common import (
    Card,
    EmptyState,
    KpiCard,
    SectionTitle,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)

#: Uzerinde islem yapilabilecek (henuz kapanmamis) gorev durumlari.
OPEN_STATUSES: frozenset[str] = frozenset(
    {
        HousekeepingStatus.PENDING.value,
        HousekeepingStatus.ASSIGNED.value,
        HousekeepingStatus.IN_PROGRESS.value,
    }
)

#: Henuz baslatilmamis gorevler.
NOT_STARTED_STATUSES: frozenset[str] = frozenset(
    {HousekeepingStatus.PENDING.value, HousekeepingStatus.ASSIGNED.value}
)


@dataclass(slots=True)
class TaskInfo:
    """Bir kat hizmetleri gorevinin ekranda gosterilen bilgileri."""

    task_id: int
    room_number: str
    task_type_label: str
    priority_label: str
    priority_weight: int
    employee_name: str
    status: str
    status_label: str
    estimated_minutes: int
    actual_minutes: int | None
    issues: str | None

    @property
    def duration_text(self) -> str:
        """Fiili sure varsa onu, yoksa tahmini sureyi gosterir."""
        if self.actual_minutes is not None:
            return f"{self.actual_minutes} dk"
        return f"~{self.estimated_minutes} dk"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


class HousekeepingPage(BasePage):
    """Gunluk temizlik gorevleri."""

    required_permission = Perm.HOUSEKEEPING_VIEW
    title = "Kat Hizmetleri"
    icon = "\U0001f9f9"

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._tasks: list[TaskInfo] = []
        self.setStyleSheet(operations_style())

        self.root_layout.addLayout(self._build_header())
        self.root_layout.addLayout(self._build_summary())
        self.root_layout.addWidget(self._build_task_card(), 1)
        self.root_layout.addLayout(self._build_actions())

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.addWidget(SectionTitle(t("nav.housekeeping")))
        header.addSpacing(12)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("dd.MM.yyyy")
        # Varsayilan genislik "15.08.2026" metnini takvim okuyla birlikte
        # kirpiyordu; tarih yaziminin tamami gorunmelidir.
        self._date_edit.setMinimumWidth(140)
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.dateChanged.connect(lambda _date: self.refresh(force=True))
        header.addWidget(self._date_edit)

        self._day_label = QLabel("-")
        self._day_label.setObjectName("Muted")
        header.addWidget(self._day_label)
        header.addStretch(1)

        self._generate_button = QPushButton("Gunun Gorevlerini Olustur")
        self._generate_button.setObjectName("Primary")
        self._generate_button.clicked.connect(self._generate_tasks)
        self._generate_button.setEnabled(self.ui.can(Perm.HOUSEKEEPING_ASSIGN))
        if not self.ui.can(Perm.HOUSEKEEPING_ASSIGN):
            self._generate_button.setToolTip("Gorev olusturma yetkiniz bulunmuyor.")
        header.addWidget(self._generate_button)

        self._refresh_button = QPushButton(t("common.refresh"))
        self._refresh_button.clicked.connect(lambda: self.refresh(force=True))
        header.addWidget(self._refresh_button)
        return header

    def _build_summary(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(12)
        self._kpis: dict[str, KpiCard] = {
            "pending": KpiCard("Bekleyen", "-"),
            "in_progress": KpiCard("Devam Eden", "-"),
            "completed": KpiCard("Tamamlanan", "-"),
            "inspected": KpiCard("Kontrol Edilen", "-"),
        }
        for index, card in enumerate(self._kpis.values()):
            grid.addWidget(card, 0, index)
        return grid

    def _build_task_card(self) -> QWidget:
        self._task_card = Card("Gorevler", self)

        self._table = FilterableTableView(
            [
                Column("room_number", t("room.number"), width=90),
                Column("task_type_label", "Tur", width=170),
                Column(
                    "priority_label",
                    "Oncelik",
                    getter=lambda info: info.priority_weight,
                    formatter=lambda weight: _PRIORITY_TEXT.get(weight, "-"),
                    width=100,
                ),
                Column("employee_name", "Atanan", width=200),
                Column("status_label", "Durum", width=130),
                Column(
                    "duration",
                    "Sure",
                    getter=lambda info: info.duration_text,
                    width=90,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column(
                    "issues",
                    "Kontrolde Gorulen",
                    getter=lambda info: info.issues or "-",
                    stretch=True,
                ),
            ],
            parent=self,
        )
        # Varsayilan sira oda numarasina gore artan olmalidir; kat gorevlisi
        # listeyi kat kat yukaridan asagi calisir. Qt'nin varsayilani ilk
        # sutunda AZALAN gosterir ve liste tersten baslardi.
        self._table.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._table.selection_changed.connect(lambda _row: self._update_action_state())
        self._task_card.add_widget(self._table)

        self._empty = EmptyState(
            "Bu gun icin gorev yok",
            hint="'Gunun Gorevlerini Olustur' dugmesi cikis ve konaklama odalarina gorev acar.",
            parent=self,
        )
        self._empty.setVisible(False)
        self._task_card.add_widget(self._empty)
        return self._task_card

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._employee_combo = QComboBox()
        self._employee_combo.setMinimumWidth(220)
        actions.addWidget(QLabel("Kat gorevlisi:"))
        actions.addWidget(self._employee_combo)

        self._assign_button = QPushButton("Ata")
        self._assign_button.clicked.connect(self._assign_selected)
        actions.addWidget(self._assign_button)

        actions.addStretch(1)

        self._start_button = QPushButton("Basla")
        self._start_button.clicked.connect(self._start_selected)
        actions.addWidget(self._start_button)

        self._complete_button = QPushButton("Tamamla")
        self._complete_button.setObjectName("Primary")
        self._complete_button.clicked.connect(self._complete_selected)
        actions.addWidget(self._complete_button)

        self._inspect_button = QPushButton("Kontrol Et")
        self._inspect_button.clicked.connect(self._inspect_selected)
        actions.addWidget(self._inspect_button)
        return actions

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def selected_day(self) -> date:
        """Ekranda secili gun."""
        return self._date_edit.date().toPython()

    def load_data(self) -> None:
        from app.application.services.housekeeping_service import HousekeepingService

        day = self.selected_day()

        with self.ui.service_context(commit=False) as ctx:
            service = HousekeepingService(ctx)
            # ORM nesneleri blok disinda kullanilamaz; burada duz veriye ceviriyoruz.
            tasks = [
                TaskInfo(
                    task_id=task.id,
                    room_number=task.room.number if task.room else "-",
                    task_type_label=task.task_type.label,
                    priority_label=task.priority.label,
                    priority_weight=task.priority.weight,
                    employee_name=(
                        task.assigned_employee.full_name
                        if task.assigned_employee is not None
                        else "Atanmadi"
                    ),
                    status=task.status.value,
                    status_label=task.status.label,
                    estimated_minutes=task.estimated_minutes,
                    actual_minutes=task.actual_minutes,
                    issues=task.issues_found,
                )
                for task in service.daily_tasks(day=day)
            ]
            staff = [(employee.id, employee.full_name) for employee in service.staff()]

        # Tema calisma sirasinda degistirilmis olabilir (bkz. operations_style).
        self.setStyleSheet(operations_style())
        self._tasks = tasks
        self._day_label.setText(format_date(day, with_day_name=True))
        self._table.set_rows(tasks)
        self._table.setVisible(bool(tasks))
        self._empty.setVisible(not tasks)
        self._reload_staff(staff)
        self._update_summary()
        self._update_action_state()

    def _reload_staff(self, staff: list[tuple[int, str]]) -> None:
        """Personel listesini secimi koruyarak yeniler."""
        previous = self._employee_combo.currentData()
        self._employee_combo.blockSignals(True)
        self._employee_combo.clear()
        if staff:
            for employee_id, name in staff:
                self._employee_combo.addItem(name, employee_id)
            position = self._employee_combo.findData(previous)
            self._employee_combo.setCurrentIndex(position if position >= 0 else 0)
        else:
            self._employee_combo.addItem("Tanimli personel yok", None)
        self._employee_combo.blockSignals(False)

    def _update_summary(self) -> None:
        counts = {
            "pending": sum(1 for task in self._tasks if task.status in NOT_STARTED_STATUSES),
            "in_progress": sum(
                1 for task in self._tasks if task.status == HousekeepingStatus.IN_PROGRESS.value
            ),
            "completed": sum(
                1 for task in self._tasks if task.status == HousekeepingStatus.COMPLETED.value
            ),
            "inspected": sum(
                1 for task in self._tasks if task.status == HousekeepingStatus.INSPECTED.value
            ),
        }
        for key, card in self._kpis.items():
            card.set_value(str(counts[key]))

    # ----------------------------------------------------------------- #
    #  Dugme durumlari
    # ----------------------------------------------------------------- #
    def selected_task(self) -> TaskInfo | None:
        row = self._table.selected_row()
        return row if isinstance(row, TaskInfo) else None

    def _update_action_state(self) -> None:
        """Dugmeleri hem **yetkiye** hem gorev durumuna gore etkinlestirir.

        Arayuz tek savunma hatti degildir - servis katmani ayni yetkileri
        yeniden kontrol eder. Buradaki amac kullaniciya yapamayacagi bir
        islemi denetip hata almasini yasatmamaktir.
        """
        task = self.selected_task()
        can_assign = self.ui.can(Perm.HOUSEKEEPING_ASSIGN)
        can_complete = self.ui.can(Perm.HOUSEKEEPING_COMPLETE)
        can_inspect = self.ui.can(Perm.HOUSEKEEPING_INSPECT)

        has_staff = self._employee_combo.currentData() is not None
        self._assign_button.setEnabled(
            task is not None and task.is_open and can_assign and has_staff
        )
        self._start_button.setEnabled(
            task is not None and task.status in NOT_STARTED_STATUSES and can_complete
        )
        self._complete_button.setEnabled(task is not None and task.is_open and can_complete)
        self._inspect_button.setEnabled(
            task is not None and task.status == HousekeepingStatus.COMPLETED.value and can_inspect
        )

        for button, allowed, permission in (
            (self._assign_button, can_assign, "Gorev atama"),
            (self._start_button, can_complete, "Gorev tamamlama"),
            (self._complete_button, can_complete, "Gorev tamamlama"),
            (self._inspect_button, can_inspect, "Temizlik kontrolu"),
        ):
            if not allowed:
                button.setToolTip(f"{permission} yetkiniz bulunmuyor.")

    # ----------------------------------------------------------------- #
    #  Islemler
    # ----------------------------------------------------------------- #
    def _generate_tasks(self) -> None:
        from app.application.services.housekeeping_service import HousekeepingService

        day = self.selected_day()
        try:
            with self.ui.service_context() as ctx:
                created = len(HousekeepingService(ctx).generate_daily_tasks(day))
        except HotelError as exc:
            show_error(self, exc)
            return

        if created:
            show_toast(self, f"{created} gorev olusturuldu.", ToastLevel.SUCCESS)
        else:
            # Sessiz kalmak "dugme calismadi" izlenimi verirdi.
            show_toast(
                self,
                "Yeni gorev uretilmedi - bu gunun gorevleri zaten hazir.",
                ToastLevel.INFO,
            )
        self.refresh(force=True)

    def _assign_selected(self) -> None:
        from app.application.services.housekeeping_service import HousekeepingService

        task = self.selected_task()
        employee_id = self._employee_combo.currentData()
        if task is None or employee_id is None:
            return

        name = self._employee_combo.currentText()
        try:
            with self.ui.service_context() as ctx:
                HousekeepingService(ctx).assign(task.task_id, employee_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, f"{task.room_number} -> {name}", ToastLevel.SUCCESS)
        self.refresh(force=True)

    def _start_selected(self) -> None:
        from app.application.services.housekeeping_service import HousekeepingService

        task = self.selected_task()
        if task is None:
            return
        try:
            with self.ui.service_context() as ctx:
                HousekeepingService(ctx).start(task.task_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, f"{task.room_number} temizligi basladi.", ToastLevel.INFO)
        self.refresh(force=True)

    def _complete_selected(self) -> None:
        from app.application.services.housekeeping_service import HousekeepingService

        task = self.selected_task()
        if task is None:
            return

        minutes, accepted = QInputDialog.getInt(
            self,
            "Temizlik Suresi",
            f"{task.room_number} numarali oda kac dakikada temizlendi?",
            task.actual_minutes or task.estimated_minutes,
            0,
            600,
        )
        if not accepted:
            return

        try:
            with self.ui.service_context() as ctx:
                HousekeepingService(ctx).complete(task.task_id, actual_minutes=minutes)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, f"{task.room_number} temizligi tamamlandi.", ToastLevel.SUCCESS)
        self.refresh(force=True)

    def _inspect_selected(self) -> None:
        """Temizlik kontrolu - gecti / kaldi / vazgec.

        "Kaldi" secildiginde oda kirliye doner ve gorev yeniden acilir; bu
        yikici sonuc kullaniciya onay kutusunda acikca yazilir.
        """
        from app.application.services.housekeeping_service import HousekeepingService

        task = self.selected_task()
        if task is None:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Temizlik Kontrolu")
        box.setText(f"{task.room_number} numarali odanin temizligi uygun mu?")
        box.setInformativeText(
            "'Kaldi' secilirse oda yeniden kirli isaretlenir ve gorev tekrar acilir."
        )
        passed_button = box.addButton("Gecti", QMessageBox.ButtonRole.AcceptRole)
        failed_button = box.addButton("Kaldi", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(t("common.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(passed_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked not in (passed_button, failed_button):
            return
        passed = clicked is passed_button

        notes: str | None = None
        if not passed:
            notes, accepted = QInputDialog.getText(
                self, "Eksik Nedir?", "Kontrolde gorulen eksikler:"
            )
            if not accepted:
                return
            if not confirm(
                self,
                f"{task.room_number} numarali oda yeniden kirli isaretlensin mi?",
                detail="Gorev tekrar acilacak ve oda satisa hazir sayilmayacak.",
                dangerous=True,
            ):
                return

        try:
            with self.ui.service_context() as ctx:
                HousekeepingService(ctx).inspect(task.task_id, passed=passed, notes=notes)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(
            self,
            f"{task.room_number} kontrolu: {'gecti' if passed else 'kaldi'}.",
            ToastLevel.SUCCESS if passed else ToastLevel.WARNING,
        )
        self.refresh(force=True)


#: Oncelik agirligindan gosterim metnine esleme.
#: Sutun HAM agirligi tasir (siralama dogru olsun diye), ekranda ise Turkce
#: etiket gorunur - "1.234,56" metnini siralamak nasil yanlissa "Acil" metnini
#: alfabetik siralamak da oyle yanlis olurdu.
_PRIORITY_TEXT: dict[int, str] = {1: "Dusuk", 2: "Normal", 3: "Yuksek", 4: "Acil", 5: "Kritik"}


__all__ = ["NOT_STARTED_STATUSES", "OPEN_STATUSES", "HousekeepingPage", "TaskInfo"]
