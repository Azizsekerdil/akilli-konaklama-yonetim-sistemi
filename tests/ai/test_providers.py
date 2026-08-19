"""Saglayici adaptoru testleri - tamami sahte HTTP (respx) uzerinde.

Buradaki yanit govdeleri, kullanicinin gercek LM Studio kurulumundan alinan
ciktilarin sadelestirilmis kopyalaridir. Ozellikle ``google/gemma-4-12b-qat``
bir DUSUNME MODELIDIR ve ``reasoning_content`` alani dondurur; bu davranis
:class:`TestDusunmeModeli` altinda ayrintili olarak sinanir.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.ai.base import extract_json_object, validate_json_schema
from app.ai.catalog import GEMMA_CHAT_MODEL, NOMIC_EMBED_MODEL, QWEN_VISION_MODEL
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.lmstudio import LMStudioProvider
from app.ai.providers.mock import MOCK_EMBED_DIM, MockProvider
from app.ai.providers.nvidia import NvidiaProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.ai.types import ChatMessage, ChatRequest
from app.core.exceptions import (
    AIAuthenticationError,
    AIModelNotFoundError,
    AIProviderError,
    AIQuotaError,
    AIResponseFormatError,
    AITimeoutError,
    ValidationError,
)
from app.core.exceptions import AIConnectionError as ConnErr

pytestmark = pytest.mark.ai

BASE_URL = "http://127.0.0.1:1234/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"
MODELS_URL = f"{BASE_URL}/models"
EMBED_URL = f"{BASE_URL}/embeddings"

ANTHROPIC_BASE = "https://api.anthropic.test/v1"
ANTHROPIC_MESSAGES_URL = f"{ANTHROPIC_BASE}/messages"
ANTHROPIC_MODELS_URL = f"{ANTHROPIC_BASE}/models"


# --------------------------------------------------------------------------
#  Ornek govdeler
# --------------------------------------------------------------------------
def chat_payload(
    content: str = "Merhaba, size nasil yardimci olabilirim?",
    *,
    reasoning: str | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 24,
    completion_tokens: int = 12,
    reasoning_tokens: int | None = None,
    total_tokens: int | None = None,
    model: str = GEMMA_CHAT_MODEL,
) -> dict[str, Any]:
    """LM Studio ``/v1/chat/completions`` yanitinin sadelestirilmis kopyasi."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning

    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if total_tokens is not None:
        usage["total_tokens"] = total_tokens
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}

    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }


#: Kullanicinin sunucusunda gercekten yuklu olan alti model.
LMSTUDIO_MODELS_PAYLOAD: dict[str, Any] = {
    "object": "list",
    "data": [
        {"id": GEMMA_CHAT_MODEL, "object": "model", "owned_by": "organization_owner"},
        {"id": QWEN_VISION_MODEL, "object": "model", "owned_by": "organization_owner"},
        {"id": "biomistral-7b", "object": "model", "owned_by": "organization_owner"},
        {"id": "qwen2.5-math-7b-instruct", "object": "model", "owned_by": "organization_owner"},
        {"id": "moondream-2b-2025-04-14", "object": "model", "owned_by": "organization_owner"},
        {"id": NOMIC_EMBED_MODEL, "object": "model", "owned_by": "organization_owner"},
    ],
}


def istek(icerik: str = "Bugunku doluluk nedir?", **kwargs: Any) -> ChatRequest:
    kwargs.setdefault("model", GEMMA_CHAT_MODEL)
    kwargs.setdefault("max_tokens", 1024)
    return ChatRequest(messages=[ChatMessage.user(icerik)], **kwargs)


def yerel_saglayici(**kwargs: Any) -> LMStudioProvider:
    """Yeniden deneme beklemesi olmayan LM Studio adaptoru."""
    kwargs.setdefault("base_url", BASE_URL)
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("retry_backoff", 0.0)
    return LMStudioProvider(**kwargs)


