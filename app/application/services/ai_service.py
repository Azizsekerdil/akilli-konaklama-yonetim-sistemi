"""Yapay zeka servis katmani - model ile veritabani arasindaki GUVENLIK SINIRI.

Bu modul, uygulamadaki tek yapay zeka giris kapisidir. Arayuz hicbir zaman
:mod:`app.ai.registry` ile dogrudan konusmaz; her cagri buradan gecer. Boylece
asagidaki dort kural **tek yerde** uygulanir ve unutulamaz:

1. **Yetki.** Her metot :data:`app.security.permissions.Perm.AI_USE` ister.
2. **Gizlilik.** Sistemin kendi topladigi ozetlerde (gunluk ozet, doluluk
   analizi, fiyat onerisi) modele **yalnizca sayisal toplamlar** gonderilir.
   Misafir adi, kimlik numarasi, e-posta ve telefon istemde **BULUNMAZ**.
   Kullanicinin serbest yazdigi metinlerde (mesaj taslagi, yorum analizi,
   serbest soru) e-posta/telefon/uzun numara dizileri gonderim oncesi
   maskelenir. Son savunma :func:`assert_prompt_is_anonymous`'tur: yapisal
   kurgu bozulursa cagri yapilmadan hata firlatir.
3. **Salt okunurluk.** Bu servis otel verisini **DEGISTIRMEZ**. Fiyat, oda,
   rezervasyon uzerinde hicbir yazma yapmaz. Fiyat cikti tipi
   :class:`PricingSuggestion`'dir ve ``applied`` alani ``init=False`` ile
   sabit ``False``'tur - bir oneriyi "uygulanmis" gostermek tip duzeyinde
   mumkun degildir. Yazilan tek kayitlar denetim izidir: ``AIUsage`` ve
   ``AuditLog``.
4. **Hesap verebilirlik.** Basarili ya da basarisiz, **her** cagri icin bir
   ``AIUsage`` satiri yazilir (saglayici, model, jeton, sure, maliyet, gorev
   turu, durum).

Basarisiz cagrilarin kaydi ve islem sinirlari
---------------------------------------------
``AIUsage`` kaydi cagiranin islemine (transaction) yazilir. Bu yuzden cagiran
taraf hatayi **baglam blogunun icinde** yakalamalidir::

    with ui.service_context() as ctx:
        try:
            sonuc = AIService(ctx).daily_summary()
        except HotelError as exc:
            hata = exc          # blok normal kapanir -> AIUsage kaydi kalir

Hata blogun disina sizarsa ``session_scope`` geri alma yapar ve basarisiz
cagrinin izi de silinir. :mod:`app.ui.pages.ai_center_page` bu kalibi uygular.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Final

from sqlalchemy import func, select

from app.ai import catalog, errors
from app.ai.registry import ProviderRegistry, get_registry
from app.ai.types import ChatMessage, ChatRequest, ChatResponse, HealthStatus
from app.application.context import ServiceContext
from app.core.exceptions import (
    AIAuthenticationError,
    AIConnectionError,
    AIModelNotFoundError,
    AIProviderError,
    AIQuotaError,
    AIResponseFormatError,
    AITimeoutError,
    ConfigurationError,
    ValidationError,
)
from app.core.log import get_logger
from app.domain.enums import (
    AITaskType,
    AIUsageStatus,
    AuditAction,
    Currency,
    HousekeepingStatus,
    MaintenanceStatus,
)
from app.domain.value_objects import DateRange, Money
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.ai import AIConversation, AIMessage, AIUsage
from app.infrastructure.db.models.ai import AIProvider as AIProviderRow
from app.infrastructure.db.models.inventory import InventoryItem
from app.infrastructure.db.models.operations import HousekeepingTask, MaintenanceTicket
from app.infrastructure.db.models.reservations import Reservation, ReservationRoom
from app.infrastructure.db.models.rooms import RoomType
from app.reporting import queries
from app.reporting.models import KPISet
from app.security.permissions import Perm

log = get_logger(__name__)

# --------------------------------------------------------------------------
#  Sabitler
# --------------------------------------------------------------------------
#: Yapay zeka ciktisinin yanina her zaman eklenen seffaflik isareti.
AI_GENERATED_MARKER: Final[str] = "Bu metin yapay zeka tarafından oluşturulmuştur."

#: Fiyat onerilerinde ZORUNLU uyari. Arayuz bu metni degistirmeden gosterir.
PRICING_ADVISORY_NOTE: Final[str] = (
    "Bu bir öneridir. Uygulamak için Fiyatlar ekranından onaylamanız gerekir."
)

#: Yapay zeka kapaliyken kullaniciya gosterilecek cozum onerisi.
REMEDY_AI_DISABLED: Final[str] = (
    "Ayarlar > Yapay Zeka ekranından yapay zekayı etkinleştirin; yerel kullanım için "
    "LM Studio sunucusunu başlatın."
)

#: Modelden JSON istenen gorevlerde kullanilan azami jeton butcesi.
#: Dusunme modelleri butcenin buyuk bolumunu akil yurutmede harcar; dar bir
#: butce bos ``content`` uretir (bkz. app.ai.errors.empty_reasoning_response_error).
JSON_TASK_MAX_TOKENS: Final[int] = 2048

#: Serbest metin gorevlerinde kullanilan azami jeton butcesi.
TEXT_TASK_MAX_TOKENS: Final[int] = 1536

#: Sohbet gecmisinden modele tasinacak azami mesaj sayisi.
#: Tum gecmisi gondermek baglam penceresini doldurur ve maliyeti buyutur.
CONVERSATION_WINDOW: Final[int] = 12

#: Doluluk analizinde modele gonderilecek azami gun sayisi.
MAX_ANALYSIS_DAYS: Final[int] = 62

#: Serbest metin girdilerinde kabul edilen azami karakter.
MAX_FREE_TEXT_CHARS: Final[int] = 4000


# --------------------------------------------------------------------------
#  Gizlilik: maskeleme ve dogrulama
# --------------------------------------------------------------------------
#: E-posta adresi.
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]*\w")

#: Turkiye telefon numarasi bicimleri: +90 555 000 00 01, 0555-000-0001, (0212) 000 00 00.
#:
#: **Neden ayirici zorunlu?** Ayirici aranmadan yazilan "en az 10 hane" kurali,
#: JSON istemindeki buyuk para tutarlarini (or. ``1234567890.0``) telefon sanar
#: ve tamamen gecerli bir raporu engellerdi. Ayiricisiz yazilmis numaralar zaten
#: :data:`_LONG_DIGITS_RE` tarafindan yakalanir; iki kural birlikte tam kapsar.
_PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\d.])"
    r"(?:\+\d{1,3}[\s.-]?)?"
    r"(?:\(0?\d{3}\)|0\d{3}|\d{3})"
    r"[\s.-]\d{3}[\s.-]?\d{2}[\s.-]?\d{2}"
    r"(?!\.?\d)"
)

#: Kimlik/pasaport/kart numarasi gibi uzun sayi dizileri (9 hane ve uzeri).
#:
#: Ondalik sayilarin parcasi olan haneler DISARIDA birakilir: ``123456789.0``
#: bir para tutaridir, kimlik numarasi degildir. Aksi halde yuksek cirolu bir
#: tesiste gunluk ozet hic uretilemezdi.
_LONG_DIGITS_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\d.])\d{9,}(?!\.?\d)")

_EMAIL_MASK: Final[str] = "[e-posta gizlendi]"
_PHONE_MASK: Final[str] = "[telefon gizlendi]"
_NUMBER_MASK: Final[str] = "[numara gizlendi]"


def redact_personal_data(text: str) -> str:
    """Metindeki e-posta, telefon ve uzun numara dizilerini maskeler.

    Kullanicinin serbest yazdigi her metin (mesaj taslagi baglami, misafir
    yorumu, serbest soru) modele gonderilmeden once buradan gecer. Ad-soyad
    otomatik olarak tespit **edilemez**; kullanici bir ad yazdiysa bu onun
    bilincli tercihidir. Buna karsilik kimlik numarasi ve iletisim bilgisi
    KVKK acisindan hicbir kosulda disari cikmamalidir.

    Sira onemlidir: e-posta once maskelenir, aksi halde adresin icindeki
    rakam dizileri telefon sanilabilir.

    >>> redact_personal_data("Iletisim: deniz@ornek.local / +90 555 000 00 01")
    'Iletisim: [e-posta gizlendi] / [telefon gizlendi]'
    >>> redact_personal_data("Kimlik 11111111110 numarali misafir")
    'Kimlik [numara gizlendi] numarali misafir'
    """
    masked = _EMAIL_RE.sub(_EMAIL_MASK, text)
    masked = _LONG_DIGITS_RE.sub(_NUMBER_MASK, masked)
    return _PHONE_RE.sub(_PHONE_MASK, masked)


def find_personal_data(text: str) -> list[str]:
    """Metinde kalan kisisel veri kaliplarini dondurur (bos liste = temiz)."""
    hits: list[str] = []
    hits.extend(_EMAIL_RE.findall(text))
    hits.extend(_LONG_DIGITS_RE.findall(text))
    hits.extend(_PHONE_RE.findall(text))
    return hits


def assert_prompt_is_anonymous(messages: Sequence[ChatMessage]) -> None:
    """Istemde kisisel veri kalmadigini dogrular; kalmissa cagriyi engeller.

    Bu **son savunma hattidir**. Asil guvence yapisaldir: sistemin urettigi
    ozetler yalnizca sayilardan olusur, kullanici metinleri ise
    :func:`redact_personal_data`'dan gecer. Buradaki kontrol, ileride biri
    sorguya bir ad/e-posta sutunu eklerse cagrinin **sessizce** degil
    **gurultuyle** basarisiz olmasini saglar.

    Raises
    ------
    ValidationError
        Istemde e-posta, telefon veya uzun numara dizisi bulunursa.
    """
    for message in messages:
        hits = find_personal_data(message.content)
        if hits:
            # Bulgunun kendisi loga YAZILMAZ - kisisel veri log dosyasina da
            # gitmemelidir. Yalnizca kac adet bulundugu bildirilir.
            raise ValidationError(
                "Yapay zeka isteği kişisel veri içerdiği için gönderilmedi.",
                field="prompt",
                code="ai_prompt_contains_pii",
                detail=f"role={message.role} eslesme_sayisi={len(hits)}",
            )


# --------------------------------------------------------------------------
#  Hata cevirisi
# --------------------------------------------------------------------------
#: Saglayici hatasinin cozum onerisi bos gelirse kullanilacak varsayilanlar.
_DEFAULT_REMEDIES: Final[dict[type[AIProviderError], str]] = {
    AITimeoutError: errors.REMEDY_TIMEOUT,
    AIAuthenticationError: errors.REMEDY_API_KEY,
    AIQuotaError: errors.REMEDY_QUOTA,
    AIModelNotFoundError: errors.REMEDY_MODEL_NOT_FOUND,
    AIResponseFormatError: errors.REMEDY_JSON_FORMAT,
}

#: Saglayici hatasi -> ``AIUsage.status``.
_ERROR_STATUS: Final[dict[type[AIProviderError], AIUsageStatus]] = {
    AITimeoutError: AIUsageStatus.TIMEOUT,
}


def humanize_provider_error(exc: AIProviderError, *, is_local: bool = True) -> AIProviderError:
    """Saglayici hatasini **cozum onerisi dolu** bir kopyasina cevirir.

    Saglayici adaptorleri ``remedy`` alanini genellikle doldurur, ancak
    zorunlu degildir (bkz. testlerdeki sahte saglayici). Arayuz her hatada
    kullaniciya *ne yapacagini* soyleyebilmelidir; bu yuzden bos oneri
    burada tur bazinda tamamlanir.

    Baglanti hatasinda oneri yerel/uzak ayrimina gore secilir: LM Studio icin
    "sunucuyu baslatin", bulut saglayici icin "internet baglantinizi kontrol
    edin" demek gerekir - ikisi ayni tavsiye degildir.
    """
    remedy = getattr(exc, "remedy", None)
    if not remedy:
        if isinstance(exc, AIConnectionError):
            remedy = errors.connection_remedy(is_local=is_local)
        else:
            remedy = _DEFAULT_REMEDIES.get(type(exc), errors.REMEDY_SERVER)

    humanized = type(exc)(
        exc.user_message,
        provider=exc.provider,
        remedy=remedy,
        detail=exc.detail,
        code=exc.code,
        context=dict(exc.context),
    )
    # Arayuz hem MessageBox'ta hem sohbet balonunda ayni metni gostersin diye
    # birlesik gosterim de saklanir.
    humanized.context.setdefault("cozum", remedy)
    return humanized


# --------------------------------------------------------------------------
#  Cikti tipleri
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AIResult:
    """Bir yapay zeka cagrisinin sonucu ve olcumleri.

    ``is_ai_generated`` alani ``init=False`` ile her zaman ``True``'dur:
    bu servisten donen hicbir metin "insan yazmis" gibi isaretlenemez.
    Arayuz bu bayragi gorup :class:`~app.ui.widgets.common.AiBadge` gosterir.
    """

    content: str
    task_type: AITaskType
    reasoning: str = ""
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    estimated_cost: Decimal = Decimal("0.000000")
    cost_currency: Currency = Currency.USD
    used_fallback: bool = False
    usage_id: int | None = None

    is_ai_generated: bool = field(default=True, init=False)

    @property
    def has_reasoning(self) -> bool:
        """Gosterilebilecek bir akil yurutme metni var mi?"""
        return bool(self.reasoning.strip())

    @property
    def duration_text(self) -> str:
        """``1,4 sn`` bicimi."""
        return f"{self.latency_ms / 1000:.1f}".replace(".", ",") + " sn"

    @property
    def cost_text(self) -> str:
        """``0,001200 USD`` bicimi; yerel modellerde ``ucretsiz``."""
        if self.estimated_cost <= 0:
            return "ucretsiz"
        return f"{self.estimated_cost:.6f}".replace(".", ",") + f" {self.cost_currency.value}"

    @property
    def marked_content(self) -> str:
        """Icerik + seffaflik isareti."""
        return f"{self.content}\n\n{AI_GENERATED_MARKER}"


class DraftKind(str, Enum):
    """Taslak metin turu."""

    RESERVATION_CONFIRMATION = "reservation_confirmation"
    COMPLAINT_RESPONSE = "complaint_response"
    ARRIVAL_INFORMATION = "arrival_information"
    THANK_YOU = "thank_you"

    @property
    def label(self) -> str:
        return _DRAFT_LABELS[self]

    @property
    def task_type(self) -> AITaskType:
        return (
            AITaskType.COMPLAINT_RESPONSE
            if self is DraftKind.COMPLAINT_RESPONSE
            else AITaskType.MESSAGE_DRAFT
        )


_DRAFT_LABELS: Final[dict[DraftKind, str]] = {
    DraftKind.RESERVATION_CONFIRMATION: "Rezervasyon onayi",
    DraftKind.COMPLAINT_RESPONSE: "Sikayet yaniti",
    DraftKind.ARRIVAL_INFORMATION: "Giris bilgilendirmesi",
    DraftKind.THANK_YOU: "Tesekkur mesaji",
}

_DRAFT_INSTRUCTIONS: Final[dict[DraftKind, str]] = {
    DraftKind.RESERVATION_CONFIRMATION: (
        "Misafire gönderilecek kısa bir rezervasyon onay metni yaz. Giriş-çıkış "
        "saatleri ve iletişim için otelin aranabileceği nazikçe belirtilsin."
    ),
    DraftKind.COMPLAINT_RESPONSE: (
        "Misafirin şikayetine karşı özür dileyen, sorumluluk alan ve somut bir "
        "çözüm adımı öneren kibar bir yanıt yaz. Savunmacı olma, suçlama."
    ),
    DraftKind.ARRIVAL_INFORMATION: (
        "Yaklaşan konaklama için giriş bilgilendirme metni yaz: giriş saati, "
        "gerekli belgeler ve ulaşım hakkında kısa bilgi."
    ),
    DraftKind.THANK_YOU: ("Konaklama sonrası kısa bir teşekkür metni yaz ve geri bildirim iste."),
}


@dataclass(frozen=True, slots=True)
class AIDraft:
    """Yapay zekanin urettigi mesaj taslagi.

    Taslak **gonderilmez**; yalnizca kullaniciya sunulur. ``is_ai_generated``
    degistirilemez (``init=False``), boylece taslak arayuzde her zaman
    "AI tarafindan olusturuldu" rozetiyle gorunur.
    """

    kind: DraftKind
    body: str
    result: AIResult
    is_ai_generated: bool = field(default=True, init=False)

    @property
    def marked_text(self) -> str:
        """Gonderilmeden once kullaniciya gosterilen, isaretli tam metin."""
        return f"{self.body.strip()}\n\n---\n{AI_GENERATED_MARKER}"


@dataclass(frozen=True, slots=True)
class PricingSuggestionItem:
    """Tek bir fiyat onerisi satiri.

    ``suggested_rate`` bir **oneridir**; hicbir tabloya yazilmaz. Mevcut fiyat
    veritabanindan okunur ki kullanici degisimin buyuklugunu gorebilsin.
    """

    day: date | None
    room_type: str
    current_rate: Money | None
    suggested_rate: Money | None
    rationale: str = ""

    @property
    def change_percent(self) -> float | None:
        """Onerilen fiyatin mevcuda gore degisim yuzdesi."""
        if self.current_rate is None or self.suggested_rate is None:
            return None
        if self.current_rate.amount <= 0:
            return None
        delta = self.suggested_rate.amount - self.current_rate.amount
        return round(float(delta / self.current_rate.amount) * 100, 1)


@dataclass(frozen=True, slots=True)
class PricingSuggestion:
    """Fiyat **onerisi** - uygulanmis bir fiyat degisikligi DEGILDIR.

    ``applied`` alani ``init=False`` ile tanimlanmistir: hicbir cagiran bu
    nesneyi "uygulanmis" olarak uretemez. Fiyati fiilen degistiren tek yer
    Fiyatlar ekranidir ve orada kullanicinin ayrica onaylamasi gerekir.
    ``advisory_note`` arayuzde **zorunlu** olarak gosterilir.
    """

    date_range: DateRange
    summary: str
    items: tuple[PricingSuggestionItem, ...]
    result: AIResult
    applied: bool = field(default=False, init=False)
    advisory_note: str = field(default=PRICING_ADVISORY_NOTE, init=False)

    @property
    def is_advisory(self) -> bool:
        """Her zaman ``True``; okunurlugu artirmak icin acikca sunulur."""
        return True


@dataclass(frozen=True, slots=True)
class ReviewClassification:
    """Misafir yorumunun duygu analizi ve kategori siniflandirmasi."""

    sentiment: str
    """``olumlu`` | ``notr`` | ``olumsuz``"""

    score: float
    """-1.0 (cok olumsuz) ile 1.0 (cok olumlu) arasi."""

    categories: tuple[str, ...]
    summary: str
    is_urgent: bool
    result: AIResult

    @property
    def sentiment_level(self) -> str:
        """Arayuz rozeti icin seviye: ``success`` | ``warning`` | ``danger``."""
        if self.sentiment == "olumlu":
            return "success"
        if self.sentiment == "olumsuz":
            return "danger"
        return "warning"


@dataclass(frozen=True, slots=True)
class DailyFacts:
    """Gunluk ozetin modele gonderilen **tum** girdisi.

    Bu yapida bilincli olarak **hicbir metin alani yoktur**: yalnizca tarih ve
    sayilar. Gunluk ozet istemi bu nesneden uretildigi icin misafir adi,
    kimlik numarasi, e-posta veya telefonun modele gitmesi yapisal olarak
    imkansizdir (bkz. ``tests/application/test_ai_service.py``).
    """

    day: date
    total_rooms: int
    sellable_room_nights: int
    sold_room_nights: int
    occupancy_percent: float
    arrivals: int
    departures: int
    in_house: int
    room_revenue: Decimal
    other_revenue: Decimal
    total_revenue: Decimal
    adr: Decimal
    revpar: Decimal
    cancellation_percent: float
    no_show_percent: float
    pending_housekeeping: int
    open_maintenance: int
    low_stock_items: int
    currency: str

    def to_payload(self) -> dict[str, Any]:
        """Modele gonderilecek JSON govdesi - yalnizca sayi ve tarih."""
        return {
            "gun": self.day.isoformat(),
            "para_birimi": self.currency,
            "toplam_oda": self.total_rooms,
            "satilabilir_oda_gecesi": self.sellable_room_nights,
            "satilan_oda_gecesi": self.sold_room_nights,
            "doluluk_yuzde": self.occupancy_percent,
            "giris_sayisi": self.arrivals,
            "cikis_sayisi": self.departures,
            "otelde_kalan_oda": self.in_house,
            "oda_geliri": float(self.room_revenue),
            "diger_gelir": float(self.other_revenue),
            "toplam_gelir": float(self.total_revenue),
            "adr": float(self.adr),
            "revpar": float(self.revpar),
            "iptal_yuzde": self.cancellation_percent,
            "gelmeme_yuzde": self.no_show_percent,
            "bekleyen_temizlik_gorevi": self.pending_housekeeping,
            "acik_ariza_kaydi": self.open_maintenance,
            "kritik_stok_kalemi": self.low_stock_items,
        }


# --------------------------------------------------------------------------
#  Sistem istemleri
# --------------------------------------------------------------------------
_BASE_SYSTEM: Final[str] = (
    "Sen bir otel yönetim yazılımının Türkçe konuşan yardımcısısın. "
    "Yanıtların kısa, somut ve Türkçe olsun. Sana verilen sayıların dışına çıkma, "
    "veri uydurma. Emin olmadığın konuda 'veri yetersiz' de. "
    "Misafirlerin adı, kimlik numarası, e-posta veya telefonu sana verilmez ve "
    "bunları asla isteme."
)

_JSON_SYSTEM_SUFFIX: Final[str] = (
    " Yanıtını YALNIZCA geçerli bir JSON nesnesi olarak ver. Açıklama, kod bloğu "
    "işareti veya başka metin ekleme."
)


class AIService:
    """Yapay zeka gorevlerini calistiran salt okunur servis.

    Parameters
    ----------
    context:
        Servis baglami (oturum, kullanici, tesis).
    registry:
        Saglayici kaydi. Verilmezse uygulama genelindeki tekil kayit
        kullanilir. Testler kendi sahte saglayicilarini bu parametreyle
        gecirir - bu sayede **hicbir test ag cagrisi yapmaz**.
    model:
        Kullanicinin arayuzden sectigi model kimligi. Bos ise gorev turune
        gore :mod:`app.ai.catalog` karar verir.
    """

    def __init__(
        self,
        context: ServiceContext,
        *,
        registry: ProviderRegistry | None = None,
        model: str = "",
    ) -> None:
        self.ctx = context
        self.session = context.session
        self.registry = registry if registry is not None else get_registry()
        self.settings = self.registry.settings
        self.model = model.strip()

    # ------------------------------------------------------------------ #
    #  Durum
    # ------------------------------------------------------------------ #
    @property
    def is_enabled(self) -> bool:
        """Yapay zeka ayarlardan etkinlestirilmis mi?"""
        return bool(self.settings.enabled)

    def provider_names(self) -> list[str]:
        """Istek zincirindeki saglayici adlari (once birincil)."""
        return [name.value for name in self.registry.configured_names()]

    def model_options(self) -> list[str]:
        """Arayuzdeki model listesi.

        Once yapilandirilmis model, sonra katalogdaki onerilen modeller gelir.
        Katalog yalnizca LM Studio modellerini kesin olarak bilir; uzak
        saglayicilarda liste bos kalabilir ve model secimi saglayiciya birakilir.
        """
        options: list[str] = []
        provider_settings = self.settings.provider_settings(self.settings.primary_provider)
        configured = getattr(provider_settings, "chat_model", "") if provider_settings else ""
        if configured:
            options.append(configured)
        for spec in catalog.LMSTUDIO_MODELS:
            if spec.recommended_default and spec.model_id not in options:
                options.append(spec.model_id)
        return options

    def provider_status(self) -> dict[str, HealthStatus]:
        """Saglayicilarin erisilebilirlik durumu. **Ag cagrisi yapar.**

        Hata firlatmaz; ulasilamayan saglayici ``ok=False`` ile doner. Arayuz
        bunu arka plan is parcaciginda cagirmalidir.
        """
        self.ctx.require(Perm.AI_USE)
        if not self.is_enabled:
            return {}
        return self.registry.health_report()

    # ------------------------------------------------------------------ #
    #  Gorevler
    # ------------------------------------------------------------------ #
    def daily_summary(self, day: date | None = None) -> AIResult:
        """Gunun panel verilerini modele ozetletir.

        **Gizlilik sozlesmesi:** modele gonderilen istem
        :class:`DailyFacts` nesnesinden uretilir ve yalnizca tarih + sayisal
        toplamlar icerir. Misafir adi, kimlik numarasi, e-posta ve telefon
        istemde **BULUNMAZ**; rezervasyon veya misafir kayitlarindan hicbir
        metin alani okunmaz. Bu kural
        ``tests/application/test_ai_service.py::TestGizlilik`` ile sinanir.
        """
        facts = self.collect_daily_facts(day)
        payload = json.dumps(facts.to_payload(), ensure_ascii=False, indent=None)
        messages = [
            ChatMessage.system(
                _BASE_SYSTEM + " Sana bir günün özet göstergeleri JSON olarak verilir. "
                "En fazla 6 madde halinde: durumu özetle, dikkat edilmesi gereken "
                "noktaları ve bugün için somut bir öneriyi yaz."
            ),
            ChatMessage.user(payload),
        ]
        return self._run(
            AITaskType.DAILY_SUMMARY,
            messages,
            max_tokens=TEXT_TASK_MAX_TOKENS,
        )

    def occupancy_analysis(self, date_range: DateRange) -> AIResult:
        """Donem dolulugunu gun bazinda modele yorumlatir.

        Istem, :func:`app.reporting.queries.occupancy_report` ciktisindan
        uretilir; o rapor yalnizca oda **sayilari** icerir, misafir bilgisi
        icermez. Cok uzun donemlerde ilk :data:`MAX_ANALYSIS_DAYS` gun
        gonderilir - baglam penceresini asan bir istem, modelin sessizce
        veri kaybetmesine yol acar.
        """
        property_id = self.ctx.require_property()
        table = queries.occupancy_report(self.session, property_id, date_range)
        kpis = queries.kpi_report(self.session, property_id, date_range)

        gunler = [
            {
                "gun": row["gun"].isoformat(),
                "satilabilir": int(row["satilabilir_oda"]),
                "dolu": int(row["dolu_oda"]),
                "doluluk_yuzde": float(row["doluluk"]),
            }
            for row in table.rows[:MAX_ANALYSIS_DAYS]
        ]
        payload = {
            "donem": {
                "baslangic": date_range.start.isoformat(),
                "bitis": date_range.end.isoformat(),
            },
            "gece_sayisi": date_range.nights,
            "ozet": _kpi_payload(kpis),
            "gunler": gunler,
        }
        messages = [
            ChatMessage.system(
                _BASE_SYSTEM + " Sana bir dönemin gün gün doluluk verisi JSON olarak verilir. "
                "Eğilimi, en yoğun ve en zayıf günleri, hafta içi/hafta sonu farkını "
                "yorumla ve en fazla 3 somut aksiyon öner."
            ),
            ChatMessage.user(json.dumps(payload, ensure_ascii=False)),
        ]
        return self._run(
            AITaskType.OCCUPANCY_ANALYSIS,
            messages,
            max_tokens=TEXT_TASK_MAX_TOKENS,
        )

    def pricing_suggestion(self, date_range: DateRange) -> PricingSuggestion:
        """Donem icin fiyat **onerisi** uretir - hicbir fiyati DEGISTIRMEZ.

        Donen :class:`PricingSuggestion` nesnesinin ``applied`` alani
        ``init=False`` ile sabit ``False``'tur. Servis oda tipi tablosunu
        yalnizca **okur**; ``UPDATE``/``INSERT`` yapmaz. Fiyatin fiilen
        degismesi icin kullanicinin Fiyatlar ekranindan onaylamasi gerekir.
        """
        property_id = self.ctx.require_property()
        table = queries.occupancy_report(self.session, property_id, date_range)
        kpis = queries.kpi_report(self.session, property_id, date_range)
        room_types = list(
            self.session.scalars(
                select(RoomType)
                .where(RoomType.property_id == property_id, RoomType.is_active.is_(True))
                .order_by(RoomType.name)
            ).all()
        )
        currency = kpis.adr.currency
        current_rates = {rt.name: Money.of(rt.base_rate, currency) for rt in room_types}

        payload = {
            "donem": {
                "baslangic": date_range.start.isoformat(),
                "bitis": date_range.end.isoformat(),
            },
            "para_birimi": currency.value,
            "ozet": _kpi_payload(kpis),
            "gunler": [
                {
                    "gun": row["gun"].isoformat(),
                    "doluluk_yuzde": float(row["doluluk"]),
                    "bos_oda": int(row["bos_oda"]),
                }
                for row in table.rows[:MAX_ANALYSIS_DAYS]
            ],
            "oda_tipleri": [
                {"ad": name, "mevcut_fiyat": float(money.amount)}
                for name, money in current_rates.items()
            ],
        }
        messages = [
            ChatMessage.system(
                _BASE_SYSTEM + " Doluluk ve mevcut fiyatlara bakarak fiyat ÖNERİSİ üret. "
                "Önerdiğin fiyatlar uygulanmaz; yalnızca kullanıcıya sunulur. "
                'Şu şemayı kullan: {"ozet": "...", "oneriler": [{"tarih": "YYYY-AA-GG", '
                '"oda_tipi": "...", "onerilen_fiyat": 0, "gerekce": "..."}]}. '
                "En fazla 8 öneri ver." + _JSON_SYSTEM_SUFFIX
            ),
            ChatMessage.user(json.dumps(payload, ensure_ascii=False)),
        ]
        result = self._run(
            AITaskType.PRICING_SUGGESTION,
            messages,
            max_tokens=JSON_TASK_MAX_TOKENS,
            temperature=0.2,
        )
        data = self._parse_json_object(result)

        items: list[PricingSuggestionItem] = []
        for raw in _as_list(data.get("oneriler")):
            if not isinstance(raw, Mapping):
                continue
            room_type = str(raw.get("oda_tipi") or "").strip()
            items.append(
                PricingSuggestionItem(
                    day=_parse_date(raw.get("tarih")),
                    room_type=room_type or "Belirtilmemis",
                    current_rate=current_rates.get(room_type),
                    suggested_rate=_parse_money(raw.get("onerilen_fiyat"), currency),
                    rationale=str(raw.get("gerekce") or "").strip(),
                )
            )

        return PricingSuggestion(
            date_range=date_range,
            summary=str(data.get("ozet") or result.content).strip(),
            items=tuple(items),
            result=result,
        )

    def draft_message(self, kind: DraftKind, context: Mapping[str, Any]) -> AIDraft:
        """Misafire gonderilecek bir metin **taslagi** uretir.

        ``context`` kullanicinin serbest yazdigi bilgidir; her deger
        :func:`redact_personal_data` ile maskelenir - kimlik numarasi,
        e-posta ve telefon modele gitmez. Taslak **gonderilmez**; kullaniciya
        "AI tarafindan olusturuldu" isaretiyle sunulur.
        """
        safe_context = {
            str(key): redact_personal_data(_as_text(value))
            for key, value in context.items()
            if _as_text(value).strip()
        }
        if not safe_context:
            raise ValidationError(
                "Taslak oluşturmak için önce bağlam yazmalısınız.",
                field="context",
                detail="draft_message bos baglam ile cagrildi",
            )

        messages = [
            ChatMessage.system(
                _BASE_SYSTEM
                + " "
                + _DRAFT_INSTRUCTIONS[kind]
                + " Metni doğrudan gönderilebilecek şekilde yaz; köşeli parantezli "
                "yer tutucu bırakma. En fazla 150 kelime."
            ),
            ChatMessage.user(json.dumps(safe_context, ensure_ascii=False)),
        ]
        result = self._run(kind.task_type, messages, max_tokens=TEXT_TASK_MAX_TOKENS)
        return AIDraft(kind=kind, body=result.content.strip(), result=result)

    def classify_review(self, text: str) -> ReviewClassification:
        """Misafir yorumunun duygusunu ve kategorilerini belirler.

        Yorum metni kullanicidan gelir; iletisim bilgileri maskelenerek
        gonderilir. Model gecerli JSON uretemezse anlasilir bir hata firlatilir
        (bkz. :func:`app.ai.errors.json_format_error`).
        """
        cleaned = _require_text(text, field_name="text")
        messages = [
            ChatMessage.system(
                _BASE_SYSTEM + " Misafir yorumunu sınıflandır. Şema: "
                '{"duygu": "olumlu|notr|olumsuz", "puan": -1.0..1.0, '
                '"kategoriler": ["temizlik", "personel", ...], "ozet": "...", '
                '"acil": true|false}. "acil" alanı, otelin bugün müdahale etmesi '
                "gereken bir durum varsa true olsun." + _JSON_SYSTEM_SUFFIX
            ),
            ChatMessage.user(redact_personal_data(cleaned)),
        ]
        result = self._run(
            AITaskType.REVIEW_CLASSIFICATION,
            messages,
            max_tokens=JSON_TASK_MAX_TOKENS,
            temperature=0.1,
        )
        data = self._parse_json_object(result)

        sentiment = str(data.get("duygu") or "notr").strip().lower()
        if sentiment not in {"olumlu", "notr", "olumsuz"}:
            sentiment = "notr"

        return ReviewClassification(
            sentiment=sentiment,
            score=_parse_score(data.get("puan")),
            categories=tuple(
                str(item).strip() for item in _as_list(data.get("kategoriler")) if str(item).strip()
            ),
            summary=str(data.get("ozet") or "").strip(),
            is_urgent=bool(data.get("acil")),
            result=result,
        )

    def ask(self, question: str, conversation_id: int | None = None) -> AIResult:
        """Serbest soru sorar.

        ``conversation_id`` verilirse gecmis mesajlar **okunur** ve baglama
        eklenir; bu servis sohbet gecmisine yazmaz (salt okunur sozlesmesi).
        Baglam penceresi :data:`CONVERSATION_WINDOW` mesajla sinirlidir.
        """
        cleaned = _require_text(question, field_name="question")
        messages: list[ChatMessage] = [
            ChatMessage.system(
                _BASE_SYSTEM + " Kullanıcı otel personelidir. Sorusuna doğrudan ve kısa yanıt ver. "
                "Veritabanına erişimin yok; sayı isteyen sorularda Raporlar ekranını öner."
            )
        ]
        messages.extend(self._conversation_history(conversation_id))
        messages.append(ChatMessage.user(redact_personal_data(cleaned)))
        return self._run(AITaskType.GENERAL_CHAT, messages, max_tokens=TEXT_TASK_MAX_TOKENS)

    # ------------------------------------------------------------------ #
    #  Veri toplama (salt okunur)
    # ------------------------------------------------------------------ #
    def collect_daily_facts(self, day: date | None = None) -> DailyFacts:
        """Gunluk ozetin sayisal girdilerini toplar.

        Ayri bir metot olmasinin nedeni **test edilebilirlik**: modele
        gonderilen verinin sayilardan ibaret oldugu, ag cagrisi yapmadan
        dogrulanabilir.
        """
        self.ctx.require(Perm.AI_USE)
        property_id = self.ctx.require_property()
        target = day or utcnow().date()
        window = DateRange.single_night(target)
        kpis = queries.kpi_report(self.session, property_id, window)

        movements = self._movement_counts(property_id, target)
        return DailyFacts(
            day=target,
            total_rooms=self._active_room_count(property_id),
            sellable_room_nights=kpis.available_room_nights,
            sold_room_nights=kpis.room_nights_sold,
            occupancy_percent=kpis.occupancy_percent,
            arrivals=movements["arrivals"],
            departures=movements["departures"],
            in_house=movements["in_house"],
            room_revenue=kpis.room_revenue.amount,
            other_revenue=kpis.other_revenue.amount,
            total_revenue=kpis.total_revenue.amount,
            adr=kpis.adr.amount,
            revpar=kpis.revpar.amount,
            cancellation_percent=round(kpis.cancellation_rate * 100, 2),
            no_show_percent=round(kpis.no_show_rate * 100, 2),
            pending_housekeeping=self._pending_housekeeping(property_id, target),
            open_maintenance=self._open_maintenance(property_id),
            low_stock_items=self._low_stock_items(property_id),
            currency=kpis.total_revenue.currency.value,
        )

    # ---------------- Sayim sorgulari ----------------
    def _active_room_count(self, property_id: int) -> int:
        from app.infrastructure.db.models.rooms import Room

        return int(
            self.session.scalar(
                select(func.count(Room.id)).where(
                    Room.property_id == property_id, Room.is_active.is_(True)
                )
            )
            or 0
        )

    def _movement_counts(self, property_id: int, day: date) -> dict[str, int]:
        """Girisi/cikisi/otelde kalani **sayar** - hicbir isim okunmaz."""
        base = (
            select(func.count(ReservationRoom.id))
            .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
            .where(
                Reservation.property_id == property_id,
                Reservation.is_deleted.is_(False),
                Reservation.status.in_(tuple(queries.OPERATIONAL_RESERVATION_STATUSES)),
                ReservationRoom.is_cancelled.is_(False),
            )
        )
        return {
            "arrivals": int(
                self.session.scalar(base.where(ReservationRoom.check_in_date == day)) or 0
            ),
            "departures": int(
                self.session.scalar(base.where(ReservationRoom.check_out_date == day)) or 0
            ),
            "in_house": int(
                self.session.scalar(
                    base.where(
                        ReservationRoom.check_in_date <= day,
                        ReservationRoom.check_out_date > day,
                    )
                )
                or 0
            ),
        }

    def _pending_housekeeping(self, property_id: int, day: date) -> int:
        return int(
            self.session.scalar(
                select(func.count(HousekeepingTask.id)).where(
                    HousekeepingTask.property_id == property_id,
                    HousekeepingTask.scheduled_date <= day,
                    HousekeepingTask.status.in_(
                        (
                            HousekeepingStatus.PENDING,
                            HousekeepingStatus.ASSIGNED,
                            HousekeepingStatus.IN_PROGRESS,
                        )
                    ),
                )
            )
            or 0
        )

    def _open_maintenance(self, property_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(MaintenanceTicket.id)).where(
                    MaintenanceTicket.property_id == property_id,
                    MaintenanceTicket.status.in_(
                        (
                            MaintenanceStatus.OPEN,
                            MaintenanceStatus.ASSIGNED,
                            MaintenanceStatus.IN_PROGRESS,
                            MaintenanceStatus.WAITING_PARTS,
                        )
                    ),
                )
            )
            or 0
        )

    def _low_stock_items(self, property_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.property_id == property_id,
                    InventoryItem.is_active.is_(True),
                    InventoryItem.current_stock < InventoryItem.minimum_stock,
                )
            )
            or 0
        )

    def _conversation_history(self, conversation_id: int | None) -> list[ChatMessage]:
        """Sohbet gecmisini **okur**; yazma yapmaz.

        Gecmis yalnizca **cagiran kullanicinin kendi** sohbetinden okunur.
        Ham kimlikle sorgulamak, ileride bir ekran kullanicidan gelen bir
        numarayi buraya gecirdiginde baskasinin sohbetini modele tasirdi;
        sohbetler serbest metindir ve icinde her sey bulunabilir. Baskasina
        ait ya da bulunamayan kimlik icin gecmis **sessizce bos** doner -
        "boyle bir sohbet var ama sizin degil" demek de bilgi sizdirir.
        """
        if conversation_id is None:
            return []
        self.ctx.require(Perm.AI_USE)
        conversation = self.session.get(AIConversation, conversation_id)
        if conversation is None or conversation.user_id != self.ctx.user_id:
            return []
        rows = list(
            self.session.scalars(
                select(AIMessage)
                .where(AIMessage.conversation_id == conversation_id)
                .order_by(AIMessage.id.desc())
                .limit(CONVERSATION_WINDOW)
            ).all()
        )
        rows.reverse()
        history: list[ChatMessage] = []
        for row in rows:
            if row.role == "assistant":
                history.append(ChatMessage.assistant(redact_personal_data(row.content)))
            elif row.role == "user":
                history.append(ChatMessage.user(redact_personal_data(row.content)))
        return history

    # ------------------------------------------------------------------ #
    #  Cekirdek cagri
    # ------------------------------------------------------------------ #
    def _run(
        self,
        task_type: AITaskType,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = TEXT_TASK_MAX_TOKENS,
        temperature: float | None = None,
    ) -> AIResult:
        """Yetki -> gizlilik -> cagri -> kullanim kaydi zincirini calistirir."""
        self.ctx.require(Perm.AI_USE)
        self._ensure_enabled(task_type)
        assert_prompt_is_anonymous(messages)

        request = ChatRequest(
            messages=list(messages),
            model=self.model,
            temperature=(
                temperature if temperature is not None else self.settings.default_temperature
            ),
            max_tokens=max_tokens,
            timeout=float(self.settings.default_timeout),
        )

        started = time.monotonic()
        try:
            response = self.registry.chat_with_fallback(request, task_type)
        except AIProviderError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            humanized = humanize_provider_error(exc, is_local=self._primary_is_local())
            self._record_usage(
                task_type=task_type,
                status=_ERROR_STATUS.get(type(exc), AIUsageStatus.FAILED),
                model=self.model,
                provider=exc.provider or "",
                latency_ms=elapsed,
                error=humanized,
            )
            self.ctx.audit(
                AuditAction.AI_REQUEST,
                f"Yapay zeka cagrisi basarisiz: {task_type.value}",
                entity_type="AIUsage",
                is_success=False,
            )
            log.warning(
                "ai_cagrisi_basarisiz",
                gorev=task_type.value,
                kod=humanized.code,
                saglayici=humanized.provider,
            )
            raise humanized from exc

        usage = self._record_usage(
            task_type=task_type,
            status=(
                AIUsageStatus.FALLBACK_USED if response.used_fallback else AIUsageStatus.SUCCESS
            ),
            model=response.model or self.model,
            provider=response.provider,
            latency_ms=response.latency_ms,
            response=response,
        )
        self.ctx.audit(
            AuditAction.AI_REQUEST,
            f"Yapay zeka cagrisi: {task_type.value}",
            entity_type="AIUsage",
            entity_id=usage.id,
        )
        return AIResult(
            content=response.content.strip(),
            task_type=task_type,
            reasoning=response.reasoning.strip(),
            model=response.model or self.model,
            provider=response.provider,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            reasoning_tokens=response.reasoning_tokens,
            total_tokens=response.total_tokens,
            latency_ms=response.latency_ms,
            estimated_cost=usage.estimated_cost,
            cost_currency=usage.cost_currency,
            used_fallback=response.used_fallback,
            usage_id=usage.id,
        )

    def _ensure_enabled(self, task_type: AITaskType) -> None:
        """Yapay zeka kapaliysa anlamli hata verir ve engellemeyi kaydeder."""
        if self.is_enabled:
            return
        self._record_usage(
            task_type=task_type,
            status=AIUsageStatus.BLOCKED,
            model=self.model,
            provider="",
            latency_ms=0,
        )
        raise ConfigurationError(
            "Yapay zeka özellikleri şu anda kapalı.",
            code="ai_disabled",
            detail="AISettings.enabled=False",
            context={"cozum": REMEDY_AI_DISABLED},
        )

    def _primary_is_local(self) -> bool:
        """Birincil saglayici yerel mi? Baglanti oneri metnini belirler."""
        try:
            return bool(self.registry.primary().is_local)
        except ConfigurationError:  # pragma: no cover - bozuk yapilandirma
            return True

    def _record_usage(
        self,
        *,
        task_type: AITaskType,
        status: AIUsageStatus,
        model: str,
        provider: str,
        latency_ms: int,
        response: ChatResponse | None = None,
        error: AIProviderError | None = None,
    ) -> AIUsage:
        """Cagrinin kullanim kaydini yazar (basarili ve basarisiz cagrilar icin).

        ``flush`` yapilir ama ``commit`` YAPILMAZ: kayit cagiranin islemine
        aittir. Boylece ayni islemdeki denetim kaydiyla tutarli kalir.
        """
        prompt_tokens = response.prompt_tokens if response else 0
        completion_tokens = response.completion_tokens if response else 0
        usage = AIUsage(
            provider_id=self._provider_row_id(provider),
            model_name=model or (response.model if response else None) or None,
            user_id=self.ctx.user_id,
            task_type=task_type,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=response.reasoning_tokens if response else 0,
            total_tokens=response.total_tokens if response else 0,
            estimated_cost=catalog.estimate_cost(
                model or (response.model if response else "") or "",
                prompt_tokens,
                completion_tokens,
            ),
            cost_currency=Currency.USD,
            latency_ms=latency_ms,
            error_code=error.code if error else None,
            error_message=(error.user_message[:500] if error else None),
            fell_back_from=(
                self.settings.primary_provider.value
                if response is not None and response.used_fallback
                else None
            ),
        )
        self.session.add(usage)
        self.session.flush()
        return usage

    def _provider_row_id(self, provider_code: str) -> int | None:
        """Saglayici kodundan veritabani satirini bulur; yoksa ``None``.

        Saglayici tablosu bos olabilir (yapilandirma tamamen ``.env``'den
        gelebilir); bu durumda kullanim kaydi saglayici baglantisi olmadan
        yazilir - kayit kaybetmek, eksik iliskiden daha kotudur.
        """
        if not provider_code:
            return None
        return self.session.scalar(
            select(AIProviderRow.id).where(AIProviderRow.code == provider_code)
        )

    def _parse_json_object(self, result: AIResult) -> dict[str, Any]:
        """Model ciktisindan JSON nesnesi cikarir.

        Modeller JSON'u sik sik ``` isaretleri arasinda ya da bir cumleyle
        birlikte dondurur; bu yuzden ham metin yerine ilk ``{`` ile son ``}``
        arasi ayristirilir. Gecerli JSON yoksa kullanim kaydi **basarisiz**
        olarak guncellenir ve anlasilir bir hata firlatilir.
        """
        block = _extract_json_block(result.content)
        data: Any = None
        if block:
            try:
                data = json.loads(block)
            except json.JSONDecodeError as exc:
                data = None
                log.warning("ai_json_ayristirilamadi", gorev=result.task_type.value, hata=str(exc))
        if not isinstance(data, dict):
            self._mark_usage_failed(result.usage_id, "ai_response_format_error")
            raise humanize_provider_error(
                errors.json_format_error(
                    provider=result.provider,
                    model=result.model,
                    detail=f"gecersiz JSON, uzunluk={len(result.content)}",
                ),
                is_local=self._primary_is_local(),
            )
        return data

    def _mark_usage_failed(self, usage_id: int | None, error_code: str) -> None:
        """Cagri sonrasi asamada (or. JSON ayristirma) basarisizligi isaretler."""
        if usage_id is None:
            return
        usage = self.session.get(AIUsage, usage_id)
        if usage is None:  # pragma: no cover - ayni islemde silinmis olamaz
            return
        usage.status = AIUsageStatus.FAILED
        usage.error_code = error_code
        usage.error_message = "Model beklenen JSON biçimini üretemedi."
        self.session.flush()


# --------------------------------------------------------------------------
#  Yardimcilar
# --------------------------------------------------------------------------
def _kpi_payload(kpis: KPISet) -> dict[str, Any]:
    """KPI kumesini sayisal JSON govdesine cevirir (metin alani yok)."""
    return {
        "doluluk_yuzde": kpis.occupancy_percent,
        "adr": float(kpis.adr.amount),
        "revpar": float(kpis.revpar.amount),
        "alos": kpis.alos,
        "iptal_yuzde": round(kpis.cancellation_rate * 100, 2),
        "gelmeme_yuzde": round(kpis.no_show_rate * 100, 2),
        "oda_geliri": float(kpis.room_revenue.amount),
        "toplam_gelir": float(kpis.total_revenue.amount),
        "satilan_oda_gecesi": kpis.room_nights_sold,
        "satilabilir_oda_gecesi": kpis.available_room_nights,
    }


def _extract_json_block(text: str) -> str:
    """Metinden ilk JSON nesnesini cikarir; bulunamazsa bos dizge."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # ```json ... ``` bloklarini soy.
        parts = cleaned.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("{"):
                cleaned = stripped
                break
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return ""
    return cleaned[start : end + 1]


