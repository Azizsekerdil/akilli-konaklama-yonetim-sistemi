"""Referans veri ve demo veri ureteci testleri.

Bu testlerin asil isi, demo verisinin **guvenli** ve **tutarli** olmasini
dogrulamaktir:

* Gercek kisi verisi sizmamalidir - kimlik numaralari gecersiz, e-postalar
  teslim edilemez alan adinda, telefonlar ornek araliginda olmalidir.
* Ayni tohum ayni veriyi uretmelidir; aksi halde ekran goruntusu, egitim
  materyali ve hata ayiklama tekrar edilemez olurdu.
* Uretilen rezervasyonlar is kurallarini ihlal etmemelidir; demo veri,
  uygulamanin kendi cakisma kuraliyla tutarli olmalidir.
"""

from __future__ import annotations

import inspect
import random
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import ConflictError, ValidationError
from app.domain.enums import (
    HousekeepingTaskType,
    Priority,
    ReservationStatus,
    RoomHousekeepingStatus,
    RoomOccupancyStatus,
    StayStatus,
)
from app.domain.rules.availability import Booking
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    Charge,
    Department,
    Folio,
    Guest,
    HousekeepingTask,
    InventoryItem,
    MaintenanceTicket,
    Notification,
    Payment,
    Property,
    Reservation,
    ReservationRoom,
    Role,
    Room,
    RoomFeature,
    Service,
    Stay,
    TaxRate,
    User,
)
from app.infrastructure.seed import (
    DEMO_EMAIL_DOMAIN,
    DEMO_MARKER,
    DEMO_PROPERTY_CODE,
    DEMO_USERS,
    SCALE_PROFILES,
    TAX_RATES,
    clear_demo_data,
    create_demo_data,
    seed_reference_data,
)
from app.infrastructure.seed.demo_data import (
    FIRST_NAMES,
    SURNAMES,
    _money,
    _random_money,
)
from app.security.passwords import verify_password

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
#  Yardimcilar
# --------------------------------------------------------------------------
def _tckn_gecerli(value: str) -> bool:
    """Resmi T.C. Kimlik No dogrulama algoritmasi.

    Kasten **bagimsiz** olarak burada yeniden yazilmistir. Ureteci kendi
    dogrulayicisiyla test etmek totolojik olurdu; testin degeri, kuralin
    disaridan uygulanmasindan gelir.
    """
    if not value or len(value) != 11 or not value.isdigit():
        return False
    digits = [int(char) for char in value]
    if digits[0] == 0:
        return False
    if (sum(digits[0:9:2]) * 7 - sum(digits[1:8:2])) % 10 != digits[9]:
        return False
    return sum(digits[:10]) % 10 == digits[10]


def _fingerprint(db_session: Session) -> list[tuple[Any, ...]]:
    """Belirlenimcilik karsilastirmasi icin is verisi parmak izi.

    Parola hash'i (rastgele tuz) ve zaman damgalari bilincli olarak DISARIDA
    birakilir: bunlarin her calistirmada farkli olmasi beklenir ve tasarim
    geregidir.
    """
    parts: list[tuple[Any, ...]] = []
    for reservation in db_session.scalars(
        select(Reservation).order_by(Reservation.confirmation_number)
    ):
        room_row = reservation.rooms[0]
        parts.append(
            (
                "reservation",
                reservation.confirmation_number,
                reservation.status.value,
                reservation.check_in_date.isoformat(),
                reservation.check_out_date.isoformat(),
                str(reservation.total_amount),
                room_row.room_id,
                room_row.rate_plan_id,
            )
        )
    for guest in db_session.scalars(select(Guest).order_by(Guest.id)):
        parts.append(
            (
                "guest",
                guest.first_name,
                guest.last_name,
                guest.email,
                guest.identity_index,
                guest.vip_level.value,
                str(guest.total_revenue),
            )
        )
    for room in db_session.scalars(select(Room).order_by(Room.id)):
        parts.append(
            (
                "room",
                room.number,
                room.room_type_id,
                room.housekeeping_status.value,
                room.occupancy_status.value,
            )
        )
    for folio in db_session.scalars(select(Folio).order_by(Folio.folio_number)):
        parts.append(("folio", folio.folio_number, str(folio.balance), folio.status.value))
    return parts


