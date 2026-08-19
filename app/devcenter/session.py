"""AI Gelistirme Merkezi oturumu - tum akisi yoneten sinif.

Akis
----
::

    istek -> analiz -> plan -> onerilen dosyalar -> diff -> KULLANICI ONAYI
          -> uygulama -> kalite zinciri -> sonuc raporu -> commit / geri alma

Her asama denetim gunlugune yazilir. Kullanici onayi olmadan hicbir dosya
degismez, hicbir komut calismaz ve hicbir dal birlestirilmez.

Durum makinesi
--------------
Oturum belirli bir sirayla ilerler; atlanan adim sessizce gecilmez::

    IDLE -> PREPARING -> AWAITING_APPROVAL -> APPLIED -> VERIFIED -> COMMITTED
                                    |             |          |
                                    +-> ABORTED <-+----------+
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from app.application.context import ServiceContext
from app.core.exceptions import DevCenterError
from app.core.log import get_logger
from app.devcenter.git_guard import Checkpoint, GitGuard
from app.devcenter.quality import QualityReport, run_quality_chain
from app.devcenter.terminal import CommandLog, CommandResult, run_command
from app.devcenter.workspace import ChangeSet, Workspace
from app.domain.enums import AuditAction
from app.security.permissions import Perm

log = get_logger(__name__)


class SessionState(str, Enum):
    """Oturumun bulundugu asama."""

    IDLE = "idle"
    PREPARING = "preparing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLIED = "applied"
    VERIFIED = "verified"
    COMMITTED = "committed"
    ABORTED = "aborted"

    @property
    def label(self) -> str:
        return {
            "idle": "Hazir",
            "preparing": "Hazirlaniyor",
            "awaiting_approval": "Onay bekliyor",
            "applied": "Uygulandi",
            "verified": "Dogrulandi",
            "committed": "Islendi",
            "aborted": "Iptal edildi",
        }[self.value]


@dataclass(slots=True)
class TaskReport:
    """Gorev sonunda uretilen rapor."""

    task: str
    state: SessionState
    branch: str | None = None
    commit_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    quality: QualityReport | None = None
    commands: CommandLog = field(default_factory=CommandLog)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.state is SessionState.COMMITTED

    def as_text(self) -> str:
        """Kullaniciya gosterilecek metin raporu."""
        lines = [
            f"Gorev   : {self.task}",
            f"Durum   : {self.state.label}",
        ]
        if self.branch:
            lines.append(f"Dal     : {self.branch}")
        if self.commit_sha:
            lines.append(f"Commit  : {self.commit_sha[:8]}")
        if self.changed_files:
            lines.append(f"Dosya   : {len(self.changed_files)} degisiklik")
            lines.extend(f"          - {path}" for path in self.changed_files[:20])
        if self.quality:
            lines.append("Kalite  :")
            lines.extend(f"          {line}" for line in self.quality.summary_lines())
        if self.commands.entries:
            lines.append(f"Komut   : {len(self.commands.entries)} calistirildi")
        if self.message:
            lines.append(f"Not     : {self.message}")
        return "\n".join(lines)


class DevSession:
    """Tek bir gelistirme gorevinin yasam dongusu.

    Kullanim::

        session = DevSession(ctx, root)
        session.start("Rezervasyon ekranina tarih filtresi ekle")
        changeset = session.propose(files)      # diff uretir
        print(changeset.full_diff())            # kullaniciya gosterilir
        session.apply(changeset, approved=True) # ONAY sonrasi
        report = session.verify_and_commit("feat: tarih filtresi")
    """

    def __init__(
        self,
        context: ServiceContext,
        root: Path | None = None,
        *,
        git: GitGuard | None = None,
    ) -> None:
        from app.core.config import get_settings

        self.ctx = context
        self.root = Path(root or get_settings().devcenter.sandbox_root).resolve()
        self.workspace = Workspace(self.root)
        self.git = git or GitGuard(self.root)

        self.state = SessionState.IDLE
        self.task: str = ""
        self.branch: str | None = None
        self.base_branch: str | None = None
        self.checkpoint: Checkpoint | None = None
        self.changeset: ChangeSet | None = None
        self.changed_files: list[str] = []
        self.commands = CommandLog()
        self.started_at: datetime | None = None

    # ---------------------------------------------------------------- #
    #  1) Baslatma
    # ---------------------------------------------------------------- #
    def start(self, task_description: str, *, use_branch: bool = True) -> None:
        """Gorevi baslatir: kontrol noktasi alir, ayri dal olusturur.

        Raises
        ------
        DevCenterError
            Depo Git deposu degilse veya oturum zaten aktifse.
        """
        self.ctx.require(Perm.DEVCENTER_USE)

        if self.state not in {SessionState.IDLE, SessionState.COMMITTED, SessionState.ABORTED}:
            raise DevCenterError(
                f"Onceki gorev henuz tamamlanmadi (durum: {self.state.label}).",
                code="session_busy",
                context={"cozum": "Once mevcut gorevi tamamlayin veya iptal edin."},
            )
        if not task_description.strip():
            raise DevCenterError("Gorev aciklamasi bos olamaz.")

        if not self.git.is_repository():
            raise DevCenterError(
                "Proje klasoru bir Git deposu degil.",
                code="not_a_repository",
                context={
                    "cozum": "Gelistirme merkezi Git olmadan calismaz. "
                    "Once 'git init' calistirin."
                },
            )

        self.task = task_description.strip()
        self.started_at = datetime.now().astimezone()
        self.commands = CommandLog()
        self.changed_files = []
        self.changeset = None

        # Kontrol noktasi HER ZAMAN alinir - dal kullanilmasa bile.
        self.checkpoint = self.git.create_checkpoint()
        self.base_branch = self.git.current_branch()

        if use_branch:
            self.branch = self.git.create_task_branch(self.task)
        else:
            self.branch = self.base_branch

        self.state = SessionState.PREPARING

        self.ctx.audit(
            AuditAction.COMMAND_EXECUTED,
            f"Gelistirme gorevi baslatildi: {self.task}",
            entity_type="DevSession",
            after={"branch": self.branch, "base": self.base_branch},
        )
        log.info("gelistirme_gorevi_basladi", task=self.task, branch=self.branch)

    # ---------------------------------------------------------------- #
    #  2) Komut calistirma (analiz asamasinda)
    # ---------------------------------------------------------------- #
    def run(
        self, command: str, *, approved: bool = False, timeout: int | None = None
    ) -> CommandResult:
        """Kisitli terminalde komut calistirir.

        Onay gerektiren komutlar ``approved=True`` olmadan calistirilmaz;
        bu bayrak yalnizca kullanici arayuzde komutu gorup onayladiginda
        gecirilir.
        """
        self.ctx.require(Perm.DEVCENTER_EXECUTE)

        result = run_command(command, cwd=self.root, timeout=timeout, approved=approved)
        self.commands.add(result)

        self.ctx.audit(
            AuditAction.COMMAND_EXECUTED,
            f"Komut calistirildi: {command}",
            entity_type="DevSession",
            after={
                "exit_code": result.exit_code,
                "duration": result.duration_seconds,
                "risk": result.decision.risk.value if result.decision else None,
            },
            is_success=result.success,
        )
        return result

    # ---------------------------------------------------------------- #
    #  3) Degisiklik onerisi (diff uretir, DISKE YAZMAZ)
    # ---------------------------------------------------------------- #
    def propose(self, files: dict[str, str | None], *, description: str = "") -> ChangeSet:
        """Dosya degisikliklerini hazirlar ve onay bekleyen duruma gecer."""
        self.ctx.require(Perm.DEVCENTER_APPLY_PATCH)

        if self.state not in {SessionState.PREPARING, SessionState.AWAITING_APPROVAL}:
            raise DevCenterError(
                "Degisiklik onerisi icin once bir gorev baslatilmalidir.",
                code="invalid_state",
            )

        self.changeset = self.workspace.prepare_changeset(
            files, description=description or self.task
        )
        self.state = SessionState.AWAITING_APPROVAL

        added, removed = self.changeset.total_delta
        log.info(
            "degisiklik_onerildi",
            files=self.changeset.file_count,
            added=added,
            removed=removed,
        )
        return self.changeset

    # ---------------------------------------------------------------- #
    #  4) Uygulama (KULLANICI ONAYI SONRASI)
    # ---------------------------------------------------------------- #
    def apply(self, changeset: ChangeSet | None = None, *, approved: bool = False) -> list[str]:
        """Onaylanan degisiklikleri diske yazar."""
        self.ctx.require(Perm.DEVCENTER_APPLY_PATCH)

        target = changeset or self.changeset
        if target is None:
            raise DevCenterError("Uygulanacak degisiklik yok.", code="no_changeset")
        if self.state is not SessionState.AWAITING_APPROVAL:
            raise DevCenterError(
                "Degisiklik onay bekleyen durumda degil.",
                code="invalid_state",
                context={"durum": self.state.label},
            )

        written = self.workspace.apply(target, approved=approved)
        self.changed_files = written
        self.state = SessionState.APPLIED

        self.ctx.audit(
            AuditAction.UPDATE,
            f"Yapay zeka degisikligi uygulandi: {len(written)} dosya",
            entity_type="DevSession",
            after={"files": written[:20], "branch": self.branch},
        )
        return written

    # ---------------------------------------------------------------- #
    #  5) Dogrulama ve islem
    # ---------------------------------------------------------------- #
    def verify(self) -> QualityReport:
        """Kalite zincirini calistirir."""
        self.ctx.require(Perm.DEVCENTER_EXECUTE)

        if self.state not in {SessionState.APPLIED, SessionState.VERIFIED}:
            raise DevCenterError(
                "Dogrulama icin once degisiklik uygulanmalidir.",
                code="invalid_state",
            )

        report = run_quality_chain(root=self.root)
        self.state = SessionState.VERIFIED if report.blocking_passed else SessionState.APPLIED

        self.ctx.audit(
            AuditAction.COMMAND_EXECUTED,
            "Kalite zinciri calistirildi.",
            entity_type="DevSession",
            after={
                "all_passed": report.all_passed,
                "blocking_passed": report.blocking_passed,
                "duration": report.total_duration,
            },
            is_success=report.blocking_passed,
        )
        return report

    def commit(self, message: str) -> str:
        """Degisiklikleri gorev dalinda isler.

        .. important::
           Kalite zinciri (:meth:`verify`) gecmeden commit yapilamaz. Bu,
           "testler basarisizsa birlestirme" kuralinin ilk kapisidir.
        """
        self.ctx.require(Perm.DEVCENTER_APPLY_PATCH)

        if self.state is not SessionState.VERIFIED:
            raise DevCenterError(
                "Kalite kontrolleri gecmeden degisiklik islenemez.",
                code="quality_gate_failed",
                context={
                    "durum": self.state.label,
                    "cozum": "Once dogrulamayi calistirin ve hatalari giderin.",
                },
            )

        sha = self.git.commit_all(message)
        self.state = SessionState.COMMITTED

        self.ctx.audit(
            AuditAction.UPDATE,
            f"Yapay zeka degisikligi islendi: {message}",
            entity_type="DevSession",
            after={"commit": sha, "branch": self.branch},
        )
        return sha

    def verify_and_commit(self, message: str) -> TaskReport:
        """Dogrula, gecerse isle, gecmezse **otomatik geri al**."""
        report = self.verify()

        task_report = TaskReport(
            task=self.task,
            state=self.state,
            branch=self.branch,
            changed_files=list(self.changed_files),
            quality=report,
            commands=self.commands,
            started_at=self.started_at,
            finished_at=datetime.now().astimezone(),
        )

        if not report.blocking_passed:
            failed = ", ".join(s.step.title for s in report.failed_steps)
            task_report.message = (
                f"Kalite kontrolleri gecemedi ({failed}). Degisiklikler geri alindi."
            )
            self.abort(reason=task_report.message)
            task_report.state = SessionState.ABORTED
            return task_report

        task_report.commit_sha = self.commit(message)
        task_report.state = SessionState.COMMITTED
        task_report.message = "Degisiklikler gorev dalinda islendi."
        return task_report

    # ---------------------------------------------------------------- #
    #  6) Birlestirme (ayri ve acik onay)
    # ---------------------------------------------------------------- #
    def merge_to_base(self, *, approved: bool = False) -> str:
        """Gorev dalini baslangic dalina birlestirir.

        Bu **ayri bir karardir**: commit basarili olsa bile birlestirme
        kullanicinin acik onayini gerektirir.
        """
        self.ctx.require(Perm.DEVCENTER_APPLY_PATCH)

        if not approved:
            raise DevCenterError(
                "Ana dala birlestirme acik onay gerektirir.",
                code="approval_required",
            )
        if self.state is not SessionState.COMMITTED:
            raise DevCenterError(
                "Yalnizca islenmis (commit edilmis) bir gorev birlestirilebilir.",
                code="invalid_state",
            )
        if not self.base_branch or not self.branch or self.branch == self.base_branch:
            raise DevCenterError("Birlestirilecek ayri bir gorev dali yok.")

        sha = self.git.merge_into(self.base_branch, source=self.branch)
        self.ctx.audit(
            AuditAction.UPDATE,
            f"Gorev dali '{self.branch}' -> '{self.base_branch}' birlestirildi.",
            entity_type="DevSession",
            after={"merge_commit": sha},
        )
        return sha

    # ---------------------------------------------------------------- #
    #  7) Geri alma
    # ---------------------------------------------------------------- #
    def abort(self, *, reason: str = "") -> None:
        """Gorevi iptal eder ve degisiklikleri geri alir."""
        previous_state = self.state

        try:
            if self.branch and self.base_branch and self.branch != self.base_branch:
                self.git.abandon_task_branch(self.branch, return_to=self.base_branch)
            elif self.checkpoint is not None:
                self.git.restore_checkpoint(self.checkpoint)
        except DevCenterError as exc:
            log.error("geri_alma_basarisiz", error=exc.detail or exc.user_message)
            raise

        self.state = SessionState.ABORTED
        self.ctx.audit(
            AuditAction.UPDATE,
            f"Gelistirme gorevi iptal edildi: {reason or 'kullanici istegi'}",
            entity_type="DevSession",
            before={"state": previous_state.value},
            after={"state": self.state.value},
            is_success=False,
        )
        log.warning("gelistirme_gorevi_iptal", task=self.task, reason=reason)

    def build_report(self, message: str = "") -> TaskReport:
        """Mevcut durumdan rapor uretir."""
        return TaskReport(
            task=self.task,
            state=self.state,
            branch=self.branch,
            changed_files=list(self.changed_files),
            commands=self.commands,
            started_at=self.started_at,
            finished_at=datetime.now().astimezone(),
            message=message,
        )


__all__ = ["DevSession", "SessionState", "TaskReport"]
