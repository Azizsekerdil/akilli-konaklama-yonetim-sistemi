"""Komut satiri arayuzu.

PowerShell betikleri (``scripts/*.ps1``) bu arayuzu kullanir; boylece is
mantigi betiklerde degil Python'da kalir ve test edilebilir olur.

Kullanim::

    python -m app.cli bootstrap        # izin/rol/yonetici kurulumu
    python -m app.cli seed-demo        # demo veri
    python -m app.cli backup           # veritabani yedegi
    python -m app.cli check-ai         # yapay zeka baglanti testi
    python -m app.cli doctor           # ortam teshisi
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app import __app_name__, __version__


def _print_header(title: str) -> None:
    print()
    print("=" * 56)
    print(f"  {title}")
    print("=" * 56)


# --------------------------------------------------------------------------
#  bootstrap
# --------------------------------------------------------------------------
def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Izinleri, rolleri ve yonetici hesabini kurar (idempotent)."""
    from app.infrastructure.db.session import session_scope
    from app.security.bootstrap import bootstrap_security

    _print_header("Guvenlik kurulumu")

    with session_scope() as session:
        result = bootstrap_security(
            session,
            create_admin=not args.no_admin,
            admin_username=args.admin_username,
            admin_password=args.admin_password,
        )

    print(
        f"  Izin  : {result.permissions_created} eklendi, {result.permissions_updated} guncellendi"
    )
    print(f"  Rol   : {result.roles_created} eklendi, {result.roles_updated} guncellendi")

    if result.admin_created and result.generated_password:
        print()
        print("  " + "-" * 52)
        print("  YONETICI HESABI OLUSTURULDU")
        print("  " + "-" * 52)
        print(f"  Kullanici adi : {result.admin_username}")
        print(f"  Parola        : {result.generated_password}")
        print()
        print("  BU PAROLA BIR DAHA GOSTERILMEYECEK.")
        print("  Hemen kaydedin ve ilk giriste degistirin.")
        print("  " + "-" * 52)
    elif result.admin_username:
        print(f"  Yonetici: '{result.admin_username}' zaten mevcut (degistirilmedi)")

    print()
    return 0


# --------------------------------------------------------------------------
#  seed-demo
# --------------------------------------------------------------------------
def cmd_seed_demo(args: argparse.Namespace) -> int:
    """Demo veri olusturur."""
    _print_header("Demo veri olusturuluyor")

    try:
        from app.infrastructure.seed.demo_data import create_demo_data
    except ImportError as exc:
        print(f"  [HATA] Demo veri modulu yuklenemedi: {exc}", file=sys.stderr)
        return 1

    from app.infrastructure.db.session import session_scope

    print("  Tum veriler hayalidir; gercek kisi bilgisi icermez.")
    print()

    with session_scope() as session:
        summary = create_demo_data(session, seed=args.seed, scale=args.scale)

    for line in str(summary).splitlines():
        print(f"  {line}")
    print()
    return 0


