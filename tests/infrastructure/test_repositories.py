"""Repository katmani testleri.

Odak noktalari
--------------
* **Yari acik aralik** semantiginin SQL tarafinda dogru uygulanmasi
  (bitisik rezervasyon cakisma uretmemeli).
* Envanteri bloke etmemesi gereken kayitlarin musaitlik hesabina
  **sizmamasi**: iptal edilen rezervasyon, iptal edilen oda satiri,
  mantiksal silinmis rezervasyon ve oda atanmamis satir.
* Sifreli kimlik alaninda kor indeks uzerinden arama.
* Bakim/ariza kaynakli oda bloklarinin domain nesnelerine dogru cevrilmesi.

Tum ornek veriler uydurmadir; gercek kisi, kimlik veya iletisim bilgisi
kullanilmaz.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.domain.enums import (
    ChargeType,
    FolioStatus,
    HousekeepingStatus,
    MaintenanceStatus,
    PaymentMethod,
    Priority,
    ReservationStatus,
    RoomHousekeepingStatus,
    StockMovementType,
)
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models import (
    Charge,
    Folio,
    Guest,
    HousekeepingTask,
    InventoryItem,
    MaintenanceTicket,
    Payment,
    Property,
    Reservation,
    ReservationRoom,
    Room,
    RoomType,
    Stay,
    StockMovement,
)
from app.infrastructure.db.repositories import (
    FolioRepository,
    GuestRepository,
    InventoryRepository,
    OperationsRepository,
    ReservationRepository,
    RoomRepository,
)

pytestmark = pytest.mark.integration

#: Testlerde benzersiz onay numarasi uretmek icin sayac.
#: "RZV-" onegi bilerek kullanilmaz; next_confirmation_number testleri
#: kendi numaralarini kontrollu olarak olusturur.
_counter = itertools.count(1)


def _confirmation() -> str:
    return f"TST-{next(_counter):06d}"


# --------------------------------------------------------------------------
#  Yardimci fabrikalar
# --------------------------------------------------------------------------
def make_reservation(
    session: Session,
    *,
    hotel_property: Property,
    guest: Guest,
    room_type: RoomType,
    start: date,
    end: date,
    room: Room | None = None,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
    room_cancelled: bool = False,
    deleted: bool = False,
    confirmation_number: str | None = None,
) -> Reservation:
    """Tek oda satirli bir rezervasyon olusturur."""
    reservation = Reservation(
        property_id=hotel_property.id,
        confirmation_number=confirmation_number or _confirmation(),
        status=status,
        primary_guest_id=guest.id,
        check_in_date=start,
        check_out_date=end,
    )
    if deleted:
        reservation.mark_deleted()
    session.add(reservation)
    session.flush()

    session.add(
        ReservationRoom(
            reservation_id=reservation.id,
            room_type_id=room_type.id,
            room_id=room.id if room is not None else None,
            check_in_date=start,
            check_out_date=end,
            is_cancelled=room_cancelled,
        )
    )
    session.commit()
    return reservation


def make_folio(
    session: Session,
    *,
    hotel_property: Property,
    number: str,
    reservation: Reservation | None = None,
    guest: Guest | None = None,
    status: FolioStatus = FolioStatus.OPEN,
    balance: Decimal = Decimal("0.00"),
) -> Folio:
    folio = Folio(
        property_id=hotel_property.id,
        folio_number=number,
        reservation_id=reservation.id if reservation is not None else None,
        guest_id=guest.id if guest is not None else None,
        status=status,
        balance=balance,
        total_charges=balance,
    )
    session.add(folio)
    session.commit()
    return folio


def make_charge(
    session: Session,
    *,
    folio: Folio,
    charge_type: ChargeType,
    day: date,
    amount: Decimal,
    is_void: bool = False,
) -> Charge:
    charge = Charge(
        folio_id=folio.id,
        charge_type=charge_type,
        description=f"{charge_type.value} kalemi",
        charge_date=day,
        quantity=Decimal("1.000"),
        unit_price=amount,
        net_amount=amount,
        total_amount=amount,
        is_void=is_void,
    )
    session.add(charge)
    session.commit()
    return charge


def make_item(
    session: Session,
    *,
    hotel_property: Property,
    sku: str,
    name: str,
    current: Decimal,
    minimum: Decimal,
    is_active: bool = True,
) -> InventoryItem:
    item = InventoryItem(
        property_id=hotel_property.id,
        sku=sku,
        name=name,
        category="Minibar",
        current_stock=current,
        minimum_stock=minimum,
        is_active=is_active,
    )
    session.add(item)
    session.commit()
    return item


def make_movement(
    session: Session,
    *,
    item: InventoryItem,
    movement_type: StockMovementType,
    day: date,
    quantity: Decimal,
    stock_after: Decimal | None = None,
) -> StockMovement:
    movement = StockMovement(
        inventory_item_id=item.id,
        movement_type=movement_type,
        movement_date=day,
        quantity=quantity,
        stock_after=stock_after,
    )
    session.add(movement)
    session.commit()
    return movement


# --------------------------------------------------------------------------
#  Taban repository
# --------------------------------------------------------------------------
class TestBaseRepository:
    def test_get_or_404_bulunamayan_kayitta_hata_firlatir(self, session, sample_property):
        repo = RoomRepository(session)
        with pytest.raises(NotFoundError) as exc:
            repo.get_or_404(9999)
        # Kullaniciya giden mesaj teknik ayrinti icermemeli.
        assert "Oda" in exc.value.user_message
        assert "9999" not in exc.value.user_message

    def test_get_mantiksal_silinmis_kaydi_dondurmez(self, session, sample_guest):
        repo = GuestRepository(session)
        assert repo.get(sample_guest.id) is not None

        repo.delete(sample_guest)
        session.commit()

        assert repo.get(sample_guest.id) is None
        assert repo.exists(sample_guest.id) is False
        # Bilerek istenirse yine erisilebilir - denetim ekranlari icin.
        assert repo.get(sample_guest.id, include_deleted=True) is not None

    def test_count_silinmis_kayitlari_saymaz(self, session, sample_guest):
        repo = GuestRepository(session)
        assert repo.count() == 1
        repo.delete(sample_guest)
        session.commit()
        assert repo.count() == 0
        assert repo.count(include_deleted=True) == 1

    def test_list_sayfalama_uygular(self, session, sample_property, sample_rooms):
        repo = RoomRepository(session)
        ilk_sayfa = repo.list(limit=2)
        ikinci_sayfa = repo.list(limit=2, offset=2)
        assert len(ilk_sayfa) == 2
        assert len(ikinci_sayfa) == 1
        # Sayfalar ortusmemeli.
        assert {r.id for r in ilk_sayfa}.isdisjoint({r.id for r in ikinci_sayfa})

    def test_add_flush_ile_birincil_anahtar_atar(self, session, sample_property, sample_room_type):
        repo = RoomRepository(session)
        oda = Room(
            property_id=sample_property.id,
            room_type_id=sample_room_type.id,
            number="901",
        )
        assert oda.id is None
        repo.add(oda)
        assert oda.id is not None


# --------------------------------------------------------------------------
#  Oda repository
# --------------------------------------------------------------------------
class TestRoomRepository:
    def test_list_rooms_numaraya_gore_sirali(self, session, sample_property, sample_rooms):
        repo = RoomRepository(session)
        assert [r.number for r in repo.list_rooms(sample_property.id)] == ["101", "102", "103"]

    def test_list_rooms_only_sellable_bakimdaki_odayi_atlar(
        self, session, sample_property, sample_rooms
    ):
        sample_rooms[1].housekeeping_status = RoomHousekeepingStatus.OUT_OF_ORDER
        session.commit()

        repo = RoomRepository(session)
        satilabilir = repo.list_rooms(sample_property.id, only_sellable=True)
        assert [r.number for r in satilabilir] == ["101", "103"]

    def test_get_by_number(self, session, sample_property, sample_rooms):
        repo = RoomRepository(session)
        assert repo.get_by_number(sample_property.id, "102").id == sample_rooms[1].id
        assert repo.get_by_number(sample_property.id, "999") is None

    def test_rooms_by_type_gruplar(self, session, sample_property, sample_room_type, sample_rooms):
        repo = RoomRepository(session)
        gruplar = repo.rooms_by_type(sample_property.id)
        assert set(gruplar) == {sample_room_type.id}
        assert len(gruplar[sample_room_type.id]) == 3

    def test_count_rooms_arizali_odayi_paydadan_duser(self, session, sample_property, sample_rooms):
        repo = RoomRepository(session)
        assert repo.count_rooms(sample_property.id) == 3

        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.OUT_OF_ORDER
        # Servis disi oda envanterde kalir, arizali oda cikar.
        sample_rooms[1].housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        session.commit()

        assert repo.count_rooms(sample_property.id) == 2
        assert repo.count_rooms(sample_property.id, exclude_out_of_order=False) == 3

    def test_blocks_for_range_bakimdaki_odayi_dondurur(
        self, session, sample_property, sample_rooms, today
    ):
        oda = sample_rooms[0]
        oda.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        oda.out_of_service_from = today
        oda.out_of_service_until = today + timedelta(days=2)
        oda.out_of_service_reason = "Klima arizasi"
        session.commit()

        repo = RoomRepository(session)
        bloklar = repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(5)))

        assert len(bloklar) == 1
        blok = bloklar[0]
        assert blok.room_id == oda.id
        assert blok.reason == "Klima arizasi"
        # until DAHIL bir gundur -> yari acik aralikta bir gun eklenir.
        assert blok.date_range == DateRange(today, today + timedelta(days=3))
        assert blok.blocks(DateRange(today + timedelta(2), today + timedelta(4))) is True
        assert blok.blocks(DateRange(today + timedelta(3), today + timedelta(4))) is False

    def test_blocks_for_range_aralik_disindaki_blogu_dondurmez(
        self, session, sample_property, sample_rooms, today
    ):
        oda = sample_rooms[0]
        oda.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        oda.out_of_service_from = today + timedelta(days=20)
        oda.out_of_service_until = today + timedelta(days=25)
        session.commit()

        repo = RoomRepository(session)
        bloklar = repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(5)))
        assert bloklar == []

    def test_blocks_for_range_tarihsiz_blok_suresizdir(
        self, session, sample_property, sample_rooms, today
    ):
        oda = sample_rooms[2]
        oda.housekeeping_status = RoomHousekeepingStatus.OUT_OF_ORDER
        session.commit()

        repo = RoomRepository(session)
        bloklar = repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(2)))
        assert len(bloklar) == 1
        assert bloklar[0].date_range is None
        assert bloklar[0].blocks(DateRange(today, today + timedelta(days=1))) is True

    def test_blocks_for_range_acik_ariza_kaydini_da_kapsar(
        self, session, sample_property, sample_rooms, today
    ):
        """Oda durumu guncellenmemis olsa bile ariza kaydi odayi kapatmali."""
        oda = sample_rooms[1]
        assert oda.housekeeping_status is RoomHousekeepingStatus.CLEAN

        session.add(
            MaintenanceTicket(
                property_id=sample_property.id,
                ticket_number="ARZ-2026-000001",
                room_id=oda.id,
                title="Su kacagi",
                description="Banyoda su kacagi tespit edildi.",
                reported_at=utcnow(),
                status=MaintenanceStatus.IN_PROGRESS,
                blocks_room=True,
                block_from=today + timedelta(days=1),
                block_until=today + timedelta(days=1),
            )
        )
        session.commit()

        repo = RoomRepository(session)
        bloklar = repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(5)))
        assert [b.room_id for b in bloklar] == [oda.id]
        assert bloklar[0].date_range == DateRange(
            today + timedelta(days=1), today + timedelta(days=2)
        )

    def test_blocks_for_range_pencere_basindaki_son_gunu_kapsar(
        self, session, sample_property, sample_rooms, today
    ):
        """``until`` pencerenin ilk gunune esitse o gece hala kapali olmali.

        Bu, "dahil son gun" -> "yari acik aralik" donusumunun sinir
        durumudur: bir gun eklenmeseydi blok bos bir aralik olur ve odanin
        son kapali gecesi satilabilir gorunurdu.
        """
        oda = sample_rooms[0]
        oda.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        oda.out_of_service_from = today - timedelta(days=5)
        oda.out_of_service_until = today
        session.commit()

        repo = RoomRepository(session)
        bloklar = repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(3)))
        assert len(bloklar) == 1
        assert bloklar[0].blocks(DateRange(today, today + timedelta(days=1))) is True
        # Ertesi gece artik serbest.
        assert bloklar[0].blocks(DateRange(today + timedelta(1), today + timedelta(2))) is False

        # Bir gun once biten blok pencereye hic girmemeli.
        oda.out_of_service_until = today - timedelta(days=1)
        session.commit()
        assert (
            repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(3))) == []
        )

    def test_blocks_for_range_bozuk_tarihte_suresiz_kabul_eder(
        self, session, sample_property, sample_rooms, today
    ):
        """Bitis < baslangic olan bozuk kayitta oda fazladan kapatilmali.

        Satilamayacak bir odayi yanlislikla satmak, fazladan kapatmaktan
        cok daha pahali bir hatadir.
        """
        oda = sample_rooms[0]
        oda.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        oda.out_of_service_from = today + timedelta(days=2)
        oda.out_of_service_until = today
        session.commit()

        repo = RoomRepository(session)
        bloklar = repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(5)))
        assert len(bloklar) == 1
        assert bloklar[0].date_range is None
        assert bloklar[0].blocks(DateRange(today, today + timedelta(days=1))) is True

    def test_blocks_for_range_kapanmis_ariza_kaydini_yok_sayar(
        self, session, sample_property, sample_rooms, today
    ):
        session.add(
            MaintenanceTicket(
                property_id=sample_property.id,
                ticket_number="ARZ-2026-000002",
                room_id=sample_rooms[1].id,
                title="Ampul degisimi",
                description="Tamamlandi.",
                reported_at=utcnow(),
                status=MaintenanceStatus.CLOSED,
                blocks_room=True,
                block_from=today,
                block_until=today + timedelta(days=3),
            )
        )
        session.commit()

        repo = RoomRepository(session)
        assert (
            repo.blocks_for_range(sample_property.id, DateRange(today, today + timedelta(5))) == []
        )


# --------------------------------------------------------------------------
#  Rezervasyon repository
# --------------------------------------------------------------------------
class TestReservationRepositoryBookings:
    def test_bookings_for_range_cakisan_rezervasyonu_dondurur(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=2),
            confirmation_number="TST-CAKISMA",
        )
        repo = ReservationRepository(session)
        bookings = repo.bookings_for_range(
            sample_property.id, DateRange(today + timedelta(1), today + timedelta(3))
        )
        assert len(bookings) == 1
        assert bookings[0].room_id == sample_rooms[0].id
        assert bookings[0].confirmation_number == "TST-CAKISMA"
        assert bookings[0].date_range == DateRange(today, today + timedelta(days=2))

    def test_bookings_for_range_bitisik_rezervasyonu_dondurmez(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        """Yari acik aralik: cikis gunu = yeni girisin gunu ise cakisma yoktur."""
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=2),
        )
        repo = ReservationRepository(session)
        bitisik = DateRange(today + timedelta(days=2), today + timedelta(days=4))
        assert repo.bookings_for_range(sample_property.id, bitisik) == []

        # Bir gun oncesi ile baslayan aralik ise cakisir.
        cakisan = DateRange(today + timedelta(days=1), today + timedelta(days=4))
        assert len(repo.bookings_for_range(sample_property.id, cakisan)) == 1

    def test_bookings_for_range_onceki_bitisik_rezervasyonu_dondurmez(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today + timedelta(days=5),
            end=today + timedelta(days=7),
        )
        repo = ReservationRepository(session)
        onceki = DateRange(today + timedelta(days=3), today + timedelta(days=5))
        assert repo.bookings_for_range(sample_property.id, onceki) == []

    @pytest.mark.parametrize(
        "status",
        [
            ReservationStatus.CANCELLED,
            ReservationStatus.NO_SHOW,
            ReservationStatus.DRAFT,
            ReservationStatus.WAITLIST,
        ],
    )
    def test_bookings_for_range_bloke_etmeyen_durumlari_atlar(
        self,
        session,
        sample_property,
        sample_room_type,
        sample_rooms,
        sample_guest,
        today,
        status,
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=2),
            status=status,
        )
        repo = ReservationRepository(session)
        assert (
            repo.bookings_for_range(sample_property.id, DateRange(today, today + timedelta(3)))
            == []
        )

    def test_bookings_for_range_iptal_edilen_oda_satirini_atlar(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        """Baslik 'confirmed' olsa bile iptal edilen oda satiri envanteri tutmaz."""
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=2),
            room_cancelled=True,
        )
        repo = ReservationRepository(session)
        assert (
            repo.bookings_for_range(sample_property.id, DateRange(today, today + timedelta(3)))
            == []
        )

    def test_bookings_for_range_oda_atanmamis_satiri_atlar(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=None,
            start=today,
            end=today + timedelta(days=2),
        )
        repo = ReservationRepository(session)
        assert (
            repo.bookings_for_range(sample_property.id, DateRange(today, today + timedelta(3)))
            == []
        )

    def test_bookings_for_range_silinmis_rezervasyonu_atlar(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=2),
            deleted=True,
        )
        repo = ReservationRepository(session)
        assert (
            repo.bookings_for_range(sample_property.id, DateRange(today, today + timedelta(3)))
            == []
        )

    def test_bookings_for_range_oda_suzgeci(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        for oda in sample_rooms[:2]:
            make_reservation(
                session,
                hotel_property=sample_property,
                guest=sample_guest,
                room_type=sample_room_type,
                room=oda,
                start=today,
                end=today + timedelta(days=2),
            )
        repo = ReservationRepository(session)
        aralik = DateRange(today, today + timedelta(days=3))
        assert len(repo.bookings_for_range(sample_property.id, aralik)) == 2
        tekil = repo.bookings_for_range(sample_property.id, aralik, room_ids=[sample_rooms[1].id])
        assert [b.room_id for b in tekil] == [sample_rooms[1].id]
        # Bos aday listesi hicbir sey dondurmemeli (tum odalar degil).
        assert repo.bookings_for_range(sample_property.id, aralik, room_ids=[]) == []

    def test_bookings_for_room(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[2],
            start=today,
            end=today + timedelta(days=3),
        )
        repo = ReservationRepository(session)
        aralik = DateRange(today, today + timedelta(days=10))
        assert len(repo.bookings_for_room(sample_rooms[2].id, aralik)) == 1
        assert repo.bookings_for_room(sample_rooms[0].id, aralik) == []


class TestReservationRepositoryQueries:
    def test_get_by_confirmation_number(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=1),
            confirmation_number="TST-ARANAN",
        )
        repo = ReservationRepository(session)
        assert repo.get_by_confirmation_number("TST-ARANAN") is not None
        assert repo.get_by_confirmation_number("TST-YOK") is None

    def test_search_misafir_adi_ve_durum_suzgeci(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=1),
        )
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[1],
            start=today + timedelta(days=1),
            end=today + timedelta(days=2),
            status=ReservationStatus.TENTATIVE,
        )
        repo = ReservationRepository(session)
        assert len(repo.search(sample_property.id, query="Yildizli")) == 2
        assert len(repo.search(sample_property.id, query="bulunmayan-isim")) == 0
        assert len(repo.search(sample_property.id, status=ReservationStatus.TENTATIVE)) == 1
        assert len(repo.search(sample_property.id, limit=1)) == 1

    def test_search_tarih_araligi_suzgeci(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=2),
        )
        repo = ReservationRepository(session)
        assert (
            len(repo.search(sample_property.id, date_range=DateRange(today, today + timedelta(1))))
            == 1
        )
        uzak = DateRange(today + timedelta(days=30), today + timedelta(days=32))
        assert repo.search(sample_property.id, date_range=uzak) == []

    def test_gunluk_listeler(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=2),
        )
        repo = ReservationRepository(session)

        assert len(repo.arrivals_on(sample_property.id, today)) == 1
        assert repo.arrivals_on(sample_property.id, today + timedelta(days=1)) == []

        assert len(repo.departures_on(sample_property.id, today + timedelta(days=2))) == 1
        assert repo.departures_on(sample_property.id, today) == []

        # Giris gunu ve ara gun otelde; cikis gunu artik degil.
        assert len(repo.in_house_on(sample_property.id, today)) == 1
        assert len(repo.in_house_on(sample_property.id, today + timedelta(days=1))) == 1
        assert repo.in_house_on(sample_property.id, today + timedelta(days=2)) == []

    def test_next_confirmation_number_ilk_ve_sonraki(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        repo = ReservationRepository(session)
        yil = utcnow().year

        ilk = repo.next_confirmation_number(sample_property.id)
        assert ilk == f"RZV-{yil}-000001"

        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=1),
            confirmation_number=ilk,
        )
        assert repo.next_confirmation_number(sample_property.id) == f"RZV-{yil}-000002"

    def test_next_confirmation_number_onceki_yil_sayaci_kirletmez(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        """Sayac yil bazindadir; gecen yilin yuksek numarasi devretmemeli."""
        repo = ReservationRepository(session)
        yil = utcnow().year
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=1),
            confirmation_number=f"RZV-{yil - 1}-000999",
        )
        assert repo.next_confirmation_number(sample_property.id) == f"RZV-{yil}-000001"

    def test_next_confirmation_number_silinmis_kaydin_numarasini_yeniden_vermez(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        """Mantiksal silme numarayi serbest birakmamalidir.

        ``confirmation_number`` sutunundaki ``UNIQUE`` kisiti silinmis
        satirlari da kapsar; sayac ``is_deleted`` suzgeci uygulasaydi ayni
        numara yeniden uretilir ve kayit ``IntegrityError`` ile reddedilirdi.
        """
        repo = ReservationRepository(session)
        yil = utcnow().year
        rezervasyon = make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=1),
            confirmation_number=f"RZV-{yil}-000001",
        )
        rezervasyon.mark_deleted()
        session.commit()

        assert repo.next_confirmation_number(sample_property.id) == f"RZV-{yil}-000002"


# --------------------------------------------------------------------------
#  Misafir repository
# --------------------------------------------------------------------------
class TestGuestRepository:
    def test_search_ad_soyad_ve_eposta(self, session, sample_guest):
        repo = GuestRepository(session)
        assert [g.id for g in repo.search("yildiz")] == [sample_guest.id]
        assert [g.id for g in repo.search("Deniz Yildizli")] == [sample_guest.id]
        assert [g.id for g in repo.search("ornek-test.local")] == [sample_guest.id]
        assert repo.search("bulunmayan") == []

    def test_search_bos_sorgu_tum_tabani_getirmez(self, session, sample_guest):
        repo = GuestRepository(session)
        assert repo.search("   ") == []

    def test_find_by_identity_sifreli_alanda_dogru_misafiri_bulur(self, session, sample_guest):
        """Sifreli sutunda esitlik aramasi ancak kor indeksle mumkundur."""
        repo = GuestRepository(session)
        bulunan = repo.find_by_identity("11111111110")
        assert bulunan is not None
        assert bulunan.id == sample_guest.id
        # Bosluklar onemsiz olmali (blind_index strip uygular).
        assert repo.find_by_identity(" 11111111110 ").id == sample_guest.id

    def test_find_by_identity_yanlis_numarada_none(self, session, sample_guest):
        repo = GuestRepository(session)
        assert repo.find_by_identity("22222222220") is None
        assert repo.find_by_identity("") is None

    def test_find_duplicates_ayni_ad_soyad_ve_dogum_tarihi(self, session, sample_guest):
        sample_guest.birth_date = date(1990, 5, 17)
        ikiz = Guest(
            first_name=sample_guest.first_name,
            last_name=sample_guest.last_name,
            birth_date=date(1990, 5, 17),
        )
        session.add(ikiz)
        session.commit()

        repo = GuestRepository(session)
        assert [g.id for g in repo.find_duplicates(sample_guest)] == [ikiz.id]

    def test_find_duplicates_ayni_eposta(self, session, sample_guest):
        ikiz = Guest(
            first_name="Baska",
            last_name="Isim",
            email=sample_guest.email,
        )
        session.add(ikiz)
        session.commit()

        repo = GuestRepository(session)
        assert [g.id for g in repo.find_duplicates(sample_guest)] == [ikiz.id]

    def test_find_duplicates_dogum_tarihi_yoksa_ad_esleyen_kaydi_saymaz(self, session):
        """Dogum tarihi bos iki 'Ali Yilmaz' ayni kisi kabul edilemez."""
        birinci = Guest(first_name="Ali", last_name="Yilmaz")
        ikinci = Guest(first_name="Ali", last_name="Yilmaz")
        session.add_all([birinci, ikinci])
        session.commit()

        repo = GuestRepository(session)
        assert repo.find_duplicates(birinci) == []

    def test_update_crm_summary_stay_ve_folio_dan_hesaplar(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        rezervasyon = make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=3),
            status=ReservationStatus.CHECKED_OUT,
        )
        oda_satiri = session.scalars(
            select(ReservationRoom).where(ReservationRoom.reservation_id == rezervasyon.id)
        ).one()

        session.add(
            Stay(
                reservation_room_id=oda_satiri.id,
                room_id=sample_rooms[0].id,
                actual_check_in=utcnow(),
                actual_check_out=utcnow() + timedelta(days=2),
            )
        )
        session.commit()

        folyo = make_folio(
            session,
            hotel_property=sample_property,
            number="FLY-TEST-0001",
            reservation=rezervasyon,
            balance=Decimal("2500.00"),
        )
        assert folyo.total_charges == Decimal("2500.00")

        repo = GuestRepository(session)
        guncel = repo.update_crm_summary(sample_guest.id)

        assert guncel.total_stays == 1
        assert guncel.total_nights == 2
        assert guncel.total_revenue == Decimal("2500.00")
        assert guncel.first_stay_date is not None
        assert guncel.last_stay_date is not None

    def test_update_crm_summary_halen_oteldeki_misafirde_plan_tarihi_kullanilir(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        """Cikis yapmamis konaklamada gece sayisi plan tarihinden gelmeli.

        ``actual_check_out`` bos oldugu icin fiili sure hesaplanamaz; bos
        birakmak yerine plan tarihi kullanilir, aksi halde otelde olan
        misafirin gecesi sifir gorunurdu.
        """
        rezervasyon = make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=4),
            status=ReservationStatus.CHECKED_IN,
        )
        oda_satiri = session.scalars(
            select(ReservationRoom).where(ReservationRoom.reservation_id == rezervasyon.id)
        ).one()
        session.add(
            Stay(
                reservation_room_id=oda_satiri.id,
                room_id=sample_rooms[0].id,
                # Giris zamani sabit "today" fikstürüyle ayni zaman cizgisinde
                # olmali; utcnow() gercek saati verir ve plan tarihiyle
                # karsilastirma anlamsizlasirdi.
                actual_check_in=datetime.combine(today, time(14, 0), tzinfo=UTC),
                actual_check_out=None,
            )
        )
        session.commit()

        repo = GuestRepository(session)
        guncel = repo.update_crm_summary(sample_guest.id)
        assert guncel.total_stays == 1
        assert guncel.total_nights == 4
        assert guncel.last_stay_date == today + timedelta(days=4)


# --------------------------------------------------------------------------
#  Folyo repository
# --------------------------------------------------------------------------
class TestFolioRepository:
    def test_open_folio_for_reservation(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        rezervasyon = make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[0],
            start=today,
            end=today + timedelta(days=1),
        )
        repo = FolioRepository(session)
        assert repo.open_folio_for_reservation(rezervasyon.id) is None

        kapali = make_folio(
            session,
            hotel_property=sample_property,
            number="FLY-TEST-1000",
            reservation=rezervasyon,
            status=FolioStatus.CLOSED,
        )
        assert repo.open_folio_for_reservation(rezervasyon.id) is None

        acik = make_folio(
            session,
            hotel_property=sample_property,
            number="FLY-TEST-1001",
            reservation=rezervasyon,
        )
        bulunan = repo.open_folio_for_reservation(rezervasyon.id)
        assert bulunan is not None
        assert bulunan.id == acik.id
        assert bulunan.id != kapali.id

    def test_get_with_lines_ucret_ve_odemeleri_yukler(
        self, session, sample_property, sample_guest, today
    ):
        folyo = make_folio(
            session, hotel_property=sample_property, number="FLY-TEST-2000", guest=sample_guest
        )
        make_charge(
            session,
            folio=folyo,
            charge_type=ChargeType.ROOM,
            day=today,
            amount=Decimal("1000.00"),
        )
        session.add(
            Payment(
                folio_id=folyo.id,
                method=PaymentMethod.CASH,
                amount=Decimal("400.00"),
                paid_at=utcnow(),
            )
        )
        session.commit()
        session.expire_all()

        repo = FolioRepository(session)
        yuklu = repo.get_with_lines(folyo.id)
        assert len(yuklu.charges) == 1
        assert len(yuklu.payments) == 1

    def test_get_with_lines_bulunamayan_folyoda_hata(self, session, sample_property):
        repo = FolioRepository(session)
        with pytest.raises(NotFoundError):
            repo.get_with_lines(4242)

    def test_next_folio_number(self, session, sample_property):
        repo = FolioRepository(session)
        yil = utcnow().year
        assert repo.next_folio_number(sample_property.id) == f"FLY-{yil}-000001"

        make_folio(session, hotel_property=sample_property, number=f"FLY-{yil}-000001")
        assert repo.next_folio_number(sample_property.id) == f"FLY-{yil}-000002"

    def test_unsettled_folios_yalnizca_borclu_acik_folyolar(self, session, sample_property):
        borclu = make_folio(
            session,
            hotel_property=sample_property,
            number="FLY-TEST-3000",
            balance=Decimal("750.00"),
        )
        make_folio(
            session,
            hotel_property=sample_property,
            number="FLY-TEST-3001",
            balance=Decimal("0.00"),
        )
        make_folio(
            session,
            hotel_property=sample_property,
            number="FLY-TEST-3002",
            status=FolioStatus.CLOSED,
            balance=Decimal("999.00"),
        )
        repo = FolioRepository(session)
        assert [f.id for f in repo.unsettled_folios(sample_property.id)] == [borclu.id]

    def test_daily_revenue_ucret_turune_gore_gruplar(self, session, sample_property, today):
        folyo = make_folio(session, hotel_property=sample_property, number="FLY-TEST-4000")
        make_charge(
            session, folio=folyo, charge_type=ChargeType.ROOM, day=today, amount=Decimal("1000.00")
        )
        make_charge(
            session, folio=folyo, charge_type=ChargeType.ROOM, day=today, amount=Decimal("500.00")
        )
        make_charge(
            session,
            folio=folyo,
            charge_type=ChargeType.MINIBAR,
            day=today,
            amount=Decimal("120.00"),
        )
        # Gecersiz kilinan satir gelire girmemeli.
        make_charge(
            session,
            folio=folyo,
            charge_type=ChargeType.SPA,
            day=today,
            amount=Decimal("300.00"),
            is_void=True,
        )
        # Baska gunun ucreti de girmemeli.
        make_charge(
            session,
            folio=folyo,
            charge_type=ChargeType.ROOM,
            day=today + timedelta(days=1),
            amount=Decimal("9999.00"),
        )

        repo = FolioRepository(session)
        dokum = repo.daily_revenue(sample_property.id, today)
        assert dokum == {
            ChargeType.ROOM: Decimal("1500.00"),
            ChargeType.MINIBAR: Decimal("120.00"),
        }


# --------------------------------------------------------------------------
#  Operasyon repository
# --------------------------------------------------------------------------
class TestOperationsRepository:
    def test_housekeeping_tasks_suzgecleri(self, session, sample_property, sample_rooms, today):
        session.add_all(
            [
                HousekeepingTask(
                    property_id=sample_property.id,
                    room_id=sample_rooms[0].id,
                    scheduled_date=today,
                    status=HousekeepingStatus.PENDING,
                ),
                HousekeepingTask(
                    property_id=sample_property.id,
                    room_id=sample_rooms[1].id,
                    scheduled_date=today,
                    status=HousekeepingStatus.COMPLETED,
                ),
                HousekeepingTask(
                    property_id=sample_property.id,
                    room_id=sample_rooms[2].id,
                    scheduled_date=today + timedelta(days=1),
                    status=HousekeepingStatus.PENDING,
                ),
            ]
        )
        session.commit()

        repo = OperationsRepository(session)
        assert len(repo.housekeeping_tasks(sample_property.id)) == 3
        assert len(repo.housekeeping_tasks(sample_property.id, day=today)) == 2
        assert (
            len(repo.housekeeping_tasks(sample_property.id, status=HousekeepingStatus.PENDING)) == 2
        )
        assert (
            len(
                repo.housekeeping_tasks(
                    sample_property.id, day=today, status=HousekeepingStatus.PENDING
                )
            )
            == 1
        )

    def test_rooms_needing_cleaning_kirli_ve_cikis_odalari(
        self, session, sample_property, sample_room_type, sample_rooms, sample_guest, today
    ):
        # 101: kirli
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        # 103: arizali -> kat hizmetlerinin isi degil
        sample_rooms[2].housekeeping_status = RoomHousekeepingStatus.OUT_OF_ORDER
        session.commit()

        # 102: bugun cikis var -> cikis temizligi gerekir
        make_reservation(
            session,
            hotel_property=sample_property,
            guest=sample_guest,
            room_type=sample_room_type,
            room=sample_rooms[1],
            start=today - timedelta(days=2),
            end=today,
        )

        repo = OperationsRepository(session)
        odalar = repo.rooms_needing_cleaning(sample_property.id, today)
        assert [o.number for o in odalar] == ["101", "102"]

    def test_rooms_needing_cleaning_acik_gorevi_olan_odayi_atlar(
        self, session, sample_property, sample_rooms, today
    ):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        session.add(
            HousekeepingTask(
                property_id=sample_property.id,
                room_id=sample_rooms[0].id,
                scheduled_date=today,
                status=HousekeepingStatus.ASSIGNED,
            )
        )
        session.commit()

        repo = OperationsRepository(session)
        assert repo.rooms_needing_cleaning(sample_property.id, today) == []

    def test_rooms_needing_cleaning_iptal_edilmis_gorevi_yok_sayar(
        self, session, sample_property, sample_rooms, today
    ):
        """Iptal edilmis gorev odayi listeden dusurmemelidir.

        Mukerrer kayit suzgeci yalnizca **acik** gorevlere bakar; iptal
        edilen gorev sayilsaydi oda o gun bir daha hic temizlik listesine
        girmez ve kirli kalirdi.
        """
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        session.add(
            HousekeepingTask(
                property_id=sample_property.id,
                room_id=sample_rooms[0].id,
                scheduled_date=today,
                status=HousekeepingStatus.CANCELLED,
            )
        )
        session.commit()

        repo = OperationsRepository(session)
        odalar = repo.rooms_needing_cleaning(sample_property.id, today)
        assert [o.number for o in odalar] == ["101"]

    def test_open_maintenance_tickets_parca_bekleyen_kayit_aciktir(
        self, session, sample_property, sample_rooms
    ):
        """``WAITING_PARTS`` acik sayilmali - oda hala satisa kapalidir."""
        session.add(
            MaintenanceTicket(
                property_id=sample_property.id,
                ticket_number="ARZ-TEST-0100",
                room_id=sample_rooms[0].id,
                title="Parca bekleniyor",
                description="Yedek parca siparis edildi.",
                reported_at=utcnow(),
                status=MaintenanceStatus.WAITING_PARTS,
            )
        )
        session.commit()

        repo = OperationsRepository(session)
        kayitlar = repo.open_maintenance_tickets(sample_property.id)
        assert [t.ticket_number for t in kayitlar] == ["ARZ-TEST-0100"]
        # Repository kumesi ile modelin kendi tanimi ayrismamali.
        assert all(t.is_open for t in kayitlar)

    def test_open_maintenance_tickets_oncelige_gore_sirali(
        self, session, sample_property, sample_rooms
    ):
        session.add_all(
            [
                MaintenanceTicket(
                    property_id=sample_property.id,
                    ticket_number="ARZ-TEST-0001",
                    room_id=sample_rooms[0].id,
                    title="Dusuk oncelikli",
                    description="Bekleyebilir.",
                    reported_at=utcnow(),
                    priority=Priority.LOW,
                    status=MaintenanceStatus.OPEN,
                ),
                MaintenanceTicket(
                    property_id=sample_property.id,
                    ticket_number="ARZ-TEST-0002",
                    room_id=sample_rooms[1].id,
                    title="Kritik ariza",
                    description="Acil mudahale.",
                    reported_at=utcnow(),
                    priority=Priority.CRITICAL,
                    status=MaintenanceStatus.ASSIGNED,
                ),
                MaintenanceTicket(
                    property_id=sample_property.id,
                    ticket_number="ARZ-TEST-0003",
                    room_id=sample_rooms[2].id,
                    title="Kapatilmis",
                    description="Cozuldu.",
                    reported_at=utcnow(),
                    priority=Priority.URGENT,
                    status=MaintenanceStatus.CLOSED,
                ),
            ]
        )
        session.commit()

        repo = OperationsRepository(session)
        kayitlar = repo.open_maintenance_tickets(sample_property.id)
        # Alfabetik siralama "critical" < "low" verirdi; agirliga gore
        # kritik olan basta olmali ve kapali kayit hic gelmemeli.
        assert [t.ticket_number for t in kayitlar] == ["ARZ-TEST-0002", "ARZ-TEST-0001"]

        yalniz_kritik = repo.open_maintenance_tickets(
            sample_property.id, priority=Priority.CRITICAL
        )
        assert [t.ticket_number for t in yalniz_kritik] == ["ARZ-TEST-0002"]

    def test_next_ticket_number(self, session, sample_property, sample_rooms):
        repo = OperationsRepository(session)
        yil = utcnow().year
        ilk = repo.next_ticket_number(sample_property.id)
        assert ilk == f"ARZ-{yil}-000001"

        session.add(
            MaintenanceTicket(
                property_id=sample_property.id,
                ticket_number=ilk,
                room_id=sample_rooms[0].id,
                title="Ilk kayit",
                description="Test.",
                reported_at=utcnow(),
            )
        )
        session.commit()
        assert repo.next_ticket_number(sample_property.id) == f"ARZ-{yil}-000002"


# --------------------------------------------------------------------------
#  Stok repository
# --------------------------------------------------------------------------
class TestInventoryRepository:
    def test_low_stock_items_esigin_altindakileri_dondurur(self, session, sample_property):
        az = make_item(
            session,
            hotel_property=sample_property,
            sku="SU-050",
            name="Su 0.5 lt",
            current=Decimal("2.000"),
            minimum=Decimal("20.000"),
        )
        biraz_az = make_item(
            session,
            hotel_property=sample_property,
            sku="COLA",
            name="Kola",
            current=Decimal("9.000"),
            minimum=Decimal("10.000"),
        )
        # Yeterli stok
        make_item(
            session,
            hotel_property=sample_property,
            sku="CIPS",
            name="Cips",
            current=Decimal("50.000"),
            minimum=Decimal("10.000"),
        )
        # Asgari seviyesi tanimsiz -> uyari uretmemeli
        make_item(
            session,
            hotel_property=sample_property,
            sku="KALEM",
            name="Kalem",
            current=Decimal("0.000"),
            minimum=Decimal("0.000"),
        )
        # Pasif kart
        make_item(
            session,
            hotel_property=sample_property,
            sku="ESKI",
            name="Eski Urun",
            current=Decimal("0.000"),
            minimum=Decimal("5.000"),
            is_active=False,
        )

        repo = InventoryRepository(session)
        # En cok eksigi olan basta.
        assert [i.id for i in repo.low_stock_items(sample_property.id)] == [az.id, biraz_az.id]

    def test_stock_on_hand_hareketlerden_hesaplar(self, session, sample_property, today):
        urun = make_item(
            session,
            hotel_property=sample_property,
            sku="SU-100",
            name="Su 1 lt",
            current=Decimal("0.000"),
            minimum=Decimal("10.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.PURCHASE_IN,
            day=today,
            quantity=Decimal("100.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.MINIBAR_OUT,
            day=today,
            quantity=Decimal("12.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.WASTE_OUT,
            day=today + timedelta(days=1),
            quantity=Decimal("3.000"),
        )

        repo = InventoryRepository(session)
        assert repo.stock_on_hand(urun.id) == Decimal("85.000")

    def test_stock_on_hand_sayim_duzeltmesini_taban_alir(self, session, sample_property, today):
        """Sayim sonrasi eski hareketler yeniden toplanmamalidir."""
        urun = make_item(
            session,
            hotel_property=sample_property,
            sku="SABUN",
            name="Sabun",
            current=Decimal("0.000"),
            minimum=Decimal("5.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.PURCHASE_IN,
            day=today,
            quantity=Decimal("500.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.ADJUSTMENT,
            day=today + timedelta(days=1),
            quantity=Decimal("0.000"),
            stock_after=Decimal("40.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.CONSUMPTION_OUT,
            day=today + timedelta(days=2),
            quantity=Decimal("5.000"),
        )

        repo = InventoryRepository(session)
        assert repo.stock_on_hand(urun.id) == Decimal("35.000")

    def test_stock_on_hand_hareketsiz_urunde_sifir(self, session, sample_property):
        urun = make_item(
            session,
            hotel_property=sample_property,
            sku="BOS",
            name="Hareketsiz Urun",
            current=Decimal("0.000"),
            minimum=Decimal("1.000"),
        )
        repo = InventoryRepository(session)
        assert repo.stock_on_hand(urun.id) == Decimal("0.000")

    def test_stock_on_hand_sayimla_ayni_gunki_sonraki_hareketi_sayar(
        self, session, sample_property, today
    ):
        """Sayim ile ayni gune dusen sonraki hareket taban disinda kalmamali.

        Taban yalnizca tarihe gore secilseydi ayni gun icindeki tuketim
        goz ardi edilir ve stok oldugundan fazla gorunurdu; siralama
        (tarih, id) ikilisiyle yapildigi icin kayit sirasi belirleyicidir.
        """
        urun = make_item(
            session,
            hotel_property=sample_property,
            sku="SAYIM-AYNIGUN",
            name="Ayni Gun Sayim",
            current=Decimal("0.000"),
            minimum=Decimal("1.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.PURCHASE_IN,
            day=today,
            quantity=Decimal("100.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.ADJUSTMENT,
            day=today,
            quantity=Decimal("0.000"),
            stock_after=Decimal("40.000"),
        )
        make_movement(
            session,
            item=urun,
            movement_type=StockMovementType.MINIBAR_OUT,
            day=today,
            quantity=Decimal("7.000"),
        )

        repo = InventoryRepository(session)
        assert repo.stock_on_hand(urun.id) == Decimal("33.000")

    def test_recent_movements_en_yeniden_eskiye(self, session, sample_property, today):
        urun = make_item(
            session,
            hotel_property=sample_property,
            sku="MEYVE",
            name="Meyve Suyu",
            current=Decimal("0.000"),
            minimum=Decimal("1.000"),
        )
        for gun in range(4):
            make_movement(
                session,
                item=urun,
                movement_type=StockMovementType.PURCHASE_IN,
                day=today + timedelta(days=gun),
                quantity=Decimal("1.000"),
            )

        repo = InventoryRepository(session)
        son_ikisi = repo.recent_movements(urun.id, limit=2)
        assert [m.movement_date for m in son_ikisi] == [
            today + timedelta(days=3),
            today + timedelta(days=2),
        ]
