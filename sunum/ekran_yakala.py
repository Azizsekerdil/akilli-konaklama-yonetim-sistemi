"""Sunum icin uygulama ekran goruntulerini uretir.

Ne yapar?
---------
1. GECICI bir klasorde sifirdan demo veritabani kurar (mevcut veriye DOKUNMAZ).
2. Yonetici hesabiyla programatik giris yapar.
3. Giris ekranini ve ana penceredeki her sayfayi acip PNG olarak
   ``sunum/ekranlar/`` klasorune kaydeder.

Calistirma::

    .\\.venv\\Scripts\\python.exe sunum\\ekran_yakala.py

Goruntuler ``sunum_uret.py`` tarafindan sunuma gomulur; bu betik yeniden
calistirilmadan sunumdaki goruntuler degismez.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EKRAN_DIR = Path(__file__).resolve().parent / "ekranlar"

# Uygulama modulleri import edilmeden ONCE gecici ortam kurulmali:
# paths.DATA_ROOT modul yuklenirken bir kez hesaplanir.
_temp_root = Path(tempfile.mkdtemp(prefix="hotel_sunum_"))
(_temp_root / "data").mkdir(parents=True, exist_ok=True)
os.environ["HOTEL_DATA_ROOT"] = str(_temp_root)
os.environ["HOTEL_DB_URL"] = f"sqlite:///{(_temp_root / 'data' / 'hotel.db').as_posix()}"

sys.path.insert(0, str(ROOT))

PENCERE_BOYUTU = (1600, 900)  # 16:9 - slayt oraniyla ayni


def _bekle(app, ms: int = 300) -> None:
    """Olay dongusunu kisa sure isletir (grafiklerin cizilmesi icin)."""
    from PySide6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)


def main() -> int:
    from app.core.config import get_settings, reload_settings

    reload_settings()

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    settings = get_settings()

    from app.ui.i18n import set_language
    from app.ui.theme import apply_theme

    set_language(settings.language)
    apply_theme(app, settings.theme)

    # --- 1) Gecici demo kurulum ---
    print(f"[1/4] Demo veritabani kuruluyor... ({_temp_root})")
    from app.ui.first_run import _SetupWorker

    result = _SetupWorker(with_demo=True)._setup()
    if not result.success:
        print(f"HATA: kurulum basarisiz: {result.message}")
        return 1
    if not result.demo_created:
        print(f"UYARI: demo veri olusturulamadi: {result.message}")
    print(f"       yonetici={result.admin_username}")

    # --- 2) Programatik giris ---
    print("[2/4] Giris yapiliyor...")
    from app.infrastructure.db.session import session_scope
    from app.security import auth

    with session_scope(commit=False) as session:
        auth_result = auth.authenticate(session, result.admin_username, result.admin_password)
    user = auth_result.user
    token = auth_result.token

    EKRAN_DIR.mkdir(parents=True, exist_ok=True)

    # --- 3) Giris ekrani goruntusu ---
    print("[3/4] Giris ekrani yakalaniyor...")
    from app.ui.login import LoginDialog

    login = LoginDialog()
    login.username_input.setText(result.admin_username)
    login.show()
    _bekle(app, 400)
    login.grab().save(str(EKRAN_DIR / "00_giris.png"))
    login.hide()
    login.deleteLater()

    # --- 4) Ana pencere sayfalari ---
    print("[4/4] Sayfalar yakalaniyor...")
    from app.ui.main_window import MainWindow

    window = MainWindow(user=user, session_token=token)
    window.resize(*PENCERE_BOYUTU)
    window.show()
    _bekle(app, 800)

    kaydedilen: list[str] = []
    for index, key in enumerate(window._pages, start=1):
        window._show_page(key)
        _bekle(app, 900)  # veriler + grafikler cizilsin
        dosya = EKRAN_DIR / f"{index:02d}_{key}.png"
        window.grab().save(str(dosya))
        kaydedilen.append(dosya.name)
        print(f"       {dosya.name}")

    window.close()

    print(f"\nToplam {len(kaydedilen) + 1} goruntu: {EKRAN_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
