# NVIDIA API Kurulumu

Bu belge, uygulamanın **bulut** yapay zekâ sağlayıcısı olarak NVIDIA NIM
(build.nvidia.com) hizmetini kullanmak için yapmanız gereken adımları anlatır.

> **Anahtarı biz oluşturmayız.** API anahtarını siz kendi NVIDIA hesabınızda
> üretir, uygulamaya kendiniz girersiniz. Bu belge yalnızca hangi düğmeye
> basacağınızı ve anahtarı **nereye yazmayacağınızı** anlatır.

> **Uygulamanın NVIDIA adaptörü ile bugüne kadar gerçek bir API çağrısı
> yapılmamıştır.** Kod, sahte HTTP aktarımı (`respx`) üzerinde kurulan dört
> testle doğrulanmıştır (`tests/ai/test_providers.py::TestNvidia`). Model
> seçimi ve beklentiler için [NVIDIA_MODEL_EVALUATION.md](NVIDIA_MODEL_EVALUATION.md)
> belgesindeki uyarıyı da okuyun.

İlgili belgeler: [AI_CONFIGURATION.md](AI_CONFIGURATION.md) ·
[LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) · [ROADMAP.md](ROADMAP.md)

---

## Önce şunu bir düşünün: gerçekten buluta ihtiyacınız var mı?

| | LM Studio (yerel) | NVIDIA (bulut) |
|---|---|---|
| Misafir verisi kurumdan çıkar mı? | **Hayır** | **Evet** — istem NVIDIA sunucularına gider |
| Maliyet | Yok (elektrik dışında) | Kredi/kota tüketir |
| İnternet gerekir mi? | Hayır | Evet |
| Hız | Donanımınıza bağlı | Genellikle daha hızlı |
| Model kalitesi | Donanımınızın kaldırdığı kadar | Çok daha büyük modeller |

KVKK açısından misafir verisiyle ilişkili işlerde **yerel model tercih
edilmelidir**. Uygulama istemlerden kimlik/iletişim bilgisini zaten çıkarır
(bkz. [AI_CONFIGURATION.md](AI_CONFIGURATION.md) bölüm 6), ancak doluluk,
ciro ve fiyat bilgisi de ticari sırdır ve bulut sağlayıcıya gider.

---

## 1. NVIDIA hesabı ve model katalogu

1. <https://build.nvidia.com> adresine gidin.
2. Sağ üstten **Sign In / Get Started** ile NVIDIA hesabınıza girin. Hesabınız
   yoksa e-posta ile ücretsiz oluşturabilirsiniz.
3. Ana sayfadaki katalogdan modellere göz atın. Her modelin bir kartı vardır;
   kartta örnek kod, model kimliği ve model kartı (modelcard) bağlantısı
   bulunur.

> **Doğrulanamadı:** Katalogdaki güncel model listesi ve bu modellerin
> uygulamayla uyumu bu belgeyi yazarken doğrudan doğrulanamadı;
> `build.nvidia.com` sayfaları otomatik erişime kapalı davrandı. Kullanmayı
> düşündüğünüz modelin kimliğini kataloğun kendisinden okuyun.

Uygulamanın kullandığı uç nokta OpenAI uyumludur:

```
https://integrate.api.nvidia.com/v1
POST /chat/completions
GET  /models
POST /embeddings
```

Bu taban adres `NvidiaProvider.DEFAULT_BASE_URL` içinde sabittir ve
`tests/ai/test_providers.py::TestNvidia::test_varsayilan_adres` ile sınanır.

---

## 2. API anahtarı oluşturma

1. build.nvidia.com'da oturum açtıktan sonra sağ üstteki **profil menüsünü**
   açın.
2. **Settings** (Ayarlar) → **API Keys** yolunu izleyin. Doğrudan adres:
   <https://build.nvidia.com/settings/api-keys>
