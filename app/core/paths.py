"""Uygulama dosya yollarinin tek dogruluk kaynagi.

Neden ayri bir modul?
---------------------
Uygulama iki farkli sekilde calisabilir:

1. **Kaynak koddan** (``python -m app.main``) - proje koku ``D:\\Hotel``
2. **PyInstaller ile paketlenmis .exe** - kod gecici bir klasore acilir,
   ama veritabani/log/yedek gibi *yazilabilir* veriler .exe'nin yaninda
   veya kullanicinin AppData klasorunde durmalidir.

Bu modul iki kavrami net biçimde ayirir:

* :data:`RESOURCE_ROOT` - salt okunur paket icerigi (ikon, ceviri, sablon)
* :data:`DATA_ROOT`     - yazilabilir veri (veritabani, log, yedek, yukleme)
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

#: PyInstaller ile paketlenmis calisiyor muyuz?
IS_FROZEN: bool = bool(getattr(sys, "frozen", False))


def _detect_resource_root() -> Path:
    """Salt okunur kaynaklarin bulundugu kok klasoru dondurur."""
    if IS_FROZEN:
        # PyInstaller onedir/onefile: kaynaklar sys._MEIPASS altina acilir.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent
    # app/core/paths.py -> app/core -> app -> proje koku
    return Path(__file__).resolve().parents[2]


def _detect_data_root() -> Path:
    """Yazilabilir verilerin bulundugu kok klasoru dondurur.

    Oncelik sirasi:

    1. ``HOTEL_DATA_ROOT`` ortam degiskeni (test ve tasinabilir kurulum icin)
    2. Paketlenmis calisiyorsa .exe'nin yanindaki klasor (tasinabilir kurulum)
    3. Kaynak koddan calisiyorsa proje koku
    """
    override = os.environ.get("HOTEL_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if IS_FROZEN:
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


#: Salt okunur paket kaynaklari (ikon, ceviri dosyalari, rapor sablonlari).
RESOURCE_ROOT: Path = _detect_resource_root()

#: Yazilabilir veri koku. Veritabani, loglar ve yedekler buranin altindadir.
DATA_ROOT: Path = _detect_data_root()

#: Proje koku - AI Gelistirme Merkezi sandbox'i icin referans nokta.
PROJECT_ROOT: Path = DATA_ROOT

# --------------------------------------------------------------------------
#  Alt klasorler
# --------------------------------------------------------------------------
DATA_DIR: Path = DATA_ROOT / "data"
LOG_DIR: Path = DATA_ROOT / "logs"
BACKUP_DIR: Path = DATA_ROOT / "backups"
UPLOAD_DIR: Path = DATA_ROOT / "uploads"
EXPORT_DIR: Path = DATA_ROOT / "exports"
VECTORSTORE_DIR: Path = DATA_ROOT / "data" / "vectorstore"

I18N_DIR: Path = RESOURCE_ROOT / "app" / "ui" / "i18n"
ASSETS_DIR: Path = RESOURCE_ROOT / "app" / "ui" / "resources"
REPORT_TEMPLATE_DIR: Path = RESOURCE_ROOT / "app" / "reporting" / "templates"

#: Kaynak koddan calisirken .env dosyasinin beklendigi yer.
ENV_FILE: Path = DATA_ROOT / ".env"

#: Yazilabilir olmasi gereken klasorlerin tam listesi.
WRITABLE_DIRS: tuple[Path, ...] = (
    DATA_DIR,
    LOG_DIR,
    BACKUP_DIR,
    UPLOAD_DIR,
    EXPORT_DIR,
    VECTORSTORE_DIR,
)


@lru_cache(maxsize=1)
def ensure_writable_dirs() -> tuple[Path, ...]:
    """Yazilabilir klasorleri olusturur (varsa dokunmaz) ve listeler.

    Idempotent'tir; birden fazla cagrilmasi guvenlidir. ``lru_cache``
    sayesinde surec omru boyunca yalnizca bir kez disk erisimi yapilir.
    """
    for directory in WRITABLE_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
    return WRITABLE_DIRS


def resolve_data_path(*parts: str | os.PathLike[str]) -> Path:
    """:data:`DATA_ROOT` altinda guvenli bir yol cozer.

    Sonuç :data:`DATA_ROOT` disina cikarsa ``ValueError`` firlatir; boylece
    ``..\\..\\Windows\\System32`` gibi yol kacislari engellenir.
    """
    candidate = DATA_ROOT.joinpath(*[str(p) for p in parts]).resolve()
    root = DATA_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Yol veri kokunun disinda: {candidate}")
    return candidate


__all__ = [
    "ASSETS_DIR",
    "BACKUP_DIR",
    "DATA_DIR",
    "DATA_ROOT",
    "ENV_FILE",
    "EXPORT_DIR",
    "I18N_DIR",
    "IS_FROZEN",
    "LOG_DIR",
    "PROJECT_ROOT",
    "REPORT_TEMPLATE_DIR",
    "RESOURCE_ROOT",
    "UPLOAD_DIR",
    "VECTORSTORE_DIR",
    "WRITABLE_DIRS",
    "ensure_writable_dirs",
    "resolve_data_path",
]
