"""Alan seviyesi sifreleme ve maskeleme testleri.

Kimlik numarasi gibi ozel nitelikli kisisel verinin veritabaninda duz metin
olarak durmadigini **fiilen** dogrular: ham SQL ile okuyup icerigi kontrol
eder.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.log import mask_text, mask_value
from app.infrastructure.db.models import Guest
from app.infrastructure.db.types import (
    blind_index,
    decrypt_value,
    encrypt_value,
    mask_identity,
)

pytestmark = pytest.mark.integration


class TestSifreleme:
    def test_sifrele_coz_dongusu(self):
        acik = "12345678901"
        sifreli = encrypt_value(acik)
        assert sifreli != acik
        assert acik not in sifreli
        assert decrypt_value(sifreli) == acik

    def test_ayni_deger_farkli_sifreli_metin_uretir(self):
        """Fernet rastgele nonce kullanir; desen analizi engellenir."""
        assert encrypt_value("12345678901") != encrypt_value("12345678901")

    def test_duz_metin_degerler_bozulmadan_gecer(self):
        """Sifreleme sonradan devreye alindiginda eski kayitlar okunabilmeli."""
        assert decrypt_value("sifresiz-eski-deger") == "sifresiz-eski-deger"

    def test_bos_deger_guvenli(self):
        assert encrypt_value("") == ""
        assert decrypt_value("") == ""


class TestKorIndeks:
    def test_ayni_deger_ayni_indeksi_uretir(self):
        """Sifreli alanda esitlik aramasi ancak boyle mumkun olur."""
        assert blind_index("12345678901") == blind_index("12345678901")

    def test_farkli_deger_farkli_indeks(self):
        assert blind_index("12345678901") != blind_index("10987654321")

    def test_indeks_ham_degeri_icermez(self):
        indeks = blind_index("12345678901")
        assert indeks is not None
        assert "12345678901" not in indeks

    def test_bosluklar_onemsizdir(self):
        assert blind_index(" 12345678901 ") == blind_index("12345678901")

    def test_bos_deger_none_doner(self):
        assert blind_index(None) is None
        assert blind_index("") is None


class TestVeritabaninaYazim:
    def test_kimlik_numarasi_diskte_duz_metin_degil(self, session, sample_guest):
        """KRITIK KVKK KONTROLU: ham SQL ile okundugunda numara gorunmemeli."""
        ham = session.execute(
            text("SELECT identity_number FROM guest WHERE id = :id"),
            {"id": sample_guest.id},
        ).scalar_one()

        assert ham is not None
        assert "11111111110" not in ham
        assert ham.startswith("enc:v1:")

    def test_orm_uzerinden_okunca_cozulur(self, session, sample_guest):
        session.expire_all()
        misafir = session.get(Guest, sample_guest.id)
        assert misafir is not None
        assert misafir.identity_number == "11111111110"

    def test_kor_indeks_ile_arama_calisir(self, session, sample_guest):
        from sqlalchemy import select

        aranan = blind_index("11111111110")
        bulunan = session.scalars(select(Guest).where(Guest.identity_index == aranan)).one_or_none()
        assert bulunan is not None
        assert bulunan.id == sample_guest.id

    def test_set_identity_ikisini_birlikte_gunceller(self, session, sample_guest):
        sample_guest.set_identity("22222222220")
        session.commit()
        assert sample_guest.identity_index == blind_index("22222222220")


class TestMaskeleme:
    def test_kimlik_numarasi_maskelenir(self):
        assert mask_identity("12345678901") == "123*****901"

    def test_kisa_deger_tamamen_maskelenir(self):
        assert mask_identity("12345") == "*****"

    def test_bos_deger(self):
        assert mask_identity(None) == "-"

    def test_log_maskeleme_api_anahtarini_gizler(self):
        assert "sk-gizli" not in mask_text("anahtar sk-gizli1234567890 burada")

    def test_log_maskeleme_eposta_kisaltir(self):
        assert mask_text("misafir ahmet@ornek.com") == "misafir a***@ornek.com"

    def test_hassas_alan_adi_tamamen_maskelenir(self):
        assert mask_value("api_key", "gercek-anahtar") == "***MASKELENDI***"
        assert mask_value("national_id", "12345678901") == "***MASKELENDI***"

    def test_zararsiz_alan_degismez(self):
        assert mask_value("room_number", "101") == "101"

    def test_ic_ice_sozluk_maskelenir(self):
        sonuc = mask_value("guest", {"name": "Ali", "password": "gizli"})
        assert sonuc["name"] == "Ali"
        assert sonuc["password"] == "***MASKELENDI***"
