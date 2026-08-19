"""Izin katalogu ve kurulum (bootstrap) testleri."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.infrastructure.db.models.security import Permission, Role, User
from app.security.bootstrap import bootstrap_security, sync_permissions, sync_roles
from app.security.permissions import (
    DEFAULT_ROLES,
    PERMISSIONS,
    Perm,
    permissions_by_category,
    validate_catalog,
)

pytestmark = pytest.mark.integration


class TestKatalog:
    def test_katalog_tutarli(self):
        """Izin kodlari benzersiz ve roller yalnizca var olan izinleri kullanir."""
        validate_catalog()

    def test_izin_kodlari_modul_nokta_eylem_biciminde(self):
        for spec in PERMISSIONS:
            assert "." in spec.code, f"Gecersiz izin kodu: {spec.code}"
            assert spec.code == spec.code.lower()

    def test_tehlikeli_izinler_isaretli(self):
        tehlikeli = {p.code for p in PERMISSIONS if p.is_dangerous}
        assert Perm.DEVCENTER_EXECUTE in tehlikeli
        assert Perm.GUEST_VIEW_IDENTITY in tehlikeli
        assert Perm.BACKUP_RESTORE in tehlikeli

    def test_kategoriye_gore_gruplama(self):
        gruplar = permissions_by_category()
        assert "Rezervasyon" in gruplar
        assert "Yapay Zeka" in gruplar

    def test_goruntuleyici_rolu_yazma_yetkisi_icermez(self):
        viewer = next(r for r in DEFAULT_ROLES if r.code == "viewer")
        yazma_belirtecleri = ("create", "edit", "delete", "manage", "approve", "execute")
        for kod in viewer.permissions:
            eylem = kod.split(".", 1)[1]
            assert not any(
                m in eylem for m in yazma_belirtecleri
            ), f"Goruntuleyici rolunde yazma yetkisi var: {kod}"

    def test_mudur_rolu_gelistirme_merkezine_erisemez(self):
        manager = next(r for r in DEFAULT_ROLES if r.code == "manager")
        assert not any(k.startswith("devcenter.") for k in manager.permissions)


class TestKurulum:
    def test_izinler_veritabanina_yazilir(self, session):
        olusan, guncellenen = sync_permissions(session)
        session.commit()
        assert olusan == len(PERMISSIONS)
        assert guncellenen == 0
        assert session.scalar(select(Permission).where(Permission.code == Perm.AI_USE))

    def test_kurulum_idempotenttir(self, session):
        """Ikinci calistirmada hicbir sey degismemeli."""
        sync_permissions(session)
        session.commit()
        olusan, guncellenen = sync_permissions(session)
        session.commit()
        assert olusan == 0
        assert guncellenen == 0

    def test_roller_izinleriyle_olusturulur(self, session):
        sync_permissions(session)
        olusan, _ = sync_roles(session)
        session.commit()
        assert olusan == len(DEFAULT_ROLES)

        frontdesk = session.scalars(select(Role).where(Role.code == "frontdesk")).one()
        kodlar = {p.code for p in frontdesk.permissions}
        assert Perm.FRONTDESK_CHECKIN in kodlar
        assert Perm.REPORT_FINANCIAL not in kodlar

    def test_kullanici_tanimli_rol_ezilmez(self, session):
        """Yonetici kendi rolunu tanimladiysa surum yukseltmesi bozmamali."""
        sync_permissions(session)
        sync_roles(session)
        ozel = Role(code="gece_muduru", name="Gece Muduru", is_system=False)
        ozel.permissions = list(session.scalars(select(Permission).limit(2)))
        session.add(ozel)
        session.commit()

        sync_roles(session)
        session.commit()
        session.refresh(ozel)
        assert len(ozel.permissions) == 2

    def test_tam_kurulum_yonetici_uretir(self, session):
        sonuc = bootstrap_security(session, create_admin=True)
        assert sonuc.admin_created
        assert sonuc.generated_password
        assert len(sonuc.generated_password) >= 12

        admin = session.scalars(select(User).where(User.username == "admin")).one()
        assert admin.is_superuser
        assert admin.must_change_password

    def test_verilen_parola_ile_yonetici(self, session):
        from app.security.passwords import verify_password

        sonuc = bootstrap_security(session, admin_password="BelirlenmisParola2026!")
        assert sonuc.generated_password is None

        admin = session.scalars(select(User).where(User.username == "admin")).one()
        assert verify_password("BelirlenmisParola2026!", admin.password_hash)
        assert not admin.must_change_password

    def test_mevcut_yonetici_yeniden_olusturulmaz(self, session):
        bootstrap_security(session)
        sonuc = bootstrap_security(session)
        assert not sonuc.admin_created
        assert sonuc.generated_password is None