# --------------------------------------------------------------------------
#  Temel sohbet
# --------------------------------------------------------------------------
class TestSohbet:
    @respx.mock
    def test_basarili_sohbet_icerigi_dondurur(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=chat_payload()))
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek())
        assert yanit.content.startswith("Merhaba")
        assert yanit.provider == "lmstudio"
        assert yanit.model == GEMMA_CHAT_MODEL
        assert yanit.finish_reason == "stop"
        assert not yanit.is_empty

    @respx.mock
    def test_jeton_sayilari_okunur(self):
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json=chat_payload(prompt_tokens=100, completion_tokens=40, total_tokens=140),
            )
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek())
        assert yanit.prompt_tokens == 100
        assert yanit.completion_tokens == 40
        assert yanit.total_tokens == 140

    @respx.mock
    def test_toplam_jeton_raporlanmazsa_hesaplanir(self):
        """Bazi sunucular ``total_tokens`` gondermez; kendimiz toplariz."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200, json=chat_payload(prompt_tokens=30, completion_tokens=7)
            )
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek())
        assert yanit.total_tokens == 37

    @respx.mock
    def test_istek_govdesi_beklenen_alanlari_tasir(self):
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=chat_payload()))
        with yerel_saglayici() as saglayici:
            saglayici.chat(istek("Selam", max_tokens=256, temperature=0.1))
        govde = route.calls.last.request.read().decode()
        assert '"model":"google/gemma-4-12b-qat"' in govde.replace(" ", "")
        assert '"max_tokens":256' in govde.replace(" ", "")
        assert '"stream":false' in govde.replace(" ", "")

    @respx.mock
    def test_choices_bos_ise_bicim_hatasi(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
        with yerel_saglayici() as saglayici, pytest.raises(AIResponseFormatError):
            saglayici.chat(istek())


# --------------------------------------------------------------------------
#  Dusunme (reasoning) modelleri - kritik davranis
# --------------------------------------------------------------------------
class TestDusunmeModeli:
    @respx.mock
    def test_reasoning_content_ayri_alanda_tutulur(self):
        """Akil yurutme metni ``content`` ile karistirilmamalidir."""
        akil_yurutme = "Kullanici kim oldugumu soruyor. Kisa ve durust yanit vermeliyim."
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json=chat_payload(
                    content="Ben, Google tarafindan egitilmis bir dil modeliyim.",
                    reasoning=akil_yurutme,
                    reasoning_tokens=322,
                    completion_tokens=340,
                ),
            )
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek("Sen kimsin?"))

        assert yanit.content == "Ben, Google tarafindan egitilmis bir dil modeliyim."
        assert yanit.reasoning == akil_yurutme
        # Akil yurutme metni kullaniciya gosterilen icerige SIZMAMALIDIR.
        assert "Kisa ve durust" not in yanit.content
        assert yanit.has_reasoning

    @respx.mock
    def test_reasoning_tokens_ayri_sayilir_ve_toplama_dahildir(self):
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json=chat_payload(
                    reasoning="uzun akil yurutme",
                    prompt_tokens=50,
                    completion_tokens=340,
                    reasoning_tokens=322,
                ),
            )
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek())

        assert yanit.reasoning_tokens == 322
        assert yanit.completion_tokens == 340
        assert yanit.total_tokens == 390
        # Gorunur metnin jetonu, dusunme jetonlari cikarilarak bulunur.
        assert yanit.visible_tokens == 18

    @respx.mock
    def test_reasoning_tokens_completion_disindaysa_eklenir(self):
        """Sunucu dusunme jetonlarini completion'a katmadiysa maliyet eksik cikar."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json=chat_payload(
                    prompt_tokens=10,
                    completion_tokens=18,
                    reasoning_tokens=322,
                ),
            )
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek())
        assert yanit.completion_tokens == 340
        assert yanit.total_tokens == 350

    @respx.mock
    def test_alternatif_reasoning_alan_adi_desteklenir(self):
        govde = chat_payload()
        govde["choices"][0]["message"]["reasoning"] = "alternatif alan adi"
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=govde))
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek())
        assert yanit.reasoning == "alternatif alan adi"

    @respx.mock
    def test_max_tokens_yetersizken_bos_icerik_hata_uretir(self):
        """max_tokens=60 iken model dusunmede tukenir; sessizce bos donmek YASAK."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json=chat_payload(
                    content="",
                    reasoning="Once soruyu anlamaliyim. Kullanici doluluk sordu...",
                    finish_reason="length",
                    prompt_tokens=40,
                    completion_tokens=60,
                    reasoning_tokens=60,
                ),
            )
        )
        with yerel_saglayici() as saglayici, pytest.raises(AIResponseFormatError) as hata:
            saglayici.chat(istek(max_tokens=60))

        assert hata.value.context["reason"] == "reasoning_budget_exhausted"
        assert hata.value.context["max_tokens"] == 60
        assert hata.value.context["reasoning_tokens"] == 60
        assert "max_tokens" in (hata.value.remedy or "")

    @respx.mock
    def test_bos_icerik_ama_normal_bitis_hata_uretmez(self):
        """``finish_reason='stop'`` ile bos yanit hatali degildir, sadece bostur."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=chat_payload(content="", finish_reason="stop"))
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.chat(istek())
        assert yanit.is_empty
        assert not yanit.truncated_while_reasoning

    def test_katalog_gemma_modelini_dusunme_modeli_olarak_isaretler(self):
        from app.ai import catalog

        assert catalog.supports_reasoning(GEMMA_CHAT_MODEL)
        assert not catalog.supports_reasoning(QWEN_VISION_MODEL)


