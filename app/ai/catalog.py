"""Bilinen modellerin yetenek ve maliyet katalogu.

Ne icin var?
------------
``/v1/models`` uclari yalnizca model **kimligini** doner; "bu model goruntu
anlar mi", "dusunme modeli mi", "1000 jetonu kaca mal olur" bilgisi yoktur.
Bu katalog o boslugu doldurur ve arayuzun her gorev icin makul bir varsayilan
onermesini saglar.

Kaynak
------
Buradaki LM Studio kayitlari, kullanicinin gercek sunucusundan alinan
``/v1/models`` ciktisina dayanir::

    google/gemma-4-12b-qat
    qwen/qwen3-vl-8b
    biomistral-7b
    qwen2.5-math-7b-instruct
    moondream-2b-2025-04-14
    text-embedding-nomic-embed-text-v1.5

Baglam penceresi bilincli olarak ``None`` birakilmistir: ayni model dosyasi
LM Studio'da farkli baglam ayarlariyla yuklenebilir, dolayisiyla kod icine
gomulen bir sayi yaniltici olur. Gercek deger sunucudan okunmalidir.

Maliyet
-------
Yerel modellerde maliyet **sifirdir** (elektrik disinda). Uzak saglayicilarin
fiyatlari sik degistigi icin koda gomulmez; :class:`app.infrastructure.db.models.ai.AIModel`
uzerinden yapilandirilir ve buradaki katalog yalnizca yerel modelleri kesin
olarak sifirlar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from app.core.config import AIProviderSettings, ProviderName
from app.domain.enums import AICapability, AIProviderType, AITaskType

_ZERO: Final[Decimal] = Decimal("0.000000")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Bir modelin katalog kaydi."""

    model_id: str
    display_name: str
    provider_type: AIProviderType
    capabilities: frozenset[AICapability] = field(default=frozenset())
    context_window: int | None = None
    supports_reasoning: bool = False
    input_cost_per_1k: Decimal = _ZERO
    output_cost_per_1k: Decimal = _ZERO
    #: Otel senaryolarinda varsayilan olarak onerilebilir mi?
    recommended_default: bool = True
    notes: str = ""

    @property
    def is_free(self) -> bool:
        return self.input_cost_per_1k == _ZERO and self.output_cost_per_1k == _ZERO

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """Bir cagrinin tahmini maliyeti.

        Dusunme jetonlari ``completion_tokens`` icinde sayilmalidir; aksi halde
        dusunme modellerinin gideri oldugundan cok dusuk gorunur.
        """
        cost = (
            Decimal(max(0, prompt_tokens)) / 1000 * self.input_cost_per_1k
            + Decimal(max(0, completion_tokens)) / 1000 * self.output_cost_per_1k
        )
        return cost.quantize(Decimal("0.000001"))


# --------------------------------------------------------------------------
#  LM Studio - kullanicinin sunucusunda dogrulanmis modeller
# --------------------------------------------------------------------------
GEMMA_CHAT_MODEL: Final[str] = "google/gemma-4-12b-qat"
QWEN_VISION_MODEL: Final[str] = "qwen/qwen3-vl-8b"
MOONDREAM_VISION_MODEL: Final[str] = "moondream-2b-2025-04-14"
QWEN_MATH_MODEL: Final[str] = "qwen2.5-math-7b-instruct"
NOMIC_EMBED_MODEL: Final[str] = "text-embedding-nomic-embed-text-v1.5"
BIOMISTRAL_MODEL: Final[str] = "biomistral-7b"

