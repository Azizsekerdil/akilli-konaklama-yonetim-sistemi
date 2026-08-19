# Windows Kurulum Kılavuzu

Bu belge, Akıllı Konaklama Yönetim Sistemi'ni **Windows 10/11** üzerinde
sıfırdan kurmayı, ilk kez çalıştırmayı, güncellemeyi, yedeklemeyi ve
kaldırmayı anlatır.

Belgedeki her komut ve her hata iletisi, depodaki gerçek kaynak dosyalardan
alınmıştır (`scripts/*.ps1`, `app/main.py`, `app/cli.py`,
`app/core/exceptions.py`). Uydurma çıktı yoktur.

> Kurulumun tamamı **tek bir betikle** yapılır: `.\scripts\setup.ps1`.
> Aşağıdaki bölümler betiğin ne yaptığını ve bir şey ters gittiğinde ne
> yapmanız gerektiğini anlatır.

---

## 1. Sistem gereksinimleri

| Bileşen | Gereksinim | Nereden doğrulandı |
|---|---|---|
| İşletim sistemi | Windows 10 veya 11 | `pyproject.toml` → `Operating System :: Microsoft :: Windows` |
| Python | **3.11, 3.12 veya 3.13** | `pyproject.toml` → `requires-python = ">=3.11,<3.14"` |
| PowerShell | Windows PowerShell 5.1 veya PowerShell 7 | Betikler `.ps1` biçimindedir |
| Git | Depoyu klonlamak için (zorunlu değil, ZIP de indirilebilir) | `README.md` |
| Disk | Sanal ortam + bağımlılıklar için ~1,5 GB boş alan | PySide6 tek başına birkaç yüz MB'dır |
| Yapay zekâ (isteğe bağlı) | LM Studio | [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) |

**Python sürümü seçimi.** `setup.ps1` sırasıyla `py -3.12`, `py -3.11` ve
`py -3.13` dener; hiçbiri yoksa PATH'teki `python` komutuna bakar ve sürümü
3.11–3.13 aralığında değilse kurulumu durdurur:

```
    [HATA] Python 3.10 destekleniyor degil. 3.11, 3.12 veya 3.13 gerekir.
    Indirme: https://www.python.org/downloads/
```

> Python'u kurarken **"Add Python to PATH"** kutusunu işaretleyin. İşaretlemezseniz
> betik Python'u bulamaz ve şu iletiyi verir:
>
> ```
>     [HATA] Python bulunamadi.
>     Python 3.11 veya 3.12 kurun: https://www.python.org/downloads/
>     Kurulumda "Add Python to PATH" secenegini isaretleyin.
> ```

---

## 2. Kurulum öncesi: PowerShell betik izni

Windows, varsayılan olarak imzasız `.ps1` betiklerinin çalışmasını
engelleyebilir. Bu **Windows PowerShell'in** ürettiği bir kısıttır, uygulamadan
gelmez; iletide "running scripts is disabled on this system" ifadesi geçer.

Mevcut politikayı görmek için:

```powershell
Get-ExecutionPolicy -List
```

Yalnızca **oturum açan kullanıcı için** ve **yerel betiklere** izin vermek
yeterlidir:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

> `Unrestricted` veya makine genelinde (`LocalMachine`) değişiklik yapmanız
> gerekmez; gereğinden geniş bir izin güvenlik açığıdır.

---

## 3. Adım adım kurulum

### 3.1. Depoyu alın

```powershell
git clone https://github.com/Azizsekerdil/akilli-konaklama-yonetim-sistemi.git
cd akilli-konaklama-yonetim-sistemi
```

### 3.2. Kurulum betiğini çalıştırın

```powershell
.\scripts\setup.ps1 -DemoData
```

Betik **idempotenttir**: birden fazla kez çalıştırmak güvenlidir. Var olan
sanal ortama, var olan `.env` dosyasına ve var olan yönetici hesabına
dokunmaz.

### 3.3. Her adımda ne olur?

Betik yedi adımı sırayla yürütür ve her adımı `==>` başlığıyla ekrana yazar.

#### Adım 1 — `==> Python surumu kontrol ediliyor`

Uygun Python sürümü aranır. Bulunduğunda (biçim betikten, sürüm numarası bu
makinedeki gerçek kurulumdan):

```
    [OK] Python 3.11 bulundu (Python 3.11.9)
```

Bulunamazsa kurulum **durur** (bkz. bölüm 1).

#### Adım 2 — `==> Sanal ortam hazirlaniyor`

Proje kökünde `.venv` klasörü oluşturulur. Zaten varsa dokunulmaz:

```
    [OK] Sanal ortam zaten mevcut
```

`-Force` verilmişse önce silinip yeniden kurulur:

```
    [!] Mevcut sanal ortam siliniyor (-Force)
```

**Neden ayrı bir sanal ortam?** Uygulamanın bağımlılıkları (PySide6,
SQLAlchemy, cryptography…) sistem genelindeki Python'a karışmaz; bilgisayardaki
diğer Python projeleri etkilenmez.

#### Adım 3 — `==> Bagimliliklar kuruluyor`

