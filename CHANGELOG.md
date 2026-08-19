# Değişiklik Günlüğü

Bu dosyanın biçimi [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/)
önerilerine dayanır ve proje [Semantic Versioning](https://semver.org/lang/tr/)
kullanır.

---

## [Yayımlanmadı]

### Güvenlik
- **AI Geliştirme Merkezi komut politikası artık okuyucudan bağımsız.** Karar
  komutun adına değil, **dokunduğu dosyaya** bakıyor: `.env` ve türevleri,
  anahtar/sertifika dosyaları, kimlik bilgisi depoları, `.secrets.baseline` ve
  misafir veritabanı/yedekleri hangi okuyucu kullanılırsa kullanılsın kapalı.
  Önceki sürümde yalnızca üç okuyucu (`type`, `get-content`, `cat`) `.env` için
  engelleniyordu; `head`, `tail`, `findstr` ve `select-string` **onaysız**
  çalışıyordu. `.env.example` bir şablondur ve açık bırakıldı.
- **Log maskeleyicisi öneksiz sırları da yakalıyor.** Adı sır-benzeri olan her
  atamanın değeri (`HOTEL_SECRET_KEY=...`, `db_password: ...`) biçiminden
  bağımsız maskeleniyor. Önceden yalnızca `sk-`/`nvapi-` gibi önekli anahtarlar
  ve sabit bir ad listesi tanınıyordu.
- **Kör indeksin gömülü yedek anahtarı kaldırıldı.** Anahtar materyali yoksa
  `blind_index` artık `ConfigurationError` fırlatır (fail-closed). Yalnızca
  `HOTEL_APP_ENV=testing` altında sabit bir test anahtarı kullanılır.
- **Şifreleme anahtarı kalıcı değilse uygulama duruyor.** Anahtar keyring'e ya
  da ortama yazılamıyorsa sessizce yeni anahtar üretilmez. Çözülemeyen bir
  kayıt için `decrypt_value` boş dizge döndürmez, `DecryptionError` fırlatır ve
  "bu kaydın üzerine yazmayın" der — sessiz veri kaybı yolu kapatıldı.
- **Kurulum parolası güç denetiminden geçiyor.** `hotel bootstrap
  --admin-password ...` ile verilen zayıf/sözlük parolaları reddedilir.
- Yeni gerileme testleri: `tests/devcenter/test_policy.py`
  (`TestHassasDosyaOkumaGerilemesi`), `tests/infrastructure/test_encryption_failclosed.py`,
  `tests/security/test_bootstrap_credentials.py`, `tests/ui/test_formatting_path.py`.

### Gizlilik
- **Demo telefon numaraları maskelendi.** Tohum verisi artık çevrilebilir bir
  numara üretmiyor: `+90 5XX XXX XX XX (D041)` — gövdesinde rakam yok. Önceki
  biçim (`+90 555 000 XX XX`) 12 haneliydi ve ekran görüntüleri yoluyla tanıtım
  sunumuna giriyordu.
- **Kara listedeki demo kaydına açıkça kurgusal bir ad verildi**
  (`ORNEK KAYIT-01 (DEMO)`). Rastgele üretilmiş bir ad-soyadın "KARA LİSTE"
  etiketiyle yan yana yayımlanması gereksiz bir itibar riskiydi.
- **Dosya yolları kullanıcı adını sızdırmıyor.** Yeni `format_path`, ev
  dizinini `~` ile gösterir; AI Geliştirme Merkezi ekranı bunu kullanır.

### Değişti
- **Tanıtım sunumundaki sayılar artık kaynak koddan ölçülüyor.** Yeni
  `sunum/olcum.py`, test adedini (`pytest --collect-only`), tablo/model, izin,
  rol, sağlayıcı ve ekran adedini, kapsam yüzdesini, `bandit` ve `ruff`
  bulgularını üretim anında hesaplar. Ölçülemeyen bir değerin yerine rakam
  değil "ölçülmedi" basılır.
- **Sunumdaki düzeltme işlem (commit) numaraları kaldırıldı.** Gösterilen dört
  numaradan üçü hiçbir satır silmiyordu — yani mevcut bir açığı kapatmış
  olamazlardı. Yerlerine, düzeltmeyi koruyan **test dosyaları** gösteriliyor.
- CI iş akışı `tests.yml` → **`ci.yml`** olarak yeniden düzenlendi: en az yetki
  (`permissions: contents: read`), `.secrets.baseline` bağımlılığı kaldırıldı
  (tarama artık sıfır bulgu bekler) ve "kapsam dışı belge girdi mi" kapısı
  eklendi.
- `setuptools>=83` (derleme aracı; `pip-audit` 65.x/69.x/78.x serilerinde açık
  kaydı gösteriyordu). Çalışma zamanı bağımlılığı değildir.

### Eklendi
- `PRIVACY.md`, `AI_TRANSPARENCY.md`, `CODE_OF_CONDUCT.md`,
  `docs/known-limitations.md`, `.github/dependabot.yml`, `.gitleaks.toml`
- `sbom.spdx.json` ve `sbom.cdx.json` (çözümlenmiş çalışma zamanı bağımlılıkları)
- `packaging/licenses/` — paketleme, zorunlu lisans dosyaları eksikse artık
  **başlamıyor**; `scripts/build.ps1` üretilen çıktıyı ayrıca doğruluyor
- `docs/presentation/` — yayımlanan sunum dosyaları (`*_PUBLIC.pdf` / `.pptx`)

### Planlanan
Bkz. [docs/ROADMAP.md](docs/ROADMAP.md)

---

## [0.1.0] — 2026-08-15

İlk sürüm. Çalışan bir PMS çekirdeği, yapay zekâ altyapısı ve kısıtlı
geliştirme ortamı.

### Eklenen — Çekirdek
- Katmanlı mimari: `ui → application → domain ← infrastructure`
- Yapılandırma katmanı (pydantic-settings, `.env` + ortam değişkeni)
- Yapılandırılmış loglama (structlog) ve **otomatik hassas veri maskeleme**
  (API anahtarı, e-posta, telefon, TCKN, kart numarası)
- Windows Credential Manager (keyring) tabanlı sır yönetimi
- Türkçe kullanıcı mesajı / teknik ayrıntı ayrımı yapan hata hiyerarşisi

### Eklenen — Veritabanı
- 60 tablo, 56 ORM modeli, Alembic göç altyapısı
- SQLite (varsayılan) ve PostgreSQL (opsiyonel) desteği
- Kimlik/pasaport numaraları için **alan seviyesi şifreleme** (Fernet) ve
  HMAC-SHA256 tabanlı kör indeks ile arama
- SQLite yabancı anahtar kısıtları ve WAL kipi
- `TZDateTime`: zaman dilimi bilinçli UTC sütun tipi

### Eklenen — İş kuralları
- Rezervasyon çakışma engelleme (yarı-açık `[giriş, çıkış)` aralık semantiği)
- Gece gece fiyatlandırma: sezonluk fiyat, hafta sonu farkı, ekstra kişi,
  indirim, vergi (dahil/hariç)
- İptal, no-show, erken giriş ve geç çıkış ücreti hesabı
- Rezervasyon durum makinesi
- Doluluk, ADR, RevPAR, ALOS ve iptal/no-show oranı hesapları

### Eklenen — Güvenlik
- Argon2id parola hash'leme ve parola politikası
- 78 izin, 7 varsayılan rol içeren RBAC
- Oturum yönetimi (jeton hash'lenerek saklanır), zaman aşımı, kaba kuvvet
  kilidi, kullanıcı sayımı engelleme
- Append-only denetim günlüğü

### Eklenen — Operasyon
- Check-in / check-out, folyo, ücret, tahsilat, iade, kasa hareketi
- Kat hizmetleri görev yönetimi, teknik servis arıza kayıtları
- Misafir CRM, KVKK izin kayıtları
- Stok ve satın alma veri modeli

### Eklenen — Raporlama
- Doluluk, kanal/oda tipi bazlı gelir, gün sonu kapanış, giriş-çıkış,
  kat hizmetleri, teknik servis ve stok raporları
- PDF (reportlab), Excel (openpyxl) ve CSV (UTF-8 BOM) dışa aktarma

### Eklenen — Arayüz
- PySide6 masaüstü arayüzü, açık/koyu tema, Türkçe/İngilizce altyapı
- Yönetim paneli: KPI kartları, kritik uyarılar, 14 günlük doluluk grafiği
- Yetkiye göre oluşan sol gezinme; tamamlanmamış ekranlar açıkça işaretli
- Sayfa kayıt defteri: yeni ekran eklemek için ana pencere değiştirilmez

### Eklenen — Yapay zekâ
- Çok sağlayıcılı adaptör mimarisi: LM Studio, OpenAI uyumlu, NVIDIA,
  Anthropic, Mock
- Düşünme (reasoning) modeli desteği; yetersiz `max_tokens` durumunda boş
  yanıt tespiti
- Geçici hatalarda yedek sağlayıcıya geçiş (kalıcı hatalarda geçilmez)
- Token ve tahmini maliyet takibi
- Tüm çıktılar "AI tarafından oluşturuldu" rozetiyle işaretlenir

### Eklenen — AI Geliştirme Merkezi
- Komut güvenlik politikası (izin listesi öncelikli), sandbox kökü
- Diff önizleme, onaysız yazma engeli, kayıp güncelleme koruması
- Git kontrol noktası, ayrı görev dalı, otomatik geri alma
- `format → lint → tip → test → güvenlik` zinciri; testler geçmeden
  değişiklik işlenmez

### Eklenen — Araçlar
- `setup.ps1`, `run.ps1`, `test.ps1`, `build.ps1`, `backup.ps1`
- CLI: `bootstrap`, `seed-demo`, `backup`, `restore`, `check-ai`, `doctor`
- SQLite için `VACUUM INTO` tabanlı tutarlı yedekleme
- Belirlenimci demo veri üreteci (1246 kayıt, tamamen uydurma)

### Bilinen sınırlar
- e-Fatura, e-Arşiv ve Kimlik Bildirim Sistemi entegrasyonları
  **tamamlanmamıştır** (yalnızca veri modeli hazırdır)
- Finans, Stok ve Personel için ayrı ekranlar henüz yoktur
- NVIDIA sağlayıcısı gerçek API çağrısıyla test edilmemiştir
- Numara üreteçleri eşzamanlı güvenli değildir

Ayrıntılar: [docs/ROADMAP.md](docs/ROADMAP.md)
