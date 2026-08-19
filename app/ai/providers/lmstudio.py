"""LM Studio yerel sunucusu adaptoru.

LM Studio, ``http://127.0.0.1:1234/v1`` adresinde OpenAI uyumlu bir sunucu
calistirir. Yerel oldugu icin:

* **API anahtari gerektirmez.** Anahtar alani doldurulmussa gonderilir (LM Studio
  surumlerinde istege bagli erisim anahtari tanimlanabilir), bos ise
  ``Authorization`` basligi hic eklenmez.
* **Maliyeti sifirdir** ve misafir verisi hicbir zaman kurum disina cikmaz;
  KVKK acisindan tercih edilen saglayicidir.
* **Yalnizca yuklu modeller** kullanilabilir. Kullanici Ayarlar'da eski bir
  model adi biraktiysa sunucu 404 doner. Bu durumda hata mesaji tek basina
  ise yaramaz - kullanicinin *hangi modellerin mevcut oldugunu* gormesi gerekir.
  Bu yuzden 404 yakalanip ``/v1/models`` ciktisiyla zenginlestirilir.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.ai.errors import REMEDY_MODEL_NOT_FOUND
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.ai.types import ChatRequest, ChatResponse, ModelInfo
from app.core.config import LMStudioSettings
from app.core.exceptions import AIModelNotFoundError, AIProviderError
from app.core.log import get_logger
from app.domain.enums import AIProviderType

log = get_logger(__name__)


class LMStudioProvider(OpenAICompatibleProvider):
    """LM Studio (yerel, OpenAI uyumlu) adaptoru."""

    name: ClassVar[str] = "lmstudio"
    is_local: ClassVar[bool] = True
    provider_type: ClassVar[AIProviderType] = AIProviderType.LMSTUDIO

    def __init__(self, *, settings: LMStudioSettings | None = None, **kwargs: Any) -> None:
        resolved = settings if settings is not None else LMStudioSettings()
        super().__init__(settings=resolved, **kwargs)
        self.vision_model = resolved.vision_model
        self.math_model = resolved.math_model

    def _resolve_api_key(self) -> str | None:
        """Yerel sunucu anahtar dogrulamaz; yer tutucu deger gonderilmez.

        ``LMStudioSettings.api_key`` varsayilani ``"lm-studio"`` yer tutucusudur.
        Bunu ``Authorization`` basligi olarak gondermek zararsizdir ama gereksiz
        gurultu yaratir ve loglarda "anahtar var" izlenimi uretir; bu yuzden
        yalnizca kullanici gercekten farkli bir deger girdiyse gonderilir.
        """
        key = super()._resolve_api_key()
        if not key or key == "lm-studio":
            return None
        return key

    # ---------------- Model dogrulama ----------------
    def ensure_model(self, model_id: str) -> None:
        """Model sunucuda yuklu degilse anlamli bir hata firlatir."""
        available = self.available_model_ids()
        if model_id in available:
            return
        raise self._model_not_found(model_id, available)

    def _model_not_found(self, model_id: str, available: list[str]) -> AIModelNotFoundError:
        listed = ", ".join(available) if available else "(sunucuda yuklu model yok)"
        return AIModelNotFoundError(
            f"'{model_id}' modeli LM Studio'da yüklü değil.",
            provider=self.name,
            remedy=(
                f"{REMEDY_MODEL_NOT_FOUND} Şu an yüklü modeller: {listed}"
                if available
                else "LM Studio'da hiç model yüklü değil. Uygulamadan bir model indirip yükleyin."
            ),
            detail=f"model={model_id} available={available}",
            context={"model": model_id, "available_models": available},
        )

    def _enrich_model_error(self, error: AIProviderError, model_id: str) -> AIProviderError:
        """404 hatasini mevcut model listesiyle zenginlestirir.

        Liste alinamazsa (sunucu bu arada kapandiysa) ozgun hata korunur;
        teshis bilgisi ugruna asil hatayi kaybetmek daha kotu olurdu.
        """
        try:
            available = self.available_model_ids()
        except AIProviderError:
            return error
        return self._model_not_found(model_id, available)

    def _chat(self, request: ChatRequest, *, json_mode: bool) -> ChatResponse:
        """Tum sohbet yollarinin (``chat`` ve ``chat_json``) ortak gecidi.

        Zenginlestirme burada yapilir - ``chat()`` uzerinde yapilsaydi
        ``chat_json()`` dogrudan ``_chat()`` cagirdigi icin JSON yolunda
        model listesi hataya eklenmezdi.
        """
        model = self.resolve_model(request)
        try:
            return super()._chat(request, json_mode=json_mode)
        except AIModelNotFoundError as exc:
            raise self._enrich_model_error(exc, model) from exc

    def list_models(self) -> list[ModelInfo]:
        models = super().list_models()
        log.debug("lmstudio_model_listesi", count=len(models))
        return models


__all__ = ["LMStudioProvider"]