# --------------------------------------------------------------------------
#  Hata eslemesi
# --------------------------------------------------------------------------
class TestHatalar:
    @pytest.mark.parametrize("kod", [401, 403])
    @respx.mock
    def test_kimlik_hatasi(self, kod: int):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(kod, json={"error": "unauthorized"}))
        with yerel_saglayici() as saglayici, pytest.raises(AIAuthenticationError) as hata:
            saglayici.chat(istek())
        assert hata.value.context["status_code"] == kod
        assert hata.value.remedy

    @respx.mock
    def test_kota_hatasi(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(429, json={"error": "rate limit"}))
        with yerel_saglayici() as saglayici, pytest.raises(AIQuotaError) as hata:
            saglayici.chat(istek())
        assert "Kota" in (hata.value.remedy or "")

    @respx.mock
    def test_model_bulunamadi(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(404, json={"error": "not found"}))
        respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=LMSTUDIO_MODELS_PAYLOAD))
        with yerel_saglayici() as saglayici, pytest.raises(AIModelNotFoundError):
            saglayici.chat(istek(model="olmayan-model"))

    @respx.mock
    def test_baglanti_reddi(self):
        respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("baglanti reddedildi"))
        with yerel_saglayici() as saglayici, pytest.raises(ConnErr) as hata:
            saglayici.chat(istek())
        assert "LM Studio" in (hata.value.remedy or "")

    @respx.mock
    def test_zaman_asimi(self):
        respx.post(CHAT_URL).mock(side_effect=httpx.ReadTimeout("cok yavas"))
        with yerel_saglayici() as saglayici, pytest.raises(AITimeoutError) as hata:
            saglayici.chat(istek())
        assert "zaman aşımı" in (hata.value.remedy or "").lower()

    @respx.mock
    def test_sunucu_hatasi(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(503, text="asiri yuklu"))
        with yerel_saglayici() as saglayici, pytest.raises(AIProviderError) as hata:
            saglayici.chat(istek())
        assert hata.value.context["status_code"] == 503

    @respx.mock
    def test_json_olmayan_yanit_bicim_hatasi(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text="<html>hata</html>"))
        with yerel_saglayici() as saglayici, pytest.raises(AIResponseFormatError):
            saglayici.chat(istek())


class TestYenidenDeneme:
    @respx.mock
    def test_500_yeniden_denenir_ve_basarili_olur(self):
        route = respx.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(500, text="gecici hata"),
                httpx.Response(200, json=chat_payload()),
            ]
        )
        with yerel_saglayici(max_retries=2) as saglayici:
            yanit = saglayici.chat(istek())
        assert route.call_count == 2
        assert not yanit.is_empty

    @respx.mock
    def test_429_yeniden_denenir(self):
        route = respx.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(429, text="yavaslayin"),
                httpx.Response(200, json=chat_payload()),
            ]
        )
        with yerel_saglayici(max_retries=1) as saglayici:
            saglayici.chat(istek())
        assert route.call_count == 2

    @respx.mock
    def test_400_te_yeniden_denenmez(self):
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(400, text="gecersiz istek"))
        with yerel_saglayici(max_retries=3) as saglayici, pytest.raises(AIProviderError):
            saglayici.chat(istek())
        assert route.call_count == 1

    @respx.mock
    def test_401_de_yeniden_denenmez(self):
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(401, text="yetkisiz"))
        with yerel_saglayici(max_retries=3) as saglayici, pytest.raises(AIAuthenticationError):
            saglayici.chat(istek())
        assert route.call_count == 1

    @respx.mock
    def test_404_te_yeniden_denenmez(self):
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(404, text="yok"))
        respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=LMSTUDIO_MODELS_PAYLOAD))
        with yerel_saglayici(max_retries=3) as saglayici, pytest.raises(AIModelNotFoundError):
            saglayici.chat(istek())
        assert route.call_count == 1

    @respx.mock
    def test_tum_denemeler_tukenirse_son_hata_firlatilir(self):
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(500, text="surekli hata"))
        with yerel_saglayici(max_retries=2) as saglayici, pytest.raises(AIProviderError):
            saglayici.chat(istek())
        assert route.call_count == 3


