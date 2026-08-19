"""Yapay zeka katmaninin veri tasiyicilari.

Tasarim ilkesi
--------------
Bu modul **framework bagimsizdir**: ``httpx``, ``SQLAlchemy`` veya ``PySide6``
import etmez. Boylece saglayici adaptorleri, servis katmani ve arayuz ayni sade
yapilar uzerinde konusur; bir saglayicinin ham yaniti (:attr:`ChatResponse.raw`)
disinda saglayiciya ozgu hicbir bicim ust katmanlara sizmaz.

Tuzak: dusunme (reasoning) modelleri
------------------------------------
``google/gemma-4-12b-qat`` gibi dusunme modelleri, gorunur cevabin yani sira
ayri bir "akil yurutme" metni uretir. Bu metin **kullaniciya gosterilmemelidir**
ama jeton olarak faturalandirilir ve baglam penceresini doldurur. Bu yuzden
:class:`ChatResponse` iki ayri alan tutar: :attr:`~ChatResponse.content`
(gosterilecek) ve :attr:`~ChatResponse.reasoning` (yalnizca hata ayiklama /
denetim icin). Ayni sebeple :attr:`~ChatResponse.reasoning_tokens` ayri sayilir;
maliyet hesabi bu jetonlari yok sayarsa gercek gideri oldugundan dusuk gosterir.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.enums import AICapability

#: Sohbet mesajinin rolu. ``tool`` yalnizca arac cagrisi sonuclarinda kullanilir.
MessageRole = Literal["system", "user", "assistant", "tool"]

#: Saglayicidan bagimsiz, normallestirilmis bitis nedenleri.
#: OpenAI ``finish_reason`` degerleri temel alinir; Anthropic ``stop_reason``
#: degerleri :mod:`app.ai.providers.anthropic` icinde bunlara cevrilir.
FINISH_STOP: str = "stop"
FINISH_LENGTH: str = "length"
FINISH_TOOL_CALLS: str = "tool_calls"
FINISH_CONTENT_FILTER: str = "content_filter"


# --------------------------------------------------------------------------
#  Istek
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Tek bir sohbet mesaji.

    ``frozen`` secilmesi bilinclidir: ayni mesaj listesi birden fazla saglayiciya
    (birincil + yedek) gonderilir. Degistirilebilir olsaydi bir adaptorun yaptigi
    kucuk bir duzeltme digerinin istegini de bozardi.
    """

    role: MessageRole
    content: str
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> ChatMessage:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str, *, name: str | None = None) -> ChatMessage:
        return cls(role="user", content=content, name=name)

    @classmethod
    def assistant(cls, content: str) -> ChatMessage:
        return cls(role="assistant", content=content)

    def to_openai_dict(self) -> dict[str, str]:
        """OpenAI uyumlu ``messages`` ogesi."""
        payload: dict[str, str] = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        return payload


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """Saglayiciya gonderilecek sohbet istegi.

    ``model`` bos birakilabilir; bu durumda saglayici kendi varsayilanini ya da
    :mod:`app.ai.registry` gorev turune gore secilen modeli doldurur. Degisiklik
    icin ``dataclasses.replace`` kullanin - nesne dondurulmustur.
    """

    messages: list[ChatMessage]
    model: str = ""
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout: float = 120.0
    json_schema: dict[str, Any] | None = None
    stop: list[str] | None = None
    extra: dict[str, Any] | None = None

    @property
    def system_prompt(self) -> str:
        """Tum sistem mesajlarini birlestirir (Anthropic ayri parametre ister)."""
        return "\n\n".join(m.content for m in self.messages if m.role == "system").strip()

    @property
    def conversation(self) -> list[ChatMessage]:
        """Sistem mesajlari haric kalan mesajlar."""
        return [m for m in self.messages if m.role != "system"]

    @property
    def last_user_content(self) -> str:
        for message in reversed(self.messages):
            if message.role == "user":
                return message.content
        return ""

    def to_openai_messages(self) -> list[dict[str, str]]:
        return [m.to_openai_dict() for m in self.messages]


