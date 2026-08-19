"""Sahte (mock) saglayici - testler ve "yapay zeka kapali" durumu icin.

Iki isi vardir:

1. **Test edilebilirlik.** Ag cagrisi yapmadan, ayni girdiye her zaman ayni
   ciktiyi veren belirlenimci yanitlar uretir. Belirlenim ``random`` yerine
   SHA-256 ozetiyle saglanir; boylece test sonuclari makineden makineye ve
   calistirmadan calistirmaya degismez.
2. **Guvenli varsayilan.** ``HOTEL_AI_ENABLED=false`` oldugunda ya da yedek
   saglayici tanimli olmadiginda kayit (registry) bu adaptore duser. Boylece
   yapay zeka kapaliyken uygulama cokmez, yalnizca "yapay zeka devre disi"
   iceren bir yanit doner.

**Asla ag cagrisi yapmaz.** ``httpx`` istemcisi hic olusturulmaz.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from typing import Any, ClassVar, Final

from app.ai.base import AIProvider
from app.ai.types import (
    FINISH_STOP,
    ChatRequest,
    ChatResponse,
    EmbeddingResponse,
    HealthStatus,
    ModelInfo,
    normalize_text_sequence,
)
from app.domain.enums import AICapability, AIProviderType

#: Sahte modelin adi.
MOCK_MODEL: Final[str] = "mock-echo-1"
MOCK_EMBED_MODEL: Final[str] = "mock-embed-1"

#: Gomme vektorlerinin boyutu. Kucuk tutulur; testlerde okunabilirlik onemli.
MOCK_EMBED_DIM: Final[int] = 8

#: Yaklasik jeton tahmini icin karakter/jeton orani. Kaba ama belirlenimcidir.
_CHARS_PER_TOKEN: Final[int] = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN) if text else 0


class MockProvider(AIProvider):
    """Belirlenimci, ag kullanmayan saglayici."""

    name: ClassVar[str] = "mock"
    is_local: ClassVar[bool] = True
    provider_type: ClassVar[AIProviderType] = AIProviderType.MOCK

    def __init__(
        self,
        *,
        responses: Sequence[str] | None = None,
        reasoning: str = "",
        fail_with: BaseException | type[BaseException] | None = None,
        latency_ms: int = 0,
        sleep: bool = False,
        models: Sequence[str] | None = None,
        healthy: bool = True,
        **kwargs: Any,
    ) -> None:
        """
        Parameters
        ----------
        responses:
            Sirayla dondurulecek hazir yanitlar. Liste tukendiginde sonuncusu
            tekrarlanir. Verilmezse istemden turetilen belirlenimci metin uretilir.
        fail_with:
            Verilirse her ``chat`` cagrisinda firlatilir. Yedege gecis (fallback)
            senaryolarini test etmek icin.
        latency_ms:
            Raporlanan gecikme. ``sleep=True`` degilse gercekten beklenmez -
            testlerin yavaslamamasi icin varsayilan budur.
        """
        super().__init__(**kwargs)
        self.responses = list(responses or [])
        self.reasoning = reasoning
        self.fail_with = fail_with
        self.latency_ms = latency_ms
        self.sleep = sleep
        self.model_ids = list(models or [MOCK_MODEL, MOCK_EMBED_MODEL])
        self.healthy = healthy
        #: Yapilan cagrilarin kaydi - testlerde dogrulama icin.
        self.calls: list[ChatRequest] = []
        self.embed_calls: list[list[str]] = []

    # ---------------- Yardimcilar ----------------
    @staticmethod
    def digest(text: str) -> str:
        """Istemin kisa, belirlenimci ozeti."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]

    def _raise_if_configured(self) -> None:
        if self.fail_with is None:
            return
        if isinstance(self.fail_with, BaseException):
            raise self.fail_with
        raise self.fail_with()

    def _simulate_latency(self) -> None:
        if self.sleep and self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000)

    def _build_content(self, request: ChatRequest) -> str:
        if self.responses:
            index = min(len(self.calls) - 1, len(self.responses) - 1)
            return self.responses[index]
        prompt = request.last_user_content
        return f"[mock:{self.digest(prompt)}] {prompt}".strip()

    # ---------------- Sozlesme ----------------
    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        self._raise_if_configured()
        self._simulate_latency()

        content = self._build_content(request)
        prompt_text = "\n".join(message.content for message in request.messages)
        prompt_tokens = _estimate_tokens(prompt_text)
        reasoning_tokens = _estimate_tokens(self.reasoning)
        completion_tokens = _estimate_tokens(content) + reasoning_tokens
        return ChatResponse(
            content=content,
            reasoning=self.reasoning,
            model=request.model or MOCK_MODEL,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=self.latency_ms,
            finish_reason=FINISH_STOP,
            raw={"mock": True},
        )

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=model_id,
                name=model_id,
                capabilities=frozenset(
                    {AICapability.EMBEDDING}
                    if "embed" in model_id
                    else {AICapability.CHAT, AICapability.JSON_MODE}
                ),
                context_window=8192,
                supports_reasoning=False,
            )
            for model_id in self.model_ids
        ]

    def health_check(self) -> HealthStatus:
        return HealthStatus(
            ok=self.healthy,
            message=(
                "Sahte sağlayıcı hazır (ağ kullanılmaz)."
                if self.healthy
                else "Sahte sağlayıcı kapalı olarak yapılandırıldı."
            ),
            latency_ms=self.latency_ms,
            models_found=len(self.model_ids) if self.healthy else 0,
            model_ids=tuple(self.model_ids) if self.healthy else (),
        )

    def embed(
        self,
        texts: Sequence[str] | str,
        model: str | None = None,
    ) -> EmbeddingResponse:
        items = normalize_text_sequence(texts)
        self.embed_calls.append(items)
        self._raise_if_configured()
        vectors = [self._vector(text) for text in items]
        return EmbeddingResponse(
            vectors=vectors,
            model=model or MOCK_EMBED_MODEL,
            tokens=sum(_estimate_tokens(text) for text in items),
        )

    @staticmethod
    def _vector(text: str) -> list[float]:
        """Metinden belirlenimci, [-1, 1] araliginda bir vektor uretir."""
        raw = hashlib.sha256(text.encode("utf-8")).digest()
        return [(raw[index] - 128) / 128 for index in range(MOCK_EMBED_DIM)]

    def close(self) -> None:
        """Ag kaynagi yok; yine de sozlesmeyi bozmadan uygulariz."""
        return None


__all__ = ["MOCK_EMBED_DIM", "MOCK_EMBED_MODEL", "MOCK_MODEL", "MockProvider"]
