"""Saglayici hatalarinin uygulama hatalarina eslenmesi.

Bu modul **yeni hata sinifi tanimlamaz**; :mod:`app.core.exceptions` icindeki
``AI*`` hiyerarsisini kullanir. Buradaki tek is, HTTP durum kodlarini ve
aktarim (baglanti/zaman asimi) hatalarini dogru hata tipine ve **Turkce cozum
onerisine** (``remedy``) cevirmektir.

Neden ``remedy`` ayri bir alan?
-------------------------------
"Yapay zeka servisine ulasilamadi" mesaji resepsiyon gorevlisine hicbir sey
anlatmaz. Onun bilmesi gereken sey *ne yapacagidir*: LM Studio'yu baslatmak,
anahtari girmek, zaman asimini artirmak. Bu yuzden her hataya somut bir adim
eklenir ve arayuz ``user_message`` ile ``remedy``'yi birlikte gosterir.

Yeniden deneme politikasi
-------------------------
Yalnizca **429** (hiz siniri) ve **5xx** (sunucu hatasi) yeniden denenir.
400/401/404 kalici hatalardir: ayni istek tekrar gonderilirse ayni sonucu verir,
yalnizca kullanicinin bekleme suresini uzatir.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from app.core.exceptions import (
    AIAuthenticationError,
    AIConnectionError,
    AIModelNotFoundError,
    AIProviderError,
    AIQuotaError,
    AIResponseFormatError,
    AITimeoutError,
)

# --------------------------------------------------------------------------
#  Turkce cozum onerileri
# --------------------------------------------------------------------------
REMEDY_LOCAL_CONNECTION: Final[str] = (
    "LM Studio çalışıyor mu? Sunucu sekmesinden Start Server deyin ve adresi "
    "Ayarlar > Yapay Zeka ekranından doğrulayın."
)
REMEDY_REMOTE_CONNECTION: Final[str] = (
    "İnternet bağlantınızı ve sunucu adresini kontrol edin. Kurum güvenlik duvarı "
    "erişimi engelliyor olabilir."
)
REMEDY_TIMEOUT: Final[str] = (
    "Model süresinde yanıt vermedi. Ayarlar > Yapay Zeka ekranından zaman aşımı "
    "süresini artırın veya daha küçük bir model seçin."
)
REMEDY_API_KEY: Final[str] = (
    "Ayarlar > Yapay Zeka ekranından anahtarınızı girin. Anahtar işletim sisteminin "
    "güvenli deposunda saklanır, veritabanına yazılmaz."
)
REMEDY_LOCAL_AUTH: Final[str] = (
    "Yerel sunucu isteği reddetti. LM Studio sunucu ayarlarında bir erişim anahtarı "
    "tanımlıysa aynısını Ayarlar > Yapay Zeka ekranına girin."
)
REMEDY_MODEL_NOT_FOUND: Final[str] = (
    "Model sunucuda yüklü değil. Ayarlar > Yapay Zeka ekranından listeden bir model "
    "seçin; LM Studio kullanıyorsanız modeli önce yükleyin."
)
REMEDY_QUOTA: Final[str] = (
    "Kota veya hız sınırı aşıldı. Birkaç dakika bekleyin, faturalandırmanızı kontrol "
    "edin ya da yerel (ücretsiz) bir modele geçin."
)
REMEDY_SERVER: Final[str] = (
    "Sağlayıcı geçici olarak hata veriyor. Birkaç dakika sonra tekrar deneyin; "
    "sorun sürerse yedek sağlayıcıya geçin."
)
REMEDY_BAD_REQUEST: Final[str] = (
    "İstek sağlayıcı tarafından reddedildi. Model adını ve Ayarlar > Yapay Zeka "
    "ekranındaki değerleri kontrol edin."
)
REMEDY_JSON_FORMAT: Final[str] = (
    "Model beklenen JSON biçimini üretemedi. Daha yetenekli bir model seçin veya "
    "isteği sadeleştirin."
)
REMEDY_REASONING_BUDGET: Final[str] = (
    "Düşünme modeli, yanıt üretmeden jeton sınırına ulaştı. Ayarlar > Yapay Zeka "
    "ekranından azami jeton (max_tokens) değerini artırın; düşünme modelleri için "
    "en az 1024 önerilir."
)
REMEDY_NO_EMBEDDING: Final[str] = (
    "Bu sağlayıcı gömme (embedding) desteklemiyor. Gömme için LM Studio üzerindeki "
    "text-embedding-nomic-embed-text-v1.5 modelini kullanın."
)

#: Yeniden denenebilir HTTP durum kodlari icin esik.
_SERVER_ERROR_FLOOR: Final[int] = 500
_TOO_MANY_REQUESTS: Final[int] = 429
_TIMEOUT_STATUSES: Final[frozenset[int]] = frozenset({408, 504})
_AUTH_STATUSES: Final[frozenset[int]] = frozenset({401, 403})

#: Yanit govdesinden loga alinacak azami karakter. Ham govde misafir verisi
#: icerebilecegi icin kirpilir ve yalnizca ``detail`` alanina yazilir.
_DETAIL_LIMIT: Final[int] = 500


def is_retryable_status(status_code: int) -> bool:
    """429 ve 5xx yeniden denenir; digerleri denenmez.

    408/504 (zaman asimi) da 5xx/istemci ayrimindan bagimsiz olarak *tek sefer*
    daha denenmez: model zaten yavas calisiyordur, ikinci deneme kullaniciyi
    yalnizca iki kat bekletir.
    """
    if status_code in _TIMEOUT_STATUSES:
        return False
    return status_code == _TOO_MANY_REQUESTS or status_code >= _SERVER_ERROR_FLOOR


def _trim(detail: str | None) -> str | None:
    if not detail:
        return None
    text = detail.strip()
    return text[:_DETAIL_LIMIT] if len(text) > _DETAIL_LIMIT else text


def connection_remedy(*, is_local: bool) -> str:
    """Baglanti hatasi icin dogru oneriyi secer."""
    return REMEDY_LOCAL_CONNECTION if is_local else REMEDY_REMOTE_CONNECTION


def map_status_code(
    status_code: int,
    *,
    provider: str,
    is_local: bool = False,
    detail: str | None = None,
    model: str | None = None,
    context: dict[str, Any] | None = None,
) -> AIProviderError:
    """HTTP durum kodunu uygun ``AI*`` hatasina cevirir.

    Eslesme:

    ==========  =========================
    Durum kodu  Hata
    ==========  =========================
    401, 403    :class:`AIAuthenticationError`
    404         :class:`AIModelNotFoundError`
    408, 504    :class:`AITimeoutError`
    429         :class:`AIQuotaError`
    5xx         :class:`AIProviderError`
    diger 4xx   :class:`AIProviderError`
    ==========  =========================
    """
    base_context: dict[str, Any] = {"status_code": status_code}
    if model:
        base_context["model"] = model
    if context:
        base_context.update(context)

    trimmed = _trim(detail)
    shared: dict[str, Any] = {
        "provider": provider,
        "detail": trimmed,
        "context": base_context,
    }

    if status_code in _AUTH_STATUSES:
        return AIAuthenticationError(
            remedy=REMEDY_LOCAL_AUTH if is_local else REMEDY_API_KEY,
            **shared,
        )
    if status_code == 404:
        return AIModelNotFoundError(
            f"'{model}' modeli sağlayıcıda bulunamadı." if model else None,
            remedy=REMEDY_MODEL_NOT_FOUND,
            **shared,
        )
    if status_code in _TIMEOUT_STATUSES:
        return AITimeoutError(remedy=REMEDY_TIMEOUT, **shared)
    if status_code == _TOO_MANY_REQUESTS:
        return AIQuotaError(remedy=REMEDY_QUOTA, **shared)
    if status_code >= _SERVER_ERROR_FLOOR:
        return AIProviderError(
            "Yapay zeka sağlayıcısı geçici bir hata döndürdü.",
            remedy=REMEDY_SERVER,
            **shared,
        )
    return AIProviderError(
        "Yapay zeka isteği sağlayıcı tarafından reddedildi.",
        remedy=REMEDY_BAD_REQUEST,
        **shared,
    )


def map_transport_error(
    exc: Exception,
    *,
    provider: str,
    is_local: bool = False,
    base_url: str = "",
) -> AIProviderError:
    """``httpx`` aktarim hatasini uygun ``AI*`` hatasina cevirir.

    Zaman asimi ve baglanti hatasi ayri tutulur: ilki "model yavas", ikincisi
    "sunucu kapali" demektir ve kullaniciya verilecek oneri tamamen farklidir.
    """
    context: dict[str, Any] = {"base_url": base_url} if base_url else {}
    if isinstance(exc, httpx.TimeoutException):
        return AITimeoutError(
            provider=provider,
            remedy=REMEDY_TIMEOUT,
            detail=f"{type(exc).__name__}: {exc}",
            context=context,
        )
    return AIConnectionError(
        provider=provider,
        remedy=connection_remedy(is_local=is_local),
        detail=f"{type(exc).__name__}: {exc}",
        context=context,
    )


def format_error(error: AIProviderError) -> str:
    """Arayuzde gosterilecek tam metin: mesaj + cozum onerisi."""
    remedy = getattr(error, "remedy", None)
    return f"{error.user_message} {remedy}".strip() if remedy else error.user_message


def empty_reasoning_response_error(
    *,
    provider: str,
    model: str,
    max_tokens: int,
    reasoning_tokens: int,
) -> AIResponseFormatError:
    """Dusunme modelinin bos icerikle donmesi durumunda uretilen hata.

    **Neden hata firlatiyoruz?** ``max_tokens`` dusuk oldugunda (or. 60)
    ``google/gemma-4-12b-qat`` tum butceyi ``reasoning_content`` icinde harcar;
    ``choices[0].message.content`` bos string doner ve ``finish_reason`` degeri
    ``"length"`` olur. Bunu sessizce bos metin olarak dondurmek, arayuzde
    "yapay zeka cevap vermedi" izlenimi yaratir ve kullanici sorunu asla
    cozemez. Bu yuzden acik bir hata + jeton sinirini artirma onerisi uretiriz.
    """
    return AIResponseFormatError(
        "Yapay zeka düşünme aşamasında jeton sınırına ulaştı ve yanıt üretemedi.",
        provider=provider,
        remedy=REMEDY_REASONING_BUDGET,
        detail=(
            f"model={model} finish_reason=length content='' "
            f"max_tokens={max_tokens} reasoning_tokens={reasoning_tokens}"
        ),
        context={
            "model": model,
            "max_tokens": max_tokens,
            "reasoning_tokens": reasoning_tokens,
            "reason": "reasoning_budget_exhausted",
        },
    )


def json_format_error(
    *,
    provider: str,
    detail: str,
    model: str | None = None,
) -> AIResponseFormatError:
    """Model gecerli JSON uretemediginde kullanilan hata."""
    context: dict[str, Any] = {"reason": "invalid_json"}
    if model:
        context["model"] = model
    return AIResponseFormatError(
        provider=provider,
        remedy=REMEDY_JSON_FORMAT,
        detail=_trim(detail),
        context=context,
    )


def unsupported_capability_error(
    *,
    provider: str,
    capability: str,
    remedy: str = REMEDY_NO_EMBEDDING,
) -> AIProviderError:
    """Saglayicinin desteklemedigi bir yetenek istendiginde."""
    return AIProviderError(
        f"Bu sağlayıcı '{capability}' özelliğini desteklemiyor.",
        provider=provider,
        remedy=remedy,
        detail=f"capability={capability} not supported by provider={provider}",
        context={"capability": capability},
    )


__all__ = [
    "REMEDY_API_KEY",
    "REMEDY_BAD_REQUEST",
    "REMEDY_JSON_FORMAT",
    "REMEDY_LOCAL_AUTH",
    "REMEDY_LOCAL_CONNECTION",
    "REMEDY_MODEL_NOT_FOUND",
    "REMEDY_NO_EMBEDDING",
    "REMEDY_QUOTA",
    "REMEDY_REASONING_BUDGET",
    "REMEDY_REMOTE_CONNECTION",
    "REMEDY_SERVER",
    "REMEDY_TIMEOUT",
    "connection_remedy",
    "empty_reasoning_response_error",
    "format_error",
    "is_retryable_status",
    "json_format_error",
    "map_status_code",
    "map_transport_error",
    "unsupported_capability_error",
]
