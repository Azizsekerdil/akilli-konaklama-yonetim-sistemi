"""Ortak test fikstürleri.

Tasarim ilkeleri
----------------
* Testler **gercek uygulama veritabanina dokunmaz**. Her test bellek ici
  yeni bir SQLite uzerinde calisir ve bittiginde yok olur.
* Anahtar deposu (keyring) testlerde devre disi birakilir; boylece testler
  gelistiricinin Windows Credential Manager'ina yazmaz.
* Argon2 maliyeti testlerde dusurulur; aksi halde her parola hash'i ~80 ms
  surer ve test paketi gereksiz yere yavaslar.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from datetime import date, time
from decimal import Decimal

import pytest

#: Sabit test sifreleme anahtari.
#: Fernet, **tam 32 bayt**tan uretilmis urlsafe-base64 bir anahtar bekler;
#: rastgele bir metin verilirse ``ValueError: Fernet key must be 32 url-safe
#: base64-encoded bytes`` alinir. Asagidaki metin tam 32 bayttir.
TEST_ENCRYPTION_KEY = base64.urlsafe_b64encode(b"hotel-test-key-32-bytes-exactly!").decode()

# --- Testler icin ortam degiskenleri (import'lardan ONCE ayarlanmalidir) ---
os.environ.setdefault("HOTEL_APP_ENV", "testing")
os.environ.setdefault("HOTEL_DB_URL", "sqlite:///:memory:")
os.environ.setdefault("HOTEL_LOG_LEVEL", "WARNING")
os.environ.setdefault("HOTEL_AI_ENABLED", "false")
os.environ.setdefault("HOTEL_ARGON2_TIME_COST", "1")
os.environ.setdefault("HOTEL_ARGON2_MEMORY_COST", "8192")
os.environ.setdefault("HOTEL_FIELD_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import reload_settings  # noqa: E402
from app.core.log import setup_logging  # noqa: E402
from app.domain.enums import (  # noqa: E402
    BedType,
    Currency,
    PropertyType,
    RoomHousekeepingStatus,
)
from app.infrastructure.db.base import Base  # noqa: E402
from app.infrastructure.db.models import (  # noqa: E402
    Building,
    Floor,
    Guest,
    Property,
    RatePlan,
    Room,
    RoomType,
    User,
)
from app.security.bootstrap import bootstrap_security  # noqa: E402
from app.security.passwords import reset_hasher_cache  # noqa: E402


# --------------------------------------------------------------------------
#  Oturum kapsamli hazirlik
# --------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _configure_test_environment() -> Iterator[None]:
    """Test oturumu boyunca gecerli yapilandirma."""
    reload_settings()
    reset_hasher_cache()
    setup_logging(level="WARNING", log_to_file=False, force=True)
    yield


@pytest.fixture(autouse=True)
def _disable_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Testlerin isletim sistemi anahtar deposuna yazmasini engeller.

    Alan sifreleme anahtari ``HOTEL_FIELD_ENCRYPTION_KEY`` ortam degiskeninden
    okunur; keyring cagrilari sessizce basarisiz olur.
    """
    import app.core.secret_store as secret_store

    monkeypatch.setattr(secret_store, "_keyring_module", lambda: None)

    # Fernet ornegi onbelleklendigi icin testler arasi sifirlanmalidir.
    import app.infrastructure.db.types as db_types

    db_types._get_fernet.cache_clear()
    monkeypatch.setenv("HOTEL_FIELD_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)


# --------------------------------------------------------------------------
#  Veritabani
# --------------------------------------------------------------------------
@pytest.fixture
def engine():
    """Her test icin temiz, bellek ici SQLite motoru."""
    from sqlalchemy.pool import StaticPool

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Yabanci anahtar kisitlari acilmazsa butunluk testleri yaniltici gecer.
    from sqlalchemy import event

    @event.listens_for(test_engine, "connect")
    def _fk_on(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    """Islem sinirlari yonetilen bir veritabani oturumu."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db_session = factory()
    try:
        yield db_session
    finally:
        db_session.rollback()
        db_session.close()


@pytest.fixture
def secured_session(session: Session) -> Session:
    """Izinleri, rolleri ve yonetici hesabini kurulmus oturum."""
    bootstrap_security(session, create_admin=True, admin_password="TestYonetici2026!")
    return session


# --------------------------------------------------------------------------
#  Ornek veri fabrikalari
# --------------------------------------------------------------------------
@pytest.fixture
def sample_property(session: Session) -> Property:
    """Tek bir test tesisi."""
    prop = Property(
        code="TEST01",
        name="Test Oteli",
        property_type=PropertyType.HOTEL,
        star_rating=4,
        city="Antalya",
        default_currency=Currency.TRY,
        check_in_time=time(14, 0),
        check_out_time=time(12, 0),
    )
    session.add(prop)
    session.commit()
    return prop


@pytest.fixture
def sample_room_type(session: Session, sample_property: Property) -> RoomType:
    """Standart oda tipi - 2 kisilik, 1000 TL taban fiyat."""
    room_type = RoomType(
        property_id=sample_property.id,
        code="STD",
        name="Standart Oda",
        base_occupancy=2,
        max_occupancy=3,
        max_adults=3,
        max_children=1,
        bed_type=BedType.DOUBLE,
        base_rate=Decimal("1000.00"),
        extra_adult_rate=Decimal("250.00"),
        extra_child_rate=Decimal("125.00"),
    )
    session.add(room_type)
    session.commit()
    return room_type


@pytest.fixture
def sample_rooms(
    session: Session, sample_property: Property, sample_room_type: RoomType
) -> list[Room]:
    """101, 102, 103 numarali uc temiz oda."""
    building = Building(property_id=sample_property.id, code="A", name="Ana Bina")
    session.add(building)
    session.flush()

    floor = Floor(building_id=building.id, number=1, name="1. Kat")
    session.add(floor)
    session.flush()

    rooms = [
        Room(
            property_id=sample_property.id,
            room_type_id=sample_room_type.id,
            floor_id=floor.id,
            number=number,
            housekeeping_status=RoomHousekeepingStatus.CLEAN,
        )
        for number in ("101", "102", "103")
    ]
    session.add_all(rooms)
    session.commit()
    return rooms


@pytest.fixture
def sample_guest(session: Session) -> Guest:
    """Tamamen hayali bir test misafiri.

    .. note::
       Tum test verileri uydurmadir. Gercek kisilere ait ad, kimlik numarasi,
       telefon veya e-posta **kullanilmaz**.
    """
    guest = Guest(
        first_name="Deniz",
        last_name="Yildizli",
        email="deniz.yildizli@ornek-test.local",
        phone="+90 5XX XXX XX 01",
        nationality="Turkiye",
    )
    guest.set_identity("11111111110")  # gecersiz bicimde, uydurma numara
    session.add(guest)
    session.commit()
    return guest


@pytest.fixture
def sample_rate_plan(session: Session, sample_property: Property) -> RatePlan:
    """Standart, iade edilebilir fiyat plani."""
    plan = RatePlan(
        property_id=sample_property.id,
        code="STD",
        name="Standart Tarife",
        min_nights=1,
        is_refundable=True,
        free_cancellation_hours=24,
        cancellation_fee_percent=Decimal("50.00"),
        no_show_fee_percent=Decimal("100.00"),
    )
    session.add(plan)
    session.commit()
    return plan


@pytest.fixture
def admin_user(secured_session: Session) -> User:
    """Tum yetkilere sahip yonetici."""
    from sqlalchemy import select

    return secured_session.scalars(select(User).where(User.username == "admin")).one()


@pytest.fixture
def frontdesk_user(secured_session: Session) -> User:
    """Yalnizca on buro yetkilerine sahip kullanici (finans yetkisi YOK)."""
    from sqlalchemy import select

    from app.infrastructure.db.models import Role
    from app.security.passwords import hash_password

    role = secured_session.scalars(select(Role).where(Role.code == "frontdesk")).one()
    user = User(
        username="resepsiyon",
        full_name="Test Resepsiyonist",
        password_hash=hash_password("ResepsiyonTest2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    secured_session.add(user)
    secured_session.commit()
    return user


# --------------------------------------------------------------------------
#  Yardimci sabitler
# --------------------------------------------------------------------------
@pytest.fixture
def today() -> date:
    """Testlerde referans alinan sabit tarih (belirlenimci sonuclar icin)."""
    return date(2026, 8, 10)


# --------------------------------------------------------------------------
#  Servis baglami (tum test paketlerinde kullanilir)
# --------------------------------------------------------------------------
@pytest.fixture
def admin_ctx(secured_session, admin_user, sample_property):
    """Tum yetkilere sahip servis baglami."""
    from app.application.context import ServiceContext

    return ServiceContext(
        session=secured_session,
        user=admin_user,
        property_id=sample_property.id,
    )


@pytest.fixture
def frontdesk_ctx(secured_session, frontdesk_user, sample_property):
    """On buro yetkilerine sahip baglam (finans ve gelistirme yetkisi YOK)."""
    from app.application.context import ServiceContext

    return ServiceContext(
        session=secured_session,
        user=frontdesk_user,
        property_id=sample_property.id,
    )