# --------------------------------------------------------------------------
#  LM Studio ozel davranislari
# --------------------------------------------------------------------------
class TestLMStudio:
    @respx.mock
    def test_gercek_model_listesi_ayristirilir(self):
        respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=LMSTUDIO_MODELS_PAYLOAD))
        with yerel_saglayici() as saglayici:
            modeller = saglayici.list_models()

        kimlikler = [model.id for model in modeller]
        assert len(modeller) == 6
        assert GEMMA_CHAT_MODEL in kimlikler
        assert NOMIC_EMBED_MODEL in kimlikler
        gemma = next(model for model in modeller if model.id == GEMMA_CHAT_MODEL)
        assert gemma.supports_reasoning
        assert gemma.display_name == "Gemma 4 12B (QAT)"

    @respx.mock
    def test_404_hatasi_mevcut_model_listesini_icerir(self):
        """Kullanici hangi modellerin yuklu oldugunu gorebilmelidir."""
        respx.post(CHAT_URL).mock(return_value=httpx.Response(404, text="model bulunamadi"))
        respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=LMSTUDIO_MODELS_PAYLOAD))

        with yerel_saglayici() as saglayici, pytest.raises(AIModelNotFoundError) as hata:
            saglayici.chat(istek(model="llama-99b-hayali"))

        mevcut = hata.value.context["available_models"]
        assert GEMMA_CHAT_MODEL in mevcut
        assert len(mevcut) == 6
        assert "llama-99b-hayali" in hata.value.user_message
        assert GEMMA_CHAT_MODEL in (hata.value.remedy or "")

    @respx.mock
    def test_model_listesi_alinamazsa_ozgun_hata_korunur(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(404, text="yok"))
        respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("sunucu kapandi"))
        with yerel_saglayici() as saglayici, pytest.raises(AIModelNotFoundError) as hata:
            saglayici.chat(istek(model="yok-boyle"))
        assert "available_models" not in hata.value.context

    @respx.mock
    def test_ensure_model_yuklu_olmayan_modelde_hata_verir(self):
        respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=LMSTUDIO_MODELS_PAYLOAD))
        with yerel_saglayici() as saglayici:
            saglayici.ensure_model(GEMMA_CHAT_MODEL)  # sorunsuz
            with pytest.raises(AIModelNotFoundError):
                saglayici.ensure_model("hic-yok")

    @respx.mock
    def test_yer_tutucu_anahtar_gonderilmez(self):
        """``lm-studio`` varsayilani anlamsizdir; Authorization eklenmez."""
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=chat_payload()))
        with yerel_saglayici() as saglayici:
            saglayici.chat(istek())
        assert "authorization" not in route.calls.last.request.headers

    @respx.mock
    def test_gercek_anahtar_verilirse_gonderilir(self):
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=chat_payload()))
        with yerel_saglayici(api_key="ozel-erisim-degeri") as saglayici:
            saglayici.chat(istek())
        assert route.calls.last.request.headers["authorization"] == "Bearer ozel-erisim-degeri"

    @respx.mock
    def test_saglik_kontrolu_basarili(self):
        respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=LMSTUDIO_MODELS_PAYLOAD))
        with yerel_saglayici() as saglayici:
            durum = saglayici.health_check()
        assert durum.ok
        assert durum.models_found == 6
        assert durum.label == "Calisiyor"

    @respx.mock
    def test_saglik_kontrolu_hata_firlatmaz(self):
        respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("kapali"))
        with yerel_saglayici() as saglayici:
            durum = saglayici.health_check()
        assert not durum.ok
        assert "LM Studio" in durum.message
        assert durum.models_found == 0
        assert durum.model_ids == ()

    @respx.mock
    def test_saglik_kontrolu_model_adlarini_da_dondurur(self):
        """Yanlis model adini duzeltebilmek icin listenin gorunmesi gerekir."""
        respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=LMSTUDIO_MODELS_PAYLOAD))
        with yerel_saglayici() as saglayici:
            durum = saglayici.health_check()
        assert durum.models_found == len(durum.model_ids) == 6
        assert GEMMA_CHAT_MODEL in durum.model_ids