LMSTUDIO_MODELS: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(
        model_id=GEMMA_CHAT_MODEL,
        display_name="Gemma 4 12B (QAT)",
        provider_type=AIProviderType.LMSTUDIO,
        capabilities=frozenset(
            {
                AICapability.CHAT,
                AICapability.REASONING,
                AICapability.JSON_MODE,
                AICapability.CODE,
            }
        ),
        supports_reasoning=True,
        notes=(
            "DUSUNME MODELI. Yaniti 'content' ve 'reasoning_content' olmak uzere iki "
            "parcada doner. max_tokens dusuk verilirse (or. 60) tum jeton butcesini "
            "dusunmede harcar ve 'content' BOS doner; en az 1024 jeton ayirin. "
            "Genel sohbet ve yonetim ozetleri icin varsayilan."
        ),
    ),
    ModelSpec(
        model_id=QWEN_VISION_MODEL,
        display_name="Qwen3-VL 8B",
        provider_type=AIProviderType.LMSTUDIO,
        capabilities=frozenset({AICapability.CHAT, AICapability.VISION, AICapability.JSON_MODE}),
        notes="Kimlik/pasaport ve fatura goruntusu okuma icin birincil gorsel model.",
    ),
    ModelSpec(
        model_id=MOONDREAM_VISION_MODEL,
        display_name="Moondream 2B",
        provider_type=AIProviderType.LMSTUDIO,
        capabilities=frozenset({AICapability.CHAT, AICapability.VISION}),
        notes=(
            "Hafif gorsel model. Dusuk donanimda veya toplu islerde Qwen3-VL yerine "
            "kullanilir; ayrinti dogrulugu daha dusuktur."
        ),
    ),
    ModelSpec(
        model_id=QWEN_MATH_MODEL,
        display_name="Qwen2.5 Math 7B Instruct",
        provider_type=AIProviderType.LMSTUDIO,
        capabilities=frozenset({AICapability.CHAT, AICapability.MATH}),
        notes=(
            "Doluluk/fiyat hesaplarinin sagirlamasi icin. Nihai para tutarlari ASLA "
            "modele hesaplattirilmaz; app.domain.rules.pricing Decimal ile hesaplar, "
            "model yalnizca oneri uretir."
        ),
    ),
    ModelSpec(
        model_id=NOMIC_EMBED_MODEL,
        display_name="Nomic Embed Text v1.5",
        provider_type=AIProviderType.LMSTUDIO,
        capabilities=frozenset({AICapability.EMBEDDING}),
        notes="Belge arama (RAG) icin gomme modeli. Sohbet icin kullanilamaz.",
    ),
    ModelSpec(
        model_id=BIOMISTRAL_MODEL,
        display_name="BioMistral 7B",
        provider_type=AIProviderType.LMSTUDIO,
        capabilities=frozenset({AICapability.CHAT}),
        recommended_default=False,
        notes=(
            "SAGLIK ALANI modeli. Otel senaryolari icin VARSAYILAN YAPILMAZ: tibbi "
            "metinlerle egitildigi icin rezervasyon/fiyat baglaminda alakasiz veya "
            "yaniltici cikti uretir. Yalnizca revir/saglik notu gibi ozel bir kullanim "
            "icin ve kullanici acikca sectiginde devreye alinmalidir."
        ),
    ),
)

#: Tum bilinen modeller, kimlik -> kayit.
KNOWN_MODELS: Final[dict[str, ModelSpec]] = {spec.model_id: spec for spec in LMSTUDIO_MODELS}


# --------------------------------------------------------------------------
#  Rol onerileri
# --------------------------------------------------------------------------
#: LM Studio icin yetenek -> onerilen model.
LMSTUDIO_ROLE_MODELS: Final[dict[AICapability, str]] = {
    AICapability.CHAT: GEMMA_CHAT_MODEL,
    AICapability.REASONING: GEMMA_CHAT_MODEL,
    AICapability.CODE: GEMMA_CHAT_MODEL,
    AICapability.VISION: QWEN_VISION_MODEL,
    AICapability.MATH: QWEN_MATH_MODEL,
    AICapability.EMBEDDING: NOMIC_EMBED_MODEL,
}

#: Dusuk donanim / toplu is icin hafif gorsel alternatif.
LMSTUDIO_LIGHT_VISION_MODEL: Final[str] = MOONDREAM_VISION_MODEL

#: Gorev turu -> gereken temel yetenek.
TASK_CAPABILITY: Final[dict[AITaskType, AICapability]] = {
    AITaskType.GENERAL_CHAT: AICapability.CHAT,
    AITaskType.DAILY_SUMMARY: AICapability.CHAT,
    AITaskType.OCCUPANCY_ANALYSIS: AICapability.MATH,
    AITaskType.DEMAND_FORECAST: AICapability.MATH,
    AITaskType.PRICING_SUGGESTION: AICapability.MATH,
    AITaskType.REVIEW_CLASSIFICATION: AICapability.CHAT,
    AITaskType.SENTIMENT_ANALYSIS: AICapability.CHAT,
    AITaskType.MESSAGE_DRAFT: AICapability.CHAT,
    AITaskType.COMPLAINT_RESPONSE: AICapability.CHAT,
    AITaskType.TASK_SUGGESTION: AICapability.CHAT,
    AITaskType.MAINTENANCE_PATTERN: AICapability.CHAT,
    AITaskType.STOCK_FORECAST: AICapability.MATH,
    AITaskType.REPORT_SUMMARY: AICapability.CHAT,
    AITaskType.DOCUMENT_QA: AICapability.CHAT,
    AITaskType.NL_REPORT: AICapability.CHAT,
    AITaskType.DOCUMENT_VISION: AICapability.VISION,
    AITaskType.CODE_ASSIST: AICapability.CODE,
    AITaskType.EMBEDDING: AICapability.EMBEDDING,
}


def normalize_model_id(model_id: str) -> str:
    """Model kimligini karsilastirilabilir bicime getirir."""
    return (model_id or "").strip().lower()


