"""AI Gelistirme Merkezi ekrani.

Bu ekran, :mod:`app.devcenter` katmaninin gorunen yuzudur. Tasarimi tek bir
ilkeye dayanir: **kullanici ne olacagini gormeden hicbir sey olmaz.**

Ekran akisi (soldan saga, yukaridan asagiya):

1. **Gorev** - kullanici ne yapilmasini istedigini yazar
2. **Terminal** - analiz icin komut calistirilir; her komut once
   degerlendirilir ve risk seviyesi gosterilir
3. **Degisiklikler** - onerilen yamalar **diff olarak** gosterilir
4. **Onay** - kullanici acikca onaylar
5. **Dogrulama** - format/lint/tip/test/guvenlik zinciri calisir
6. **Sonuc** - gecerse islenir, gecmezse otomatik geri alinir

Uzun suren islemler (kalite zinciri dakikalar surebilir) arka plan is
parcaciginda calisir; arayuz donmaz.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from app.core.exceptions import HotelError
from app.core.log import get_logger
from app.devcenter.policy import RiskLevel, evaluate_command
from app.devcenter.quality import QualityReport
from app.devcenter.session import DevSession, SessionState
from app.security.permissions import Perm
from app.ui.pages.base import BasePage
from app.ui.session import UiSession
from app.ui.widgets.common import (
    Card,
    SectionTitle,
    StatusBadge,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)

log = get_logger(__name__)


class _QualityWorker(QObject):
    """Kalite zincirini arka planda calistirir.

    Zincir dakikalarca surebilir; ana is parcaciginda calistirilirsa arayuz
    tamamen donar ve kullanici uygulamanin cokdugunu sanir.
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, session: DevSession) -> None:
        super().__init__()
        self._session = session

    def run(self) -> None:
        try:
            report = self._session.verify()
            self.finished.emit(report)
        except Exception as exc:
            log.error("kalite_zinciri_hatasi", error=str(exc), exc_info=True)
            self.failed.emit(str(exc))


