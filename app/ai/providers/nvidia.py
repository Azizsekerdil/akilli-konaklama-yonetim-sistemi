"""NVIDIA NIM (build.nvidia.com) adaptoru.

Uc nokta OpenAI uyumludur (``https://integrate.api.nvidia.com/v1``) ve
``Authorization: Bearer <anahtar>`` bekler.

Anahtar yonetimi
----------------
Anahtar **koda gomulmez, veritabanina yazilmaz ve loglanmaz**. Cozunme sirasi
:func:`app.core.secret_store.get_secret` tarafindan belirlenir: once Windows
Credential Manager (keyring), sonra yalnizca gelistirme icin ``.env``.

Cozumleme **tembeldir**: kayit (registry) uygulama acilisinda tum saglayicilari
kurar; anahtar yoksa yapicinin patlamasi, NVIDIA hic kullanilmayacak olsa bile
tum yapay zeka katmanini calismaz hale getirirdi. Bunun yerine anahtar ilk
istekte cozulur ve yoksa Turkce cozum onerisiyle
:class:`~app.core.exceptions.AIAuthenticationError` firlatilir.
:meth:`NvidiaProvider.health_check` bu hatayi yakalayip ``ok=False`` dondugu
icin Ayarlar ekrani yine de acilabilir.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.ai.errors import REMEDY_API_KEY
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.core.config import NvidiaSettings
from app.core.exceptions import AIAuthenticationError
from app.core.secret_store import get_secret
from app.domain.enums import AIProviderType

#: keyring'de aranan girdi adi (deger degil, yalnizca ad).
NVIDIA_KEYRING_ENTRY: str = "nvidia_api_key"


class NvidiaProvider(OpenAICompatibleProvider):
    """NVIDIA NIM adaptoru."""

    name: ClassVar[str] = "nvidia"
    is_local: ClassVar[bool] = False
    provider_type: ClassVar[AIProviderType] = AIProviderType.NVIDIA

    DEFAULT_BASE_URL: ClassVar[str] = "https://integrate.api.nvidia.com/v1"

    def __init__(self, *, settings: NvidiaSettings | None = None, **kwargs: Any) -> None:
        resolved = settings if settings is not None else NvidiaSettings()
        super().__init__(settings=resolved, **kwargs)
        if not self.base_url:
            self.base_url = self.DEFAULT_BASE_URL

    def _resolve_api_key(self) -> str:
        """Anahtari cozer; bulunamazsa Turkce oneriyle hata firlatir."""
        if self._api_key:
            return self._api_key

        key = get_secret(NVIDIA_KEYRING_ENTRY)
        if not key and self.settings is not None:
            key = self.settings.resolve_api_key()

        if not key:
            raise AIAuthenticationError(
                "NVIDIA API anahtarı tanımlı değil.",
                provider=self.name,
                remedy=REMEDY_API_KEY,
                # Anahtarin KENDISI degil, yalnizca arandigi ad kaydedilir.
                detail=f"'{NVIDIA_KEYRING_ENTRY}' keyring'de de ortamda da bulunamadi",
                context={"keyring_entry": NVIDIA_KEYRING_ENTRY},
            )
        self._api_key = key
        return key

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._resolve_api_key()}",
        }
        headers.update(self.extra_headers)
        return headers

    @property
    def has_api_key(self) -> bool:
        """Anahtar var mi? Ayarlar ekraninin durum gostergesi icin."""
        try:
            return bool(self._resolve_api_key())
        except AIAuthenticationError:
            return False


__all__ = ["NVIDIA_KEYRING_ENTRY", "NvidiaProvider"]
