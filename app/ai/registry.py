"""Saglayici kaydi ve yedege gecis (fallback) mantigi.

Sorumluluk siniri
-----------------
Bu modul **veritabanina dokunmaz**. ``AIUsage`` kaydini, maliyet hesabini ve
denetim gunlugunu servis katmani yazar; kayit yalnizca "hangi saglayici, hangi
model, hata olursa ne yapilir" sorularini yanitlar. Boylece kayit, veritabani
olmadan test edilebilir ve arayuz is parcaciklarindan guvenle cagrilabilir.

Yedege gecis politikasi
-----------------------
Yedege gecmek **her hatada dogru degildir**. Ayrim su ilkeye dayanir:
*ayni istek yedek saglayicida farkli sonuc verebilir mi?*

**Gecici hatalar** (yedege gecilir)
    :class:`~app.core.exceptions.AIConnectionError` - LM Studio kapali olabilir,
    bulut saglayici acik olabilir.
    :class:`~app.core.exceptions.AITimeoutError` - yerel model yavas, uzak model
    hizli olabilir.
    :class:`~app.core.exceptions.AIQuotaError` - bir saglayicinin kotasi dolmus,
    digerininki dolmamis olabilir.
    Duz 5xx - saglayicinin gecici arizasi.

**Kalici hatalar** (yedege GECILMEZ)
    :class:`~app.core.exceptions.AIAuthenticationError` - anahtar hatasi
    kullanicinin duzeltmesi gereken bir yapilandirma sorunudur. Yedege gecmek
    sorunu gizler; kullanici anahtarinin bozuk oldugunu asla ogrenemez ve
    aylarca yanlislikla ucretli saglayiciya calisir.
    :class:`~app.core.exceptions.AIModelNotFoundError` - istenen model adi
    genellikle saglayiciya ozeldir; yedekte de bulunmayacaktir.
    :class:`~app.core.exceptions.AIResponseFormatError` - jeton butcesi veya
    sema sorunu; ayni istek yedekte de ayni sekilde basarisiz olur. Cozum
    ``max_tokens`` degerini artirmaktir, baska saglayici denemek degil.

Yedege gecildiginde yanit :attr:`ChatResponse.used_fallback` = ``True`` ile
isaretlenir; arayuz bunu rozet olarak gosterir ve servis katmani ``AIUsage``
kaydinda ``fell_back_from`` alanini doldurur.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from types import TracebackType
from typing import Final

from app.ai import catalog
from app.ai.base import AIProvider
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.lmstudio import LMStudioProvider
from app.ai.providers.mock import MockProvider
from app.ai.providers.nvidia import NvidiaProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.ai.types import ChatRequest, ChatResponse, HealthStatus
from app.core.config import AISettings, ProviderName, get_settings
from app.core.exceptions import (
    AIAuthenticationError,
    AIModelNotFoundError,
    AIProviderError,
    AIResponseFormatError,
    ConfigurationError,
)
from app.core.log import get_logger
from app.domain.enums import AIProviderType, AITaskType

log = get_logger(__name__)

#: Ayni istek yedekte de ayni sekilde basarisiz olur - gecilmez.
PERMANENT_ERRORS: Final[tuple[type[AIProviderError], ...]] = (
    AIAuthenticationError,
    AIModelNotFoundError,
    AIResponseFormatError,
)

ProviderFactory = Callable[[AISettings], AIProvider]

#: Saglayici adi -> kurucu. Testler kendi fabrikalarini gecebilir.
DEFAULT_FACTORIES: Final[dict[ProviderName, ProviderFactory]] = {
    ProviderName.LMSTUDIO: lambda settings: LMStudioProvider(settings=settings.lmstudio),
    ProviderName.NVIDIA: lambda settings: NvidiaProvider(settings=settings.nvidia),
    ProviderName.OPENAI: lambda settings: OpenAICompatibleProvider(settings=settings.openai),
    ProviderName.ANTHROPIC: lambda settings: AnthropicProvider(settings=settings.anthropic),
    ProviderName.MOCK: lambda _settings: MockProvider(),
}


def should_fall_back(error: BaseException) -> bool:
    """Bu hatada yedek saglayiciya gecilmeli mi?

    Kalici hatalarda ``False`` doner - gerekcesi modul aciklamasindadir.
    """
    if isinstance(error, PERMANENT_ERRORS):
        return False
    return isinstance(error, AIProviderError)


class ProviderRegistry:
    """Ayarlardan saglayicilari kurar, yasam donguslerini yonetir."""

    def __init__(
        self,
        settings: AISettings | None = None,
        *,
        factories: dict[ProviderName, ProviderFactory] | None = None,
    ) -> None:
        self.settings = settings if settings is not None else get_settings().ai
        self._factories: dict[ProviderName, ProviderFactory] = {**DEFAULT_FACTORIES}
        if factories:
            self._factories.update(factories)
        self._instances: dict[ProviderName, AIProvider] = {}

    # ---------------- Kurulum ----------------
    def get(self, name: ProviderName) -> AIProvider:
        """Saglayiciyi (tembel kurarak) dondurur."""
        cached = self._instances.get(name)
        if cached is not None:
            return cached
        factory = self._factories.get(name)
        if factory is None:
            raise ConfigurationError(
                f"'{name.value}' yapay zeka sağlayıcısı tanımlı değil.",
                detail=f"unknown provider {name!r}",
                code="unknown_ai_provider",
            )
        instance = factory(self.settings)
        self._instances[name] = instance
        return instance

    def primary(self) -> AIProvider:
        """Birincil saglayici.

        Yapay zeka kapaliysa (:attr:`AISettings.enabled` = ``False``) sahte
        saglayici doner: uygulamanin yapay zeka cagiran ekranlari cokmek yerine
        "devre disi" yanitini alir.
        """
        if not self.settings.enabled:
            return self.get(ProviderName.MOCK)
        return self.get(self.settings.primary_provider)

    def fallback(self) -> AIProvider | None:
        """Yedek saglayici; tanimli degilse ``None``."""
        name = self.settings.fallback_provider
        if name is None or not self.settings.enabled:
            return None
        return self.get(name)

    def configured_names(self) -> list[ProviderName]:
        """Bu yapilandirmada gercekten kullanilacak saglayici adlari.

        Yapay zeka kapaliyken yalnizca sahte saglayici doner; teshis ciktisinin
        ``primary()`` ile ayni sonucu gostermesi icin bu ayrim burada yapilir.
        """
        if not self.settings.enabled:
            return [ProviderName.MOCK]
        names = [self.settings.primary_provider]
        if self.settings.fallback_provider is not None:
            names.append(self.settings.fallback_provider)
        return list(dict.fromkeys(names))

    def available_providers(self) -> list[AIProvider]:
        """Yapilandirilmis saglayici ornekleri: once birincil, sonra yedek.

        ``python -m app.cli check-ai`` gibi teshis akislari saglayicilari tek tek
        yoklamak ister. Kurulamayan saglayici (eksik fabrika) listeye alinmaz;
        teshis komutunun tek bir bozuk ayar yuzunden hic cikti uretmemesi
        kullaniciyi sorunun kaynagindan uzaklastirirdi.
        """
        providers: list[AIProvider] = []
        for name in self.configured_names():
            try:
                provider = self.get(name)
            except ConfigurationError:
                continue
            if not any(existing is provider for existing in providers):
                providers.append(provider)
        return providers

    def provider_settings(self, provider: AIProvider) -> object | None:
        """Saglayicinin ayar nesnesi (model secimi icin)."""
        return getattr(provider, "settings", None)

    # ---------------- Kullanim ----------------
    def prepare(
        self,
        request: ChatRequest,
        provider: AIProvider,
        task_type: AITaskType,
    ) -> ChatRequest:
        """Istekte model bos ise gorev turune uygun modeli doldurur.

        Ayar nesnesi olmayan saglayicilarda (or. :class:`MockProvider`) katalog
        onerisi **kullanilmaz**: :func:`app.ai.catalog.model_for_task` ayar
        verilmediginde LM Studio rol listesine duser ve ``google/gemma-4-12b-qat``
        adini LM Studio disindaki bir saglayiciya gondermek kesin bir 404 uretir.
        O durumda saglayicinin kendi ``chat_model`` degeri kullanilir, o da yoksa
        model bos birakilir ve saglayici kendi varsayilanina karar verir.
        """
        if request.model:
            return request
        settings = getattr(provider, "settings", None)
        if settings is not None:
            model = catalog.model_for_task(task_type, settings)
        elif provider.provider_type is AIProviderType.LMSTUDIO:
            model = catalog.model_for_task(task_type)
        else:
            model = ""
        if not model:
            model = getattr(provider, "chat_model", "") or ""
        return replace(request, model=model) if model else request

    def chat_with_fallback(
        self,
        request: ChatRequest,
        task_type: AITaskType = AITaskType.GENERAL_CHAT,
    ) -> ChatResponse:
        """Birincil saglayici ile dener, gerekirse yedege gecer."""
        primary = self.primary()
        try:
            return primary.chat(self.prepare(request, primary, task_type))
        except AIProviderError as exc:
            secondary = self.fallback()
            if secondary is None or secondary is primary or not should_fall_back(exc):
                raise
            log.warning(
                "ai_yedege_gecildi",
                birincil=primary.name,
                yedek=secondary.name,
                hata_kodu=exc.code,
                gorev=task_type.value,
            )
            response = secondary.chat(self.prepare(request, secondary, task_type))
            return replace(response, used_fallback=True)

    def health_report(self) -> dict[str, HealthStatus]:
        """Yapilandirilmis saglayicilarin durumu. Hata firlatmaz."""
        report: dict[str, HealthStatus] = {}
        for name in self.configured_names():
            try:
                provider = self.get(name)
            except ConfigurationError as exc:
                report[name.value] = HealthStatus(ok=False, message=exc.user_message)
                continue
            report[provider.name] = provider.health_check()
        return report

    # ---------------- Yasam dongusu ----------------
    def close(self) -> None:
        """Kurulmus tum saglayicilarin baglantilarini kapatir."""
        for provider in self._instances.values():
            provider.close()
        self._instances.clear()

    def __enter__(self) -> ProviderRegistry:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Uygulama genelinde paylasilan kayit.

    Tekil tutulur ki HTTP baglanti havuzu ekranlar arasinda paylasilsin.
    """
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def reset_registry() -> None:
    """Kaydi kapatip sifirlar (ayar degisikligi veya testler icin)."""
    global _registry
    if _registry is not None:
        _registry.close()
    _registry = None


__all__ = [
    "DEFAULT_FACTORIES",
    "PERMANENT_ERRORS",
    "ProviderFactory",
    "ProviderRegistry",
    "get_registry",
    "reset_registry",
    "should_fall_back",
]
