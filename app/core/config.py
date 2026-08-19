"""Uygulama yapilandirmasi.

Yapilandirma kaynaklari, oncelik sirasiyla:

1. Ortam degiskenleri (``HOTEL_*``)
2. ``.env`` dosyasi (yalnizca gelistirme; ``.gitignore`` icinde)
3. Kod icindeki guvenli varsayilanlar

Her yapilandirma grubu kendi ``BaseSettings`` sinifidir; boylece bir grup
degistiginde digerleri etkilenmez ve testlerde tek tek uretilebilirler.

**API anahtarlari bu modulde tutulmaz.** :mod:`app.core.secret_store` uzerinden
keyring'den okunur; buradaki ``*_api_key`` alanlari yalnizca gelistirme
ortaminda ``.env`` ile calisabilmek icin vardir ve
:meth:`AIProviderSettings.resolve_api_key` cagrisinda keyring onceliklidir.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import paths
from app.core.secret_store import get_secret

# --------------------------------------------------------------------------
#  Ortak
# --------------------------------------------------------------------------
_ENV_FILE = paths.ENV_FILE


def _base_config(prefix: str) -> SettingsConfigDict:
    """Tum ayar siniflari icin ortak pydantic-settings yapilandirmasi."""
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=_ENV_FILE if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
    )


class AppEnvironment(str, Enum):
    """Calisma ortami."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        return self is AppEnvironment.PRODUCTION


class ProviderName(str, Enum):
    """Desteklenen yapay zeka saglayicilari."""

    LMSTUDIO = "lmstudio"
    OPENAI = "openai"
    NVIDIA = "nvidia"
    ANTHROPIC = "anthropic"
    MOCK = "mock"


# --------------------------------------------------------------------------
#  Veritabani
# --------------------------------------------------------------------------
class DatabaseSettings(BaseSettings):
    """Veritabani baglanti ayarlari."""

    model_config = _base_config("HOTEL_DB_")

    url: str = Field(
        default="sqlite:///data/hotel.db",
        description="SQLAlchemy baglanti adresi. Goreli SQLite yollari veri koku ile birlestirilir.",
    )
    echo: bool = Field(default=False, description="Tum SQL ifadelerini logla (gelistirme).")
    pool_size: int = Field(default=5, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_timeout: int = Field(default=30, ge=1)
    pool_recycle: int = Field(default=1800, ge=-1)

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")

    def resolved_url(self) -> str:
        """Goreli SQLite yolunu mutlak yola cevirir.

        ``sqlite:///data/hotel.db`` gibi goreli bir adres, uygulamanin hangi
        calisma dizininden baslatildigina bagli olarak farkli dosyalari
        isaret ederdi. Bunu :data:`app.core.paths.DATA_ROOT` ile sabitleriz.
        """
        if not self.is_sqlite:
            return self.url
        prefix, _, rest = self.url.partition(":///")
        if not rest or rest == ":memory:":
            return self.url
        candidate = Path(rest)
        if candidate.is_absolute():
            return self.url
        absolute = (paths.DATA_ROOT / candidate).resolve()
        absolute.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}:///{absolute.as_posix()}"


# --------------------------------------------------------------------------
#  Guvenlik
# --------------------------------------------------------------------------
class SecuritySettings(BaseSettings):
    """Kimlik dogrulama ve oturum guvenligi ayarlari."""

    model_config = _base_config("HOTEL_")

    secret_key: SecretStr = Field(
        default=SecretStr("gelistirme-icin-guvensiz-varsayilan-deger-degistirin"),
        description="Oturum imzalama anahtari. Uretimde MUTLAKA degistirilmelidir.",
    )
    session_timeout_minutes: int = Field(default=30, ge=1, le=1440)
    max_failed_logins: int = Field(default=5, ge=1, le=50)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    password_min_length: int = Field(default=10, ge=8, le=128)

    # Argon2id parametreleri - OWASP 2024 onerilerine yakin, masaustu icin dengeli.
    argon2_time_cost: int = Field(default=3, ge=1, le=10)
    argon2_memory_cost: int = Field(default=65536, ge=8192, le=1048576)
    argon2_parallelism: int = Field(default=2, ge=1, le=16)

    @property
    def uses_default_secret(self) -> bool:
        """Varsayilan (guvensiz) anahtar hala kullaniliyor mu?"""
        return "degistirin" in self.secret_key.get_secret_value().lower()