def _count(db_session: Session, model: type) -> int:
    return int(db_session.scalar(select(func.count()).select_from(model)) or 0)


# --------------------------------------------------------------------------
#  Fiksturler
# --------------------------------------------------------------------------
@pytest.fixture
def make_session() -> Iterator[Any]:
    """Birbirinden bagimsiz, bellek ici oturumlar uretebilen fabrika.

    Belirlenimcilik testi ayni islem icinde **iki ayri veritabani** ister;
    tek oturum veren standart fikstur bunu karsilamaz.
    """
    created: list[tuple[Any, Session]] = []

    def _make() -> Session:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        db_session = factory()
        created.append((engine, db_session))
        return db_session

    yield _make

    for engine, db_session in created:
        db_session.rollback()
        db_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def demo(session: Session):
    """Kucuk olcekli demo veri kumesi ve ozeti."""
    summary = create_demo_data(session, seed=42, scale="small")
    return session, summary


# ==========================================================================
#  Referans veriler
# ==========================================================================
class TestReferansVerisi:
    def test_referans_verisi_olusturulur(self, session: Session, sample_property: Property):
        summary = seed_reference_data(session, property_id=sample_property.id)

        assert summary.room_features_created > 0
        assert summary.tax_rates_created == len(TAX_RATES)
        assert summary.services_created > 0
        assert summary.departments_created == 6
        assert summary.any_change is True

    def test_referans_verisi_idempotenttir(self, session: Session, sample_property: Property):
        """Ikinci cagri hicbir sey uretmemeli - surum yukseltmesinde cogaltma olmaz."""
        seed_reference_data(session, property_id=sample_property.id)
        before = _count(session, RoomFeature), _count(session, Service)

        ikinci = seed_reference_data(session, property_id=sample_property.id)

        assert ikinci.total_created == 0
        assert ikinci.any_change is False
        assert (_count(session, RoomFeature), _count(session, Service)) == before

    def test_departmanlar_beklenen_kodlari_icerir(
        self, session: Session, sample_property: Property
    ):
        seed_reference_data(session, property_id=sample_property.id)
        kodlar = {
            department.code
            for department in session.scalars(
                select(Department).where(Department.property_id == sample_property.id)
            )
        }
        assert {"ONBURO", "KAT", "TEKNIK", "MUHASEBE", "YIYECEK", "GUVENLIK"} <= kodlar

    def test_vergi_oranlari_ornek_olduklarini_belirtir(
        self, session: Session, sample_property: Property
    ):
        """Oranlar mevzuat degil ornek; ad alani bunu kullaniciya soylemeli."""
        seed_reference_data(session, property_id=sample_property.id)
        oranlar = {
            rate.code: rate
            for rate in session.scalars(
                select(TaxRate).where(TaxRate.property_id == sample_property.id)
            )
        }
        assert oranlar["KDV10"].rate_percent == Decimal("10.00")
        assert oranlar["KDV20"].rate_percent == Decimal("20.00")
        assert oranlar["KONAKLAMA2"].rate_percent == Decimal("2.00")
        assert all("ornek" in rate.name.lower() for rate in oranlar.values())
        # Konaklama vergisi faturada ayri satirdir; fiyata dahil degildir.
        assert oranlar["KONAKLAMA2"].is_included_in_price is False