3. **Generate Key** (Anahtar Üret) düğmesine basın.
4. Anahtara açıklayıcı bir ad verin (örneğin `otel-pms-uretim`) — ileride hangi
   anahtarın nerede kullanıldığını bilmek, sızıntı durumunda yalnızca doğru
   anahtarı iptal etmenizi sağlar.
5. Üretilen anahtar `nvapi-` önekiyle başlar.

> **Anahtar yalnızca bir kez gösterilir.** Sayfayı kapatmadan önce güvenli bir
> yere alın. Kaybederseniz yenisini üretip eskisini iptal etmeniz gerekir.
>
> Anahtarı **e-postayla, sohbet penceresine, ekran görüntüsüne veya bir issue
> kaydına yapıştırmayın.** Bir parola yöneticisi kullanın.

*(Adım adlandırmaları NVIDIA arayüzü değiştikçe farklılaşabilir. Menü adları
bu belgede genel erişilebilir kaynaklardan derlenmiştir ve
**doğrulanamamıştır**; ekranda gördüğünüz metni esas alın.)*

---

## 3. Anahtarı güvenli girme

### Önerilen yol — Uygulama içinden (Windows Credential Manager)

1. Uygulamayı açın ve **Ayarlar** ekranına gidin.
2. **Yapay Zekâ** sekmesini seçin.
3. **Sağlayıcı Ayarları** kartındaki açılır listeden `nvidia` seçin.
4. **API Anahtarı** kartındaki **Yeni Anahtar** alanına anahtarı yapıştırın.
   Alan parola kipindedir; yazdığınız değer ekranda **hiçbir zaman okunabilir
   olmaz**.
5. **Anahtarı Kaydet** düğmesine basın.

Bu düğme değeri `set_secret("nvidia_api_key", ...)` ile **Windows Credential
Manager**'a yazar (`app/core/secret_store.py`, servis adı
`AkilliKonaklamaYonetimSistemi`). Kaydettikten sonra:

- **Kayıtlı Anahtar** satırında yalnızca maskeli özet görünür
  (`nvap...cdef` biçiminde).
- Girdi alanı otomatik temizlenir; değer bellekte gereksiz yere durmaz.
- Sağlayıcı önbelleği `reset_registry()` ile sıfırlanır, yeni anahtar hemen
  geçerli olur.

> Bu işlem için **Sağlayıcı/model yapılandırma** (`ai.configure`) yetkisi
> gerekir. Yetkiniz yoksa alan devre dışıdır ve ekranda gerekçesi yazar.

**Keyring kullanılamıyorsa uygulama sessizce "kaydedildi" demez.** `set_secret`
yazma başarısız olursa `SecretBackend.ENV` döner, ekranda şu uyarı belirir:

> Anahtar deposu kullanılamadı; anahtar KAYDEDİLMEDİ. '.env' dosyasına şu
> satırı ekleyin: HOTEL_NVIDIA_API_KEY=...

### Alternatif — `.env` dosyası (yalnızca geliştirme)

Proje kökündeki `.env` dosyasına:

```ini
HOTEL_NVIDIA_API_KEY=nvapi-...
```

`.env` dosyası `.gitignore` içindedir, yani Git'e girmez. **Ama diskte düz
metin olarak durur.** Üretim kurulumunda keyring tercih edilmelidir.

### Anahtar nasıl çözülür?

`NvidiaProvider._resolve_api_key()` sırayla bakar:

1. Yapıcıya doğrudan verilen değer (yalnızca testlerde)
2. **Windows Credential Manager** — `nvidia_api_key` adı altında
3. `.env` / ortam değişkeni — `HOTEL_NVIDIA_API_KEY`

Hiçbirinde yoksa Türkçe çözüm önerisiyle `AIAuthenticationError` fırlatılır.

Çözümleme **tembeldir**: kayıt (registry) uygulama açılışında tüm
sağlayıcıları kurar; anahtar yoksa yapıcının patlaması, NVIDIA hiç
kullanılmayacak olsa bile tüm yapay zekâ katmanını çalışmaz hale getirirdi.

### Anahtar ASLA şuralara yazılmaz