`requirements.txt` içindeki paketler kurulur, ardından proje düzenlenebilir
kipte (`pip install -e .`) eklenir. Ekranda uyarı görürsünüz:

```
    PySide6 buyuk bir pakettir; ilk kurulum birkac dakika surebilir.
```

Bu adım **internet gerektirir**. Başarısız olursa:

```
    [HATA] Bagimliliklar kurulamadi. Internet baglantinizi kontrol edin.
```

#### Adım 4 — `==> Ortam dosyasi (.env) hazirlaniyor`

`.env` yoksa `.env.example` kopyalanır ve `HOTEL_SECRET_KEY` satırı
**kriptografik olarak rastgele** bir değerle değiştirilir
(`secrets.token_urlsafe(64)`):

```
    [OK] .env olusturuldu ve rastgele HOTEL_SECRET_KEY yazildi
    [!] .env dosyasi git tarafindan izlenmez; yedegini guvenli tutun.
```

`.env` zaten varsa **hiç dokunulmaz**:

```
    [OK] .env zaten mevcut - DOKUNULMADI
```

> Bu davranış bilinçlidir: yeniden kurulum, elle yaptığınız yapılandırmayı ve
> oturum anahtarınızı ezmemelidir.

#### Adım 5 — `==> Veritabani goclerini uygulaniyor`

`alembic upgrade head` çalışır ve veritabanı şeması oluşturulur
(SQLite varsayılanında `data\hotel.db`).

```
    [OK] Veritabani guncel
```

Başarısız olursa betik durur ve tanı komutunu gösterir:

```
    [HATA] Veritabani gocleri uygulanamadi.
    Ayrinti icin: .\.venv\Scripts\alembic.exe upgrade head
```

#### Adım 6 — `==> Izinler, roller ve yonetici hesabi kuruluyor`

`python -m app.cli bootstrap` çalışır. İzin kataloğu ve varsayılan roller
veritabanına yazılır. **Doğrulanmış sayılar:** 72 izin, 7 varsayılan rol
(`admin`, `manager`, `frontdesk`, `housekeeping`, `maintenance`, `accounting`,
`viewer`).

```
========================================================
  Guvenlik kurulumu
========================================================
  Izin  : 72 eklendi, 0 guncellendi
  Rol   : 7 eklendi, 0 guncellendi

  ----------------------------------------------------
  YONETICI HESABI OLUSTURULDU
  ----------------------------------------------------
  Kullanici adi : admin
  Parola        : <20 karakterlik rastgele parola>

  BU PAROLA BIR DAHA GOSTERILMEYECEK.
  Hemen kaydedin ve ilk giriste degistirin.
  ----------------------------------------------------
```

> **En kritik adım budur.** Parola üretilir, ekrana bir kez yazılır ve
> **hiçbir yere kaydedilmez, loglanmaz** (`app/security/bootstrap.py`:
> `generated_password` yalnızca dönüş değerinde taşınır). Kaybederseniz o
> hesaba giriş yapmanın yolu yoktur; bölüm 7.4'teki kurtarma yordamına bakın.

Yönetici zaten varsa parola üretilmez:

```
  Yonetici: 'admin' zaten mevcut (degistirilmedi)
```

#### Adım 7 — `==> Demo veri olusturuluyor` *(yalnızca `-DemoData` ile)*

```
    [!] Demo veri tamamen hayalidir; gercek isletme verisi degildir.
```

Demo veri; tesis, odalar, misafirler, rezervasyonlar, folyolar, kat hizmetleri
görevleri, arıza kayıtları ve beş rol hesabı (`demo.mudur`, `demo.onburo`,
`demo.kat`, `demo.teknik`, `demo.muhasebe`) üretir. **Hesap adları ve
parolaları bu adımın çıktısında görünür** — çıktıyı kaydedin. Üretilen toplam
kayıt sayısı da aynı çıktıda (`total_records`) yazar; varsayılan `medium`
ölçeğinde README'de bildirilen değer 1246'dır.

Ölçek `medium` dışında `small` veya `large` seçilebilir; bu yalnızca doğrudan
CLI ile mümkündür:

```powershell
.\.venv\Scripts\python.exe -m app.cli seed-demo --scale small
.\.venv\Scripts\python.exe -m app.cli seed-demo --seed 1234   # farklı ama tekrarlanabilir veri
```

Aynı `--seed` değeri **aynı veriyi** üretir; demo ekranları ve testler
tekrarlanabilir olsun diye böyle tasarlanmıştır.

> Demo verideki kimlik numaraları kasten **geçersiz** üretilir, e-posta
> adresleri `@ornek-test.local` alanındadır ve telefonlar tahsis edilmemiş
> `+90 555 000 XX XX` bloğundadır. Hiçbiri gerçek bir kişiye ait değildir.
> Gerçek bir işletme kurulumunda demo veri **kullanılmamalıdır**.

#### Kapanış

```
========================================================
  KURULUM TAMAMLANDI
========================================================

  Uygulamayi baslatmak icin:
      .\scripts\run.ps1

  Testleri calistirmak icin:
      .\scripts\test.ps1
```