# ==========================================================================
#  Demo veri - genel
# ==========================================================================
class TestDemoVeriUretimi:
    def test_tum_ana_tablolar_dolar(self, session: Session):
        create_demo_data(session, seed=7, scale="medium")

        for model in (
            Property,
            Room,
            Guest,
            Reservation,
            ReservationRoom,
            Stay,
            Folio,
            Charge,
            Payment,
            HousekeepingTask,
            MaintenanceTicket,
            InventoryItem,
            Notification,
            User,
        ):
            assert _count(session, model) > 0, f"{model.__name__} tablosu bos kaldi"

    def test_ozet_sayilari_veritabaniyla_uyusur(self, demo):
        db_session, summary = demo

        assert summary.counts["room"] == _count(db_session, Room)
        assert summary.counts["guest"] == _count(db_session, Guest)
        assert summary.counts["reservation"] == _count(db_session, Reservation)
        assert summary.counts["folio"] == _count(db_session, Folio)
        assert summary.counts["charge"] == _count(db_session, Charge)
        assert summary.total_records > 0

    def test_olcek_profiline_uyar(self, session: Session):
        summary = create_demo_data(session, seed=1, scale="small")
        profile = SCALE_PROFILES["small"]

        assert _count(session, Room) == profile.rooms
        assert _count(session, Guest) == profile.guests
        assert summary.scale == "small"

    def test_bilinmeyen_olcek_hata_verir(self, session: Session):
        with pytest.raises(ValidationError):
            create_demo_data(session, scale="devasa")

    def test_mevcut_demo_verisi_uzerine_yazilmaz(self, session: Session):
        """Ikinci cagri sessizce cift kayit uretmek yerine acikca hata vermeli."""
        create_demo_data(session, seed=42, scale="small")
        with pytest.raises(ConflictError):
            create_demo_data(session, seed=42, scale="small")


# ==========================================================================
#  Belirlenimcilik
# ==========================================================================
class TestBelirlenimcilik:
    def test_ayni_seed_ayni_veriyi_uretir(self, make_session):
        birinci = make_session()
        ikinci = make_session()

        create_demo_data(birinci, seed=1234, scale="small")
        create_demo_data(ikinci, seed=1234, scale="small")

        assert _fingerprint(birinci) == _fingerprint(ikinci)

    def test_farkli_seed_farkli_veri_uretir(self, make_session):
        birinci = make_session()
        ikinci = make_session()

        create_demo_data(birinci, seed=1, scale="small")
        create_demo_data(ikinci, seed=999, scale="small")

        assert _fingerprint(birinci) != _fingerprint(ikinci)

    def test_ozet_sayilari_ayni_seedde_ayni(self, make_session):
        birinci = make_session()
        ikinci = make_session()

        ilk_ozet = create_demo_data(birinci, seed=55, scale="small")
        ikinci_ozet = create_demo_data(ikinci, seed=55, scale="small")

        assert ilk_ozet.counts == ikinci_ozet.counts