# --------------------------------------------------------------------------
#  JSON ayiklama ve dogrulama
# --------------------------------------------------------------------------
class TestJsonAyiklama:
    def test_duz_json(self):
        assert extract_json_object('{"oda": 101}') == {"oda": 101}

    def test_markdown_kod_blogundan_ayiklanir(self):
        metin = 'Iste sonuc:\n```json\n{"oda": 101, "durum": "temiz"}\n```\nUmarim yeterlidir.'
        assert extract_json_object(metin) == {"oda": 101, "durum": "temiz"}

    def test_etiketsiz_kod_blogu(self):
        assert extract_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_metin_arasindaki_ilk_nesne(self):
        metin = 'Tabii! {"oda": 205, "not": "kapali}"} ... baska metin'
        assert extract_json_object(metin) == {"oda": 205, "not": "kapali}"}

    def test_ic_ice_nesneler_bozulmaz(self):
        metin = 'Sonuc: {"a": {"b": {"c": 3}}} bitti'
        assert extract_json_object(metin) == {"a": {"b": {"c": 3}}}

    def test_gecersiz_json_hata_verir(self):
        with pytest.raises(AIResponseFormatError):
            extract_json_object("bu tamamen duz bir cumledir")

    def test_bos_yanit_hata_verir(self):
        with pytest.raises(AIResponseFormatError):
            extract_json_object("   ")

    def test_ust_duzey_dizi_kabul_edilmez(self):
        with pytest.raises(AIResponseFormatError):
            extract_json_object("[1, 2, 3]")

    def test_nesne_dizisi_sessizce_ilk_ogeye_indirgenmez(self):
        """``[{...}, {...}]`` ciktisinda ilk ogeyi almak veri kaybidir."""
        with pytest.raises(AIResponseFormatError) as hata:
            extract_json_object('[{"ucret": 100}, {"ucret": 250}]')
        assert "dizi" in (hata.value.detail or "")
        # Kaybolacak oge sayisi teshis icin ayrintida gorunmelidir.
        assert "2 ogeli" in (hata.value.detail or "")

    def test_kod_blogundaki_dizi_de_reddedilir(self):
        with pytest.raises(AIResponseFormatError):
            extract_json_object('```json\n[{"oda": 101}]\n```')

    def test_metin_icindeki_dizi_nesne_bulmayi_engellemez(self):
        """Serbest metinde gecen dizi, asil nesnenin bulunmasini bozmamalidir."""
        metin = 'Odalar: [101, 102]. Ozet: {"toplam": 2}'
        assert extract_json_object(metin) == {"toplam": 2}

    def test_sema_zorunlu_alan_eksik(self):
        sema = {"type": "object", "required": ["oda"], "properties": {"oda": {"type": "integer"}}}
        with pytest.raises(AIResponseFormatError):
            validate_json_schema({"durum": "temiz"}, sema)

    def test_sema_tip_uyusmazligi(self):
        sema = {"type": "object", "properties": {"oda": {"type": "integer"}}}
        with pytest.raises(AIResponseFormatError):
            validate_json_schema({"oda": "101"}, sema)

    def test_sema_bool_integer_yerine_gecmez(self):
        sema = {"type": "object", "properties": {"sayi": {"type": "integer"}}}
        with pytest.raises(AIResponseFormatError):
            validate_json_schema({"sayi": True}, sema)

    def test_sema_gecerli_veriyi_gecirir(self):
        sema = {
            "type": "object",
            "required": ["oda", "etiketler"],
            "properties": {
                "oda": {"type": "integer"},
                "etiketler": {"type": "array", "items": {"type": "string"}},
            },
        }
        veri = {"oda": 101, "etiketler": ["deniz", "balkon"]}
        assert validate_json_schema(veri, sema) == veri


class TestJsonModu:
    @respx.mock
    def test_response_format_gonderilir(self):
        route = respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=chat_payload(content='{"oda": 101}'))
        )
        with yerel_saglayici() as saglayici:
            veri = saglayici.chat_json(istek(), {"type": "object"})
        assert veri == {"oda": 101}
        assert "json_object" in route.calls.last.request.read().decode()

    @respx.mock
    def test_json_modu_desteklenmiyorsa_istem_yontemine_duser(self):
        route = respx.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(400, text="response_format is not supported by this model"),
                httpx.Response(200, json=chat_payload(content='```json\n{"oda": 7}\n```')),
            ]
        )
        with yerel_saglayici() as saglayici:
            veri = saglayici.chat_json(istek())
        assert veri == {"oda": 7}
        assert route.call_count == 2
        # Ikinci istekte response_format gonderilmemis olmalidir.
        assert "response_format" not in route.calls[1].request.read().decode()

    @respx.mock
    def test_ilgisiz_400_hatasi_yutulmaz(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(400, text="model parametresi eksik"))
        with yerel_saglayici() as saglayici, pytest.raises(AIProviderError):
            saglayici.chat_json(istek())


