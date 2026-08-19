"""Ozel SQLAlchemy sutun tipleri.

En onemlisi :class:`EncryptedString`: kimlik/pasaport numarasi gibi ozel
nitelikli kisisel verilerin veritabaninda **duz metin olarak durmamasini**
saglar. Veritabani dosyasi kopyalansa bile bu alanlar anahtar olmadan
okunamaz.

Anahtar yonetimi
----------------
Sifreleme anahtari :mod:`app.core.secret_store` uzerinden Windows Credential
Manager'da tutulur. Yoksa ilk kullanimda uretilir ve keyring'e yazilir.
Keyring hic kullanilamiyorsa (or. CI) ``HOTEL_FIELD_ENCRYPTION_KEY`` ortam
degiskenine bakilir.

**Fail-closed davranis.** Modul hicbir kosulda "idare eden" bir yedek deger
kullanmaz:

* Anahtar ne keyring'e ne ortama yazilabiliyorsa :func:`_get_fernet`
  :class:`~app.core.exceptions.ConfigurationError` firlatir - aksi halde her
  acilista yeni anahtar uretilir ve onceki veri sessizce okunamaz hale
  gelirdi.
* Cozulemeyen bir kayit icin :func:`decrypt_value` bos dizge **dondurmez**,
  :class:`~app.core.exceptions.DecryptionError` firlatir - bos gorunen alan
  uzerine yazilirsa veri kalici olarak kaybolur.
* :func:`blind_index` icin kaynak koda gomulu sabit bir anahtar **yoktur**;
  anahtar yoksa hata verir (yalnizca ``HOTEL_APP_ENV=testing`` altinda sabit
  bir test anahtari kullanilir).

.. warning::
   Anahtar kaybedilirse sifreli alanlar **geri getirilemez**. Yedekleme
   yordami (``backup.ps1``) anahtari yedeklemez; yonetici anahtari ayrica
   guvenli bir yerde saklamalidir. Bkz. ``docs/SECURITY_REVIEW.md``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import DateTime, String, TypeDecorator
from sqlalchemy.engine import Dialect

from app.core.log import get_logger
from app.core.secret_store import (
    SecretBackend,
    get_secret,
    is_keyring_available,
    set_secret,
)

log = get_logger(__name__)

#: keyring'de sifreleme anahtarinin saklandigi ad.
FIELD_KEY_NAME = "field_encryption_key"

#: Sifreli degerlerin basina eklenen isaret - cift sifrelemeyi onler.
_PREFIX = "enc:v1:"


def _key_material() -> str | None:
    """Kalici alan sifreleme anahtarini dondurur; yoksa ``None``.

    :func:`app.core.secret_store.get_secret` once keyring'e, sonra
    ``HOTEL_FIELD_ENCRYPTION_KEY`` ortam degiskenine bakar.
    """
    return get_secret(FIELD_KEY_NAME)


def encryption_key_status() -> tuple[bool, str]:
    """Anahtarin kalici olarak saklanabilir olup olmadigini bildirir.

    Ilk calistirma sihirbazi ve ``hotel doctor`` bunu kullanir: kullanici
    veri girmeden **once** uyarilir, sifreleme yapildiktan sonra degil.

    Returns
    -------
    tuple[bool, str]
        (uygun_mu, insan-okunur aciklama).
    """
    if _key_material():
        return True, "Alan sifreleme anahtari mevcut ve kalici olarak saklaniyor."
    if is_keyring_available():
        return True, "Anahtar deposu (keyring) kullanilabilir; anahtar ilk kullanimda uretilecek."
    return False, (
        "Alan sifreleme anahtari kalici olarak saklanamiyor: keyring arka ucu yok ve "
        "HOTEL_FIELD_ENCRYPTION_KEY tanimli degil. Kimlik/pasaport alanlari sifrelenirse "
        "bir sonraki acilista okunamaz. Once anahtari tanimlayin."
    )


@lru_cache(maxsize=1)
def _get_fernet() -> Any:
    """Fernet ornegini (tembel, onbellekli) dondurur.

    Raises
    ------
    ConfigurationError
        Anahtar yoksa **ve** uretilen yeni anahtar kalici olarak
        saklanamiyorsa.

    Neden hata firlatiyor? (guvenlik incelemesi bulgusu HTL-H3)
    -----------------------------------------------------------
    Onceki surumde keyring arka ucu yoksa :func:`set_secret`
    :attr:`SecretBackend.ENV` dondurur ve degeri **hicbir yere yazmazdi**.
    Sonuc: her acilista yeni bir anahtar uretilir, bir onceki acilista
    sifrelenen kimlik ve pasaport verisi bir daha cozulemezdi. Bu sessiz
    **veri kaybi**dir - hem de tam olarak KVKK acisindan korunmasi gereken
    alanlarda. Artik uygulama bu durumda **gurultulu sekilde durur**: yeni
    anahtar uretilmez, mevcut veri riske atilmaz.
    """
    from cryptography.fernet import Fernet

    from app.core.exceptions import ConfigurationError

    key = _key_material()
    if not key:
        candidate = Fernet.generate_key().decode("ascii")
        backend = set_secret(FIELD_KEY_NAME, candidate)
        if backend is not SecretBackend.KEYRING:
            raise ConfigurationError(
                "Alan sifreleme anahtari kalici olarak saklanamiyor.",
                detail=(
                    "Isletim sisteminin anahtar deposu (Windows Credential Manager / "
                    "keyring) kullanilamiyor ve HOTEL_FIELD_ENCRYPTION_KEY ortam "
                    "degiskeni tanimli degil. Bu durumda her acilista YENI bir anahtar "
                    "uretilir ve daha once sifrelenen kimlik/pasaport verisi bir daha "
                    "cozulemez. Veri kaybini onlemek icin uygulama durduruldu."
                ),
                code="field_encryption_key_not_persistable",
                context={
                    "remedy": (
                        "Ya keyring arka ucunu kullanilabilir hale getirin, ya da kalici "
                        "bir anahtar uretip HOTEL_FIELD_ENCRYPTION_KEY olarak tanimlayin: "
                        'python -c "from cryptography.fernet import Fernet; '
                        'print(Fernet.generate_key().decode())"'
                    ),
                    "backend": backend.value,
                },
            )
        key = candidate
        log.warning(
            "alan_sifreleme_anahtari_uretildi",
            backend=backend.value,
            uyari=(
                "Yeni bir alan sifreleme anahtari uretildi. Bu anahtari guvenli bir yerde "
                "yedekleyin; kaybedilirse sifreli kisisel veriler geri getirilemez."
            ),
        )
    return Fernet(key.encode("ascii") if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    """Metni sifreler ve isaretli base64 dizgesi dondurur."""
    if not plaintext:
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return _PREFIX + token.decode("ascii")


def decrypt_value(ciphertext: str) -> str:
    """Sifreli metni cozer.

    Isaretsiz (eski/duz metin) degerler oldugu gibi dondurulur; boylece
    sifreleme sonradan devreye alindiginda mevcut kayitlar bozulmaz.

    Raises
    ------
    DecryptionError
        Isaretli bir deger **cozulemezse**.

    Neden bos dizge dondurmuyor? (guvenlik incelemesi bulgusu HTL-H3)
    -----------------------------------------------------------------
    Onceki surumde gecersiz jeton yakalanip ``""`` donduruluyordu. Sonuc:
    yanlis anahtarla acilan bir kurulumda kimlik ve pasaport alanlari
    arayuzde **bos** gorunur, kullanici bunu "veri girilmemis" sanip uzerine
    yazar ve sifreli veri kalici olarak kaybolurdu - geriye yalnizca bir log
    satiri kalirdi. Artik hata yukari tasinir: cagiran katman kullaniciya
    "anahtar uyusmuyor" der, veri silinmez.
    """
    if not ciphertext or not ciphertext.startswith(_PREFIX):
        return ciphertext
    from cryptography.fernet import InvalidToken

    from app.core.exceptions import DecryptionError

    try:
        return _get_fernet().decrypt(ciphertext[len(_PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        log.error(
            "alan_sifre_cozme_basarisiz", detail="Anahtar degismis veya veri bozulmus olabilir."
        )
        raise DecryptionError(
            "Sifreli alan cozulemedi.",
            detail=(
                "Kayit baska bir alan sifreleme anahtariyla sifrelenmis ya da veri "
                "bozulmus. Degerin UZERINE YAZMAYIN: dogru anahtar geri yuklendiginde "
                "veri okunabilir."
            ),
            code="field_decryption_failed",
            context={
                "remedy": (
                    "Dogru HOTEL_FIELD_ENCRYPTION_KEY degerini geri yukleyin veya "
                    "anahtarin bulundugu keyring profilinde calistirin."
                )
            },
        ) from exc


class TZDateTime(TypeDecorator[datetime]):
    """Her zaman **zaman dilimi bilincli UTC** dondüren tarih-saat sutunu.

    Sorun
    -----
    SQLite'ta ``DATETIME`` tipi zaman dilimi bilgisi tasimaz. ``DateTime(
    timezone=True)`` tanimlansa bile veritabanindan **naive** bir ``datetime``
    doner. Bu deger ``datetime.now(UTC)`` ile karsilastirildiginda::

        TypeError: can't compare offset-naive and offset-aware datetimes

    hatasi alinir. Hata yalnizca calisma aninda ve genellikle oturum suresi
    kontrolu gibi kritik yollarda ortaya cikar.

    Cozum
    -----
    * **Yazarken**: naive deger UTC kabul edilir, aware deger UTC'ye cevrilir.
    * **Okurken**: naive deger UTC olarak isaretlenir.

    Boylece uygulama katmani her zaman aware UTC ``datetime`` gorur;
    PostgreSQL'e gecildiginde de davranis ayni kalir.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EncryptedString(TypeDecorator[str]):
    """Veritabanina sifreli, uygulamaya duz metin donen dize sutunu.

    Kullanim::

        identity_number: Mapped[str | None] = mapped_column(
            EncryptedString(512), default=None
        )

    ``length`` **saklama** uzunlugudur, duz metin uzunlugu degil. Fernet
    ciktisi base64'tur ve duz metinden yaklasik 2.5 kat uzundur; 40 karakterlik
    bir kimlik numarasi icin 512 fazlasiyla yeterlidir.

    .. note::
       Uzunlugu ``__init__`` icinde carpmiyoruz (or. ``length * 3``). Boyle
       yapilsaydi Alembic'in ``--autogenerate`` ciktisi
       ``EncryptedString(length=765)`` uretir, o da yeniden yorumlandiginda
       2295'e cikardi; her goc uretiminde sutun genisleyerek "surekli
       degisiyor" gorunurdu. Uzunlugun sabit kalmasi round-trip guvenligi
       saglar.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 512, **kwargs: Any) -> None:
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return encrypt_value(str(value))

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return decrypt_value(value)


#: Yalnizca ``HOTEL_APP_ENV=testing`` altinda kullanilan sabit test anahtari.
#: Uretim veya gelistirme ortaminda **asla** devreye girmez; gercek veriyle
#: uretilmis bir kor indeks bu degerle hesaplanamaz.
_TESTING_ONLY_BLIND_INDEX_KEY: str = "testing-only-blind-index-key-not-for-real-data"


def _blind_index_key_material() -> str:
    """Kor indeks icin HMAC anahtar materyalini dondurur (fail-closed).

    Raises
    ------
    ConfigurationError
        Anahtar bulunamazsa ve ortam ``testing`` degilse.
    """
    key = _key_material()
    if key:
        return key

    from app.core.config import get_settings
    from app.core.exceptions import ConfigurationError

    if get_settings().is_testing:
        return _TESTING_ONLY_BLIND_INDEX_KEY

    raise ConfigurationError(
        "Kor indeks icin alan sifreleme anahtari bulunamadi.",
        detail=(
            "Kimlik numarasi uzerinde arama yapilabilmesi icin anahtarli bir ozet "
            "(HMAC) gerekir. Anahtar yoksa ozet ya hic uretilemez ya da herkesce "
            "bilinen bir sabitle uretilir; ikincisi kimlik numaralarinin cevrimdisi "
            "taranarak bulunmasina izin verir. Bu yuzden islem durduruldu."
        ),
        code="blind_index_key_missing",
        context={
            "remedy": (
                "Anahtar deposunu (keyring) kullanilabilir hale getirin veya kalici bir "
                "anahtar uretip HOTEL_FIELD_ENCRYPTION_KEY olarak tanimlayin."
            )
        },
    )


def blind_index(value: str | None, *, salt: str = "hotel-blind-index") -> str | None:
    """Sifreli alanda **esitlik aramasi** yapabilmek icin deterministik ozet.

    Sifreli sutunda ``WHERE identity_number = ?`` calismaz, cunku her
    sifreleme farkli cikti uretir. Cozum, ayni degerin her zaman ayni ozeti
    uretmesini saglayan bir "kor indeks" sutunu tutmaktir.

    HMAC-SHA256 kullanilir; anahtar olarak alan sifreleme anahtari alinir.
    Boylece ozet, anahtari bilmeyen biri tarafindan sozluk saldirisiyla
    (or. tum olasi TCKN'leri deneyerek) geri cozulemez.

    .. important::
       **Sabit bir yedek anahtar YOKTUR** (guvenlik incelemesi bulgusu
       HTL-H2). Onceki surumde anahtar bulunamazsa kaynak koda gomulu bir
       sabit kullanilirdi. Kaynak kod yayimlandigi anda o sabit herkesce
       bilinir hale gelir; TCKN uzayi ~10^10 ve ucuz bir sagilama filtresi
       ile daraldigi icin veritabani dosyasini eline gecirmis biri **sifreyi
       hic kirmadan** kimlik numaralarini cevrimdisi tarayarak bulabilirdi.
       Bu yuzden anahtar yoksa fonksiyon **hata firlatir** (fail-closed);
       yalnizca ``HOTEL_APP_ENV=testing`` altinda sabit bir test anahtari
       kullanilir ve o anahtar gercek veri icin asla devreye girmez.

    Raises
    ------
    ConfigurationError
        Anahtar materyali yoksa ve ortam ``testing`` degilse.

    >>> a = blind_index("12345678901")
    >>> b = blind_index("12345678901")
    >>> a == b
    True
    >>> blind_index("12345678901") == blind_index("10987654321")
    False
    """
    if not value:
        return None
    key_material = _blind_index_key_material()
    digest = hmac.new(
        f"{key_material}:{salt}".encode(),
        value.strip().encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:44]


def mask_identity(value: str | None, *, visible: int = 3) -> str:
    """Kimlik numarasini arayuzde gosterim icin maskeler.

    >>> mask_identity("12345678901")
    '123*****901'
    >>> mask_identity("12345")
    '*****'
    >>> mask_identity(None)
    '-'
    """
    if not value:
        return "-"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * (len(value) - visible * 2)}{value[-visible:]}"


__all__ = [
    "FIELD_KEY_NAME",
    "EncryptedString",
    "TZDateTime",
    "blind_index",
    "decrypt_value",
    "encrypt_value",
    "encryption_key_status",
    "mask_identity",
]
