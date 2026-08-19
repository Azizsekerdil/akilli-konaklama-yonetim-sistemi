"""Anthropic Claude (Messages API) adaptoru.

Bu sema OpenAI'den **onemli olcude farklidir** ve donusum bu adaptorun asil
isidir:

===================  =========================  ================================
Konu                 OpenAI                     Anthropic
===================  =========================  ================================
Uc nokta             ``/chat/completions``      ``/messages``
Kimlik dogrulama     ``Authorization: Bearer``  ``x-api-key`` basligi
Surum                yok                        ``anthropic-version`` basligi
Sistem istemi        ``messages`` icinde rol    ayri ``system`` parametresi
``max_tokens``       istege bagli               **ZORUNLU**
Yanit govdesi        ``choices[0].message``     ``content`` blok listesi
Dusunme metni        ``reasoning_content``      ``{"type": "thinking"}`` blogu
Jeton alanlari       ``prompt/completion``      ``input_tokens/output_tokens``
Bitis nedeni         ``finish_reason``          ``stop_reason``
Gomme                ``/embeddings``            **yok**
===================  =========================  ================================

Ayrica ``messages`` dizisi bos olamaz ve ``system`` disinda yalnizca
``user``/``assistant`` rolleri kabul edilir; ``tool`` rolundeki mesajlar
``user`` olarak gonderilir.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, ClassVar, Final

from app.ai import catalog
from app.ai.base import AIProvider
from app.ai.errors import (
    REMEDY_NO_EMBEDDING,
    empty_reasoning_response_error,
    json_format_error,
    unsupported_capability_error,
)
from app.ai.types import (
    FINISH_CONTENT_FILTER,
    FINISH_LENGTH,
    FINISH_STOP,
    FINISH_TOOL_CALLS,
    ChatRequest,
    ChatResponse,
    EmbeddingResponse,
    HealthStatus,
    ModelInfo,
)
from app.core.config import AnthropicSettings
from app.core.exceptions import AIProviderError, ValidationError
from app.core.log import get_logger
from app.domain.enums import AICapability, AIProviderType

log = get_logger(__name__)

#: Anthropic ``stop_reason`` -> normallestirilmis bitis nedeni.
_STOP_REASON_MAP: Final[dict[str, str]] = {
    "end_turn": FINISH_STOP,
    "stop_sequence": FINISH_STOP,
    "max_tokens": FINISH_LENGTH,
    "tool_use": FINISH_TOOL_CALLS,
    "pause_turn": FINISH_TOOL_CALLS,
    "refusal": FINISH_CONTENT_FILTER,
}


class AnthropicProvider(AIProvider):
    """Anthropic Messages API adaptoru."""

    name: ClassVar[str] = "anthropic"
    is_local: ClassVar[bool] = False
    provider_type: ClassVar[AIProviderType] = AIProviderType.ANTHROPIC

    DEFAULT_BASE_URL: ClassVar[str] = "https://api.anthropic.com/v1"
    #: ``anthropic-version`` basligi. Sabittir; surum atlamak kirilma yaratir.
    API_VERSION: ClassVar[str] = "2023-06-01"

    MESSAGES_PATH: ClassVar[str] = "/messages"
    MODELS_PATH: ClassVar[str] = "/models"

    def __init__(
        self,
        *,
        settings: AnthropicSettings | None = None,
        chat_model: str = "",
        **kwargs: Any,
    ) -> None:
        resolved = settings if settings is not None else AnthropicSettings()
        super().__init__(settings=resolved, **kwargs)
        if not self.base_url:
            self.base_url = self.DEFAULT_BASE_URL
        self.chat_model = chat_model or resolved.chat_model

    # ---------------- Basliklar ----------------
    def _headers(self) -> dict[str, str]:
        """Anthropic ``Authorization`` degil ``x-api-key`` bekler."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": self.API_VERSION,
        }
        key = self._resolve_api_key()
        if key:
            headers["x-api-key"] = key
        headers.update(self.extra_headers)
        return headers

    # ---------------- Sohbet ----------------
    def resolve_model(self, request: ChatRequest) -> str:
        return request.model or self.chat_model

    def build_payload(self, request: ChatRequest) -> dict[str, Any]:
        """Istegi Anthropic Messages govdesine cevirir."""
        conversation = request.conversation
        if not conversation:
            raise ValidationError(
                "Yapay zekaya gönderilecek en az bir kullanıcı mesajı gerekir.",
                field="messages",
                detail="Anthropic /v1/messages bos 'messages' dizisini reddeder.",
            )

        payload: dict[str, Any] = {
            "model": self.resolve_model(request),
            # max_tokens Anthropic'te ZORUNLUDUR; eksikse 400 doner.
            "max_tokens": request.max_tokens,
            "messages": [
                {
                    "role": "assistant" if message.role == "assistant" else "user",
                    "content": message.content,
                }
                for message in conversation
            ],
            "temperature": request.temperature,
        }
        system_prompt = request.system_prompt
        if system_prompt:
            # Sistem istemi mesaj listesinde DEGIL, ayri bir alandadir.
            payload["system"] = system_prompt
        if request.stop:
            payload["stop_sequences"] = list(request.stop)
        if request.extra:
            payload.update(request.extra)
        return payload

    def chat(self, request: ChatRequest) -> ChatResponse:
        model = self.resolve_model(request)
        payload = self.build_payload(request)
        started = time.perf_counter()
        data = self._request(
            "POST",
            self.MESSAGES_PATH,
            payload=payload,
            timeout=request.timeout,
            model=model,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return self.parse_response(data, model=model, request=request, latency_ms=latency_ms)

    def parse_response(
        self,
        data: dict[str, Any],
        *,
        model: str,
        request: ChatRequest,
        latency_ms: int,
    ) -> ChatResponse:
        """Icerik bloklarini tek bir metne ve akil yurutme metnine ayirir."""
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise json_format_error(
                provider=self.name,
                detail="Yanitta 'content' blok listesi yok.",
                model=model,
            )

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block_type in {"thinking", "redacted_thinking"}:
                thinking_parts.append(str(block.get("thinking") or ""))

        stop_reason = str(data.get("stop_reason") or "")
        finish_reason = _STOP_REASON_MAP.get(stop_reason, stop_reason)

        usage = data.get("usage") or {}
        prompt_tokens = _as_int(usage.get("input_tokens"))
        completion_tokens = _as_int(usage.get("output_tokens"))
        # Anthropic dusunme jetonlarini ayri saymaz; output_tokens icinde
        # gelirler. Ayri bir alan olmadigi icin 0 birakilir - toplam yine dogru.
        response = ChatResponse(
            content="".join(text_parts),
            reasoning="\n".join(part for part in thinking_parts if part),
            model=str(data.get("model") or model),
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=0,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            raw=data,
        )

        if response.truncated_while_reasoning:
            raise empty_reasoning_response_error(
                provider=self.name,
                model=response.model,
                max_tokens=request.max_tokens,
                reasoning_tokens=response.completion_tokens,
            )
        if response.is_empty:
            log.warning(
                "ai_bos_yanit",
                provider=self.name,
                model=response.model,
                finish_reason=finish_reason,
                stop_reason=stop_reason,
            )
        return response

    # ---------------- Modeller ----------------
    def list_models(self) -> list[ModelInfo]:
        data = self._request("GET", self.MODELS_PATH)
        items = data.get("data")
        if not isinstance(items, list):
            raise json_format_error(
                provider=self.name,
                detail="Model listesinde 'data' dizisi yok.",
            )
        return [self._parse_model(item) for item in items if isinstance(item, dict)]

    def _parse_model(self, item: dict[str, Any]) -> ModelInfo:
        model_id = str(item.get("id") or "")
        spec = catalog.lookup(model_id)
        return ModelInfo(
            id=model_id,
            name=str(item.get("display_name") or model_id),
            capabilities=(
                spec.capabilities
                if spec
                else frozenset({AICapability.CHAT, AICapability.VISION, AICapability.TOOL_USE})
            ),
            context_window=_as_optional_int(item.get("max_input_tokens")),
            supports_reasoning=bool(spec and spec.supports_reasoning),
        )

    # ---------------- Saglik ----------------
    def health_check(self) -> HealthStatus:
        started = time.perf_counter()
        try:
            models = self.list_models()
        except AIProviderError as exc:
            remedy = getattr(exc, "remedy", "") or ""
            return HealthStatus(
                ok=False,
                message=f"{exc.user_message} {remedy}".strip(),
                latency_ms=int((time.perf_counter() - started) * 1000),
                models_found=0,
            )
        return HealthStatus(
            ok=True,
            message=f"{len(models)} model bulundu.",
            latency_ms=int((time.perf_counter() - started) * 1000),
            models_found=len(models),
            model_ids=tuple(model.id for model in models),
        )

    # ---------------- Gomme ----------------
    def embed(
        self,
        texts: Sequence[str] | str,
        model: str | None = None,
    ) -> EmbeddingResponse:
        """Anthropic gomme ucu sunmaz; sessizce bos donmek yerine hata veririz."""
        raise unsupported_capability_error(
            provider=self.name,
            capability="embedding",
            remedy=REMEDY_NO_EMBEDDING,
        )


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["AnthropicProvider"]