# --------------------------------------------------------------------------
#  API sunucusu
# --------------------------------------------------------------------------
class APISettings(BaseSettings):
    """FastAPI servis katmani ayarlari."""

    model_config = _base_config("HOTEL_API_")

    enabled: bool = Field(default=True)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8760, ge=1, le=65535)
    rate_limit_per_minute: int = Field(default=120, ge=1)
    cors_origins: str = Field(default="http://127.0.0.1:8760")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @field_validator("host")
    @classmethod
    def _warn_on_public_bind(cls, value: str) -> str:
        # 0.0.0.0'a baglanmak masaustu uygulamasi icin gereksiz risk yaratir.
        # Engellemek yerine kaydediyoruz; uyari baslangicta loglanir.
        return value


# --------------------------------------------------------------------------
#  Loglama
# --------------------------------------------------------------------------
class LoggingSettings(BaseSettings):
    """Yapilandirilmis loglama ayarlari."""

    model_config = _base_config("HOTEL_LOG_")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    dir: str = Field(default="logs")
    json_format: bool = Field(default=False, alias="HOTEL_LOG_JSON")
    retention_days: int = Field(default=30, ge=1, le=3650)
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=10, ge=1, le=100)

    @property
    def directory(self) -> Path:
        candidate = Path(self.dir)
        return candidate if candidate.is_absolute() else paths.DATA_ROOT / candidate


# --------------------------------------------------------------------------
#  Yapay zeka
# --------------------------------------------------------------------------
class AIProviderSettings(BaseSettings):
    """Tek bir yapay zeka saglayicisinin ayarlari.

    Alt siniflar yalnizca ``model_config`` prefix'ini ve varsayilanlari
    degistirir; davranis ortaktir.
    """

    model_config = _base_config("HOTEL_AI_UNUSED_")

    #: Bu saglayicinin mantiksal adi; alt siniflar override eder.
    provider: ProviderName = ProviderName.MOCK

    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    chat_model: str = ""
    vision_model: str = ""
    math_model: str = ""
    embed_model: str = ""

    @property
    def secret_name(self) -> str:
        """keyring'de kullanilacak sir adi, or. ``nvidia_api_key``."""
        return f"{self.provider.value}_api_key"

    def resolve_api_key(self, *, allow_env: bool = True) -> str | None:
        """Anahtari once keyring'den, sonra ``.env``'den cozer.

        Keyring uretim icin tercih edilen yontemdir; ``.env`` yalnizca
        gelistirme kolayligi saglar.
        """
        from_keyring = get_secret(self.secret_name, allow_env=False)
        if from_keyring:
            return from_keyring
        if allow_env:
            env_value = self.api_key.get_secret_value()
            if env_value:
                return env_value
        return None

    @property
    def has_api_key(self) -> bool:
        return bool(self.resolve_api_key())


class LMStudioSettings(AIProviderSettings):
    """LM Studio yerel sunucusu (OpenAI uyumlu)."""

    model_config = _base_config("HOTEL_LMSTUDIO_")

    provider: ProviderName = ProviderName.LMSTUDIO
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: SecretStr = SecretStr("lm-studio")  # LM Studio anahtar dogrulamaz
    chat_model: str = "google/gemma-4-12b-qat"
    vision_model: str = "qwen/qwen3-vl-8b"
    math_model: str = "qwen2.5-math-7b-instruct"
    embed_model: str = "text-embedding-nomic-embed-text-v1.5"


class NvidiaSettings(AIProviderSettings):
    """NVIDIA NIM / build.nvidia.com."""

    model_config = _base_config("HOTEL_NVIDIA_")

    provider: ProviderName = ProviderName.NVIDIA
    base_url: str = "https://integrate.api.nvidia.com/v1"
    chat_model: str = ""


