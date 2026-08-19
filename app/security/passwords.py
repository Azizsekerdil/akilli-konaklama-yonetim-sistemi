"""Parola hash'leme ve guc denetimi.

Neden Argon2id?
---------------
Argon2id, 2015 Password Hashing Competition kazanani ve OWASP'in birinci
onerisidir. Bcrypt'ten farkli olarak **bellek-zor** (memory-hard) bir
algoritmadir: saldirganin GPU/ASIC ile paralel deneme yapmasi, her deneme
icin megabaytlarca RAM gerektirdiginden ekonomik olmaktan cikar.

Parametreler :class:`~app.core.config.SecuritySettings` uzerinden
ayarlanabilir; varsayilanlar masaustu bir uygulamada giris gecikmesini
makul tutacak sekilde secilmistir (~50-100 ms).
"""

from __future__ import annotations

import re
import secrets as _stdlib_secrets
import string
import unicodedata
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.core.exceptions import ValidationError

#: Sik kullanilan, sozluk saldirisinda ilk denenen paralolar.
COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        # Kisa olanlar (uzunluk kontrolu bunlari zaten yakalar, yine de listede)
        "123456",
        "password",
        "12345678",
        "qwerty",
        "123456789",
        "12345",
        "1234",
        "111111",
        "1234567",
        "dragon",
        "123123",
        "admin",
        "sifre",
        "parola",
        "sifre123",
        "parola123",
        "admin123",
        "otel123",
        "hotel123",
        "qwerty123",
        "1q2w3e4r",
        "iloveyou",
        "asdasd",
        "123qwe",
        "zxcvbnm",
        "159357",
        "sifrem",
        "deneme",
        "test123",
        "user123",
        "root123",
        # Asgari uzunlugu gecen ama yine de cok yaygin olanlar - asil onemli
        # kisim burasidir, cunku uzunluk kontrolu bunlari elemez.
        "password123",
        "passw0rd123",
        "qwertyuiop",
        "1234567890",
        "123456789012",
        "admin12345",
        "sifre12345",
        "parola12345",
        "qwerty12345",
        "iloveyou123",
        "welcome123",
        "hosgeldiniz1",
        "otelparola1",
        "resepsiyon1",
        "123456qwerty",
        "asdasd123456",
    }
)


@lru_cache(maxsize=1)
def _hasher() -> PasswordHasher:
    """Ayarlardan yapilandirilmis (onbellekli) Argon2 hasher."""
    from app.core.config import get_settings

    security = get_settings().security
    return PasswordHasher(
        time_cost=security.argon2_time_cost,
        memory_cost=security.argon2_memory_cost,
        parallelism=security.argon2_parallelism,
        hash_len=32,
        salt_len=16,
    )


def reset_hasher_cache() -> None:
    """Ayarlar degistiginde hasher'i yeniden olusturur (testler icin)."""
    _hasher.cache_clear()


def normalize_password(password: str) -> str:
    """Parolayi Unicode NFKC ile normallestirir.

    Turkce karakterler farkli kod noktalari ile yazilabilir; normallestirme
    olmadan ayni gorunen iki parola farkli hash uretir ve kullanici
    "dogru parolayi girdigi halde" giris yapamaz.
    """
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    """Parolayi Argon2id ile hash'ler.

    Dogrulama :func:`verify_password` ile yapilir; hash her cagrida farkli
    olur (rastgele tuz), bu yuzden hash'ler dogrudan karsilastirilamaz.
    """
    if not password:
        raise ValidationError("Parola bos olamaz.", field="password")
    return _hasher().hash(normalize_password(password))


