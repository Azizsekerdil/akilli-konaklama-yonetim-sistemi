"""Odalar, Kat Hizmetleri ve Teknik Servis ekranlarinin testleri.

Testler gercek bir veritabani (bellek ici SQLite) ve gercek Qt bilesenleri
kullanir; yalnizca iki sey taklit edilir:

* :func:`app.ui.session.session_scope` - arayuz oturumu uygulama
  veritabanina degil, testin gecici oturumuna baglanir.
* Modal kutular (``confirm``, ``show_error``, ``QInputDialog``) - aksi halde
  test kullanici girdisi bekleyerek kilitlenirdi.

``QT_QPA_PLATFORM=offscreen`` kok ``conftest.py`` icinde ayarlidir.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.application.context import ServiceContext
from app.application.services.housekeeping_service import HousekeepingService
from app.application.services.maintenance_service import MaintenanceService
from app.application.services.reservation_service import ReservationService, RoomRequest
from app.domain.enums import (
    EmploymentStatus,
    HousekeepingStatus,
    MaintenanceCategory,
    MaintenanceStatus,
    Priority,
    RoomHousekeepingStatus,
)
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models import Role, Room, User
from app.infrastructure.db.models.operations import MaintenanceTicket
from app.infrastructure.db.models.organization import Department, Employee
from app.security.passwords import hash_password
from app.ui.dialogs import maintenance_dialog as dialog_module
from app.ui.dialogs.maintenance_dialog import (
    MaintenanceDialog,
    ResolveMaintenanceDialog,
    parse_decimal,
)
from app.ui.pages import housekeeping_page as housekeeping_module
from app.ui.pages import maintenance_page as maintenance_module
from app.ui.pages import rooms_page as rooms_module
from app.ui.pages.housekeeping_page import HousekeepingPage, TaskInfo
from app.ui.pages.maintenance_page import MaintenancePage
from app.ui.pages.rooms_page import RoomInfo, RoomsPage
from app.ui.session import UiSession
from app.ui.theme import active_palette, room_status_color

pytestmark = pytest.mark.ui


# --------------------------------------------------------------------------
#  Fiksturler
# --------------------------------------------------------------------------
@pytest.fixture
def patched_scope(secured_session, monkeypatch):
    """Arayuz oturumunu test veritabanina baglar."""

    @contextmanager
    def fake_scope(*, commit: bool = True):
        yield secured_session

    monkeypatch.setattr("app.ui.session.session_scope", fake_scope)
    return secured_session


@pytest.fixture
def staff(patched_scope, sample_property) -> dict[str, Employee]:
    """Kat hizmetleri ve teknik servis departmanlarinda birer personel."""
    people: dict[str, Employee] = {}
    for key, code, name, first, last in (
        ("housekeeper", "KAT", "Kat Hizmetleri", "Bahar", "Yaprakli"),
        ("technician", "TEKNIK", "Teknik Servis", "Poyraz", "Demirli"),
    ):
        department = Department(property_id=sample_property.id, code=code, name=name)
        patched_scope.add(department)
        patched_scope.flush()
        employee = Employee(
            property_id=sample_property.id,
            department_id=department.id,
            employee_code=f"{code}-001",
            first_name=first,
            last_name=last,
            employment_status=EmploymentStatus.ACTIVE,
        )
        patched_scope.add(employee)
        people[key] = employee
    patched_scope.commit()
    return people


@pytest.fixture
def ui_session(
    patched_scope,
    admin_user,
    sample_property,
    sample_room_type,
    sample_rooms,
    sample_rate_plan,
    staff,
) -> UiSession:
    """Tum yetkilere sahip arayuz oturumu."""
    session = UiSession(user=admin_user, token="test-token")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def viewer_ui_session(patched_scope, sample_property, sample_rooms, staff) -> UiSession:
    """Yalnizca goruntuleme yetkisi olan kullanicinin oturumu."""
    role = patched_scope.scalars(select(Role).where(Role.code == "viewer")).one()
    user = User(
        username="izleyici",
        full_name="Test Izleyici",
        password_hash=hash_password("IzleyiciTest2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    patched_scope.add(user)
    patched_scope.commit()

    session = UiSession(user=user, token="viewer-token")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def admin_ctx_for_ui(patched_scope, admin_user, sample_property) -> ServiceContext:
    """Test verisi hazirlamak icin tam yetkili baglam."""
    return ServiceContext(session=patched_scope, user=admin_user, property_id=sample_property.id)


@pytest.fixture
def seeded_rooms(admin_ctx_for_ui, sample_rooms, patched_scope):
    """101 kirli, 102 dolu, 103 servis disi (acik ariza kaydiyla)."""
    sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
    sample_rooms[1].occupancy_status = sample_rooms[1].occupancy_status.OCCUPIED
    patched_scope.commit()

    MaintenanceService(admin_ctx_for_ui).create_ticket(
        room_id=sample_rooms[2].id,
        category=MaintenanceCategory.PLUMBING,
        title="Su kacagi",
        description="Banyo zeminine su siziyor.",
        priority=Priority.CRITICAL,
        blocks_room=True,
        block_from=utcnow().date(),
        block_until=utcnow().date() + timedelta(days=2),
    )
    patched_scope.commit()
    return sample_rooms


@pytest.fixture
def seeded_tasks(admin_ctx_for_ui, sample_rooms, sample_room_type, sample_guest, patched_scope):
    """Bugun icin uretilmis kat hizmetleri gorevleri."""
    today = utcnow().date()
    ReservationService(admin_ctx_for_ui).create_reservation(
        guest_id=sample_guest.id,
        room_requests=[
            RoomRequest(
                room_type_id=sample_room_type.id,
                room_id=sample_rooms[0].id,
                check_in=today - timedelta(days=1),
                check_out=today + timedelta(days=1),
            ),
            RoomRequest(
                room_type_id=sample_room_type.id,
                room_id=sample_rooms[1].id,
                check_in=today - timedelta(days=2),
                check_out=today,
            ),
        ],
    )
    tasks = HousekeepingService(admin_ctx_for_ui).generate_daily_tasks(today)
    patched_scope.commit()
    return tasks


@pytest.fixture
def seeded_tickets(admin_ctx_for_ui, sample_rooms, patched_scope):
    """Uc ariza kaydi: kritik, normal ve kapatilmis."""
    service = MaintenanceService(admin_ctx_for_ui)
    critical = service.create_ticket(
        room_id=sample_rooms[0].id,
        category=MaintenanceCategory.SAFETY,
        title="Yangin alarmi calismiyor",
        description="Panel hata veriyor.",
        priority=Priority.CRITICAL,
    )
    normal = service.create_ticket(
        room_id=sample_rooms[1].id,
        category=MaintenanceCategory.FURNITURE,
        title="Koltuk yirtik",
        description="Kilif degisecek.",
        priority=Priority.NORMAL,
    )
    closed = service.create_ticket(
        room_id=None,
        category=MaintenanceCategory.ELEVATOR,
        title="Asansor takiliyor",
        description="2. katta duruyor.",
        priority=Priority.LOW,
        location_description="Lobi - 2. asansor",
    )
    service.resolve(closed.id, resolution_notes="Servis geldi.", labor_cost=Decimal("500.00"))
    service.close(closed.id)
    patched_scope.commit()
    return {"critical": critical, "normal": normal, "closed": closed}


@pytest.fixture
def rooms_page(qtbot, ui_session, seeded_rooms) -> RoomsPage:
    page = RoomsPage(ui_session)
    qtbot.addWidget(page)
    page.on_shown()
    return page


@pytest.fixture
def housekeeping_page(qtbot, ui_session, seeded_tasks) -> HousekeepingPage:
    page = HousekeepingPage(ui_session)
    qtbot.addWidget(page)
    page.on_shown()
    return page


@pytest.fixture
def maintenance_page(qtbot, ui_session, seeded_tickets) -> MaintenancePage:
    page = MaintenancePage(ui_session)
    qtbot.addWidget(page)
    page.on_shown()
    return page


def find_room(page: RoomsPage, number: str) -> RoomInfo:
    for info in page._rooms:
        if info.number == number:
            return info
    raise AssertionError(f"{number} numarali oda ekranda yok.")


def find_task(page: HousekeepingPage, room_number: str) -> TaskInfo:
    for task in page._tasks:
        if task.room_number == room_number:
            return task
    raise AssertionError(f"{room_number} numarali odanin gorevi listede yok.")


def select_task(page: HousekeepingPage, task: TaskInfo) -> None:
    for position, row in enumerate(page._table.visible_rows()):
        if row.task_id == task.task_id:
            page._table.table.selectRow(position)
            return
    raise AssertionError("Gorev tabloda gorunmuyor.")


def select_ticket(page: MaintenancePage, ticket_number: str) -> None:
    for position, row in enumerate(page._table.visible_rows()):
        if row.ticket_number == ticket_number:
            page._table.table.selectRow(position)
            return
    raise AssertionError(f"{ticket_number} kaydi tabloda gorunmuyor.")


# --------------------------------------------------------------------------
#  Odalar ekrani
# --------------------------------------------------------------------------
class TestRoomsPage:
    def test_ekran_olusur_ve_odalari_yukler(self, rooms_page):
        assert len(rooms_page._rooms) == 3
        assert rooms_page._table.total_count == 3
        assert set(rooms_page._tiles) == {info.room_id for info in rooms_page._rooms}

    def test_ozet_satiri_dolu_kirli_ve_servis_disi_sayar(self, rooms_page):
        text = rooms_page._summary_label.text()
        assert "3 oda" in text
        assert "1 dolu" in text
        assert "1 kirli" in text
        assert "1 servis disi" in text

    def test_oda_karti_rengi_durumla_tutarli(self, rooms_page):
        """Renk yalnizca bir sinyaldir; durum METNI de kartta yazmalidir."""
        palette = active_palette()
        for info in rooms_page._rooms:
            tile = rooms_page._tiles[info.room_id]
            expected = room_status_color(palette, info.occupancy, info.housekeeping)
            assert expected in tile.styleSheet()
            assert info.housekeeping_label in info.status_text

        dirty = find_room(rooms_page, "101")
        occupied = find_room(rooms_page, "102")
        blocked = find_room(rooms_page, "103")
        assert room_status_color(palette, dirty.occupancy, dirty.housekeeping) == (
            palette.room_vacant_dirty
        )
        assert room_status_color(palette, occupied.occupancy, occupied.housekeeping) == (
            palette.room_occupied
        )
        assert room_status_color(palette, blocked.occupancy, blocked.housekeeping) == (
            palette.room_out_of_service
        )

    def test_ariza_kaydi_ayrinti_panelinde_gorunur(self, rooms_page):
        rooms_page._select_room(find_room(rooms_page, "103"))
        assert "Su kacagi" in rooms_page._detail_fields["ticket"].text()
        assert rooms_page._detail_fields["housekeeping"].text() == "Servis Disi"

    def test_durum_suzgeci_liste_satirlarini_azaltir(self, rooms_page):
        index = rooms_page._status_filter.findData(RoomHousekeepingStatus.DIRTY.value)
        rooms_page._status_filter.setCurrentIndex(index)

        assert rooms_page._table.visible_count == 1
        assert rooms_page._table.visible_rows()[0].number == "101"
        assert "1 / 3 oda" in rooms_page._list_count.text()

    def test_bos_sonucta_empty_state_gorunur(self, rooms_page):
        rooms_page._search.setText("boyle-bir-oda-yok")
        rooms_page._apply_filters()

        assert rooms_page._table.visible_count == 0
        assert rooms_page._list_empty.isVisible() or not rooms_page._table.isVisible()

    def test_yetkisiz_kullanicida_durum_dugmeleri_pasif(self, qtbot, viewer_ui_session):
        page = RoomsPage(viewer_ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        assert page._status_buttons
        assert all(not button.isEnabled() for button in page._status_buttons)

    def test_durum_degistirme_odayi_gunceller(self, monkeypatch, rooms_page, patched_scope):
        monkeypatch.setattr(rooms_module, "confirm", lambda *args, **kwargs: True)
        monkeypatch.setattr(rooms_module, "show_toast", lambda *args, **kwargs: None)

        rooms_page._change_status(find_room(rooms_page, "101"), RoomHousekeepingStatus.CLEAN)

        assert find_room(rooms_page, "101").housekeeping == RoomHousekeepingStatus.CLEAN.value
        room = patched_scope.scalars(select(Room).where(Room.number == "101")).one()
        assert room.housekeeping_status is RoomHousekeepingStatus.CLEAN

    def test_satilmis_oda_kapatilirken_uyari_gosterilir(
        self,
        monkeypatch,
        rooms_page,
        patched_scope,
        admin_ctx_for_ui,
        sample_room_type,
        sample_rooms,
        sample_guest,
    ):
        """KRITIK: cakisan rezervasyon varsa onaylanmadan oda kapanmamalidir."""
        today = utcnow().date()
        ReservationService(admin_ctx_for_ui).create_reservation(
            guest_id=sample_guest.id,
            room_requests=[
                RoomRequest(
                    room_type_id=sample_room_type.id,
                    room_id=sample_rooms[0].id,
                    check_in=today - timedelta(days=1),
                    check_out=today + timedelta(days=1),
                )
            ],
        )
        patched_scope.commit()
        rooms_page.refresh(force=True)

        seen: list[str] = []
        monkeypatch.setattr(rooms_module, "confirm", lambda *args, **kwargs: True)
        monkeypatch.setattr(rooms_module, "show_toast", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            rooms_module,
            "show_error",
            lambda _parent, exc, **kwargs: seen.append(exc.code),
        )

        # Kullanici uyariyi REDDEDERSE oda kapanmaz.
        monkeypatch.setattr(rooms_page, "_offer_override", lambda _exc: False, raising=False)
        rooms_page._change_status(
            find_room(rooms_page, "101"), RoomHousekeepingStatus.OUT_OF_SERVICE
        )
        room = patched_scope.scalars(select(Room).where(Room.number == "101")).one()
        assert room.housekeeping_status is not RoomHousekeepingStatus.OUT_OF_SERVICE

        # Yetkili kullanici onaylarsa islem gerceklesir.
        monkeypatch.setattr(rooms_page, "_offer_override", lambda _exc: True, raising=False)
        rooms_page._change_status(
            find_room(rooms_page, "101"), RoomHousekeepingStatus.OUT_OF_SERVICE
        )
        room = patched_scope.scalars(select(Room).where(Room.number == "101")).one()
        assert room.housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_yetkisiz_kullaniciya_asma_secenegi_sunulmaz(
        self, qtbot, monkeypatch, viewer_ui_session
    ):
        """'reservation.override' yoksa uyari gosterilir, secenek verilmez.

        Aksi halde kullanici onaylar, servis reddeder ve ekranda anlamsiz bir
        "yetkiniz yok" hatasi belirirdi.
        """
        from app.core.exceptions import BusinessRuleError

        page = RoomsPage(viewer_ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        shown: list[str] = []
        monkeypatch.setattr(
            rooms_module, "show_error", lambda _parent, exc, **kwargs: shown.append(exc.code)
        )
        monkeypatch.setattr(
            rooms_module,
            "confirm",
            lambda *args, **kwargs: pytest.fail("Yetkisiz kullaniciya onay sorulmamaliydi."),
        )

        assert (
            page._offer_override(BusinessRuleError("Cakisma var", code="room_has_reservation"))
            is False
        )
        assert shown == ["room_has_reservation"]


class TestRoomInfo:
    """Bina/kat gruplamasi ve dogal siralama."""

    @staticmethod
    def _info(number: str, floor: str, order: int, building: str | None) -> RoomInfo:
        return RoomInfo(
            room_id=hash(number) & 0xFFFF,
            number=number,
            room_type_id=1,
            room_type_name="Standart Oda",
            floor_label=floor,
            floor_order=order,
            occupancy="vacant",
            occupancy_label="Bos",
            housekeeping="clean",
            housekeeping_label="Temiz",
            building_name=building,
        )

    def test_bina_adi_kat_etiketine_eklenir(self):
        info = self._info("101", "1. Kat", 1, "Ana Bina")
        assert info.location_label == "Ana Bina - 1. Kat"

    def test_binasiz_kat_etiketi_degismez(self):
        info = self._info("101", "1. Kat", 1, None)
        assert info.location_label == "1. Kat"

    def test_iki_binanin_odalari_ic_ice_gecmez(self):
        """Bina ayrimi olmasa "101, B101, 102, B102" sirasi olusurdu."""
        rooms = [
            self._info("B101", "1. Kat", 1, "Deniz Blok"),
            self._info("102", "1. Kat", 1, "Ana Bina"),
            self._info("B102", "1. Kat", 1, "Deniz Blok"),
            self._info("101", "1. Kat", 1, "Ana Bina"),
        ]
        order = [info.number for info in sorted(rooms, key=lambda i: i.sort_key)]
        assert order == ["101", "102", "B101", "B102"]

    def test_oda_numarasi_sayisal_siralanir(self):
        """Metin siralamasi "1001"i "99"dan once koyardi."""
        rooms = [
            self._info("1001", "10. Kat", 10, None),
            self._info("99", "10. Kat", 10, None),
        ]
        order = [info.number for info in sorted(rooms, key=lambda i: i.sort_key)]
        assert order == ["99", "1001"]


def test_devre_disi_birincil_dugme_stili_tanimli():
    """Birincil dugme devre disiyken parlak kalmamali - kullaniciyi yanildir."""
    style = rooms_module.operations_style()
    palette = active_palette()
    assert "QPushButton#Primary:disabled" in style
    assert palette.text_disabled in style
    assert "background: transparent" in style


# --------------------------------------------------------------------------
#  Kat hizmetleri ekrani
# --------------------------------------------------------------------------
class TestHousekeepingPage:
    def test_ekran_gunun_gorevlerini_yukler(self, housekeeping_page, seeded_tasks):
        assert len(housekeeping_page._tasks) == len(seeded_tasks) == 2
        assert housekeeping_page._table.total_count == 2
        assert {task.room_number for task in housekeeping_page._tasks} == {"101", "102"}

    def test_ozet_kartlari_durumlari_sayar(self, housekeeping_page):
        assert housekeeping_page._kpis["pending"]._value.text() == "2"
        assert housekeeping_page._kpis["completed"]._value.text() == "0"

    def test_gorev_olustur_dugmesi_idempotent(self, monkeypatch, housekeeping_page):
        """Ikinci kez basmak gorev tekrarlamaz; kullaniciya bilgi verilir."""
        messages: list[str] = []
        monkeypatch.setattr(
            housekeeping_module,
            "show_toast",
            lambda _parent, message, *args, **kwargs: messages.append(message),
        )

        housekeeping_page._generate_tasks()

        assert housekeeping_page._table.total_count == 2
        assert "zaten hazir" in messages[-1]

    def test_atama_gorevi_personele_baglar(self, monkeypatch, housekeeping_page, staff):
        monkeypatch.setattr(housekeeping_module, "show_toast", lambda *args, **kwargs: None)
        task = find_task(housekeeping_page, "101")
        select_task(housekeeping_page, task)

        position = housekeeping_page._employee_combo.findData(staff["housekeeper"].id)
        housekeeping_page._employee_combo.setCurrentIndex(position)
        housekeeping_page._assign_selected()

        updated = find_task(housekeeping_page, "101")
        assert updated.employee_name == "Bahar Yaprakli"
        assert updated.status == HousekeepingStatus.ASSIGNED.value

    def test_tamamla_odayi_temiz_yapar(self, monkeypatch, housekeeping_page, patched_scope):
        monkeypatch.setattr(housekeeping_module, "show_toast", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            housekeeping_module.QInputDialog,
            "getInt",
            staticmethod(lambda *args, **kwargs: (32, True)),
        )
        select_task(housekeeping_page, find_task(housekeeping_page, "101"))
        housekeeping_page._complete_selected()

        updated = find_task(housekeeping_page, "101")
        assert updated.status == HousekeepingStatus.COMPLETED.value
        assert updated.actual_minutes == 32
        room = patched_scope.scalars(select(Room).where(Room.number == "101")).one()
        assert room.housekeeping_status is RoomHousekeepingStatus.CLEAN

    def test_dugmeler_gorev_durumuna_gore_etkinlesir(self, monkeypatch, housekeeping_page):
        assert not housekeeping_page._inspect_button.isEnabled()  # secim yok

        select_task(housekeeping_page, find_task(housekeeping_page, "101"))
        assert housekeeping_page._start_button.isEnabled()
        assert housekeeping_page._complete_button.isEnabled()
        # Tamamlanmamis gorev kontrol edilemez.
        assert not housekeeping_page._inspect_button.isEnabled()

        monkeypatch.setattr(housekeeping_module, "show_toast", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            housekeeping_module.QInputDialog,
            "getInt",
            staticmethod(lambda *args, **kwargs: (20, True)),
        )
        housekeeping_page._complete_selected()
        select_task(housekeeping_page, find_task(housekeeping_page, "101"))

        assert housekeeping_page._inspect_button.isEnabled()
        assert not housekeeping_page._start_button.isEnabled()

    def test_yetkisiz_kullanicida_islem_dugmeleri_pasif(self, qtbot, viewer_ui_session):
        page = HousekeepingPage(viewer_ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        assert not page._generate_button.isEnabled()
        assert not page._assign_button.isEnabled()
        assert not page._complete_button.isEnabled()
        assert not page._inspect_button.isEnabled()

    def test_gorev_yoksa_empty_state_gorunur(self, qtbot, ui_session):
        page = HousekeepingPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        assert page._table.total_count == 0
        assert page._empty.isVisible() or not page._table.isVisible()


# --------------------------------------------------------------------------
#  Teknik servis ekrani
# --------------------------------------------------------------------------
class TestMaintenancePage:
    def test_ekran_kayitlari_yukler(self, maintenance_page):
        assert len(maintenance_page._tickets) == 3
        assert maintenance_page._table.total_count == 3

    def test_liste_oncelige_gore_sirali(self, maintenance_page):
        """Alfabetik sirada 'Acil' 'Kritik'ten once gelirdi - agirlik kullanilir."""
        # Varsayilan suzgec yalnizca acik kayitlari gosterir.
        weights = [row.priority_weight for row in maintenance_page._table.visible_rows()]
        assert weights == sorted(weights, reverse=True)
        assert maintenance_page._table.visible_rows()[0].priority == Priority.CRITICAL.value

    def test_varsayilan_suzgec_kapali_kayitlari_gizler(self, maintenance_page, seeded_tickets):
        visible = {row.ticket_number for row in maintenance_page._table.visible_rows()}
        assert seeded_tickets["closed"].ticket_number not in visible

        index = maintenance_page._status_filter.findData(None)  # "Tumu"
        maintenance_page._status_filter.setCurrentIndex(index)
        visible = {row.ticket_number for row in maintenance_page._table.visible_rows()}
        assert seeded_tickets["closed"].ticket_number in visible

    def test_ozet_kartlari_acik_kayitlari_sayar(self, maintenance_page):
        assert maintenance_page._kpis["open"]._value.text() == "2"
        assert maintenance_page._kpis["urgent"]._value.text() == "1"
        # Turkce bicim: binlik nokta, ondalik VIRGUL.
        assert maintenance_page._kpis["cost"]._value.text() == "500,00 TL"

    def test_teknisyen_atama_kaydi_gunceller(self, monkeypatch, maintenance_page, staff):
        monkeypatch.setattr(maintenance_module, "show_toast", lambda *args, **kwargs: None)
        select_ticket(
            maintenance_page,
            maintenance_page._table.visible_rows()[0].ticket_number,
        )
        position = maintenance_page._technician_combo.findData(staff["technician"].id)
        maintenance_page._technician_combo.setCurrentIndex(position)
        maintenance_page._assign_selected()

        row = maintenance_page._table.visible_rows()[0]
        assert row.technician == "Poyraz Demirli"
        assert row.status == MaintenanceStatus.ASSIGNED.value

    def test_yetkisiz_kullanicida_dugmeler_pasif(self, qtbot, viewer_ui_session):
        page = MaintenancePage(viewer_ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        assert not page._new_button.isEnabled()
        assert not page._assign_button.isEnabled()
        assert not page._resolve_button.isEnabled()
        assert not page._close_button.isEnabled()

    def test_ortak_alan_kaydi_konumu_ariza_sutununda_gosterir(
        self, maintenance_page, seeded_tickets
    ):
        index = maintenance_page._status_filter.findData(None)
        maintenance_page._status_filter.setCurrentIndex(index)

        row = next(
            r
            for r in maintenance_page._table.visible_rows()
            if r.ticket_number == seeded_tickets["closed"].ticket_number
        )
        assert row.room_label == "Ortak alan"
        assert "Lobi - 2. asansor" in row.summary


# --------------------------------------------------------------------------
#  Diyaloglar
# --------------------------------------------------------------------------
class TestMaintenanceDialog:
    def test_diyalog_kayit_olusturur(self, qtbot, ui_session, sample_rooms, patched_scope):
        dialog = MaintenanceDialog(ui_session)
        qtbot.addWidget(dialog)

        dialog._room_combo.setCurrentIndex(dialog._room_combo.findData(sample_rooms[0].id))
        dialog._title_edit.setText("Musluk damlatiyor")
        dialog._description_edit.setPlainText("Lavabo bataryasi conta degisimi istiyor.")
        dialog._submit()

        assert dialog.created_ticket_id is not None
        ticket = patched_scope.get(MaintenanceTicket, dialog.created_ticket_id)
        assert ticket.title == "Musluk damlatiyor"
        assert ticket.blocks_room is False

    def test_oda_secilince_konum_alani_kapanir(self, qtbot, ui_session, sample_rooms):
        dialog = MaintenanceDialog(ui_session)
        qtbot.addWidget(dialog)

        assert dialog._location_edit.isEnabled()  # varsayilan: ortak alan
        dialog._room_combo.setCurrentIndex(dialog._room_combo.findData(sample_rooms[0].id))
        assert not dialog._location_edit.isEnabled()

    def test_cakisan_rezervasyonda_onay_istenir_ve_asilabilir(
        self,
        qtbot,
        monkeypatch,
        ui_session,
        admin_ctx_for_ui,
        sample_rooms,
        sample_room_type,
        sample_guest,
        patched_scope,
    ):
        """KRITIK: satilmis oda ancak bilincli onayla kapatilabilir."""
        today = utcnow().date()
        ReservationService(admin_ctx_for_ui).create_reservation(
            guest_id=sample_guest.id,
            room_requests=[
                RoomRequest(
                    room_type_id=sample_room_type.id,
                    room_id=sample_rooms[0].id,
                    check_in=today,
                    check_out=today + timedelta(days=2),
                )
            ],
        )
        patched_scope.commit()

        asked: list[str] = []
        monkeypatch.setattr(
            dialog_module,
            "confirm",
            lambda _parent, message, **kwargs: (asked.append(message), True)[1],
        )

        dialog = MaintenanceDialog(ui_session)
        qtbot.addWidget(dialog)
        dialog._room_combo.setCurrentIndex(dialog._room_combo.findData(sample_rooms[0].id))
        dialog._title_edit.setText("Klima arizasi")
        dialog._description_edit.setPlainText("Kompresor degisecek.")
        dialog._block_check.setChecked(True)
        dialog._submit()

        assert asked, "Cakisma uyarisi kullaniciya gosterilmeliydi"
        assert "rezervasyon" in asked[0].lower()
        assert dialog.created_ticket_id is not None
        room = patched_scope.get(Room, sample_rooms[0].id)
        assert room.housekeeping_status is RoomHousekeepingStatus.OUT_OF_SERVICE

    def test_yetkisiz_kullanicida_bloke_secenegi_pasif(self, qtbot, viewer_ui_session):
        dialog = MaintenanceDialog(viewer_ui_session)
        qtbot.addWidget(dialog)
        assert not dialog._block_check.isEnabled()

    def test_cozum_diyalogu_parcalari_ve_maliyeti_kaydeder(
        self, qtbot, ui_session, seeded_tickets, patched_scope
    ):
        ticket = seeded_tickets["critical"]
        dialog = ResolveMaintenanceDialog(ui_session, ticket.id, "Test kaydi")
        qtbot.addWidget(dialog)

        dialog._notes_edit.setPlainText("Panel degistirildi.")
        dialog._labor_spin.setValue(750.0)
        dialog._add_part_row()
        dialog._parts_table.item(0, 0).setText("Alarm paneli")
        dialog._parts_table.item(0, 1).setText("1")
        dialog._parts_table.item(0, 2).setText("1.250,50")
        dialog._submit()

        saved = patched_scope.get(MaintenanceTicket, ticket.id)
        assert saved.status is MaintenanceStatus.RESOLVED
        assert saved.labor_cost == Decimal("750.00")
        assert saved.parts_cost == Decimal("1250.50")
        assert saved.total_cost == Decimal("2000.50")

    def test_bos_parca_satiri_atlanir(self, qtbot, ui_session, seeded_tickets):
        dialog = ResolveMaintenanceDialog(ui_session, seeded_tickets["critical"].id, "Test")
        qtbot.addWidget(dialog)
        dialog._add_part_row()  # bos birakilir
        assert dialog.collect_parts() == []

    def test_turkce_ondalik_ayirici_okunur(self):
        """Turkce klavyede ondalik ayirici virguldur: '1.250,50' -> 1250.50."""
        assert parse_decimal("1.250,50", field="test") == Decimal("1250.50")
        assert parse_decimal("42", field="test") == Decimal("42")
        assert parse_decimal("", field="test") == Decimal("0.00")