| Yer | Durum | Nasıl sağlanıyor |
|---|---|---|
| Kaynak kodu | Yazılmaz | Anahtar yalnızca çalışma zamanında çözülür |
| Veritabanı | Yazılmaz | `AIProvider` tablosu yalnızca `secret_name` tutar, değeri değil |
| Log dosyaları | Maskelenir | `app/core/log.py` `nvapi-` önekini ve `Authorization: Bearer ...` başlıklarını `***MASKELENDI***` yapar |
| Hata mesajları / ayrıntı alanı | Yazılmaz | Anahtar yoksa yalnızca aranan **ad** kaydedilir: `'nvidia_api_key' keyring'de de ortamda da bulunamadi` |
| Ekran | Maskelenir | Girdi parola kipinde, kayıtlı değer `mask_secret()` ile özetlenir |
| Sohbet / yapay zekâ istemleri | Gönderilmez | Anahtar yalnızca HTTP başlığında taşınır, istem gövdesine hiç girmez |

Log maskelemesi doğrulanmıştır:

```
>>> mask_text('anahtar nvapi-abc123def456ghi burada')
'anahtar ***MASKELENDI*** burada'
```

Anahtarın hata ayrıntısına sızmadığını sınayan test:
`tests/ai/test_providers.py::TestNvidia::test_anahtar_yoksa_kimlik_hatasi`
— `assert "nvapi" not in str(hata.value.detail or "")`.

Anahtarın gerçekten `Authorization: Bearer` başlığında gittiğini sınayan test:
`test_anahtar_bearer_basliginda_gonderilir`.

---

## 4. NVIDIA'yı sağlayıcı olarak seçme

Anahtarı kaydettikten sonra sağlayıcıyı da seçmeniz gerekir. `.env` dosyasında:

```ini
HOTEL_AI_ENABLED=true
HOTEL_AI_PRIMARY_PROVIDER=nvidia
HOTEL_AI_FALLBACK_PROVIDER=lmstudio     # yerel yedek; mock da olabilir
HOTEL_NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
HOTEL_NVIDIA_CHAT_MODEL=<katalogdan-alacaginiz-model-kimligi>
```

> **`HOTEL_NVIDIA_CHAT_MODEL` boş bırakılırsa istekte model adı boş gider.**
> Uygulama uzak sağlayıcılara **kendi kataloğundan model önermez**; katalogdaki
> öneri listesi yalnızca LM Studio içindir. `google/gemma-4-12b-qat` adını
> NVIDIA'ya göndermek kesin bir 404 üretirdi. Bu davranışı sınayan test:
> `tests/ai/test_registry.py::TestKatalog::test_uzak_saglayiciya_yerel_model_onerilmez`
>
> Sonuç: NVIDIA kullanacaksanız model kimliğini **elle yazmanız gerekir**.

Görsel/matematik/gömme rolleri için ayrı model tanımlamak isterseniz aynı
önekle devam edin (bu satırlar `.env.example` içinde yoktur ama okunur):

```ini
HOTEL_NVIDIA_VISION_MODEL=...
HOTEL_NVIDIA_MATH_MODEL=...
HOTEL_NVIDIA_EMBED_MODEL=...
```

---

## 5. Bağlantı testi

### Ayarlar ekranından (önerilen)

Ayarlar > Yapay Zekâ > **Bağlantıyı Test Et** düğmesi, yapılandırılmış her
sağlayıcı için `/models` ucunu yoklar ve tabloya `Çalışıyor` / `Ulaşılamıyor`
yazar. Sağlık kontrolü **hata fırlatmaz**; başarısızlık da geçerli bir
sonuçtur.

### Komut satırından

```powershell
.\.venv\Scripts\python.exe -m app.cli check-ai
```

