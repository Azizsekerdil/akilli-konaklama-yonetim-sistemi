# LM Studio Kurulumu ve Yapilandirmasi

Bu belge, uygulamanin **yerel** yapay zeka ozelliklerini LM Studio ile
calistirmak icin gereken adimlari anlatir.

Yerel model kullanmanin iki onemli avantaji vardir:

- **Veri disari cikmaz.** Misafir bilgileri, doluluk verisi ve mali rakamlar
  bilgisayarinizdan ayrilmaz. KVKK acisindan en guvenli secenektir.
- **Maliyet yoktur.** Jeton basina ucret odenmez.

Karsiliginda yanit sureleri bulut servislerine gore daha uzundur ve model
kalitesi donaniminiza baglidir.

---

## 1. LM Studio'yu kurun

1. <https://lmstudio.ai> adresinden Windows surumunu indirin ve kurun.
2. Uygulamayi acin.

## 2. Model indirin

Sol menudeki arama (buyutec) sekmesinden model indirin. Bu projede
**dogrulanmis** ve rol atamasi yapilmis modeller:

| Model | Rol | Not |
|---|---|---|
| `google/gemma-4-12b-qat` | Genel otel asistani, yonetim analizi | **Dusunme (reasoning) modelidir** - asagiya bakin |
| `qwen/qwen3-vl-8b` | Gorsel belge / oda fotografi analizi | Gorsel destekli |
| `qwen2.5-math-7b-instruct` | Fiyat ve matematiksel analiz | Sayisal islemlerde daha tutarli |
| `moondream-2b-2025-04-14` | Hafif gorsel gorevler | Kucuk ve hizli |
| `text-embedding-nomic-embed-text-v1.5` | Belge arama (RAG) | Gomme modeli - sohbet icin kullanilmaz |
| `biomistral-7b` | — | Saglik alanina yoneliktir; **otel yonetiminde varsayilan yapilmaz** |

> En az bir sohbet modeli ve bir gomme modeli indirmeniz onerilir.
> Belge soru-cevap (RAG) ozelligi gomme modeli olmadan calismaz.

## 3. Yerel sunucuyu baslatin

1. Sol menuden **Developer** (veya **Local Server**) sekmesine gecin.
2. Yuklemek istediginiz modeli secin.
3. **Start Server** dugmesine basin.
4. Ekranda gorunen adresi not edin. Varsayilan:

```
http://127.0.0.1:1234/v1
```

> **Onemli:** Adresi tahmin etmeyin. LM Studio farkli bir port kullaniyorsa
> (or. 1235), uygulamanin Ayarlar ekranindan bu adresi guncelleyin.

## 4. Uygulamada dogrulayin

Ayarlar > Yapay Zeka ekranindan **Baglantiyi Test Et** dugmesine basin.
Alternatif olarak komut satirindan:

```bash
.\.venv\Scripts\python.exe -m app.cli check-ai
```

Basarili ciktida sunucudaki gercek model listesi gorunur. Uygulama model
adlarini tahmin etmez; LM Studio'nun `/v1/models` ucundan dogrular. Ayarlarda
yazili model adi sunucuda yoksa, hata mesajinda **mevcut modellerin listesi**
gosterilir.

---

## Dusunme (reasoning) modelleri hakkinda

`google/gemma-4-12b-qat` yaniti uretmeden once **kendi icinde akil yurutur**.
Bu, API yanitinda ayri bir alan olarak gelir:

```json
{
  "choices": [{
    "message": {
      "content": "Ben, Google tarafindan egitilmis bir yapay zekayim.",
      "reasoning_content": "Language: Turkish... Task: self-introduction..."
    }
  }],
  "usage": {
    "completion_tokens": 356,
    "completion_tokens_details": { "reasoning_tokens": 322 }
  }
}
```

Bunun iki pratik sonucu vardir:

1. **`max_tokens` degerini dusuk tutmayin.** Ornekte 356 jetonun 322'si
   dusunmeye harcanmistir. `max_tokens` 60 olsaydi model dusunme asamasinda
   tukenir ve `content` **bos** donerdi. Uygulama bu durumu tespit edip
   anlamli bir uyari gosterir, ancak yine de en az 1024 jeton onerilir.
2. **Yanitlar daha yavastir.** Ornek olcumde basit bir Turkce soru
   ~9.7 saniyede yanitlanmistir (donaniminiza gore degisir).

Hiz onemliyse Ayarlar'dan daha kucuk bir model secebilirsiniz.

---

## Sik karsilasilan sorunlar

| Belirti | Neden | Cozum |
|---|---|---|
| "Yapay zeka saglayicisina baglanilamadi" | Sunucu calismiyor | LM Studio > Developer > **Start Server** |
| Baglanti var ama model bulunamadi | Ayarlardaki model adi sunucudakinden farkli | Hata mesajindaki mevcut model listesinden dogru adi secin |
| Yanit bos geliyor | `max_tokens` dusunme icin yetersiz | Ayarlardan `max_tokens` degerini 2048'e cikarin |
| Yanit cok yavas | Model donaniminiz icin buyuk | Daha kucuk bir model secin veya GPU hizlandirmayi acin |
| Zaman asimi | Ilk yukleme model dosyasini belleğe aliyor | Zaman asimi suresini artirin (Ayarlar > Yapay Zeka > Timeout) |
| Turkce yanit gelmiyor | Sistem mesaji Ingilizce | Ayarlardaki sistem mesajina "Turkce yanit ver" ekleyin |

---

## Yedek saglayici

LM Studio kapaliyken uygulamanin **cokmemesi** icin bir yedek saglayici
tanimlanabilir (Ayarlar > Yapay Zeka > Yedek Saglayici).

Yedege gecis yalnizca **gecici** hatalarda yapilir: baglanti kurulamamasi,
zaman asimi veya kota dolmasi. Gecersiz API anahtari veya bulunamayan model
gibi **kalici** hatalarda yedege gecilmez - ayni hata yedekte de
tekrarlanacagi icin bu yalnizca gecikme ve gereksiz maliyet uretirdi.

Yedek saglayici `mock` secilirse gercek bir model cagrilmaz; uygulama
"yapay zeka su anda kullanilamiyor" bilgisiyle calismaya devam eder.

---

## Guvenlik notu

- LM Studio API anahtari dogrulamasi yapmaz. Sunucuyu **yalnizca
  `127.0.0.1`** uzerinde calistirin; ag uzerine acmayin.
- Yapay zekaya gonderilen istemlerde misafir kimlik numarasi gibi ozel
  nitelikli veriler bulunmaz. Belge indeksinde `is_sensitive` isaretli
  belgeler modele gonderilmez.
- Yapay zeka ciktilari **her zaman** "AI tarafindan olusturuldu" rozetiyle
  isaretlenir. Kritik isletme kararlarinda dogrulama yapiniz.

İlgili belgeler: [AI_CONFIGURATION.md](AI_CONFIGURATION.md) ·
[NVIDIA_API_SETUP.md](NVIDIA_API_SETUP.md) · [SECURITY_REVIEW.md](SECURITY_REVIEW.md)
