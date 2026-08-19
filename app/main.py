"""Masaustu uygulamasinin giris noktasi.

Baslatma sirasi
---------------
1. Loglama kurulur (mumkun olan en erken an - sonraki adimlarin hatalari
   da kayda gecsin)
2. Yazilabilir klasorler olusturulur
3. Veritabani hazir mi kontrol edilir; degilse kullaniciya ne yapacagi
   ACIKCA soylenir (sessizce cokmez)
4. Tema uygulanir
5. Giris ekrani gosterilir
6. Ana pencere acilir

Beklenmeyen hatalar icin genel bir yakalayici kurulur: uygulama sessizce
kapanmak yerine kullaniciya anlasilir bir mesaj gosterir ve ayrintiyi loga
yazar.
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType

from app.core import paths


def _write_startup_error(title: str, message: str, hint: str | None = None) -> None:
    """Baslatma hatasini dosyaya yazar.

    Neden gerekli: paketlenmis uygulama ``console=False`` ile calisir ve
    stderr hicbir yere gitmez. Loglama daha kurulmamis olabilecegi icin
    normal log dosyasi da bos kalir. Bu dosya, kullanicinin bize
    gonderebilecegi tek kanittir.
    """
    try:
        path = paths.DATA_ROOT / "startup_error.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{'=' * 60}\n")
            handle.write(f"{title}\n{message}\n")
            if hint:
                handle.write(f"{hint}\n")
            handle.write(f"frozen={paths.IS_FROZEN} data_root={paths.DATA_ROOT}\n")
            handle.write(f"executable={sys.executable}\n")
            handle.write(f"sys.path[0:3]={sys.path[:3]}\n")
            handle.write(f"{'=' * 60}\n")
    except Exception:  # noqa: S110 - bilincli sessiz yutma
        # Bu fonksiyon zaten bir olumlu hatayi kaydetmeye calisiyor.
        # Yazma da basarisiz olursa (salt okunur klasor, disk dolu) yapacak
        # bir sey yok; burada hata firlatmak asil hata mesajinin kullaniciya
        # gosterilmesini de engellerdi. Loglama henuz kurulmamis olabilecegi
        # icin log da yazilamaz.
        pass


def _fatal(title: str, message: str, hint: str | None = None) -> int:
    """Arayuz acilamadan olusan olumcul hatayi gosterir."""
    _write_startup_error(title, message, hint)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        if hint:
            box.setInformativeText(hint)
        box.exec()
        del app
    except Exception:
        print(f"\n[HATA] {title}\n{message}", file=sys.stderr)
        if hint:
            print(f"\n{hint}", file=sys.stderr)
    return 1


def _install_exception_hook() -> None:
    """Yakalanmamis hatalari loga yazan ve kullaniciya gosteren kanca."""
    from app.core.log import get_logger

    log = get_logger("app.main")

    def handler(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        log.error(
            "yakalanmamis_hata",
            error_type=exc_type.__name__,
            error=str(exc_value),
            traceback="".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                box = QMessageBox()
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("Beklenmeyen hata")
                box.setText(
                    "Uygulamada beklenmeyen bir hata olustu.\n"
                    "Islem tamamlanamadi, ancak uygulama calismaya devam ediyor."
                )
                box.setInformativeText(f"Ayrinti loglara yazildi:\n{paths.LOG_DIR / 'error.log'}")
                box.exec()
        except Exception:  # pragma: no cover
            # Asil hata yukarida zaten loglandi. Kutu gosterilemezse (Qt henuz
            # kurulmamis, ekran yok, ya da cikis sirasinda olay dongusu kapali)
            # burada yeniden firlatmak excepthook'u bozar ve kullanici hicbir
            # kayit goremez. Bu yuzden yalnizca debug seviyesinde not dusuluyor.
            log.debug("hata_kutusu_gosterilemedi", exc_info=True)

    sys.excepthook = handler


def _check_database_ready() -> str | None:
    """Veritabani kullanima hazir mi? Degilse Turkce aciklama dondurur.

    Donen metin, ilk kurulum sihirbazinin tetiklenmesi icin kullanilir;
    kullaniciya dogrudan gosterilmez (sihirbaz kendi metnini gosterir).
    """
    try:
        from sqlalchemy import inspect

        from app.infrastructure.db.session import get_engine

        inspector = inspect(get_engine())
        tables = set(inspector.get_table_names())
    except Exception as exc:
        return f"Veritabanina baglanilamadi.\n\nTeknik ayrinti: {exc}"

    if "alembic_version" not in tables:
        return "Veritabani henuz hazirlanmamis."
    if "user" not in tables:
        return "Veritabani semasi eksik gorunuyor."
    return None


def _self_test() -> int:
    """Paketlenmis uygulamayi arayuz olmadan sinar.

    ``AkilliKonaklama.exe --self-test`` ile calistirilir. Neden gerekli:
    pencereli uygulamada konsol yoktur ve ilk kurulum akisi ancak dugmeye
    basilarak tetiklenir; paketleme hatalari (eksik gizli import gibi)
    yalnizca son kullanicinin karsisina cikar. Bu bayrak, kurulum akisinin
    tamamini calistirip sonucu ``selftest.log`` dosyasina yazar.

    **Gecici bir klasorde calisir; mevcut veritabanina DOKUNMAZ.**
    """
    import tempfile

    report: list[str] = []
    ok = True

    def check(name: str, action) -> None:
        nonlocal ok
        try:
            detail = action()
            report.append(f"[OK]   {name}" + (f" - {detail}" if detail else ""))
        except Exception as exc:
            ok = False
            report.append(f"[HATA] {name}: {type(exc).__name__}: {exc}")

    report.append(f"frozen={paths.IS_FROZEN}")
    report.append(f"data_root={paths.DATA_ROOT}")
    report.append(f"resource_root={paths.RESOURCE_ROOT}")
    report.append("")

    # Paketlemede en sik eksik kalan modüller
    for module_name in (
        "logging.config",
        "logging.handlers",
        "sqlalchemy.dialects.sqlite",
        "alembic.command",
        "alembic.config",
        "keyring.backends.Windows",
        "reportlab.pdfgen.canvas",
        "openpyxl",
        "PySide6.QtCharts",
    ):
        check(f"import {module_name}", lambda m=module_name: __import__(m) and "")

    # Alembic goc betikleri pakete girdi mi?
    check(
        "alembic betikleri",
        lambda: f"{len(list((paths.RESOURCE_ROOT / 'alembic' / 'versions').glob('*.py')))} goc dosyasi",
    )

    # Ilk kurulum akisinin tamami - GECICI klasorde
    def run_setup() -> str:
        import os
        from pathlib import Path

        temp_root = Path(tempfile.mkdtemp(prefix="hotel_selftest_"))
        # NOT: paths.DATA_ROOT modul yuklenirken bir kez hesaplanir; burada
        # HOTEL_DATA_ROOT'u degistirmek onu ETKILEMEZ. Bu yuzden gecici
        # veritabaninin klasorunu elle olusturuyoruz - aksi halde SQLite
        # "unable to open database file" verir.
        (temp_root / "data").mkdir(parents=True, exist_ok=True)

        os.environ["HOTEL_DATA_ROOT"] = str(temp_root)
        os.environ["HOTEL_DB_URL"] = f"sqlite:///{(temp_root / 'data' / 'hotel.db').as_posix()}"

        from app.core.config import reload_settings

        reload_settings()

        from app.ui.first_run import _SetupWorker

        result = _SetupWorker(with_demo=False)._setup()
        if not result.success:
            raise RuntimeError(result.message)
        return f"yonetici={result.admin_username}, parola {len(result.admin_password)} karakter"

    check("ilk kurulum akisi", run_setup)

    report.append("")
    report.append("SONUC: " + ("BASARILI" if ok else "BASARISIZ"))

    try:
        (paths.DATA_ROOT / "selftest.log").write_text("\n".join(report), encoding="utf-8")
    except OSError:
        pass

    print("\n".join(report))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """Uygulamayi baslatir. Cikis kodunu dondurur."""
    argv = list(argv if argv is not None else sys.argv)

    if "--self-test" in argv:
        return _self_test()

    # --- 1) Loglama ---
    try:
        from app.core.log import setup_logging

        setup_logging()
    except Exception as exc:
        return _fatal(
            "Baslatma hatasi",
            "Loglama kurulamadi.",
            f"Teknik ayrinti: {type(exc).__name__}: {exc}\n" + "".join(traceback.format_exc()),
        )

    from app.core.config import get_settings
    from app.core.log import get_logger

    log = get_logger("app.main")

    # --- 2) Klasorler ---
    paths.ensure_writable_dirs()

    settings = get_settings()
    log.info(
        "uygulama_baslatiliyor",
        env=settings.env.value,
        data_root=str(paths.DATA_ROOT),
        frozen=paths.IS_FROZEN,
    )
    for warning in settings.startup_warnings():
        log.warning("yapilandirma_uyarisi", uyari=warning)

    # --- 3) Qt uygulamasi ve tema ---
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from app import __app_name__, __version__
    from app.ui.i18n import set_language
    from app.ui.theme import apply_theme

    QApplication.setApplicationName(__app_name__)
    QApplication.setApplicationVersion(__version__)
    QApplication.setOrganizationName("Akilli Konaklama")

    app = QApplication(argv)

    icon_path = paths.ASSETS_DIR / "icons" / "app.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    set_language(settings.language)
    # apply_theme hem stil sayfasini uygular hem aktif paleti kaydeder;
    # QtCharts gibi stil sayfasindan etkilenmeyen bilesenler paleti oradan okur.
    apply_theme(app, settings.theme)

    _install_exception_hook()

    # --- 4) Veritabani hazir mi? Degilse ilk kurulum sihirbazi ---
    #
    # Kaynak koddan calistiran gelistirici setup.ps1 kullanir; ancak
    # paketlenmis .exe'yi cift tiklayan kullanicida o betik YOKTUR.
    # "setup.ps1 calistirin" deyip kapanmak kullanilabilir bir urun degildir,
    # bu yuzden kurulumu uygulamanin kendisi yapar.
    problem = _check_database_ready()
    if problem:
        log.info("ilk_kurulum_gerekli", detail=problem.replace("\n", " "))

        from app.ui.first_run import FirstRunDialog

        wizard = FirstRunDialog()
        if wizard.exec() != FirstRunDialog.DialogCode.Accepted:
            log.info("ilk_kurulum_iptal_edildi")
            return 0

        # Kurulum sonrasi motor yeniden olusturulmali: sema artik farkli.
        from app.infrastructure.db.session import reset_engine

        reset_engine()

        remaining = _check_database_ready()
        if remaining:
            return _fatal("Kurulum tamamlanamadi", remaining)

    # --- 5) Giris ---
    from app.ui.login import ChangePasswordDialog, LoginDialog

    login = LoginDialog()
    if login.exec() != LoginDialog.DialogCode.Accepted:
        log.info("giris_iptal_edildi")
        return 0

    user = login.user
    token = login.session_token
    if user is None or token is None:  # pragma: no cover - savunma amacli
        return _fatal("Giris hatasi", "Oturum olusturulamadi.")

    # Zorunlu parola degisimi
    if user.must_change_password:
        dialog = ChangePasswordDialog(user, forced=True)
        if dialog.exec() != ChangePasswordDialog.DialogCode.Accepted:
            log.warning("zorunlu_parola_degisimi_reddedildi", username=user.username)
            return 0
        # Parola degisimi tum oturumlari kapattigi icin yeniden giris gerekir.
        login = LoginDialog()
        if login.exec() != LoginDialog.DialogCode.Accepted:
            return 0
        user = login.user
        token = login.session_token
        if user is None or token is None:  # pragma: no cover
            return 0

    # --- 6) Ana pencere ---
    from app.ui.main_window import MainWindow

    window = MainWindow(user=user, session_token=token)
    window.show()

    log.info("arayuz_acildi", username=user.username, roles=user.role_names)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