> **Bilinen hata (15.08.2026 tarihinde doğrulandı):** Bu komut, bir sağlayıcı
> sağlıklı dönüp model listesi bulduğunda çöker:
>
> ```
> File "C:\AkilliKonaklama\app\cli.py", line 194, in cmd_check_ai
>     print(f"    Modeller: {len(status.models_found)} adet")
> TypeError: object of type 'int' has no len()
> ```
>
> Sağlayıcı adı ve durum satırı ekrana basılır, ardından komut çıkış kodu 1
> ile sonlanır. Düzeltilene kadar **Ayarlar ekranındaki düğmeyi** kullanın.

---

## 6. Ücretlendirme uyarısı

> **NVIDIA API çağrıları kredi/kota tüketir.**
>
> - Uygulama bir maliyet **tahmini** gösterir, ancak
>   [AI_CONFIGURATION.md](AI_CONFIGURATION.md) bölüm 5'te açıklandığı gibi
>   **bu tahmin şu anda her model için `0.000000` döner.** Uzak sağlayıcı
>   fiyatları koda gömülü değildir.
> - **Gerçek fatura ve kredi tüketimi sağlayıcıdan gelir.** Kullanımınızı
>   NVIDIA'nın kendi panelinden takip edin.
> - Anahtarınız sızarsa krediyi/kotayı **başkası harcar**. Anahtarı Git'e
>   koymayın, ekran görüntüsüne almayın; şüphelenirseniz build.nvidia.com
>   üzerinden iptal edip yenisini üretin.
> - Düşünme (reasoning) modelleri, kullanıcıya gösterilmeyen akıl yürütme
>   metni için de jeton harcar. Uygulama bunu `reasoning_tokens` olarak ayrı
>   sayar ve toplama ekler; sağlayıcı da faturaya ekler.

**Doğrulanamadı:** NVIDIA'nın güncel ücretsiz kredi miktarı, hız sınırı ve
üretim fiyatlandırması bu belgeyi yazarken resmî kaynaktan tam olarak
doğrulanamadı. NVIDIA'nın kendi geliştirici blogu, Developer Program
üyelerine **indirilebilir** NIM mikroservisleri için ücretsiz erişim
verildiğini ve NVIDIA'nın barındırdığı uç noktalar için API Catalog üzerinden
"ücretsiz kredi" sunulduğunu belirtir; kredi adedi ve dakikadaki istek sınırı
gibi sayılar yalnızca üçüncü parti kaynaklarda geçmektedir. Güncel koşulları
kendi hesabınızın faturalandırma sayfasından doğrulayın.

---

## 7. Sorun çıktığında uygulama ne yapar?

Aşağıdaki davranışlar `app/ai/errors.py` ve `app/ai/registry.py` içinden
doğrulanmıştır.

### Geçersiz veya eksik anahtar (HTTP 401 / 403)

| Konu | Davranış |
|---|---|
| Hata tipi | `AIAuthenticationError` |
| Yeniden denenir mi? | **Hayır** — kalıcı hata |
| Yedeğe geçilir mi? | **HAYIR** |
| Kullanıcıya gösterilen | "Ayarlar > Yapay Zeka ekranından anahtarınızı girin. Anahtar işletim sisteminin güvenli deposunda saklanır, veritabanına yazılmaz." |
| `AIUsage` kaydı | `status=failed`, `error_code` dolu |

**Neden yedeğe geçilmez?** Anahtar hatasını yedekle gizlemek, kullanıcının
sorunu görmesini engeller: anahtarının bozuk olduğunu asla öğrenemez ve
aylarca farkında olmadan başka bir sağlayıcıya çalışır.

Anahtar hiç tanımlı değilse istek ağa **hiç çıkmaz**; adaptör anahtarı
çözerken hatayı fırlatır. `NvidiaProvider.health_check()` bu hatayı yakalayıp
`ok=False` döndüğü için Ayarlar ekranı yine de açılır.

### Kota / hız sınırı dolması (HTTP 429)

