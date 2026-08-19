"""Kat hizmetleri ve teknik servis servis katmani testleri.

Kapsanan kritik senaryolar:

* Gunluk gorev uretimi **idempotenttir** - ikinci calistirma gorev tekrarlamaz
* ``complete()`` odayi temiz, ``inspect(passed=False)`` yeniden kirli yapar
* ``blocks_room=True`` odayi satisa kapatir
* **Satilmis oda** sessizce kapatilamaz; ``force=True`` + yetki ile gecilir
* ``resolve()`` blokeyi kaldirir ve odayi temizlige gonderir
* Yetkisiz kullanici gorev atayamaz / oda durumu degistiremez
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.application.context import ServiceContext
from app.application.services.frontdesk_service import FrontdeskService
from app.application.services.housekeeping_service import HousekeepingService
from app.application.services.maintenance_service import MaintenanceService, PartUsage
from app.application.services.reservation_service import ReservationService, RoomRequest
from app.core.exceptions import (
    AuthorizationError,
    BusinessRuleError,
    NotFoundError,
    ValidationError,
)
from app.domain.enums import (
    EmploymentStatus,
    HousekeepingStatus,
    HousekeepingTaskType,
    MaintenanceCategory,
    MaintenanceStatus,
    Priority,
    RoomHousekeepingStatus,
)
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models import Property, Role, Room, User
from app.infrastructure.db.models.organization import Department, Employee
from app.security.passwords import hash_password

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
#  Fiksturler
# --------------------------------------------------------------------------
@pytest.fixture
def viewer_ctx(secured_session: Session, sample_property: Property) -> ServiceContext:
    """Yalnizca okuma yetkisi olan baglam (hicbir kayit degistiremez)."""
    from sqlalchemy import select

    role = secured_session.scalars(select(Role).where(Role.code == "viewer")).one()
    user = User(
        username="izleyici",
        full_name="Test Izleyici",
        password_hash=hash_password("IzleyiciTest2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    secured_session.add(user)
    secured_session.commit()
    return ServiceContext(
        session=secured_session,
        user=user,
        property_id=sample_property.id,
    )


@pytest.fixture
def housekeeper(secured_session: Session, sample_property: Property) -> Employee:
    """Kat hizmetleri departmaninda aktif bir personel (uydurma)."""
    department = Department(property_id=sample_property.id, code="KAT", name="Kat Hizmetleri")
    secured_session.add(department)
    secured_session.flush()

    employee = Employee(
        property_id=sample_property.id,
        department_id=department.id,
        employee_code="KAT-001",
        first_name="Bahar",
        last_name="Yaprakli",
        position="Kat Gorevlisi",
        employment_status=EmploymentStatus.ACTIVE,
    )
    secured_session.add(employee)
    secured_session.commit()
    return employee


@pytest.fixture
def technician(secured_session: Session, sample_property: Property) -> Employee:
    """Teknik servis departmaninda aktif bir personel (uydurma)."""
    department = Department(property_id=sample_property.id, code="TEKNIK", name="Teknik Servis")
    secured_session.add(department)
    secured_session.flush()

    employee = Employee(
        property_id=sample_property.id,
        department_id=department.id,
        employee_code="TEK-001",
        first_name="Poyraz",
        last_name="Demirli",
        position="Teknisyen",
        employment_status=EmploymentStatus.ACTIVE,
    )
    secured_session.add(employee)
    secured_session.commit()
    return employee


@pytest.fixture
def in_house_reservation(admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest):
    """101 numarali odada dun baslamis, yarin bitecek onayli konaklama."""
    today = utcnow().date()
    return ReservationService(admin_ctx).create_reservation(
        guest_id=guest.id,
        room_requests=[
            RoomRequest(
                room_type_id=sample_room_type.id,
                room_id=sample_rooms[0].id,
                check_in=today - timedelta(days=1),
                check_out=today + timedelta(days=1),
            )
        ],
    )


@pytest.fixture
def departing_reservation(admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest):
    """102 numarali odada bugun cikis yapacak konaklama."""
    today = utcnow().date()
    return ReservationService(admin_ctx).create_reservation(
        guest_id=guest.id,
        room_requests=[
            RoomRequest(
                room_type_id=sample_room_type.id,
                room_id=sample_rooms[1].id,
                check_in=today - timedelta(days=2),
                check_out=today,
            )
        ],
    )


@pytest.fixture
def open_task(admin_ctx, property_with_rooms, sample_rooms):
    """101 numarali oda icin bekleyen bir cikis temizligi gorevi."""
    from app.infrastructure.db.models.operations import HousekeepingTask

    task = HousekeepingTask(
        property_id=sample_rooms[0].property_id,
        room_id=sample_rooms[0].id,
        task_type=HousekeepingTaskType.CHECKOUT_CLEANING,
        status=HousekeepingStatus.PENDING,
        priority=Priority.HIGH,
        scheduled_date=utcnow().date(),
        estimated_minutes=45,
    )
    admin_ctx.session.add(task)
    admin_ctx.session.commit()
    return task


# --------------------------------------------------------------------------
#  Gunluk gorev uretimi
# --------------------------------------------------------------------------
class TestGenerateDailyTasks:
    def test_cikis_odasi_icin_cikis_temizligi_uretilir(
        self, admin_ctx, departing_reservation, sample_rooms
    ):
        created = HousekeepingService(admin_ctx).generate_daily_tasks()

        assert len(created) == 1
        assert created[0].room_id == sample_rooms[1].id
        assert created[0].task_type is HousekeepingTaskType.CHECKOUT_CLEANING
        assert created[0].priority is Priority.HIGH

    def test_otelde_kalan_oda_icin_gunluk_temizlik_uretilir(
        self, admin_ctx, in_house_reservation, sample_rooms
    ):
        created = HousekeepingService(admin_ctx).generate_daily_tasks()

        assert len(created) == 1
        assert created[0].room_id == sample_rooms[0].id
        assert created[0].task_type is HousekeepingTaskType.DAILY_CLEANING
        assert created[0].priority is Priority.NORMAL

    def test_ikinci_calistirma_gorev_tekrarlamaz(
        self, admin_ctx, in_house_reservation, departing_reservation
    ):
        """IDEMPOTENT: vardiya sefi dugmeye iki kez basarsa liste bozulmamali."""
        service = HousekeepingService(admin_ctx)

        first = service.generate_daily_tasks()
        second = service.generate_daily_tasks()

        assert len(first) == 2
        assert second == []
        assert len(service.daily_tasks()) == 2

    def test_servis_disi_oda_gorev_uretmez(self, admin_ctx, in_house_reservation, sample_rooms):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        admin_ctx.session.commit()

        assert HousekeepingService(admin_ctx).generate_daily_tasks() == []

    def test_iptal_edilen_gorevin_yerine_yenisi_uretilir(self, admin_ctx, in_house_reservation):
        service = HousekeepingService(admin_ctx)
        created = service.generate_daily_tasks()
        created[0].status = HousekeepingStatus.CANCELLED
        admin_ctx.session.commit()

        assert len(service.generate_daily_tasks()) == 1

    def test_yetkisiz_kullanici_gorev_uretemez(self, viewer_ctx, property_with_rooms):
        with pytest.raises(AuthorizationError):
            HousekeepingService(viewer_ctx).generate_daily_tasks()


# --------------------------------------------------------------------------
#  Gorev yasam dongusu
# --------------------------------------------------------------------------
class TestHousekeepingLifecycle:
    def test_gorev_personele_atanir(self, admin_ctx, open_task, housekeeper):
        task = HousekeepingService(admin_ctx).assign(open_task.id, housekeeper.id)

        assert task.assigned_employee_id == housekeeper.id
        assert task.status is HousekeepingStatus.ASSIGNED

    def test_yetkisiz_kullanici_gorev_atayamaz(self, frontdesk_ctx, open_task, housekeeper):
        """On buro gorevlisinin 'housekeeping.assign' yetkisi yoktur."""
        with pytest.raises(AuthorizationError) as hata:
            HousekeepingService(frontdesk_ctx).assign(open_task.id, housekeeper.id)
        assert hata.value.permission == "housekeeping.assign"

    def test_izinli_personele_atama_engellenir(self, admin_ctx, open_task, housekeeper):
        housekeeper.employment_status = EmploymentStatus.ON_LEAVE
        admin_ctx.session.commit()

        with pytest.raises(BusinessRuleError) as hata:
            HousekeepingService(admin_ctx).assign(open_task.id, housekeeper.id)
        assert hata.value.code == "employee_unavailable"

    def test_olmayan_personele_atama_hata_verir(self, admin_ctx, open_task):
        with pytest.raises(NotFoundError):
            HousekeepingService(admin_ctx).assign(open_task.id, 9999)

    def test_basla_odayi_temizleniyor_yapar(self, admin_ctx, open_task, sample_rooms):
        task = HousekeepingService(admin_ctx).start(open_task.id)

        assert task.status is HousekeepingStatus.IN_PROGRESS
        assert task.started_at is not None
        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.CLEANING_IN_PROGRESS

    def test_tamamla_odayi_temiz_yapar(self, admin_ctx, open_task, sample_rooms):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        admin_ctx.session.commit()

        service = HousekeepingService(admin_ctx)
        service.start(open_task.id)
        task = service.complete(open_task.id, actual_minutes=38, issues="Dus basligi kirecli")

        assert task.status is HousekeepingStatus.COMPLETED
        assert task.actual_minutes == 38
        assert task.issues_found == "Dus basligi kirecli"
        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.CLEAN

    def test_sure_verilmezse_baslangictan_hesaplanir(self, admin_ctx, open_task):
        service = HousekeepingService(admin_ctx)
        service.start(open_task.id)
        task = service.complete(open_task.id)

        assert task.actual_minutes is not None
        assert task.actual_minutes >= 0

    def test_kapanmis_gorev_yeniden_tamamlanamaz(self, admin_ctx, open_task):
        service = HousekeepingService(admin_ctx)
        service.complete(open_task.id)

        with pytest.raises(BusinessRuleError) as hata:
            service.complete(open_task.id)
        assert hata.value.code == "task_closed"

    def test_negatif_sure_reddedilir(self, admin_ctx, open_task):
        with pytest.raises(ValidationError):
            HousekeepingService(admin_ctx).complete(open_task.id, actual_minutes=-5)


class TestHousekeepingInspection:
    def test_kontrol_gecerse_oda_kontrol_edildi_olur(self, admin_ctx, open_task, sample_rooms):
        service = HousekeepingService(admin_ctx)
        service.complete(open_task.id)
        task = service.inspect(open_task.id, passed=True, notes="Sorunsuz")

        assert task.status is HousekeepingStatus.INSPECTED
        assert task.inspection_passed is True
        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.INSPECTED

    def test_kontrol_kalirsa_oda_kirliye_doner_ve_gorev_yeniden_acilir(
        self, admin_ctx, open_task, sample_rooms
    ):
        service = HousekeepingService(admin_ctx)
        service.start(open_task.id)
        service.complete(open_task.id, actual_minutes=10)
        task = service.inspect(open_task.id, passed=False, notes="Banyo temizlenmemis")

        assert task.status is HousekeepingStatus.PENDING
        assert task.inspection_passed is False
        assert task.completed_at is None
        assert task.actual_minutes is None
        assert task.priority is Priority.HIGH
        assert task.issues_found == "Banyo temizlenmemis"
        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.DIRTY

    def test_tamamlanmamis_gorev_kontrol_edilemez(self, admin_ctx, open_task):
        with pytest.raises(BusinessRuleError) as hata:
            HousekeepingService(admin_ctx).inspect(open_task.id, passed=True)
        assert hata.value.code == "task_not_completed"


class TestRoomStatus:
    def test_oda_durumu_degistirilir_ve_blok_alanlari_temizlenir(self, admin_ctx, sample_rooms):
        today = utcnow().date()
        sample_rooms[2].housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        sample_rooms[2].out_of_service_from = today
        sample_rooms[2].out_of_service_until = today + timedelta(days=3)
        sample_rooms[2].out_of_service_reason = "Eski kayit"
        admin_ctx.session.commit()

        room = HousekeepingService(admin_ctx).set_room_status(
            sample_rooms[2].id, RoomHousekeepingStatus.CLEAN
        )

        assert room.housekeeping_status is RoomHousekeepingStatus.CLEAN
        assert room.out_of_service_from is None
        assert room.out_of_service_until is None
        assert room.out_of_service_reason is None

    def test_yetkisiz_kullanici_oda_durumu_degistiremez(self, viewer_ctx, sample_rooms):
        with pytest.raises(AuthorizationError) as hata:
            HousekeepingService(viewer_ctx).set_room_status(
                sample_rooms[0].id, RoomHousekeepingStatus.DIRTY
            )
        assert hata.value.permission == "room.status_change"

    def test_satilmis_oda_servis_disi_yapilamaz(
        self, admin_ctx, in_house_reservation, sample_rooms
    ):
        """KRITIK: ariza kaydi yolundaki koruma bu yolda da gecerlidir.

        Oda planindan sag tikla 'Servis disi yap' demek, ariza kaydi acmakla
        ayni sonucu dogurur: oda satistan cikar. Koruma yalnizca bir yolda
        olsaydi kullanici digerinden gecerdi.
        """
        with pytest.raises(BusinessRuleError) as hata:
            HousekeepingService(admin_ctx).set_room_status(
                sample_rooms[0].id, RoomHousekeepingStatus.OUT_OF_SERVICE
            )
        assert hata.value.code == "room_has_reservation"
        assert sample_rooms[0].housekeeping_status is not RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_force_ile_yetkili_servis_disi_yapabilir(
        self, admin_ctx, in_house_reservation, sample_rooms
    ):
        room = HousekeepingService(admin_ctx).set_room_status(
            sample_rooms[0].id, RoomHousekeepingStatus.OUT_OF_SERVICE, force=True
        )
        assert room.housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_force_yetkisi_olmayan_kullanicida_reddedilir(
        self, frontdesk_ctx, in_house_reservation, sample_rooms
    ):
        """On buro 'reservation.override' yetkisine sahip degildir."""
        with pytest.raises(AuthorizationError):
            HousekeepingService(frontdesk_ctx).set_room_status(
                sample_rooms[0].id, RoomHousekeepingStatus.OUT_OF_SERVICE, force=True
            )

    def test_rezervasyonsuz_oda_serbestce_kapatilir(self, admin_ctx, sample_rooms):
        room = HousekeepingService(admin_ctx).set_room_status(
            sample_rooms[2].id, RoomHousekeepingStatus.OUT_OF_SERVICE
        )
        assert room.housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_bugun_cikan_rezervasyon_kapatmayi_engellemez(
        self, admin_ctx, departing_reservation, sample_rooms
    ):
        """Cikis gunu oda bosalir; yari acik aralik geregi cakisma yoktur."""
        room = HousekeepingService(admin_ctx).set_room_status(
            sample_rooms[1].id, RoomHousekeepingStatus.OUT_OF_SERVICE
        )
        assert room.housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_zaten_servis_disi_odada_kontrol_tekrarlanmaz(
        self, admin_ctx, in_house_reservation, sample_rooms
    ):
        """Satilamaz durumdan satilamaz duruma gecis yeni bir zarar uretmez."""
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        admin_ctx.session.commit()

        room = HousekeepingService(admin_ctx).set_room_status(
            sample_rooms[0].id, RoomHousekeepingStatus.OUT_OF_ORDER
        )
        assert room.housekeeping_status is RoomHousekeepingStatus.OUT_OF_ORDER

    def test_satilabilir_duruma_donus_engellenmez(
        self, admin_ctx, in_house_reservation, sample_rooms
    ):
        room = HousekeepingService(admin_ctx).set_room_status(
            sample_rooms[0].id, RoomHousekeepingStatus.CLEAN
        )
        assert room.housekeeping_status is RoomHousekeepingStatus.CLEAN

    def test_baska_tesisin_odasi_reddedilir(self, admin_ctx, secured_session, sample_rooms):
        other = Property(code="TEST02", name="Ikinci Otel")
        secured_session.add(other)
        secured_session.flush()
        stray = Room(
            property_id=other.id,
            room_type_id=sample_rooms[0].room_type_id,
            number="901",
        )
        secured_session.add(stray)
        secured_session.commit()

        with pytest.raises(ValidationError):
            HousekeepingService(admin_ctx).set_room_status(stray.id, RoomHousekeepingStatus.DIRTY)


# --------------------------------------------------------------------------
#  Teknik servis
# --------------------------------------------------------------------------
class TestMaintenanceCreate:
    def test_ariza_kaydi_acilir(self, admin_ctx, sample_rooms):
        ticket = MaintenanceService(admin_ctx).create_ticket(
            room_id=sample_rooms[0].id,
            category=MaintenanceCategory.PLUMBING,
            title="Lavabo akitiyor",
            description="Sifon baglantisindan damlama var.",
            priority=Priority.HIGH,
        )

        assert ticket.ticket_number.startswith("ARZ-")
        assert ticket.status is MaintenanceStatus.OPEN
        assert ticket.is_open
        assert sample_rooms[0].housekeeping_status is not RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_blocks_room_odayi_servis_disi_yapar(self, admin_ctx, sample_rooms):
        today = utcnow().date()
        ticket = MaintenanceService(admin_ctx).create_ticket(
            room_id=sample_rooms[2].id,
            category=MaintenanceCategory.HVAC,
            title="Klima calismiyor",
            description="Kompresor arizali, parca bekleniyor.",
            priority=Priority.URGENT,
            blocks_room=True,
            block_from=today,
            block_until=today + timedelta(days=2),
        )

        assert sample_rooms[2].housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE
        assert sample_rooms[2].out_of_service_until == today + timedelta(days=2)
        assert ticket.ticket_number in (sample_rooms[2].out_of_service_reason or "")

    def test_cakisan_rezervasyon_varken_bloke_engellenir(
        self, admin_ctx, in_house_reservation, sample_rooms
    ):
        """KRITIK: satilmis odayi sessizce kapatmak misafiri kapida birakir."""
        today = utcnow().date()
        with pytest.raises(BusinessRuleError) as hata:
            MaintenanceService(admin_ctx).create_ticket(
                room_id=sample_rooms[0].id,
                category=MaintenanceCategory.ELECTRICAL,
                title="Priz yanmis",
                description="Yatak basi priz calismiyor.",
                blocks_room=True,
                block_from=today,
                block_until=today,
            )
        assert hata.value.code == "room_has_reservation"
        assert sample_rooms[0].housekeeping_status is not RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_force_ile_yetkili_bloke_edebilir(self, admin_ctx, in_house_reservation, sample_rooms):
        today = utcnow().date()
        ticket = MaintenanceService(admin_ctx).create_ticket(
            room_id=sample_rooms[0].id,
            category=MaintenanceCategory.ELECTRICAL,
            title="Priz yanmis",
            description="Yatak basi priz calismiyor.",
            blocks_room=True,
            block_from=today,
            block_until=today,
            force=True,
        )

        assert ticket.blocks_room is True
        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_force_yetkisi_olmayan_kullanicida_reddedilir(
        self, frontdesk_ctx, in_house_reservation, sample_rooms
    ):
        """On buro 'room.block' ve 'reservation.override' yetkilerine sahip degildir."""
        today = utcnow().date()
        with pytest.raises(AuthorizationError):
            MaintenanceService(frontdesk_ctx).create_ticket(
                room_id=sample_rooms[0].id,
                category=MaintenanceCategory.ELECTRICAL,
                title="Priz yanmis",
                description="Yatak basi priz calismiyor.",
                blocks_room=True,
                block_from=today,
                block_until=today,
                force=True,
            )

    def test_bitmis_rezervasyon_bloke_engellemez(
        self, admin_ctx, departing_reservation, sample_rooms
    ):
        """Cikis gunu oda bosalir; yari acik aralik geregi cakisma yoktur."""
        today = utcnow().date()
        MaintenanceService(admin_ctx).create_ticket(
            room_id=sample_rooms[1].id,
            category=MaintenanceCategory.FURNITURE,
            title="Koltuk yirtik",
            description="Yeni kilif siparis edilecek.",
            blocks_room=True,
            block_from=today,
            block_until=today,
        )
        assert sample_rooms[1].housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_oda_secilmeden_bloke_yapilamaz(self, admin_ctx, property_with_rooms):
        with pytest.raises(ValidationError):
            MaintenanceService(admin_ctx).create_ticket(
                room_id=None,
                category=MaintenanceCategory.ELEVATOR,
                title="Asansor takiliyor",
                description="2. katta duruyor.",
                blocks_room=True,
            )

    def test_ortak_alan_arizasi_konum_ister(self, admin_ctx, property_with_rooms):
        with pytest.raises(ValidationError):
            MaintenanceService(admin_ctx).create_ticket(
                room_id=None,
                category=MaintenanceCategory.ELEVATOR,
                title="Asansor takiliyor",
                description="2. katta duruyor.",
            )

    def test_ters_blok_tarihi_reddedilir(self, admin_ctx, sample_rooms):
        today = utcnow().date()
        with pytest.raises(ValidationError):
            MaintenanceService(admin_ctx).create_ticket(
                room_id=sample_rooms[0].id,
                category=MaintenanceCategory.OTHER,
                title="Test",
                description="Test aciklamasi",
                blocks_room=True,
                block_from=today,
                block_until=today - timedelta(days=1),
            )

    def test_bos_baslik_reddedilir(self, admin_ctx, sample_rooms):
        with pytest.raises(ValidationError):
            MaintenanceService(admin_ctx).create_ticket(
                room_id=sample_rooms[0].id,
                category=MaintenanceCategory.OTHER,
                title="   ",
                description="Aciklama",
            )


class TestMaintenanceLifecycle:
    @pytest.fixture
    def blocking_ticket(self, admin_ctx, sample_rooms):
        today = utcnow().date()
        return MaintenanceService(admin_ctx).create_ticket(
            room_id=sample_rooms[2].id,
            category=MaintenanceCategory.PLUMBING,
            title="Su kacagi",
            description="Banyo zeminine su siziyor.",
            priority=Priority.CRITICAL,
            blocks_room=True,
            block_from=today,
            block_until=today + timedelta(days=3),
        )

    def test_teknisyen_atanir(self, admin_ctx, blocking_ticket, technician):
        ticket = MaintenanceService(admin_ctx).assign(blocking_ticket.id, technician.id)

        assert ticket.assigned_employee_id == technician.id
        assert ticket.status is MaintenanceStatus.ASSIGNED
        assert ticket.assigned_at is not None

    def test_resolve_blokeyi_kaldirir_ve_odayi_kirli_yapar(
        self, admin_ctx, blocking_ticket, sample_rooms
    ):
        ticket = MaintenanceService(admin_ctx).resolve(
            blocking_ticket.id,
            resolution_notes="Conta degistirildi.",
            labor_cost=Decimal("450.00"),
        )

        assert ticket.status is MaintenanceStatus.RESOLVED
        assert sample_rooms[2].housekeeping_status is RoomHousekeepingStatus.DIRTY
        assert sample_rooms[2].out_of_service_from is None
        assert sample_rooms[2].out_of_service_until is None
        assert sample_rooms[2].out_of_service_reason is None

    def test_resolve_parca_maliyetini_toplar(self, admin_ctx, blocking_ticket):
        ticket = MaintenanceService(admin_ctx).resolve(
            blocking_ticket.id,
            resolution_notes="Conta ve hortum degisti.",
            labor_cost=Decimal("300.00"),
            parts=[
                PartUsage("Conta", Decimal("2"), Decimal("35.50")),
                PartUsage("Hortum", Decimal("1"), Decimal("129.00")),
            ],
        )

        assert ticket.parts_cost == Decimal("200.00")
        assert ticket.total_cost == Decimal("500.00")
        assert len(ticket.parts) == 2

    def test_ikinci_acik_bloke_varken_oda_serbest_birakilmaz(
        self, admin_ctx, blocking_ticket, sample_rooms
    ):
        """Iki ayri ariza ayni odayi kapatiyorsa biri cozulunce oda acilmamali."""
        today = utcnow().date()
        MaintenanceService(admin_ctx).create_ticket(
            room_id=sample_rooms[2].id,
            category=MaintenanceCategory.ELECTRICAL,
            title="Aydinlatma arizasi",
            description="Tavan spotu yanmiyor.",
            blocks_room=True,
            block_from=today,
            block_until=today + timedelta(days=5),
        )

        MaintenanceService(admin_ctx).resolve(blocking_ticket.id, resolution_notes="Conta degisti.")

        assert sample_rooms[2].housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_bos_cozum_notu_reddedilir(self, admin_ctx, blocking_ticket):
        with pytest.raises(ValidationError):
            MaintenanceService(admin_ctx).resolve(blocking_ticket.id, resolution_notes="  ")

    def test_cozulmeden_kapatilamaz(self, admin_ctx, blocking_ticket):
        with pytest.raises(BusinessRuleError) as hata:
            MaintenanceService(admin_ctx).close(blocking_ticket.id)
        assert hata.value.code == "ticket_not_resolved"

    def test_cozulmus_kayit_kapatilir(self, admin_ctx, blocking_ticket):
        service = MaintenanceService(admin_ctx)
        service.resolve(blocking_ticket.id, resolution_notes="Tamir edildi.")
        ticket = service.close(blocking_ticket.id)

        assert ticket.status is MaintenanceStatus.CLOSED
        assert ticket.closed_at is not None
        assert not ticket.is_open

    def test_ayni_kayit_iki_kez_cozulemez(self, admin_ctx, blocking_ticket):
        service = MaintenanceService(admin_ctx)
        service.resolve(blocking_ticket.id, resolution_notes="Tamir edildi.")

        with pytest.raises(BusinessRuleError) as hata:
            service.resolve(blocking_ticket.id, resolution_notes="Tekrar.")
        assert hata.value.code == "ticket_closed"

    def test_acik_kayitlar_oncelige_gore_sirali_doner(self, admin_ctx, sample_rooms):
        service = MaintenanceService(admin_ctx)
        for priority, title in (
            (Priority.LOW, "Duvar boyasi"),
            (Priority.CRITICAL, "Yangin alarmi"),
            (Priority.NORMAL, "Perde rayi"),
        ):
            service.create_ticket(
                room_id=sample_rooms[0].id,
                category=MaintenanceCategory.OTHER,
                title=title,
                description="Test kaydi",
                priority=priority,
            )

        weights = [t.priority.weight for t in service.open_tickets()]
        assert weights == sorted(weights, reverse=True)
        assert service.open_tickets()[0].title == "Yangin alarmi"

    def test_oncelik_suzgeci_calisir(self, admin_ctx, sample_rooms):
        service = MaintenanceService(admin_ctx)
        service.create_ticket(
            room_id=sample_rooms[0].id,
            category=MaintenanceCategory.OTHER,
            title="Acil is",
            description="Test",
            priority=Priority.URGENT,
        )
        service.create_ticket(
            room_id=sample_rooms[0].id,
            category=MaintenanceCategory.OTHER,
            title="Normal is",
            description="Test",
            priority=Priority.NORMAL,
        )

        urgent = service.open_tickets(priority=Priority.URGENT)
        assert [t.title for t in urgent] == ["Acil is"]

    def test_kapali_kayit_all_tickets_ile_gorunur(self, admin_ctx, blocking_ticket):
        service = MaintenanceService(admin_ctx)
        service.resolve(blocking_ticket.id, resolution_notes="Bitti.")
        service.close(blocking_ticket.id)

        assert service.open_tickets() == []
        assert len(service.all_tickets()) == 1
        assert len(service.all_tickets(status=MaintenanceStatus.CLOSED)) == 1


# --------------------------------------------------------------------------
#  Ucdan uca
# --------------------------------------------------------------------------
class TestOperationsEndToEnd:
    def test_cikistan_sonra_gorev_tamamlanip_oda_yeniden_satilabilir(
        self, admin_ctx, in_house_reservation, sample_rooms
    ):
        """Cikis -> oda kirli -> temizlik gorevi -> tamamla -> oda temiz."""
        frontdesk = FrontdeskService(admin_ctx)
        stay = frontdesk.check_in(in_house_reservation.rooms[0].id, allow_dirty_room=True)
        frontdesk.check_out(stay.id, allow_open_balance=True)

        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.DIRTY

        housekeeping = HousekeepingService(admin_ctx)
        tasks = housekeeping.daily_tasks()
        assert tasks, "Cikista otomatik temizlik gorevi olusmali"

        housekeeping.complete(tasks[0].id, actual_minutes=40)
        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.CLEAN
        assert sample_rooms[0].is_sellable
