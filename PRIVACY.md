# Gizlilik ve Kişisel Veri

Bu belge, programın kişisel veriyle **ne yaptığını ve ne yapmadığını**
anlatır. İddia değil, koddaki davranış anlatılır; her madde bir dosyaya veya
bir teste bağlıdır.

> **Bu belge hukuki danışmanlık değildir.** KVKK/GDPR kapsamında **veri
> sorumlusu işletmedir**, bu yazılımın geliştiricisi değildir. Aydınlatma
> metni, açık rıza, VERBİS kaydı, saklama süreleri ve ilgili kişi başvuruları
> işletmenin sorumluluğundadır.

---

## 1. Veri nerede durur?

**Tamamı sizin bilgisayarınızda.** Program bir masaüstü uygulamasıdır:

- Varsayılan veritabanı, uygulamanın yanındaki `data/hotel.db` dosyasıdır
  (SQLite). İsteğe bağlı olarak kendi PostgreSQL sunucunuza bağlanabilirsiniz.
- Geliştiricinin eriştiği bir sunucu, bir bulut hesabı, bir telemetri ucu
  veya bir "kullanım istatistiği" göndericisi **yoktur**.
- Program, siz bir bulut yapay zekâ sağlayıcısı **yapılandırmadıkça** hiçbir
  ağ isteği yapmaz. Test paketi bunu ayrı bir testle korur: testlerin hiçbiri
  ağa çıkmaz.

## 2. Hangi özel nitelikli veriler tutulur ve nasıl korunur?

| Alan | Saklama | Görüntüleme |
|---|---|---|
| Kimlik numarası (TCKN) | **Şifreli** (Fernet / AES-128-CBC + HMAC) | Varsayılan **maskeli** (`123*****901`). Açık görmek **ayrı bir yetkidir** ve her görüntüleme denetim günlüğüne yazılır |
| Pasaport numarası | **Şifreli** | Maskeli |
| Ad, e-posta, telefon, adres | Düz metin | Rol bazlı erişim |
| Kredi kartı numarası | **Hiç saklanmaz** — yalnızca son 4 hane | — |
| Parola | **Argon2id** özet | Hiçbir yerde okunamaz |
| Oturum jetonu | Özetlenerek | — |

Şifreli alanda arama yapabilmek için HMAC-SHA256 tabanlı bir **kör indeks**
tutulur. Anahtar bulunamazsa indeks **hesaplanmaz** ve işlem hata verir:
kaynak koda gömülü sabit bir yedek anahtar yoktur. (Yayımlanan bir sabit
herkesçe bilinir hâle gelir ve indeksi çevrimdışı taramaya açardı.)

**Anahtar sizindir.** Alan şifreleme anahtarı Windows Credential Manager'da
tutulur; program onu hiçbir yere göndermez. Anahtar kaybedilirse şifreli
alanlar **geri getirilemez** — yedekleme yordamı anahtarı yedeklemez, onu
ayrıca güvenli bir yerde saklamanız gerekir.

## 3. Loglar

Log kayıtları maskelenerek yazılır: API anahtarı, e-posta, telefon, kimlik
numarası, kart numarası ve **adı sır-benzeri olan her atama** (örneğin
`HOTEL_SECRET_KEY=...`) düz metin olarak loga girmez. Maskeleme ayrı testlerle
korunur (`tests/infrastructure/test_encryption_failclosed.py`).

Loglar `logs/` klasöründedir, varsayılan saklama süresi 30 gündür ve
depoya **hiçbir zaman** girmez.

## 4. Yapay zekâ ve veri

Ayrıntı için [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md). Özet:

- **Varsayılan sağlayıcı yereldir** (LM Studio). Yerel modda hiçbir veri
  bilgisayarınızdan çıkmaz.
- Bir bulut sağlayıcısı yapılandırırsanız, ona **gönderdiğiniz istem** o
  sağlayıcının sunucusuna gider. Sağlayıcının saklama ve eğitim politikası
  **onun** politikasıdır; bu program o politikayı değiştiremez.
- Yapay zekâya giden metinde kişisel veri kalıplarını temizleyen bir
  redaksiyon katmanı vardır (`app/application/services/ai_service.py` →
  `redact_personal_data`). Bu katman bir garanti değil, bir **azaltmadır**:
  serbest metne elle yazdığınız bir bilgiyi yakalamayabilir.
- Bulut sağlayıcı kullanacaksanız, KVKK açısından bu bir **yurt dışına veri
  aktarımı** olabilir. Bu değerlendirmeyi işletme yapmalıdır.

## 5. Demo veri

`hotel seed-demo` ile üretilen verinin **tamamı uydurmadır**:

- Kimlik numaraları **kasten geçersiz** üretilir (T.C. Kimlik No doğrulama
  algoritmasının her iki sağlama hanesi bilerek kaydırılır).
- E-postalar yalnızca `@ornek-test.local` alan adındadır; `.local` RFC 6762
  gereği yerel ağa ayrılmıştır ve internetten teslim edilemez.
- Telefonlar **çevrilemez** bir maske olarak üretilir
  (`+90 5XX XXX XX XX (D041)`) — rakam içermez.
- Adlar uydurma havuzlardan eşleştirilir; kara listedeki tek kayda açıkça
  kurgusal bir ad verilir (`ORNEK KAYIT-01 (DEMO)`).

Bunların hepsi testle korunur (`tests/infrastructure/test_seed.py`).

**Gerçek bir kurulumda demo veriyi silin** (`hotel seed-demo --temizle`) ve
demo hesaplarını kapatın: demo parolaları herkese açıktır.

## 6. Ekran görüntüleri ve tanıtım belgeleri

`sunum/ekranlar/` altındaki görüntüler ve `docs/presentation/` altındaki
PDF'ler **yalnızca sentetik demo veriyle** üretilmiştir. Üretim zinciri
kaynaktan başlar: tohum verisi → yakalama betiği → PNG → PPTX → PDF. Bir
görüntüdeki veriyi düzeltmek için PDF'e dokunulmaz, tohum verisi düzeltilir
ve zincir yeniden çalıştırılır.

## 7. Silme ve dışa aktarma

- Misafir kayıtları arayüzden silinebilir; silme denetim günlüğüne yazılır.
- KVKK izinleri **verme ve geri alma** tarihleriyle birlikte tutulur.
- Rapor ekranlarından CSV / Excel / PDF dışa aktarma yapılabilir; ilgili
  kişi başvurularında bu çıktılar kullanılabilir.
- **Otomatik saklama süresi uygulaması yoktur.** Süresi dolan kaydı silmek
  işletmenin sorumluluğundadır. Bkz. [docs/known-limitations.md](docs/known-limitations.md).

## 8. Soru ve bildirim

Gizlilikle ilgili bir sorun gördüyseniz [SECURITY.md](SECURITY.md) içindeki
bildirim yolunu kullanın. Genel bir GitHub issue açmayın.