def verify_password(password: str, password_hash: str) -> bool:
    """Parolayi hash ile karsilastirir.

    Hicbir kosulda istisna sizdirmaz; gecersiz/bozuk hash de ``False`` doner.
    Boylece cagiran taraf "kullanici yok" ile "parola yanlis" arasindaki farki
    disari sizdirmadan tek bir mesaj gosterebilir.
    """
    if not password or not password_hash:
        return False
    try:
        return _hasher().verify(password_hash, normalize_password(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    """Hash, guncel parametrelerin altinda mi uretilmis?

    Ayarlardaki maliyet parametreleri yukseltildiginde, kullanici bir sonraki
    basarili girisinde parolasi sessizce yeni parametrelerle yeniden
    hash'lenmelidir.
    """
    if not password_hash:
        return True
    try:
        return _hasher().check_needs_rehash(password_hash)
    except Exception:
        return True


def validate_password_strength(
    password: str,
    *,
    min_length: int | None = None,
    username: str | None = None,
) -> None:
    """Parola politikasini uygular; ihlal varsa Turkce aciklamali hata firlatir.

    Politika:

    * En az ``min_length`` karakter (varsayilan ayarlardan gelir)
    * En az bir harf ve bir rakam
    * Sik kullanilan parolalar listesinde olmamali
    * Kullanici adini icermemeli
    * Tek bir karakterin tekrarindan olusmamali
    """
    from app.core.config import get_settings

    if min_length is None:
        min_length = get_settings().security.password_min_length

    normalized = normalize_password(password)

    if len(normalized) < min_length:
        raise ValidationError(f"Parola en az {min_length} karakter olmalidir.", field="password")
    if len(normalized) > 128:
        raise ValidationError("Parola en fazla 128 karakter olabilir.", field="password")
    if not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", normalized):
        raise ValidationError("Parola en az bir harf icermelidir.", field="password")
    if not re.search(r"\d", normalized):
        raise ValidationError("Parola en az bir rakam icermelidir.", field="password")
    if normalized.lower() in COMMON_PASSWORDS:
        raise ValidationError(
            "Bu parola cok yaygin kullaniliyor; daha ozgun bir parola secin.",
            field="password",
        )
    if username and len(username) >= 3 and username.lower() in normalized.lower():
        raise ValidationError("Parola kullanici adinizi icermemelidir.", field="password")
    if len(set(normalized)) < 4:
        raise ValidationError("Parola cok az farkli karakter iceriyor.", field="password")


def generate_password(length: int = 16) -> str:
    """Kriptografik olarak guvenli rastgele parola uretir.

    Yeni kullanici olusturmada ve parola sifirlamada kullanilir. Uretilen
    parola politikayi her zaman gecer.
    """
    if length < 12:
        raise ValueError("Uretilen parola en az 12 karakter olmalidir.")
    # Karisikliga yol acan karakterler (O/0, l/1/I) disarida birakilir.
    alphabet = (
        "".join(c for c in string.ascii_letters if c not in "lIO")
        + "".join(c for c in string.digits if c not in "01")
        + "!@#$%^&*-_=+?"
    )
    while True:
        candidate = "".join(_stdlib_secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isdigit() for c in candidate)
            and any(c.isalpha() for c in candidate)
            and candidate.lower() not in COMMON_PASSWORDS
        ):
            return candidate


def generate_token(length: int = 48) -> str:
    """Oturum jetonu gibi kullanimlar icin URL-guvenli rastgele dizge."""
    return _stdlib_secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """Oturum jetonunun veritabaninda saklanacak SHA-256 ozeti.

    Jetonun kendisi saklanmaz; veritabani sizsa bile aktif oturumlar ele
    gecirilemez. Argon2 yerine SHA-256 kullanilir cunku jeton zaten yuksek
    entropili rastgele bir degerdir ve sozluk saldirisina acik degildir;
    ayrica her istekte dogrulanacagi icin hizli olmalidir.
    """
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(left: str, right: str) -> bool:
    """Zamanlama saldirilarina karsi sabit sureli dizge karsilastirmasi."""
    return _stdlib_secrets.compare_digest(left, right)


__all__ = [
    "COMMON_PASSWORDS",
    "constant_time_compare",
    "generate_password",
    "generate_token",
    "hash_password",
    "hash_token",
    "needs_rehash",
    "normalize_password",
    "reset_hasher_cache",
    "validate_password_strength",
    "verify_password",
]