| Konu | Davranış |
|---|---|
| Hata tipi | `AIQuotaError` |
| Yeniden denenir mi? | **Evet** — `HOTEL_AI_MAX_RETRIES` kadar (varsayılan 2), üstel geri çekilmeyle (0.5 sn, 1 sn) |
| Yedeğe geçilir mi? | **Evet** — geçici hata |
| Kullanıcıya gösterilen | "Kota veya hız sınırı aşıldı. Birkaç dakika bekleyin, faturalandırmanızı kontrol edin ya da yerel (ücretsiz) bir modele geçin." |

Yedek `lmstudio` olarak ayarlanmışsa istek yerel modele döner, yanıtta
`used_fallback=True` işareti taşır ve arayüzde "yedek sağlayıcı kullanıldı"
yazar.

### Model bulunamadı (HTTP 404)

| Konu | Davranış |
|---|---|
| Hata tipi | `AIModelNotFoundError` |
| Yeniden denenir mi? | **Hayır** |
| Yedeğe geçilir mi? | **HAYIR** — model adı sağlayıcıya özeldir, yedekte de bulunmaz |
| Kullanıcıya gösterilen | "Model sunucuda yüklü değil. Ayarlar > Yapay Zeka ekranından listeden bir model seçin; LM Studio kullanıyorsanız modeli önce yükleyin." |

> Not: LM Studio adaptörü 404 hatasını **mevcut model listesiyle
> zenginleştirir**. NVIDIA adaptörü bunu yapmaz; mesaj genel kalır.
> Model kimliğini build.nvidia.com katalog kartından kopyalayın.

### Bağlantı kurulamaması / zaman aşımı

| Durum | Hata tipi | Yedeğe geçilir mi? | Öneri metni |
|---|---|---|---|
| Ağ hatası, DNS, güvenlik duvarı | `AIConnectionError` | **Evet** | "İnternet bağlantınızı ve sunucu adresini kontrol edin. Kurum güvenlik duvarı erişimi engelliyor olabilir." |
| İstemci zaman aşımı, HTTP 408/504 | `AITimeoutError` | **Evet** | "Model süresinde yanıt vermedi. ... zaman aşımı süresini artırın veya daha küçük bir model seçin." |

408 ve 504 durumlarında **aynı sağlayıcıda tekrar denenmez**: model zaten
yavaş çalışıyordur, ikinci deneme kullanıcıyı yalnızca iki kat bekletir.
Bunun yerine doğrudan yedeğe geçilir.

### Sağlayıcı geçici arızası (5xx)

`AIProviderError` fırlatılır, `HOTEL_AI_MAX_RETRIES` kadar yeniden denenir,
sonra yedeğe geçilir. Öneri: "Sağlayıcı geçici olarak hata veriyor. Birkaç
dakika sonra tekrar deneyin; sorun sürerse yedek sağlayıcıya geçin."

### Model geçerli JSON üretemedi

Fiyat önerisi ve yorum analizi gibi JSON isteyen görevlerde model şemaya
uymayan bir çıktı verirse `AIResponseFormatError` fırlar. **Yedeğe geçilmez**
— aynı istek yedekte de aynı şekilde başarısız olur. Öneri: daha yetenekli bir
model seçmek veya isteği sadeleştirmek.

Sağlayıcı `response_format` parametresini reddederse (HTTP 400 + tanıdık bir
ifade) adaptör bunu bir kez algılar, o oturum için JSON kipini kapatır ve
istem tabanlı yönteme düşer — kullanıcıya hata gösterilmez.

---

## 8. Anahtarı kaldırma

Uygulama içinde anahtar **silme** düğmesi yoktur. Kaldırmak için:

- **Windows Credential Manager**'ı açın (Denetim Masası > Kimlik Bilgileri
  Yöneticisi > Windows Kimlik Bilgileri), `AkilliKonaklamaYonetimSistemi`
  servisi altındaki `nvidia_api_key` girdisini silin.
- `.env` dosyasına yazdıysanız `HOTEL_NVIDIA_API_KEY` satırını boşaltın.
- Ayrıca **build.nvidia.com üzerinden anahtarı iptal edin** — yerel kopyayı
  silmek, anahtarın başka bir yerde kullanılmasını engellemez.