---

## 4. `setup.ps1` parametreleri

| Parametre | Ne yapar | Ne zaman kullanılır |
|---|---|---|
| *(parametresiz)* | Tam kurulum, demo veri **olmadan** | Gerçek işletme kurulumu |
| `-DemoData` | Kurulumun sonunda demo veri üretir | Tanıtım, deneme, eğitim |
| `-Force` | Var olan `.venv` klasörünü siler ve yeniden kurar | Sanal ortam bozulduğunda, Python sürümü değiştiğinde |
| `-SkipDeps` | Bağımlılık kurulumunu atlar; yalnızca `.env`, göç ve güvenlik kurulumu çalışır | Bağımlılıklar zaten kuruluyken göçü tekrar uygulamak için |

**Örnekler:**

```powershell
.\scripts\setup.ps1                    # temiz kurulum
.\scripts\setup.ps1 -DemoData          # kurulum + demo veri
.\scripts\setup.ps1 -Force             # sanal ortamı sıfırdan kur
.\scripts\setup.ps1 -SkipDeps          # yalnızca göç + güvenlik kurulumu
```

> `-DemoData` gerçek işletme verisi bulunan bir kurulumda **kullanılmamalıdır**
> (betiğin kendi uyarısı: *"Gercek isletme verisi olan bir kurulumda
> KULLANMAYIN"*).

---

## 5. İlk çalıştırma ve yönetici parolası

### 5.1. Uygulamayı başlatın

```powershell
.\scripts\run.ps1
```

Betik önce ortamı denetler:

- `.venv` yoksa:
  ```
  [HATA] Sanal ortam bulunamadi.
  Once kurulumu calistirin:
      .\scripts\setup.ps1
  ```
- `.env` yoksa uygulama yine de açılır, ama uyarır:
  ```
  [!] .env dosyasi yok; varsayilan ayarlarla baslatiliyor.
      Onerilen: .\scripts\setup.ps1
  ```

Ayrıntılı günlükle başlatmak için:

```powershell
.\scripts\run.ps1 -Debug      # HOTEL_LOG_LEVEL=DEBUG
```

### 5.2. Giriş yapın

Giriş penceresinde kullanıcı adı `admin`, parola ise kurulum çıktısındaki
20 karakterlik değerdir. Enter tuşu girişi tamamlar, Esc iptal eder.

> Hatalı girişte ekranda **her zaman aynı** ileti çıkar:
> *"Kullanici adi veya parola hatali."* Bu bilinçlidir; var olmayan bir
> kullanıcı ile yanlış parola ayırt edilemesin diye böyle yapılmıştır
> (kullanıcı adı listesi çıkarmayı engeller).

Art arda başarısız denemede hesap geçici olarak kilitlenir (varsayılan:
5 deneme, 15 dakika — `.env` içindeki `HOTEL_MAX_FAILED_LOGINS` ve
`HOTEL_LOCKOUT_MINUTES`):

> *"Cok fazla basarisiz giris denemesi nedeniyle hesabiniz gecici olarak
> kilitlendi."*

### 5.3. Zorunlu parola değişimi

Kurulumda üretilen yönetici parolası `must_change_password` işaretiyle
gelir. İlk girişte kapatılamayan bir pencere açılır:

> *"Guvenlik nedeniyle ilk giriste parolanizi degistirmeniz gerekiyor."*

Parola kuralları (`app/security/passwords.py`):

- En az **10** karakter (`HOTEL_PASSWORD_MIN_LENGTH`), en fazla 128
- En az bir harf **ve** en az bir rakam
- Yaygın parola listesinde bulunmamalı
- Kullanıcı adını içermemeli
- En az 4 farklı karakter içermeli

Parola değiştiğinde **tüm oturumlar kapatılır**; uygulama sizden yeniden giriş
yapmanızı ister. Bu, çalınmış bir oturumun parola değişiminden sonra
kullanılmaya devam etmesini engeller.

### 5.4. Masaüstü kısayolu (isteğe bağlı)

```powershell
.\scripts\create_shortcut.ps1 -Dev              # sanal ortamdan çalıştırır
.\scripts\create_shortcut.ps1 -Dev -StartMenu   # Başlat menüsüne de ekler
.\scripts\create_shortcut.ps1                   # dist\ altındaki .exe'ye kısayol
.\scripts\create_shortcut.ps1 -Remove           # kısayolları siler
```

`-Dev` kipi `pythonw.exe` kullanır; böylece uygulamanın arkasında siyah bir
konsol penceresi kalmaz. Paketlenmiş `.exe` yoksa betik açıkça söyler:

```
[HATA] dist\ klasorunde .exe bulunamadi.

Secenekler:
  1) Once paketleyin:   .\scripts\build.ps1
  2) Gelistirme kipi:   .\scripts\create_shortcut.ps1 -Dev
```

---

## 6. Kurulumu doğrulama

### 6.1. Ortam teşhisi

```powershell
.\.venv\Scripts\python.exe -m app.cli doctor
```

Sağlıklı bir kurulumda çıktı şuna benzer (bu çıktı gerçek bir çalıştırmadan
alınmıştır):

```
========================================================
  Ortam teshisi
========================================================
  Python           : 3.11.9
  Uygulama surumu  : 0.1.0
  Ortam            : development
  Veri koku        : C:\AkilliKonaklama
  Paketlenmis mi   : hayir

  .env dosyasi     : var
  HOTEL_SECRET_KEY : ozellestirilmis
  Anahtar deposu   : kullanilabilir
  Veritabani       : sqlite, 61 tablo
  Yapay zeka       : acik
      Birincil     : lmstudio
      LM Studio    : http://127.0.0.1:1234/v1
```

`doctor` bir sorun bulursa çıkış kodu `1` olur ve satırın altına ne yapılması
gerektiğini yazar (örneğin *"-> Gocler uygulanmamis: alembic upgrade head"*).

### 6.2. Testler

```powershell
.\scripts\test.ps1              # biçim + lint + tip + test + güvenlik
.\scripts\test.ps1 -Fast        # yalnızca testler
.\scripts\test.ps1 -Coverage    # kapsam raporu (htmlcov\index.html)
.\scripts\test.ps1 -Live        # gerçek LM Studio bağlantı testi dahil
.\scripts\test.ps1 -NoFix       # düzeltme uygulamaz, yalnızca denetler
```

Bu depoda `-m "not live"` süzgeciyle **985 test** toplanır (1 test `live`
işaretli olduğu için varsayılan olarak atlanır).

Betik bir adım başarısız olsa bile sonraki adımlara devam eder ve sonunda
özet gösterir; böylece tek çalıştırmada tüm sorunlar görülür.

---

## 7. Sorun giderme

Aşağıdaki iletilerin tamamı kaynak koddan alınmıştır. Sol sütundaki metni
ekranda gördüğünüz iletiyle eşleştirin.

### 7.1. Kurulum ve başlatma

| Gördüğünüz ileti | Nedeni | Çözüm |
|---|---|---|
| `[HATA] Python bulunamadi.` | Python kurulu değil ya da PATH'te yok | Python 3.11/3.12 kurun, "Add Python to PATH" işaretleyin |
| `[HATA] Python 3.10 destekleniyor degil. 3.11, 3.12 veya 3.13 gerekir.` | Desteklenmeyen sürüm | Desteklenen bir sürüm kurun; `py -3.12 --version` ile doğrulayın |
| `[HATA] Sanal ortam olusturulamadi.` | `venv` modülü çalışmadı, disk/izin sorunu | Klasör yazma iznini kontrol edin; `.\scripts\setup.ps1 -Force` ile yeniden deneyin |
| `[HATA] Bagimliliklar kurulamadi. Internet baglantinizi kontrol edin.` | pip paketleri indiremedi (ağ, proxy, güvenlik duvarı) | Bağlantıyı kontrol edin, kurumsal proxy varsa `pip` proxy ayarını verin, sonra `.\scripts\setup.ps1` |
| `[HATA] .env.example bulunamadi.` | Depo eksik klonlanmış | Depoyu yeniden klonlayın |
| `[HATA] Veritabani gocleri uygulanamadi.` | Şema oluşturulamadı | `.\.venv\Scripts\alembic.exe upgrade head` ile ayrıntılı hatayı görün |
| `[HATA] Guvenlik kurulumu basarisiz.` | `bootstrap` adımı hata verdi | `.\.venv\Scripts\python.exe -m app.cli bootstrap` ile tekrar deneyin; ayrıntı `logs\error.log` içindedir |
| `[HATA] Demo veri olusturulamadi.` + `Veritabaninda zaten demo verisi var.` | `-DemoData` ikinci kez çalıştırıldı | Demo veri **üzerine yazılmaz**; aşağıdaki "Demo veriyi temizleme" notuna bakın |
| `[HATA] Sanal ortam bulunamadi.` (run/test/backup/build) | Kurulum yapılmamış | `.\scripts\setup.ps1` |
| `[HATA] Uygulama 1 kodu ile sonlandi.` + `Loglar: logs\error.log` | Uygulama açılışta çöktü | `logs\error.log` dosyasının son satırlarını okuyun |

#### Demo veriyi temizleme

`setup.ps1 -DemoData` (ya da `app.cli seed-demo`) ikinci kez çalıştırıldığında
sessizce çift kayıt üretmek yerine **açıkça durur**:

```
  [HATA] Veritabaninda zaten demo verisi var. Yeniden olusturmadan once
  mevcut demo verisini temizleyin.
```

Temizleme için **hazır bir komut satırı komutu yoktur** (`app.cli` altında
böyle bir alt komut tanımlı değildir); işlev `clear_demo_data` yalnızca kod
içinden çağrılabilir. Geçici bir betikle çalıştırabilirsiniz:

```powershell
@'
from app.infrastructure.db.session import session_scope
from app.infrastructure.seed.demo_data import clear_demo_data

with session_scope() as session:
    summary = clear_demo_data(session, confirm=True)
    print(f"Silinen kayit: {summary.total_deleted}")
'@ | Set-Content -Encoding utf8 temizle_demo.py

.\.venv\Scripts\python.exe temizle_demo.py
Remove-Item temizle_demo.py
```

> **Bu işlem geri alınamaz.** Yalnızca demo işaretli kayıtları siler, ancak
> çalıştırmadan önce mutlaka yedek alın (`.\scripts\backup.ps1`). Gerçek
> işletme verisi bulunan bir veritabanında bu komutu **çalıştırmayın**.

### 7.2. Uygulama açılırken (pencere içinde çıkan iletiler)

> Bu iletiler `app/main.py` içindeki açılış denetimlerinden gelir. Aşağıdaki
> tablo, veritabanı hazır değilken **komut satırından** yapılacak işi verir;
> uygulamanın kendi açılış akışı sürüm sürüm değişebilir.

| Gördüğünüz ileti | Nedeni | Çözüm |
|---|---|---|
| `Veritabani henuz hazirlanmamis.` | Veritabanı hiç kurulmamış (`alembic_version` tablosu yok) | `.\scripts\setup.ps1` |
| `Veritabani semasi eksik gorunuyor.` | Göçler eksik uygulanmış | `.\.venv\Scripts\alembic.exe upgrade head` |
| `Veritabanina baglanilamadi.` + teknik ayrıntı | Yanlış `HOTEL_DB_URL`, kilitli dosya, kapalı PostgreSQL | Adresi kontrol edin; PostgreSQL kullanıyorsanız sunucunun çalıştığını doğrulayın |
| **Baslatma hatasi** → `Loglama kurulamadi.` | `logs\` klasörüne yazılamıyor | Klasör iznini kontrol edin veya `.env` içinde `HOTEL_LOG_DIR` değerini yazılabilir bir yola alın |
| `Sistemde tanimli bir tesis bulunamadi.` (ana pencere) | Veritabanı boş; hiç tesis yok | Pencerede yazan komut: `.\scripts\setup.ps1 -DemoData` ya da `.\.venv\Scripts\python.exe -m app.cli seed-demo` |
| **Beklenmeyen hata** → `Uygulamada beklenmeyen bir hata olustu.` | Yakalanmamış hata; uygulama çalışmaya devam eder | Ayrıntı `logs\error.log` dosyasındadır |

### 7.3. Kullanım sırasında (iş kuralı ve yetki iletileri)

Bu iletiler `app/core/exceptions.py` içindeki hata sınıflarının kullanıcıya
gösterilen metinleridir.

| İleti | Anlamı | Çözüm |
|---|---|---|
| `Kullanici adi veya parola hatali.` | Kimlik doğrulama başarısız (kullanıcının var olup olmadığı sızdırılmaz) | Bilgileri kontrol edin |
| `Cok fazla basarisiz giris denemesi nedeniyle hesabiniz gecici olarak kilitlendi.` | Kaba kuvvet koruması devrede | `HOTEL_LOCKOUT_MINUTES` kadar (varsayılan 15 dk) bekleyin |
| `Oturum sureniz doldu. Lutfen yeniden giris yapin.` | Oturum zaman aşımı (varsayılan 30 dk) | Yeniden giriş yapın; süreyi `HOTEL_SESSION_TIMEOUT_MINUTES` ile değiştirebilirsiniz |
| `Bu islem icin yetkiniz bulunmuyor.` | Rolünüzde gerekli izin yok | Yöneticiden ilgili izni isteyin |
| `Bu odada secilen tarihlerle cakisan baska bir rezervasyon bulunuyor.` | Çakışma engeli | Başka oda veya tarih seçin |
| `Oda bakim nedeniyle satisa kapali.` | Oda "Servis Dışı"/"Arızalı" | Teknik servis kaydını kapatın ya da başka oda seçin |
| `Bu kaydin mevcut durumunda bu islem yapilamaz.` | Geçersiz durum geçişi (ör. iptal edilmiş rezervasyona giriş) | Kaydın durumunu kontrol edin |
| `Yapay zeka saglayicisina baglanilamadi.` | LM Studio/uzak servis kapalı | [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) → sunucuyu başlatın |
| `Yapay zeka servisi API anahtarini kabul etmedi.` | Geçersiz/eksik anahtar | Ayarlar > Yapay Zeka ekranından anahtarı yeniden kaydedin |
| `Otomatik yedekleme yalnizca SQLite icin desteklenir.` | PostgreSQL kullanıyorsunuz | `pg_dump -Fc -f yedek.dump hotel` (iletinin kendi önerisi) |
| `Veritabani dosyasi bulunamadi.` (yedek alırken) | Göçler uygulanmamış | `alembic upgrade head` |
| `Yedek dosyasi gecerli bir veritabani degil.` | Bozuk/yarım yedek | Başka bir yedek deneyin |

### 7.4. Yönetici parolası kaybolduğunda

**Önce bilinmesi gereken:** Bu sürümde **kullanıcı ve rol yönetimi ekranı
yoktur**. İzin kataloğunda `user.manage` ve `role.manage` izinleri tanımlıdır,
ancak bunları kullanan bir arayüz henüz yazılmamıştır. Komut satırında da
parola sıfırlayan bir komut bulunmaz (`app.cli` komutları: `bootstrap`,
`seed-demo`, `backup`, `restore`, `list-backups`, `check-ai`, `doctor`).

Dolayısıyla **var olan bir hesabın parolası uygulama üzerinden
sıfırlanamaz.** Uygulanabilir tek yol, **yeni bir yönetici hesabı
oluşturmaktır**:

```powershell
.\.venv\Scripts\python.exe -m app.cli bootstrap --admin-username yeniyonetici --admin-password "<güçlü-parola>"
```

Bu komut:

- `yeniyonetici` adında **yeni** bir hesap oluşturur, `admin` rolünü atar
- Parolayı siz verdiğiniz için **ilk girişte değiştirme zorunluluğu koymaz**
- Aynı adda bir hesap zaten varsa **hiçbir şey değiştirmez** (çıktıda
  *"Yonetici: '...' zaten mevcut (degistirilmedi)"* yazar)

> Parolayı komut satırına yazmak, PowerShell geçmişinde iz bırakır. İşlem
> sonrası geçmişi temizlemeniz ve ilk fırsatta parolayı arayüzden
> (Adınız > Parola Degistir) değiştirmeniz önerilir.
>
> Bu adım, makineye dosya erişimi gerektirir; bu yüzden sunucuya/terminale
> fiziksel veya yönetici erişimi olmayan kimse hesap oluşturamaz.

Eski hesap veritabanında kalır ve kilitli değildir; yalnızca parolası
bilinmediği için kullanılamaz.

### 7.5. Bilinen sınırlar

| Konu | Durum |
|---|---|
| `.\scripts\run.ps1 -Api` | **Çalışmıyor.** `app.api` modülü depoda yoktur; komut `ModuleNotFoundError: No module named 'app.api'` ile sonlanır. FastAPI bağımlılığı kuruludur, servis katmanı henüz yazılmamıştır. |
| `seed-demo` çıktısının biçimi | Demo hesap adları ve parolaları çıktıda görünür, ancak biçimli rapor yerine **tek satırlık bir nesne özeti** olarak basılır. Bilgi kaybı yoktur, okunuşu zordur. |
| Türkiye entegrasyonları (e-Fatura, KBS) | Yapılmadı; varsayılan olarak kapalıdır. Bkz. [ROADMAP.md](ROADMAP.md) |

---

## 8. PostgreSQL'e geçiş

SQLite tek kullanıcılı ve tek makineli kurulumlar için yeterlidir. Birden çok
resepsiyon terminali aynı veriye yazacaksa PostgreSQL kullanın.

### 8.1. Sürücüyü kurun

```powershell
.\.venv\Scripts\python.exe -m pip install "psycopg[binary]>=3.2"
```

Aynısı proje ek bağımlılığı olarak da tanımlıdır (`pyproject.toml` →
`[project.optional-dependencies] postgres`):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[postgres]"
```

### 8.2. Veritabanını hazırlayın

PostgreSQL sunucusunda boş bir veritabanı ve kullanıcı oluşturun (bu adım
uygulamanın dışındadır, `psql` veya pgAdmin ile yapılır).

### 8.3. `.env` dosyasını güncelleyin

`.env` içindeki `HOTEL_DB_URL` satırını değiştirin. Örnek biçim
`.env.example` dosyasında yazılıdır:

```dotenv
# SQLite (varsayılan)
# HOTEL_DB_URL=sqlite:///data/hotel.db

# PostgreSQL
HOTEL_DB_URL=postgresql+psycopg://hotel_user:PAROLA@localhost:5432/hotel
```

### 8.4. Şemayı ve güvenlik verilerini oluşturun

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m app.cli bootstrap
.\.venv\Scripts\python.exe -m app.cli doctor
```

`alembic` adresi `alembic.ini` dosyasından değil, uygulama ayarlarından okur
(`alembic/env.py` → `get_settings().database.resolved_url()`); yani yalnızca
`HOTEL_DB_URL` değerini değiştirmeniz yeterlidir.

`doctor` çıktısında artık `Veritabani : postgresql, ... tablo` görmelisiniz.

### 8.5. Geçiş sonrası dikkat edilecekler

- **Mevcut SQLite verisi otomatik taşınmaz.** Bu belge veri taşıma yordamı
  içermez; `alembic upgrade head` yalnızca boş şemayı kurar.
- **`.\scripts\backup.ps1` PostgreSQL'de yedek almaz.** İlgili kod açıkça
  reddeder ve `pg_dump` önerir (bkz. bölüm 7.3).
- **Alan şifreleme anahtarı makineye bağlıdır** (bölüm 9.3). Veritabanını
  taşırken anahtarı da taşımanız gerekir.

---

## 9. Yedekleme ve geri yükleme

### 9.1. Yedek alma

```powershell
.\scripts\backup.ps1              # varsayılan saklama sayısıyla
.\scripts\backup.ps1 -Keep 30     # en yeni 30 yedeği sakla
```

Yedekler `backups\hotel_YYYYAAGG_SSDDSS.db` adıyla yazılır. Klasör ve saklama
sayısı `.env` içindeki `HOTEL_BACKUP_DIR` (varsayılan `backups`) ve
`HOTEL_BACKUP_RETENTION` (varsayılan 14) ile ayarlanır.

Örnek çıktı:

```
========================================================
  Veritabani yedegi
========================================================
  Dosya  : C:\AkilliKonaklama\backups\hotel_20260815_143000.db
  Boyut  : 3.42 MB
  Temizlik: 2 eski yedek silindi
```

**Neden dosya kopyalamak yerine `VACUUM INTO`?** Uygulama SQLite'ı WAL kipinde
kullanır; ana `.db` dosyasını kopyalamak, henüz ana dosyaya aktarılmamış
işlemleri kaçırabilir ve **tutarsız** bir yedek üretir. `VACUUM INTO` tutarlı
bir anlık görüntü yazar ve uygulama çalışmaya devam edebilir.

Mevcut yedekleri listelemek için:

```powershell
.\.venv\Scripts\python.exe -m app.cli list-backups
```

Aynı işlem arayüzden de yapılabilir: **Ayarlar > Yedekleme** sekmesi
(`Yedek Al` düğmesi, `backup.run` izni gerekir).

### 9.2. Geri yükleme

```powershell
.\scripts\backup.ps1 -Restore backups\hotel_20260815_143000.db
```

Betik önce uyarır ve **açık onay** ister:

```
  DIKKAT: GERI YUKLEME
  Mevcut veritabaninin UZERINE YAZILACAK.
  Kaynak: backups\hotel_20260815_143000.db

  Devam etmek icin "EVET" yazin:
```

`EVET` (büyük harflerle) yazmazsanız işlem iptal edilir. Onaydan sonra:

- Yedek dosyasının gerçekten okunabilir bir SQLite veritabanı olduğu
  doğrulanır; değilse *"Yedek dosyasi gecerli bir veritabani degil."*
- Mevcut veritabanının `.pre-restore` uzantılı bir kopyası saklanır — yanlış
  yedeği yüklerseniz dönüş yolunuz kalır
- Eski `-wal` ve `-shm` yan dosyaları silinir (yeni dosyayla tutarsız olurlardı)

```
  Geri yuklendi: C:\AkilliKonaklama\data\hotel.db
  Onceki veritabani '.pre-restore' uzantisiyla saklandi.
```

Onay istemeden çalıştırmak için `-Force` vardır, ancak **önerilmez**:

```powershell
.\scripts\backup.ps1 -Restore backups\hotel_20260815_143000.db -Force
```

> Geri yükleme **geri alınamaz**. Yedek alındıktan sonra girilen tüm
> rezervasyon, tahsilat ve misafir kayıtları kaybolur. İşlemden önce mutlaka
> yeni bir yedek alın. (Arayüzdeki Ayarlar > Yedekleme sekmesi de aynı uyarıyı
> gösterir.)

### 9.3. Yedeğin **kapsamadığı** şey: alan şifreleme anahtarı

Misafirlerin kimlik/pasaport numaraları veritabanında **şifreli** durur
(`app/infrastructure/db/types.py` → `EncryptedString`). Şifreleme anahtarı
veritabanında değil, **Windows Credential Manager** içinde tutulur:

- Servis adı: `AkilliKonaklamaYonetimSistemi`
- Anahtar adı: `field_encryption_key`

`backup.ps1` bu anahtarı **yedeklemez**. Anahtar kaybolursa şifreli alanlar
geri getirilemez; kod bu durumda çözme denemesini sessizce boş dizgeye
düşürür ve loga `alan_sifre_cozme_basarisiz` yazar.

**Bu yüzden düzenli bir yedek yordamı üç parçadan oluşmalıdır:**

1. `backups\hotel_*.db` dosyaları
2. `.env` dosyası (`HOTEL_SECRET_KEY` dahil)
3. Credential Manager'daki `field_encryption_key` değeri — ayrı ve güvenli bir
   yerde (ör. kurumsal parola kasası)

Anahtarı okumak için:

```powershell
.\.venv\Scripts\python.exe -c "from app.core.secret_store import get_secret; print(get_secret('field_encryption_key'))"
```

> Bu komut anahtarı **düz metin** olarak ekrana yazar. Yalnızca güvendiğiniz
> bir makinede, gerekli olduğunda çalıştırın ve konsol geçmişini temizleyin.

Yeni bir makineye taşırken aynı anahtarı yazmak için Ayarlar ekranı yoktur;
`.env` dosyasına `HOTEL_FIELD_ENCRYPTION_KEY=<değer>` satırı eklemek de
çalışır (`types.py` keyring bulunamazsa bu ortam değişkenine bakar).

---

## 10. Güncelleme

Sıra önemlidir: **önce yedek**, sonra kod, sonra şema.

```powershell
# 1) Yedek al (geri dönüş yolu)
.\scripts\backup.ps1

# 2) Yeni sürümü çek
git pull

# 3) Bağımlılıkları güncelle
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 4) Veritabanı şemasını güncelle
.\.venv\Scripts\alembic.exe upgrade head

