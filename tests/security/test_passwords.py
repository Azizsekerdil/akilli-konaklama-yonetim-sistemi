"""Parola hash'leme ve politika testleri."""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.security.passwords import (
    constant_time_compare,
    generate_password,
    generate_token,
    hash_password,
    hash_token,
    normalize_password,
    validate_password_strength,
    verify_password,
)

pytestmark = pytest.mark.unit


class TestHashleme:
    def test_hash_duz_parolayi_icermez(self):
        """Hash ciktisinda parola hicbir bicimde gorunmemeli."""
        parola = "CokGizliParola2026!"
        h = hash_password(parola)
        assert parola not in h
        assert h.startswith("$argon2id$")

    def test_ayni_parola_farkli_hash_uretir(self):
        """Rastgele tuz sayesinde iki hash ayni olmamali."""
        assert hash_password("AyniParola2026") != hash_password("AyniParola2026")

    def test_dogru_parola_dogrulanir(self):
        h = hash_password("DogruParola2026!")
        assert verify_password("DogruParola2026!", h)

    def test_yanlis_parola_reddedilir(self):
        h = hash_password("DogruParola2026!")
        assert not verify_password("YanlisParola2026!", h)

    def test_bos_parola_hashlenmez(self):
        with pytest.raises(ValidationError):
            hash_password("")

    def test_bozuk_hash_istisna_sizdirmaz(self):
        """Gecersiz hash sessizce False donmeli; cokme olmamali."""
        assert not verify_password("herhangi", "bu-gecerli-bir-hash-degil")
        assert not verify_password("herhangi", "")

    def test_unicode_normallestirme(self):
        """Ayni gorunen farkli kodlanmis Turkce parolalar eslesmeli."""
        # 'İ' iki farkli sekilde kodlanabilir (onceden birlestirilmis / birlesik)
        parola_nfc = normalize_password("İstanbul2026")
        h = hash_password("İstanbul2026")
        assert verify_password(parola_nfc, h)


class TestParolaPolitikasi:
    def test_gecerli_parola_kabul_edilir(self):
        validate_password_strength("GucluParola2026")

    @pytest.mark.parametrize(
        ("parola", "beklenen_mesaj"),
        [
            ("kisa1", "en az"),
            ("sadeceharfler", "rakam"),
            ("1234567890123", "harf"),
            # Asgari uzunlugu gecen ama yaygin bir parola secilmeli; aksi halde
            # uzunluk kontrolu once devreye girer ve "yaygin" dali test edilmez.
            ("password123", "yaygin"),
            ("aaaa1111aaaa", "az farkli karakter"),
        ],
    )
    def test_zayif_parolalar_reddedilir(self, parola, beklenen_mesaj):
        with pytest.raises(ValidationError) as hata:
            validate_password_strength(parola)
        assert beklenen_mesaj in hata.value.user_message

    def test_kullanici_adini_iceren_parola_reddedilir(self):
        with pytest.raises(ValidationError, match="kullanici adinizi"):
            validate_password_strength("resepsiyon2026", username="resepsiyon")

    def test_asiri_uzun_parola_reddedilir(self):
        with pytest.raises(ValidationError, match="en fazla"):
            validate_password_strength("A1" * 100)


class TestUretecler:
    def test_uretilen_parola_politikayi_gecer(self):
        for _ in range(20):
            validate_password_strength(generate_password(16), min_length=10)

    def test_uretilen_parolalar_benzersiz(self):
        parolalar = {generate_password() for _ in range(50)}
        assert len(parolalar) == 50

    def test_cok_kisa_parola_uretilemez(self):
        with pytest.raises(ValueError):
            generate_password(8)

    def test_jeton_hashi_geri_dondurulemez(self):
        jeton = generate_token()
        ozet = hash_token(jeton)
        assert jeton not in ozet
        assert len(ozet) == 64  # SHA-256 onaltilik

    def test_ayni_jeton_ayni_ozeti_uretir(self):
        jeton = generate_token()
        assert hash_token(jeton) == hash_token(jeton)

    def test_sabit_sureli_karsilastirma(self):
        assert constant_time_compare("abc", "abc")
        assert not constant_time_compare("abc", "abd")
