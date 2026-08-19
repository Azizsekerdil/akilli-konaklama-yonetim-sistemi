"""Saglayici kaydi, yedege gecis ve model katalogu testleri.

Yedege gecis kurali burada sinanir: **gecici** hatalarda (baglanti, zaman
asimi, kota) yedek saglayiciya gecilir; **kalici** hatalarda (gecersiz anahtar,
bulunamayan model, bicim hatasi) gecilmez - ayni istek yedekte de ayni sekilde
basarisiz olur ve gecmek asil sorunu gizler.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.ai import catalog
from app.ai.catalog import (
    BIOMISTRAL_MODEL,
    GEMMA_CHAT_MODEL,
    LMSTUDIO_LIGHT_VISION_MODEL,
    NOMIC_EMBED_MODEL,
    QWEN_MATH_MODEL,
    QWEN_VISION_MODEL,
)
from app.ai.providers.lmstudio import LMStudioProvider
from app.ai.providers.mock import MockProvider
from app.ai.registry import ProviderRegistry, should_fall_back
from app.ai.types import ChatMessage, ChatRequest
from app.core.config import AISettings, ProviderName
from app.core.exceptions import (
    AIAuthenticationError,
    AIConnectionError,
    AIModelNotFoundError,
    AIProviderError,
    AIQuotaError,
    AIResponseFormatError,
    AITimeoutError,
    ConfigurationError,
)
from app.domain.enums import AICapability, AIProviderType, AITaskType

pytestmark = pytest.mark.ai


def ayarlar(**kwargs) -> AISettings:
    """Testler icin acikca yapilandirilmis yapay zeka ayarlari."""
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("primary_provider", ProviderName.LMSTUDIO)
    kwargs.setdefault("fallback_provider", ProviderName.MOCK)
    return AISettings(**kwargs)


def istek(icerik: str = "Doluluk ozeti") -> ChatRequest:
    return ChatRequest(messages=[ChatMessage.user(icerik)], max_tokens=512)


def kayit(
    *,
    birincil: MockProvider | LMStudioProvider,
    yedek: MockProvider | None = None,
    settings: AISettings | None = None,
) -> ProviderRegistry:
    """Sahte fabrikalarla kurulmus kayit."""
    fabrikalar = {ProviderName.LMSTUDIO: lambda _s: birincil}
    if yedek is not None:
        fabrikalar[ProviderName.MOCK] = lambda _s: yedek
    return ProviderRegistry(settings or ayarlar(), factories=fabrikalar)


# --------------------------------------------------------------------------
#  Kurulum
# --------------------------------------------------------------------------
class TestKurulum:
    def test_ayarlardan_saglayici_kurulur(self):
        with ProviderRegistry(ayarlar()) as registry:
            birincil = registry.primary()
            assert isinstance(birincil, LMStudioProvider)
            assert birincil.is_local

    def test_yedek_saglayici_cozulur(self):
        with ProviderRegistry(ayarlar()) as registry:
            assert isinstance(registry.fallback(), MockProvider)

    def test_ayni_saglayici_yeniden_kullanilir(self):
        with ProviderRegistry(ayarlar()) as registry:
            assert registry.get(ProviderName.LMSTUDIO) is registry.get(ProviderName.LMSTUDIO)

    def test_yapay_zeka_kapaliyken_sahte_saglayiciya_dusulur(self):
        with ProviderRegistry(ayarlar(enabled=False)) as registry:
            assert isinstance(registry.primary(), MockProvider)
            assert registry.fallback() is None

    def test_yedek_tanimsizsa_none(self):
        with ProviderRegistry(ayarlar(fallback_provider=None)) as registry:
            assert registry.fallback() is None

    def test_bilinmeyen_saglayici_yapilandirma_hatasi(self):
        registry = ProviderRegistry(ayarlar(), factories={})
        registry._factories.pop(ProviderName.NVIDIA)
        with pytest.raises(ConfigurationError):
            registry.get(ProviderName.NVIDIA)

    def test_available_providers_birincil_ve_yedegi_dondurur(self):
        with ProviderRegistry(ayarlar()) as registry:
            saglayicilar = registry.available_providers()
        assert [saglayici.name for saglayici in saglayicilar] == ["lmstudio", "mock"]

    def test_available_providers_kapaliyken_yalnizca_sahte(self):
        """Yapay zeka kapaliyken teshis, gercekten kullanilacak saglayiciyi gostermelidir."""
        with ProviderRegistry(ayarlar(enabled=False)) as registry:
            assert [saglayici.name for saglayici in registry.available_providers()] == ["mock"]

    def test_available_providers_kurulamayan_saglayiciyi_atlar(self):
        registry = ProviderRegistry(ayarlar(primary_provider=ProviderName.NVIDIA))
        registry._factories.pop(ProviderName.NVIDIA)
        with registry:
            assert [saglayici.name for saglayici in registry.available_providers()] == ["mock"]

    def test_close_tum_saglayicilari_kapatir(self):
        birincil = MockProvider()
        yedek = MockProvider()
        registry = kayit(birincil=birincil, yedek=yedek)
        registry.primary()
        registry.fallback()
        assert registry._instances
        registry.close()
        assert not registry._instances


# --------------------------------------------------------------------------
#  Yedege gecis
# --------------------------------------------------------------------------
class TestYedegeGecis:
    @pytest.mark.parametrize(
        "hata",
        [
            AIConnectionError("LM Studio kapali"),
            AITimeoutError("model yavas"),
            AIQuotaError("kota doldu"),
            AIProviderError("sunucu 503"),
        ],
    )
    def test_gecici_hatalarda_yedege_gecilir(self, hata: AIProviderError):
        birincil = MockProvider(fail_with=hata)
        yedek = MockProvider(responses=["yedekten gelen yanit"])
        with kayit(birincil=birincil, yedek=yedek) as registry:
            yanit = registry.chat_with_fallback(istek())

        assert yanit.content == "yedekten gelen yanit"
        assert yanit.used_fallback is True
        assert len(birincil.calls) == 1
        assert len(yedek.calls) == 1

    @pytest.mark.parametrize(
        "hata",
        [
            AIAuthenticationError("anahtar gecersiz"),
            AIModelNotFoundError("model yok"),
            AIResponseFormatError("gecersiz JSON"),
        ],
    )
    def test_kalici_hatalarda_yedege_gecilmez(self, hata: AIProviderError):
        """Anahtar hatasini yedekle gizlemek, kullanicinin sorunu gormesini engeller."""
        birincil = MockProvider(fail_with=hata)
        yedek = MockProvider(responses=["asla cagrilmamali"])
        with kayit(birincil=birincil, yedek=yedek) as registry, pytest.raises(type(hata)):
            registry.chat_with_fallback(istek())
        assert yedek.calls == []

    def test_yedek_yoksa_ozgun_hata_firlatilir(self):
        birincil = MockProvider(fail_with=AIConnectionError("kapali"))
        with (
            kayit(birincil=birincil, settings=ayarlar(fallback_provider=None)) as registry,
            pytest.raises(AIConnectionError),
        ):
            registry.chat_with_fallback(istek())

    def test_basarili_cagride_yedek_isareti_konmaz(self):
        birincil = MockProvider(responses=["birincil yanit"])
        yedek = MockProvider()
        with kayit(birincil=birincil, yedek=yedek) as registry:
            yanit = registry.chat_with_fallback(istek())
        assert yanit.used_fallback is False
        assert yedek.calls == []

    def test_yedek_de_basarisizsa_hata_yayilir(self):
        birincil = MockProvider(fail_with=AIConnectionError("birincil kapali"))
        yedek = MockProvider(fail_with=AITimeoutError("yedek de yavas"))
        with kayit(birincil=birincil, yedek=yedek) as registry, pytest.raises(AITimeoutError):
            registry.chat_with_fallback(istek())

    def test_should_fall_back_kurali(self):
        assert should_fall_back(AIConnectionError())
        assert should_fall_back(AITimeoutError())
        assert should_fall_back(AIQuotaError())
        assert should_fall_back(AIProviderError())
        assert not should_fall_back(AIAuthenticationError())
        assert not should_fall_back(AIModelNotFoundError())
        assert not should_fall_back(AIResponseFormatError())
        assert not should_fall_back(ValueError("yapay zeka disi hata"))


# --------------------------------------------------------------------------
#  Model secimi
# --------------------------------------------------------------------------
class TestModelSecimi:
    def test_bos_model_gorev_turune_gore_doldurulur(self):
        birincil = MockProvider()
        with ProviderRegistry(
            ayarlar(), factories={ProviderName.LMSTUDIO: lambda _s: birincil}
        ) as registry:
            registry.chat_with_fallback(istek(), AITaskType.GENERAL_CHAT)
        assert len(birincil.calls) == 1

    def test_ayarsiz_saglayiciya_lmstudio_modeli_verilmez(self):
        """Katalog onerisi LM Studio'ya ozeldir; baska saglayiciya gonderilirse 404 olur.

        ``MockProvider``'in ayar nesnesi yoktur. Eskiden bu durumda katalogun
        LM Studio rol listesi devreye giriyor ve modele ``google/gemma-4-12b-qat``
        adi yaziliyordu - gercek bir uzak saglayicida bu kesin bir 404 uretirdi.
        """
        birincil = MockProvider()
        with ProviderRegistry(
            ayarlar(), factories={ProviderName.LMSTUDIO: lambda _s: birincil}
        ) as registry:
            hazir = registry.prepare(istek(), birincil, AITaskType.GENERAL_CHAT)
            gorsel = registry.prepare(istek(), birincil, AITaskType.DOCUMENT_VISION)
        assert hazir.model == ""
        assert gorsel.model == ""

    def test_lmstudio_gorev_turune_gore_model_secer(self):
        with ProviderRegistry(ayarlar()) as registry:
            saglayici = registry.primary()
            sohbet = registry.prepare(istek(), saglayici, AITaskType.GENERAL_CHAT)
            gorsel = registry.prepare(istek(), saglayici, AITaskType.DOCUMENT_VISION)
            matematik = registry.prepare(istek(), saglayici, AITaskType.PRICING_SUGGESTION)

        assert sohbet.model == GEMMA_CHAT_MODEL
        assert gorsel.model == QWEN_VISION_MODEL
        assert matematik.model == QWEN_MATH_MODEL

    def test_acikca_verilen_model_degistirilmez(self):
        with ProviderRegistry(ayarlar()) as registry:
            saglayici = registry.primary()
            talep = ChatRequest(messages=[ChatMessage.user("x")], model="ozel-model")
            assert registry.prepare(talep, saglayici, AITaskType.DOCUMENT_VISION).model == (
                "ozel-model"
            )

    def test_prepare_ozgun_istegi_degistirmez(self):
        with ProviderRegistry(ayarlar()) as registry:
            saglayici = registry.primary()
            talep = istek()
            registry.prepare(talep, saglayici, AITaskType.GENERAL_CHAT)
            assert talep.model == ""


# --------------------------------------------------------------------------
#  Saglik raporu
# --------------------------------------------------------------------------
class TestSaglikRaporu:
    def test_saglikli_saglayici_raporlanir(self):
        with kayit(birincil=MockProvider(), settings=ayarlar(fallback_provider=None)) as registry:
            rapor = registry.health_report()
        assert rapor["mock"].ok is True
        assert rapor["mock"].models_found > 0
        assert rapor["mock"].models_found == len(rapor["mock"].model_ids)

    def test_kapaliyken_rapor_sahte_saglayiciyi_gosterir(self):
        """Kapaliyken ``primary()`` sahte saglayiciya duser; rapor da onu gostermelidir."""
        with ProviderRegistry(ayarlar(enabled=False)) as registry:
            rapor = registry.health_report()
        assert list(rapor) == ["mock"]

    @respx.mock
    def test_rapor_hata_firlatmaz(self):
        """Saglayiciya ulasilamazsa rapor cokmez, ``ok=False`` doner."""
        respx.get("http://127.0.0.1:1234/v1/models").mock(
            side_effect=httpx.ConnectError("sunucu kapali")
        )
        with ProviderRegistry(ayarlar(fallback_provider=None)) as registry:
            rapor = registry.health_report()
        assert rapor["lmstudio"].ok is False
        assert "LM Studio" in rapor["lmstudio"].message


# --------------------------------------------------------------------------
#  Katalog
# --------------------------------------------------------------------------
class TestKatalog:
    def test_alti_gercek_lmstudio_modeli_kayitli(self):
        modeller = catalog.models_for_provider(AIProviderType.LMSTUDIO)
        kimlikler = {model.model_id for model in modeller}
        assert kimlikler == {
            GEMMA_CHAT_MODEL,
            QWEN_VISION_MODEL,
            QWEN_MATH_MODEL,
            NOMIC_EMBED_MODEL,
            LMSTUDIO_LIGHT_VISION_MODEL,
            BIOMISTRAL_MODEL,
        }

    def test_rol_onerileri(self):
        assert catalog.recommended_model_id(AICapability.CHAT) == GEMMA_CHAT_MODEL
        assert catalog.recommended_model_id(AICapability.VISION) == QWEN_VISION_MODEL
        assert catalog.recommended_model_id(AICapability.MATH) == QWEN_MATH_MODEL
        assert catalog.recommended_model_id(AICapability.EMBEDDING) == NOMIC_EMBED_MODEL

    def test_gemma_dusunme_modeli_ve_sohbet_varsayilani(self):
        spec = catalog.lookup(GEMMA_CHAT_MODEL)
        assert spec is not None
        assert spec.supports_reasoning
        assert AICapability.REASONING in spec.capabilities
        assert "max_tokens" in spec.notes

    def test_hafif_gorsel_model_moondream(self):
        assert LMSTUDIO_LIGHT_VISION_MODEL == "moondream-2b-2025-04-14"
        assert AICapability.VISION in catalog.capabilities_for(LMSTUDIO_LIGHT_VISION_MODEL)

    def test_biomistral_varsayilan_yapilmaz(self):
        """Saglik alani modeli otel senaryolarinda varsayilan olmamalidir."""
        assert not catalog.is_recommended_default(BIOMISTRAL_MODEL)
        assert catalog.is_recommended_default(GEMMA_CHAT_MODEL)
        onerilenler = {
            spec.model_id for spec in catalog.recommended_models(AIProviderType.LMSTUDIO)
        }
        assert BIOMISTRAL_MODEL not in onerilenler

        spec = catalog.lookup(BIOMISTRAL_MODEL)
        assert spec is not None
        # Gerekce koda gomulu: baska bir gelistirici "neden varsayilan degil?"
        # sorusunun yanitini kaynakta bulmalidir.
        assert "SAGLIK ALANI" in spec.notes

    def test_yerel_modeller_ucretsizdir(self):
        for spec in catalog.models_for_provider(AIProviderType.LMSTUDIO):
            assert spec.is_free
        assert catalog.estimate_cost(GEMMA_CHAT_MODEL, 10_000, 5_000) == Decimal("0.000000")

    def test_bilinmeyen_model_maliyeti_sifir(self):
        assert catalog.estimate_cost("hic-bilinmeyen", 1000, 1000) == Decimal("0")
        assert catalog.lookup("hic-bilinmeyen") is None
        assert catalog.capabilities_for("hic-bilinmeyen") == frozenset()

    def test_model_kimligi_buyuk_kucuk_harf_duyarsiz(self):
        assert catalog.lookup("GOOGLE/Gemma-4-12B-QAT") is not None
        assert catalog.display_name_for("  " + GEMMA_CHAT_MODEL + "  ") == "Gemma 4 12B (QAT)"

    def test_gorev_yetenek_eslemesi(self):
        assert catalog.capability_for_task(AITaskType.DOCUMENT_VISION) is AICapability.VISION
        assert catalog.capability_for_task(AITaskType.PRICING_SUGGESTION) is AICapability.MATH
        assert catalog.capability_for_task(AITaskType.EMBEDDING) is AICapability.EMBEDDING
        assert catalog.capability_for_task(AITaskType.DAILY_SUMMARY) is AICapability.CHAT

    def test_tum_gorev_turleri_eslenmis(self):
        eksik = [task for task in AITaskType if task not in catalog.TASK_CAPABILITY]
        assert eksik == []

    def test_uzak_saglayiciya_yerel_model_onerilmez(self):
        """gemma adini NVIDIA'ya gondermek kesin 404 uretirdi."""
        nvidia = ayarlar().nvidia
        assert catalog.model_for_task(AITaskType.GENERAL_CHAT, nvidia) == ""

    def test_ayarlardaki_model_onceliklidir(self):
        lmstudio = ayarlar().lmstudio
        assert catalog.model_for_task(AITaskType.EMBEDDING, lmstudio) == NOMIC_EMBED_MODEL
        assert catalog.model_for_task(AITaskType.DOCUMENT_VISION, lmstudio) == QWEN_VISION_MODEL