class OpenAISettings(AIProviderSettings):
    """OpenAI veya OpenAI uyumlu herhangi bir servis."""

    model_config = _base_config("HOTEL_OPENAI_")

    provider: ProviderName = ProviderName.OPENAI
    base_url: str = "https://api.openai.com/v1"
    chat_model: str = ""


class AnthropicSettings(AIProviderSettings):
    """Anthropic Claude API."""

    model_config = _base_config("HOTEL_ANTHROPIC_")

    provider: ProviderName = ProviderName.ANTHROPIC
    base_url: str = "https://api.anthropic.com/v1"
    chat_model: str = ""


class AISettings(BaseSettings):
    """Yapay zeka katmaninin genel ayarlari."""

    model_config = _base_config("HOTEL_AI_")

    enabled: bool = Field(default=True)
    primary_provider: ProviderName = Field(default=ProviderName.LMSTUDIO)
    fallback_provider: ProviderName | None = Field(default=ProviderName.MOCK)
    default_timeout: int = Field(default=120, ge=5, le=1800)
    default_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    default_max_tokens: int = Field(default=2048, ge=64, le=200_000)
    track_cost: bool = Field(default=True)
    max_retries: int = Field(default=2, ge=0, le=10)

    #: Yapay zekanin veri degistiren islemleri kullanici onayi olmadan
    #: yapmasini engeller. Kapatilmasi ONERILMEZ.
    require_approval_for_writes: bool = Field(default=True)

    # Alt saglayici ayarlari
    lmstudio: LMStudioSettings = Field(default_factory=LMStudioSettings)
    nvidia: NvidiaSettings = Field(default_factory=NvidiaSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)

    def provider_settings(self, name: ProviderName) -> AIProviderSettings | None:
        """Verilen saglayicinin ayar nesnesini dondurur."""
        return {
            ProviderName.LMSTUDIO: self.lmstudio,
            ProviderName.NVIDIA: self.nvidia,
            ProviderName.OPENAI: self.openai,
            ProviderName.ANTHROPIC: self.anthropic,
        }.get(name)

    @model_validator(mode="after")
    def _no_self_fallback(self) -> AISettings:
        if self.fallback_provider is not None and self.fallback_provider == self.primary_provider:
            # Kendine yedek olmak sonsuz dongu riski yaratir; sessizce kapatiriz.
            object.__setattr__(self, "fallback_provider", None)
        return self


# --------------------------------------------------------------------------
#  AI Gelistirme Merkezi
# --------------------------------------------------------------------------
class DevCenterSettings(BaseSettings):
    """AI Gelistirme Merkezi ve kisitli terminal ayarlari."""

    model_config = _base_config("HOTEL_DEVCENTER_")

    enabled: bool = Field(default=True)
    root: str = Field(default="", description="Sandbox koku. Bos ise proje koku kullanilir.")
    require_approval: bool = Field(default=True)
    command_timeout: int = Field(default=300, ge=5, le=3600)
    git_checkpoint: bool = Field(default=True)
    max_output_bytes: int = Field(default=256 * 1024, ge=1024)

    @property
    def sandbox_root(self) -> Path:
        return Path(self.root).resolve() if self.root else paths.PROJECT_ROOT.resolve()


# --------------------------------------------------------------------------
#  Yedekleme
# --------------------------------------------------------------------------
class BackupSettings(BaseSettings):
    """Veritabani yedekleme ayarlari."""

    model_config = _base_config("HOTEL_BACKUP_")

    dir: str = Field(default="backups")
    retention: int = Field(default=14, ge=1, le=365)

    @property
    def directory(self) -> Path:
        candidate = Path(self.dir)
        return candidate if candidate.is_absolute() else paths.DATA_ROOT / candidate


