"""Yapay zeka saglayici adaptorlerinin ortak tabani.

Neden senkron?
--------------
Arayuz PySide6 ile yazilmistir ve Qt'nin olay dongusu ile ``asyncio``'yu ayni
surecte yasatmak, iptal/kapanis sirasinda gorunmesi zor kilitlenmeler uretir.
Bu yuzden tum saglayici cagrilari **senkron**dur ve arayuz tarafinda bir
``QThreadPool`` is parcaciginda calistirilir. Bu, hata ayiklamayi da
basitlestirir: yigin izi tek parcadir.

Neden tek bir ``httpx.Client``?
-------------------------------
Her istekte yeni istemci acmak, TLS el sikismasini ve TCP baglantisini her
seferinde yeniden kurar. Yerel LM Studio'da bu fark kucuktur ama uzak
saglayicilarda cagri basina yuzlerce milisaniye eder. Istemci tembel olusturulur
(``MockProvider`` gibi ag kullanmayan adaptorler hic acmaz) ve :meth:`close`
ile kapatilir. Sinif ayrica baglam yoneticisidir::

    with LMStudioProvider() as provider:
        response = provider.chat(request)
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import replace
from types import TracebackType
from typing import Any, ClassVar, Final

import httpx

from app.ai.errors import (
    is_retryable_status,
    json_format_error,
    map_status_code,
    map_transport_error,
)
from app.ai.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbeddingResponse,
    HealthStatus,
    ModelInfo,
)
from app.core.config import AIProviderSettings, get_settings
from app.core.exceptions import AIProviderError
from app.core.log import get_logger
from app.domain.enums import AIProviderType

log = get_logger(__name__)

#: Markdown kod blogu icine sarilmis JSON'u yakalayan desen.
_FENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n?(.*?)```",
    re.DOTALL,
)

#: Sema dogrulamasinda takip edilecek azami derinlik (kotu semalara karsi kalkan).
_MAX_SCHEMA_DEPTH: Final[int] = 12

_JSON_TYPES: Final[dict[str, tuple[type, ...]]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


# --------------------------------------------------------------------------
#  JSON yardimcilari
# --------------------------------------------------------------------------
def _iter_balanced_objects(text: str) -> Iterator[str]:
    """Metin icindeki dengeli ``{...}`` bloklarini sirayla verir.

    Basit bir ``text[text.find('{'):text.rfind('}')+1]`` kirpmasi, metinde
    birden fazla nesne veya ic ice suslu parantez varsa bozuk sonuc uretir.
    Dizge icindeki ``{``/``}`` karakterleri ve kacislar da sayilmamalidir -
    bu tarayici ikisini de dogru ele alir.
    """
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                yield text[start : index + 1]
                start = -1


def _parse_or_none(candidate: str) -> Any:
    """Adayi ayristirir; JSON degilse ``None`` doner (istisna uretmez)."""
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_json_object(text: str, *, provider: str = "") -> dict[str, Any]:
    """Model ciktisindan ilk gecerli JSON **nesnesini** ayiklar.

    Su uc durum sirayla denenir:

    1. Duz JSON (``{"a": 1}``)
    2. Markdown kod blogu (uc ters tirnak + istege bagli ``json`` etiketi)
    3. Serbest metin arasindaki ilk dengeli JSON nesnesi
       (or. ``Iste sonuc: {"a": 1} umarim yardimci olur.``)

    Ciktinin **tamami** bir dizi ise (``[...]`` ya da kod blogu icinde dizi)
    hata firlatilir. Bunun ozel olarak ele alinmasi sarttir: ``[{"a": 1},
    {"b": 2}]`` ciktisinda dengeli tarayici ilk nesneyi bulup dondururdu ve
    kalan ogeler **sessizce kaybolurdu** - "tum ek ucretleri cikar" gibi bir
    istekte bu, verinin bir kismini yok saymak demektir. Dizi icinden secim
    yapmak yerine acik hata veririz.

    Serbest metin *icinde* gecen diziler (or. ``Odalar: [101, 102]. Ozet:
    {"toplam": 2}``) bu kurala girmez; oradaki amac zaten nesneyi bulmaktir.
    """
    stripped = (text or "").strip()
    if not stripped:
        raise json_format_error(provider=provider, detail="Model bos yanit dondurdu.")

    # 1-2. Ciktinin tamami ya da kod blogunun tamami.
    whole: list[str] = [stripped]
    whole.extend(match.strip() for match in _FENCE_PATTERN.findall(stripped))
    for candidate in whole:
        if not candidate:
            continue
        parsed = _parse_or_none(candidate)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            raise json_format_error(
                provider=provider,
                detail=(
                    f"Model JSON nesnesi yerine {len(parsed)} ogeli dizi dondurdu. "
                    "Ilk ogeyi secmek kalan ogeleri sessizce kaybettirirdi. "
                    f"Ham cikti: {stripped[:300]}"
                ),
            )

    # 3. Serbest metin arasindaki ilk dengeli nesne.
    for candidate in _iter_balanced_objects(stripped):
        parsed = _parse_or_none(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise json_format_error(
        provider=provider,
        detail=f"Gecerli JSON nesnesi bulunamadi. Ham cikti: {stripped[:300]}",
    )


def _check_node(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str,
    depth: int,
    provider: str,
) -> None:
    if depth > _MAX_SCHEMA_DEPTH:
        return

    expected = schema.get("type")
    if isinstance(expected, str) and expected in _JSON_TYPES:
        allowed = _JSON_TYPES[expected]
        # bool, Python'da int'in alt sinifidir; "integer" beklenirken True
        # gecerli sayilmamalidir.
        is_bad_bool = expected in {"integer", "number"} and isinstance(value, bool)
        if is_bad_bool or not isinstance(value, allowed):
            raise json_format_error(
                provider=provider,
                detail=f"{path} alani '{expected}' olmali, {type(value).__name__} geldi.",
            )

    choices = schema.get("enum")
    if isinstance(choices, list) and value not in choices:
        raise json_format_error(
            provider=provider,
            detail=f"{path} alani su degerlerden biri olmali: {choices!r}",
        )

    if isinstance(value, dict):
        for name in schema.get("required", []) or []:
            if name not in value:
                raise json_format_error(
                    provider=provider,
                    detail=f"{path} icinde zorunlu '{name}' alani eksik.",
                )
        properties = schema.get("properties") or {}
        for name, sub_schema in properties.items():
            if name in value and isinstance(sub_schema, dict):
                _check_node(
                    value[name],
                    sub_schema,
                    path=f"{path}.{name}",
                    depth=depth + 1,
                    provider=provider,
                )
    elif isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _check_node(
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    provider=provider,
                )


def validate_json_schema(
    data: dict[str, Any],
    schema: dict[str, Any] | None,
    *,
    provider: str = "",
) -> dict[str, Any]:
    """Hafif JSON Sema dogrulamasi.

    Tam bir JSON Schema uygulamasi degildir - yeni bagimlilik eklememek icin
    yalnizca pratikte ise yarayan alt kume desteklenir: ``type``, ``required``,
    ``properties``, ``items`` ve ``enum``. Amac, modelin uydurdugu alan
    adlarini ve tip hatalarini servis katmanina sizmadan yakalamaktir.
    """
    if not schema:
        return data
    _check_node(data, schema, path="$", depth=0, provider=provider)
    return data


def json_instruction(schema: dict[str, Any] | None) -> str:
    """``response_format`` desteklemeyen saglayicilar icin istem talimati."""
    lines = [
        "Yanitini SADECE gecerli bir JSON nesnesi olarak ver.",
        "Aciklama, giris cumlesi, baslik veya markdown kod blogu isareti EKLEME.",
    ]
    if schema:
        lines.append("Cikti su semaya uymalidir:")
        lines.append(json.dumps(schema, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


# --------------------------------------------------------------------------
#  Taban sinif
# --------------------------------------------------------------------------
class AIProvider(ABC):
    """Tum yapay zeka saglayici adaptorlerinin tabani.

    .. note::
       Ad benzerligine dikkat: :class:`app.infrastructure.db.models.ai.AIProvider`
       veritabani tablosudur, bu sinif ise **calisma zamani adaptorudur**. Ikisi
       farkli katmanlara aittir ve birbirini import etmez.
    """

    #: Kayitta ve loglarda kullanilan mantiksal ad.
    name: ClassVar[str] = "base"
    #: Yerelde calisiyor mu? Hata onerileri ve maliyet hesabi buna gore degisir.
    is_local: ClassVar[bool] = False
    #: Karsilik gelen domain enum degeri.
    provider_type: ClassVar[AIProviderType] = AIProviderType.MOCK

    def __init__(
        self,
        *,
        settings: AIProviderSettings | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        ai_settings = get_settings().ai
        self.settings = settings
        resolved_url = base_url if base_url is not None else (settings.base_url if settings else "")
        self.base_url = (resolved_url or "").rstrip("/")
        self.timeout = float(timeout if timeout is not None else ai_settings.default_timeout)
        self.max_retries = int(max_retries if max_retries is not None else ai_settings.max_retries)
        self.retry_backoff = float(retry_backoff if retry_backoff is not None else 0.5)
        self.extra_headers = dict(extra_headers or {})
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    # ---------------- HTTP altyapisi ----------------
    @property
    def client(self) -> httpx.Client:
        """Tembel olusturulan, yeniden kullanilan HTTP istemcisi."""
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
            )
            self._owns_client = True
        return self._client

    def url(self, path: str) -> str:
        """Taban adres ile yolu birlestirir."""
        return f"{self.base_url}/{path.lstrip('/')}"

    def _resolve_api_key(self) -> str | None:
        """Anahtari cozer. Alt siniflar eksik anahtarda hata firlatabilir."""
        if self._api_key:
            return self._api_key
        if self.settings is not None:
            self._api_key = self.settings.resolve_api_key()
        return self._api_key

    def _headers(self) -> dict[str, str]:
        """Istek basliklari. Anahtar **asla loglanmaz**."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        key = self._resolve_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        headers.update(self.extra_headers)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
        retry: bool = True,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Tek bir HTTP cagrisi yapar, hatalari ``AI*`` tiplerine cevirir.

        Yeniden deneme yalnizca 429 ve 5xx icin, ussel geri cekilme ile yapilir.
        400/401/404 gibi kalici hatalarda tekrar denemek anlamsizdir.
        """
        url = self.url(path)
        attempts = self.max_retries + 1 if retry else 1
        last_error: AIProviderError | None = None

        for attempt in range(attempts):
            try:
                response = self.client.request(
                    method,
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=timeout if timeout is not None else self.timeout,
                )
            except httpx.HTTPError as exc:
                raise map_transport_error(
                    exc,
                    provider=self.name,
                    is_local=self.is_local,
                    base_url=self.base_url,
                ) from exc

            if response.status_code >= 400:
                last_error = map_status_code(
                    response.status_code,
                    provider=self.name,
                    is_local=self.is_local,
                    detail=_safe_body(response),
                    model=model,
                )
                if is_retryable_status(response.status_code) and attempt < attempts - 1:
                    self._sleep_backoff(attempt)
                    continue
                raise last_error

            try:
                data = response.json()
            except ValueError as exc:
                raise json_format_error(
                    provider=self.name,
                    detail=f"Saglayici JSON olmayan yanit dondurdu: {response.text[:200]}",
                    model=model,
                ) from exc
            if not isinstance(data, dict):
                raise json_format_error(
                    provider=self.name,
                    detail=f"Saglayici sozluk yerine {type(data).__name__} dondurdu.",
                    model=model,
                )
            return data

        # Buraya yalnizca tum denemeler tukendiginde gelinir.
        raise last_error if last_error else AIProviderError(provider=self.name)

    def _sleep_backoff(self, attempt: int) -> None:
        """Ussel geri cekilme. ``retry_backoff=0`` ise testlerde beklemez."""
        delay = self.retry_backoff * (2**attempt)
        if delay > 0:
            time.sleep(delay)

    # ---------------- Sozlesme ----------------
    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Sohbet tamamlamasi yapar."""

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """Saglayicida kullanilabilir modelleri listeler."""

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Saglayiciya ulasilabiliyor mu? **Hata firlatmaz.**"""

    @abstractmethod
    def embed(self, texts: Sequence[str] | str, model: str | None = None) -> EmbeddingResponse:
        """Metinleri vektore cevirir."""

    def chat_json(
        self,
        request: ChatRequest,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """JSON dondurmesi beklenen bir sohbet cagrisi yapar.

        Varsayilan uygulama saf istem tabanlidir: talimat eklenir, yanit
        ayiklanir ve (verilmisse) semaya gore dogrulanir. OpenAI uyumlu
        saglayicilar bunu ``response_format`` ile guclendirmek uzere override
        eder.
        """
        effective_schema = schema if schema is not None else request.json_schema
        prepared = self._with_json_instruction(request, effective_schema)
        response = self.chat(prepared)
        data = extract_json_object(response.content, provider=self.name)
        return validate_json_schema(data, effective_schema, provider=self.name)

    @staticmethod
    def _with_json_instruction(
        request: ChatRequest,
        schema: dict[str, Any] | None,
    ) -> ChatRequest:
        """Istek mesajlarina JSON talimatini ekler (istegi degistirmeden)."""
        messages = [*request.messages, ChatMessage.system(json_instruction(schema))]
        return replace(request, messages=messages, json_schema=schema)

    # ---------------- Yasam dongusu ----------------
    def close(self) -> None:
        """HTTP istemcisini kapatir. Birden fazla cagrilmasi guvenlidir.

        Disaridan verilen (odunc alinan) istemciye **dokunulmaz**: ne kapatilir
        ne de birakilir; yasam dongusu cagirana aittir. Birakilsaydi bir sonraki
        istekte :attr:`client` sessizce yeni bir istemci acardi - testte sahte
        aktarim yerine gercek ag baglantisi kurulur, uretimde ise kimsenin
        kapatmadigi bir baglanti havuzu sizardi.
        """
        if self._client is None or not self._owns_client:
            return
        self._client.close()
        self._client = None

    def __enter__(self) -> AIProvider:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - hata ayiklama kolayligi
        return f"{type(self).__name__}(name={self.name!r}, base_url={self.base_url!r})"


def _safe_body(response: httpx.Response) -> str:
    """Hata govdesini loglanabilir bicimde kirpar."""
    try:
        return response.text
    except Exception:  # pragma: no cover - govde okunamayan uc durum
        return f"<govde okunamadi: HTTP {response.status_code}>"


__all__ = [
    "AIProvider",
    "extract_json_object",
    "json_instruction",
    "validate_json_schema",
]
