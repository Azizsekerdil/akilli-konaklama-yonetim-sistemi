"""OpenAI uyumlu saglayicilar icin ortak adaptor.

LM Studio, NVIDIA NIM, OpenAI ve benzeri servisler ayni uc noktalari sunar::

    POST {base_url}/chat/completions
    GET  {base_url}/models
    POST {base_url}/embeddings

Dusunme (reasoning) modelleri
-----------------------------
Bazi modeller - kullanicinin LM Studio kurulumundaki ``google/gemma-4-12b-qat``
dahil - yaniti iki parcada doner::

    choices[0].message.content            -> kullaniciya gosterilecek metin
    choices[0].message.reasoning_content  -> akil yurutme (gosterilmez)
    usage.completion_tokens_details.reasoning_tokens -> harcanan dusunme jetonu

Bu alan OpenAI'nin resmi semasinda yoktur; LM Studio, DeepSeek ve vLLM gibi
sunucular ekler. Adaptor bunu :attr:`ChatResponse.reasoning` alanina ayirir.

**En onemli tuzak:** ``max_tokens`` dusuk verildiginde model tum butceyi
dusunmede harcar, ``content`` bos string doner ve ``finish_reason`` degeri
``"length"`` olur. Bu durumu sessizce bos yanit olarak gecmek kabul edilemez -
kullanici "yapay zeka cevap vermedi" gorur ve nedenini asla ogrenemez. Bu
yuzden :func:`app.ai.errors.empty_reasoning_response_error` ile acik bir hata
ve "max_tokens degerini artirin" onerisi uretilir.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, ClassVar

from app.ai import catalog
from app.ai.base import AIProvider, extract_json_object, validate_json_schema
from app.ai.errors import empty_reasoning_response_error, json_format_error
from app.ai.types import (
    ChatRequest,
    ChatResponse,
    EmbeddingResponse,
    HealthStatus,
    ModelInfo,
    normalize_text_sequence,
)
from app.core.exceptions import AIProviderError
from app.core.log import get_logger
from app.domain.enums import AICapability, AIProviderType

log = get_logger(__name__)

#: 400 yanitinda bu ifadelerden biri geciyorsa saglayici JSON modunu
#: desteklemiyor demektir; istem tabanli yonteme duseriz.
_JSON_MODE_HINTS: tuple[str, ...] = (
    "response_format",
    "json_object",
    "json_schema",
    "not supported",
    "unsupported",
    "unrecognized",
)


class OpenAICompatibleProvider(AIProvider):
    """OpenAI uyumlu bir HTTP servisi icin adaptor."""

    name: ClassVar[str] = "openai"
    is_local: ClassVar[bool] = False
    provider_type: ClassVar[AIProviderType] = AIProviderType.OPENAI

    CHAT_PATH: ClassVar[str] = "/chat/completions"
    MODELS_PATH: ClassVar[str] = "/models"
    EMBEDDINGS_PATH: ClassVar[str] = "/embeddings"

    #: Saglayici ``response_format`` destekliyor mu? Ilk 400 yanitinda kapatilir.
    supports_json_mode: ClassVar[bool] = True

    def __init__(
        self,
        *,
        chat_model: str = "",
        embed_model: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        settings = self.settings
        self.chat_model = chat_model or (settings.chat_model if settings else "")
        self.embed_model = embed_model or (settings.embed_model if settings else "")
        self._json_mode_available = self.supports_json_mode

    # ---------------- Sohbet ----------------
    def resolve_model(self, request: ChatRequest) -> str:
        """Istekte model belirtilmemisse saglayici varsayilanini kullanir."""
        return request.model or self.chat_model

    def build_chat_payload(self, request: ChatRequest, *, json_mode: bool) -> dict[str, Any]:
        """Istegi OpenAI govdesine cevirir."""
        payload: dict[str, Any] = {
            "model": self.resolve_model(request),
            "messages": request.to_openai_messages(),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.stop:
            payload["stop"] = list(request.stop)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.extra:
            payload.update(request.extra)
        return payload

    def chat(self, request: ChatRequest) -> ChatResponse:
        return self._chat(request, json_mode=False)

    def _chat(self, request: ChatRequest, *, json_mode: bool) -> ChatResponse:
        model = self.resolve_model(request)
        payload = self.build_chat_payload(request, json_mode=json_mode)
        started = time.perf_counter()
        data = self._request(
            "POST",
            self.CHAT_PATH,
            payload=payload,
            timeout=request.timeout,
            model=model,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return self.parse_chat_response(data, model=model, request=request, latency_ms=latency_ms)

    def parse_chat_response(
        self,
        data: dict[str, Any],
        *,
        model: str,
        request: ChatRequest,
        latency_ms: int,
    ) -> ChatResponse:
        """Ham OpenAI yanitini :class:`ChatResponse` nesnesine cevirir."""
        choices = data.get("choices") or []
        if not choices:
            raise json_format_error(
                provider=self.name,
                detail="Yanitta 'choices' alani bos.",
                model=model,
            )

        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}
        content = str(message.get("content") or "")
        # LM Studio/DeepSeek 'reasoning_content', bazi sunucular yalnizca
        # 'reasoning' adini kullanir. Ikisini de destekliyoruz.
        reasoning = str(message.get("reasoning_content") or message.get("reasoning") or "")
        finish_reason = str(choice.get("finish_reason") or "")

        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = _as_int(details.get("reasoning_tokens"))
        prompt_tokens = _as_int(usage.get("prompt_tokens"))
        completion_tokens = _as_int(usage.get("completion_tokens"))

        # OpenAI semasinda reasoning_tokens, completion_tokens'in ALT KUMESIDIR.
        # Ancak bazi yerel sunucular yalnizca gorunur jetonlari sayar; bu durumda
        # dusunme jetonlarini eklemezsek maliyet oldugundan dusuk cikar.
        if reasoning_tokens > completion_tokens:
            completion_tokens += reasoning_tokens

        reported_total = _as_int(usage.get("total_tokens"))
        total_tokens = max(reported_total, prompt_tokens + completion_tokens)

        response = ChatResponse(
            content=content,
            reasoning=reasoning,
            model=str(data.get("model") or model),
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            raw=data,
        )

        if response.truncated_while_reasoning:
            raise empty_reasoning_response_error(
                provider=self.name,
                model=response.model,
                max_tokens=request.max_tokens,
                reasoning_tokens=reasoning_tokens,
            )
        if response.is_empty:
            # finish_reason 'stop' ise model gercekten bos donmustur; hata degil
            # ama gorunur bir uyaridir - sessizce gecilirse teshis imkansizlasir.
            log.warning(
                "ai_bos_yanit",
                provider=self.name,
                model=response.model,
                finish_reason=finish_reason,
                reasoning_tokens=reasoning_tokens,
            )
        return response

    # ---------------- JSON ----------------
    def chat_json(
        self,
        request: ChatRequest,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """JSON modu ile, desteklenmiyorsa istem talimati ile JSON uretir."""
        effective_schema = schema if schema is not None else request.json_schema
        prepared = self._with_json_instruction(request, effective_schema)

        if self._json_mode_available:
            try:
                response = self._chat(prepared, json_mode=True)
            except AIProviderError as exc:
                if not _is_json_mode_rejection(exc):
                    raise
                # Saglayici response_format bilmiyor: bir daha denemeyelim.
                log.info("ai_json_modu_desteklenmiyor", provider=self.name)
                self._json_mode_available = False
                response = self._chat(prepared, json_mode=False)
        else:
            response = self._chat(prepared, json_mode=False)

        data = extract_json_object(response.content, provider=self.name)
        return validate_json_schema(data, effective_schema, provider=self.name)

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

    def available_model_ids(self) -> list[str]:
        """Yalnizca model kimlikleri. Hata mesajlarini zenginlestirmek icin."""
        return [model.id for model in self.list_models()]

    def _parse_model(self, item: dict[str, Any]) -> ModelInfo:
        model_id = str(item.get("id") or "")
        spec = catalog.lookup(model_id)
        capabilities = spec.capabilities if spec else frozenset({AICapability.CHAT})
        context_window = _as_optional_int(
            item.get("context_length")
            or item.get("max_context_length")
            or item.get("max_input_tokens")
        )
        if context_window is None and spec is not None:
            context_window = spec.context_window
        return ModelInfo(
            id=model_id,
            name=str(item.get("display_name") or (spec.display_name if spec else model_id)),
            capabilities=capabilities,
            context_window=context_window,
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
            # Ad listesi teshis icin sarttir: kullanici Ayarlar'daki yanlis model
            # adini ancak dogrusunu gorurse duzeltebilir.
            model_ids=tuple(model.id for model in models),
        )

    # ---------------- Gomme ----------------
    def embed(
        self,
        texts: Sequence[str] | str,
        model: str | None = None,
    ) -> EmbeddingResponse:
        items = normalize_text_sequence(texts)
        if not items:
            return EmbeddingResponse(vectors=[], model=model or self.embed_model, tokens=0)

        target = model or self.embed_model
        data = self._request(
            "POST",
            self.EMBEDDINGS_PATH,
            payload={"model": target, "input": items},
            model=target,
        )
        rows = data.get("data")
        if not isinstance(rows, list):
            raise json_format_error(
                provider=self.name,
                detail="Gomme yanitinda 'data' dizisi yok.",
                model=target,
            )
        # Saglayici sirayi garanti etmez; 'index' alanina gore siralanir.
        ordered = sorted(
            (row for row in rows if isinstance(row, dict)),
            key=lambda row: _as_int(row.get("index")),
        )
        vectors = [[float(value) for value in (row.get("embedding") or [])] for row in ordered]
        usage = data.get("usage") or {}
        tokens = _as_int(usage.get("prompt_tokens")) or _as_int(usage.get("total_tokens"))
        return EmbeddingResponse(
            vectors=vectors,
            model=str(data.get("model") or target),
            tokens=tokens,
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


def _is_json_mode_rejection(error: AIProviderError) -> bool:
    """400 yaniti ``response_format`` yuzunden mi geldi?"""
    if error.context.get("status_code") != 400:
        return False
    detail = (error.detail or "").lower()
    return any(hint in detail for hint in _JSON_MODE_HINTS)


__all__ = ["OpenAICompatibleProvider"]