# --------------------------------------------------------------------------
#  Gomme
# --------------------------------------------------------------------------
class TestGomme:
    @respx.mock
    def test_vektorler_dondurulur(self):
        respx.post(EMBED_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": NOMIC_EMBED_MODEL,
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2]},
                        {"index": 1, "embedding": [0.3, 0.4]},
                    ],
                    "usage": {"prompt_tokens": 9, "total_tokens": 9},
                },
            )
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.embed(["ilk", "ikinci"])
        assert len(yanit) == 2
        assert yanit.dimension == 2
        assert yanit.tokens == 9

    @respx.mock
    def test_sira_index_alanina_gore_duzeltilir(self):
        respx.post(EMBED_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [9.0]},
                        {"index": 0, "embedding": [1.0]},
                    ]
                },
            )
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.embed(["a", "b"])
        assert yanit.vectors == [[1.0], [9.0]]

    @respx.mock
    def test_tek_metin_listeye_cevrilir(self):
        """``embed("metin")`` karakter karakter gomulmemelidir."""
        route = respx.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
        )
        with yerel_saglayici() as saglayici:
            yanit = saglayici.embed("tek metin")
        govde = json.loads(route.calls.last.request.read())
        assert govde["input"] == ["tek metin"]
        assert len(yanit) == 1

    @respx.mock
    def test_bos_liste_ag_cagrisi_yapmaz(self):
        route = respx.post(EMBED_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        with yerel_saglayici() as saglayici:
            yanit = saglayici.embed([])
        assert route.call_count == 0
        assert yanit.dimension == 0


# --------------------------------------------------------------------------
#  NVIDIA
# --------------------------------------------------------------------------
class TestNvidia:
    def test_anahtar_yoksa_kimlik_hatasi(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("app.ai.providers.nvidia.get_secret", lambda *a, **k: None)
        saglayici = NvidiaProvider(max_retries=0, retry_backoff=0.0)
        # Gelistirici makinesinde .env'de anahtar bulunma ihtimalini eleriz.
        saglayici.settings = None
        with pytest.raises(AIAuthenticationError) as hata:
            saglayici._resolve_api_key()
        assert "Ayarlar" in (hata.value.remedy or "")
        assert "Yapay Zeka" in (hata.value.remedy or "")
        # Hata ayrintisinda yalnizca sirrin ADI gecer, degeri degil.
        assert hata.value.context["keyring_entry"] == "nvidia_api_key"
        assert "nvapi" not in str(hata.value.detail or "")

    def test_varsayilan_adres(self):
        saglayici = NvidiaProvider()
        assert saglayici.base_url == "https://integrate.api.nvidia.com/v1"
        assert not saglayici.is_local

    @respx.mock
    def test_anahtar_bearer_basliginda_gonderilir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("app.ai.providers.nvidia.get_secret", lambda *a, **k: "nvapi-sahte")
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        route = respx.post(url).mock(return_value=httpx.Response(200, json=chat_payload()))
        with NvidiaProvider(max_retries=0, retry_backoff=0.0) as saglayici:
            saglayici.chat(istek(model="meta/llama-test"))
        assert route.calls.last.request.headers["authorization"] == "Bearer nvapi-sahte"

    def test_has_api_key_hata_firlatmaz(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("app.ai.providers.nvidia.get_secret", lambda *a, **k: None)
        saglayici = NvidiaProvider()
        saglayici.settings = None
        assert saglayici.has_api_key is False


# --------------------------------------------------------------------------
#  Anthropic - farkli sema
# --------------------------------------------------------------------------
def anthropic_saglayici(**kwargs: Any) -> AnthropicProvider:
    kwargs.setdefault("base_url", ANTHROPIC_BASE)
    kwargs.setdefault("api_key", "sahte-anahtar")
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("retry_backoff", 0.0)
    kwargs.setdefault("chat_model", "claude-test")
    return AnthropicProvider(**kwargs)


class TestAnthropic:
    @respx.mock
    def test_sistem_istemi_ayri_parametre_olarak_gonderilir(self):
        route = respx.post(ANTHROPIC_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Tamam."}],
                    "model": "claude-test",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 3},
                },
            )
        )
        talep = ChatRequest(
            messages=[
                ChatMessage.system("Sen bir otel asistanisin."),
                ChatMessage.user("Merhaba"),
            ],
            model="claude-test",
            max_tokens=512,
        )
        with anthropic_saglayici() as saglayici:
            saglayici.chat(talep)

        govde = json.loads(route.calls.last.request.read())
        assert govde["system"] == "Sen bir otel asistanisin."
        assert govde["messages"] == [{"role": "user", "content": "Merhaba"}]
        assert govde["max_tokens"] == 512

    @respx.mock
    def test_zorunlu_basliklar_gonderilir(self):
        route = respx.post(ANTHROPIC_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )
        )
        with anthropic_saglayici() as saglayici:
            saglayici.chat(istek(model="claude-test"))
        basliklar = route.calls.last.request.headers
        assert basliklar["x-api-key"] == "sahte-anahtar"
        assert basliklar["anthropic-version"] == "2023-06-01"
        assert "authorization" not in basliklar

    @respx.mock
    def test_icerik_bloklari_ve_dusunme_ayristirilir(self):
        respx.post(ANTHROPIC_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "thinking", "thinking": "Once odayi kontrol etmeliyim."},
                        {"type": "text", "text": "101 numarali oda "},
                        {"type": "text", "text": "musait."},
                    ],
                    "model": "claude-test",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 40, "output_tokens": 25},
                },
            )
        )
        with anthropic_saglayici() as saglayici:
            yanit = saglayici.chat(istek(model="claude-test"))

        assert yanit.content == "101 numarali oda musait."
        assert yanit.reasoning == "Once odayi kontrol etmeliyim."
        assert yanit.prompt_tokens == 40
        assert yanit.completion_tokens == 25
        assert yanit.total_tokens == 65
        assert yanit.finish_reason == "stop"

    @respx.mock
    def test_max_tokens_bitisi_length_olarak_normallestirilir(self):
        respx.post(ANTHROPIC_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Yarim kalan"}],
                    "stop_reason": "max_tokens",
                    "usage": {"input_tokens": 5, "output_tokens": 5},
                },
            )
        )
        with anthropic_saglayici() as saglayici:
            yanit = saglayici.chat(istek(model="claude-test"))
        assert yanit.finish_reason == "length"

    @respx.mock
    def test_dusunmede_tukenirse_hata_uretir(self):
        respx.post(ANTHROPIC_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "thinking", "thinking": "uzun dusunce"}],
                    "stop_reason": "max_tokens",
                    "usage": {"input_tokens": 5, "output_tokens": 60},
                },
            )
        )
        with anthropic_saglayici() as saglayici, pytest.raises(AIResponseFormatError):
            saglayici.chat(istek(model="claude-test", max_tokens=60))

    def test_bos_konusma_reddedilir(self):
        talep = ChatRequest(
            messages=[ChatMessage.system("yalnizca sistem")],
            model="claude-test",
        )
        with anthropic_saglayici() as saglayici, pytest.raises(ValidationError):
            saglayici.chat(talep)

    @respx.mock
    def test_model_listesi(self):
        respx.get(ANTHROPIC_MODELS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [{"id": "claude-test", "display_name": "Claude Test", "type": "model"}]
                },
            )
        )
        with anthropic_saglayici() as saglayici:
            modeller = saglayici.list_models()
        assert [model.id for model in modeller] == ["claude-test"]
        assert modeller[0].display_name == "Claude Test"

    def test_gomme_desteklenmez(self):
        with anthropic_saglayici() as saglayici, pytest.raises(AIProviderError) as hata:
            saglayici.embed(["metin"])
        assert hata.value.context["capability"] == "embedding"
        assert "gömme" in (hata.value.remedy or "").lower()