# --------------------------------------------------------------------------
#  backup / restore
# --------------------------------------------------------------------------
def cmd_backup(args: argparse.Namespace) -> int:
    """Veritabani yedegi alir."""
    from app.core.exceptions import HotelError
    from app.infrastructure.backup import create_backup

    _print_header("Veritabani yedegi")

    try:
        result = create_backup(keep=args.keep)
    except HotelError as exc:
        print(f"  [HATA] {exc.user_message}", file=sys.stderr)
        if exc.context.get("cozum"):
            print(f"  Cozum: {exc.context['cozum']}", file=sys.stderr)
        return 1

    print(f"  Dosya  : {result.path}")
    print(f"  Boyut  : {result.size_mb} MB")
    if result.removed_old:
        print(f"  Temizlik: {result.removed_old} eski yedek silindi")
    print()
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Yedegi geri yukler."""
    from pathlib import Path

    from app.core.exceptions import HotelError
    from app.infrastructure.backup import restore_backup

    _print_header("Yedekten geri yukleme")

    if not args.confirm:
        print("  [HATA] Bu islem --confirm gerektirir.", file=sys.stderr)
        return 1

    try:
        target = restore_backup(Path(args.source), confirm=True)
    except HotelError as exc:
        print(f"  [HATA] {exc.user_message}", file=sys.stderr)
        if exc.context.get("cozum"):
            print(f"  Cozum: {exc.context['cozum']}", file=sys.stderr)
        return 1

    print(f"  Geri yuklendi: {target}")
    print("  Onceki veritabani '.pre-restore' uzantisiyla saklandi.")
    print()
    return 0


def cmd_list_backups(args: argparse.Namespace) -> int:
    """Mevcut yedekleri listeler."""
    from app.infrastructure.backup import list_backups

    _print_header("Yedekler")
    backups = list_backups()
    if not backups:
        print("  Yedek bulunamadi.")
        print()
        return 0

    for path in backups:
        stat = path.stat()
        size_mb = round(stat.st_size / (1024 * 1024), 2)
        print(f"  {path.name:<32} {size_mb:>8} MB")
    print()
    return 0


# --------------------------------------------------------------------------
#  check-ai
# --------------------------------------------------------------------------
def cmd_check_ai(args: argparse.Namespace) -> int:
    """Yapay zeka saglayicilarina baglanti testi yapar."""
    _print_header("Yapay zeka baglanti testi")

    try:
        from app.ai.registry import ProviderRegistry
    except ImportError as exc:
        print(f"  [HATA] Yapay zeka modulu yuklenemedi: {exc}", file=sys.stderr)
        return 1

    registry = ProviderRegistry()
    any_ok = False

    for provider in registry.available_providers():
        print(f"  {provider.name}")
        status = provider.health_check()
        if status.ok:
            any_ok = True
            print(f"    Durum   : Calisiyor ({status.latency_ms} ms)")
            if status.models_found:
                print(f"    Modeller: {len(status.models_found)} adet")
                for model_id in status.models_found[:10]:
                    print(f"              - {model_id}")
        else:
            print("    Durum   : Ulasilamiyor")
            print(f"    Ayrinti : {status.message}")
        print()

    return 0 if any_ok else 1


# --------------------------------------------------------------------------
#  doctor
# --------------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    """Ortam teshisi - neyin eksik oldugunu gosterir."""
    from app.core import paths
    from app.core.config import get_settings
    from app.core.secret_store import is_keyring_available

    _print_header("Ortam teshisi")

    settings = get_settings()
    ok = True

    print(f"  Python           : {sys.version.split()[0]}")
    print(f"  Uygulama surumu  : {__version__}")
    print(f"  Ortam            : {settings.env.value}")
    print(f"  Veri koku        : {paths.DATA_ROOT}")
    print(f"  Paketlenmis mi   : {'evet' if paths.IS_FROZEN else 'hayir'}")
    print()

    # .env
    env_exists = paths.ENV_FILE.exists()
    print(f"  .env dosyasi     : {'var' if env_exists else 'YOK'}")
    if not env_exists:
        print("      -> .\\scripts\\setup.ps1 calistirin")

    # Oturum anahtari
    if settings.security.uses_default_secret:
        print("  HOTEL_SECRET_KEY : VARSAYILAN (guvensiz)")
        if settings.is_production:
            ok = False
            print("      -> URETIMDE MUTLAKA DEGISTIRIN")
    else:
        print("  HOTEL_SECRET_KEY : ozellestirilmis")

    # keyring
    keyring_ok = is_keyring_available()
    print(f"  Anahtar deposu   : {'kullanilabilir' if keyring_ok else 'YOK (.env kullanilacak)'}")

    # Veritabani
    try:
        from sqlalchemy import inspect

        from app.infrastructure.db.session import get_engine

        engine = get_engine()
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"  Veritabani       : {engine.dialect.name}, {len(tables)} tablo")
        if "alembic_version" not in tables:
            ok = False
            print("      -> Gocler uygulanmamis: alembic upgrade head")
    except Exception as exc:
        ok = False
        print(f"  Veritabani       : HATA - {exc}")

    # Yapay zeka
    print(f"  Yapay zeka       : {'acik' if settings.ai.enabled else 'kapali'}")
    if settings.ai.enabled:
        print(f"      Birincil     : {settings.ai.primary_provider.value}")
        print(f"      LM Studio    : {settings.ai.lmstudio.base_url}")

    # Uyarilar
    warnings = settings.startup_warnings()
    if warnings:
        print()
        print("  UYARILAR:")
        for warning in warnings:
            print(f"    - {warning}")

    print()
    return 0 if ok else 1


# --------------------------------------------------------------------------
#  Argumanlar
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hotel",
        description=f"{__app_name__} - komut satiri araclari",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # bootstrap
    p = sub.add_parser("bootstrap", help="Izin, rol ve yonetici hesabini kurar")
    p.add_argument("--admin-username", default="admin")
    p.add_argument("--admin-password", default=None, help="Belirtilmezse guvenli parola uretilir")
    p.add_argument("--no-admin", action="store_true", help="Yonetici hesabi olusturma")
    p.set_defaults(func=cmd_bootstrap)

    # seed-demo
    p = sub.add_parser("seed-demo", help="Demo veri olusturur (hayali)")
    p.add_argument("--seed", type=int, default=42, help="Belirlenimcilik icin tohum degeri")
    p.add_argument("--scale", default="medium", choices=["small", "medium", "large"])
    p.set_defaults(func=cmd_seed_demo)

    # backup
    p = sub.add_parser("backup", help="Veritabani yedegi alir")
    p.add_argument("--keep", type=int, default=None, help="Saklanacak yedek sayisi")
    p.set_defaults(func=cmd_backup)

    # restore
    p = sub.add_parser("restore", help="Yedekten geri yukler (UZERINE YAZAR)")
    p.add_argument("--source", required=True, help="Yedek dosyasinin yolu")
    p.add_argument("--confirm", action="store_true", help="Onay - zorunlu")
    p.set_defaults(func=cmd_restore)

    # list-backups
    p = sub.add_parser("list-backups", help="Yedekleri listeler")
    p.set_defaults(func=cmd_list_backups)

    # check-ai
    p = sub.add_parser("check-ai", help="Yapay zeka saglayicilarini test eder")
    p.set_defaults(func=cmd_check_ai)

    # doctor
    p = sub.add_parser("doctor", help="Ortam teshisi")
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI giris noktasi."""
    from app.core.log import setup_logging

    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging()

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\n  Iptal edildi.", file=sys.stderr)
        return 130
    except Exception as exc:
        from app.core.exceptions import HotelError
        from app.core.log import get_logger

        get_logger(__name__).error("cli_hatasi", command=args.command, exc_info=True)
        if isinstance(exc, HotelError):
            print(f"\n  [HATA] {exc.user_message}", file=sys.stderr)
        else:
            print(f"\n  [HATA] Beklenmeyen hata: {exc}", file=sys.stderr)
            print("  Ayrinti icin logs/error.log dosyasina bakin.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
