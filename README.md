# Akıllı Konaklama Yönetim Sistemi

Otel, butik otel, pansiyon, apart otel ve tatil köyü gibi konaklama
işletmeleri için geliştirilen, **Windows üzerinde çalışan, yapay zekâ
destekli** masaüstü otel yönetim sistemi (PMS).

Python 3.11 · PySide6 · SQLAlchemy 2.x · SQLite/PostgreSQL · MIT lisansı

> **Olgunluk: alpha (0.1.0).** Tek bir işletmenin bilgisayarında çalışacak
> biçimde tasarlandı; geniş bir kurulum tabanında denenmedi. Neyin
> **yapılmadığı** [docs/known-limitations.md](docs/known-limitations.md) ve
> [docs/ROADMAP.md](docs/ROADMAP.md) içinde açıkça yazılıdır — üretimde
> kullanmadan önce ikisini de okuyun.

**Ne yapar:** rezervasyon, check-in/check-out, folyo ve tahsilat, oda ve kat
hizmetleri, teknik servis, stok, misafir CRM (KVKK izinleriyle), yönetim
paneli ve raporlama; isteğe bağlı, **varsayılanı yerel** bir yapay zekâ
yardımcısı.

**Ne yapmaz:** e-Fatura/e-Arşiv göndermez, Kimlik Bildirim Sistemi'ne bildirim
yapmaz (ikisinde de yalnızca arayüz katmanı hazırdır), kanal yöneticisi /
OTA entegrasyonu yoktur, çok şubeli merkezi bir sunucu değildir, ödeme almaz
ve **hukuki, mali veya sağlıkla ilgili tavsiye vermez**.

---

## Bu proje ne durumda?

Dürüst bir özet — abartılmış bir özellik listesi yerine gerçekte ne çalıştığı:

| Alan | Durum |
|---|---|
| Veritabanı şeması (60 tablo) ve göçler | **Çalışıyor** |
| Rezervasyon motoru, çakışma engelleme, fiyatlandırma | **Çalışıyor**, test edilmiş |
| Check-in / check-out / folyo / tahsilat | **Çalışıyor**, test edilmiş |
| Rol bazlı yetkilendirme, oturum, denetim günlüğü | **Çalışıyor** |
| Kimlik verisi şifreleme (KVKK) | **Çalışıyor**, ham SQL ile doğrulanmış |
| Yönetim paneli (KPI, uyarılar, doluluk grafiği) | **Çalışıyor** |
| Raporlama ve PDF/Excel/CSV dışa aktarma | **Çalışıyor** |
| Yapay zekâ sağlayıcı adaptörleri (LM Studio, NVIDIA, OpenAI, Anthropic) | **Çalışıyor** — LM Studio gerçek istekle doğrulandı |
| AI Geliştirme Merkezi (kısıtlı terminal, diff, Git koruması) | **Çalışıyor** |
| Demo veri üreteci (1246 kayıt) | **Çalışıyor** |
| e-Fatura / e-Arşiv / Kimlik Bildirim Sistemi | **YAPILMADI** — yalnızca arayüz katmanı hazır, bkz. [ROADMAP](docs/ROADMAP.md) |
| Stok ve Finans ekranları | **Kısmi** — iş mantığı ve raporlar hazır, ayrı ekranları henüz yok |
| NVIDIA API gerçek çağrı testi | **Yapılmadı** — API anahtarı gerektirir, bkz. [NVIDIA_API_SETUP](docs/NVIDIA_API_SETUP.md) |

Tamamlanmamış ekranlar uygulamada **açıkça işaretlidir**: ne durumda oldukları,
neyin planlandığı ve aynı işi şu anda nasıl yapabileceğiniz yazılıdır.

---

## Ekran görüntüleri

> **Ekran görüntülerindeki verinin tamamı sentetiktir.** `hotel seed-demo`
> ile üretilen 1246 kayıtlık demo kümesi kullanılır: kimlik numaraları
> **kasten geçersiz**, e-postalar teslim edilemez bir `.local` alan adında,
> telefonlar rakam içermeyen ve **çevrilemez** bir maske
> (`+90 5XX XXX XX XX (D041)`). Gerçek hiçbir kişiye ait veri yoktur; bu,
> `tests/infrastructure/test_seed.py` içindeki testlerle korunur.
>
> Görüntüler `sunum/ekranlar/` altındadır ve `sunum/ekran_yakala.py`
> tarafından üretilir — elle düzenlenmez.

Yönetim paneli — koyu ve açık tema desteklidir; doluluk, ADR, RevPAR gibi
otelcilik göstergeleri, kritik uyarılar ve 14 günlük doluluk tahmini tek
ekranda toplanır.