# 5) Yeni izin/rolleri veritabanına yaz (idempotent)
.\.venv\Scripts\python.exe -m app.cli bootstrap

# 6) Doğrula
.\.venv\Scripts\python.exe -m app.cli doctor
.\scripts\test.ps1 -Fast
```

Adım 3–5 yerine tek komut da kullanılabilir; `setup.ps1` idempotenttir ve
`.env` dosyanıza dokunmaz:

```powershell
.\scripts\setup.ps1
```

**Adım 5 neden gerekli?** İzin kataloğu kodda tanımlıdır ve
`bootstrap` her çalıştığında veritabanıyla eşitlenir: yeni izinler eklenir,
adı değişenler güncellenir. Katalogda olmayan izinler **silinmez** — kendi
tanımladığınız özel izinler kaybolmaz.

> Güncelleme sonrası uygulama açılmıyorsa `logs\error.log` dosyasının son
> satırlarına bakın; göç hatası varsa yedeği geri yükleyip (bölüm 9.2) sorunu
> bildirin.

---

## 11. Paketleme (isteğe bağlı)

```powershell
.\scripts\build.ps1              # dist\ altına klasör (onedir) üretir
.\scripts\build.ps1 -OneFile     # tek dosyalık .exe
.\scripts\build.ps1 -Clean       # önceki çıktıları siler
.\scripts\build.ps1 -SkipTests   # testleri atlar — ÖNERİLMEZ
```

Betik paketlemeden önce testleri çalıştırır; başarısız olurlarsa durur:

```
[HATA] Testler basarisiz. Paketleme durduruldu.
Yine de paketlemek icin: .\scripts\build.ps1 -SkipTests
```

Varsayılan **onedir** kipidir. Nedeni betikte yazılıdır: onefile kipi her
çalıştırmada geçici klasöre açılır; bu hem başlangıcı yavaşlatır hem de bazı
kurumsal antivirüslerin uygulamayı karantinaya almasına yol açar.

```
  NOT: Veritabani ve loglar .exe ile ayni klasorde tutulur.
  Uygulamayi tasirken bu klasorun tamamini kopyalayin.
