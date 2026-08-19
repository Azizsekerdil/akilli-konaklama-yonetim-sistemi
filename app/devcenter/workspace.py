"""Dosya degisikliklerini hazirlama, onizleme ve uygulama.

Akis: **once diff, sonra onay, en son yazma.**

Yapay zeka bir dosya degisikligi onerdiginde disk hemen degismez. Once bir
:class:`ChangeSet` olusturulur, birlesik fark (unified diff) uretilir ve
kullaniciya gosterilir. Kullanici onaylarsa yazma yapilir.

Korumalar
---------
* Yol sandbox disina cikamaz (``..`` kacislari cozumlenerek engellenir).
* Hassas dosyalar (``.env``, ``.git/``, veritabani, anahtar dosyalari)
  hicbir kosulda yazilamaz.
* Yazmadan once mevcut icerik okunur; dosya bu arada baskasi tarafindan
  degistirilmisse islem durdurulur (kayip guncelleme onlenir).
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.core.exceptions import DevCenterError, SandboxViolationError
from app.core.log import get_logger

log = get_logger(__name__)

#: Hicbir kosulda degistirilemeyecek yollar (sandbox icinde olsalar bile).
PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        ".env",
        ".git",
        ".venv",
        "data",
        "backups",
        "logs",
        "uploads",
    }
)

#: Yazilamayan dosya uzantilari.
PROTECTED_SUFFIXES: frozenset[str] = frozenset(
    {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".p12", ".bak"}
)

#: Tek seferde uygulanabilecek azami dosya sayisi.
MAX_FILES_PER_CHANGESET = 40

#: Tek dosya icin azami boyut (yarim megabayt).
MAX_FILE_BYTES = 512 * 1024


class ChangeAction(str, Enum):
    """Bir dosya uzerinde yapilacak islem."""

    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"

    @property
    def label(self) -> str:
        return {"create": "Yeni dosya", "modify": "Degisiklik", "delete": "Silme"}[self.value]


@dataclass(slots=True)
class FileChange:
    """Tek bir dosya uzerindeki degisiklik onerisi."""

    relative_path: str
    action: ChangeAction
    new_content: str | None = None
    """``DELETE`` icin ``None``."""

    original_content: str | None = None
    original_hash: str | None = None
    """Hazirlama anindaki icerik ozeti - yazmadan once dogrulanir."""

    @property
    def line_delta(self) -> tuple[int, int]:
        """(eklenen, silinen) satir sayilari."""
        old_lines = (self.original_content or "").splitlines()
        new_lines = (self.new_content or "").splitlines()
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        added = removed = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in {"replace", "delete"}:
                removed += i2 - i1
            if tag in {"replace", "insert"}:
                added += j2 - j1
        return added, removed

    def diff(self, *, context_lines: int = 3) -> str:
        """Birlesik fark (unified diff) uretir."""
        old_lines = (self.original_content or "").splitlines(keepends=True)
        new_lines = (self.new_content or "").splitlines(keepends=True)

        from_label = f"a/{self.relative_path}"
        to_label = f"b/{self.relative_path}"
        if self.action is ChangeAction.CREATE:
            from_label = "/dev/null"
        elif self.action is ChangeAction.DELETE:
            to_label = "/dev/null"

        return "".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=from_label,
                tofile=to_label,
                n=context_lines,
            )
        )

    def summary(self) -> str:
        added, removed = self.line_delta
        return f"{self.action.label}: {self.relative_path}  (+{added} / -{removed})"


@dataclass(slots=True)
class ChangeSet:
    """Birlikte uygulanacak dosya degisiklikleri."""

    changes: list[FileChange] = field(default_factory=list)
    description: str = ""

    @property
    def file_count(self) -> int:
        return len(self.changes)

    @property
    def total_delta(self) -> tuple[int, int]:
        added = removed = 0
        for change in self.changes:
            a, r = change.line_delta
            added += a
            removed += r
        return added, removed

    def full_diff(self) -> str:
        """Tum degisikliklerin birlesik farki."""
        return "\n".join(change.diff() for change in self.changes)

    def summary_lines(self) -> list[str]:
        return [change.summary() for change in self.changes]


class Workspace:
    """Sandbox icinde guvenli dosya islemleri."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    # ---------------------------------------------------------------- #
    #  Yol guvenligi
    # ---------------------------------------------------------------- #
    def resolve(self, relative_path: str) -> Path:
        """Goreli yolu sandbox icinde cozer.

        Raises
        ------
        SandboxViolationError
            Yol kok disina cikiyorsa veya korumali bir yolsa.
        """
        candidate_str = str(relative_path).strip().replace("\\", "/")
        if not candidate_str:
            raise SandboxViolationError("Bos dosya yolu.", detail=relative_path)

        if Path(candidate_str).is_absolute() or ":" in candidate_str[:3]:
            raise SandboxViolationError(
                "Mutlak yol kullanilamaz; yollar proje koküne göreli olmalidir.",
                detail=candidate_str,
            )

        candidate = (self.root / candidate_str).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise SandboxViolationError(
                "Dosya proje klasorunun disinda.",
                detail=str(candidate),
                context={"path": candidate_str},
            )

        # Korumali klasor/dosya kontrolu
        try:
            parts = candidate.relative_to(self.root).parts
        except ValueError:  # pragma: no cover - yukarida elendi
            raise SandboxViolationError("Yol cozulemedi.", detail=str(candidate)) from None

        if parts and parts[0] in PROTECTED_PATHS:
            raise SandboxViolationError(
                f"'{parts[0]}' korumali bir konumdur ve degistirilemez.",
                detail=str(candidate),
                context={"cozum": "Bu konumdaki dosyalar elle yonetilmelidir."},
            )
        if candidate.name in PROTECTED_PATHS:
            raise SandboxViolationError(
                f"'{candidate.name}' korumali bir dosyadir.",
                detail=str(candidate),
            )
        if candidate.suffix.lower() in PROTECTED_SUFFIXES:
            raise SandboxViolationError(
                f"'{candidate.suffix}' uzantili dosyalar degistirilemez.",
                detail=str(candidate),
            )
        return candidate

    def read(self, relative_path: str) -> str | None:
        """Dosyayi okur; yoksa ``None`` doner."""
        path = self.resolve(relative_path)
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    # ---------------------------------------------------------------- #
    #  Degisiklik hazirlama
    # ---------------------------------------------------------------- #
    def prepare_change(
        self,
        relative_path: str,
        new_content: str | None,
        *,
        action: ChangeAction | None = None,
    ) -> FileChange:
        """Tek bir dosya degisikligi hazirlar (DISKE YAZMAZ)."""
        path = self.resolve(relative_path)
        exists = path.exists()

        if action is None:
            if new_content is None:
                action = ChangeAction.DELETE
            else:
                action = ChangeAction.MODIFY if exists else ChangeAction.CREATE

        if action is ChangeAction.DELETE and not exists:
            raise DevCenterError(
                f"Silinecek dosya bulunamadi: {relative_path}",
                code="file_not_found",
            )
        if action is ChangeAction.CREATE and exists:
            raise DevCenterError(
                f"Dosya zaten var: {relative_path}",
                code="file_exists",
                context={"cozum": "Degisiklik icin 'modify' kullanin."},
            )
        if new_content is not None and len(new_content.encode("utf-8")) > MAX_FILE_BYTES:
            raise DevCenterError(
                f"Dosya cok buyuk: {relative_path}",
                code="file_too_large",
                context={"limit_kb": MAX_FILE_BYTES // 1024},
            )

        original = path.read_text(encoding="utf-8") if exists else None

        return FileChange(
            relative_path=str(Path(relative_path).as_posix()),
            action=action,
            new_content=new_content,
            original_content=original,
            original_hash=_hash(original),
        )

    def prepare_changeset(
        self,
        files: dict[str, str | None],
        *,
        description: str = "",
    ) -> ChangeSet:
        """Birden fazla dosya degisikligini birlikte hazirlar."""
        if len(files) > MAX_FILES_PER_CHANGESET:
            raise DevCenterError(
                f"Tek seferde en fazla {MAX_FILES_PER_CHANGESET} dosya degistirilebilir "
                f"(istenen: {len(files)}).",
                code="too_many_files",
                context={"cozum": "Degisikligi daha kucuk adimlara bolun."},
            )

        changeset = ChangeSet(description=description)
        for relative_path, content in files.items():
            changeset.changes.append(self.prepare_change(relative_path, content))
        return changeset

    # ---------------------------------------------------------------- #
    #  Uygulama
    # ---------------------------------------------------------------- #
    def apply(self, changeset: ChangeSet, *, approved: bool = False) -> list[str]:
        """Degisiklikleri diske yazar.

        Parameters
        ----------
        approved:
            Kullanici **farki gorup onayladiysa** ``True``. Bu bayrak olmadan
            hicbir sey yazilmaz.

        Returns
        -------
        list[str]
            Yazilan dosyalarin goreli yollari.

        Raises
        ------
        DevCenterError
            Onay yoksa veya dosya hazirlik anindan beri degistiyse.
        """
        if not approved:
            raise DevCenterError(
                "Degisiklikler uygulanmadan once onaylanmalidir.",
                code="approval_required",
                context={"cozum": "Farki inceleyip onaylayin."},
            )

        # --- Once TUM dosyalari dogrula (kismi yazma olmasin) ---
        for change in changeset.changes:
            path = self.resolve(change.relative_path)
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if _hash(current) != change.original_hash:
                raise DevCenterError(
                    f"'{change.relative_path}' dosyasi bu degisiklik hazirlandiktan "
                    "sonra baskasi tarafindan degistirildi. Islem iptal edildi.",
                    code="stale_change",
                    context={"cozum": "Degisikligi yeniden hazirlayin (dosya guncel halinden)."},
                )

        # --- Yazma ---
        written: list[str] = []
        for change in changeset.changes:
            path = self.resolve(change.relative_path)

            if change.action is ChangeAction.DELETE:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Satir sonu bicimini koru: Windows'ta CRLF, aksi halde LF.
                path.write_text(change.new_content or "", encoding="utf-8", newline="")

            written.append(change.relative_path)

        added, removed = changeset.total_delta
        log.warning(
            "dosya_degisikligi_uygulandi",
            file_count=len(written),
            added_lines=added,
            removed_lines=removed,
        )
        return written


def _hash(content: str | None) -> str | None:
    """Icerik ozeti - eszamanli degisiklik tespiti icin."""
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "MAX_FILES_PER_CHANGESET",
    "MAX_FILE_BYTES",
    "PROTECTED_PATHS",
    "PROTECTED_SUFFIXES",
    "ChangeAction",
    "ChangeSet",
    "FileChange",
    "Workspace",
]
