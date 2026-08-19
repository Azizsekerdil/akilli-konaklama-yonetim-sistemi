"""Git guvenlik agi: kontrol noktasi, ayri dal, geri alma.

Neden bu katman?
----------------
Yapay zekanin urettigi bir degisiklik yanlis olabilir. Bu modul, **her
degisiklikten once geri donus yolu birakildigindan** emin olur:

1. Degisiklik oncesi ``git stash create`` ile bir **kontrol noktasi** alinir
   (calisma agacina dokunmadan, yalnizca nesne olarak).
2. Degisiklikler **ayri bir dalda** yapilir; ana dal (``main``) korunur.
3. Kalite zinciri gecmezse dal birlestirilmez.
4. Basarisiz degisiklik ``restore_checkpoint`` ile geri alinir.

Guvenlik: bu modul hicbir zaman ``git push`` yapmaz. Uzak depoya gonderim
kullanicinin bilincli kararidir ve arayuzden ayri bir onay akisiyla yapilir.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.exceptions import DevCenterError
from app.core.log import get_logger

log = get_logger(__name__)

#: Otomatik olusturulan dallarin oneki - temizlik ve ayirt etme icin.
BRANCH_PREFIX = "ai/"

#: Uzerinde dogrudan calisilmayan korunan dallar.
PROTECTED_BRANCHES = frozenset({"main", "master", "develop", "release"})


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Degisiklik oncesi alinan geri donus noktasi."""

    commit_sha: str | None
    """``git stash create`` ciktisi. Calisma agaci temizse ``None``."""

    head_sha: str
    branch: str
    created_at: datetime
    had_changes: bool

    @property
    def can_restore(self) -> bool:
        return self.commit_sha is not None


@dataclass(frozen=True, slots=True)
class GitStatus:
    """Deponun anlik durumu."""

    branch: str
    is_clean: bool
    modified: tuple[str, ...] = ()
    untracked: tuple[str, ...] = ()
    staged: tuple[str, ...] = ()

    @property
    def is_protected_branch(self) -> bool:
        return self.branch in PROTECTED_BRANCHES

    @property
    def change_count(self) -> int:
        return len(self.modified) + len(self.untracked) + len(self.staged)