# ==========================================================================
#  Is kurallari
# ==========================================================================
class TestIsKurallari:
    def test_rezervasyonlarda_cakisma_yok(self, demo):
        """KRITIK: ayni oda ayni gece iki kez satilamaz.

        Kontrol, uygulamanin kendi cakisma kurali
        (:class:`~app.domain.value_objects.DateRange`) ile yapilir.
        """
        db_session, _ = demo
        bookings: dict[int, list[Booking]] = {}

        for row in db_session.scalars(select(ReservationRoom)):
            if row.room_id is None:
                continue
            aralik = DateRange(row.check_in_date, row.check_out_date)
            for mevcut in bookings.get(row.room_id, []):
                assert not mevcut.date_range.overlaps(aralik), (
                    f"Oda {row.room_id} icin cakisma: "
                    f"{mevcut.date_range.format()} / {aralik.format()}"
                )
            bookings.setdefault(row.room_id, []).append(
                Booking(room_id=row.room_id, date_range=aralik)
            )

        assert bookings, "Hicbir odaya rezervasyon yerlestirilmemis"

    def test_satisa_kapali_odalar_blok_suresince_bos(self, demo):
        """Bloke odalar, blok **suresince** rezervasyon almamalidir.

        Suresiz kapali oda (tadilat) hic rezervasyon almaz; tarihli blok
        (ariza) yalnizca kendi araliginda engeller - oncesi ve sonrasi
        satilabilir, ki bu da dogru davranistir.
        """
        db_session, _ = demo
        kapali_odalar = [
            room
            for room in db_session.scalars(select(Room))
            if room.housekeeping_status
            in {RoomHousekeepingStatus.OUT_OF_ORDER, RoomHousekeepingStatus.OUT_OF_SERVICE}
        ]
        assert kapali_odalar, "Demo veride satisa kapali oda uretilmemis"

        atamalar: dict[int, list[DateRange]] = {}
        for row in db_session.scalars(select(ReservationRoom)):
            if row.room_id is None:
                continue
            atamalar.setdefault(row.room_id, []).append(
                DateRange(row.check_in_date, row.check_out_date)
            )

        suresiz_kapali = 0
        for room in kapali_odalar:
            if room.out_of_service_from is None and room.out_of_service_until is None:
                suresiz_kapali += 1
                assert room.id not in atamalar
                continue
            blok = DateRange(
                room.out_of_service_from, room.out_of_service_until + timedelta(days=1)
            )
            for aralik in atamalar.get(room.id, []):
                assert not aralik.overlaps(
                    blok
                ), f"Oda {room.number} blok suresinde satilmis: {aralik.format()}"
        assert suresiz_kapali == 1

    def test_bugun_icin_giris_cikis_ve_otelde_kayitlari_var(self, demo):
        db_session, summary = demo
        bugun = summary.reference_date

        girisler = db_session.scalars(
            select(Reservation).where(
                Reservation.check_in_date == bugun,
                Reservation.status == ReservationStatus.CONFIRMED,
            )
        ).all()
        cikislar = db_session.scalars(
            select(Reservation).where(
                Reservation.check_out_date == bugun,
                Reservation.status == ReservationStatus.CHECKED_IN,
            )
        ).all()
        otelde = db_session.scalars(select(Stay).where(Stay.status == StayStatus.IN_HOUSE)).all()

        assert girisler, "Bugun giris bekleyen rezervasyon yok"
        assert cikislar, "Bugun cikis yapacak rezervasyon yok"
        assert otelde, "Otelde konaklayan misafir yok"

    def test_iptal_ve_gelmedi_ornekleri_var(self, demo):
        db_session, _ = demo
        durumlar = {reservation.status for reservation in db_session.scalars(select(Reservation))}
        assert ReservationStatus.CANCELLED in durumlar
        assert ReservationStatus.NO_SHOW in durumlar
        assert ReservationStatus.CHECKED_OUT in durumlar
        assert ReservationStatus.TENTATIVE in durumlar

    def test_folio_bakiyeleri_tutarlidir(self, demo):
        """Bakiye her zaman ``toplam ucret - toplam odeme`` olmalidir."""
        db_session, _ = demo
        folyolar = db_session.scalars(select(Folio)).all()
        assert folyolar

        for folio in folyolar:
            ucret_toplami = sum(
                (charge.total_amount for charge in folio.charges if not charge.is_void),
                start=Decimal("0.00"),
            )
            odeme_toplami = sum(
                (payment.amount for payment in folio.payments if not payment.is_refund),
                start=Decimal("0.00"),
            )
            assert folio.total_charges == ucret_toplami
            assert folio.total_payments == odeme_toplami
            assert folio.balance == folio.total_charges - folio.total_payments

    def test_cikis_yapmis_folyolar_kapali_ve_sifir_bakiyeli(self, demo):
        db_session, _ = demo
        kapali = [
            folio for folio in db_session.scalars(select(Folio)) if folio.status.value == "closed"
        ]
        assert kapali
        assert all(folio.balance == Decimal("0.00") for folio in kapali)

    def test_kat_hizmetleri_gorevleri_bugune_ait(self, demo):
        db_session, summary = demo
        gorevler = db_session.scalars(select(HousekeepingTask)).all()

        assert gorevler
        assert all(task.scheduled_date == summary.reference_date for task in gorevler)

    def test_odayi_bloke_eden_ariza_kaydi_var(self, demo):
        db_session, _ = demo
        bloke_edenler = [
            ticket for ticket in db_session.scalars(select(MaintenanceTicket)) if ticket.blocks_room
        ]
        assert len(bloke_edenler) == 1

        ticket = bloke_edenler[0]
        assert ticket.room_id is not None
        assert ticket.block_from is not None and ticket.block_until is not None
        oda = db_session.get(Room, ticket.room_id)
        assert oda is not None
        assert oda.housekeeping_status is RoomHousekeepingStatus.OUT_OF_ORDER

    def test_bugun_cikis_yapmis_odalar_temizlik_kuyrugunda(self, demo):
        """Bugun cikan misafirin odasi bos + kirli olmali ve temizlik beklemeli.

        Bu, kat hizmetleri ekraninin en onemli sahnesidir. Demo veride bu
        durum hic uretilmezse ekran bos gorunur ve ureticideki "bugun cikti"
        dali olu kod olurdu.
        """
        db_session, summary = demo

        bugun_cikanlar = [
            stay
            for stay in db_session.scalars(select(Stay))
            if stay.actual_check_out is not None
            and stay.actual_check_out.date() == summary.reference_date
        ]
        assert bugun_cikanlar, "Bugun cikis yapmis konaklama uretilmemis"

        bos_kirli = db_session.scalars(
            select(Room).where(
                Room.occupancy_status == RoomOccupancyStatus.VACANT,
                Room.housekeeping_status == RoomHousekeepingStatus.DIRTY,
            )
        ).all()
        assert bos_kirli, "Cikis sonrasi temizlik bekleyen oda yok"

    def test_cikis_temizligi_gorevi_uretilir(self, demo):
        """Bos-kirli odalar icin yuksek oncelikli cikis temizligi acilmali."""
        db_session, _ = demo
        gorevler = db_session.scalars(select(HousekeepingTask)).all()

        cikis_temizligi = [
            task for task in gorevler if task.task_type is HousekeepingTaskType.CHECKOUT_CLEANING
        ]
        assert cikis_temizligi, "Cikis temizligi gorevi hic uretilmemis"
        assert all(task.priority is Priority.HIGH for task in cikis_temizligi)

    def test_bazi_stok_kalemleri_minimum_altinda(self, demo):
        db_session, _ = demo
        kalemler = db_session.scalars(select(InventoryItem)).all()
        dusuk = [item for item in kalemler if item.is_below_minimum]

        assert kalemler
        assert dusuk, "Dusuk stok uyarilarini gosterecek kalem uretilmemis"
        assert len(dusuk) < len(kalemler), "Tum stok bitmis gorunuyor - gercekci degil"


