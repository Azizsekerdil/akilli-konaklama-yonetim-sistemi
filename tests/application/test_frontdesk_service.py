"""On buro (check-in / check-out) ve folyo ucdan uca testleri.

Kapsanan kritik senaryolar:

* Giris yapilinca oda dolu isaretlenir, folyo acilir ve oda ucretleri islenir
* Kirli / bakimdaki odaya giris engellenir
* Bakiye acikken cikis engellenir
* Cikista oda kirli isaretlenir ve temizlik gorevi olusur
* Erken giris ve gec cikis ucretleri hesaplanir
* Hatali (fazla) odeme tutari reddedilir
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.application.services.folio_service import FolioService
from app.application.services.frontdesk_service import FrontdeskService
from app.application.services.reservation_service import ReservationService, RoomRequest
from app.core.exceptions import (
    BusinessRuleError,
    PaymentError,
    RoomNotAvailableError,
)
from app.domain.enums import (
    ChargeType,
    HousekeepingStatus,
    PaymentMethod,
    ReservationStatus,
    RoomHousekeepingStatus,
    RoomOccupancyStatus,
    StayStatus,
)
from app.infrastructure.db.base import utcnow

pytestmark = pytest.mark.integration


@pytest.fixture
def reservation(admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest):
    """Bugun giris yapacak, 2 gecelik onayli bir rezervasyon."""
    today = utcnow().date()
    return ReservationService(admin_ctx).create_reservation(
        guest_id=guest.id,
        room_requests=[
            RoomRequest(
                room_type_id=sample_room_type.id,
                room_id=sample_rooms[0].id,
                check_in=today,
                check_out=today + timedelta(days=2),
            )
        ],
    )


class TestCheckIn:
    def test_giris_yapilir(self, admin_ctx, reservation, sample_rooms):
        service = FrontdeskService(admin_ctx)
        stay = service.check_in(reservation.rooms[0].id)

        assert stay.status is StayStatus.IN_HOUSE
        assert stay.is_in_house
        assert sample_rooms[0].occupancy_status is RoomOccupancyStatus.OCCUPIED
        assert reservation.status is ReservationStatus.CHECKED_IN

    def test_folyo_acilir_ve_oda_ucretleri_islenir(self, admin_ctx, reservation):
        service = FrontdeskService(admin_ctx)
        service.check_in(reservation.rooms[0].id)

        folio = FolioService(admin_ctx).folio_for_room(reservation.rooms[0].id)
        assert folio is not None

        room_charges = [c for c in folio.charges if c.charge_type is ChargeType.ROOM]
        # Ucretler GECE BASINA ayri satir olarak islenir
        assert len(room_charges) == 2
        assert sum(c.total_amount for c in room_charges) == Decimal("2000.00")
        assert folio.balance == Decimal("2000.00")

    def test_ayni_satira_ikinci_giris_engellenir(self, admin_ctx, reservation):
        service = FrontdeskService(admin_ctx)
        service.check_in(reservation.rooms[0].id)

        with pytest.raises(BusinessRuleError) as hata:
            service.check_in(reservation.rooms[0].id)
        assert hata.value.code == "already_checked_in"

    def test_kirli_odaya_giris_onaysiz_engellenir(self, admin_ctx, reservation, sample_rooms):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        admin_ctx.session.commit()

        service = FrontdeskService(admin_ctx)
        with pytest.raises(BusinessRuleError) as hata:
            service.check_in(reservation.rooms[0].id)
        assert hata.value.code == "room_dirty"

    def test_kirli_odaya_onayla_giris_yapilabilir(self, admin_ctx, reservation, sample_rooms):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        admin_ctx.session.commit()

        stay = FrontdeskService(admin_ctx).check_in(reservation.rooms[0].id, allow_dirty_room=True)
        assert stay.is_in_house

    def test_bakimdaki_odaya_giris_engellenir(self, admin_ctx, reservation, sample_rooms):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.OUT_OF_ORDER
        admin_ctx.session.commit()

        with pytest.raises(RoomNotAvailableError) as hata:
            FrontdeskService(admin_ctx).check_in(reservation.rooms[0].id)
        assert hata.value.code == "room_out_of_service"

    def test_iptal_edilen_rezervasyona_giris_engellenir(self, admin_ctx, reservation):
        ReservationService(admin_ctx).cancel(reservation.id, reason="Test iptali")

        with pytest.raises(BusinessRuleError):
            FrontdeskService(admin_ctx).check_in(reservation.rooms[0].id)

    def test_erken_giris_ucreti_folyoya_islenir(self, admin_ctx, reservation):
        service = FrontdeskService(admin_ctx)
        service.check_in(reservation.rooms[0].id, early_check_in_hours=4)

        folio = FolioService(admin_ctx).folio_for_room(reservation.rooms[0].id)
        assert folio is not None
        early = [c for c in folio.charges if c.charge_type is ChargeType.EARLY_CHECKIN]
        assert len(early) == 1
        # Gecelik 1000 TL, 4 saat -> 2 dilim x %25 = %50
        assert early[0].total_amount == Decimal("500.00")


class TestCheckOut:
    def test_bakiye_acikken_cikis_engellenir(self, admin_ctx, reservation):
        service = FrontdeskService(admin_ctx)
        stay = service.check_in(reservation.rooms[0].id)

        with pytest.raises(PaymentError) as hata:
            service.check_out(stay.id)
        assert hata.value.code == "checkout_open_balance"

    def test_odeme_sonrasi_cikis_yapilir(self, admin_ctx, reservation, sample_rooms):
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)

        stay = frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)
        assert folio is not None

        folios.add_payment(folio.id, amount=Decimal("2000.00"), method=PaymentMethod.CREDIT_CARD)
        result = frontdesk.check_out(stay.id)

        assert result.actual_check_out is not None
        assert not result.is_in_house
        assert sample_rooms[0].occupancy_status is RoomOccupancyStatus.VACANT
        assert sample_rooms[0].housekeeping_status is RoomHousekeepingStatus.DIRTY

    def test_cikista_temizlik_gorevi_olusur(self, admin_ctx, reservation, sample_rooms):
        from sqlalchemy import select

        from app.infrastructure.db.models.operations import HousekeepingTask

        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)

        stay = frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)
        folios.add_payment(folio.id, amount=Decimal("2000.00"), method=PaymentMethod.CASH)
        frontdesk.check_out(stay.id)

        tasks = admin_ctx.session.scalars(
            select(HousekeepingTask).where(HousekeepingTask.room_id == sample_rooms[0].id)
        ).all()
        assert len(tasks) == 1
        assert tasks[0].status is HousekeepingStatus.PENDING

    def test_gec_cikis_ucreti_islenir(self, admin_ctx, reservation):
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)

        stay = frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)

        # Gec cikis ucreti eklenecegi icin once oda ucreti odenir,
        # sonra gec cikis ucreti dogar ve bakiye acik kalir.
        folios.add_payment(folio.id, amount=Decimal("2000.00"), method=PaymentMethod.CASH)

        with pytest.raises(PaymentError):
            frontdesk.check_out(stay.id, late_check_out_hours=3)

        folio = folios.folio_for_room(reservation.rooms[0].id)
        late = [c for c in folio.charges if c.charge_type is ChargeType.LATE_CHECKOUT]
        assert len(late) == 1
        assert late[0].total_amount == Decimal("250.00")  # 1 dilim x %25

    def test_hasar_ucreti_aciklama_ister(self, admin_ctx, reservation):
        from app.core.exceptions import ValidationError

        frontdesk = FrontdeskService(admin_ctx)
        stay = frontdesk.check_in(reservation.rooms[0].id)

        with pytest.raises(ValidationError):
            frontdesk.check_out(stay.id, damage_charge=Decimal("500.00"))

    def test_crm_ozeti_guncellenir(self, admin_ctx, reservation, guest):
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)

        stay = frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)
        folios.add_payment(folio.id, amount=Decimal("2000.00"), method=PaymentMethod.CASH)
        frontdesk.check_out(stay.id)

        assert guest.total_stays == 1
        assert guest.total_nights == 2
        assert guest.total_revenue == Decimal("2000.00")


class TestFolyo:
    def test_fazla_odeme_reddedilir(self, admin_ctx, reservation):
        """KRITIK: hatali odeme tutari (or. 2000 yerine 20000) yakalanmali."""
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)

        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)

        with pytest.raises(PaymentError) as hata:
            folios.add_payment(folio.id, amount=Decimal("20000.00"), method=PaymentMethod.CASH)
        assert hata.value.code == "overpayment"

    def test_bilincli_fazla_odemeye_izin_verilir(self, admin_ctx, reservation):
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)

        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)

        payment = folios.add_payment(
            folio.id,
            amount=Decimal("2500.00"),
            method=PaymentMethod.CASH,
            allow_overpayment=True,
        )
        assert payment.amount == Decimal("2500.00")

    def test_negatif_odeme_reddedilir(self, admin_ctx, reservation):
        from app.core.exceptions import ValidationError

        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)
        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)

        with pytest.raises(ValidationError):
            folios.add_payment(folio.id, amount=Decimal("-100"), method=PaymentMethod.CASH)

    def test_ucret_gecersiz_kilinir_ve_bakiye_duser(self, admin_ctx, reservation):
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)

        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)
        assert folio.balance == Decimal("2000.00")

        first_charge = folio.charges[0]
        folios.void_charge(first_charge.id, reason="Yanlis islendi")

        assert first_charge.is_void
        assert folio.balance == Decimal("1000.00")
        # Kayit SILINMEZ - denetim izi korunur
        assert first_charge.id is not None
        assert first_charge.void_reason == "Yanlis islendi"

    def test_gecersiz_kilma_gerekce_ister(self, admin_ctx, reservation):
        from app.core.exceptions import ValidationError

        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)
        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)

        with pytest.raises(ValidationError):
            folios.void_charge(folio.charges[0].id, reason="")

    def test_yetkisiz_kullanici_ucret_gecersiz_kilamaz(self, admin_ctx, frontdesk_ctx, reservation):
        from app.core.exceptions import AuthorizationError

        FrontdeskService(admin_ctx).check_in(reservation.rooms[0].id)
        folio = FolioService(admin_ctx).folio_for_room(reservation.rooms[0].id)

        with pytest.raises(AuthorizationError):
            FolioService(frontdesk_ctx).void_charge(folio.charges[0].id, reason="Deneme")

    def test_indirim_toplami_asamaz(self, admin_ctx, reservation):
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)
        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)

        with pytest.raises(BusinessRuleError):
            folios.apply_discount(folio.id, amount=Decimal("5000.00"))

    def test_kasa_hareketi_olusur(self, admin_ctx, reservation):
        from sqlalchemy import select

        from app.infrastructure.db.models.billing import CashRegisterEntry

        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)
        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)
        folios.add_payment(folio.id, amount=Decimal("2000.00"), method=PaymentMethod.CASH)

        entries = admin_ctx.session.scalars(select(CashRegisterEntry)).all()
        assert len(entries) == 1
        assert entries[0].amount == Decimal("2000.00")
        assert entries[0].signed_amount == Decimal("2000.00")

    def test_kart_numarasi_sadece_son_dort_hane_saklanir(self, admin_ctx, reservation):
        frontdesk = FrontdeskService(admin_ctx)
        folios = FolioService(admin_ctx)
        frontdesk.check_in(reservation.rooms[0].id)
        folio = folios.folio_for_room(reservation.rooms[0].id)

        payment = folios.add_payment(
            folio.id,
            amount=Decimal("2000.00"),
            method=PaymentMethod.CREDIT_CARD,
            card_last_four="4111111111111111",
        )
        assert payment.card_last_four == "1111"
        assert len(payment.card_last_four) == 4