# --------------------------------------------------------------------------
#  Sahte saglayici
# --------------------------------------------------------------------------
class TestMockSaglayici:
    def test_belirlenimci_yanit(self):
        saglayici = MockProvider()
        birinci = saglayici.chat(istek("ayni soru"))
        ikinci = MockProvider().chat(istek("ayni soru"))
        assert birinci.content == ikinci.content
        assert birinci.content != saglayici.chat(istek("farkli soru")).content

    def test_hazir_yanitlar_sirayla_verilir(self):
        saglayici = MockProvider(responses=["ilk", "ikinci"])
        assert saglayici.chat(istek()).content == "ilk"
        assert saglayici.chat(istek()).content == "ikinci"
        # Liste tukendiginde sonuncusu tekrarlanir.
        assert saglayici.chat(istek()).content == "ikinci"

    def test_hata_simulasyonu(self):
        saglayici = MockProvider(fail_with=ConnErr("simule edilmis kesinti"))
        with pytest.raises(ConnErr):
            saglayici.chat(istek())

    def test_cagrilar_kaydedilir(self):
        saglayici = MockProvider()
        saglayici.chat(istek("birinci"))
        saglayici.chat(istek("ikinci"))
        assert len(saglayici.calls) == 2
        assert saglayici.calls[1].last_user_content == "ikinci"

    def test_hicbir_ag_baglantisi_acilmaz(self):
        saglayici = MockProvider()
        saglayici.chat(istek())
        saglayici.embed(["a"])
        assert saglayici._client is None

    def test_gomme_belirlenimci(self):
        birinci = MockProvider().embed(["oda"])
        ikinci = MockProvider().embed(["oda"])
        assert birinci.vectors == ikinci.vectors
        assert birinci.dimension == MOCK_EMBED_DIM
        assert all(-1.0 <= deger <= 1.0 for deger in birinci.vectors[0])

    def test_saglik_durumu(self):
        assert MockProvider().health_check().ok
        assert not MockProvider(healthy=False).health_check().ok

    def test_jeton_sayilari_uretilir(self):
        yanit = MockProvider(reasoning="kisa dusunce metni").chat(istek("uzunca bir soru metni"))
        assert yanit.prompt_tokens > 0
        assert yanit.reasoning_tokens > 0
        assert yanit.total_tokens == yanit.prompt_tokens + yanit.completion_tokens