def _as_list(value: Any) -> list[Any]:
    """Modelin tek nesne dondurdugu durumu da listeye cevirir."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _require_text(value: str, *, field_name: str) -> str:
    """Bos olmayan, makul uzunlukta metin dogrular."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValidationError(
            "Önce bir metin yazmalısınız.",
            field=field_name,
            detail=f"{field_name} bos",
        )
    return cleaned[:MAX_FREE_TEXT_CHARS]


def _parse_date(value: Any) -> date | None:
    """``YYYY-AA-GG`` metnini tarihe cevirir; cevrilemezse ``None``."""
    if isinstance(value, date):
        return value
    text = _as_text(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_money(value: Any, currency: Currency) -> Money | None:
    """Model ciktisindaki sayiyi ``Money``'ye cevirir; gecersizse ``None``.

    Para tutarlari modele **hesaplattirilmaz**; burada yalnizca modelin
    onerdigi sayi guvenli bicimde okunur ve ``Decimal`` olarak tutulur.
    ``float`` ile devam etmek kurus hatasi uretirdi.
    """
    if value is None:
        return None
    try:
        return Money.of(Decimal(str(value)), currency)
    except (ArithmeticError, ValueError, TypeError):
        return None


def _parse_score(value: Any) -> float:
    """Duygu puanini ``-1.0 .. 1.0`` araligina sikistirir."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, round(score, 3)))


__all__ = [
    "AI_GENERATED_MARKER",
    "CONVERSATION_WINDOW",
    "MAX_ANALYSIS_DAYS",
    "PRICING_ADVISORY_NOTE",
    "REMEDY_AI_DISABLED",
    "AIDraft",
    "AIResult",
    "AIService",
    "DailyFacts",
    "DraftKind",
    "PricingSuggestion",
    "PricingSuggestionItem",
    "ReviewClassification",
    "assert_prompt_is_anonymous",
    "find_personal_data",
    "humanize_provider_error",
    "redact_personal_data",
]