---

## Hızlı başlangıç

### Gereksinimler

- Windows 10/11
- [Python 3.11 veya 3.12](https://www.python.org/downloads/) *(kurulumda
  "Add Python to PATH" işaretleyin)*
- [Git](https://git-scm.com/download/win)
- *(İsteğe bağlı)* [LM Studio](https://lmstudio.ai) — yerel yapay zekâ için

### Kurulum

```powershell
git clone https://github.com/Azizsekerdil/akilli-konaklama-yonetim-sistemi.git
cd akilli-konaklama-yonetim-sistemi
.\scripts\setup.ps1 -DemoData
```

Kurulum betiği sırasıyla: Python sürümünü doğrular, sanal ortam kurar,
bağımlılıkları yükler, `.env` dosyasını **rastgele bir oturum anahtarıyla**
oluşturur, veritabanı göçlerini uygular, izin/rol/yönetici hesabını kurar ve
(istenirse) demo veri ekler.

> İlk girişte yalnızca ana bilgisayardan `admin` / `admin` kullanın ve istenince
> parolayı hemen değiştirin.

### Çalıştırma

```powershell
.\scripts\run.ps1
```

### Demo hesapları

`-DemoData` ile kurulum yaptıysanız beş rol hesabı hazırdır
(`demo.mudur`, `demo.onburo`, `demo.kat`, `demo.teknik`, `demo.muhasebe`).
Parolalar kurulum çıktısında listelenir.

> **Uyarı:** Demo hesapları ve demo veri gerçek bir kurulumda silinmelidir
> (`hotel seed-demo --temizle`). Demo parolaları kaynak kodda açıkça yazılıdır
> ve **herkese açıktır**.

### Yönetici hesabı — tek kullanımlık `admin` / `admin`

Boş kurulumda `admin` hesabı `admin` geçici parolasıyla oluşturulur. Parola
Argon2id ile karmalanır, ilk giriş yalnız yerel masaüstü oturumundan yapılabilir
ve ana pencere açılmadan önce yeni, güçlü bir parola seçmek zorunludur. Değişimden
sonra geçici parola yeniden kullanılamaz. Bu sözleşme
`tests/security/test_bootstrap_credentials.py` ile test edilir.

---

## Özellikler

### Otel yönetimi
- **Rezervasyon**: takvim, grup rezervasyonu, bekleme listesi, no-show,
  erken giriş/geç çıkış, kanal bazlı kayıt
- **Çakışma engelleme**: aynı oda aynı gece iki kez satılamaz; yarı-açık
  aralık semantiği sayesinde çıkış günü oda yeniden satılabilir
- **Fiyatlandırma**: gece gece hesap, sezonluk fiyatlar, hafta sonu farkı,
  erken rezervasyon/iade edilemez planlar, ekstra kişi, indirim, vergi
- **Check-in / check-out**: oda kartı, refakatçi, folyo, ek ücretler,
  hasar/depozito kaydı
- **Folyo**: ücret satırları silinmez, gerekçeli olarak geçersiz kılınır
  (mali denetim izi korunur)
- **Misafir CRM**: profil, konaklama geçmişi, tercihler, VIP, kara liste,
  KVKK izin kayıtları
- **Kat hizmetleri**: günlük görev üretimi, atama, temizlik kontrolü
- **Teknik servis**: arıza kaydı, öncelik, odayı satışa kapatma, periyodik bakım
- **Raporlama**: doluluk, ADR, RevPAR, ALOS, iptal/no-show oranı, kanal ve
  oda tipi bazlı gelir; PDF/Excel/CSV çıktı

### Yapay zekâ
- **Çok sağlayıcılı**: LM Studio (yerel), OpenAI uyumlu, NVIDIA, Anthropic
- Birincil sağlayıcı ulaşılamazsa **yedeğe geçiş** — ancak yalnızca geçici
  hatalarda (geçersiz anahtar gibi kalıcı hatalarda geçilmez)
- Düşünme (reasoning) modelleri desteklenir
- Token ve tahmini maliyet takibi
- Tüm yapay zekâ çıktıları **"AI tarafından oluşturuldu"** rozetiyle işaretlenir
- Yapay zekâ **hiçbir veriyi kendiliğinden değiştirmez**; yalnızca öneri üretir

### AI Geliştirme Merkezi
Yapay zekâya kodlama görevleri verilebilen, **kısıtlanmış** bir geliştirme
ortamı: komut güvenlik politikası, sandbox kökü, diff önizleme, Git kontrol
noktası, ayrı görev dalı ve `format → lint → tip → test → güvenlik` zinciri.
Testler geçmeden değişiklik işlenmez, ana dala birleştirme ayrı onay ister.

---

## Test ve kalite

```powershell
.\scripts\test.ps1              # format + lint + tip + test + güvenlik
.\scripts\test.ps1 -Coverage    # kapsam raporu
.\scripts\test.ps1 -Live        # gerçek LM Studio bağlantı testi dahil
```

Sanal ortamı kendiniz kurduysanız betik olmadan da çalıştırabilirsiniz:

```powershell
python -m pip install -r requirements-dev.txt
$env:QT_QPA_PLATFORM = 'offscreen'   # arayüz testleri ekransız çalışır
python -m pytest -q -m "not live"
python -m pytest -q --cov=app --cov-branch      # kapsam
python -m ruff check app tests                  # lint
python -m black --check app tests               # biçim
python -m bandit -q -c pyproject.toml -r app    # statik güvenlik
```

**19 Ağustos 2026 ölçümü** — 1075 test toplanır, 1074'ü geçer, 1'i atlanır
(`live` işaretli: gerçek bir LM Studio sunucusu ister). Dal dahil kapsam
**%77,6**. `ruff` ve `black` temiz; `bandit` 0 yüksek / 0 orta / 9 düşük.
Testlerin hiçbiri ağa çıkmaz ve bu ayrı bir testle korunur.

Her `push`'ta aynı kapılar CI'da çalışır:
[.github/workflows/ci.yml](.github/workflows/ci.yml) — biçim, lint, tip,
göç tutarlılığı, test, `bandit`, `pip-audit`, `detect-secrets` ve "depoya
hassas dosya girdi mi" denetimi.

Ayrıntılı sonuçlar: [docs/TEST_REPORT.md](docs/TEST_REPORT.md)

---

## Paketleme

```powershell
.\scripts\build.ps1
```

`dist\` klasörüne Windows çalıştırılabilir dosyası üretir. Veritabanı ve
loglar `.exe` ile aynı klasörde tutulur; uygulama taşınabilir kalır.

> **Paketleme, lisans dosyaları eksikse başlamaz.** `LICENSE`,
> `THIRD_PARTY_NOTICES.md`, `packaging/licenses/GPL-3.0.txt` ve
> `packaging/licenses/LGPL-3.0.txt` pakete girmek zorundadır (Qt/PySide6
> LGPL-3.0 ile dinamik olarak bağlanır). **`LGPL-3.0.txt` bu depoda yoktur**
> ve birebir metniyle eklenmelidir; nedeni ve nasılı
> [packaging/licenses/README.md](packaging/licenses/README.md) içinde.
> Kaynak koddan çalıştırmak için gerekli değildir.

---

## Yedekleme

```powershell
.\scripts\backup.ps1                                    # yedek al
.\scripts\backup.ps1 -Restore backups\hotel_...db       # geri yükle
```

SQLite yedeği `VACUUM INTO` ile alınır — WAL kipinde dosya kopyalamak
tutarsız yedek üretir. Geri yükleme öncesi mevcut veritabanının bir kopyası
saklanır.

---

## Belgeler

| Belge | İçerik |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Katmanlı mimari ve tasarım kararları |
| [INSTALLATION_WINDOWS](docs/INSTALLATION_WINDOWS.md) | Ayrıntılı kurulum |
| [USER_GUIDE_TR](docs/USER_GUIDE_TR.md) | Kullanıcı kılavuzu |
| [DATABASE_SCHEMA](docs/DATABASE_SCHEMA.md) | Veritabanı şeması |
| [AI_CONFIGURATION](docs/AI_CONFIGURATION.md) | Yapay zekâ yapılandırması |
| [LM_STUDIO_SETUP](docs/LM_STUDIO_SETUP.md) | LM Studio kurulumu |
| [NVIDIA_API_SETUP](docs/NVIDIA_API_SETUP.md) | NVIDIA API kurulumu |
| [SECURITY_REVIEW](docs/SECURITY_REVIEW.md) | Güvenlik incelemesi |
| [TEST_REPORT](docs/TEST_REPORT.md) | Test raporu |
| [GITHUB_RESEARCH](docs/GITHUB_RESEARCH.md) | Açık kaynak araştırması ve lisans analizi |
| [ROADMAP](docs/ROADMAP.md) | Yol haritası ve bilinen eksikler |
| [known-limitations](docs/known-limitations.md) | **Neyin çalışmadığı** — üretime geçmeden önce okuyun |
| [presentation](docs/presentation/) | Tanıtım sunumu (TR/EN, ekran ve baskı sürümü, PDF + PPTX) |
| [SECURITY](SECURITY.md) | Güvenlik politikası ve **açık bildirimi** |
| [PRIVACY](PRIVACY.md) | Kişisel veri: ne saklanır, nasıl korunur, nereye gitmez |
| [AI_TRANSPARENCY](AI_TRANSPARENCY.md) | Yapay zekâ: sağlayıcılar, veri akışı, **neye karar veremez** |
| [CONTRIBUTING](CONTRIBUTING.md) | Katkı rehberi |
| [CODE_OF_CONDUCT](CODE_OF_CONDUCT.md) | Davranış kuralları |
| [CHANGELOG](CHANGELOG.md) | Sürüm geçmişi |
| [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) | Üçüncü parti lisanslar ve dağıtım yükümlülükleri |

---

## Güvenlik

- Parolalar **Argon2id** ile hash'lenir
- Kimlik/pasaport numaraları veritabanında **şifreli** saklanır; arama
  deterministik "kör indeks" ile yapılır
- API anahtarları **Windows Credential Manager**'da tutulur, veritabanına
  veya kaynak koda yazılmaz
- Loglarda API anahtarı, e-posta, telefon, TCKN ve kart numarası maskelenir
- Rol bazlı yetkilendirme + oturum zaman aşımı + kaba kuvvet kilidi
- Tüm kritik işlemler denetim günlüğüne yazılır

- Alan şifreleme anahtarı kalıcı olarak saklanamıyorsa uygulama **durur**;
  çözülemeyen bir kayıt sessizce boşaltılmaz (veri kaybını önler)
- Kör indeks için kaynak koda gömülü **sabit yedek anahtar yoktur**:
  anahtar yoksa indeks hesaplanmaz
- AI Geliştirme Merkezi'nde `.env`, anahtar dosyaları ve misafir
  veritabanı **hangi okuyucu kullanılırsa kullanılsın** kapalıdır

**Bir açık bulduysanız genel bir issue açmayın** — bildirim yolu
[SECURITY.md](SECURITY.md) içindedir.

### Ortam değişkenleri ve gizli bilgiler

`.env.example` dosyasını `.env` olarak kopyalayın ve kendi değerlerinizle
doldurun. `.env` **hiçbir zaman** depoya girmez (`.gitignore`).

- Dosyada **gerçek hiçbir anahtar yoktur**; sağlayıcı anahtarı alanları
  boştur. Anahtarı kurulumdan sonra **siz** girersiniz: *Ayarlar → Yapay
  Zekâ* (tercihen Windows Credential Manager'a) veya ortam değişkeniyle.
- Anahtar yoksa sağlayıcı **NOT_CONFIGURED** görünür ve hiçbir çağrı
  yapmaz; yerel yapay zekâ ve yapay zekâ dışı işlevler çalışmaya devam eder.
- Arayüzde yalnızca sağlayıcı adı, durum ve anahtarın **son 4 karakteri**
  gösterilir. "Bağlantıyı test et" yalnızca sizin açık eyleminizle çalışır.
- `HOTEL_SECRET_KEY` üretimde **mutlaka** değiştirilmelidir:
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`

Ayrıntılar: [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) ·
[PRIVACY.md](PRIVACY.md) · [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md)

---

## Yasal uyarı

Bu yazılım konaklama işletmelerinin veri işlemesini kolaylaştırır; ancak
**KVKK, e-Fatura, Kimlik Bildirim Sistemi ve diğer yasal yükümlülüklere uyum
sorumluluğu tamamen kullanıcı işletmeye aittir.** Türkiye'ye özel
entegrasyonlar (e-Fatura, e-Arşiv, KBS) **tamamlanmamıştır**; yalnızca veri
modeli ve arayüz katmanı hazırdır. Bu modüller tamamlanmadan üretimde
kullanılmamalıdır.

**Yapay zekâ çıktısı hakkında:** program bir dil modeli kullanabilir.
Üretilen metinler, fiyat önerileri ve doluluk tahminleri **doğrulanmamış**
model çıktısıdır; **finansal, hukuki veya tıbbi tavsiye değildir**. Yapay
zekâ kendi başına fiyat değiştiremez, rezervasyon oluşturamaz veya iptal
edemez, tahsilat yapamaz; her veri değiştiren işlem kullanıcı onayı ister.
Ayrıntı: [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md).

---

## Lisans

MIT — bkz. [LICENSE](LICENSE)

Üçüncü parti bağımlılıklar ve lisansları:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

Bu proje hiçbir üçüncü parti **kaynak kodu** içermez; bağımlılıklar PyPI
üzerinden standart şekilde kurulur ve kendi lisansları altındadır.
