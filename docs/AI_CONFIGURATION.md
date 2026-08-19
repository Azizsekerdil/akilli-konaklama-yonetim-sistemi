# Yapay Zekâ Yapılandırması

Bu belge, uygulamanın yapay zekâ katmanının **nasıl kurgulandığını**, hangi
ayarların ne işe yaradığını ve yapay zekânın **neyi yapamayacağını** anlatır.

Belgedeki her teknik iddia kaynak kodundan doğrulanmıştır; ilgili dosya ve
satır aralıkları metin içinde verilmiştir. Doğrulanamayan veya yarım kalan
noktalar **açıkça işaretlenmiştir**.

İlgili belgeler: [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) ·
[NVIDIA_API_SETUP.md](NVIDIA_API_SETUP.md) ·
[NVIDIA_MODEL_EVALUATION.md](NVIDIA_MODEL_EVALUATION.md) ·
[ROADMAP.md](ROADMAP.md)

---

## 1. Sağlayıcı mimarisi

### Neden bir soyutlama katmanı var?

Bir otel yazılımının ömrü, bir dil modeli sağlayıcısının fiyat listesinden
uzundur. LM Studio bugün ücretsiz, NVIDIA yarın kota koyabilir, Anthropic
şemasını değiştirebilir. Sağlayıcıyı doğrudan çağıran bir kod, her değişimde
uygulamanın her yerinde düzeltme ister.

Bu yüzden katman **tek bir sözleşme** etrafında kurulur: istek gönder,
normalleştirilmiş yanıt al, hata olursa kullanıcının anlayacağı bir çözüm
önerisiyle bildir. Sağlayıcıya özgü hiçbir biçim üst katmanlara sızmaz —
tek istisna, hata ayıklama için saklanan ham yanıttır (`ChatResponse.raw`).

### Katmanlar

```
app/ui/pages/ai_center_page.py       Sunum (QThreadPool ile arka planda çağırır)
        │
        ▼
app/application/services/ai_service.py   GÜVENLİK SINIRI
        │   yetki · gizlilik · salt okunurluk · kullanım kaydı
        ▼
app/ai/registry.py                    Sağlayıcı seçimi ve yedeğe geçiş
        │
        ▼
app/ai/base.py  (AIProvider)          Ortak HTTP altyapısı, JSON ayıklama
        │
        ├── providers/openai_compatible.py   /chat/completions · /models · /embeddings
        │       ├── providers/lmstudio.py    yerel, ücretsiz
        │       └── providers/nvidia.py      NVIDIA NIM
        ├── providers/anthropic.py           /messages (farklı şema)
        └── providers/mock.py                ağ kullanmaz, belirlenimci
```

`app/ai/types.py` bilinçli olarak **framework bağımsızdır**: `httpx`,
`SQLAlchemy` veya `PySide6` import etmez. Böylece adaptörler, servis katmanı
ve arayüz aynı sade veri yapıları üzerinde konuşur.

### Ortak protokol

`AIProvider` (`app/ai/base.py`) dört soyut metot tanımlar:

| Metot | Görev | Hata davranışı |
|---|---|---|
| `chat(request)` | Sohbet tamamlaması | `AI*` hatası fırlatır |
| `list_models()` | Sağlayıcıdaki modelleri listeler | `AI*` hatası fırlatır |
| `health_check()` | Erişilebilirlik yoklaması | **Hata fırlatmaz**, `ok=False` döner |
| `embed(texts, model)` | Metni vektöre çevirir | Desteklenmiyorsa açık hata |

Ek olarak `chat_json(request, schema)` vardır: modelden JSON ister, çıktıyı
ayıklar ve hafif bir şema doğrulamasından geçirir.

Tasarım kararları ve gerekçeleri:

- **Senkron çağrı.** Arayüz PySide6 ile yazılmıştır; Qt olay döngüsü ile
  `asyncio`'yu aynı süreçte yaşatmak kapanış sırasında görünmesi zor
  kilitlenmeler üretir. Çağrılar bu yüzden senkrondur ve arayüz tarafında
  `QThreadPool` iş parçacığında çalıştırılır (`ai_center_page.py`, `_AiJob`).
- **Tek `httpx.Client`.** Her istekte yeni istemci açmak TLS el sıkışmasını
  tekrarlar. İstemci tembel oluşturulur; `MockProvider` hiç açmaz.
- **Ödünç alınan istemciye dokunulmaz.** Dışarıdan verilen `client`,
  `close()` çağrısında kapatılmaz — yaşam döngüsü çağırana aittir.

### Adaptörler

| Sağlayıcı | Sınıf | Taban adres (varsayılan) | Kimlik doğrulama | Yerel mi? | Gömme |
|---|---|---|---|---|---|
| LM Studio | `LMStudioProvider` | `http://127.0.0.1:1234/v1` | Yok (yer tutucu `lm-studio` gönderilmez) | **Evet** | Var |
| NVIDIA NIM | `NvidiaProvider` | `https://integrate.api.nvidia.com/v1` | `Authorization: Bearer` | Hayır | Var (uç OpenAI uyumlu) |
| OpenAI uyumlu | `OpenAICompatibleProvider` | `https://api.openai.com/v1` | `Authorization: Bearer` | Hayır | Var |
| Anthropic | `AnthropicProvider` | `https://api.anthropic.com/v1` | `x-api-key` + `anthropic-version: 2023-06-01` | Hayır | **Yok** — açık hata verir |
| Mock | `MockProvider` | — | — | **Evet** | Var (sahte) |

