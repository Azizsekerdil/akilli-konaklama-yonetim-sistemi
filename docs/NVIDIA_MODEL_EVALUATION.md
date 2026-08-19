# NVIDIA Model Değerlendirmesi

> ## ⚠ ÖNCE BUNU OKUYUN
>
> **Bu projede NVIDIA API'ye bugüne kadar GERÇEK BİR ÇAĞRI YAPILMAMIŞTIR.**
> Elimizde bir API anahtarı yoktur; hiçbir model gerçek bir istekle
> denenmemiştir. Aşağıdaki değerlendirme **genel erişilebilir bilgilere**
> (NVIDIA'nın kendi dokümantasyonu, model kartları ve üçüncü parti kaynaklar)
> dayanır.
>
> Bu belge bir **ön araştırmadır**, bir test raporu değildir. Buradaki hiçbir
> satır "şu model bizim otelimizde şöyle çalışıyor" anlamına gelmez.
>
> **Kullanım öncesi her aday model kendi hesabınızla, kendi verinizle
> denenmelidir.** Özellikle Türkçe yanıt kalitesi, JSON şemasına uyum ve
> düşünme jetonu tüketimi kaynaklarda yazandan bağımsız olarak ölçülmelidir.
>
> Doğrulanamayan her alan aşağıda **`doğrulanamadı`** olarak işaretlenmiştir.

**Araştırma tarihi:** 15.08.2026
**Erişim notu:** `build.nvidia.com` katalog sayfaları otomatik erişimde
zaman aşımına uğradı (JavaScript ile çizilen tek sayfa uygulaması). Bu yüzden
model bilgileri `docs.api.nvidia.com`, NVIDIA geliştirici blogu ve model
kartlarından derlendi. **Katalogdaki güncel model listesi doğrulanamadı.**

İlgili belgeler: [NVIDIA_API_SETUP.md](NVIDIA_API_SETUP.md) ·
[AI_CONFIGURATION.md](AI_CONFIGURATION.md) ·
[LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md)

---

## 1. Otel yönetiminde hangi işler için model gerekir?

Uygulamanın görev katalogu (`app/domain/enums.py::AITaskType`) 18 görev türü
tanımlar. Bunlar dört pratik kümede toplanır:

| Kullanım senaryosu | Görev türü (kodda) | Gereken yetenek | Zorluk kaynağı |
|---|---|---|---|
| **Türkçe sohbet / özet** — günlük özet, doluluk yorumu, misafir mesajı taslağı, şikayet yanıtı | `daily_summary`, `general_chat`, `message_draft`, `complaint_response`, `report_summary` | `chat` | Türkçe akıcılık ve nezaket tonu; kısa kalma disiplini |
| **JSON üretimi** — fiyat önerisi, yorum sınıflandırma | `pricing_suggestion`, `review_classification` | `math` / `chat` + `json_mode` | Şemaya birebir uyum; markdown kod bloğu eklememe |
| **Uzun belge analizi** — sözleşme, tedarikçi teklifi, rapor özeti *(uygulamada akış yok)* | `document_qa`, `nl_report` | `long_context` | 100K+ jeton bağlam; Türkçe belge |
| **Görsel belge analizi** — kimlik/pasaport, fatura görüntüsü *(uygulamada akış yok)* | `document_vision` | `vision` | Türkçe metin okuma; **KVKK riski en yüksek iş** |
| **Gömme (embedding)** — belge arama, RAG *(uygulamada akış yok)* | `embedding` | `embedding` | Türkçe destekli çok dilli gömme |
| **Kod** — AI Geliştirme Merkezi | `code_assist` | `code` | Python 3.11, tip ipuçları |

> **Dürüstlük notu:** Yukarıdaki listede *(uygulamada akış yok)* işaretli
> satırların adaptör desteği hazırdır ancak uygulamada bunları çağıran bir
> ekran veya servis yoktur. Uzun belge analizi, görsel belge analizi ve
> gömme/RAG akışları [ROADMAP.md](ROADMAP.md) içinde eksik olarak listelidir.
> Bugün NVIDIA'ya bağlarsanız yalnızca **sohbet/özet ve JSON üretimi**
> görevleri gerçekten çalışır.

---

## 2. Aday model türleri ve öne çıkan adaylar

Aşağıdaki tablolarda **doğrulandı** işaretli alanlar belirtilen kaynaktan
okunmuştur. **`doğrulanamadı`** işaretli alanlar için hiçbir güvenilir kaynak
bulunamadı ya da yalnızca üçüncü parti bloglarda geçiyordu.

Model kimlikleri, katalog URL'lerinden türetilmiştir. **API'ye gönderilecek
gerçek kimlik dizgesi doğrulanamadı** — NVIDIA katalog sayfalarında URL
kısmında alt çizgi (`llama-3_3-...`), API kimliğinde nokta
(`llama-3.3-...`) kullanılabilmektedir. Kimliği model kartındaki örnek
koddan kopyalayın.

### 2.1 Türkçe sohbet ve yönetim özeti

| Alan | `nvidia/llama-3.3-nemotron-super-49b-v1` | `meta/llama-3.3-70b-instruct` | `qwen/qwen3-235b-a22b` |
|---|---|---|---|
| Yayıncı | NVIDIA (Meta Llama 3.3 70B türevi) — **doğrulandı** | Meta — **doğrulandı** | Alibaba / Qwen — **doğrulandı** |
| Bağlam penceresi | 128K (131 072 jeton) — **doğrulandı** (HF model kartı) | 128K — **doğrulandı** (NGC/NVIDIA docs) | Yerel 32 768; YaRN ile 131 072'ye kadar — **doğrulandı** (HF model kartı) |
| Düşünme (reasoning) modeli mi? | **Evet** — sistem istemiyle açılıp kapanabilir, `<think>` etiketi üretir — **doğrulandı** | Hayır (klasik instruct) — **doğrulandı** | **Evet** — `enable_thinking` ile açılır/kapanır — **doğrulandı** |
| Resmî Türkçe desteği | **HAYIR.** Model kartı İngilizce + Almanca, Fransızca, İtalyanca, Portekizce, Hintçe, İspanyolca, Tayca sayar; **Türkçe listede yok** — **doğrulandı** | Aynı Llama 3.3 dil listesi; **Türkçe yok** — **doğrulandı** | "100+ dil ve lehçe" iddiası var; Türkçe adı **açıkça geçmiyor** — kısmen doğrulandı |
| Lisans | NVIDIA Open Model License + Llama 3.3 Community License — **doğrulandı** | Llama 3.3 Community License — kısmen doğrulandı | Apache-2.0 — **doğrulandı** |
| Fiyat / kota | `doğrulanamadı` | `doğrulanamadı` | `doğrulanamadı` |
| Pratik Türkçe kalitesi | `doğrulanamadı` — **ölçülmeli** | `doğrulanamadı` — **ölçülmeli** | `doğrulanamadı` — **ölçülmeli** |

> **En önemli bulgu:** Llama ailesinin **resmî dil listesinde Türkçe yoktur.**
> Modeller pratikte Türkçe üretebilir, ancak bu üreticinin desteklediği bir
> yetenek değildir; kalite ve tutarlılık garanti edilmez. Misafire
> gönderilecek metinlerde (şikayet yanıtı, teşekkür mesajı) bu ciddi bir
> risktir. Türkçe çıktı gerektiren her aday **kendi verinizle denenmeden**
> kullanılmamalıdır.

### 2.2 JSON üretimi (fiyat önerisi, yorum sınıflandırma)

Uygulama JSON'u iki aşamalı olarak güvenceye alır (`app/ai/base.py`):

1. OpenAI uyumlu sağlayıcılarda `response_format: {"type": "json_object"}`
   denenir. Sağlayıcı reddederse (HTTP 400 + tanıdık ifade) bir kez algılanır,
   o oturum için JSON kipi kapatılır ve istem tabanlı yönteme düşülür.
2. Çıktıdan JSON nesnesi ayıklanır: düz JSON, markdown kod bloğu ve serbest
   metin içindeki ilk dengeli `{...}` bloğu sırayla denenir.
3. Şema verilmişse hafif doğrulama yapılır (`type`, `required`, `properties`,
   `items`, `enum`).

| Konu | Durum |
|---|---|
| NVIDIA NIM `response_format` desteği | `doğrulanamadı` — modelden modele değişebilir; uygulama reddedilirse kendiliğinden istem tabanlı yönteme düşer |
| Hangi modelin JSON'a daha sadık kaldığı | `doğrulanamadı` — **ölçülmeli** |
| Düşünme modellerinin JSON'u | Riskli: `<think>` bloğu çıktının başına gelirse ayıklayıcı dengeli `{...}` arayarak kurtarır; ancak jeton bütçesi düşünmede tükenirse `content` boş döner ve `AIResponseFormatError` fırlar |

> JSON isteyen görevlerde **düşünme kipi kapalı** bir model tercih etmek daha
> öngörülebilirdir. `nvidia/llama-3.3-nemotron-super-49b-v1` ve
> `qwen/qwen3-235b-a22b` için düşünme kipi sistem istemi/parametre ile
> kapatılabilir (**doğrulandı**), ancak bunu uygulamadan yapmak için
> `ChatRequest.extra` alanına parametre eklemek gerekir — bugün Ayarlar
> ekranında böyle bir seçenek **yoktur**.

### 2.3 Uzun belge analizi

| Aday | Bağlam | Not |
|---|---|---|
| `nvidia/llama-3.3-nemotron-super-49b-v1` | 128K — **doğrulandı** | Otel sözleşmesi/rapor boyutu için fazlasıyla yeterli |
| `meta/llama-3.3-70b-instruct` | 128K — **doğrulandı** | Aynı |
| `qwen/qwen3-235b-a22b` | 32K yerel / 131K YaRN ile — **doğrulandı** | YaRN'ın NVIDIA barındırmasında açık olup olmadığı `doğrulanamadı` |

> Uygulama tarafında engel: `AIService` uzun belge gönderen bir yol
> içermez ve serbest metin girdisi `MAX_FREE_TEXT_CHARS = 4000` karakterde
> kırpılır. 128K bağlamdan bugün faydalanılamaz.

### 2.4 Kod yardımı

Adaylar (`doğrulanamadı` — katalogdaki güncel kod modelleri doğrulanamadı):
genel amaçlı büyük instruct modelleri (Llama 3.3 70B, Nemotron Super 49B,
Qwen3) kod üretiminde de kullanılabilir.

> Uygulamada kod görevleri **AI Geliştirme Merkezi** üzerinden çalışır ve o
> akış aynı sağlayıcı katmanını kullanır. Kod görevleri misafir verisi
> içermez; bu yüzden bulut modeli KVKK açısından görece düşük risklidir —
> ancak **kaynak kodunuz sağlayıcıya gider**. Bu ticari bir karardır.

### 2.5 Görsel belge analizi

| Aday | Alan | Değer |
|---|---|---|
| `meta/llama-3.2-90b-vision-instruct` | Giriş / çıkış | Metin + görüntü giriş, yalnızca metin çıkış — **doğrulandı** |
| | Bağlam | 128K — **doğrulandı** |
| | Parametre | 90B — **doğrulandı** |
| | Türkçe metin okuma başarımı | `doğrulanamadı` |
| | Görüntü boyutu sınırı | `doğrulanamadı` |

> **KVKK uyarısı — bu senaryo özel dikkat ister.** Kimlik veya pasaport
> görüntüsünü bulut sağlayıcıya göndermek, özel nitelikli kişisel veriyi
> yurt dışına aktarmak demektir. Uygulamanın istem maskeleme katmanı
> **metin** üzerinde çalışır; bir görüntünün içindeki kimlik numarasını
> maskeleyemez. Bu iş için **yerel model kullanılmalıdır** (bkz. bölüm 5).
>
> Ayrıca hatırlatma: uygulamada bugün görüntü gönderen bir çağrı yolu
> **yoktur**; bu satırlar ileriye dönük bir değerlendirmedir.

### 2.6 Gömme (embedding)

| Alan | `nvidia/llama-3.2-nv-embedqa-1b-v2` |
|---|---|
| Yayıncı | NVIDIA (NeMo Retriever) — **doğrulandı** |
| Vektör boyutu | 384 / 512 / 768 / 1024 / 2048 arasından seçilebilir (Matryoshka) — **doğrulandı** |
| Azami girdi | 8192 jeton — **doğrulandı** |
| Dil desteği | 26 dilde değerlendirilmiş ve listede **Türkçe açıkça yer alıyor** — **doğrulandı** |
| Fiyat / kota | `doğrulanamadı` |

> Bu, araştırmada **Türkçe desteği açıkça belgelenmiş tek NVIDIA modelidir**.
> Buna karşılık uygulamada gömmeyi çağıran bir kod yolu yoktur
> (`app/ai/rag` mevcut değil), dolayısıyla bugün kullanılamaz.

### 2.7 Erişim ve kota

| Konu | Durum |
|---|---|
| Uç nokta `https://integrate.api.nvidia.com`, `POST /v1/chat/completions` | **doğrulandı** (NVIDIA API dokümantasyonu) |
| OpenAI uyumlu API | **doğrulandı** |
| Developer Program üyelerine **indirilebilir** NIM mikroservisleri için ücretsiz erişim (en fazla 2 düğüm / 16 GPU) | **doğrulandı** (NVIDIA geliştirici blogu) |
| NVIDIA'nın barındırdığı uç noktalar için API Catalog üzerinden "ücretsiz kredi" | **doğrulandı** (aynı blog) — miktar belirtilmiyor |
| "1 000 ücretsiz kredi, istek üzerine 5 000'e kadar" | `doğrulanamadı` — yalnızca üçüncü parti bloglarda |
| "Dakikada 40 istek hız sınırı" | `doğrulanamadı` — yalnızca üçüncü parti bloglarda |
| Jeton başına liste fiyatı | `doğrulanamadı` — NVIDIA'nın barındırdığı uçlar için genel bir jeton fiyat listesi bulunamadı |
| Üretim kullanımı için NVIDIA AI Enterprise lisansı gerekliliği | Kısmen doğrulandı — blog "üretime hazır olunca 90 günlük ücretsiz AI Enterprise lisansı" diyor; fiyat rakamları `doğrulanamadı` |

---

## 3. Yerel (LM Studio) ve bulut (NVIDIA) karşılaştırması

| Ölçüt | LM Studio (yerel) | NVIDIA NIM (bulut) |
|---|---|---|
| **Veri gizliliği** | İstem bilgisayardan **ayrılmaz**. KVKK açısından en güvenli seçenek. | İstem NVIDIA sunucularına gider. Uygulama kimlik/iletişim bilgisini istemden çıkarır, ancak doluluk, ciro ve fiyat verisi de gider. |
| **Maliyet** | Elektrik dışında sıfır. Katalogda `is_free = True` olarak kayıtlı. | Kredi/kota tüketir. Uygulamanın maliyet tahmini şu an her zaman 0 gösterir (bkz. [AI_CONFIGURATION.md](AI_CONFIGURATION.md) bölüm 5) — **gerçek fatura sağlayıcıdan gelir.** |
| **Hız** | Donanıma bağlı. [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) içinde kayıtlı ölçüm: basit bir Türkçe soru ~9,7 sn (düşünme modeli). | Genellikle daha hızlı — `doğrulanamadı`, ölçülmedi. |
| **Model kalitesi** | Donanımın kaldırdığı boyutla sınırlı (12B'ye kadar doğrulanmış modeller). | 49B–235B aralığında modeller erişilebilir. |
| **Kesinti riski** | Yalnızca kendi bilgisayarınız. Sunucu kapalıysa bağlanılamaz. | İnternet, güvenlik duvarı, sağlayıcı arızası, kota. |
| **Uygulamadaki doğrulama** | **Gerçek istekle doğrulandı** (`pytest -m live` ve `check-ai`) | **Gerçek çağrı yapılmadı** — yalnızca sahte HTTP testleri |
| **Model adı yönetimi** | Uygulama `/v1/models` ucundan doğrular, yanlış adda mevcut listeyi gösterir | Uygulama model önermez; adı **elle yazmanız** gerekir |
| **Bağlam penceresi** | Katalogda bilinçli olarak `None` — aynı model farklı ayarlarla yüklenebilir | 128K'ya kadar |

---

## 4. Uygulamanın bugünkü kısıtları (model seçimini etkileyenler)

Model seçmeden önce bilinmesi gerekenler — hepsi koddan doğrulanmıştır:

1. **Uzak sağlayıcıya model önerilmez.** `catalog.model_for_task()` LM Studio
   dışındaki sağlayıcılar için boş metin döner. `HOTEL_NVIDIA_CHAT_MODEL`
   tanımlamazsanız istekte model adı boş gider.
2. **Yapay Zekâ Merkezi'ndeki model listesi eksik kalır.**
   `AIService.model_options()` yalnızca yapılandırılmış `chat_model` değerini
   ve katalogdaki **LM Studio** modellerini listeler. NVIDIA modelleri
   açılır listede görünmez.
3. **Maliyet tahmini her zaman 0'dır.** Katalogda yalnızca altı ücretsiz LM
   Studio modeli kayıtlıdır.
4. **`max_tokens` sabittir.** JSON görevlerinde 2048, metin görevlerinde 1536.
   Ayarlar ekranındaki değer gerçek çağrıya yansımaz.
5. **Düşünme kipini kapatma seçeneği yoktur.** Arayüzde böyle bir kontrol
   bulunmaz.
6. **Gömme, görsel ve uzun belge akışları bağlı değildir.**

---

## 5. Öneri: hangi iş için hangi seçenek

| İş | Öneri | Gerekçe |
|---|---|---|
| Misafir adı/iletişimi geçen her iş — mesaj taslağı, şikayet yanıtı, misafir yorumu analizi | **YEREL (LM Studio)** | KVKK. Uygulama iletişim bilgisini maskeler ama bağlamın tamamı (şikayetin içeriği, oda numarası, tarih) yine de dışarı çıkar. |
| Kimlik / pasaport / fatura görüntüsü okuma | **YEREL — kesinlikle** | Özel nitelikli kişisel veri. Maskeleme katmanı görüntü içeriğine etki edemez. Yurt dışına aktarım ayrı bir hukuki gerekçe ister. |
| Günlük özet, doluluk analizi, fiyat önerisi | **YEREL tercih edilir** | İstem yalnızca sayı içerir, ama doluluk/ADR/RevPAR ticari sırdır. Yerel model bu iş için yeterlidir. |
| Belge arama / RAG *(akış yok)* | **YEREL** | Belgeler misafir ve sözleşme verisi içerir. |
| Kod yardımı (AI Geliştirme Merkezi) | **Bulut kabul edilebilir** | Misafir verisi içermez. Karar ticari: kaynak kodunuzun sağlayıcıya gitmesini istiyor musunuz? |
| Yerel donanımın yetmediği ağır analiz, çok dilli özet, taslak fikir üretimi | **Bulut (NVIDIA) — yedek olarak** | `HOTEL_AI_PRIMARY_PROVIDER=lmstudio`, `HOTEL_AI_FALLBACK_PROVIDER=nvidia` kurgusu, yerel sunucu kapalıyken hizmeti sürdürür. |

### Önerilen varsayılan yapılandırma

```ini
HOTEL_AI_ENABLED=true
HOTEL_AI_PRIMARY_PROVIDER=lmstudio
HOTEL_AI_FALLBACK_PROVIDER=mock        # ya da nvidia (aşağıdaki uyarıyı okuyun)
```

> **Yedeği `nvidia` yapmadan önce düşünün.** Yedeğe geçiş bağlantı hatası,
> zaman aşımı ve kota hatalarında **otomatik** olur. LM Studio kapalı
> kaldığında misafir verisi içeren bir taslak isteği farkında olmadan buluta
> gidebilir. Yedek `mock` seçilirse gerçek bir model çağrılmaz; uygulama
> çökmez, yer tutucu bir yanıt döner ve veri kurumdan çıkmaz.
>
> Bulut yedeğini yalnızca gizlilik riski düşük görevlerde kullanacaksanız
> açın; bugün uygulamada görev bazlı sağlayıcı seçimi **yoktur**.

### KVKK açısından kayda değer noktalar

- Bulut sağlayıcı kullanımı **yurt dışına veri aktarımıdır**. Aydınlatma
  metni, açık rıza ve varsa kurumsal bağlayıcı kurallar açısından kendi
  hukuk danışmanınıza sorun. Bu belge hukuki görüş değildir.
- Uygulamanın gizlilik katmanları (bkz. [AI_CONFIGURATION.md](AI_CONFIGURATION.md)
  bölüm 6) e-posta, telefon ve uzun numara dizilerini maskeler; **ad-soyadı
  maskelemez.**
- `AIUsage` tablosu istem ve yanıt metnini saklamaz; sağlayıcının kendi
  tarafında ne sakladığı ayrı bir konudur ve sağlayıcının sözleşmesine bakılmalıdır.

---

## 6. Uygulamaya yeni model ekleme

### En basit yol — kod değiştirmeden

`.env` dosyasına model kimliğini yazın:

```ini
HOTEL_NVIDIA_CHAT_MODEL=meta/llama-3.3-70b-instruct
```

Bu yeterlidir: `catalog.model_for_task()` sağlayıcı ayarındaki `chat_model`
alanını en yüksek öncelikle okur. Rol bazlı ayrım isterseniz
`HOTEL_NVIDIA_VISION_MODEL`, `HOTEL_NVIDIA_MATH_MODEL`,
`HOTEL_NVIDIA_EMBED_MODEL` satırlarını da ekleyebilirsiniz.

Bu yolun **eksiği**: model Yapay Zekâ Merkezi'ndeki açılır listede "otomatik"
seçeneğinden sonra tek başına görünür, katalog bilgisi (yetenek, düşünme
modeli mi, maliyet) olmadığı için maliyet tahmini 0 kalır.

### Katalog kaydı ekleme — kod değişikliği gerektirir

`app/ai/catalog.py` bugün **yalnızca LM Studio modellerini** tanır:

```python
LMSTUDIO_MODELS: Final[tuple[ModelSpec, ...]] = (...)

#: Tum bilinen modeller, kimlik -> kayit.
KNOWN_MODELS: Final[dict[str, ModelSpec]] = {spec.model_id: spec for spec in LMSTUDIO_MODELS}
```

NVIDIA modellerini tanıtmak için:

1. **Yeni bir demet tanımlayın.** `ModelSpec` alanları:

   | Alan | Anlamı |
   |---|---|
   | `model_id` | API'ye gönderilen gerçek kimlik |
   | `display_name` | Arayüzde görünen ad |
   | `provider_type` | `AIProviderType.NVIDIA` |
   | `capabilities` | `AICapability` kümesi (`CHAT`, `VISION`, `JSON_MODE`, `MATH`, `EMBEDDING`, `REASONING`, `CODE`, `LONG_CONTEXT`, `TOOL_USE`) |
   | `context_window` | Bağlam penceresi (bilinmiyorsa `None`) |
   | `supports_reasoning` | Düşünme modeliyse `True` — `max_tokens` cömert ayarlanmalı |
   | `input_cost_per_1k`, `output_cost_per_1k` | `Decimal` fiyat; **doldurulmazsa maliyet 0 kalır** |
   | `recommended_default` | Otel senaryolarında varsayılan yapılabilir mi? |
   | `notes` | Tuzaklar ve uyarılar (katalogdaki mevcut kayıtlar bu alanı ciddiyetle kullanır) |

2. **`KNOWN_MODELS` sözlüğünü genişletin** — bugün yalnızca `LMSTUDIO_MODELS`
   üzerinden kuruluyor; yeni demeti de kapsayacak şekilde birleştirilmelidir.
   Bu adım atlanırsa `lookup()`, `estimate_cost()` ve
   `models_for_provider()` yeni modeli görmez.

3. **Rol önerisi istiyorsanız** `model_for_task()` içindeki
   "LM Studio değilse boş metin dön" kuralını gözden geçirin. Bu kural
   bilinçlidir ve bir testle korunur
   (`tests/ai/test_registry.py::TestKatalog::test_uzak_saglayiciya_yerel_model_onerilmez`);
   değiştirilecekse testin gerekçesi de güncellenmelidir.

4. **Arayüz listesinde görünmesi için** `AIService.model_options()` metodunu
   genişletin — bugün yalnızca `catalog.LMSTUDIO_MODELS` üzerinde dolaşıyor.

5. **Test yazın.** `tests/ai/test_registry.py::TestKatalog` içindeki kalıbı
   izleyin; gerçek çağrı yapmadan katalog kaydının doğruluğu sınanabilir.

### Fiyat bilgisini nereye yazmalı?

İki yer vardır ve **ikisi de bugün servis tarafından okunmuyor** olabilir:

- `ModelSpec.input_cost_per_1k` / `output_cost_per_1k` — `AIService`
  maliyeti buradan hesaplar (`catalog.estimate_cost`). **Doldurulursa çalışır.**
- `AIModel` veritabanı tablosundaki aynı adlı sütunlar ve
  `AIModel.estimate_cost()` metodu — **`AIService` bu tabloyu okumaz.**
  Veritabanı üzerinden yapılandırma öngörülmüş ama bağlanmamıştır.

Uzak sağlayıcı fiyatları sık değiştiği için koda gömmek de bir bakım yüküdür.
Gerçek gideri her hâlükârda sağlayıcının faturasından takip edin.

---

## 7. Değerlendirme yapmak isterseniz: minimum kontrol listesi

Bir aday modeli üretimde kullanmadan önce en az şunları kendi anahtarınızla
ölçün:

- [ ] Türkçe yanıt akıcı mı, dilbilgisi hataları var mı?
- [ ] Sistem istemindeki "yalnızca verilen sayıları kullan, veri uydurma"
      talimatına uyuyor mu?
- [ ] Fiyat önerisi görevinde şemaya birebir uyan JSON üretiyor mu?
      (`ozet`, `oneriler[].tarih/oda_tipi/onerilen_fiyat/gerekce`)
- [ ] Yorum analizi görevinde `duygu` alanı yalnızca
      `olumlu|notr|olumsuz` değerlerinden birini veriyor mu?
- [ ] Düşünme modeliyse 2048 jeton bütçesi yeterli mi, yoksa `content`
      boş mu dönüyor?
- [ ] Ortalama yanıt süresi kaç saniye? Resepsiyon akışını yavaşlatıyor mu?
- [ ] Aynı istem 5 kez gönderildiğinde çıktı ne kadar değişiyor?
      (fiyat önerisinde tutarlılık önemlidir)
- [ ] 10 çağrının maliyeti NVIDIA panelinde ne kadar görünüyor?

Ölçüm sonuçlarını bu belgeye eklerken **hangi tarihte, hangi model sürümüyle
ve kaç örnekle** ölçtüğünüzü yazın. Ölçülmemiş bir satırı "doğrulandı"
işaretlemek, bu belgenin tüm değerini yok eder.

---

## Kaynaklar

Aşağıdaki kaynaklar 15.08.2026 tarihinde erişilmiştir.

- [NVIDIA NIM LLM API referansı (docs.api.nvidia.com)](https://docs.api.nvidia.com/nim/reference/llm-apis)
- [meta/llama-3.2-90b-vision-instruct model referansı](https://docs.api.nvidia.com/nim/reference/meta-llama-3_2-90b-vision-instruct)
- [nvidia/llama-3.2-nv-embedqa-1b-v2 model referansı](https://docs.api.nvidia.com/nim/reference/nvidia-llama-3_2-nv-embedqa-1b-v2)
- [Access to NVIDIA NIM Now Available Free to Developer Program Members (NVIDIA Technical Blog)](https://developer.nvidia.com/blog/access-to-nvidia-nim-now-available-free-to-developer-program-members/)
- [nvidia/Llama-3_3-Nemotron-Super-49B-v1 model kartı (Hugging Face)](https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1)
- [Qwen/Qwen3-235B-A22B model kartı (Hugging Face)](https://huggingface.co/Qwen/Qwen3-235B-A22B)
- [Llama-3.3-70b-Instruct (NGC Catalog)](https://catalog.ngc.nvidia.com/orgs/nim/teams/meta/containers/llama-3.3-70b-instruct)

**Erişilemeyen kaynak:** <https://build.nvidia.com/models> — otomatik
erişimde zaman aşımına uğradı; katalogdaki güncel model listesi bu nedenle
doğrulanamadı.