class TestYasamDongusu:
    @respx.mock
    def test_baglam_yoneticisi_istemciyi_kapatir(self):
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=chat_payload()))
        saglayici = yerel_saglayici()
        with saglayici:
            saglayici.chat(istek())
            assert saglayici._client is not None
        assert saglayici._client is None

    def test_close_birden_fazla_cagrilabilir(self):
        saglayici = OpenAICompatibleProvider(base_url=BASE_URL)
        saglayici.close()
        saglayici.close()

    @respx.mock
    def test_odunc_alinan_istemci_ne_kapatilir_ne_birakilir(self):
        """Disaridan verilen istemcinin yasam dongusu cagirana aittir.

        Istemci birakilsaydi (``_client = None``) bir sonraki cagri sessizce
        yeni bir istemci acardi; testte respx yerine gercek ag kullanilir,
        uretimde kimsenin kapatmadigi bir havuz sizardi.
        """
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=chat_payload()))
        odunc = httpx.Client()
        saglayici = LMStudioProvider(base_url=BASE_URL, max_retries=0, client=odunc)
        saglayici.close()

        assert not odunc.is_closed
        assert saglayici._client is odunc
        # Kapatildiktan sonra bile ayni odunc istemci kullanilmalidir.
        saglayici.chat(istek())
        assert saglayici._client is odunc
        odunc.close()

    def test_url_birlestirme(self):
        saglayici = OpenAICompatibleProvider(base_url="http://ornek.test/v1/")
        assert saglayici.url("/chat/completions") == "http://ornek.test/v1/chat/completions"
        assert saglayici.url("models") == "http://ornek.test/v1/models"


# --------------------------------------------------------------------------
#  Gercek sunucu testi - VARSAYILAN OLARAK ATLANIR
# --------------------------------------------------------------------------
@pytest.mark.live
def test_gercek_lmstudio_model_listesi(request: pytest.FixtureRequest) -> None:
    """Gercek LM Studio sunucusuna baglanip model listesini alir.

    Yalnizca ``pytest -m live`` ile calistirilir; normal test kosusunda atlanir.
    LM Studio kapaliysa test basarisiz olmaz, atlanir - gelistirici makinesinde
    sunucunun acik olmasi zorunlu degildir.
    """
    secilen = request.config.getoption("-m") or ""
    if "live" not in secilen:
        pytest.skip("Gercek LM Studio gerekir. Calistirmak icin: pytest -m live")

    with LMStudioProvider(base_url="http://127.0.0.1:1234/v1", max_retries=0) as saglayici:
        try:
            modeller = saglayici.list_models()
        except ConnErr as hata:  # pragma: no cover - ortama bagli
            pytest.skip(f"LM Studio calismiyor: {hata.user_message}")

    assert modeller, "LM Studio calisiyor ama hic model yuklu degil."
    for model in modeller:
        assert model.id
