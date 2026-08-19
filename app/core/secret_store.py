"""Guvenli sir (API anahtari, parola) yonetimi.

Guvenlik politikasi
-------------------
API anahtarlari **asla** veritabaninda duz metin olarak saklanmaz. Cozunme
sirasi:

1. **Windows Credential Manager (keyring)** - tercih edilen yontem. Anahtar
   isletim sisteminin sifreli deposunda tutulur.
2. **``.env`` dosyasi / ortam degiskeni** - yalnizca gelistirme icindir.
   ``.env`` ``.gitignore`` icinde tanimlidir.
3. Bulunamazsa ``None`` doner; cagiran taraf anlamli bir hata uretir.

Veritabani yalnizca "bu saglayicinin anahtari nerede saklaniyor" bilgisini
(:class:`SecretRef`) tutar, degeri tutmaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.exceptions import ConfigurationError

#: keyring'de kullanilacak servis adi.
KEYRING_SERVICE: Final[str] = "AkilliKonaklamaYonetimSistemi"

#: Loglarda ve arayuzde maskelenmesi gereken anahtar isimleri.
SECRET_KEY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "authorization",
        "password",
        "passwd",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "private_key",
        "client_secret",
        "x-api-key",
        "session_token",
        "credential",
        "credentials",
    }
)


class SecretBackend(str, Enum):
    """Bir sirrin nerede saklandigini belirtir."""

    KEYRING = "keyring"
    """Windows Credential Manager - uretim icin onerilen."""

    ENV = "env"
    """Ortam degiskeni veya .env dosyasi - yalnizca gelistirme."""

    NONE = "none"
    """Anahtar gerekmiyor (or. LM Studio yerel sunucusu)."""


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Bir sirra isaret eden referans. **Degerin kendisini icermez.**"""

    name: str
    """Mantiksal ad, or. ``nvidia_api_key``."""

    backend: SecretBackend = SecretBackend.KEYRING

    @property
    def env_var(self) -> str:
        """Karsilik gelen ortam degiskeni adi, or. ``HOTEL_NVIDIA_API_KEY``."""
        return f"HOTEL_{self.name.upper()}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"SecretRef(name={self.name!r}, backend={self.backend.value!r})"


def _keyring_module():  # pragma: no cover - ortama bagli
    """keyring modulunu tembel yukler.

    keyring bazi kisitli ortamlarda (or. CI, headless) kullanilamaz.
    Import hatasini yutup ``None`` doneriz ki uygulama cokmesin.
    """
    try:
        import keyring

        return keyring
    except Exception:
        return None


def is_keyring_available() -> bool:
    """Sistemde calisan bir keyring arka ucu var mi?"""
    keyring = _keyring_module()
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:  # pragma: no cover
        return False
    name = type(backend).__name__
    # "fail" arka ucu keyring'in "hicbir sey bulamadim" gostergesidir.
    return "fail" not in name.lower()


def get_secret(name: str, *, allow_env: bool = True) -> str | None:
    """Sirri cozer. Bulunamazsa ``None`` doner.

    Parameters
    ----------
    name:
        Mantiksal sir adi, or. ``nvidia_api_key``.
    allow_env:
        ``False`` ise yalnizca keyring'e bakilir; .env yok sayilir. Uretim
        ortaminda .env kullanimini yasaklamak icin kullanilir.
    """
    keyring = _keyring_module()
    if keyring is not None:
        try:
            value = keyring.get_password(KEYRING_SERVICE, name)
        except Exception:  # pragma: no cover
            value = None
        if value:
            return value

    if allow_env:
        env_value = os.environ.get(f"HOTEL_{name.upper()}") or os.environ.get(name.upper())
        if env_value:
            return env_value

    return None


def require_secret(name: str, *, allow_env: bool = True, hint: str | None = None) -> str:
    """:func:`get_secret` gibi ama bulunamazsa anlamli bir hata firlatir."""
    value = get_secret(name, allow_env=allow_env)
    if value:
        return value
    remedy = hint or (
        f"Anahtari kaydetmek icin: Ayarlar > Yapay Zeka ekranini kullanin veya "
        f"'.env' dosyasina HOTEL_{name.upper()}=... satirini ekleyin."
    )
    raise ConfigurationError(
        f"'{name}' anahtari bulunamadi.",
        detail=f"Secret '{name}' neither in keyring nor environment.",
        code="secret_not_found",
        context={"secret_name": name, "remedy": remedy},
    )


def set_secret(name: str, value: str) -> SecretBackend:
    """Sirri mumkunse keyring'e yazar.

    Returns
    -------
    SecretBackend
        Degerin gercekte nereye yazildigi. keyring kullanilamiyorsa
        :attr:`SecretBackend.ENV` doner ve deger **yazilmaz** - cagiran
        tarafin kullaniciyi .env'e yonlendirmesi gerekir.
    """
    if not value or not value.strip():
        raise ValueError("Bos deger sir olarak kaydedilemez.")

    keyring = _keyring_module()
    if keyring is not None:
        try:
            keyring.set_password(KEYRING_SERVICE, name, value)
            return SecretBackend.KEYRING
        except Exception as exc:  # pragma: no cover - ortama bagli
            # Sessizce yutmak, kullanicinin "anahtarim kaydedildi" sanmasina
            # yol acar. Neden basarisiz oldugunu kaydediyoruz - ancak
            # 'name' loglanir, 'value' ASLA loglanmaz.
            #
            # Log modulu burada tembel yuklenir: app.core.log zaten bu modulu
            # (looks_like_secret_key icin) import eder; ust seviyede import
            # etmek dairesel bagimlilik olustururdu.
            from app.core.log import get_logger

            get_logger(__name__).warning(
                "keyring_yazma_basarisiz",
                secret_name=name,
                error=str(exc),
                cozum="Anahtari '.env' dosyasina elle ekleyin.",
            )
    return SecretBackend.ENV


def delete_secret(name: str) -> bool:
    """Sirri keyring'den siler. Silinen bir sey varsa ``True`` doner."""
    keyring = _keyring_module()
    if keyring is None:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
        return True
    except Exception:
        return False


def mask_secret(value: str | None, *, visible: int = 4) -> str:
    """Sirri gosterime uygun sekilde maskeler.

    >>> mask_secret("nvapi-1234567890abcdef")
    'nvap...cdef'
    >>> mask_secret("kisa")
    '********'
    >>> mask_secret(None)
    '(tanimsiz)'
    """
    if value is None:
        return "(tanimsiz)"
    if not value:
        return "(bos)"
    if len(value) <= visible * 2:
        return "*" * 8
    return f"{value[:visible]}...{value[-visible:]}"


def looks_like_secret_key(key: str) -> bool:
    """Bir sozluk anahtarinin hassas veri tasiyip tasimadigini tahmin eder.

    Loglama ve arayuz maskelemesi tarafindan kullanilir.

    >>> looks_like_secret_key("HOTEL_NVIDIA_API_KEY")
    True
    >>> looks_like_secret_key("room_number")
    False
    """
    normalized = key.lower().replace("-", "_")
    if normalized in SECRET_KEY_NAMES:
        return True
    return any(
        marker in normalized
        for marker in ("api_key", "apikey", "password", "secret", "token", "credential")
    )


__all__ = [
    "KEYRING_SERVICE",
    "SECRET_KEY_NAMES",
    "SecretBackend",
    "SecretRef",
    "delete_secret",
    "get_secret",
    "is_keyring_available",
    "looks_like_secret_key",
    "mask_secret",
    "require_secret",
    "set_secret",
]