class DevCenterPage(BasePage):
    """Kisitlanmis gelistirme terminali ve yama akisi."""

    required_permission = Perm.DEVCENTER_USE
    title = "AI Gelistirme Merkezi"
    icon = "\U0001f6e0"

    def __init__(self, ui_session: UiSession, parent: QWidget | None = None) -> None:
        self._dev: DevSession | None = None
        self._thread: QThread | None = None
        self._worker: _QualityWorker | None = None
        super().__init__(ui_session, parent)

    # ----------------------------------------------------------------- #
    #  Arayuz
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        header = QHBoxLayout()
        header.addWidget(SectionTitle(self.title))
        header.addSpacing(12)

        self._state_badge = StatusBadge("Hazir", "info")
        header.addWidget(self._state_badge)
        header.addStretch(1)

        self._branch_label = QLabel()
        self._branch_label.setObjectName("Muted")
        header.addWidget(self._branch_label)
        self.root_layout.addLayout(header)

        # --- Guvenlik bilgilendirmesi ---
        notice = QLabel(
            "Bu ekran yalnizca proje klasoru icinde calisir. Komutlar once "
            "guvenlik politikasindan gecer, dosya degisiklikleri once fark "
            "(diff) olarak gosterilir ve hicbir sey onayiniz olmadan uygulanmaz. "
            "Her islem denetim gunlugune yazilir."
        )
        notice.setObjectName("BadgeInfo")
        notice.setWordWrap(True)
        self.root_layout.addWidget(notice)

        # --- Gorev satiri ---
        task_card = Card("Gorev", self)
        task_row = QHBoxLayout()
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText("Or. Rezervasyon ekranina tarih araligi filtresi ekle")
        self._task_input.setMinimumHeight(32)

        self._start_button = QPushButton("Gorevi Baslat")
        self._start_button.setObjectName("Primary")
        self._start_button.clicked.connect(self._start_task)

        self._abort_button = QPushButton("Iptal Et")
        self._abort_button.setObjectName("Danger")
        self._abort_button.clicked.connect(self._abort_task)
        self._abort_button.setEnabled(False)

        task_row.addWidget(self._task_input, 1)
        task_row.addWidget(self._start_button)
        task_row.addWidget(self._abort_button)
        task_card.add_layout(task_row)
        self.root_layout.addWidget(task_card)

        # --- Ana bolum: terminal | degisiklikler ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_terminal_panel())
        splitter.addWidget(self._build_changes_panel())
        splitter.setSizes([620, 620])
        self.root_layout.addWidget(splitter, 1)

        self._update_state_display()

    def _build_terminal_panel(self) -> QWidget:
        panel = Card("Kisitli Terminal", self)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Consolas", 9))
        self._output.setPlaceholderText(
            "Komut ciktisi burada gorunur.\n\n"
            "Yalnizca izin listesindeki komutlar calisir; degisiklik yapan "
            "komutlar onay ister."
        )
        panel.add_widget(self._output)

        # Komut degerlendirme gostergesi
        self._risk_label = QLabel()
        self._risk_label.setWordWrap(True)
        self._risk_label.setVisible(False)
        panel.add_widget(self._risk_label)

        command_row = QHBoxLayout()
        self._command_input = QLineEdit()
        self._command_input.setPlaceholderText("git status")
        self._command_input.setFont(QFont("Consolas", 9))
        self._command_input.textChanged.connect(self._preview_command_risk)
        self._command_input.returnPressed.connect(self._run_command)

        self._run_button = QPushButton("Calistir")
        self._run_button.clicked.connect(self._run_command)

        command_row.addWidget(self._command_input, 1)
        command_row.addWidget(self._run_button)
        panel.add_layout(command_row)

        return panel

    def _build_changes_panel(self) -> QWidget:
        panel = Card("Degisiklikler ve Dogrulama", self)

        self._tabs = QTabWidget()

        # Diff sekmesi
        self._diff_view = QPlainTextEdit()
        self._diff_view.setReadOnly(True)
        self._diff_view.setFont(QFont("Consolas", 9))
        self._diff_view.setPlaceholderText(
            "Onerilen dosya degisiklikleri burada fark (diff) olarak gosterilir.\n"
            "Uygulanmadan once tamamini inceleyin."
        )
        self._tabs.addTab(self._diff_view, "Fark")

        # Kalite sekmesi
        self._quality_view = QTextEdit()
        self._quality_view.setReadOnly(True)
        self._quality_view.setPlaceholderText(
            "format -> lint -> tip -> test -> guvenlik zincirinin sonucu " "burada gorunur."
        )
        self._tabs.addTab(self._quality_view, "Dogrulama")

        panel.add_widget(self._tabs)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # belirsiz ilerleme
        self._progress.setVisible(False)
        panel.add_widget(self._progress)

        # Eylem dugmeleri
        actions = QHBoxLayout()
        self._apply_button = QPushButton("Degisiklikleri Uygula")
        self._apply_button.setObjectName("Primary")
        self._apply_button.clicked.connect(self._apply_changes)
        self._apply_button.setEnabled(False)

        self._verify_button = QPushButton("Dogrula")
        self._verify_button.clicked.connect(self._verify)
        self._verify_button.setEnabled(False)

        self._commit_button = QPushButton("Isle (commit)")
        self._commit_button.clicked.connect(self._commit)
        self._commit_button.setEnabled(False)

        actions.addWidget(self._apply_button)
        actions.addWidget(self._verify_button)
        actions.addWidget(self._commit_button)
        panel.add_layout(actions)

        return panel

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        """Depo durumunu okur ve gosterir."""
        from app.core.config import get_settings
        from app.ui.formatting import format_path

        root = Path(get_settings().devcenter.sandbox_root)
        # Yol, kullanici adini sizdirmadan gosterilir: ekran goruntusu ve
        # destek ciktilari gereksiz bir kisisel tanimlayici tasimasin.
        self._append_output(f"Proje klasoru: {format_path(root)}")

        try:
            from app.devcenter.git_guard import GitGuard

            guard = GitGuard(root)
            if not guard.is_repository():
                self._append_output(
                    "[!] Bu klasor bir Git deposu degil. Gelistirme merkezi "
                    "Git olmadan calismaz."
                )
                self._start_button.setEnabled(False)
                return

            status = guard.status()
            self._branch_label.setText(f"Dal: {status.branch}")
            self._append_output(
                f"Dal: {status.branch} | "
                f"{'temiz' if status.is_clean else f'{status.change_count} degisiklik'}"
            )
        except HotelError as exc:
            self._append_output(f"[!] Git durumu okunamadi: {exc.user_message}")

    # ----------------------------------------------------------------- #
    #  Gorev yasam dongusu
    # ----------------------------------------------------------------- #
    def _start_task(self) -> None:
        description = self._task_input.text().strip()
        if not description:
            show_toast(self, "Once bir gorev tanimi yazin.", ToastLevel.WARNING)
            return

        try:
            with self.ui.service_context() as ctx:
                self._dev = DevSession(ctx)
                self._dev.start(description)
                branch = self._dev.branch
        except HotelError as exc:
            show_error(self, exc)
            return

        self._append_output(f"\n=== Gorev baslatildi: {description}")
        self._append_output(f"Gorev dali: {branch}")
        self._append_output("Kontrol noktasi alindi. Bu noktaya her zaman geri donulebilir.")
        self._branch_label.setText(f"Dal: {branch}")
        self._update_state_display()

    def _abort_task(self) -> None:
        if self._dev is None:
            return
        if not confirm(
            self,
            "Gorev iptal edilsin mi?",
            detail="Uygulanan degisiklikler geri alinacak ve gorev dali silinecek.",
            dangerous=True,
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                self._dev.ctx = ctx
                self._dev.abort(reason="Kullanici iptal etti")
        except HotelError as exc:
            show_error(self, exc)
            return

        self._append_output("\n=== Gorev iptal edildi, degisiklikler geri alindi.")
        self._diff_view.clear()
        self._quality_view.clear()
        self._update_state_display()

    # ----------------------------------------------------------------- #
    #  Terminal
    # ----------------------------------------------------------------- #
    def _preview_command_risk(self, text: str) -> None:
        """Kullanici yazarken komutun risk seviyesini gosterir.

        Komut calistirilmadan **once** ne olacagini bilmek, kullanicinin
        yanlislikla riskli bir sey onaylamasini onler.
        """
        command = text.strip()
        if not command:
            self._risk_label.setVisible(False)
            return

        decision = evaluate_command(command)
        badge = {
            RiskLevel.SAFE: "BadgeSuccess",
            RiskLevel.WRITE: "BadgeWarning",
            RiskLevel.DANGEROUS: "BadgeWarning",
            RiskLevel.BLOCKED: "BadgeDanger",
        }[decision.risk]

        self._risk_label.setObjectName(badge)
        self._risk_label.style().unpolish(self._risk_label)
        self._risk_label.style().polish(self._risk_label)

        message = f"{decision.risk.label}: {decision.reason}"
        if decision.warnings:
            message += "\n" + "\n".join(f"• {w}" for w in decision.warnings)
        self._risk_label.setText(message)
        self._risk_label.setVisible(True)

        self._run_button.setEnabled(decision.allowed)

    def _run_command(self) -> None:
        command = self._command_input.text().strip()
        if not command or self._dev is None:
            if self._dev is None:
                show_toast(self, "Once bir gorev baslatin.", ToastLevel.WARNING)
            return

        decision = evaluate_command(command)

        if not decision.allowed:
            show_toast(self, decision.reason, ToastLevel.ERROR)
            return

        approved = True
        if decision.needs_approval:
            # Kullaniciya komutun TAM HALI gosterilir.
            approved = confirm(
                self,
                "Bu komut calistirilsin mi?",
                detail=f"{command}\n\n{decision.risk.label}: {decision.reason}",
                dangerous=decision.risk is RiskLevel.DANGEROUS,
            )
        if not approved:
            self._append_output(f"\n$ {command}\n[Kullanici onaylamadi]")
            return

        self._append_output(f"\n$ {command}")
        try:
            with self.ui.service_context() as ctx:
                self._dev.ctx = ctx
                result = self._dev.run(command, approved=True)
        except HotelError as exc:
            show_error(self, exc)
            return

        if result.output:
            self._append_output(result.output)
        self._append_output(f"[{result.summary()}]")
        self._command_input.clear()

    # ----------------------------------------------------------------- #
    #  Degisiklikler
    # ----------------------------------------------------------------- #
    def show_changeset_preview(self, files: dict[str, str | None], description: str = "") -> None:
        """Onerilen degisiklikleri fark olarak gosterir (uygulamaz).

        Yapay zeka entegrasyonu bu metodu cagirir; kullanici farki gorup
        "Degisiklikleri Uygula" dedigi anda yazma yapilir.
        """
        if self._dev is None:
            show_toast(self, "Once bir gorev baslatin.", ToastLevel.WARNING)
            return

        try:
            with self.ui.service_context() as ctx:
                self._dev.ctx = ctx
                changeset = self._dev.propose(files, description=description)
        except HotelError as exc:
            show_error(self, exc)
            return

        added, removed = changeset.total_delta
        header = [
            f"# {changeset.file_count} dosya, +{added} / -{removed} satir",
            "",
            *changeset.summary_lines(),
            "",
            "-" * 60,
            "",
        ]
        self._diff_view.setPlainText("\n".join(header) + changeset.full_diff())
        self._tabs.setCurrentIndex(0)
        self._update_state_display()

    def _apply_changes(self) -> None:
        if self._dev is None or self._dev.changeset is None:
            return

        changeset = self._dev.changeset
        added, removed = changeset.total_delta
        if not confirm(
            self,
            f"{changeset.file_count} dosyadaki degisiklikler uygulansin mi?",
            detail=(
                f"+{added} satir eklenecek, -{removed} satir silinecek.\n"
                "Degisiklikler gorev dalinda yapilir; testler gecmezse "
                "otomatik geri alinir."
            ),
            dangerous=True,
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                self._dev.ctx = ctx
                written = self._dev.apply(approved=True)
        except HotelError as exc:
            show_error(self, exc)
            return

        self._append_output(f"\n=== {len(written)} dosya guncellendi.")
        show_toast(self, f"{len(written)} dosya guncellendi.", ToastLevel.SUCCESS)
        self._update_state_display()

    # ----------------------------------------------------------------- #
    #  Dogrulama (arka planda)
    # ----------------------------------------------------------------- #
    def _verify(self) -> None:
        if self._dev is None:
            return

        self._set_busy(True, "Kalite zinciri calisiyor... (birkac dakika surebilir)")
        self._tabs.setCurrentIndex(1)
        self._quality_view.setPlainText(
            "format -> lint -> tip -> test -> guvenlik zinciri calisiyor...\n"
            "Bu islem sirasinda arayuz kullanilabilir durumda kalir."
        )

        # Arka plan is parcacigi: ana is parcacigi bloklanmaz.
        self._thread = QThread(self)
        self._worker = _QualityWorker(self._dev)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_quality_finished)
        self._worker.failed.connect(self._on_quality_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_quality_finished(self, report: QualityReport) -> None:
        self._set_busy(False)

        lines = ["KALITE ZINCIRI SONUCU", "=" * 40, ""]
        lines.extend(report.summary_lines())
        lines.append("")
        lines.append(f"Toplam sure: {report.total_duration} sn")

        if report.blocking_passed:
            lines.append("")
            lines.append("Zorunlu kontroller GECTI. Degisiklik islenebilir.")
        else:
            lines.append("")
            lines.append("ZORUNLU KONTROLLER GECEMEDI. Degisiklik islenemez.")
            lines.append("")
            lines.append(report.failure_detail())

        self._quality_view.setPlainText("\n".join(lines))
        self._update_state_display()

        if report.blocking_passed:
            show_toast(self, "Kalite kontrolleri gecti.", ToastLevel.SUCCESS)
        else:
            show_toast(self, "Kalite kontrolleri gecemedi.", ToastLevel.ERROR)

    def _on_quality_failed(self, message: str) -> None:
        self._set_busy(False)
        self._quality_view.setPlainText(f"Kalite zinciri calistirilamadi:\n{message}")
        show_toast(self, "Dogrulama calistirilamadi.", ToastLevel.ERROR)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._progress.setVisible(busy)
        self._verify_button.setEnabled(not busy)
        self._apply_button.setEnabled(not busy and self._can_apply())
        self._run_button.setEnabled(not busy)
        if message:
            self._append_output(message)

    # ----------------------------------------------------------------- #
    #  Isleme
    # ----------------------------------------------------------------- #
    def _commit(self) -> None:
        if self._dev is None:
            return

        message = f"feat(ai): {self._dev.task}"
        if not confirm(
            self,
            "Degisiklikler islensin mi?",
            detail=f"Commit mesaji:\n{message}\n\nDal: {self._dev.branch}",
        ):
            return

        try:
            with self.ui.service_context() as ctx:
                self._dev.ctx = ctx
                sha = self._dev.commit(message)
        except HotelError as exc:
            show_error(self, exc)
            return

        self._append_output(f"\n=== Islendi: {sha[:8]}")
        self._append_output(
            "Degisiklik gorev dalinda. Ana dala birlestirmek ayri bir onay "
            "gerektirir ve su an arayuzden yapilmamaktadir; birlestirmeyi "
            "gozden gecirdikten sonra kendiniz yapabilirsiniz:\n"
            f"    git merge --no-ff {self._dev.branch}"
        )
        show_toast(self, f"Islendi: {sha[:8]}", ToastLevel.SUCCESS)
        self._update_state_display()

    # ----------------------------------------------------------------- #
    #  Durum
    # ----------------------------------------------------------------- #
    def _can_apply(self) -> bool:
        return (
            self._dev is not None
            and self._dev.state is SessionState.AWAITING_APPROVAL
            and self.ui.can(Perm.DEVCENTER_APPLY_PATCH)
        )

    def _update_state_display(self) -> None:
        state = self._dev.state if self._dev else SessionState.IDLE

        level = {
            SessionState.IDLE: "info",
            SessionState.PREPARING: "info",
            SessionState.AWAITING_APPROVAL: "warning",
            SessionState.APPLIED: "warning",
            SessionState.VERIFIED: "success",
            SessionState.COMMITTED: "success",
            SessionState.ABORTED: "danger",
        }[state]
        self._state_badge.set_status(state.label, level)

        active = self._dev is not None and state not in {
            SessionState.IDLE,
            SessionState.COMMITTED,
            SessionState.ABORTED,
        }
        self._start_button.setEnabled(not active)
        self._task_input.setEnabled(not active)
        self._abort_button.setEnabled(active)

        can_execute = self.ui.can(Perm.DEVCENTER_EXECUTE)
        self._run_button.setEnabled(active and can_execute)
        self._command_input.setEnabled(active and can_execute)
        if not can_execute:
            self._command_input.setToolTip(
                "Komut calistirmak icin 'devcenter.execute' yetkisi gerekir."
            )

        self._apply_button.setEnabled(self._can_apply())
        self._verify_button.setEnabled(
            state in {SessionState.APPLIED, SessionState.VERIFIED} and can_execute
        )
        self._commit_button.setEnabled(
            state is SessionState.VERIFIED and self.ui.can(Perm.DEVCENTER_APPLY_PATCH)
        )

    def _append_output(self, text: str) -> None:
        self._output.appendPlainText(text)
        scrollbar = self._output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


__all__ = ["DevCenterPage"]
