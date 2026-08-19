"""Uygulama genelinde kullanilan hata tipleri.

Tasarim ilkesi
--------------
Kullaniciya gosterilecek mesaj (``user_message``) ile teknik ayrinti
(``detail``) birbirinden ayrilir. Arayuz yalnizca ``user_message`` gosterir;
teknik ayrinti loga yazilir. Boylece yigin izleri, SQL parcalari veya dosya
yollari son kullaniciya sizmaz (bkz. docs/SECURITY_REVIEW.md - "Guvenli hata
mesajlari").
"""

from __future__ import annotations

from typing import Any


class HotelError(Exception):
    """Tum uygulama hatalarinin atasi.

    Parameters
    ----------
    user_message:
        Son kullaniciya gosterilebilecek, teknik ayrinti icermeyen Turkce mesaj.
    detail:
        Yalnizca loglara yazilacak teknik aciklama.
    code:
        Programatik olarak ayirt etmeye yarayan kisa kod.
    context:
        Loglamaya eklenecek ek alanlar. Hassas veri KOYULMAMALIDIR.
    """

    default_user_message = "Beklenmeyen bir hata olustu."
    default_code = "hotel_error"

    def __init__(
        self,
        user_message: str | None = None,
        *,
        detail: str | None = None,
        code: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.user_message = user_message or self.default_user_message
        self.detail = detail
        self.code = code or self.default_code
        self.context: dict[str, Any] = context or {}
        super().__init__(self.detail or self.user_message)

    def to_dict(self) -> dict[str, Any]:
        """API yanitlarinda kullanilacak guvenli sozluk gosterimi."""
        return {"code": self.code, "message": self.user_message}

    def __repr__(self) -> str:  # pragma: no cover - hata ayiklama kolayligi
        return f"{type(self).__name__}(code={self.code!r}, message={self.user_message!r})"


# --------------------------------------------------------------------------
#  Yapilandirma / altyapi
# --------------------------------------------------------------------------
class ConfigurationError(HotelError):
    """Eksik veya gecersiz yapilandirma."""

    default_user_message = "Uygulama yapilandirmasi eksik veya hatali."
    default_code = "configuration_error"


class DatabaseError(HotelError):
    """Veritabani katmani hatasi."""

    default_user_message = "Veritabani islemi sirasinda bir sorun olustu."
    default_code = "database_error"


class DecryptionError(DatabaseError):
    """Sifreli bir alan cozulemedi.

    Sessizce bos dizge dondurmek yerine bu hata firlatilir: bos gorunen bir
    kimlik alani kullanicinin uzerine yazmasina ve sifreli verinin kalici
    olarak kaybolmasina yol acar (bkz. ``app/infrastructure/db/types.py``).
    """

    default_user_message = (
        "Sifreli alan cozulemedi. Alan sifreleme anahtari degismis olabilir; "
        "bu kaydin uzerine YAZMAYIN."
    )
    default_code = "field_decryption_failed"


# --------------------------------------------------------------------------
#  Girdi / veri
# --------------------------------------------------------------------------
class ValidationError(HotelError):
    """Girdi dogrulama hatasi."""

    default_user_message = "Girilen bilgiler gecerli degil."
    default_code = "validation_error"

    def __init__(
        self,
        user_message: str | None = None,
        *,
        field: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(user_message, **kwargs)
        self.field = field
        if field:
            self.context.setdefault("field", field)


class NotFoundError(HotelError):
    """Istenen kayit bulunamadi."""

    default_user_message = "Aradiginiz kayit bulunamadi."
    default_code = "not_found"

    def __init__(
        self,
        entity: str | None = None,
        entity_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        message = kwargs.pop("user_message", None)
        if message is None and entity:
            message = f"{entity} bulunamadi."
        super().__init__(message, **kwargs)
        self.entity = entity
        self.entity_id = entity_id
        if entity:
            self.context.setdefault("entity", entity)
        if entity_id is not None:
            self.context.setdefault("entity_id", str(entity_id))


class ConflictError(HotelError):
    """Ayni kaynak uzerinde cakisan islem (benzersizlik ihlali vb.)."""

    default_user_message = "Bu islem mevcut bir kayitla cakisiyor."
    default_code = "conflict"


# --------------------------------------------------------------------------
#  Is kurallari
# --------------------------------------------------------------------------
class BusinessRuleError(HotelError):
    """Bir isletme kurali ihlal edildi."""

    default_user_message = "Bu islem isletme kurallari nedeniyle yapilamiyor."
    default_code = "business_rule_violation"


class RoomNotAvailableError(BusinessRuleError):
    """Oda istenen tarihlerde musait degil."""

    default_user_message = "Secilen oda bu tarihlerde musait degil."
    default_code = "room_not_available"


class OverlappingReservationError(RoomNotAvailableError):
    """Ayni odada tarih araligi cakisan baska bir rezervasyon var."""

    default_user_message = "Bu odada secilen tarihlerle cakisan baska bir rezervasyon bulunuyor."
    default_code = "overlapping_reservation"


class RoomOutOfServiceError(RoomNotAvailableError):
    """Oda bakim/ariza nedeniyle satisa kapali."""

    default_user_message = "Oda bakim nedeniyle satisa kapali."
    default_code = "room_out_of_service"


class InvalidStateTransitionError(BusinessRuleError):
    """Gecersiz durum gecisi (or. iptal edilmis rezervasyona check-in)."""

    default_user_message = "Bu kaydin mevcut durumunda bu islem yapilamaz."
    default_code = "invalid_state_transition"


class PaymentError(BusinessRuleError):
    """Odeme / folyo tutari hatasi."""

    default_user_message = "Odeme islemi gerceklestirilemedi."
    default_code = "payment_error"


# --------------------------------------------------------------------------
#  Guvenlik
# --------------------------------------------------------------------------
class AuthenticationError(HotelError):
    """Kimlik dogrulama basarisiz."""

    default_user_message = "Kullanici adi veya parola hatali."
    default_code = "authentication_failed"


class AccountLockedError(AuthenticationError):
    """Cok sayida basarisiz denemeden sonra hesap gecici olarak kilitlendi."""

    default_user_message = (
        "Cok fazla basarisiz giris denemesi nedeniyle hesabiniz gecici olarak kilitlendi."
    )
    default_code = "account_locked"


class SessionExpiredError(AuthenticationError):
    """Oturum suresi doldu."""

    default_user_message = "Oturum sureniz doldu. Lutfen yeniden giris yapin."
    default_code = "session_expired"


class AuthorizationError(HotelError):
    """Yetki yetersiz."""

    default_user_message = "Bu islem icin yetkiniz bulunmuyor."
    default_code = "authorization_failed"

    def __init__(self, permission: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.permission = permission
        if permission:
            self.context.setdefault("required_permission", permission)


# --------------------------------------------------------------------------
#  Yapay zeka
# --------------------------------------------------------------------------
class AIProviderError(HotelError):
    """Yapay zeka saglayicisi kaynakli hata."""

    default_user_message = "Yapay zeka servisine ulasilamadi."
    default_code = "ai_provider_error"

    def __init__(
        self,
        user_message: str | None = None,
        *,
        provider: str | None = None,
        remedy: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(user_message, **kwargs)
        self.provider = provider
        #: Kullaniciya gosterilecek somut cozum onerisi.
        self.remedy = remedy
        if provider:
            self.context.setdefault("provider", provider)


class AIConnectionError(AIProviderError):
    """Saglayiciya baglanilamadi."""

    default_user_message = "Yapay zeka saglayicisina baglanilamadi."
    default_code = "ai_connection_error"


class AITimeoutError(AIProviderError):
    """Saglayici zaman asimina ugradi."""

    default_user_message = "Yapay zeka yaniti zaman asimina ugradi."
    default_code = "ai_timeout"


class AIAuthenticationError(AIProviderError):
    """Gecersiz veya eksik API anahtari."""

    default_user_message = "Yapay zeka servisi API anahtarini kabul etmedi."
    default_code = "ai_authentication_error"


class AIQuotaError(AIProviderError):
    """Kota / kredi tukendi veya hiz siniri asildi."""

    default_user_message = "Yapay zeka servisi kotasi dolmus gorunuyor."
    default_code = "ai_quota_exceeded"


class AIModelNotFoundError(AIProviderError):
    """Istenen model saglayicida bulunamadi."""

    default_user_message = "Secilen yapay zeka modeli saglayicida bulunamadi."
    default_code = "ai_model_not_found"


class AIResponseFormatError(AIProviderError):
    """Model beklenen formatta (or. gecerli JSON) yanit uretmedi."""

    default_user_message = "Yapay zeka beklenen formatta yanit uretemedi."
    default_code = "ai_response_format_error"


# --------------------------------------------------------------------------
#  AI Gelistirme Merkezi / terminal
# --------------------------------------------------------------------------
class DevCenterError(HotelError):
    """AI Gelistirme Merkezi hatasi."""

    default_user_message = "Gelistirme merkezi islemi tamamlanamadi."
    default_code = "devcenter_error"


class CommandBlockedError(DevCenterError):
    """Komut guvenlik politikasi tarafindan engellendi."""

    default_user_message = "Bu komut guvenlik politikasi geregi engellendi."
    default_code = "command_blocked"

    def __init__(self, reason: str, command: str | None = None, **kwargs: Any) -> None:
        super().__init__(f"Komut engellendi: {reason}", **kwargs)
        self.reason = reason
        self.command = command


class SandboxViolationError(DevCenterError):
    """Sandbox koku disina cikma girisimi."""

    default_user_message = "Islem yalnizca proje klasoru icinde yapilabilir."
    default_code = "sandbox_violation"


__all__ = [
    "AIAuthenticationError",
    "AIConnectionError",
    "AIModelNotFoundError",
    "AIProviderError",
    "AIQuotaError",
    "AIResponseFormatError",
    "AITimeoutError",
    "AccountLockedError",
    "AuthenticationError",
    "AuthorizationError",
    "BusinessRuleError",
    "CommandBlockedError",
    "ConfigurationError",
    "ConflictError",
    "DatabaseError",
    "DecryptionError",
    "DevCenterError",
    "HotelError",
    "InvalidStateTransitionError",
    "NotFoundError",
    "OverlappingReservationError",
    "PaymentError",
    "RoomNotAvailableError",
    "RoomOutOfServiceError",
    "SandboxViolationError",
    "SessionExpiredError",
    "ValidationError",
]
