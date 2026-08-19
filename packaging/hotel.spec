# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapilandirmasi.

Neden bu ayarlar?
-----------------
* **onedir varsayilan**: "onefile" her calistirmada gecici klasore acilir;
  bu hem baslangici yavaslatir hem bazi kurumsal antiviruslerin uygulamayi
  karantinaya almasina yol acar. Tek dosya isteniyorsa build.ps1 -OneFile.
* **Yazilabilir veriler .exe'nin yaninda**: veritabani, log ve yedekler
  gecici klasorde degil, uygulamanin yaninda tutulur (bkz. app/core/paths.py).
  Boylece uygulama tasinabilir kalir ve guncelleme veriyi silmez.
* **Alembic goc dosyalari veriye dahil edilir**: aksi halde paketlenmis
  uygulama veritabani semasini kuramaz.
* **Gereksiz buyuk modüller dislanir**: PySide6 tum Qt modullerini
  toplamaya calisir; kullanmadiklarimiz paketi ~150 MB sisirir.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = Path(SPECPATH).parent  # noqa: F821 - PyInstaller saglar
ONEFILE = os.environ.get("HOTEL_BUILD_ONEFILE", "0") == "1"

APP_NAME = "AkilliKonaklama"
ICON_PATH = PROJECT_ROOT / "app" / "ui" / "resources" / "icons" / "app.ico"

# --------------------------------------------------------------------------
#  Veri dosyalari
# --------------------------------------------------------------------------
# Lisans / bildirim dosyalari - DAGITIM YUKUMLULUGU (bulgu HTL-H4)
#
# Bagimsiz yayin oncesi denetimde uretilen paketin ne projenin kendi MIT
# metnini ne de dinamik olarak baglanan Qt kutuphanelerinin gerektirdigi
# LGPL-3.0 metnini icermedigi tespit edildi: iki ayri yukumluluk ayni anda
# karsilanmiyordu. Biri kendi lisansimizin sarti (telif bildirimi tum
# kopyalarda), digeri THIRD_PARTY_NOTICES.md §5.1'de yazili LGPL sarti.
#
# Cozum iki parcadir: (1) dosyalar pakete VERI olarak eklenir, (2) asagidaki
# dogrulama eksiklik halinde paketlemeyi BASLAMADAN durdurur. Yalnizca (1)
# yapilsaydi dosyalardan biri silindiginde hata sessizce geri gelirdi.
REQUIRED_LICENSE_FILES = [
    (PROJECT_ROOT / "LICENSE", "."),
    (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md", "."),
    (PROJECT_ROOT / "packaging" / "licenses" / "GPL-3.0.txt", "licenses"),
    (PROJECT_ROOT / "packaging" / "licenses" / "LGPL-3.0.txt", "licenses"),
]

_missing = [str(p) for p, _dest in REQUIRED_LICENSE_FILES if not p.exists()]
if _missing:
    raise SystemExit(
        "PAKETLEME DURDURULDU - zorunlu lisans dosyalari eksik:\n  "
        + "\n  ".join(_missing)
        + "\n\nBu dosyalar bir dagitim YUKUMLULUGUDUR (MIT telif bildirimi + "
        "Qt/PySide6 icin LGPL-3.0 metni). LGPL-3.0.txt birebir metin olmalidir; "
        "nasil temin edilecegi packaging/licenses/README.md dosyasinda yazilidir.\n"
        "Eksik dosyayi ekleyin ve derlemeyi tekrar calistirin."
    )

datas = [
    # Alembic goc altyapisi - paketlenmis uygulamada da sema kurulabilmeli
    (str(PROJECT_ROOT / "alembic"), "alembic"),
    (str(PROJECT_ROOT / "alembic.ini"), "."),
    # Ornek ortam dosyasi - ilk calistirmada .env uretmek icin
    (str(PROJECT_ROOT / ".env.example"), "."),
    # Lisans ve ucuncu parti bildirimleri (yukaridaki dogrulamadan gecti)
    *[(str(p), dest) for p, dest in REQUIRED_LICENSE_FILES],
]

# Arayuz kaynaklari (ikon, ceviri) varsa eklenir
resources = PROJECT_ROOT / "app" / "ui" / "resources"
if resources.exists():
    datas.append((str(resources), "app/ui/resources"))

i18n = PROJECT_ROOT / "app" / "ui" / "i18n"
if i18n.exists():
    datas.append((str(i18n), "app/ui/i18n"))

# --------------------------------------------------------------------------
#  Gizli import'lar
# --------------------------------------------------------------------------
# PyInstaller dinamik import'lari goremez. Su modüller calisma aninda
# yuklenir ve acikca belirtilmeleri gerekir:
hiddenimports = [
    # Sayfa modulleri registry.py icinde importlib ile tembel yuklenir
    *collect_submodules("app.ui.pages"),
    *collect_submodules("app.ui.dialogs"),
    # Alembic goc dosyalari calisma aninda yuklenir
    *collect_submodules("alembic"),
    # ---- Standart kutuphane alt modulleri ----
    # DIKKAT: alembic/env.py ve goc dosyalari pakete VERI olarak girer;
    # PyInstaller onlarin icindeki import satirlarini goremez. env.py
    # "from logging.config import fileConfig" yapar ve bu alt modul
    # baska hicbir yerden statik olarak import edilmediginden pakete
    # girmez. Sonuc: ilk kurulum sirasinda
    # "No module named 'logging.config'" hatasi.
    "logging.config",
    "logging.handlers",
    # SQLAlchemy lehceleri
    "sqlalchemy.dialects.sqlite",
    # keyring arka uclari (Windows Credential Manager)
    "keyring.backends.Windows",
    "win32timezone",
    # Rapor uretimi
    "reportlab.graphics.barcode",
]

# --------------------------------------------------------------------------
#  Dislanacaklar
# --------------------------------------------------------------------------
excludes = [
    # Kullanilmayan Qt modulleri - paketi onemli olcude kucultur
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia",
    "PySide6.Qt3DCore",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    # Gelistirme araclari uretim paketine girmez
    "pytest",
    "black",
    "ruff",
    "mypy",
    "bandit",
    "pip_audit",
    "IPython",
    "jupyter",
    "matplotlib",
    "tkinter",
]

block_cipher = None

a = Analysis(  # noqa: F821
    [str(PROJECT_ROOT / "app" / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe_kwargs = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX bazi antivirusleri tetikler; sikistirma degmez
    console=False,  # masaustu uygulamasi - konsol penceresi acilmaz
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)

if ONEFILE:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        runtime_tmpdir=None,
        **exe_kwargs,
    )
else:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **exe_kwargs,
    )
    coll = COLLECT(  # noqa: F821
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