# --------------------------------------------------------------------------
#  Yanit
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChatResponse:
    """Saglayicidan bagimsiz sohbet yaniti."""

    content: str
    reasoning: str = ""
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = ""
    used_fallback: bool = False
    raw: dict[str, Any] | None = None

    @property
    def is_empty(self) -> bool:
        """Gorunur icerik yok mu?

        Dusunme modellerinde ``content`` bos ama ``reasoning`` dolu olabilir;
        bu yine de "bos yanit" sayilir cunku kullaniciya gosterilecek bir sey
        yoktur.
        """
        return not self.content.strip()

    @property
    def has_reasoning(self) -> bool:
        return bool(self.reasoning.strip()) or self.reasoning_tokens > 0

    @property
    def truncated_while_reasoning(self) -> bool:
        """Model, cevap uretmeden dusunme asamasinda jeton sinirina mi carpti?

        ``max_tokens`` dusuk verildiginde (or. 60) dusunme modeli tum butceyi
        akil yurutmede harcar ve ``content`` bos doner. Bu sessizce yutulmamali,
        anlamli bir hataya cevrilmelidir - bkz. :mod:`app.ai.errors`.
        """
        return self.finish_reason == FINISH_LENGTH and self.is_empty

    @property
    def visible_tokens(self) -> int:
        """Kullaniciya donen metnin jeton sayisi (dusunme jetonlari haric)."""
        return max(0, self.completion_tokens - self.reasoning_tokens)


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Saglayici katalogundaki tek bir model."""

    id: str
    name: str = ""
    capabilities: frozenset[AICapability] = field(default=frozenset())
    context_window: int | None = None
    supports_reasoning: bool = False

    @property
    def display_name(self) -> str:
        return self.name or self.id

    def supports(self, capability: AICapability) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    """Gomme (embedding) yaniti."""

    vectors: list[list[float]]
    model: str = ""
    tokens: int = 0

    @property
    def dimension(self) -> int:
        """Vektor boyutu; bos yanitta 0."""
        return len(self.vectors[0]) if self.vectors else 0

    def __len__(self) -> int:
        return len(self.vectors)


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Bir saglayicinin erisilebilirlik durumu.

    Saglik kontrolu **hata firlatmaz**; arayuzde bir gosterge olarak
    kullanildigi icin basarisizlik da gecerli bir sonuctur.

    :attr:`models_found` bir **sayidir**, :attr:`model_ids` ise adlarin
    kendisidir. Ikisi ayri tutulur cunku arayuzdeki durum rozeti yalnizca sayiyi
    ister, ``check-ai`` teshis ciktisi ise "hangi modeller yuklu" sorusunu
    yanitlamak zorundadir - kullanicinin Ayarlar'daki model adini duzeltebilmesi
    icin listenin gorunmesi gerekir.
    """

    ok: bool
    message: str = ""
    latency_ms: int = 0
    models_found: int = 0
    model_ids: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Arayuzde gosterilecek kisa etiket."""
        return "Calisiyor" if self.ok else "Ulasilamiyor"


def normalize_text_sequence(texts: Sequence[str] | str) -> list[str]:
    """Tek metin ya da metin dizisini her zaman listeye cevirir.

    ``embed("tek metin")`` cagrisinin sessizce karakter karakter gomulmesini
    onler - bu, kolayca gozden kacan ve cok pahaliya mal olan bir hatadir.
    """
    if isinstance(texts, str):
        return [texts]
    return [str(item) for item in texts]


__all__ = [
    "FINISH_CONTENT_FILTER",
    "FINISH_LENGTH",
    "FINISH_STOP",
    "FINISH_TOOL_CALLS",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "EmbeddingResponse",
    "HealthStatus",
    "MessageRole",
    "ModelInfo",
    "normalize_text_sequence",
]