# --------------------------------------------------------------------------
#  Turkiye'ye ozel entegrasyonlar
# --------------------------------------------------------------------------
class TurkeyIntegrationSettings(BaseSettings):
    """e-Fatura / e-Arsiv / KBS entegrasyon ayarlari.

    .. warning::
       Bu entegrasyonlar **tamamlanmamistir**. Yalnizca arayuz (protokol)
       katmani mevcuttur ve varsayilan olarak kapalidir. Gercek bir servis
       saglayici ile entegrasyon yapilmadan uretimde kullanilmamalidir.
       Ayrintilar icin ``docs/ROADMAP.md``.
    """

    model_config = _base_config("HOTEL_")

    efatura_enabled: bool = Field(default=False)
    efatura_provider: str = Field(default="")
    efatura_base_url: str = Field(default="")
    kbs_enabled: bool = Field(default=False)
    kbs_base_url: str = Field(default="")

    @property
    def any_enabled(self) -> bool:
        return self.efatura_enabled or self.kbs_enabled


# --------------------------------------------------------------------------
#  Kok ayar nesnesi
# --------------------------------------------------------------------------
class Settings(BaseSettings):
    """Uygulamanin tum ayarlarini toplayan kok nesne."""

    model_config = _base_config("HOTEL_APP_")

    env: AppEnvironment = Field(default=AppEnvironment.DEVELOPMENT)
    debug: bool = Field(default=False)
    language: Literal["tr", "en"] = Field(default="tr")
    theme: Literal["light", "dark", "system"] = Field(default="dark")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    api: APISettings = Field(default_factory=APISettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    ai: AISettings = Field(default_factory=AISettings)
    devcenter: DevCenterSettings = Field(default_factory=DevCenterSettings)
    backup: BackupSettings = Field(default_factory=BackupSettings)
    turkey: TurkeyIntegrationSettings = Field(default_factory=TurkeyIntegrationSettings)

    # ---------------- Turetilmis ozellikler ----------------
    @property
    def is_production(self) -> bool:
        return self.env.is_production

    @property
    def is_testing(self) -> bool:
        return self.env is AppEnvironment.TESTING

    def startup_warnings(self) -> list[str]:
        """Baslangicta loglanacak/gosterilecek yapilandirma uyarilari.

        Uygulamayi durdurmaz; yalnizca riskli ayarlari gorunur kilar.
        """
        warnings: list[str] = []
        if self.is_production:
            if self.security.uses_default_secret:
                warnings.append(
                    "URETIM ORTAMINDA VARSAYILAN HOTEL_SECRET_KEY KULLANILIYOR. "
                    'Derhal degistirin: python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            if self.debug:
                warnings.append("Uretim ortaminda DEBUG acik. Kapatmaniz onerilir.")
            if self.database.echo:
                warnings.append("Uretim ortaminda SQL echo acik; loglar sisebilir.")
        if self.api.host not in {"127.0.0.1", "localhost", "::1"}:
            warnings.append(
                f"API sunucusu '{self.api.host}' adresine baglaniyor. Masaustu kullanimda "
                "127.0.0.1 disina acmak gereksiz risk olusturur."
            )
        if not self.devcenter.require_approval:
            warnings.append(
                "AI Gelistirme Merkezi onay istemeden calisacak sekilde ayarlanmis. "
                "Bu ayar onerilmez."
            )
        if not self.ai.require_approval_for_writes:
            warnings.append(
                "Yapay zekanin veri degistiren islemleri icin onay zorunlulugu kapatilmis."
            )
        return warnings


# --------------------------------------------------------------------------
#  Erisim
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Uygulama ayarlarini (onbelleklenmis) dondurur."""
    return Settings()


def reload_settings() -> Settings:
    """Onbellegi temizleyip ayarlari yeniden okur.

    Ayarlar ekranindan degisiklik yapildiktan sonra veya testlerde kullanilir.
    """
    get_settings.cache_clear()
    return get_settings()


__all__ = [
    "AIProviderSettings",
    "AISettings",
    "APISettings",
    "AnthropicSettings",
    "AppEnvironment",
    "BackupSettings",
    "DatabaseSettings",
    "DevCenterSettings",
    "LMStudioSettings",
    "LoggingSettings",
    "NvidiaSettings",
    "OpenAISettings",
    "ProviderName",
    "SecuritySettings",
    "Settings",
    "TurkeyIntegrationSettings",
    "get_settings",
    "reload_settings",
]