def lookup(model_id: str) -> ModelSpec | None:
    """Katalogdaki kaydi dondurur; bilinmiyorsa ``None``."""
    normalized = normalize_model_id(model_id)
    if not normalized:
        return None
    for key, spec in KNOWN_MODELS.items():
        if normalize_model_id(key) == normalized:
            return spec
    return None


def capabilities_for(model_id: str) -> frozenset[AICapability]:
    """Modelin yetenekleri; bilinmiyorsa bos kume."""
    spec = lookup(model_id)
    return spec.capabilities if spec else frozenset()


def supports_reasoning(model_id: str) -> bool:
    """Model bir dusunme modeli mi?

    ``True`` ise ``max_tokens`` comert ayarlanmali ve ``reasoning_content``
    ayri saklanmalidir.
    """
    spec = lookup(model_id)
    return bool(spec and spec.supports_reasoning)


def context_window_for(model_id: str) -> int | None:
    spec = lookup(model_id)
    return spec.context_window if spec else None


def display_name_for(model_id: str) -> str:
    spec = lookup(model_id)
    return spec.display_name if spec else model_id


def is_recommended_default(model_id: str) -> bool:
    """Model otel senaryolarinda varsayilan yapilabilir mi?

    ``biomistral-7b`` icin ``False`` doner - saglik alani modelidir.
    """
    spec = lookup(model_id)
    return bool(spec and spec.recommended_default)


def estimate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Tahmini maliyet. Bilinmeyen ve yerel modellerde sifirdir."""
    spec = lookup(model_id)
    if spec is None:
        return _ZERO
    return spec.estimate_cost(prompt_tokens, completion_tokens)


def capability_for_task(task_type: AITaskType) -> AICapability:
    """Gorev turunun gerektirdigi yetenek."""
    return TASK_CAPABILITY.get(task_type, AICapability.CHAT)


def recommended_model_id(capability: AICapability) -> str:
    """LM Studio icin bir yetenegin onerilen modeli; yoksa bos metin."""
    return LMSTUDIO_ROLE_MODELS.get(capability, "")


def model_for_task(
    task_type: AITaskType,
    settings: AIProviderSettings | None = None,
) -> str:
    """Gorev turune uygun model kimligini secer.

    Once saglayici ayarlarindaki alan (``chat_model`` / ``vision_model`` /
    ``math_model`` / ``embed_model``) kullanilir; bos ise saglayicinin genel
    ``chat_model`` degerine duser.

    Dahili oneri listesi (:data:`LMSTUDIO_ROLE_MODELS`) **yalnizca LM Studio**
    icin devreye girer. Uzak saglayicilarda model adlari tamamen farklidir;
    ``google/gemma-4-12b-qat`` adini NVIDIA'ya gondermek kesin bir 404 uretir
    ve kullaniciyi yaniltir. Bu durumda bos metin doneriz - saglayici kendi
    varsayilanini kullanir ya da anlamli bir hata verir.
    """
    capability = capability_for_task(task_type)
    if settings is not None:
        field_name = {
            AICapability.VISION: "vision_model",
            AICapability.MATH: "math_model",
            AICapability.EMBEDDING: "embed_model",
        }.get(capability, "chat_model")
        configured = getattr(settings, field_name, "") or ""
        if configured:
            return configured
        if capability not in {AICapability.EMBEDDING, AICapability.VISION}:
            fallback = settings.chat_model or ""
            if fallback:
                return fallback
        if settings.provider is not ProviderName.LMSTUDIO:
            return ""
    return recommended_model_id(capability)


def models_for_provider(provider_type: AIProviderType) -> list[ModelSpec]:
    """Bir saglayiciya ait katalog kayitlari."""
    return [spec for spec in KNOWN_MODELS.values() if spec.provider_type is provider_type]


def recommended_models(provider_type: AIProviderType) -> list[ModelSpec]:
    """Varsayilan yapilabilir kayitlar (or. biomistral haric)."""
    return [spec for spec in models_for_provider(provider_type) if spec.recommended_default]


__all__ = [
    "BIOMISTRAL_MODEL",
    "GEMMA_CHAT_MODEL",
    "KNOWN_MODELS",
    "LMSTUDIO_LIGHT_VISION_MODEL",
    "LMSTUDIO_MODELS",
    "LMSTUDIO_ROLE_MODELS",
    "MOONDREAM_VISION_MODEL",
    "NOMIC_EMBED_MODEL",
    "QWEN_MATH_MODEL",
    "QWEN_VISION_MODEL",
    "TASK_CAPABILITY",
    "ModelSpec",
    "capabilities_for",
    "capability_for_task",
    "context_window_for",
    "display_name_for",
    "estimate_cost",
    "is_recommended_default",
    "lookup",
    "model_for_task",
    "models_for_provider",
    "normalize_model_id",
    "recommended_model_id",
    "recommended_models",
    "supports_reasoning",
]
