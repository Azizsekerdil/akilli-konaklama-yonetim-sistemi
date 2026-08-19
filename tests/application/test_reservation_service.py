"""Rezervasyon servisi ucdan uca testleri.

Bu testler gercek bir veritabani uzerinde calisir ve kullanicinin istedigi
kritik senaryolari dogrular:

* Ayni odaya cakisan iki rezervasyon **engellenir**
* Bitisik rezervasyon (cikis = giris gunu) **kabul edilir**
* Bakimdaki oda **satilamaz**
* Iptal edilen rezervasyona islem yapilamaz
* No-show cezasi hesaplanir
* Yetkisiz kullanici islem yapamaz
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.application.services.reservation_service import ReservationService, RoomRequest
from app.core.exceptions import (
    AuthorizationError,
    BusinessRuleError,
    InvalidStateTransitionError,
    OverlappingReservationError,
    RoomOutOfServiceError,
    ValidationError,
)
from app.domain.enums import (
    AuditAction,
    ReservationStatus,
    RoomHousekeepingStatus,
)
from app.domain.value_objects import DateRange

pytestmark = pytest.mark.integration


def make_request(room_type_id, room_id, start, nights=2, **kwargs) -> RoomRequest:
    return RoomRequest(
        room_type_id=room_type_id,
        room_id=room_id,
        check_in=start,
        check_out=start + timedelta(days=nights),
        **kwargs,
    )


class TestOlusturma:
    def test_rezervasyon_olusturulur(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )

        assert reservation.confirmation_number.startswith("RZV")
        assert reservation.status is ReservationStatus.CONFIRMED
        assert reservation.nights == 2
        assert len(reservation.rooms) == 1
        # 2 gece x 1000 TL taban fiyat
        assert reservation.total_amount == Decimal("2000.00")

    def test_onay_numarasi_benzersiz(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        first = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        second = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[1].id, next_week)],
        )
        assert first.confirmation_number != second.confirmation_number

    def test_denetim_kaydi_yazilir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        from sqlalchemy import select

        from app.infrastructure.db.models.security import AuditLog

        service = ReservationService(admin_ctx)
        service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )

        kayitlar = admin_ctx.session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "Reservation",
                AuditLog.action == AuditAction.CREATE,
            )
        ).all()
        assert len(kayitlar) == 1

    def test_oda_secilmeden_olusturulamaz(self, admin_ctx, property_with_rooms, guest):
        service = ReservationService(admin_ctx)
        with pytest.raises(ValidationError, match="En az bir oda"):
            service.create_reservation(guest_id=guest.id, room_requests=[])

    def test_gecersiz_tarih_reddedilir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        request = RoomRequest(
            room_type_id=sample_room_type.id,
            room_id=sample_rooms[0].id,
            check_in=next_week,
            check_out=next_week,  # ayni gun -> 0 gece
        )
        with pytest.raises(ValidationError):
            service.create_reservation(guest_id=guest.id, room_requests=[request])

    def test_kapasite_asimi_reddedilir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        request = make_request(sample_room_type.id, sample_rooms[0].id, next_week, adults=5)
        with pytest.raises(BusinessRuleError, match=r"kisiliktir|yetiskin"):
            service.create_reservation(guest_id=guest.id, room_requests=[request])


class TestCakismaEngelleme:
    def test_ayni_odaya_cakisan_rezervasyon_reddedilir(
        self,
        admin_ctx,
        property_with_rooms,
        sample_room_type,
        sample_rooms,
        guest,
        second_guest,
        next_week,
    ):
        """EN KRITIK TEST: ayni oda ayni gece iki kez satilamaz."""
        service = ReservationService(admin_ctx)
        service.create_reservation(
            guest_id=guest.id,
            room_requests=[
                make_request(sample_room_type.id, sample_rooms[0].id, next_week, nights=4)
            ],
        )

        with pytest.raises(OverlappingReservationError):
            service.create_reservation(
                guest_id=second_guest.id,
                room_requests=[
                    make_request(
                        sample_room_type.id,
                        sample_rooms[0].id,
                        next_week + timedelta(days=2),
                        nights=3,
                    )
                ],
            )

    def test_bitisik_rezervasyon_kabul_edilir(
        self,
        admin_ctx,
        property_with_rooms,
        sample_room_type,
        sample_rooms,
        guest,
        second_guest,
        next_week,
    ):
        """Cikis gunu = giris gunu ise oda ayni gun tekrar satilabilir."""
        service = ReservationService(admin_ctx)
        service.create_reservation(
            guest_id=guest.id,
            room_requests=[
                make_request(sample_room_type.id, sample_rooms[0].id, next_week, nights=2)
            ],
        )
        second = service.create_reservation(
            guest_id=second_guest.id,
            room_requests=[
                make_request(
                    sample_room_type.id,
                    sample_rooms[0].id,
                    next_week + timedelta(days=2),
                    nights=2,
                )
            ],
        )
        assert second.status is ReservationStatus.CONFIRMED

    def test_farkli_oda_cakismaz(
        self,
        admin_ctx,
        property_with_rooms,
        sample_room_type,
        sample_rooms,
        guest,
        second_guest,
        next_week,
    ):
        service = ReservationService(admin_ctx)
        service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        second = service.create_reservation(
            guest_id=second_guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[1].id, next_week)],
        )
        assert second.id is not None

    def test_ayni_istek_icinde_cakisma_yakalanir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        """Tek istekte ayni oda iki kez, cakisan tarihlerle istenirse reddedilir."""
        service = ReservationService(admin_ctx)
        with pytest.raises(OverlappingReservationError):
            service.create_reservation(
                guest_id=guest.id,
                room_requests=[
                    make_request(sample_room_type.id, sample_rooms[0].id, next_week, nights=3),
                    make_request(
                        sample_room_type.id,
                        sample_rooms[0].id,
                        next_week + timedelta(days=1),
                        nights=3,
                    ),
                ],
            )

    def test_iptal_edilen_rezervasyon_odayi_serbest_birakir(
        self,
        admin_ctx,
        property_with_rooms,
        sample_room_type,
        sample_rooms,
        guest,
        second_guest,
        next_week,
    ):
        service = ReservationService(admin_ctx)
        first = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        service.cancel(first.id, reason="Musteri talebi")

        # Ayni tarihlere yeni rezervasyon artik yapilabilmeli.
        second = service.create_reservation(
            guest_id=second_guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        assert second.status is ReservationStatus.CONFIRMED


class TestBakimBlokesi:
    def test_bakimdaki_odaya_rezervasyon_yapilamaz(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        room = sample_rooms[0]
        room.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        room.out_of_service_from = next_week - timedelta(days=1)
        room.out_of_service_until = next_week + timedelta(days=10)
        admin_ctx.session.commit()

        service = ReservationService(admin_ctx)
        with pytest.raises(RoomOutOfServiceError):
            service.create_reservation(
                guest_id=guest.id,
                room_requests=[make_request(sample_room_type.id, room.id, next_week)],
            )

    def test_blok_disindaki_tarihe_rezervasyon_yapilabilir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        room = sample_rooms[0]
        room.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        room.out_of_service_from = next_week - timedelta(days=5)
        room.out_of_service_until = next_week - timedelta(days=1)
        admin_ctx.session.commit()

        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, room.id, next_week)],
        )
        assert reservation.id is not None


class TestKaraListe:
    def test_kara_listedeki_misafir_engellenir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        guest.is_blacklisted = True
        guest.blacklist_reason = "Odeme sorunu"
        admin_ctx.session.commit()

        service = ReservationService(admin_ctx)
        with pytest.raises(BusinessRuleError) as hata:
            service.create_reservation(
                guest_id=guest.id,
                room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
            )
        # NOT: pytest'in `match` parametresi str(exception) uzerinde calisir;
        # HotelError'da bu deger teknik `detail` alanidir. Kullaniciya
        # gosterilen metni dogrulamak icin user_message kontrol edilir.
        assert "kara listede" in hata.value.user_message
        assert hata.value.code == "guest_blacklisted"

    def test_yetkili_kara_listeyi_asabilir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        guest.is_blacklisted = True
        admin_ctx.session.commit()

        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
            allow_blacklisted=True,
        )
        assert reservation.id is not None

    def test_yetkisiz_kullanici_kara_listeyi_asamaz(
        self, frontdesk_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        guest.is_blacklisted = True
        frontdesk_ctx.session.commit()

        service = ReservationService(frontdesk_ctx)
        with pytest.raises(AuthorizationError):
            service.create_reservation(
                guest_id=guest.id,
                room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
                allow_blacklisted=True,
            )


class TestDurumGecisleri:
    def test_iptal_edilen_rezervasyon_yeniden_iptal_edilemez(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        service.cancel(reservation.id, reason="Ilk iptal")

        with pytest.raises(InvalidStateTransitionError):
            service.cancel(reservation.id, reason="Ikinci iptal")

    def test_iptal_gerekcesi_zorunlu(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        with pytest.raises(ValidationError, match="gerekce"):
            service.cancel(reservation.id, reason="   ")

    def test_no_show_cezasi_hesaplanir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        updated, fee = service.mark_no_show(reservation.id)

        assert updated.status is ReservationStatus.NO_SHOW
        # Fiyat planinda no_show_fee_percent = 100 -> tam tutar
        assert fee.amount == Decimal("2000.00")
        assert guest.no_show_count == 1

    def test_iptal_sayaci_artar(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )
        service.cancel(reservation.id, reason="Test")
        assert guest.cancellation_count == 1


class TestDegistirme:
    def test_tarih_degisimi_kendisiyle_cakismaz(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        """Rezervasyon kendi kaydiyla cakismamali - regresyon korumasi."""
        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[
                make_request(sample_room_type.id, sample_rooms[0].id, next_week, nights=2)
            ],
        )
        row = reservation.rooms[0]

        updated = service.change_dates(
            row.id,
            check_in=next_week,
            check_out=next_week + timedelta(days=4),
        )
        assert updated.nights == 4
        assert updated.total_amount == Decimal("4000.00")

    def test_tarih_degisimi_baskasiyla_cakisirsa_reddedilir(
        self,
        admin_ctx,
        property_with_rooms,
        sample_room_type,
        sample_rooms,
        guest,
        second_guest,
        next_week,
    ):
        service = ReservationService(admin_ctx)
        first = service.create_reservation(
            guest_id=guest.id,
            room_requests=[
                make_request(sample_room_type.id, sample_rooms[0].id, next_week, nights=2)
            ],
        )
        service.create_reservation(
            guest_id=second_guest.id,
            room_requests=[
                make_request(
                    sample_room_type.id,
                    sample_rooms[0].id,
                    next_week + timedelta(days=3),
                    nights=2,
                )
            ],
        )

        with pytest.raises(OverlappingReservationError):
            service.change_dates(
                first.rooms[0].id,
                check_in=next_week,
                check_out=next_week + timedelta(days=5),
            )

    def test_oda_atama(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        reservation = service.create_reservation(
            guest_id=guest.id,
            room_requests=[
                RoomRequest(
                    room_type_id=sample_room_type.id,
                    check_in=next_week,
                    check_out=next_week + timedelta(days=2),
                )
            ],
        )
        row = reservation.rooms[0]
        assert row.room_id is None  # oda tipi bazli rezervasyon

        updated = service.assign_room(row.id, sample_rooms[0].id)
        assert updated.room_id == sample_rooms[0].id


class TestMusaitlikArama:
    def test_musait_odalar_listelenir(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, next_week
    ):
        service = ReservationService(admin_ctx)
        results = service.search_availability(DateRange(next_week, next_week + timedelta(days=2)))
        assert len(results) == 1
        assert results[0].available_count == 3
        assert results[0].price is not None
        assert results[0].price.total.amount == Decimal("2000.00")

    def test_dolu_oda_listeden_cikar(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, guest, next_week
    ):
        service = ReservationService(admin_ctx)
        service.create_reservation(
            guest_id=guest.id,
            room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
        )

        results = service.search_availability(DateRange(next_week, next_week + timedelta(days=2)))
        assert results[0].available_count == 2
        assert sample_rooms[0].id not in results[0].available_room_ids

    def test_kapasitesi_yetmeyen_tip_gorunmez(
        self, admin_ctx, property_with_rooms, sample_room_type, sample_rooms, next_week
    ):
        service = ReservationService(admin_ctx)
        results = service.search_availability(
            DateRange(next_week, next_week + timedelta(days=2)), adults=8
        )
        assert results == []


class TestYetkilendirme:
    def test_yetkisiz_kullanici_rezervasyon_olusturamaz(
        self, secured_session, sample_property, sample_room_type, sample_rooms, guest, next_week
    ):
        from sqlalchemy import select

        from app.application.context import ServiceContext
        from app.infrastructure.db.models import Role, User
        from app.security.passwords import hash_password

        viewer_role = secured_session.scalars(select(Role).where(Role.code == "viewer")).one()
        viewer = User(
            username="izleyici",
            full_name="Test Izleyici",
            password_hash=hash_password("IzleyiciTest2026!"),
        )
        viewer.roles.append(viewer_role)
        secured_session.add(viewer)
        secured_session.commit()

        ctx = ServiceContext(session=secured_session, user=viewer, property_id=sample_property.id)
        service = ReservationService(ctx)

        with pytest.raises(AuthorizationError):
            service.create_reservation(
                guest_id=guest.id,
                room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
            )

    def test_yetki_reddi_denetime_yazilir(
        self, secured_session, sample_property, sample_room_type, sample_rooms, guest, next_week
    ):
        from sqlalchemy import select

        from app.application.context import ServiceContext
        from app.infrastructure.db.models import Role, User
        from app.infrastructure.db.models.security import AuditLog
        from app.security.passwords import hash_password

        viewer_role = secured_session.scalars(select(Role).where(Role.code == "viewer")).one()
        viewer = User(
            username="izleyici2",
            full_name="Test Izleyici 2",
            password_hash=hash_password("IzleyiciTest2026!"),
        )
        viewer.roles.append(viewer_role)
        secured_session.add(viewer)
        secured_session.commit()

        ctx = ServiceContext(session=secured_session, user=viewer, property_id=sample_property.id)
        with pytest.raises(AuthorizationError):
            ReservationService(ctx).create_reservation(
                guest_id=guest.id,
                room_requests=[make_request(sample_room_type.id, sample_rooms[0].id, next_week)],
            )

        kayitlar = secured_session.scalars(
            select(AuditLog).where(AuditLog.action == AuditAction.PERMISSION_DENIED)
        ).all()
        assert len(kayitlar) >= 1
        assert kayitlar[0].is_success is False
