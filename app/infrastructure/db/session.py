"""Veritabani motoru ve oturum yonetimi.

Onemli ayrinti: **SQLite'ta yabanci anahtar kisitlari varsayilan olarak
kapalidir.** Acilmazsa, silinen bir odaya bagli rezervasyonlar sessizce
yetim kalir. Asagidaki ``PRAGMA foreign_keys=ON`` dinleyicisi bunu her
baglantida acar. Ayrica WAL kipi, masaustu uygulamasinda arayuz ile arka plan
gorevlerinin ayni anda okuma/yazma yapabilmesi icin acilir.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import DatabaseSettings, get_settings
from app.core.exceptions import DatabaseError
from app.core.log import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
    """Her yeni SQLite baglantisinda guvenlik ve performans PRAGMA'larini uygular."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        # Yabanci anahtar kisitlarini ac - veri butunlugu icin ZORUNLU.
        cursor.execute("PRAGMA foreign_keys=ON")
        # Write-Ahead Logging: okuyucular yazicilari engellemez.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Dayaniklilik/hiz dengesi; WAL ile birlikte guvenli kabul edilir.
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Kilitli veritabaninda 5 sn bekle (arayuz + arka plan gorevi cakismasi).
        cursor.execute("PRAGMA busy_timeout=5000")
        # Gecici tablolari bellekte tut.
        cursor.execute("PRAGMA temp_store=MEMORY")
    finally:
        cursor.close()


def create_engine_from_settings(
    settings: DatabaseSettings | None = None,
    *,
    url_override: str | None = None,
) -> Engine:
    """Ayarlardan bir SQLAlchemy motoru olusturur.

    Parameters
    ----------
    settings:
        Kullanilacak veritabani ayarlari. ``None`` ise uygulama ayarlari.
    url_override:
        Testlerde ``sqlite:///:memory:`` gibi bir adresi zorlamak icin.
    """
    db_settings = settings or get_settings().database
    url = url_override or db_settings.resolved_url()

    kwargs: dict[str, Any] = {
        "echo": db_settings.echo,
        "future": True,
        "pool_pre_ping": True,
    }

    if url.startswith("sqlite"):
        # SQLite + PySide6: arayuz is parcacigi disindan da erisim olabilir.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # Bellek ici veritabaninin testler boyunca ayni kalmasi icin
            # tek baglantili havuz kullanilir.
            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update(
            pool_size=db_settings.pool_size,
            max_overflow=db_settings.max_overflow,
            pool_timeout=db_settings.pool_timeout,
            pool_recycle=db_settings.pool_recycle,
        )

    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        event.listen(engine, "connect", _configure_sqlite)

    log.debug("db_engine_olusturuldu", dialect=engine.dialect.name)
    return engine


def get_engine() -> Engine:
    """Uygulama genelindeki tekil motoru dondurur (gerekirse olusturur)."""
    global _engine
    if _engine is None:
        _engine = create_engine_from_settings()
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    """Uygulama genelindeki tekil oturum fabrikasini dondurur."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,  # commit sonrasi nesneler kullanilabilir kalsin
            future=True,
        )
    return _sessionmaker


def get_session() -> Session:
    """Yeni bir oturum dondurur. Kapatmak cagiranin sorumlulugundadir.

    Cogu durumda :func:`session_scope` tercih edilmelidir.
    """
    return get_sessionmaker()()


@contextmanager
def session_scope(*, commit: bool = True) -> Iterator[Session]:
    """Islem (transaction) sinirlarini yoneten baglam yoneticisi.

    Basarili cikista ``commit``, hata durumunda ``rollback`` yapar ve oturumu
    her hâlükârda kapatir::

        with session_scope() as session:
            session.add(reservation)
            # cikista otomatik commit

    Parameters
    ----------
    commit:
        ``False`` ise yalnizca okuma yapilir; cikista commit denenmez.
    """
    session = get_session()
    try:
        yield session
        if commit:
            session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        log.error("db_islem_hatasi", error=str(exc), exc_info=True)
        raise DatabaseError(
            detail=str(exc),
            context={"error_type": type(exc).__name__},
        ) from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def fastapi_session() -> Generator[Session, None, None]:
    """FastAPI ``Depends`` bagimliligi olarak kullanilacak oturum saglayici."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Motoru ve oturum fabrikasini sifirlar.

    Ayarlar degistiginde (or. SQLite'tan PostgreSQL'e gecis) veya testler
    arasinda temiz baslangic icin kullanilir.
    """
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None


def set_engine(engine: Engine) -> None:
    """Motoru disaridan enjekte eder - testlerde bellek ici veritabani icin."""
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


__all__ = [
    "create_engine_from_settings",
    "fastapi_session",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "reset_engine",
    "session_scope",
    "set_engine",
]
