"""Kimlik dogrulama, oturum ve yetkilendirme testleri.

Kapsanan kritik senaryolar:

* Yetkisiz kullanicinin finans modulune erisememesi
* Kaba kuvvet denemesinde hesabin kilitlenmesi
* Kullanici sayiminin (user enumeration) engellenmesi
* Oturum jetonunun veritabaninda duz metin saklanmamasi
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    AccountLockedError,
    AuthenticationError,
    AuthorizationError,
    SessionExpiredError,
)
from app.domain.enums import AuditAction
from app.infrastructure.db.models.security import AuditLog, User, UserSession
from app.security import auth
from app.security.permissions import Perm

pytestmark = pytest.mark.integration

ADMIN_PAROLA = "TestYonetici2026!"
RESEPSIYON_PAROLA = "ResepsiyonTest2026!"


class TestGiris:
    def test_basarili_giris_oturum_acar(self, secured_session, admin_user):
        sonuc = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        assert sonuc.user.username == "admin"
        assert sonuc.token
        assert sonuc.session_id > 0

    def test_yanlis_parola_reddedilir(self, secured_session, admin_user):
        with pytest.raises(AuthenticationError):
            auth.authenticate(secured_session, "admin", "YanlisParola123")

    def test_olmayan_kullanici_ayni_hatayi_verir(self, secured_session, admin_user):
        """Kullanici sayimi engellenmeli: iki durum ayni mesaji dondurmeli."""
        with pytest.raises(AuthenticationError) as yok:
            auth.authenticate(secured_session, "boyle-biri-yok", "HerhangiBir123")
        with pytest.raises(AuthenticationError) as yanlis:
            auth.authenticate(secured_session, "admin", "YanlisParola123")
        assert yok.value.user_message == yanlis.value.user_message

    def test_pasif_hesap_giris_yapamaz(self, secured_session, admin_user):
        admin_user.is_active = False
        secured_session.commit()
        with pytest.raises(AuthenticationError):
            auth.authenticate(secured_session, "admin", ADMIN_PAROLA)

    def test_basarili_giris_denetime_yazilir(self, secured_session, admin_user):
        auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        kayitlar = secured_session.scalars(
            select(AuditLog).where(AuditLog.action == AuditAction.LOGIN)
        ).all()
        assert len(kayitlar) == 1
        assert kayitlar[0].username == "admin"

    def test_basarisiz_giris_denetime_yazilir(self, secured_session, admin_user):
        with pytest.raises(AuthenticationError):
            auth.authenticate(secured_session, "admin", "YanlisParola123")
        kayitlar = secured_session.scalars(
            select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_FAILED)
        ).all()
        assert len(kayitlar) == 1
        assert kayitlar[0].is_success is False


class TestKabaKuvvetKorumasi:
    def test_ardisik_hatali_denemede_hesap_kilitlenir(self, secured_session, admin_user):
        for _ in range(5):
            with pytest.raises(AuthenticationError):
                auth.authenticate(secured_session, "admin", "YanlisParola123")

        # Artik dogru parolayla bile giremez.
        with pytest.raises(AccountLockedError) as hata:
            auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        assert "kilitlendi" in hata.value.user_message

    def test_basarili_giris_sayaci_sifirlar(self, secured_session, admin_user):
        for _ in range(3):
            with pytest.raises(AuthenticationError):
                auth.authenticate(secured_session, "admin", "YanlisParola123")
        assert admin_user.failed_login_count == 3

        auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        secured_session.refresh(admin_user)
        assert admin_user.failed_login_count == 0
        assert admin_user.locked_until is None


class TestOturum:
    def test_jeton_veritabaninda_duz_saklanmaz(self, secured_session, admin_user):
        """Veritabani sizsa bile aktif oturumlar ele gecirilememeli."""
        sonuc = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        oturum = secured_session.get(UserSession, sonuc.session_id)
        assert oturum is not None
        assert oturum.token_hash != sonuc.token
        assert sonuc.token not in oturum.token_hash

    def test_jeton_kullaniciyi_cozer(self, secured_session, admin_user):
        sonuc = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        cozulen = auth.resolve_session(secured_session, sonuc.token)
        assert cozulen.id == admin_user.id

    def test_gecersiz_jeton_reddedilir(self, secured_session, admin_user):
        with pytest.raises(SessionExpiredError):
            auth.resolve_session(secured_session, "gecersiz-jeton")

    def test_bos_jeton_reddedilir(self, secured_session):
        with pytest.raises(SessionExpiredError):
            auth.resolve_session(secured_session, "")

    def test_cikis_sonrasi_jeton_gecersiz(self, secured_session, admin_user):
        sonuc = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        assert auth.logout(secured_session, sonuc.token)
        with pytest.raises(SessionExpiredError):
            auth.resolve_session(secured_session, sonuc.token)

    def test_tum_oturumlar_iptal_edilebilir(self, secured_session, admin_user):
        birinci = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        ikinci = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)

        assert auth.revoke_all_sessions(secured_session, admin_user.id) == 2

        for sonuc in (birinci, ikinci):
            with pytest.raises(SessionExpiredError):
                auth.resolve_session(secured_session, sonuc.token)

    def test_parola_degisimi_oturumlari_kapatir(self, secured_session, admin_user):
        sonuc = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        auth.change_password(
            secured_session,
            admin_user,
            current_password=ADMIN_PAROLA,
            new_password="YeniGucluParola2026",
        )
        with pytest.raises(SessionExpiredError):
            auth.resolve_session(secured_session, sonuc.token)

    def test_yanlis_mevcut_parolayla_degisim_reddedilir(self, secured_session, admin_user):
        with pytest.raises(AuthenticationError):
            auth.change_password(
                secured_session,
                admin_user,
                current_password="YanlisParola123",
                new_password="YeniGucluParola2026",
            )


class TestYetkilendirme:
    def test_yetkisiz_kullanici_finans_modulune_erisemez(self, secured_session, frontdesk_user):
        """KRITIK: on buro personeli mali raporlari goremez."""
        assert not frontdesk_user.has_permission(Perm.REPORT_FINANCIAL)
        with pytest.raises(AuthorizationError) as hata:
            auth.require_permission(frontdesk_user, Perm.REPORT_FINANCIAL)
        assert hata.value.permission == Perm.REPORT_FINANCIAL

    def test_yetkisiz_kullanici_ucret_gecersiz_kilamaz(self, secured_session, frontdesk_user):
        with pytest.raises(AuthorizationError):
            auth.require_permission(frontdesk_user, Perm.FOLIO_VOID_CHARGE)

    def test_yetkili_kullanici_gecebilir(self, secured_session, frontdesk_user):
        auth.require_permission(frontdesk_user, Perm.RESERVATION_CREATE)
        auth.require_permission(frontdesk_user, Perm.FRONTDESK_CHECKIN)

    def test_superuser_tum_izinlere_sahiptir(self, secured_session, admin_user):
        assert admin_user.has_permission(Perm.DEVCENTER_EXECUTE)
        assert admin_user.has_permission("var-olmayan.izin")

    def test_giris_yapmamis_kullanici_reddedilir(self):
        with pytest.raises(AuthenticationError):
            auth.require_permission(None, Perm.RESERVATION_VIEW)

    def test_joker_izin_modulu_kapsar(self, secured_session):
        from app.infrastructure.db.models.security import Permission, Role
        from app.security.passwords import hash_password

        joker = Permission(
            code="reservation.*", name="Tum rezervasyon yetkileri", category="Rezervasyon"
        )
        rol = Role(code="rez_yonetici", name="Rezervasyon Yoneticisi")
        rol.permissions.append(joker)
        kullanici = User(
            username="joker_test",
            full_name="Joker Test",
            password_hash=hash_password("JokerTest2026!"),
        )
        kullanici.roles.append(rol)
        secured_session.add_all([joker, rol, kullanici])
        secured_session.commit()

        assert kullanici.has_permission(Perm.RESERVATION_CREATE)
        assert kullanici.has_permission(Perm.RESERVATION_CANCEL)
        assert not kullanici.has_permission(Perm.FINANCE_MANAGE)

    def test_pasif_rol_izin_vermez(self, secured_session, frontdesk_user):
        for rol in frontdesk_user.roles:
            rol.is_active = False
        secured_session.commit()
        assert not frontdesk_user.has_permission(Perm.RESERVATION_CREATE)


class TestOturumTemizligi:
    def test_suresi_dolmus_oturumlar_silinir(self, secured_session, admin_user):
        from datetime import timedelta

        from app.infrastructure.db.base import utcnow

        sonuc = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        oturum = secured_session.get(UserSession, sonuc.session_id)
        oturum.expires_at = utcnow() - timedelta(hours=1)
        secured_session.commit()

        assert auth.purge_expired_sessions(secured_session) == 1
        assert secured_session.get(UserSession, sonuc.session_id) is None
