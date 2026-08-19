# Yapay Zekâ Şeffaflığı

Bu belge, programın yapay zekâ katmanının **ne yaptığını, neye karar
veremediğini ve verinin nereye gittiğini** anlatır. Ayrıntılı yapılandırma
için [docs/AI_CONFIGURATION.md](docs/AI_CONFIGURATION.md).

---

## 1. Yapay zekâ **isteğe bağlıdır**

`HOTEL_AI_ENABLED=false` yapıldığında programın yapay zekâ dışındaki tüm
işlevleri (rezervasyon, check-in/out, folyo, kat hizmetleri, teknik servis,
stok, raporlar) **eksiksiz çalışır**. Yapay zekâ bir yardımcıdır, bir bağımlılık
değildir.

## 2. Sağlayıcılar ve varsayılan

| Sağlayıcı | Nerede çalışır | Anahtar gerekir mi | Durum |
|---|---|---|---|
| **LM Studio** (varsayılan) | **Sizin bilgisayarınızda** | Hayır | Gerçek istekle doğrulandı |
| Mock | Bellekte, ağa çıkmaz | Hayır | Testlerde kullanılır |
| NVIDIA NIM | Bulut | Evet | **Gerçek bir çağrı hiç yapılmadı** — yalnızca sahte HTTP aktarımı üzerinde test edildi |
| OpenAI uyumlu | Bulut | Evet | Aynı — gerçek çağrı yapılmadı |
| Anthropic | Bulut | Evet | Aynı — gerçek çağrı yapılmadı |

**Varsayılan yereldir.** `HOTEL_AI_PRIMARY_PROVIDER=lmstudio`, yedek
`mock`'tur. Bir bulut sağlayıcısı **siz açıkça yapılandırmadıkça** devreye
girmez.

## 3. API anahtarları

- Depoda, örnek dosyalarda, testlerde, belgelerde, ekran görüntülerinde ve
  sunumda **hiçbir gerçek anahtar yoktur**. Bu, yayın öncesi
  `gitleaks`, `detect-secrets` ve `semgrep p/secrets` taramalarıyla
  doğrulandı; sonuçlar `docs/TEST_REPORT.md` özetinde durur.
- `.env.example` içindeki anahtar alanları **boştur**. Bir yer tutucu yazmak
  gerekiyorsa `YOUR_PROVIDER_API_KEY_HERE` biçimi kullanılır — gerçekçi
  görünen, tarayıcıları tetikleyen sahte bir jeton **asla** yazılmaz.
- Anahtarı **siz** kurulumdan sonra girersiniz: *Ayarlar → Yapay Zekâ*
  ekranından (tercihen Windows Credential Manager'a) veya bir ortam
  değişkeniyle.
- Anahtar yoksa sağlayıcı **NOT_CONFIGURED** durumunda görünür ve **hiçbir
  çağrı yapmaz**; yerel ve yapay zekâ dışı işlevler çalışmaya devam eder.
- Arayüzde yalnızca **sağlayıcı adı, durum ve anahtarın son 4 karakteri**
  gösterilir (`app/core/secret_store.py` → `mask_secret`).
- "Bağlantıyı test et" **yalnızca sizin açık eyleminizle** çalışır; anahtar
  hiçbir zaman loglanmaz.

## 4. Veri nereye gider?

| Mod | Veri nereye gider |
|---|---|
| LM Studio (yerel) | **Hiçbir yere.** İstem bilgisayarınızdaki modele gider |
| Mock | Hiçbir yere; ağ yok |
| Bulut sağlayıcı | İstem, o sağlayıcının sunucusuna gider |

Bulut moduna geçmeden önce: sağlayıcının **saklama** ve **eğitimde kullanma**
politikası onun politikasıdır ve bu program onu değiştiremez. KVKK açısından
bu bir **yurt dışına veri aktarımı** olabilir; değerlendirme işletmeye aittir.

**Redaksiyon katmanı.** Modele giden serbest metin, gönderilmeden önce
`redact_personal_data` süzgecinden geçer: e-posta, telefon ve uzun numara
dizileri maskelenir. İki sınırı açıkça yazalım:

1. **Ad-soyad otomatik olarak tespit edilemez.** Bir ada elle yazdıysanız o
   metin modele gider.
2. Redaksiyon bir **azaltmadır**, bir garanti değildir.

Yapılandırılmış sorgu sonuçları için ayrıca bir denetim vardır: istemde
e-posta/telefon/uzun numara kalırsa çağrı **sessizce değil, gürültüyle**
başarısız olur (`ValidationError`).

## 5. Yapay zekâ neye karar **veremez**

Bu, ürünün en önemli sınırıdır:

- **Fiyat değiştiremez.** Fiyat önerisi bir öneridir; uygulanması için
  kullanıcının *Fiyatlar* ekranından ayrıca onaylaması gerekir.
- **Rezervasyon oluşturamaz, iptal edemez, oda atayamaz.**
- **Tahsilat yapamaz, folyo kapatamaz.**
- **Misafir kaydı silemez, kara listeye alamaz.**
- Ürettiği metin (rezervasyon onayı, misafire mesaj taslağı) bir **taslaktır**;
  gönderme eylemi kullanıcıdadır.

Yapay zekânın veri değiştiren her önerisi için onay zorunluluğu ayarla
kapatılabilir (`HOTEL_AI_REQUIRE_APPROVAL_FOR_WRITES`); kapatılırsa program
açılışta bunu bir uyarı olarak bildirir. **Kapatmayın.**

## 6. AI Geliştirme Merkezi (kısıtlı terminal)

Programda, yapay zekâya kodlama görevi verilebilen bir geliştirme ekranı
vardır. Sınırları:

- **İzin listesi** hangi komutun çalışacağına karar verir; bilinmeyen komut
  asla sessizce çalışmaz, onay ister.
- **Hedef denetimi** hangi dosyaya dokunulabileceğine karar verir ve izin
  listesinden **önce** çalışır: `.env` ve türevleri, anahtar/sertifika
  dosyaları, kimlik bilgisi depoları ve misafir veritabanı/yedekleri —
  **hangi okuyucu kullanılırsa kullanılsın** — kapalıdır. (Bu kural, bağımsız
  bir yayın öncesi incelemede bulunan gerçek bir atlatmanın sonucudur:
  `head .env` gibi bir komut, izin listesindeki "güvenli" bir okuyucu olduğu
  için onaysız çalışabiliyordu.)
- Yazma yalnızca proje klasörü içinde yapılır; her değişiklik önce **fark
  (diff)** olarak gösterilir ve onaysız uygulanmaz.
- Alt sürece **sır geçirilmez**; çıktı maskeleme süzgecinden geçer.
- Görev ayrı bir dalda çalışır, başlamadan kontrol noktası alınır.

**Kalan sınır:** koruma dosya *hedefine* bakar. Bir komut hedefini çalışma
anında üretirse politika bunu göremez; bu yüzden `python -c` gibi genel
çalıştırıcılar izin listesinde değildir ve onay ister.

## 7. Model çıktısının doğruluğu

Üretilen metinler ve öneriler **doğrulanmamış** dil modeli çıktısıdır.

- Fiyat, doluluk ve gelir tahminleri **finansal tavsiye değildir.**
- Hiçbir çıktı hukuki, mali veya sağlıkla ilgili bir tavsiye olarak
  kullanılamaz.
- Modelin ürettiği her sayıyı programın kendi raporlarıyla doğrulayın:
  raporlar veritabanından hesaplanır, modelden değil.