# ==========================================================================
#  Para yolu - float yasagi
# ==========================================================================
class TestParaYolu:
    """Para degerlerinin hicbir asamada float'a dusmedigini dogrular."""

    def test_rastgele_tutar_decimal_ve_iki_ondalikli(self):
        rng = random.Random(11)
        for _ in range(200):
            tutar = _random_money(rng, "0.00", "2500.00")
            assert isinstance(tutar, Decimal)
            assert tutar.as_tuple().exponent == -2
            assert Decimal("0.00") <= tutar <= Decimal("2500.00")

    def test_rastgele_tutar_belirlenimcidir(self):
        birinci = [_random_money(random.Random(5), "1.00", "9.00") for _ in range(3)]
        ikinci = [_random_money(random.Random(5), "1.00", "9.00") for _ in range(3)]
        assert birinci == ikinci

    def test_money_float_kabul_etmez(self):
        """Imza float almamali; alsaydi 'para yolunda float yok' kurali delinirdi."""
        imza = inspect.signature(_money)
        annotation = imza.parameters["value"].annotation
        assert "float" not in str(annotation)

    def test_uretilen_para_alanlarinda_float_yok(self, demo):
        """KRITIK: veritabanina yazilan hicbir para degeri float olmamali."""
        db_session, _ = demo
        kacaklar: list[str] = []

        for model in (Charge, Payment, Folio, Reservation, ReservationRoom):
            para_sutunlari = [
                column
                for column in sa_inspect(model).columns
                if column.type.__class__.__name__ == "Numeric"
            ]
            for row in db_session.scalars(select(model)):
                for column in para_sutunlari:
                    deger = getattr(row, column.key, None)
                    if isinstance(deger, float):
                        kacaklar.append(f"{model.__name__}.{column.key}={deger!r}")

        assert not kacaklar, f"Para sutunlarinda float bulundu: {kacaklar[:5]}"


