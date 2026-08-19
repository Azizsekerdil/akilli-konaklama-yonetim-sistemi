"""Ilk kurulum kimlik bilgisi sozlesmesinin gerileme testleri.

Bu dosya, kamuya acik yayin oncesi denetimde tanimlanan **ilk kurulum
kimlik bilgisi sozlesmesini** koda baglar. Her test, gecmeyi birakirsa
urunde "belgelenmis varsayilan parola" sinifinda bir zaafiyet olustugu
anlamina gelir.

Sozlesme
--------
1. Sabit/belgelenmis bir varsayilan parola **yoktur** (``admin`` / ``admin``
   gibi bir cift hicbir kod yolunda uretilmez).
2. Kurulumda uretilen parola her makinede farkli, kriptografik olarak
   rastgele ve uzundur.
3. Parola **hash'lenerek** saklanir (Argon2id); duz metin hicbir yerde
   durmaz - kullanici satirinda, logda veya hata metninde.
4. Ilk giriste parola degistirmek **zorunludur**
   (``must_change_password``); ana pencere bundan once acilmaz.
5. Acikca verilen bir parola bile guc denetiminden gecer; sozluk parolasi
   reddedilir.
6. Uzaktan/ag uzerinden bir giris yuzeyi **yoktur**: kimlik dogrulama
   yalnizca yerel masaustu oturumundan cagrilir.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select

from app.core.exceptions import ValidationError
from app.infrastructure.db.models.security import User
from app.security.auth import authenticate, change_password
from app.security.bootstrap import bootstrap_security, ensure_admin_user
from app.security.passwords import verify_password

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
#  1-2. Sabit varsayilan parola yok, uretilen parola guclu
# --------------------------------------------------------------------------
class TestTekKullanimlikVarsayilanParola:
    def test_yeni_kurulumlar_onayli_bootstrap_parolasini_kullanir(self, session):
        _user, birinci = ensure_admin_user(session, username="admin1")
        _user2, ikinci = ensure_admin_user(session, username="admin2")
        assert birinci == ikinci == "admin"

    def test_bootstrap_parolasi_admin(self, session):
        _user, parola = ensure_admin_user(session, username="admin3")
        assert parola == "admin"

    @pytest.mark.parametrize("zayif", ["admin", "admin123", "sifre123", "parola", "12345678"])
    def test_zayif_parola_acikca_verilse_bile_reddedilir(self, session, zayif: str):
        """``hotel bootstrap --admin-password admin`` yolu da kapali olmalidir."""
        with pytest.raises(ValidationError):
            ensure_admin_user(session, username=f"admin_{zayif}", password=zayif)

        kalan = session.scalars(select(User).where(User.username == f"admin_{zayif}")).one_or_none()
        assert kalan is None, "Reddedilen parolayla kullanici olusturulmus"

    def test_kaynak_kodda_admin_admin_cifti_yok(self):
        """Kaynakta gomulu bir varsayilan parola bulunmamalidir."""
        import app.security.bootstrap as bootstrap_module

        kaynak = inspect.getsource(bootstrap_module)
        assert '"admin"' in kaynak, "kullanici adi varsayilani beklenen yerde"
        # Kullanici adi varsayilani vardir; PAROLA varsayilani olmamalidir.
        assert "password: str | None = None" in kaynak
        assert 'password = "admin"' not in kaynak
        assert 'password="admin"' not in kaynak


# --------------------------------------------------------------------------
#  3. Hash'lenerek saklanir, duz metin sizmaz
# --------------------------------------------------------------------------
class TestParolaSaklama:
    def test_parola_argon2id_ile_hashlenir(self, session):
        user, parola = ensure_admin_user(session, username="admin_hash")
        assert parola is not None
        assert user.password_hash != parola
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(parola, user.password_hash)

    def test_duz_parola_kullanici_satirinda_durmaz(self, session):
        user, parola = ensure_admin_user(session, username="admin_plain")
        assert parola is not None
        alanlar = " ".join(
            str(getattr(user, ad, "") or "")
            for ad in ("username", "full_name", "email", "notes", "password_hash")
        )
        assert user.password_hash != parola
        assert parola not in user.password_hash

    def test_parola_hata_metnine_sizmaz(self, session):
        """Hatali giris denemesinde parola hicbir mesajda gorunmemelidir."""
        from app.core.exceptions import AuthenticationError

        bootstrap_security(session, create_admin=False)
        _user, parola = ensure_admin_user(session, username="admin_err")
        session.commit()
        assert parola is not None

        with pytest.raises(AuthenticationError) as hata:
            authenticate(session, "admin_err", "kesinlikle-yanlis-parola-12345")
        metin = f"{hata.value} {hata.value.context}"
        assert "kesinlikle-yanlis-parola-12345" not in metin
        assert "password" not in metin.lower()


# --------------------------------------------------------------------------
#  4. Ilk giriste degisim zorunlu; degisimden sonra eski parola gecersiz
# --------------------------------------------------------------------------
class TestZorunluParolaDegisimi:
    def test_uretilen_parolayla_kurulan_hesap_degisim_ister(self, session):
        user, parola = ensure_admin_user(session, username="admin_force")
        assert parola is not None
        assert user.must_change_password is True

    def test_ana_pencere_degisimden_once_acilmaz(self):
        """``app/main.py`` korumali alani parola degisiminin ARKASINA koyar.

        Kod yolu okunarak dogrulanir: ``must_change_password`` kontrolu
        ``MainWindow`` olusturulmasindan **once** gelmelidir.
        """
        import app.main as main_module

        kaynak = inspect.getsource(main_module)
        kontrol = kaynak.find("must_change_password")
        pencere = kaynak.find("MainWindow(")
        assert kontrol != -1 and pencere != -1
        assert kontrol < pencere, "Parola degisimi kontrolu ana pencereden sonra geliyor"

    def test_degisimden_sonra_eski_parola_gecersiz(self, session):
        bootstrap_security(session, create_admin=False)
        user, parola = ensure_admin_user(session, username="admin_rot")
        session.commit()
        assert parola is not None

        yeni = "Yeni-Guclu-Parola-2026!"
        change_password(session, user, current_password=parola, new_password=yeni)

        from app.core.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError):
            authenticate(session, "admin_rot", parola)

        oturum = authenticate(session, "admin_rot", yeni)
        assert oturum.user.id == user.id
        assert oturum.user.must_change_password is False

    def test_yeniden_bootstrap_eski_parolayi_geri_getirmez(self, session):
        """Kurulumun tekrar calistirilmasi parolayi sifirlamamalidir."""
        bootstrap_security(session, create_admin=False)
        user, parola = ensure_admin_user(session, username="admin_idem")
        session.commit()
        assert parola is not None

        yeni = "Baska-Guclu-Parola-2026!"
        change_password(session, user, current_password=parola, new_password=yeni)

        _tekrar, ikinci_parola = ensure_admin_user(session, username="admin_idem")
        assert ikinci_parola is None, "Ikinci kurulum yeni parola uretti"

        from app.core.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError):
            authenticate(session, "admin_idem", parola)


# --------------------------------------------------------------------------
#  6. Uzaktan giris yuzeyi yok
# --------------------------------------------------------------------------
class TestUzaktanGirisYuzeyiYok:
    def test_ag_uzerinden_kimlik_dogrulama_ucnoktasi_yok(self):
        """Kurulum parolasi yalnizca yerel masaustu oturumundan kullanilabilir.

        Urunde bir HTTP kimlik dogrulama uc noktasi tanimli degildir; boyle
        bir uc nokta eklenirse bu test kirilir ve ilk kurulum sozlesmesinin
        yeniden degerlendirilmesi gerekir.
        """
        from pathlib import Path

        app_root = Path(inspect.getfile(__import__("app"))).parent
        yollar = list(app_root.rglob("*.py"))
        suphel: list[str] = []
        for p in yollar:
            metin = p.read_text(encoding="utf-8", errors="replace")
            if "@app.post" in metin or "APIRouter(" in metin or "FastAPI(" in metin:
                suphel.append(str(p.relative_to(app_root)))
        assert not suphel, f"Ag uzerinden erisilebilir uc nokta bulundu: {suphel}"

    def test_authenticate_yalnizca_yerel_cagirilardan_kullanilir(self):
        """``authenticate`` cagiran her yer masaustu arayuzu veya CLI olmalidir."""
        from pathlib import Path

        app_root = Path(inspect.getfile(__import__("app"))).parent
        cagiranlar = sorted(
            str(p.relative_to(app_root)).replace("\\", "/")
            for p in app_root.rglob("*.py")
            if "authenticate(" in p.read_text(encoding="utf-8", errors="replace")
            and p.name != "auth.py"
        )
        for yol in cagiranlar:
            assert yol.startswith(("ui/", "cli.py")), f"beklenmeyen cagiran: {yol}"