Anthropic şeması OpenAI'den önemli ölçüde farklıdır ve dönüşüm adaptörün asıl
işidir: uç nokta `/messages`, sistem istemi ayrı bir alan, `max_tokens`
**zorunlu**, yanıt bir blok listesi, düşünme metni `{"type": "thinking"}`
bloğu, jetonlar `input_tokens`/`output_tokens`.

### Yedek zinciri

İstek sırası `AISettings` içinde iki alanla belirlenir: `primary_provider` ve
`fallback_provider`. Zincir en fazla **iki halkalıdır**; öncelik sıralı bir
sağlayıcı listesi yoktur.

```python
# app/ai/registry.py
def chat_with_fallback(self, request, task_type=AITaskType.GENERAL_CHAT):
    primary = self.primary()
    try:
        return primary.chat(self.prepare(request, primary, task_type))
    except AIProviderError as exc:
        secondary = self.fallback()
        if secondary is None or secondary is primary or not should_fall_back(exc):
            raise
        ...
        response = secondary.chat(self.prepare(request, secondary, task_type))
        return replace(response, used_fallback=True)
```

Ayrıntılı kural için [4. Yedeğe geçiş kuralı](#4-yedeğe-geçiş-kuralı) bölümüne
bakın.

> **Not:** `AIProvider` adı iki farklı şeyde geçer. `app/ai/base.py` içindeki
> **çalışma zamanı adaptörüdür**; `app/infrastructure/db/models/ai.py`
> içindeki ise **veritabanı tablosudur**. Birbirlerini import etmezler.

---

## 2. Tüm ayarlar

Ayarlar `.env` dosyasından okunur (`app/core/config.py`). Örnek dosya:
`.env.example`.

### Genel — `AISettings` (`HOTEL_AI_` öneki)

| `.env` anahtarı | Varsayılan | Ne işe yarar |
|---|---|---|
| `HOTEL_AI_ENABLED` | `true` | `false` ise kayıt (registry) her istekte `MockProvider` döndürür; servis katmanı çağrıyı `ConfigurationError` ile reddeder ve `AIUsage` satırını `blocked` durumuyla yazar. |
| `HOTEL_AI_PRIMARY_PROVIDER` | `lmstudio` | `lmstudio` \| `openai` \| `nvidia` \| `anthropic` \| `mock` |
| `HOTEL_AI_FALLBACK_PROVIDER` | `mock` | Boş bırakılabilir. **Birincil ile aynı verilirse otomatik olarak `None` yapılır** (sonsuz döngü koruması, `_no_self_fallback`). |
| `HOTEL_AI_DEFAULT_TIMEOUT` | `120` | Saniye. Kabul aralığı 5–1800. Hem HTTP istemcisine hem `ChatRequest.timeout` alanına geçer. |
| `HOTEL_AI_DEFAULT_TEMPERATURE` | `0.3` | 0.0–2.0. Servis, göreve göre bunu geçersiz kılabilir (fiyat önerisi 0.2, yorum analizi 0.1). |
| `HOTEL_AI_DEFAULT_MAX_TOKENS` | `2048` | 64–200000. **Uyarı:** `AIService` bu değeri okumaz; kendi sabitlerini kullanır (aşağıya bakın). |
| `HOTEL_AI_TRACK_COST` | `true` | **Tanımlıdır ancak hiçbir kod yolu tarafından okunmaz.** Maliyet kaydı bu bayraktan bağımsız olarak her zaman yazılır. |
| `HOTEL_AI_MAX_RETRIES` | `2` | 0–10. Yalnızca 429 ve 5xx için, üssel geri çekilmeyle. **`.env.example` içinde yer almaz**, elle eklenmelidir. |
| `HOTEL_AI_REQUIRE_APPROVAL_FOR_WRITES` | `true` | Yalnızca açılışta uyarı üretir (`Settings.startup_warnings`). Şu an yapay zekânın veri yazan bir yolu **zaten yoktur**; bu bayrak ileriye dönük bir korumadır. |

`AIService` içindeki jeton bütçesi sabitleri
(`app/application/services/ai_service.py`):

| Sabit | Değer | Nerede kullanılır |
|---|---|---|
| `JSON_TASK_MAX_TOKENS` | `2048` | Fiyat önerisi, yorum sınıflandırma |
| `TEXT_TASK_MAX_TOKENS` | `1536` | Günlük özet, doluluk analizi, mesaj taslağı, serbest soru |
| `CONVERSATION_WINDOW` | `12` | Geçmişten modele taşınan azami mesaj |
| `MAX_ANALYSIS_DAYS` | `62` | Doluluk/fiyat isteminde azami gün |
| `MAX_FREE_TEXT_CHARS` | `4000` | Serbest metin girdisinde kırpma sınırı |

> **Bu bir yarım kalmışlıktır ve öyle belgelenmiştir:** Ayarlar ekranındaki
> "Azami Jeton (max_tokens)" alanı `AISettings.default_max_tokens` değerini
> değiştirir, ancak `AIService` yukarıdaki sabitleri kullandığı için değişiklik
> **gerçek çağrılara yansımaz**. Düşünme modelinin jeton sınırına takılması
> durumunda çözüm, ayarı değiştirmek değil daha küçük bir görev seçmek ya da
> kodu düzeltmektir.

### Sağlayıcı bazlı — `AIProviderSettings`

Dört sağlayıcının **hepsi** aşağıdaki altı alanı destekler; yalnızca önek
değişir: `HOTEL_LMSTUDIO_`, `HOTEL_NVIDIA_`, `HOTEL_OPENAI_`,
`HOTEL_ANTHROPIC_`.

| Alan | `.env` soneki | Ne işe yarar |
|---|---|---|
| `base_url` | `_BASE_URL` | Sağlayıcının taban adresi |
| `api_key` | `_API_KEY` | **Yalnızca geliştirme için.** Üretimde Windows Credential Manager tercih edilir (bkz. bölüm 6). |
| `chat_model` | `_CHAT_MODEL` | Sohbet/akıl yürütme/kod görevlerinin modeli |
| `vision_model` | `_VISION_MODEL` | Görsel belge analizi modeli |
| `math_model` | `_MATH_MODEL` | Doluluk/fiyat/talep gibi sayısal görevlerin modeli |
| `embed_model` | `_EMBED_MODEL` | Gömme (embedding) modeli |

Varsayılanlar:

| Sağlayıcı | `base_url` | `chat_model` | Diğer roller |
|---|---|---|---|
| LM Studio | `http://127.0.0.1:1234/v1` | `google/gemma-4-12b-qat` | `qwen/qwen3-vl-8b`, `qwen2.5-math-7b-instruct`, `text-embedding-nomic-embed-text-v1.5` |
| NVIDIA | `https://integrate.api.nvidia.com/v1` | *(boş)* | *(boş)* |
| OpenAI | `https://api.openai.com/v1` | *(boş)* | *(boş)* |
| Anthropic | `https://api.anthropic.com/v1` | *(boş)* | *(boş)* |

`.env.example` yalnızca LM Studio için dört rolü de listeler; NVIDIA/OpenAI/
Anthropic satırlarında yalnızca `_BASE_URL`, `_API_KEY` ve `_CHAT_MODEL`
vardır. Diğer roller yine de çalışır — örneğin `HOTEL_NVIDIA_VISION_MODEL`
tanımlanabilir, ayar nesnesi bunu okur.

### Ayarlar ekranından değiştirme

Ayarlar > Yapay Zekâ sekmesinden `base_url`, `chat_model`, zaman aşımı,
sıcaklık ve azami jeton değiştirilebilir. Ekran bunun **kalıcı olmadığını**
açıkça yazar: değerler çalışan oturumda geçerlidir, uygulama yeniden
başlatıldığında `.env` değerlerine döner. Kalıcı yapmak için ilgili satır
`.env` dosyasına yazılmalıdır. Değişiklikten sonra sağlayıcı önbelleği
`reset_registry()` ile temizlenir.

---

## 3. Model rolleri ve atama

### Yetenek katalogu

`app/domain/enums.py::AICapability` dokuz yetenek tanımlar: `chat`, `vision`,
`embedding`, `reasoning`, `tool_use`, `json_mode`, `long_context`, `code`,
`math`.

`app/ai/catalog.py` içindeki `TASK_CAPABILITY` sözlüğü 18 görev türünün
tamamını bir yeteneğe eşler (bu eşlemenin eksiksizliği
`tests/ai/test_registry.py::TestKatalog::test_tum_gorev_turleri_eslenmis`
ile sınanır):

| Yetenek | Görev türleri |
|---|---|
| `chat` | `general_chat`, `daily_summary`, `review_classification`, `sentiment_analysis`, `message_draft`, `complaint_response`, `task_suggestion`, `maintenance_pattern`, `report_summary`, `document_qa`, `nl_report` |
| `math` | `occupancy_analysis`, `demand_forecast`, `pricing_suggestion`, `stock_forecast` |
| `vision` | `document_vision` |
| `code` | `code_assist` |
| `embedding` | `embedding` |

### Model seçim sırası

`catalog.model_for_task(task_type, settings)` şu sırayı izler:

1. Göreve karşılık gelen yetenek bulunur (`TASK_CAPABILITY`).
2. Sağlayıcı ayarlarındaki ilgili alan okunur:
   `vision` → `vision_model`, `math` → `math_model`,
   `embedding` → `embed_model`, diğer her şey → `chat_model`.
3. Alan boşsa ve yetenek `embedding`/`vision` **değilse** sağlayıcının genel
   `chat_model` değerine düşülür.
4. O da boşsa ve sağlayıcı **LM Studio değilse boş metin döner.**
5. LM Studio için dahili öneri listesi (`LMSTUDIO_ROLE_MODELS`) kullanılır.

4. adım kritiktir: `google/gemma-4-12b-qat` adını NVIDIA'ya göndermek kesin
bir 404 üretir ve kullanıcıyı yanıltır. Bunun yerine model boş bırakılır;
sağlayıcı kendi varsayılanına karar verir ya da anlamlı bir hata verir.
Sınayan test: `tests/ai/test_registry.py::TestKatalog::test_uzak_saglayiciya_yerel_model_onerilmez`.

### LM Studio rol atamaları (katalogda doğrulanmış)

| Yetenek | Model |
|---|---|
| `chat`, `reasoning`, `code` | `google/gemma-4-12b-qat` |
| `vision` | `qwen/qwen3-vl-8b` (hafif alternatif: `moondream-2b-2025-04-14`) |
| `math` | `qwen2.5-math-7b-instruct` |
| `embedding` | `text-embedding-nomic-embed-text-v1.5` |

`biomistral-7b` katalogda kayıtlıdır ancak `recommended_default=False`
işaretlidir: sağlık alanı modelidir ve otel senaryolarında varsayılan
yapılmaz.

### Rollerin gerçek durumu

Dürüst tablo — kod hazır olması ile iş akışının bağlı olması aynı şey değildir:

| Rol | Adaptör | Uygulama akışı |
|---|---|---|
| Sohbet / özet / taslak | Çalışıyor | **Bağlı** — Yapay Zekâ Merkezi ekranı |
| Matematik (doluluk, fiyat) | Çalışıyor | **Bağlı** — Yapay Zekâ Merkezi ekranı |
| Görsel (`document_vision`) | Çalışıyor | **Bağlı değil** — görsel gönderen bir çağrı yolu yok |
| Gömme (`embedding`) | Çalışıyor (`embed()`) | **Bağlı değil** — `app/` içinde hiçbir yerden çağrılmıyor; `app/ai/rag` modülü mevcut değil |

Gömme ve RAG akışının tamamlanmadığı [ROADMAP.md](ROADMAP.md) içinde de
listelidir.

---

## 4. Yedeğe geçiş kuralı

Ayrım tek bir soruya dayanır: **aynı istek yedek sağlayıcıda farklı sonuç
verebilir mi?**

### Geçici hatalar — yedeğe GEÇİLİR

| Hata | Neden geçici |
|---|---|
| `AIConnectionError` | LM Studio kapalı olabilir, bulut sağlayıcı açıktır |
| `AITimeoutError` | Yerel model yavaş, uzak model hızlı olabilir |
| `AIQuotaError` (HTTP 429) | Bir sağlayıcının kotası dolmuş, diğerininki dolmamış olabilir |
| Düz `AIProviderError` (5xx) | Sağlayıcının geçici arızası |

### Kalıcı hatalar — yedeğe GEÇİLMEZ

| Hata | Neden geçilmez |
|---|---|
| `AIAuthenticationError` (401/403) | Anahtar hatası kullanıcının düzeltmesi gereken bir yapılandırma sorunudur. Yedeğe geçmek sorunu **gizler**: kullanıcı anahtarının bozuk olduğunu asla öğrenemez ve aylarca farkında olmadan ücretli sağlayıcıya çalışır. |
| `AIModelNotFoundError` (404) | İstenen model adı genellikle sağlayıcıya özeldir; yedekte de bulunmayacaktır. Aynı 404, iki kat gecikmeyle tekrarlanır. |
| `AIResponseFormatError` | Jeton bütçesi veya şema sorunudur; **aynı istek yedekte de aynı şekilde başarısız olur.** Çözüm `max_tokens` değerini artırmak ya da isteği sadeleştirmektir, başka sağlayıcı denemek değil. |

Kural `app/ai/registry.py::should_fall_back` içindedir ve
`tests/ai/test_registry.py::TestYedegeGecis` altında dört geçici + üç kalıcı
hata için ayrı ayrı sınanır (`test_gecici_hatalarda_yedege_gecilir`,
`test_kalici_hatalarda_yedege_gecilmez`, `test_should_fall_back_kurali`).

### Yeniden deneme (aynı sağlayıcıda)

Yedeğe geçiş ile yeniden deneme farklı şeylerdir. `app/ai/errors.py::is_retryable_status`:

| Durum kodu | Yeniden denenir mi? | Gerekçe |
|---|---|---|
| 429 | **Evet** | Hız sınırı geçicidir |
| 5xx (500 ve üzeri) | **Evet** | Sunucu arızası geçicidir |
| 408, 504 | **Hayır** | Model zaten yavaş çalışıyordur; ikinci deneme kullanıcıyı yalnızca iki kat bekletir |
| 400, 401, 403, 404 | **Hayır** | Kalıcı hatalar; aynı istek aynı sonucu verir |

Bekleme süresi üsteldir: `retry_backoff * 2**deneme` (varsayılan `0.5` sn).

### Yedeğe geçildiğinde ne olur?

- Yanıt `ChatResponse.used_fallback = True` ile işaretlenir.
- Arayüz ölçüm satırında **"yedek sağlayıcı kullanıldı"** yazar
  (`ai_center_page.py::_meta_label`).
- `AIUsage.status` değeri `fallback_used` olur ve `fell_back_from` alanına
  birincil sağlayıcının kodu yazılır.
- Log'a `ai_yedege_gecildi` uyarısı düşer.

Yedek `mock` seçilirse gerçek bir model çağrılmaz; uygulama çökmez, belirlenimci
bir yer tutucu yanıt döner. Bu, "yapay zekâ kapalı" durumunun da güvenli
varsayılanıdır.

---

## 5. Jeton ve maliyet takibi

### `AIUsage` tablosu

**Başarılı ya da başarısız, her çağrı için bir satır yazılır**
(`ai_service.py::_record_usage`). Tablo yalnızca ekleme yapılan (append-only)
bir kayıttır.

| Sütun | İçerik |
|---|---|
| `created_at` | Çağrı zamanı (UTC) |
| `provider_id`, `model_name` | Hangi sağlayıcı/model — model silinse bile ad korunur |
| `user_id` | Çağrıyı yapan kullanıcı |
| `task_type` | 18 görev türünden biri |
| `status` | `success` \| `failed` \| `timeout` \| `fallback_used` \| `cancelled` \| `blocked` |
| `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `total_tokens` | Jeton sayaçları |
| `estimated_cost`, `cost_currency` | Tahmini maliyet (varsayılan `USD`) |
| `latency_ms` | Süre |
| `error_code`, `error_message` | Hata durumunda (mesaj 500 karakterde kırpılır) |
| `fell_back_from` | Yedeğe geçildiyse birincil sağlayıcının kodu |

**İstem ve yanıt metinleri bu tabloda saklanmaz.** Gerekçesi model
dokümantasyonunda yazılıdır: misafir verisi içerebilecek istemlerin kalıcı
olarak birikmesini önlemek.

### Düşünme jetonları neden ayrı sayılır?

`google/gemma-4-12b-qat` gibi düşünme modelleri görünür cevabın yanı sıra ayrı
bir akıl yürütme metni üretir. Bu metin kullanıcıya gösterilmez ama
**jeton olarak faturalandırılır ve bağlam penceresini doldurur.** Maliyet
hesabı bu jetonları yok sayarsa gerçek gideri olduğundan düşük gösterir.

Adaptör, bazı yerel sunucuların yalnızca görünür jetonları saymasına karşı bir
düzeltme uygular (`openai_compatible.py`):

```python
# OpenAI semasinda reasoning_tokens, completion_tokens'in ALT KUMESIDIR.
# Ancak bazi yerel sunucular yalnizca gorunur jetonlari sayar; bu durumda
# dusunme jetonlarini eklemezsek maliyet oldugundan dusuk cikar.
if reasoning_tokens > completion_tokens:
    completion_tokens += reasoning_tokens
```

### Maliyet hesabının gerçek durumu — DİKKAT

`_record_usage`, maliyeti `app/ai/catalog.py::estimate_cost` ile hesaplar.
Katalogdaki `KNOWN_MODELS` sözlüğü **yalnızca altı LM Studio modelinden**
oluşur ve hepsinin fiyatı sıfırdır. Bilinmeyen bir model kimliği için de
sıfır döner.

**Sonuç: uygulama şu anda hangi sağlayıcı kullanılırsa kullanılsın
`estimated_cost = 0.000000` yazar.** Arayüzde maliyet satırı "ucretsiz"
görünür.

Bu bilinçli bir tasarım tercihinin yarım kalmış tarafıdır: uzak sağlayıcı
fiyatları sık değiştiği için koda gömülmez, `AIModel` veritabanı tablosu
üzerinden yapılandırılması öngörülmüştür (`input_cost_per_1k`,
`output_cost_per_1k`, `cost_currency` sütunları ve `AIModel.estimate_cost`
metodu mevcuttur). **Ancak `AIService` bu tabloyu okumaz.** Ücretli bir
sağlayıcı kullanacaksanız gerçek maliyeti sağlayıcının kendi faturasından
takip edin; uygulamanın maliyet sütununa güvenmeyin.

Jeton sayaçları bu durumdan etkilenmez — onlar sağlayıcının `usage` alanından
gelir ve doğrudur.

---

## 6. Güvenlik: istemde misafir kişisel verisi bulunmaz

`app/application/services/ai_service.py` uygulamadaki **tek yapay zekâ giriş
kapısıdır**. Yapay Zekâ Merkezi ekranı `app.ai.registry` ile doğrudan
konuşmaz; her görev çağrısı buradan geçer. (Tek istisna: Ayarlar ekranındaki
"Bağlantıyı Test Et" düğmesi `get_registry().health_report()` çağırır — bu
yalnızca `/models` yoklamasıdır, istem göndermez.)

Gizlilik dört katmanla sağlanır.

### Katman 1 — Yapısal: sistemin topladığı veride metin alanı yok

Günlük özet isteminin **tüm** girdisi `DailyFacts` sınıfıdır. Bu dataclass'ta
bilinçli olarak hiçbir serbest metin alanı yoktur; yalnızca tarih, para birimi
kodu ve sayılar vardır:

```python
@dataclass(frozen=True, slots=True)
class DailyFacts:
    """Gunluk ozetin modele gonderilen **tum** girdisi.

    Bu yapida bilincli olarak **hicbir metin alani yoktur**: yalnizca tarih ve
    sayilar. Gunluk ozet istemi bu nesneden uretildigi icin misafir adi,
    kimlik numarasi, e-posta veya telefonun modele gitmesi yapisal olarak
    imkansizdir.
    """
    day: date
    total_rooms: int
    ...
```

Aynı ilke doluluk analizi ve fiyat önerisinde de geçerlidir: istemler
`app/reporting/queries.py` çıktısından üretilir ve o raporlar yalnızca oda
**sayıları** içerir. Hareket sayıları da isim okumadan, `COUNT(*)` ile
hesaplanır (`_movement_counts`).

### Katman 2 — Maskeleme: kullanıcının serbest yazdığı metin

Mesaj taslağı bağlamı, misafir yorumu, serbest soru ve okunan sohbet geçmişi
`redact_personal_data()` fonksiyonundan geçer:

| Desen | Maske |
|---|---|
| E-posta adresi | `[e-posta gizlendi]` |
| Türkiye telefon biçimleri | `[telefon gizlendi]` |
| 9 hane ve üzeri sayı dizileri (kimlik, pasaport, kart) | `[numara gizlendi]` |

Sıra önemlidir: e-posta önce maskelenir, aksi halde adresin içindeki rakamlar
telefon sanılabilir.

Ad-soyad otomatik tespit **edilmez**. Kullanıcı bir ad yazdıysa bu onun
bilinçli tercihidir; buna karşılık kimlik numarası ve iletişim bilgisi hiçbir
koşulda dışarı çıkmamalıdır.

Yanlış pozitif tuzağı bilinçle çözülmüştür: telefon deseni ayırıcı ister ve
uzun sayı deseni ondalık sayıların parçasını dışarıda bırakır. Aksi halde
yüksek cirolu bir tesiste `1234567890.0` gibi bir toplam telefon/kimlik
sanılır ve **günlük özet hiç üretilemezdi.**

### Katman 3 — Son savunma: gönderim öncesi doğrulama

Her çağrı `_run()` içinde şu zinciri izler:

```python
def _run(self, task_type, messages, *, max_tokens=..., temperature=None):
    """Yetki -> gizlilik -> cagri -> kullanim kaydi zincirini calistirir."""
    self.ctx.require(Perm.AI_USE)
    self._ensure_enabled(task_type)
    assert_prompt_is_anonymous(messages)
```

`assert_prompt_is_anonymous()` istemde e-posta, telefon veya uzun numara
kalmışsa `ValidationError` fırlatır ve **çağrı hiç yapılmaz**. Bu, ileride
biri bir sorguya ad/e-posta sütunu eklerse hatanın sessizce değil gürültüyle
ortaya çıkmasını sağlar.

Bulgunun kendisi log'a veya hata mesajına **yazılmaz** — kişisel veri log
dosyasına da gitmemelidir. Yalnızca kaç eşleşme bulunduğu bildirilir.

### Katman 4 — Sistem istemi

Her istemin başında yer alan `_BASE_SYSTEM` metni modele açıkça söyler:

> "Misafirlerin adı, kimlik numarası, e-posta veya telefonu sana verilmez ve
> bunları asla isteme."

### Bunu doğrulayan testler

`tests/application/test_ai_service.py::TestGizlilik` — 6 test:

| Test | Ne doğrular |
|---|---|
| `test_gunluk_ozet_istemi_misafir_bilgisi_icermez` | Gerçek bir rezervasyon oluşturulur, günlük özet çalıştırılır; gönderilen istemde misafirin adı, soyadı, e-postası, kimlik numarası ve telefonu **aranır ve bulunmaz**. Aynı testte `"giris_sayisi": 1` bulunur — yani rezervasyon gerçekten döneme dahildir, test boş veriyle geçmemektedir. |
| `test_gunluk_veri_yapisi_yalnizca_sayi_icerir` | `DailyFacts.to_payload()` içindeki metin alanlarının kümesi tam olarak `{"gun", "para_birimi"}`; kalan her değer `int` veya `float`. |
| `test_serbest_metinde_iletisim_bilgisi_maskelenir` | Taslak bağlamındaki e-posta ve kimlik numarası isteme geçmez; yerine maske metni geçer. |
| `test_kisisel_veri_kalirsa_cagri_yapilmadan_engellenir` | `ai_prompt_contains_pii` kodlu hata fırlar ve bulgunun kendisi hata metnine yazılmaz. |
| `test_maskeleme_para_tutarlarini_bozmaz` | Büyük ciro sayıları telefon/kimlik sanılmaz (yanlış pozitif yok). |
| `test_maskeleme_gercek_verileri_yakalar` | Kart numarası, telefon ve e-posta gerçekten maskelenir. |

Ayrıca `tests/application/test_ai_service.py::TestGorevler::test_baskasinin_sohbeti_okunmaz`,
başka bir kullanıcının sohbet geçmişinin modele taşınmadığını doğrular.
Geçmiş bulunamadığında **sessizce boş** döner — "böyle bir sohbet var ama
sizin değil" demek de bilgi sızdırır.

### Anahtar ve log güvenliği

- API anahtarları veritabanına **yazılmaz**. `AIProvider` tablosu yalnızca
  anahtarın keyring'de hangi ad altında arandığını (`secret_name`) tutar.
- `nvapi-`, `sk-`, `xai-`, `hf_`, `ghp_` gibi bilinen anahtar önekleri ve
  `Authorization: Bearer ...` başlıkları log'da maskelenir
  (`app/core/log.py`). Doğrulama:

  ```
  >>> mask_text('anahtar nvapi-abc123def456ghi burada')
  'anahtar ***MASKELENDI*** burada'
  >>> mask_text('Authorization: Bearer nvapi-XYZ0123456789')
  'Authorization: Bearer ***MASKELENDI***'
  ```

- NVIDIA adaptörü anahtar bulunamadığında hata ayrıntısına yalnızca aranan
  **adı** yazar, değerini değil:
  `detail="'nvidia_api_key' keyring'de de ortamda da bulunamadi"`.

---

## 7. Yapay zekânın YAPAMADIKLARI

Bu bölüm bir vaat değil, koda gömülmüş bir kısıttır.

### Veriyi değiştiremez

`AIService` otel verisi üzerinde hiçbir yazma işlemi yapmaz. Fiyat, oda,
rezervasyon, folyo tablolarına `UPDATE`/`INSERT`/`DELETE` göndermez. Yazdığı
**tek** kayıtlar denetim izidir: `AIUsage` ve `AuditLog`.

### Fiyat uygulayamaz

Fiyat çıktı tipi `PricingSuggestion`'dır ve `applied` alanı `init=False` ile
sabit `False`'tur:

```python
@dataclass(frozen=True, slots=True)
class PricingSuggestion:
    date_range: DateRange
    summary: str
    items: tuple[PricingSuggestionItem, ...]
    result: AIResult
    applied: bool = field(default=False, init=False)
    advisory_note: str = field(default=PRICING_ADVISORY_NOTE, init=False)
```

Bir öneriyi "uygulanmış" göstermek **tip düzeyinde imkânsızdır** — hiçbir
çağıran bu nesneyi `applied=True` ile üretemez.

Arayüz tarafında fiyat önerisi sonucunda **fiyatı değiştiren hiçbir düğme
yoktur** (`ai_center_page.py::_add_pricing_message`). Sonucun üstünde şu uyarı
zorunlu olarak gösterilir:

> Bu bir öneridir. Uygulamak için Fiyatlar ekranından onaylamanız gerekir.

Doğrulayan testler: `TestFiyatOnerisi::test_oneri_uygulanmis_olarak_donmez`,
`test_oneri_hicbir_fiyati_degistirmez` (çağrı sonrası `RoomType.base_rate`
veritabanından yeniden okunur ve değişmediği gösterilir),
`test_applied_alani_disaridan_verilemez`.

### Rezervasyon silemez, mesaj gönderemez

- `AIDraft` bir **taslaktır**; hiçbir e-posta/SMS altyapısına bağlı değildir.
  Kullanıcıya "AI tarafından oluşturuldu" işaretiyle sunulur, kopyalanır.
- Model çıktısındaki para tutarları `Decimal` olarak okunur ve yalnızca
  gösterilir. Nihai tutarlar **modele hesaplattırılmaz**;
  `app/domain/rules/pricing` hesaplar.
- Sohbet geçmişi yalnızca **okunur**; servis `AIConversation`/`AIMessage`
  tablolarına yazmaz.

### Her çıktı işaretlidir

`AIResult.is_ai_generated` ve `AIDraft.is_ai_generated` alanları `init=False`
ile her zaman `True`'dur: bu servisten dönen hiçbir metin "insan yazmış" gibi
işaretlenemez. Arayüz her yanıt balonunda `AiBadge` gösterir. Düşünme metni
katlanabilir bir bölümde ve **varsayılan olarak kapalı** sunulur — akıl
yürütme kullanıcıya yanıt değil, hata ayıklama malzemesidir.

### İptal ne yapar, ne yapmaz

"İptal" düğmesi arayüzü hemen serbest bırakır ve gelen yanıtı yok sayar.
Ancak sağlayıcıya gönderilmiş bir HTTP isteği dışarıdan durdurulamaz: model
üretmeye devam eder ve kullanım kaydı yazılır. Arayüz bunu kullanıcıya
açıkça söyler.

---

## 8. Sorun giderme

Aşağıdaki çözüm önerileri `app/ai/errors.py` içindeki `REMEDY_*` sabitlerinin
kendisidir; uygulama hata anında bunları kullanıcıya gösterir.

| Belirti / hata | Hata tipi | Uygulamanın gösterdiği çözüm |
|---|---|---|
| Yerel sunucuya bağlanılamıyor | `AIConnectionError` | "LM Studio çalışıyor mu? Sunucu sekmesinden Start Server deyin ve adresi Ayarlar > Yapay Zeka ekranından doğrulayın." |
| Uzak sağlayıcıya bağlanılamıyor | `AIConnectionError` | "İnternet bağlantınızı ve sunucu adresini kontrol edin. Kurum güvenlik duvarı erişimi engelliyor olabilir." |
| Model süresinde yanıt vermedi | `AITimeoutError` | "Model süresinde yanıt vermedi. Ayarlar > Yapay Zeka ekranından zaman aşımı süresini artırın veya daha küçük bir model seçin." |
| Anahtar yok / geçersiz (401, 403) | `AIAuthenticationError` | "Ayarlar > Yapay Zeka ekranından anahtarınızı girin. Anahtar işletim sisteminin güvenli deposunda saklanır, veritabanına yazılmaz." |
| Yerel sunucu isteği reddetti | `AIAuthenticationError` | "Yerel sunucu isteği reddetti. LM Studio sunucu ayarlarında bir erişim anahtarı tanımlıysa aynısını Ayarlar > Yapay Zeka ekranına girin." |
| Model bulunamadı (404) | `AIModelNotFoundError` | "Model sunucuda yüklü değil. Ayarlar > Yapay Zeka ekranından listeden bir model seçin; LM Studio kullanıyorsanız modeli önce yükleyin." |
| Kota / hız sınırı (429) | `AIQuotaError` | "Kota veya hız sınırı aşıldı. Birkaç dakika bekleyin, faturalandırmanızı kontrol edin ya da yerel (ücretsiz) bir modele geçin." |
| Sağlayıcı 5xx döndürdü | `AIProviderError` | "Sağlayıcı geçici olarak hata veriyor. Birkaç dakika sonra tekrar deneyin; sorun sürerse yedek sağlayıcıya geçin." |
| İstek reddedildi (400) | `AIProviderError` | "İstek sağlayıcı tarafından reddedildi. Model adını ve Ayarlar > Yapay Zeka ekranındaki değerleri kontrol edin." |
| Model geçerli JSON üretemedi | `AIResponseFormatError` | "Model beklenen JSON biçimini üretemedi. Daha yetenekli bir model seçin veya isteği sadeleştirin." |
| Düşünme modeli boş yanıt döndürdü | `AIResponseFormatError` | "Düşünme modeli, yanıt üretmeden jeton sınırına ulaştı. Ayarlar > Yapay Zeka ekranından azami jeton (max_tokens) değerini artırın; düşünme modelleri için en az 1024 önerilir." |
| Sağlayıcı gömme desteklemiyor | `AIProviderError` | "Bu sağlayıcı gömme (embedding) desteklemiyor. Gömme için LM Studio üzerindeki text-embedding-nomic-embed-text-v1.5 modelini kullanın." |
| "Yapay zeka özellikleri şu anda kapalı" | `ConfigurationError` | "Ayarlar > Yapay Zeka ekranından yapay zekayı etkinleştirin; yerel kullanım için LM Studio sunucusunu başlatın." |

LM Studio 404 hatası ayrıca **zenginleştirilir**: mevcut model listesi
`/v1/models` ucundan çekilip hata mesajına eklenir. Kullanıcı Ayarlar'daki
yanlış model adını ancak doğrusunu görürse düzeltebilir. Liste alınamazsa
(sunucu bu arada kapandıysa) özgün hata korunur.

### Bağlantı testi

Ayarlar > Yapay Zekâ ekranındaki **Bağlantıyı Test Et** düğmesi tüm
yapılandırılmış sağlayıcıları yoklar ve tabloya durum yazar.

Komut satırı karşılığı:

```powershell
.\.venv\Scripts\python.exe -m app.cli check-ai
```

> **Bilinen hata (15.08.2026 tarihinde doğrulandı):** `check-ai` komutu,
> bir sağlayıcı **sağlıklı** dönüp model listesi bulduğunda çöker:
>
> ```
> File "C:\AkilliKonaklama\app\cli.py", line 194, in cmd_check_ai
>     print(f"    Modeller: {len(status.models_found)} adet")
> TypeError: object of type 'int' has no len()
> ```
>
> `HealthStatus.models_found` bir **sayıdır**; model adları
> `HealthStatus.model_ids` alanındadır. Durum satırı ("Calisiyor (345 ms)")
> ekrana basılır, ardından komut çıkış kodu 1 ile sonlanır. Sorun giderilene
> kadar bağlantı testi için **Ayarlar ekranındaki düğmeyi** kullanın; o yol
> `health_report()` çağırdığı için etkilenmez.

---

## 9. Doğrulama durumu

| Alan | Durum | Nasıl doğrulandı |
|---|---|---|
| LM Studio adaptörü | **Çalışıyor** | `pytest -m live` ile gerçek sunucu testi; bu belge yazılırken `check-ai` çıktısında "Calisiyor (345 ms)" |
| NVIDIA adaptörü | **Kod hazır, gerçek çağrı YAPILMADI** | Sahte HTTP (`respx`) testleri: `tests/ai/test_providers.py::TestNvidia` — 4 test |
| Anthropic adaptörü | **Kod hazır, gerçek çağrı yapılmadı** | `respx` testleri |
| Yedeğe geçiş kuralı | **Çalışıyor** | `tests/ai/test_registry.py::TestYedegeGecis` |
| Gizlilik güvenceleri | **Çalışıyor** | `tests/application/test_ai_service.py::TestGizlilik` |
| Salt okunurluk | **Çalışıyor** | `tests/application/test_ai_service.py::TestFiyatOnerisi` |
| Maliyet tahmini | **Yarım** | Her zaman 0 döner — bkz. bölüm 5 |
| `HOTEL_AI_DEFAULT_MAX_TOKENS` etkisi | **Yarım** | Servis sabitleri kullanıyor — bkz. bölüm 2 |
| `HOTEL_AI_TRACK_COST` | **Kullanılmıyor** | Kaynak kodda okuyan yer yok |
| Gömme / RAG akışı | **Yapılmadı** | `app/ai/rag` mevcut değil; `embed()` `app/` içinden çağrılmıyor |
| Görsel belge analizi akışı | **Yapılmadı** | Adaptör destekliyor, çağrı yolu yok |
| `app.cli check-ai` | **Hatalı** | Yukarıdaki `TypeError` |

Yapay zekâ ile ilgili test sayıları (`pytest -m "not live"`, 15.08.2026):

| Dosya | Test |
|---|---|
| `tests/ai/test_providers.py` | 81 (+1 `live` işaretli, atlanır) |
| `tests/ai/test_registry.py` | 41 |
| `tests/application/test_ai_service.py` | 29 |
| `tests/ui/test_reports_ai_pages.py` | 25 |
| **Toplam** | **176** |

Proje genelinde `pytest -m "not live" --collect-only` çıktısı:
**985/986 test toplanır (1 tanesi `live` işaretli olduğu için seçilmez).**