```

---

## 12. Kaldırma

Uygulama Windows'a **kurulmaz**; kayıt defterine yazmaz, Program Ekle/Kaldır
listesinde görünmez. Kaldırmak, dosyaları silmek ve kimlik bilgisi deposundaki
girdileri temizlemektir.

**1. Kısayolları silin**

```powershell
.\scripts\create_shortcut.ps1 -Remove
```

**2. Verinizi dışa alın (silmeden önce!)**

```powershell
.\scripts\backup.ps1
```

`backups\` klasörünü ve `.env` dosyasını proje klasörünün **dışına** kopyalayın.

**3. Credential Manager girdilerini silin**

`AkilliKonaklamaYonetimSistemi` servisi altında iki tür girdi olabilir:

| Anahtar adı | İçerik |
|---|---|
| `field_encryption_key` | Kimlik numarası şifreleme anahtarı |
| `lmstudio_api_key`, `nvidia_api_key`, `openai_api_key`, `anthropic_api_key` | Yapay zekâ sağlayıcı anahtarları (yalnızca kaydettiyseniz) |

Silmek için:

```powershell
.\.venv\Scripts\python.exe -c "from app.core.secret_store import delete_secret; print(delete_secret('field_encryption_key'))"
```

Aynı komutu silmek istediğiniz her anahtar adı için tekrarlayın. Alternatif
olarak Windows'ta **Denetim Masası > Kimlik Bilgileri Yöneticisi > Windows
Kimlik Bilgileri** ekranından da silebilirsiniz.

> `field_encryption_key` silindikten sonra elinizdeki yedeklerdeki kimlik
> numaraları **bir daha okunamaz**. Silmeden önce bölüm 9.3'e bakın.

**4. Proje klasörünü silin**

```powershell
Remove-Item -Recurse -Force C:\AkilliKonaklama
```

Bu işlem `.venv`, `data\hotel.db`, `logs\`, `backups\`, `exports\` ve `.env`
dahil her şeyi kaldırır.

**5. Python (isteğe bağlı)**

Python'u başka bir şey için kullanmıyorsanız Ayarlar > Uygulamalar üzerinden
kaldırabilirsiniz. Uygulama Python'a sistem genelinde hiçbir paket kurmaz;
her şey `.venv` içindedir.

---

## İlgili belgeler

| Belge | İçerik |
|---|---|
| [USER_GUIDE_TR.md](USER_GUIDE_TR.md) | Otel çalışanı için kullanım kılavuzu |
| [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) | Yerel yapay zekâ kurulumu |
| [ROADMAP.md](ROADMAP.md) | Yapılmamış modüller ve bilinen eksikler |
| [../SECURITY.md](../SECURITY.md) | Güvenlik politikası ve açık bildirimi |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Katkı rehberi |
| [../README.md](../README.md) | Genel bakış |
