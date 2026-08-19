"""Sifreleme katmaninin **fail-closed** davranisinin gerileme testleri.

Bagimsiz guvenlik incelemesinde dogrulanan iki bulguyu koda baglar:

* **HTL-H2** - kor indeks, kaynak koda gomulu sabit bir anahtara geri
  dusuyordu. Kaynak kod yayimlandiginda o sabit herkesce bilinir hale gelir;
  kimlik numarasi uzayi kucuk oldugu icin veritabani dosyasini eline
  gecirmis biri sifreyi hic kirmadan numaralari cevrimdisi tarayabilirdi.
* **HTL-H3** - anahtar kalici olarak saklanamadiginda her acilista yeni
  anahtar uretiliyor, cozulemeyen kayitlar icin ``""`` donduruluyordu.
  Kullanici bos gorunen alanin uzerine yazinca sifreli kisisel veri kalici
  olarak kayboluyordu.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ConfigurationError, DecryptionError
from app.infrastructure.db import types as db_types

pytestmark = pytest.mark.integration


class TestKorIndeksSabitYedekYok:
    def test_gomulu_sabit_yedek_anahtar_yok(self):
        """Kaynakta 'gelistirme-varsayilani' turu bir yedek bulunmamalidir."""
        import inspect

        kaynak = inspect.getsource(db_types)
        assert "gelistirme-varsayilani" not in kaynak
        assert 'os.environ.get(\n        "HOTEL_FIELD_ENCRYPTION_KEY", ' not in kaynak

    def test_anahtar_yoksa_uretim_ortaminda_hata_verir(self, monkeypatch: pytest.MonkeyPatch):
        """Anahtar materyali yoksa kor indeks **hesaplanmaz**, hata verir."""
        monkeypatch.setattr(db_types, "_key_material", lambda: None)

        class _SahteAyar:
            is_testing = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: _SahteAyar())

        with pytest.raises(ConfigurationError) as hata:
            db_types.blind_index("11111111110")
        assert hata.value.code == "blind_index_key_missing"

    def test_test_ortaminda_sabit_test_anahtari_kullanilir(self, monkeypatch: pytest.MonkeyPatch):
        """Testler anahtarsiz calisabilmeli; ama o anahtar gercek veriye gitmez."""
        monkeypatch.setattr(db_types, "_key_material", lambda: None)

        class _SahteAyar:
            is_testing = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: _SahteAyar())
        indeks = db_types.blind_index("11111111110")
        assert indeks is not None

    def test_indeks_anahtara_bagimlidir(self, monkeypatch: pytest.MonkeyPatch):
        """Farkli anahtar -> farkli indeks. Anahtar gercekten kullaniliyor mu?"""
        monkeypatch.setattr(db_types, "_key_material", lambda: "anahtar-bir")
        birinci = db_types.blind_index("11111111110")
        monkeypatch.setattr(db_types, "_key_material", lambda: "anahtar-iki")
        ikinci = db_types.blind_index("11111111110")
        assert birinci != ikinci


class TestAnahtarKaliciDegilseDurur:
    def test_keyring_yoksa_ve_ortam_bossa_hata_verir(self, monkeypatch: pytest.MonkeyPatch):
        """Sessizce yeni anahtar uretmek yerine gurultulu sekilde durur."""
        from app.core.secret_store import SecretBackend

        db_types._get_fernet.cache_clear()
        monkeypatch.setattr(db_types, "_key_material", lambda: None)
        monkeypatch.setattr(db_types, "set_secret", lambda *a, **k: SecretBackend.ENV)
        try:
            with pytest.raises(ConfigurationError) as hata:
                db_types._get_fernet()
            assert hata.value.code == "field_encryption_key_not_persistable"
        finally:
            db_types._get_fernet.cache_clear()

    def test_durum_raporu_kullanilamaz_durumu_bildirir(self, monkeypatch: pytest.MonkeyPatch):
        """Ilk kurulum sihirbazi kullaniciyi VERI GIRMEDEN once uyarabilmeli."""
        monkeypatch.setattr(db_types, "_key_material", lambda: None)
        monkeypatch.setattr(db_types, "is_keyring_available", lambda: False)
        uygun, mesaj = db_types.encryption_key_status()
        assert uygun is False
        assert "HOTEL_FIELD_ENCRYPTION_KEY" in mesaj

    def test_durum_raporu_anahtar_varken_olumlu(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(db_types, "_key_material", lambda: "bir-anahtar")
        uygun, _mesaj = db_types.encryption_key_status()
        assert uygun is True


class TestCozulemeyenKayitSessizceBosalmaz:
    def test_gecersiz_jeton_hata_firlatir(self):
        """Bos dizge dondurmek, verinin uzerine yazilmasina yol aciyordu."""
        bozuk = "enc:v1:" + "Z" * 60
        with pytest.raises(DecryptionError) as hata:
            db_types.decrypt_value(bozuk)
        assert hata.value.code == "field_decryption_failed"
        # Kullaniciya "uzerine yazma" uyarisi verilmelidir.
        assert "YAZMAYIN" in (hata.value.detail or "")

    def test_isaretsiz_eski_deger_hala_gecer(self):
        """Sifreleme sonradan devreye alindiginda eski kayitlar bozulmamali."""
        assert db_types.decrypt_value("duz-metin-eski-kayit") == "duz-metin-eski-kayit"

    def test_bos_deger_guvenli(self):
        assert db_types.decrypt_value("") == ""


class TestLogMaskelemeOneksizAnahtarlar:
    """HTL-H1 (ikinci yarisi): onek tasimayan sirlar maskelenmiyordu."""

    @pytest.mark.parametrize(
        "satir",
        [
            "HOTEL_SECRET_KEY=ORNEK-DEGER-BU-BIR-SIR-DEGILDIR",
            "HOTEL_FIELD_ENCRYPTION_KEY=ORNEK-DEGER-BU-BIR-SIR-DEGILDIR",
            "db_password: ORNEK-PAROLA-GERCEK-DEGIL",
            'client_secret = "ORNEK-DEGER-GERCEK-DEGIL"',
            "SESSION_TOKEN=ORNEK-JETON-GERCEK-DEGIL",
        ],
    )
    def test_oneksiz_sir_atamalari_maskelenir(self, satir: str):
        from app.core.log import MASK, mask_text

        sonuc = mask_text(satir)
        assert MASK in sonuc, satir
        deger = satir.split("=", 1)[-1].split(":", 1)[-1].strip().strip("\"'")
        assert deger not in sonuc, satir

    def test_zararsiz_atamalar_bozulmaz(self):
        from app.core.log import mask_text

        assert mask_text("room_number=101") == "room_number=101"
        assert mask_text("HOTEL_LOG_LEVEL=INFO") == "HOTEL_LOG_LEVEL=INFO"
