"""Veritabani yedekleme ve geri yukleme.

Neden ``VACUUM INTO``?
----------------------
SQLite WAL kipinde calisirken (bkz. :mod:`app.infrastructure.db.session`)
ana ``.db`` dosyasini kopyalamak **tutarsiz bir yedek** uretir: henuz ana
dosyaya aktarilmamis islemler ``-wal`` dosyasinda bekliyor olabilir ve
kopyalama sirasinda yeni yazmalar gelebilir. ``VACUUM INTO`` ise veritabanini
tek bir tutarli anlik goruntu olarak yeni bir dosyaya yazar; uygulama
calismaya devam edebilir.

PostgreSQL icin bu modul yedek almaz; ``pg_dump`` kullanilmasi gerektigini
bildirir. Nedeni, ag uzerindeki bir sunucunun yedeginin isletim sistemi
araclariyla alinmasinin daha guvenilir olmasidir.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import DatabaseError, ValidationError
from app.core.log import get_logger

log = get_logger(__name__)

#: Yedek dosyasi adi kalibi.
BACKUP_PREFIX = "hotel_"
BACKUP_SUFFIX = ".db"
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


@dataclass(slots=True)
class BackupResult:
    """Yedekleme sonucu."""

    path: Path
    size_bytes: int
    created_at: datetime
    removed_old: int = 0

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)


def _sqlite_path_from_url(url: str) -> Path | None:
    """SQLAlchemy adresinden SQLite dosya yolunu cikarir."""
    if not url.startswith("sqlite"):
        return None
    _, _, rest = url.partition(":///")
    if not rest or rest == ":memory:":
        return None
    return Path(rest)


def create_backup(*, backup_dir: Path | None = None, keep: int | None = None) -> BackupResult:
    """Veritabaninin tutarli bir yedegini alir.

    Parameters
    ----------
    backup_dir:
        Hedef klasor. ``None`` ise ayarlardaki ``HOTEL_BACKUP_DIR``.
    keep:
        Saklanacak yedek sayisi. ``None`` ise ayarlardaki deger.

    Raises
    ------
    DatabaseError
        Veritabani SQLite degilse veya yedek alinamazsa.
    """
    settings = get_settings()
    url = settings.database.resolved_url()

    source = _sqlite_path_from_url(url)
    if source is None:
        raise DatabaseError(
            "Otomatik yedekleme yalnizca SQLite icin desteklenir.",
            detail=f"Desteklenmeyen adres: {url.split('://')[0]}",
            context={
                "cozum": "PostgreSQL kullaniyorsaniz 'pg_dump' ile yedek alin; "
                "ornek: pg_dump -Fc -f yedek.dump hotel"
            },
        )

    if not source.exists():
        raise DatabaseError(
            "Veritabani dosyasi bulunamadi.",
            detail=str(source),
            context={"cozum": "Once gocleri uygulayin: alembic upgrade head"},
        )

    target_dir = backup_dir or settings.backup.directory
    target_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().astimezone()
    target = target_dir / f"{BACKUP_PREFIX}{created_at.strftime(TIMESTAMP_FORMAT)}{BACKUP_SUFFIX}"

    if target.exists():
        raise DatabaseError(
            "Ayni adla bir yedek zaten var.",
            detail=str(target),
            context={"cozum": "Bir saniye bekleyip tekrar deneyin."},
        )

    connection = sqlite3.connect(str(source))
    try:
        # VACUUM INTO parametre baglamayi desteklemez; yol dizgeye gomulur.
        # Bu yuzden tek tirnaklari kacirarak SQL enjeksiyonunu onluyoruz.
        escaped = str(target).replace("'", "''")
        connection.execute(f"VACUUM INTO '{escaped}'")
    except sqlite3.Error as exc:
        raise DatabaseError(
            "Yedek alinamadi.",
            detail=str(exc),
            context={"cozum": "Disk alanini ve klasor yazma iznini kontrol edin."},
        ) from exc
    finally:
        connection.close()

    removed = prune_backups(
        target_dir, keep=keep if keep is not None else settings.backup.retention
    )

    result = BackupResult(
        path=target,
        size_bytes=target.stat().st_size,
        created_at=created_at,
        removed_old=removed,
    )
    log.info(
        "yedek_alindi",
        path=str(target),
        size_mb=result.size_mb,
        silinen_eski=removed,
    )
    return result


def list_backups(backup_dir: Path | None = None) -> list[Path]:
    """Yedekleri en yeniden eskiye siralar."""
    directory = backup_dir or get_settings().backup.directory
    if not directory.exists():
        return []
    backups = [p for p in directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}") if p.is_file()]
    return sorted(backups, key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(backup_dir: Path | None = None, *, keep: int = 14) -> int:
    """En yeni ``keep`` yedegi birakip digerlerini siler.

    Returns
    -------
    int
        Silinen dosya sayisi.
    """
    if keep < 1:
        raise ValidationError("En az 1 yedek saklanmalidir.", field="keep")

    backups = list_backups(backup_dir)
    to_remove = backups[keep:]
    removed = 0
    for path in to_remove:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:  # pragma: no cover - dosya kilitli olabilir
            log.warning("eski_yedek_silinemedi", path=str(path), error=str(exc))
    return removed


def restore_backup(source: Path, *, confirm: bool = False) -> Path:
    """Yedegi geri yukler.

    .. warning::
       Mevcut veritabaninin **uzerine yazar**. Geri alinamaz.

    Guvenlik onlemi olarak, uzerine yazmadan hemen once mevcut veritabaninin
    ``.pre-restore`` uzantili bir kopyasi alinir; boylece yanlis yedek
    yuklendiginde donus yolu kalir.

    Parameters
    ----------
    confirm:
        ``True`` olmadan calismaz. Kazara cagriyi onler.
    """
    if not confirm:
        raise ValidationError(
            "Geri yukleme onay gerektirir.",
            detail="restore_backup(confirm=True) ile cagirin.",
            field="confirm",
        )

    source = Path(source)
    if not source.exists():
        raise DatabaseError("Yedek dosyasi bulunamadi.", detail=str(source))

    settings = get_settings()
    target = _sqlite_path_from_url(settings.database.resolved_url())
    if target is None:
        raise DatabaseError(
            "Otomatik geri yukleme yalnizca SQLite icin desteklenir.",
            context={"cozum": "PostgreSQL icin 'pg_restore' kullanin."},
        )

    # Yedegin gercekten okunabilir bir SQLite veritabani oldugunu dogrula.
    try:
        check = sqlite3.connect(str(source))
        try:
            check.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            check.close()
    except sqlite3.Error as exc:
        raise DatabaseError(
            "Yedek dosyasi gecerli bir veritabani degil.",
            detail=str(exc),
            context={"cozum": "Baska bir yedek deneyin."},
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        safety = target.with_suffix(target.suffix + ".pre-restore")
        shutil.copy2(target, safety)
        log.warning("geri_yukleme_oncesi_kopya", path=str(safety))

    # WAL yan dosyalari eski veritabanina aittir; birakilirsa yeni dosyayla
    # tutarsiz olur ve veritabani bozuk gorunur.
    for suffix in ("-wal", "-shm"):
        side = Path(str(target) + suffix)
        if side.exists():
            side.unlink()

    shutil.copy2(source, target)
    log.warning("yedek_geri_yuklendi", source=str(source), target=str(target))
    return target


__all__ = [
    "BackupResult",
    "create_backup",
    "list_backups",
    "prune_backups",
    "restore_backup",
]