# ==========================================================================
#  Kisisel veri guvenligi
# ==========================================================================
class TestUydurmaVeriGuvenligi:
    def test_kimlik_numaralari_gecerli_tckn_degildir(self, demo):
        """KRITIK: uretilen hicbir numara gercek bir kimlik numarasi olmamali."""
        db_session, _ = demo
        misafirler = db_session.scalars(select(Guest)).all()
        assert misafirler

        for guest in misafirler:
            numara = guest.identity_number
            assert numara, f"{guest.full_name} icin kimlik numarasi uretilmemis"
            assert not _tckn_gecerli(numara), f"GECERLI TCKN uretildi: {numara}"

    def test_kimlik_numaralari_benzersizdir(self, demo):
        db_session, _ = demo
        indeksler = [guest.identity_index for guest in db_session.scalars(select(Guest))]
        assert len(indeksler) == len(set(indeksler))

    def test_epostalar_teslim_edilemez_alan_adinda(self, demo):
        db_session, _ = demo
        for guest in db_session.scalars(select(Guest)):
            assert guest.email is not None
            assert guest.email.endswith(f"@{DEMO_EMAIL_DOMAIN}")
            assert guest.email.endswith(".local")

    def test_kullanici_epostalari_da_local_alan_adinda(self, demo):
        db_session, _ = demo
        for user in db_session.scalars(select(User).where(User.notes == DEMO_MARKER)):
            assert user.email is not None
            assert user.email.endswith(f"@{DEMO_EMAIL_DOMAIN}")

    def test_telefonlar_maskeli_ve_cevrilemez(self, demo):
        """Demo telefonlari **cevrilemez** olmalidir.

        Bu test bicim degil, guvenlik kosulu dogrular: numarada cevrilmeye
        yetecek kadar rakam **bulunmamalidir**. Turkiye mobil numarasi ulke
        kodu dahil 12 hanedir; maskede yalnizca ``+90 5`` sabiti kalir.
        Ekran goruntusu betigi bu veriyi yakalayip tanitim sunumuna gomdugu
        icin, tam bicimli bir numara buradan disari cikardi.
        """
        import re

        from app.infrastructure.seed.demo_data import DEMO_PHONE_MASK

        db_session, _ = demo
        for guest in db_session.scalars(select(Guest)):
            assert guest.phone is not None
            assert guest.phone.startswith(DEMO_PHONE_MASK)
            govde = guest.phone.split("(")[0]
            rakamlar = re.sub(r"\D", "", govde)
            # "+90 5" -> 3 rakam. Cevrilebilir bir numara icin 12 gerekir.
            assert len(rakamlar) <= 3, guest.phone
            # Cevrilebilir bir E.164 dizisi hicbir yerde kalmamali.
            assert not re.search(r"\+?\d[\d \-]{9,}\d", guest.phone), guest.phone

    def test_calisan_ve_kurumsal_telefonlar_da_maskeli(self, demo):
        """Maskeleme yalnizca misafir tablosuna degil, tum kayitlara uygulanir."""
        from app.infrastructure.db.models import Employee
        from app.infrastructure.seed.demo_data import DEMO_PHONE_MASK

        db_session2, _ = demo
        for employee in db_session2.scalars(select(Employee)):
            if employee.phone:
                assert employee.phone.startswith(DEMO_PHONE_MASK), employee.phone

    def test_bir_misafir_kara_listede(self, demo):
        db_session, _ = demo
        kara_liste = db_session.scalars(select(Guest).where(Guest.is_blacklisted.is_(True))).all()

        assert len(kara_liste) == 1
        assert kara_liste[0].blacklist_reason
        assert kara_liste[0].blacklisted_at is not None

    def test_demo_kullanicilari_ozette_listelenir_ve_giris_yapabilir(self, demo):
        db_session, summary = demo

        assert len(summary.users) == len(DEMO_USERS)
        assert "UYARI" in summary.warning
        assert "demo" in summary.warning.lower()

        for credential in summary.users:
            user = db_session.scalars(
                select(User).where(User.username == credential.username)
            ).one()
            assert verify_password(credential.password, user.password_hash)
            assert user.is_superuser is False
            assert credential.password in summary.format_report()

    def test_demo_kullanicilarina_beklenen_roller_atanmis(self, demo):
        db_session, _ = demo
        beklenen = {"manager", "frontdesk", "housekeeping", "maintenance", "accounting"}
        atanan: set[str] = set()

        for user in db_session.scalars(select(User).where(User.notes == DEMO_MARKER)):
            atanan.update(role.code for role in user.roles)

        assert beklenen <= atanan
        assert _count(db_session, Role) > 0