class GitGuard:
    """Depo uzerinde guvenli islemler."""

    def __init__(self, repo_root: Path) -> None:
        self.root = Path(repo_root).resolve()

    # ---------------------------------------------------------------- #
    #  Dusuk seviye
    # ---------------------------------------------------------------- #
    def _run(self, *args: str, check: bool = True, strip: bool = True) -> str:
        """Git komutu calistirir ve stdout dondurur.

        Parameters
        ----------
        strip:
            ``False`` verilmelidir - ``git status --porcelain`` ciktisinda
            **bastaki bosluk anlamlidir**: ilk sutun indeks (staged) durumunu,
            ikinci sutun calisma agaci durumunu gosterir. ``" M dosya"``
            degerini ``strip()`` etmek ``"M dosya"`` uretir ve sutunlar bir
            karakter kayarak staged/modified ayrimi tersine doner.
        """
        try:
            # S607 (kismi yol): "git" bilincli olarak PATH'ten cozulur.
            # Tam yol gomulseydi farkli kurulumlarda (Git for Windows, scoop,
            # winget) uygulama calismazdi. Argumanlar sabit listedir ve
            # shell=False oldugu icin enjeksiyon riski yoktur.
            completed = subprocess.run(  # noqa: S603
                ["git", *args],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DevCenterError(
                "Git komutu calistirilamadi.",
                detail=f"git {' '.join(args)}: {exc}",
                context={"cozum": "Git kurulu ve PATH icinde mi kontrol edin."},
            ) from exc

        if check and completed.returncode != 0:
            raise DevCenterError(
                "Git islemi basarisiz oldu.",
                detail=f"git {' '.join(args)} -> {completed.stderr.strip()}",
                context={"git_error": completed.stderr.strip()[:400]},
            )
        return completed.stdout.strip() if strip else completed.stdout

    # ---------------------------------------------------------------- #
    #  Durum
    # ---------------------------------------------------------------- #
    def is_repository(self) -> bool:
        """Klasor bir Git deposu mu?"""
        try:
            self._run("rev-parse", "--git-dir")
            return True
        except DevCenterError:
            return False

    def status(self) -> GitStatus:
        """Deponun anlik durumunu dondurur."""
        branch = self._run("rev-parse", "--abbrev-ref", "HEAD")
        # strip=False sart: bkz. _run docstring'i (sutun hizasi bozulur).
        porcelain = self._run("status", "--porcelain", strip=False)

        modified: list[str] = []
        untracked: list[str] = []
        staged: list[str] = []

        for line in porcelain.splitlines():
            if len(line) < 3:
                continue
            index_state, work_state, path = line[0], line[1], line[3:]
            if index_state == "?" and work_state == "?":
                untracked.append(path)
                continue
            if index_state != " ":
                staged.append(path)
            if work_state != " ":
                modified.append(path)

        return GitStatus(
            branch=branch,
            is_clean=not porcelain.strip(),
            modified=tuple(modified),
            untracked=tuple(untracked),
            staged=tuple(staged),
        )

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD")

    def diff(self, *, staged: bool = False, path: str | None = None) -> str:
        """Calisma agacindaki farki dondurur."""
        args = ["diff"]
        if staged:
            args.append("--cached")
        if path:
            args.extend(["--", path])
        return self._run(*args, check=False)

    # ---------------------------------------------------------------- #
    #  Kontrol noktasi
    # ---------------------------------------------------------------- #
    def create_checkpoint(self) -> Checkpoint:
        """Degisiklik oncesi geri donus noktasi olusturur.

        ``git stash create`` kullanilir: calisma agacini **degistirmeden**
        mevcut durumu bir commit nesnesi olarak kaydeder. ``git stash push``
        kullanilsaydi kullanicinin dosyalari aninda geri alinir ve
        beklenmedik bicimde kaybolmus gibi gorunurdu.
        """
        status = self.status()
        head = self._run("rev-parse", "HEAD")

        stash_sha: str | None = None
        if not status.is_clean:
            output = self._run("stash", "create", check=False).strip()
            stash_sha = output or None
            if stash_sha:
                # Nesnenin cop toplayiciya yem olmamasi icin isaretle.
                self._run(
                    "update-ref",
                    "refs/devcenter/checkpoint",
                    stash_sha,
                    check=False,
                )

        checkpoint = Checkpoint(
            commit_sha=stash_sha,
            head_sha=head,
            branch=status.branch,
            created_at=datetime.now().astimezone(),
            had_changes=not status.is_clean,
        )
        log.info(
            "kontrol_noktasi_olusturuldu",
            branch=status.branch,
            had_changes=checkpoint.had_changes,
            restorable=checkpoint.can_restore,
        )
        return checkpoint

    def restore_checkpoint(self, checkpoint: Checkpoint) -> bool:
        """Kontrol noktasina geri doner.

        Returns
        -------
        bool
            Geri yukleme yapildiysa ``True``. Kontrol noktasi bos bir calisma
            agacindan alindiysa yapacak bir sey yoktur ve ``False`` doner.
        """
        if not checkpoint.can_restore:
            log.info("kontrol_noktasi_bos", detail="Geri yuklenecek degisiklik yok.")
            return False

        self._run("checkout", "--", ".", check=False)
        self._run("stash", "apply", checkpoint.commit_sha or "", check=False)
        log.warning("kontrol_noktasina_donuldu", sha=(checkpoint.commit_sha or "")[:8])
        return True

    # ---------------------------------------------------------------- #
    #  Dal yonetimi
    # ---------------------------------------------------------------- #
    @staticmethod
    def slugify(text: str, *, max_length: int = 40) -> str:
        """Metni dal adina uygun hale getirir.

        >>> GitGuard.slugify("Rezervasyon ekranina filtre ekle")
        'rezervasyon-ekranina-filtre-ekle'
        """
        lowered = text.strip().lower()
        replacements = {
            "ç": "c",
            "ğ": "g",
            "ı": "i",
            "ö": "o",
            "ş": "s",
            "ü": "u",
            "Ç": "c",
            "Ğ": "g",
            "İ": "i",
            "Ö": "o",
            "Ş": "s",
            "Ü": "u",
        }
        for source, target in replacements.items():
            lowered = lowered.replace(source, target)
        slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return (slug[:max_length].rstrip("-")) or "gorev"

    def create_task_branch(self, task_description: str) -> str:
        """Gorev icin ayri bir dal olusturur ve o dala gecer.

        Ana dal her zaman korunur: degisiklikler ``ai/<gorev>`` dalinda yapilir
        ve yalnizca kalite zinciri gectikten sonra, kullanicinin acik onayiyla
        birlestirilir.
        """
        base = self.current_branch()
        stamp = datetime.now().astimezone().strftime("%m%d-%H%M")
        branch = f"{BRANCH_PREFIX}{stamp}-{self.slugify(task_description)}"

        self._run("checkout", "-b", branch)
        log.info("gorev_dali_olusturuldu", branch=branch, base=base)
        return branch

    def switch_branch(self, branch: str) -> None:
        """Baska bir dala gecer."""
        self._run("checkout", branch)

    def commit_all(self, message: str) -> str:
        """Tum degisiklikleri isler ve commit SHA dondurur.

        .. note::
           Bu metod ``git add -A`` kullanir; ``.gitignore`` kurallari
           gecerlidir, yani ``.env`` ve veritabani dosyalari eklenmez.
        """
        if not message.strip():
            raise DevCenterError("Commit mesaji bos olamaz.")

        self._run("add", "-A")
        status = self.status()
        if not status.staged:
            raise DevCenterError(
                "Islenecek degisiklik yok.",
                context={"cozum": "Once bir degisiklik uygulayin."},
            )

        self._run("commit", "-m", message)
        sha = self._run("rev-parse", "HEAD")
        log.info("degisiklik_islendi", sha=sha[:8], branch=status.branch)
        return sha

    def merge_into(self, target: str, *, source: str | None = None, no_ff: bool = True) -> str:
        """Gorev dalini hedef dala birlestirir.

        .. warning::
           Bu islem yalnizca kalite zinciri **gectikten** ve kullanici acik
           onay verdikten sonra cagrilmalidir. Cagiran taraf bunu garanti eder;
           bu metod tek basina bir kapi degildir.
        """
        current = source or self.current_branch()
        self._run("checkout", target)
        args = ["merge", "--no-ff" if no_ff else "--ff", current]
        self._run(*args)
        sha = self._run("rev-parse", "HEAD")
        log.warning("dal_birlestirildi", source=current, target=target, sha=sha[:8])
        return sha

    def delete_branch(self, branch: str, *, force: bool = False) -> None:
        """Gorev dalini siler.

        Korunan dallar (``main`` vb.) hicbir kosulda silinemez.
        """
        if branch in PROTECTED_BRANCHES:
            raise DevCenterError(
                f"'{branch}' korunan bir daldir ve silinemez.",
                code="protected_branch",
            )
        self._run("branch", "-D" if force else "-d", branch)

    def abandon_task_branch(self, branch: str, *, return_to: str) -> None:
        """Basarisiz gorev dalini terk eder ve onceki dala doner."""
        if branch in PROTECTED_BRANCHES:
            raise DevCenterError(f"'{branch}' korunan bir daldir.", code="protected_branch")

        self._run("checkout", "--", ".", check=False)
        self._run("checkout", return_to)
        self._run("branch", "-D", branch, check=False)
        log.warning("gorev_dali_terk_edildi", branch=branch, returned_to=return_to)

    def list_task_branches(self) -> list[str]:
        """Yapay zeka tarafindan olusturulmus dallari listeler."""
        output = self._run("branch", "--list", f"{BRANCH_PREFIX}*", check=False)
        return [line.strip().lstrip("* ").strip() for line in output.splitlines() if line.strip()]


__all__ = [
    "BRANCH_PREFIX",
    "PROTECTED_BRANCHES",
    "Checkpoint",
    "GitGuard",
    "GitStatus",
]
