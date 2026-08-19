"""Yapay zeka katmani - saglayici adaptorleri, katalog ve yedekli calisma.

Katman sozlesmesi
-----------------
``app.ai`` **saf bir dis dunya adaptorudur**: veritabanina yazmaz, is kurali
uygulamaz, kullanici onayi istemez. Bunlarin hepsi servis katmaninin isidir.
Buradaki tek soz, "istegi gonder, normallestirilmis yaniti dondur, hata olursa
kullanicinin anlayacagi bir cozum onerisiyle bildir".

Hizli kullanim::

    from app.ai import ChatMessage, ChatRequest, get_registry

    request = ChatRequest(
        messages=[ChatMessage.user("Bugunku doluluk ozetini cikar")],
        max_tokens=1024,        # dusunme modelleri icin comert olun
    )
    response = get_registry().chat_with_fallback(request)
    print(response.content)     # reasoning ayri alanda, kullaniciya gosterilmez

Uyari
-----
Bu cagrilar **senkron**dur ve saniyelerce surebilir. PySide6 arayuzunden
dogrudan degil, bir is parcaciginda cagirin.
"""

from __future__ import annotations

from app.ai.base import AIProvider, extract_json_object, validate_json_schema
from app.ai.catalog import ModelSpec, estimate_cost, lookup, model_for_task
from app.ai.errors import format_error, is_retryable_status, map_status_code
from app.ai.providers import (
    AnthropicProvider,
    LMStudioProvider,
    MockProvider,
    NvidiaProvider,
    OpenAICompatibleProvider,
)
from app.ai.registry import ProviderRegistry, get_registry, reset_registry, should_fall_back
from app.ai.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbeddingResponse,
    HealthStatus,
    ModelInfo,
)

__all__ = [
    "AIProvider",
    "AnthropicProvider",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "EmbeddingResponse",
    "HealthStatus",
    "LMStudioProvider",
    "MockProvider",
    "ModelInfo",
    "ModelSpec",
    "NvidiaProvider",
    "OpenAICompatibleProvider",
    "ProviderRegistry",
    "estimate_cost",
    "extract_json_object",
    "format_error",
    "get_registry",
    "is_retryable_status",
    "lookup",
    "map_status_code",
    "model_for_task",
    "reset_registry",
    "should_fall_back",
    "validate_json_schema",
]