# ==========================================================================
#  Temizleme
# ==========================================================================
class TestDemoVeriTemizleme:
    def test_onay_olmadan_calismaz(self, demo):
        db_session, _ = demo
        onceki = _count(db_session, Reservation)

        with pytest.raises(ValidationError):
            clear_demo_data(db_session)

        assert _count(db_session, Reservation) == onceki

    def test_onay_ile_demo_kayitlari_silinir(self, demo):
        db_session, _ = demo
        sonuc = clear_demo_data(db_session, confirm=True)

        assert sonuc.any_deleted
        assert sonuc.total_deleted > 0
        for model in (Property, Room, Guest, Reservation, Folio, Charge, Payment, Stay):
            assert _count(db_session, model) == 0
        assert (
            db_session.scalars(
                select(Property).where(Property.code == DEMO_PROPERTY_CODE)
            ).one_or_none()
            is None
        )

    def test_referans_ve_guvenlik_verisi_korunur(self, demo):
        """Oda ozellikleri, roller ve izinler demo degildir - silinmemeli."""
        db_session, _ = demo
        ozellik_sayisi = _count(db_session, RoomFeature)
        rol_sayisi = _count(db_session, Role)

        clear_demo_data(db_session, confirm=True)

        assert _count(db_session, RoomFeature) == ozellik_sayisi
        assert _count(db_session, Role) == rol_sayisi

    def test_isletmenin_kendi_kayitlari_silinmez(self, demo):
        """Demo isareti tasimayan bir misafir temizlemeden etkilenmemeli."""
        db_session, _ = demo
        gercek_misafir = Guest(
            first_name="Gercek",
            last_name="Kayit",
            email="isletme.kaydi@ornek-test.local",
        )
        gercek_misafir.set_identity("00000000001")
        db_session.add(gercek_misafir)
        db_session.commit()

        clear_demo_data(db_session, confirm=True)

        kalanlar = db_session.scalars(select(Guest)).all()
        assert len(kalanlar) == 1
        assert kalanlar[0].last_name == "Kayit"

    def test_temizleme_sonrasi_yeniden_uretilebilir(self, demo):
        db_session, _ = demo
        clear_demo_data(db_session, confirm=True)

        yeni = create_demo_data(db_session, seed=42, scale="small")

        assert yeni.total_records > 0
        assert _count(db_session, Reservation) > 0

    def test_bos_veritabaninda_temizleme_hata_vermez(self, session: Session):
        sonuc = clear_demo_data(session, confirm=True)
        assert sonuc.total_deleted == 0
        assert sonuc.any_deleted is False

    def test_kara_listedeki_kayit_acikca_kurgusal_adlidir(self, demo):
        """Kara liste etiketi gercek gorunumlu bir adla eslesmemelidir.

        Bu ekran tanitim sunumuna goruntu olarak girer. Rastgele uretilmis
        bir ad-soyad birlesimi gercek bir kisiyle ortusurse, "KARA LISTE"
        etiketiyle yan yana yayimlanmasi itibar riski dogurur. Risk bicimde
        degil, ad ile etiketin yan yana gorunmesindedir; bu yuzden maskeleme
        degil, acikca kurgusal bir ad kullanilir.
        """
        db_session, _ = demo
        kara_liste = db_session.scalars(select(Guest).where(Guest.is_blacklisted.is_(True))).all()
        assert len(kara_liste) == 1
        kayit = kara_liste[0]
        tam_ad = f"{kayit.first_name} {kayit.last_name}"
        assert "DEMO" in tam_ad.upper()
        assert kayit.first_name not in FIRST_NAMES
        assert kayit.last_name not in SURNAMES

    def test_demo_ureteci_kaynaginda_cevrilebilir_numara_yok(self):
        """Kaynakta elle yazilmis tam bicimli bir numara kalmamalidir.

        Maskeleme yalnizca ``_demo_phone`` icinde yapilirsa, dogrudan
        ``phone="+90 555 ..."`` yazan bir satir gozden kacar - nitekim tesis
        kaydinda tam olarak bu olmustu. Bu test kaynagi tarar.
        """
        import re

        from app.infrastructure.seed import demo_data as modul

        kaynak = inspect.getsource(modul)
        satirlar = [
            satir
            for satir in kaynak.splitlines()
            if re.search(r"\+90[ \-]?\d{3}[ \-]?\d{3}[ \-]?\d{2}[ \-]?\d{2}", satir)
            and "Onceki surum" not in satir
        ]
        assert not satirlar, f"Cevrilebilir numara iceren satirlar: {satirlar}"
