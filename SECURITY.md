# Güvenlik Politikası

## Güvenlik açığı bildirimi

Bir güvenlik açığı bulduysanız **genel bir GitHub issue açmayın.**

Bunun yerine depo sahibine özel olarak bildirin (GitHub üzerinden
"Private vulnerability reporting" veya doğrudan iletişim). Bildiriminizde
şunları belirtin:

- Açığın türü ve etkisi
- Yeniden üretme adımları
- Etkilenen sürüm
- Varsa önerdiğiniz düzeltme

Bildirimlere makul sürede yanıt verilmeye çalışılır. Bu bir açık kaynak
projesidir; ticari bir destek taahhüdü yoktur.

---

## Uygulanan güvenlik önlemleri

### Kimlik doğrulama ve yetkilendirme
- Parolalar **Argon2id** ile hash'lenir (OWASP'ın birinci önerisi)
- Parola politikası: asgari uzunluk, harf+rakam, yaygın parola reddi
- **Kaba kuvvet koruması**: ardışık başarısız denemede hesap geçici kilitlenir
- **Kullanıcı sayımı engellenir**: var olmayan kullanıcı için de parola
  doğrulaması yapılır ve aynı hata mesajı döner
- Oturum jetonu veritabanında **hash'lenerek** saklanır
- Oturum zaman aşımı; parola değişiminde tüm oturumlar kapatılır
- Rol bazlı erişim kontrolü (72 izin, 7 varsayılan rol — sayı koddan
  ölçülür: `python -c "from app.security.permissions import PERMISSIONS; print(len(PERMISSIONS))"`)
- Yetki kontrolü **hem arayüzde hem servis katmanında** yapılır; menüyü
  gizlemek tek başına bir güvenlik önlemi sayılmaz

### Kişisel veri koruması (KVKK)
- Kimlik/pasaport numaraları **Fernet ile şifreli** saklanır
- Şifreli alanda arama, HMAC-SHA256 tabanlı **kör indeks** ile yapılır.
  Anahtar bulunamazsa indeks **hesaplanmaz** (fail-closed): kaynak koda
  gömülü sabit bir yedek anahtar yoktur, çünkü yayımlanan bir sabit
  herkesçe bilinir hâle gelir ve indeksi çevrimdışı taramaya açardı
- Kimlik numarasını açık görmek **ayrı bir yetkidir** ve her görüntüleme
  denetim günlüğüne yazılır
- Loglarda API anahtarı, e-posta, telefon, TCKN ve kart numarası
  **otomatik maskelenir**
- Kredi kartı numarası **hiçbir zaman saklanmaz**; yalnızca son 4 hane
- KVKK izinleri verme *ve geri alma* tarihleriyle birlikte kaydedilir

### Sır yönetimi
- API anahtarları **Windows Credential Manager** (keyring) içinde tutulur
- Veritabanı yalnızca "anahtar hangi adla saklanıyor" bilgisini tutar
- `.env` yalnızca geliştirme içindir ve `.gitignore` kapsamındadır
- Depoya yalnızca `.env.example` gönderilir
- Alt süreçlere gizli ortam değişkenleri **geçirilmez**

### Veri bütünlüğü
- SQLite'ta yabancı anahtar kısıtları açıktır (varsayılan olarak kapalıdır)
- Parametreli sorgular; ham SQL birleştirme yapılmaz
- Pydantic ile girdi doğrulama
- Mali kayıtlar **silinmez**, gerekçeli olarak geçersiz kılınır
- Rezervasyon çakışması iki aşamada kontrol edilir (yazma öncesi ve sonrası)

### AI Geliştirme Merkezi
- Komut güvenlik politikası: izin listesi öncelikli, bilinmeyen komut
  onaysız çalışmaz
- Sandbox kökü: proje klasörü dışına çıkılamaz
- Dosya değişiklikleri önce **diff** olarak gösterilir; onaysız yazma yok
- Her değişiklik öncesi Git kontrol noktası, ayrı görev dalı
- Testler geçmeden değişiklik işlenmez
- Sistem klasörleri, kayıt defteri, kullanıcı yönetimi ve disk işlemleri
  koşulsuz engellenir

### Hata yönetimi
- Kullanıcıya gösterilen mesaj ile teknik ayrıntı ayrılır; yığın izleri,
  SQL parçaları ve dosya yolları son kullanıcıya sızmaz

---

## Bilinen sınırlar

Dürüstlük gereği açıkça belirtilmesi gerekenler:

1. **Alan şifreleme anahtarı kaybedilirse veriler geri getirilemez.**
   Yedekleme yordamı anahtarı yedeklemez; yönetici anahtarı ayrıca güvenli
   bir yerde saklamalıdır.
2. **SQLite dosya sistemi izinlerine güvenir.** Veritabanı dosyasına erişimi
   olan biri şifreli olmayan alanları okuyabilir. Çok kullanıcılı kurulumda
   PostgreSQL önerilir.
3. **Numara üreteçleri (rezervasyon/folyo no) eşzamanlı güvenli değildir.**
   Çok kullanıcılı yoğun kullanımda çakışma olabilir; çağıran taraf yeniden
   denemelidir.
4. **e-Fatura, e-Arşiv ve KBS entegrasyonları tamamlanmamıştır.** Bu
   modüller yalnızca veri modeli düzeyindedir.
5. **Sızma testi yapılmamıştır.** Otomatik güvenlik taraması (bandit,
   pip-audit) ve testler mevcuttur; bağımsız bir güvenlik denetimi
   yapılmamıştır.

---

## Üretim öncesi kontrol listesi

- [ ] `HOTEL_SECRET_KEY` varsayılan değerden değiştirildi
- [ ] `HOTEL_APP_ENV=production` ayarlandı, `HOTEL_APP_DEBUG=false`
- [ ] Yönetici parolası değiştirildi, demo hesapları silindi
- [ ] Demo veri temizlendi
- [ ] Alan şifreleme anahtarı güvenli bir yerde yedeklendi
- [ ] Otomatik yedekleme kuruldu ve **geri yükleme denendi**
- [ ] Vergi oranları işletmenin gerçek oranlarıyla güncellendi
- [ ] Kullanıcılara en az yetki ilkesiyle rol atandı
- [ ] AI Geliştirme Merkezi yetkisi yalnızca gerekli kişide
- [ ] API sunucusu yalnızca `127.0.0.1` üzerinde dinliyor
- [ ] LM Studio kullanılıyorsa yalnızca yerel adreste çalışıyor
