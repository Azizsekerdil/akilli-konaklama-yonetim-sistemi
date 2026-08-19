# Bilinen Sınırlar

Bu belge **olmayanı** anlatır. Bir maddenin burada olması, o alanda üretime
geçmeden önce ek bir karar vermeniz gerektiği anlamına gelir.

Tamamlanmamış modüllerin yol haritası için [ROADMAP.md](ROADMAP.md);
güvenlik incelemesinin kalan riskler bölümü için
[SECURITY_REVIEW.md](SECURITY_REVIEW.md) 9. bölüm.

Ölçüm tarihi: **19 Ağustos 2026**, sürüm **0.1.0**.

---

## 1. Olgunluk

**Alpha (`Development Status :: 3 - Alpha`).** Program tek bir işletmenin
bilgisayarında çalışacak biçimde tasarlandı, geniş bir kurulum tabanında
denenmedi. Gerçek bir otelde üretim kullanımı için:

- verinizi düzenli yedekleyin **ve geri yüklemeyi deneyin**,
- alan şifreleme anahtarını ayrıca saklayın,
- demo veriyi silin ve demo hesaplarını kapatın.

## 2. Tamamlanmamış modüller

| Modül | Durum |
|---|---|
| e-Fatura / e-Arşiv | **YAPILMADI.** Yalnızca arayüz (interface) katmanı hazır; gerçek entegrasyon yok. Varsayılan olarak kapalı |
| Kimlik Bildirim Sistemi (KBS) | **YAPILMADI.** Aynı şekilde yalnızca arayüz katmanı |
| Stok ve Finans **ekranları** | **Kısmi.** İş mantığı ve raporlar hazır, ayrı ekranları yok — mevcut ekranlarda görünürler |
| Kanal yöneticisi / OTA entegrasyonu | Yok. Mimaride sınır bırakıldı, uygulanmadı |
| PostgreSQL | Kod destekler, **gerçek bir kurulumda denenmedi**. Varsayılan ve test edilen motor SQLite'tır |
| NVIDIA / OpenAI / Anthropic sağlayıcıları | Kod hazır, **gerçek bir API çağrısı hiç yapılmadı**; yalnızca sahte HTTP aktarımıyla test edildi |

## 3. Eşzamanlılık

- Numara üreteçleri (rezervasyon onay numarası, folyo numarası) **eşzamanlı
  güvenli değildir**. Aynı anda iki kullanıcı kayıt oluşturursa çakışma
  olabilir ve işlem yeniden denenmelidir.
- SQLite tek yazıcılıdır. Yoğun çok kullanıcılı kullanım hedefleniyorsa
  PostgreSQL'e geçilmelidir — ancak yukarıdaki maddeye bakın: bu yol
  denenmemiştir.

## 4. Güvenlik ve gizlilik sınırları

- **Alan şifreleme anahtarı yedeklenmez.** `scripts/backup.ps1` veritabanını
  yedekler, anahtarı yedeklemez. Anahtar kaybedilirse kimlik ve pasaport
  alanları **geri getirilemez**. Program artık anahtar kalıcı olarak
  saklanamıyorsa **açılışta durur** ve çözülemeyen bir kaydı sessizce
  boşaltmaz — ama anahtarı sizin yerinize saklayamaz.
- **SQLite dosya sistemi izinlerine güvenir.** Veritabanı dosyasını okuyabilen
  bir yerel kullanıcı, şifreli olmayan alanları (ad, e-posta, telefon) görür.
  Disk şifrelemesi (BitLocker) işletmenin sorumluluğundadır.
- **Otomatik saklama süresi (retention) uygulaması yoktur.** Süresi dolmuş
  kişisel veriyi silmek işletmenin sorumluluğundadır.
- **Bağımsız sızma testi yapılmamıştır.** Güvenlik incelemesi, kod ve testler
  üzerinden yapılan bir iç incelemedir; harici bir denetimin yerini tutmaz.
- AI Geliştirme Merkezi'nin komutu **fiilen çalıştıran** katmanı düşük
  kapsamlıdır. Politika katmanı (kararı veren yer) iyi test edilmiştir.

## 5. Test kapsamı boşlukları

`pytest --cov=app --cov-branch` toplam **%77,6**. Bilinçli boşluklar:

| Alan | Kapsam | Neden |
|---|---|---|
| Açılış yolu (`app/main.py`) | Kapsam dışı | Qt uygulama döngüsünü başlatır; birim testinde anlamlı değil |
| Giriş ekranı, ana pencere | Düşük | Aynı gerekçe; iş mantığı servis katmanında test edilir |
| Komut satırı (`app/cli.py`) | Kapsam dışı | Servisleri sarar; sardığı servisler test edilir |
| `app/devcenter/terminal.py` | Düşük | Gerçek alt süreç başlatır |
| Yedekleme | Düşük | Dosya sistemi ağırlıklı |

Bir test `live` işaretlidir ve varsayılan olarak **atlanır**: gerçek bir
LM Studio sunucusu gerektirir.

## 6. Platform

Yalnızca **Windows 10/11** hedeflenir ve orada test edilir. Linux/macOS'ta
çalışması beklenebilir (saf Python + Qt) ama **denenmemiştir**; keyring arka
ucu ve PowerShell betikleri platforma bağımlıdır.

## 7. Tanıtım sunumu

- Sunum **Calibri** ile dizilmiştir; Calibri, Windows/Office ile gelen
  tescilli bir yazı tipidir. Libre bir yazı tipi (Inter, Source Sans 3,
  DejaVu Sans) tercih edilirdi, ancak sunum PowerPoint COM ile üretildiği
  için yazı tipinin **kurulu olması** gerekir ve üretim makinesinde kurulu
  libre bir yazı tipi yoktu. Ayrıntı: [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
- Sunum üretimi `python-pptx`, `pywin32` ve **kurulu PowerPoint** ister.
  Bunlar çalışma zamanı bağımlılığı değildir.

## 8. İkili (binary) dağıtım

`scripts/build.ps1` PyInstaller ile bir paket üretir. Paketleme, aşağıdaki
lisans dosyalarının hepsi mevcut olmadan **başlamaz**:

`LICENSE`, `THIRD_PARTY_NOTICES.md`, `packaging/licenses/GPL-3.0.txt`,
`packaging/licenses/LGPL-3.0.txt`.

Bunlardan **`LGPL-3.0.txt` bu depoda yoktur** ve ikili paket üretmeden önce
birebir metniyle eklenmelidir; nedeni ve nasıl yapılacağı
[../packaging/licenses/README.md](../packaging/licenses/README.md) dosyasında
yazılıdır. Kaynak koddan çalıştırmak için gerekli değildir.

## 9. Yasal

Program **hukuki, mali veya sağlıkla ilgili tavsiye vermez.** KVKK, e-Fatura,
konaklama vergisi ve kimlik bildirim yükümlülükleri açısından **veri sorumlusu
ve mükellef işletmedir**. Yazılım bu yükümlülükleri yerine getirmeyi
kolaylaştırabilir; yerine getirmiş saymaz.
