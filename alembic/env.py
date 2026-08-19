"""Alembic calisma ortami.

Iki onemli ayar
---------------
1. **Baglanti adresi koda gomulu degildir.** ``alembic.ini`` icindeki
   ``sqlalchemy.url`` bos birakilmistir; adres burada uygulama ayarlarindan
   (``HOTEL_DB_URL`` / ``.env``) okunur. Boylece gercek baglanti bilgisi
   depoya girmez.

2. **``render_as_batch=True``.** SQLite ``ALTER TABLE`` islemlerinin cogunu
   desteklemez. Batch kipi, Alembic'in tabloyu yeniden olusturup veriyi
   kopyalamasini saglar; bu da sutun degistirme/silme gocleri icin sarttir.
   Isimlendirme kurallari :mod:`app.infrastructure.db.base` icinde tanimlidir
   ve batch kipinin dogru calismasi icin gereklidir.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, event, pool

from alembic import context

# Proje kokunu import yoluna ekle (alembic kendi dizininden calisir).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.infrastructure.db import models  # noqa: E402,F401  (metadata'yi doldurur)
from app.infrastructure.db.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#: ``--autogenerate`` bu metadata'yi hedef sema olarak kullanir.
target_metadata = Base.metadata

# Baglanti adresini uygulama ayarlarindan al.
config.set_main_option("sqlalchemy.url", get_settings().database.resolved_url())


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Bazi nesneleri goc karsilastirmasindan disla.

    SQLite'in dahili ``sqlite_sequence`` tablosu autogenerate'te "silinmis
    tablo" gibi gorunur; disliyoruz.
    """
    if type_ == "table" and name in {"sqlite_sequence", "alembic_version"}:
        return False
    return True


def render_item(type_, obj, autogen_context) -> str | bool:
    """Uygulamaya ozel sutun tiplerini gerekli import ile birlikte render eder.

    Varsayilan davranista ``EncryptedString`` goc dosyasina
    ``app.infrastructure.db.types.EncryptedString(...)`` olarak yazilir ama
    ilgili ``import`` satiri uretilmez; goc calistirildiginda
    ``NameError: name 'app' is not defined`` alinir. Burada modulu
    ``autogen_context.imports`` kumesine ekleyerek bunu onluyoruz.
    """
    if type_ == "type":
        module = type(obj).__module__
        if module.startswith("app."):
            autogen_context.imports.add(f"import {module}")
    return False  # False = Alembic varsayilan render'i kullansin


def run_migrations_offline() -> None:
    """Baglanti acmadan SQL betigi uretir (``alembic upgrade --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    """Her yeni SQLite baglantisinda yabanci anahtar kisitlarini acar.

    PRAGMA'yi ``connection.exec_driver_sql(...)`` ile calistirmak cazip
    gorunur ama SQLAlchemy 2.0'in "commit as you go" modelinde bu, ortulu
    bir islem (transaction) baslatir. Alembic daha sonra kendi islemini
    acamaz ve goc sonunda ``alembic_version`` damgasi **commit edilmez**:
    tablolar olusur ama ``alembic current`` bos doner. Baglanti olayina
    baglamak bu tuzagi tamamen ortadan kaldirir.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def run_migrations_online() -> None:
    """Canli baglanti uzerinden gocleri uygular."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    if connectable.dialect.name == "sqlite":
        event.listen(connectable, "connect", _enable_sqlite_foreign_keys)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite icin ZORUNLU
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
