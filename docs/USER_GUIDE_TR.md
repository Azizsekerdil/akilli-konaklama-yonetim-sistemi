# Kullanım Kılavuzu

Bu kılavuz **otelde çalışan kişiler** içindir: resepsiyon görevlisi, kat
hizmetleri sorumlusu, teknik servis, muhasebe ve otel müdürü. Bilgisayar
bilgisi gerektirmez.

Programın kurulumu ayrı bir belgede anlatılır:
[INSTALLATION_WINDOWS.md](INSTALLATION_WINDOWS.md).

> Bu kılavuzdaki her ekran, düğme ve uyarı metni programın kendisinden
> alınmıştır. Anlatılan her şey gerçekten vardır. Henüz tamamlanmamış
> bölümler açıkça belirtilmiştir.

---

## İçindekiler

1. [Giriş ve ilk kullanım](#1-giriş-ve-ilk-kullanım)
2. [Ekranın genel düzeni](#2-ekranın-genel-düzeni)
3. [Yönetim Paneli](#3-yönetim-paneli)
4. [Rezervasyonlar](#4-rezervasyonlar)
5. [Ön Büro](#5-ön-büro)
6. [Odalar](#6-odalar)
7. [Kat Hizmetleri](#7-kat-hizmetleri)
8. [Teknik Servis](#8-teknik-servis)
9. [Misafirler](#9-misafirler)
10. [Raporlar](#10-raporlar)
11. [Yapay Zekâ Merkezi](#11-yapay-zekâ-merkezi)
12. [Klavye kısayolları](#12-klavye-kısayolları)
13. [Roller ve yetkiler](#13-roller-ve-yetkiler)
14. [Sık sorulanlar](#14-sık-sorulanlar)

---

## 1. Giriş ve ilk kullanım

### Programı açma

Masaüstündeki **Akilli Konaklama Yonetimi** kısayoluna çift tıklayın.
Kısayol yoksa sistem sorumlunuzdan oluşturmasını isteyin.

### Giriş ekranı

Kullanıcı adınızı ve parolanızı yazıp **Giris** düğmesine basın ya da
doğrudan **Enter** tuşuna basın. Vazgeçmek için **Esc**.

Ekranda bir **"Kullanıcı adımı hatırla"** kutusu vardır. Kutunun açıklaması
"Parola HİÇBİR ZAMAN saklanmaz" der ve bu doğrudur; ancak **kutu şu an
işlevsizdir** — işaretlense de kullanıcı adı bir sonraki açılışa
taşınmamaktadır. (Doğrulandı: seçim programda hiçbir yerde okunmuyor.)

Bilgiler yanlışsa her durumda aynı ileti çıkar:

> Kullanici adi veya parola hatali.

Bu bilinçli bir tercihtir: kullanıcı adının var olup olmadığı dışarıya
sızdırılmaz.

Art arda birkaç kez yanlış parola girilirse hesap **geçici olarak
kilitlenir**:

> Cok fazla basarisiz giris denemesi nedeniyle hesabiniz gecici olarak
> kilitlendi.

Varsayılan ayar 5 başarısız denemeden sonra 15 dakikadır. Bu süreyi sistem
sorumlunuz değiştirebilir.

### İlk girişte parola değiştirme zorunludur

Size verilen ilk parola **tek kullanımlıktır**. İlk girişte kapatılamayan bir
pencere açılır:

> Guvenlik nedeniyle ilk giriste parolanizi degistirmeniz gerekiyor.

Yeni parolanın taşıması gereken özellikler ekranda da yazar:

- En az **10 karakter**
- En az bir **harf** ve en az bir **rakam**
- Çok yaygın parolalar kabul edilmez (`parola123`, `admin12345` gibi)
- Kullanıcı adınızı içeremez
- En az 4 farklı karakter içermeli

Parolayı değiştirdiğinizde **açık olan tüm oturumlarınız kapanır** ve program
sizden yeniden giriş yapmanızı ister. Bu, başka bir bilgisayarda açık kalmış
bir oturumun kullanılmaya devam etmesini engeller.

### Parolayı sonradan değiştirmek

Sağ üstteki adınıza tıklayın → **Parola Degistir**. Aynı kurallar geçerlidir
ve değişiklikten sonra yeniden giriş yapmanız istenir.

### Oturum süresi

Bir süre işlem yapılmazsa oturumunuz kapanır (varsayılan 30 dakika) ve şu
ileti görünür:

> Oturum sureniz doldu. Lutfen yeniden giris yapin.

Vardiya değişiminde bilgisayarı açık bırakmak yerine sağ üstteki menüden
**Cikis** yapmanız önerilir.

---

## 2. Ekranın genel düzeni

| Bölüm | Ne işe yarar |
|---|---|
| **Üst çubuk** | Solda program adı, ortada **tesis seçici** (birden çok tesis varsa), sağda adınız ve menüsü |
| **Sol menü** | Ekranlar arası geçiş |
| **Orta alan** | Seçili ekranın içeriği |
| **Alt çubuk** | Adınız ve rolleriniz |

### Menüde gördükleriniz kişiye göre değişir

Sol menüde **yalnızca yetkiniz olan ekranlar** görünür. Bir arkadaşınızda olan
bir ekran sizde yoksa, o ekran için yetkiniz yok demektir; bu bir arıza
değildir. Yetki değişikliği için sistem sorumlunuza başvurun.

### Yenileme

Her ekranın sağ üstünde bir **Yenile** düğmesi vardır. Klavyeden **F5**
tuşu da aynı işi yapar ve "Veriler yenilendi." bildirimi çıkar.

Bir ekran ilk açılışında verisini yükler ve tekrar açtığınızda hazır gelir;
başka birinin yaptığı değişikliği görmek için **Yenile** demeniz gerekir.

### Henüz tamamlanmamış ekranlar

**Finans** ve **Stok** ekranları menüde görünür ancak içlerinde işlem
yapılmaz. Açtığınızda ne planlandığı ve aynı işi şu an nasıl
yapabileceğiniz yazılıdır:

- **Finans yerine:** tahsilat ve folyo işlemleri **Ön Büro** ekranından
  yapılır, mali özetler **Raporlar** ekranındadır.
- **Stok yerine:** kritik stok uyarıları **Yönetim Paneli**'nde görünür,
  stok raporu **Raporlar** ekranından alınır.

### Tema ve dil

**Ayarlar > Genel > Görünüm** bölümünden koyu/açık tema seçilir. Tema seçimi
anında uygulanır. Dil değişikliği için programın yeniden başlatılması
gerekir.

---

## 3. Yönetim Paneli

Günün tek bakışta özeti. Sekiz gösterge kartı, kritik uyarılar, operasyon
durumu, 14 günlük doluluk tahmini ve bugünkü girişler listesi vardır.

### Gösterge kartları

| Kart | Ne gösterir |
|---|---|
| **Doluluk Orani** | Bugün dolu oda oranı; altında `dolu/satılabilir oda` yazar |
| **Bos Oda** | Satılabilir ve şu anda boş oda sayısı |
| **Bugunku Girisler** | Bugün gelmesi beklenen oda satırı sayısı; altında kaçının henüz gelmediği yazar |
| **Bugunku Cikislar** | Bugün çıkış yapacak oda sayısı |
| **Otelde** | Şu anda konaklayan oda sayısı |
| **Gunluk Gelir** | Bugüne işlenmiş **tüm** gelir; altında son 7 günün toplamı |
| **Ortalama Oda Fiyati (ADR)** | Bugünkü oda geliri ÷ dolu oda sayısı |
| **Oda Basina Gelir (RevPAR)** | Bugünkü oda geliri ÷ satılabilir oda sayısı |

### Doluluk oranı nasıl hesaplanır?

```
Doluluk = Dolu oda sayısı ÷ SATILABILIR oda sayısı
```

**Satılabilir oda**, o gün gerçekten satılabilecek odadır. Panelde
**"Servis Dışı"** ve **"Arızalı"** işaretli odaların ikisi de paydadan
düşülür. Nedeni basittir: bozuk bir odayı satamazsınız; onu paydada bırakmak,
işletmeyi kendi elinde olmayan bir nedenle düşük dolulukta gösterir.

**Örnek.** 40 odalı bir otelde 3 oda arızalı ve 25 oda dolu ise:

```
Satılabilir = 40 − 3 = 37
Doluluk     = 25 ÷ 37 = %67,6      (25 ÷ 40 = %62,5 DEĞİL)
```

> **Raporlar ekranındaki doluluk biraz farklı hesaplanır.** Orada paydadan
> yalnızca **"Arızalı"** odalar düşülür; "Servis Dışı" odalar envanterde
> kalır. Ayrım bilinçlidir: "Servis Dışı" küçük ve geçici bir sorunu,
> "Arızalı" ise odayı envanterden çıkaran ciddi bir arızayı ifade eder.
> Panel *bugünün operasyonunu*, rapor ise *dönemin performansını* gösterir.

### ADR nedir, neden sadece oda gelirini sayar?

**ADR** (Average Daily Rate), satılan bir odanın ortalama fiyatıdır.

```
ADR = ODA GELİRİ ÷ satılan oda sayısı
```

Paya **yalnızca oda geliri** girer. Restoran, SPA, minibar, transfer, otopark
gelirleri **ADR'ye dahil edilmez**. Bu, sektörde en sık yapılan hesap
hatasıdır: toplam gelir kullanılırsa ADR şişer ve rakip kıyaslaması, acente
komisyon pazarlığı, fiyat kararları yanlış bir temele oturur.

### RevPAR nedir?

**RevPAR** (Revenue Per Available Room), satılabilir oda başına oda geliridir.

```
RevPAR = oda geliri ÷ SATILABILIR oda sayısı
       = ADR × Doluluk
```

RevPAR, ADR'den daha dürüsttür: yüksek fiyattan az oda satan bir otel yüksek
ADR ama düşük RevPAR üretir. Fiyat ve doluluğu tek sayıda birleştirdiği için
yönetimin ana göstergesidir.

**Örnek.** ADR 1.500 TL, doluluk %80 → RevPAR = 1.200 TL.

### Kritik Uyarılar

Bu kutuda yalnızca **eyleme geçmeniz gereken** durumlar listelenir:

| Uyarı | Anlamı |
|---|---|
| *N acil ariza kaydi var* | Acil/kritik öncelikli açık arıza; Teknik Servis'e bakın |
| *N oda satisa kapali* | O odalar doluluk hesabında envanterden düşülür |
| *N urun kritik stok seviyesinde* | Satın alma talebi oluşturmayı değerlendirin |
| *N misafir henuz giris yapmadi* | Gün sonunda gelmeyenleri "Gelmedi" olarak işaretleyin |
| *N gecmis tarihli rezervasyon islem bekliyor* | Girişi yapılmamış eski kayıtları kapatın |
| *N kirli oda, N giris bekliyor* | Kat hizmetlerinde önceliklendirme gerekebilir |

Hiçbir şey yoksa "Kritik uyari yok." yazar. İşaretlerin rengi tek başına anlam
taşımaz; her satırda ne olduğu yazılıdır.

### Operasyon kutusu

Kirli Oda, Servis Dışı, Bekleyen Görev, Açık Arıza ve Kritik Stok sayılarını
tek bakışta verir.

### 14 Günlük Doluluk Tahmini

Bugünden itibaren 14 günün beklenen doluluğunu mevcut rezervasyonlara göre
çizer. **Tahmin bir tahmindir**: yeni rezervasyon geldikçe ve iptaller
oldukça değişir.

### Bugünkü Girişler tablosu

Oda, misafir, gece sayısı ve durum (*Giris yapildi* / *Bekliyor*).

---

## 4. Rezervasyonlar

### Listeyi süzme

Ekranın üstünde üç süzgeç vardır:

- **Arama kutusu:** onay numarası, misafir adı veya oda numarası
- **Durum:** Taslak, Opsiyonlu, Onaylandı, Giriş Yapıldı, Çıkış Yapıldı,
  İptal, Gelmedi, Bekleme Listesi
- **Tarih:** Tümü / Bugün / Bu hafta / Bu ay / Gelecek

Başlıkta kaç kaydın gösterildiği ve toplam kaç kayıt olduğu yazar. Ekran tek
seferde en fazla **500 kayıt** getirir; daha eskisine ulaşmak için arama
kutusunu kullanın.

### Ayrıntı paneli

Listeden bir satıra tıklayın; alt panelde onay numarası, durum rozeti, kanal,
misafir bilgisi, oda satırları ve tutar dökümü (Toplam / Depozito / Tahsil
edilen / Bakiye) görünür.

Misafir kara listedeyse panelde kırmızı bir **"Misafir kara listede"** uyarısı
belirir.

### Yeni rezervasyon adımları

Sağ üstteki **Yeni Rezervasyon** düğmesi tek bir pencere açar. Pencere
yukarıdan aşağı dört numaralı bölümden oluşur; en altta ise her zaman görünen
bir **Fiyat Dökümü** şeridi vardır.

**1. Tarih ve Kişi Sayısı**
Giriş, çıkış, yetişkin ve çocuk sayısını girin. Altta kaç gece olduğu anında
yazar. **Musaitlik Ara** düğmesine basın.

**2. Müsaitlik ve Oda Seçimi**
Tesisin tüm oda tipleri listelenir. **Müsait olmayan tipler listeden
silinmez**; satırda nedeni yazar:

- *"Musait degil"* → o tarihlerde boş oda kalmamış
- *"Kapasite yetersiz (en fazla N kisi)"* → girdiğiniz kişi sayısı bu oda
  tipine sığmıyor

Bir satır seçtiğinizde fiyat dökümü dolar. İsterseniz **belirli bir oda**
seçebilirsiniz; seçmezseniz "Farketmez - girise kadar atanacak" kalır ve oda
girişte atanır.

**3. Misafir**
İki sekme vardır:
- **Mevcut Misafir:** ad, soyad, telefon veya e-posta ile arayın (en az iki
  karakter). Kara listedeki kayıtlar `[KARA LISTE]` etiketiyle görünür.
- **Yeni Misafir:** ad ve soyad zorunludur; telefon ve e-posta isteğe bağlı.

**4. Rezervasyon Bilgileri**
Kanal (Doğrudan, Telefon, Kapıdan Gelen, Booking.com, Acente…), özel istekler
ve depozito tutarı.

**Fiyat Dökümü** şeridi pencerenin altında sabit durur; kaydırsanız da
görünür kalır. Toplam tutarı görmeden **Kaydet** demeniz beklenmez.

### "Çakışma uyarısı" ne demek?

Sistemin en temel kuralı şudur: **aynı oda aynı gece iki kez satılamaz.**
Böyle bir durumda şu uyarıyı alırsınız:

> Bu odada 01.09.2026 - 04.09.2026 tarihlerinde RZV-2026-000042 numarali
> rezervasyon bulunuyor.

Yapılacaklar: başka bir oda seçin, tarihleri değiştirin ya da müsaitlik
aramasını yeniden çalıştırın.

> **Çıkış günü ile ilgili önemli kural:** Konaklama **giriş günü dahil, çıkış
> günü hariç** sayılır. 1 Eylül'de girip 4 Eylül'de çıkan bir misafir 3 gece
> kalır ve **4 Eylül gecesi o oda başka bir misafire satılabilir**. Bu bir
> hata değil, otelcilikteki standart hesaptır.

Kara listedeki bir misafire rezervasyon açmak da engellenir:

> [Misafirin adı] kara listede. Rezervasyon icin yetkili onayi gerekir.

### Onaylama, iptal ve "Gelmedi"

Ayrıntı panelinin altındaki üç düğme, **kaydın mevcut durumuna** ve
yetkinize göre etkinleşir. Hiçbiri kullanılamıyorsa nedeni yanında yazar:

> 'Iptal' durumundaki bir rezervasyon uzerinde durum degisikligi yapilamaz.

**Onayla** — opsiyonlu/taslak bir kaydı kesinleştirir.

**İptal Et** — önce **iptal gerekçesi** ister; gerekçe **zorunludur**. Sonra
onay kutusunda uyarır:

> Gerekce: ...
> Iptal ucreti tarifeye gore hesaplanacaktir.

İptal edilince hesaplanan ücret ayrı bir pencerede gösterilir:

> RZV-2026-000042 iptal edildi.
> Hesaplanan iptal ucreti: 1.000,00 ₺

**Gelmedi İşaretle** — misafir hiç gelmediyse kullanılır. Odaları serbest
bırakır ve tarifeye göre ceza ücreti hesaplar (varsayılan: toplam tutarın
%100'ü).

### İptal ücreti nasıl belirlenir?

| Durum | Alınan ücret |
|---|---|
| Ücretsiz iptal süresi içinde | **Ücret yok** |
| Ücretsiz iptal süresi geçtikten sonra | Tarifedeki iptal ücreti yüzdesi |
| **İade edilemez** tarife | Her zaman **tam tutar** |
| **Gelmedi (no-show)** | Tarifedeki gelmeme yüzdesi |

Ücretsiz iptal süresi, iptal ücreti yüzdesi ve gelmeme yüzdesi rezervasyonun
**fiyat tarifesinde** tanımlıdır. Rezervasyona bağlı bir tarife yoksa
program şu varsayılanları kullanır: ücretsiz iptal **24 saat**, iptal ücreti
**%0**, gelmeme ücreti **%100**.

> **Önemli:** Program iptal/gelmeme ücretini **hesaplar ve size gösterir**,
> ancak misafirin hesabına (folyoya) **otomatik olarak işlemez**. Tahsil
> edilecekse ilgili tutarı folyoya elle eklemeniz gerekir. Bu, hesaplanan
> ücreti onaylamadan yansıtmamak için bilinçli bir tercihtir.

İptal ve gelmedi işlemleri misafirin kartındaki iptal / gelmeme sayacını
artırır ve denetim günlüğüne yazılır.

---

## 5. Ön Büro

Günlük operasyonun kalbi. Üstte dört gösterge, altında üç sekme vardır.

**Göstergeler:** Bekleyen Giriş · Bekleyen Çıkış · Otelde · Açık Bakiye
(tahsil edilmemiş toplam folyo bakiyesi).

### Sekme 1 — Bugünkü Girişler

Onay no, misafir, oda tipi, oda, gece, kişi ve durum sütunları vardır.
Durum üç değer alır: *Oda atanmadi*, *Bekliyor*, *Giris yapildi*.

Bir satır seçip **Giris Yap** düğmesine basın (ya da satıra çift tıklayın).
Düğme kapalıysa nedeni fare ile üzerine gelince yazar; örneğin:

> Bu rezervasyon icin giris zaten yapilmis.

#### Giriş penceresi

Üstte rezervasyon özeti (onay no, misafir, oda tipi, tarihler, kişi, pansiyon,
tutar) salt okunur olarak görünür. Misafirin özel talebi varsa mavi bir
şeritte yazar. Kimlik bilgisi eksikse misafir adının yanında
*"(kimlik bilgisi eksik)"* uyarısı çıkar.

Doldurulacak alanlar:

| Alan | Açıklama |
|---|---|
| **Oda** | O tarihlerde uygun ve boş odalar listelenir. Rezervasyonda oda atanmışsa seçili gelir. |
| **Kimlik No** | Kimlik veya pasaport numarası. Zorunlu değildir. |
| **Oda Kartı** | Verilen kart adedi (0–8) |
| **Erken Giriş** | Standart giriş saatinden kaç saat önce girildiği |

> **KVKK notu (ekranda da yazar):** *Kimlik numarasi sifreli saklanir ve
> yalnizca yetkili personel tarafindan gorulebilir. Yalnizca konaklama
> bildirimi icin gerekli oldugunda girin.*

**Erken giriş ücreti** her 3 saatlik dilim için gecelik ücretin %25'i olarak
hesaplanır ve en fazla bir gecelik ücrete kadar çıkar. Bu alan yalnızca
"Erken giriş / geç çıkış onayı" yetkisi olan kullanıcılarda açıktır; yetkisi
olmayanda kutuda **"Yetkiniz yok"** yazar.

#### Kirli odaya giriş

Seçtiğiniz oda temizlenmemişse pencerenin altında sarı bir uyarı ve bir onay
kutusu belirir:

> Uyari: 204 numarali oda henuz temizlenmemis (Kirli). Girisin
> yapilabilmesi icin asagidaki kutuyu isaretleyerek onay vermelisiniz.

Kutuyu işaretlemeden **Giris Yap** düğmesi açılmaz. Uyarı ve kutu bilerek
düğmenin hemen yanında, her zaman görünür konumdadır.

#### Giriş yapıldığında ne olur?

1. Oda **Dolu** duruma geçer
2. Misafirin **folyosu (hesabı) açılır**
3. Oda ücreti **gece gece ayrı satırlar** hâlinde folyoya işlenir
   (*"Oda ucreti - 01.09.2026"*). Böylece erken çıkışta kalan geceler tek tek
   düşülebilir ve misafire gün gün döküm gösterilebilir.
4. Erken giriş ücreti girildiyse ayrı bir satır olarak eklenir
5. Rezervasyonun durumu **Giriş Yapıldı** olur

### Sekme 2 — Bugünkü Çıkışlar

Oda, misafir, giriş, çıkış, **bakiye** ve durum sütunları. Bakiye sütununda
renk tek başına bilgi taşımaz; açık hesapta tutarın yanında **"(acik)"**,
fazla ödemede **"(fazla odeme)"** yazar. Folyosu olmayan satırda `-` görünür.

Bir satır seçip **Cikis Yap** düğmesine basın.

#### Çıkış penceresi

Dört bölümden oluşur:

**Konaklama** — onay no, misafir, oda, tarihler.

**Folyo Özeti** — Toplam Ücret, Ödenen ve büyük puntoyla **KALAN BAKİYE**.
Altındaki not durumu açıkça söyler:

- *Bakiye acik. Cikis yapabilmek icin once tahsilat alin.*
- *Hesap kapali; cikis yapilabilir.*
- *Bu konaklama icin acik folyo bulunmuyor.*

**Tahsilat Al** — yalnızca açık bakiye varken görünür. Tutar ve ödeme yöntemi
(Nakit, Kredi Kartı, Banka Kartı, Havale/EFT, Online Ödeme, Voucher, Cari
Hesap) seçilir, **Tahsilat Yap** denir.

**Çıkış Bilgileri** — Geç Çıkış (saat), İade Edilen Oda Kartı, Hasar
Açıklaması ve Hasar Tutarı. **Açıklama yazmadan hasar tutarı girilemez**;
tutar alanı kapalı durur.

#### Açık bakiyeyle çıkış

Bakiye kapanmadan çıkış yapmaya çalışırsanız işlem **engellenir**:

> Folyo bakiyesi 1.250,00 ₺ acik. Cikis oncesi tahsilat yapilmalidir.
>
> Cozum: Once tahsilat yapin: yukaridaki 'Tahsilat Al' bolumunden kalan
> bakiyeyi tahsil edin, sonra cikis yapin.

Tahsilat mümkün değilse (ör. kurumsal misafir, fatura sonra gönderilecek)
pencerenin altındaki **"Kalan bakiyeyi cari hesaba devret (yonetici onayi)"**
kutusu kullanılır. Bu kutu yalnızca **finans yönetimi** yetkisi olan
kullanıcılarda açıktır; işlem denetim günlüğüne yazılır.

#### Çıkış onayı ve sonuçları

Çıkış **geri alınamaz**. Bu yüzden onay kutusunda varsayılan cevap "Hayır"dır:

> 204 numarali odadan cikis yapilsin mi?
> Folyo kapatilir, oda kirli olarak isaretlenir ve temizlik gorevi
> olusturulur. Bu islem geri alinamaz.

Çıkış yapıldığında:

1. Geç çıkış ve hasar ücretleri folyoya işlenir
2. Folyo **kapatılır**
3. Oda **Boş + Kirli** olur ve **yüksek öncelikli bir temizlik görevi** açılır
4. Misafirin konaklama geçmişi güncellenir (konaklama sayısı, gece, ciro)
5. Rezervasyon **Çıkış Yapıldı** olur — çok odalı bir rezervasyonda ise
   **tüm odalar çıkış yapana kadar** rezervasyon kapanmaz

### Sekme 3 — Otelde

Şu anda konaklayanları gösterir. Durum sütununda *Otelde*, *Bekleniyor*
(bugün gelecek ama henüz gelmemiş) veya *Cikis yapildi* yazar.

Bir satır seçip **Folyo** düğmesine basınca misafir hesabı açılır.

### Folyo (misafir hesabı)

Folyo penceresi üç bölümdür: **Ücretler**, **Ödemeler** ve **Özet**.

**Ücret Ekle** — tür (Restoran, Minibar, SPA, Çamaşırhane, Transfer,
Otopark, Telefon, İnternet, Hasar…), açıklama, miktar ve birim fiyat
istenir. Açıklama zorunludur:

> Aciklama zorunludur; misafir folyosunda ne oldugu okunmalidir.

**Tahsilat** — kalan bakiye önerilir; tutar, ödeme yöntemi ve isteğe bağlı
referans (dekont/işlem numarası) girilir.

> **Kart numarası kaydedilmez; yalnızca ödeme yöntemi ve tutar saklanır.**

**Geçersiz Kıl** — yanlış işlenmiş bir ücreti kaldırmak için kullanılır.
**Kayıt silinmez**: üstü çizili ve soluk olarak listede kalır, gerekçesi
fareyle üzerine gelince okunur ve toplama dahil edilmez.

> Kayit silinmez; gecersiz olarak isaretlenir ve folyoda ustu cizili
> gorunmeye devam eder. Gerekce denetim gunlugune yazilir.

Gerekçe **zorunludur**. Bu kural mali denetim izinin korunması içindir: bir
ücretin niye iptal edildiği her zaman geriye dönük olarak görülebilmelidir.

Özet bölümünde Toplam Ücret, Toplam Ödeme ve **BAKİYE** yazar; altında durum
açıklanır (*Hesap kapali; odenecek tutar yok.* / *Bakiye acik - cikis oncesi
tahsilat yapilmalidir.* / *Fazla odeme var - iade gerekebilir.*) ve varsa kaç
satırın geçersiz kılındığı belirtilir.

---

## 6. Odalar

İki görünüm vardır: **Oda Planı** ve **Liste**.

### Oda planı renkleri

Odalar bina ve kat kat gruplanmış kartlar hâlinde gösterilir. Kartın sol
kenarındaki renk şeridi durumu anlatır; üstteki renk açıklaması da ekranda
durur:

| Renk | Anlamı |
|---|---|
| **Boş - Temiz** | Oda satışa hazır |
| **Boş - Kirli** | Misafir yok ama temizlik bekliyor |
| **Dolu** | İçinde misafir var |
| **Servis Dışı** | Satışa kapalı (bakım/arıza) |

**Renk tek başına bilgi taşımaz.** Her kartın üzerinde durum metni de yazar
(ör. *"Bos - Kirli"*), böylece renk körlüğü olan bir kullanıcı da ayrımı
yapabilir.

Renk önceliği şöyledir: **önce satışa kapalılık**, sonra doluluk, en son
temizlik durumu. Yani dolu ama arızalı bir oda "Servis Dışı" renginde
görünür — çünkü asıl bilgi o odanın satılamayacağıdır.

Kartın üzerine geldiğinizde oda numarası, tipi, durumu, varsa misafir adı ve
açık arıza kaydı ipucu olarak çıkar.

### Oda ayrıntısı

Sağdaki panelde seçili odanın tipi, bina/kat, doluluk, temizlik durumu,
misafiri, planlanan çıkış tarihi, açık arıza kaydı ve özellikleri (manzara,
sigara, engelli erişimi vb.) listelenir.

### Oda durumunu değiştirme

İki yol vardır: sağ paneldeki düğmeler veya kartın üzerinde **sağ tık**.
Üç seçenek sunulur:

- **Temiz yap**
- **Kirli yap**
- **Servis dışı yap**

Bu menüde **silme gibi geri alınamaz bir işlem yoktur**; oda durumu her zaman
geri alınabilir olmalıdır.

**Servis dışı yapmak** ayrıca onay ister:

> 204 numarali oda satisa kapatilsin mi?
> Bu odaya yeni rezervasyon alinamaz. Islem geri alinabilir.

O odada aktif bir rezervasyon varsa işlem durur. Yalnızca **"Kural
uyarılarını aşma"** yetkisi olan kullanıcıya devam seçeneği sunulur:

> Yine de kapatmak icin onaylayin. Misafirin baska bir odaya alinmasi sizin
> sorumlulugunuzdadir; islem denetim gunlugune yazilir.

Yetkisi olmayan kullanıcıya bu seçenek **hiç gösterilmez**; yalnızca uyarı
görünür.

### Liste görünümü

Aynı odalar tablo hâlinde; kat, oda tipi ve temizlik durumuna göre süzülür,
oda numarası/tip/özellik metniyle aranır. Altta kaç odanın gösterildiği
yazar.

---

## 7. Kat Hizmetleri

Ekranın merkezinde **bir gün** vardır. Üstteki tarih kutusunu değiştirdiğinizde
tüm liste o güne göre yeniden yüklenir; geçmiş bir günün performansı da aynı
ekrandan incelenebilir.

### Günün görevlerini oluşturma

**Gunun Gorevlerini Olustur** düğmesi iki tür görev açar:

- O gün **çıkış** yapacak odalar → *çıkış temizliği* (yüksek öncelik; oda aynı
  gün yeniden satılabilir)
- O gün **konaklamaya devam eden** odalar → *günlük temizlik*

Düğmeye ikinci kez basmak görevleri tekrarlamaz. Yeni görev üretilmediyse
program bunu açıkça söyler:

> Yeni gorev uretilmedi - bu gunun gorevleri zaten hazir.

### Göstergeler ve liste

Üstte dört sayaç vardır: **Bekleyen**, **Devam Eden**, **Tamamlanan**,
**Kontrol Edilen**.

Tablo sütunları: Oda · Tür · Öncelik · Atanan · Durum · Süre · Kontrolde
Görülen. Liste oda numarasına göre artan sırada gelir — kat görevlisi listeyi
kat kat yukarıdan aşağı çalışır.

Süre sütununda görev tamamlandıysa **gerçek süre** (ör. `35 dk`),
tamamlanmadıysa **tahmini süre** (ör. `~45 dk`) görünür.

### Görev akışı

| Düğme | Ne yapar | Gerekli yetki |
|---|---|---|
| **Ata** | Soldaki listeden seçtiğiniz kat görevlisine görevi verir | Görev atama |
| **Başla** | Temizliği başlatır; oda "Temizleniyor" olur | Görevi tamamlama |
| **Tamamla** | Kaç dakikada temizlendiğini sorar, odayı **Temiz** yapar | Görevi tamamlama |
| **Kontrol Et** | Temizliği denetler | Temizlik kontrolü |

**Kontrol Et** üç seçenek sunar:

> 204 numarali odanin temizligi uygun mu?
> 'Kaldi' secilirse oda yeniden kirli isaretlenir ve gorev tekrar acilir.

- **Geçti** → oda kontrol edilmiş sayılır
- **Kaldı** → önce eksiklerin ne olduğu sorulur, sonra ayrıca onay istenir;
  oda **yeniden kirli** işaretlenir ve görev tekrar açılır
- **İptal** → hiçbir şey yapılmaz

Kontrolü geçmeyen bir odayı "tamamlandı" bırakmak, resepsiyonun o odayı
satmasına ve misafirin kirli odaya girmesine yol açardı; bu yüzden kural
katıdır.

Bir düğme kapalıysa nedeni ipucunda yazar (ör. *"Gorev atama yetkiniz
bulunmuyor."*). Personel listesi boşsa **"Tanimli personel yok"** görünür ve
atama yapılamaz.

---

## 8. Teknik Servis

### Yeni arıza kaydı

Sağ üstteki **Yeni Ariza** düğmesi bir form açar:

| Alan | Açıklama |
|---|---|
| **Oda** | Belirli bir oda ya da "Ortak alan (oda disi)" |
| **Konum** | Yalnızca ortak alan seçilince açılır (ör. *"Lobi - 2. asansor"*) |
| **Kategori** | Elektrik, tesisat, mobilya vb. |
| **Öncelik** | Düşük, Normal, Yüksek, Acil, Kritik |
| **Başlık** | Kısa başlık (ör. *"Klima sogutmuyor"*) |
| **Açıklama** | Sorunun ayrıntısı |

### ⚠ Odayı satışa kapatma

Formun altındaki **"Odayi satisa kapat (servis disi)"** kutusu işaretlendiğinde
başlangıç ve bitiş tarihi istenir. Ekranda uyarı yazılıdır:

> Satisa kapatma, o tarihlerde rezervasyonu olan odalarda yetkili onayi
> ister.

**Bu işlemin sonucu ciddidir:** seçtiğiniz tarih aralığında o odaya **yeni
rezervasyon alınamaz** ve oda doluluk hesabında satılabilir oda sayısından
düşülür. Yani doluluk oranınız ve RevPAR'ınız değişir.

O tarihlerde zaten rezervasyon varsa işlem durur. Yalnızca **"Kural
uyarılarını aşma"** yetkisi olan kullanıcıya şu soru sorulur:

> Yine de kapatmak icin onaylayin. Misafirin baska bir odaya alinmasi sizin
> sorumlulugunuzdadir; islem denetim gunlugune yazilir.

Bu kutuyu işaretlemek için ayrıca **"Odayı satışa kapatma"** yetkisi
gerekir; yoksa kutu kapalıdır.

> **Kısacası:** Odayı satışa kapatmak bir satış kaybıdır. Yalnızca oda
> gerçekten kullanılamaz durumdayken ve gerçekçi bir bitiş tarihiyle
> yapılmalıdır. İş bitince kaydı çözüp odayı yeniden satışa açmayı unutmayın.

### Liste ve süzgeçler

Liste varsayılan olarak **önceliğe göre azalan** sırada gelir — en acil kayıt
en üstte. Varsayılan süzgeç **"Yalnizca acik kayitlar"**tır; geçmişi görmek
için "Tümü" seçin.

Satışa kapalı bir odanın kaydında Arıza sütununda **`[SATISA KAPALI]`**
etiketi görünür.

Üstteki dört gösterge: **Açık Kayıt**, **Acil / Kritik**, **Satışa Kapalı
Oda**, **Toplam Maliyet** (işçilik + parça).

### Kaydı ilerletme

| Düğme | Ne yapar |
|---|---|
| **Ata** | Soldaki listeden seçilen teknisyene atar |
| **Çöz** | Çözüm notu, işçilik maliyeti ve kullanılan parçaların listesini ister |
| **Kaydı Kapat** | Yalnızca "çözüldü" durumundaki kaydı kapatır |

**Çöz** penceresinde parça satırları **Satır Ekle** ile eklenir (parça adı,
miktar, birim maliyet). Adı boş bırakılan satırlar sessizce atlanır.

Satışa kapalı bir oda için kayıt çözüldüğünde bildirim şunu ekler:
*"Oda temizlik icin acildi."*

Kaydı kapatırken onay istenir:

> Kapatilan kayit operasyon listesinden cikar; gecmiste gorunmeye devam
> eder.

---

## 9. Misafirler

Ekran ikiye bölünmüştür: solda arama ve liste, sağda seçili misafirin sekmeli
profili. Bu düzen bilinçlidir — resepsiyon görevlisi telefonda konuşurken hem
listeyi hem profili aynı anda görmek zorundadır.

### Liste

Ad, telefon, e-posta, VIP, konaklama sayısı ve son ziyaret sütunları vardır.
Ad, soyad, e-posta veya telefonla arama yapılır.

Dikkat gerektiren kayıtlar adın **önüne** yazılan bir işaretle belirtilir:

- `! KARA LISTE - Ad Soyad` → misafir kara listede
- `! Ad Soyad` → misafirde bir **uyarı notu** var

İşaret adın önündedir; böylece sütun dar olsa ve ad kırpılsa bile kritik bilgi
görünür kalır. Ada göre sıralandığında bu kayıtlar listenin başında toplanır —
resepsiyon için doğru davranış budur.

### Profil sekmeleri

**Genel** — e-posta, telefon, cep, doğum tarihi (yaşıyla birlikte), uyruk, dil
tercihi, adres, şehir/ülke, VIP seviyesi, kurumsal müşteri, acente ve
konaklama özeti (kaç konaklama, kaç gece, toplam ciro).

**Konaklamalar** — giriş tarihi, oda, gece, tutar ve durum.

**Tercih ve Not** — kayıtlı tercihler (kritik olanlar kırmızı **KRİTİK**
rozetiyle) ve personel notları. **Not Ekle** ile yeni not girilir; *"Uyari
notu"* kutusu işaretlenirse not vurgulanır ve misafir listede `!` ile
işaretlenir.

**KVKK** — açık rıza kayıtları.

### Kimlik numarası ve KVKK

Kimlik/pasaport numarası profilde **her zaman maskeli** durur. Yanındaki
**Göster** düğmesi yalnızca **"Kimlik numarasını açık görme"** yetkisi olan
kullanıcıda etkindir. Ekranda not olarak yazar:

> KVKK: Kimlik numarasi sifreli saklanir. Acik her goruntuleme kullanici adi
> ve zaman damgasiyla denetim gunlugune yazilir.

**Göster** düğmesine bastığınızda önce onay istenir:

> Kimlik numarasi acik olarak gosterilecek.
> Bu goruntuleme, kullanici adiniz ve zaman damgasiyla birlikte denetim
> gunlugune kaydedilir. Devam edilsin mi?

Onayladıktan sonra numara görünür ve *"Kimlik goruntulemesi denetim
gunlugune kaydedildi."* bildirimi çıkar.

> **Uygulamada dikkat edilecek:** Kimlik numarasını yalnızca gerçekten
> gerektiğinde (konaklama bildirimi, resmi talep) görüntüleyin. Her
> görüntüleme kalıcı bir kayıt bırakır ve denetimde size sorulabilir.

### KVKK izinleri

**İzin Kaydet** düğmesiyle izin türü, işlem (*İzin verildi* / *İzin geri
alındı*) ve kaynak (ör. *"giris formu"*, *"web sitesi"*, *"telefon"*) girilir.

> Izinler uzerine yazilmaz: her verme ve geri alma ayri bir satir olarak
> saklanir. Boylece hangi izin hangi tarihte alindi/geri alindi sorusu
> denetimde yanitlanabilir.
>
> Bu kayit silinemez ve degistirilemez; izin gecmisi KVKK denetiminde ispat
> niteligindedir.

### Kara liste

**Kara Listeye Al** düğmesi zorunlu bir gerekçe ister, sonra ayrıca onay
sorar. Kara listeye alınan misafir için yeni rezervasyonlarda uyarı çıkar ve
rezervasyon ancak yetkili onayıyla açılabilir. Çıkarma işlemi de denetim
günlüğüne yazılır.

---

## 10. Raporlar

Soldan rapor türünü, üstten tarih aralığını seçip **Raporu Oluştur** deyin.

### Hangi rapor ne zaman kullanılır?

| Rapor | Ne gösterir | Ne zaman kullanılır |
|---|---|---|
| **Doluluk** | Gün bazında toplam, arızalı, satılabilir, dolu oda ve doluluk % | Haftalık/aylık performans takibi, fiyat kararları |
| **Gelir (Kanal)** | Rezervasyon kanalına göre net, vergi ve toplam gelir | Acente/kanal komisyon değerlendirmesi |
| **Gelir (Oda Tipi)** | Oda tipine göre oda geliri ve diğer gelir | Hangi oda tipinin kazandırdığını görmek |
| **Gün Sonu Kapanış** | Seçilen günün geliri, tahsilatı ve kasa hareketleri | Her gün vardiya sonunda |
| **Giriş - Çıkış** | Seçilen günün girişleri, çıkışları, devam eden konaklamalar | Günlük operasyon planı |
| **Kat Hizmetleri** | Seçilen günün temizlik görevleri ve kontrol sonuçları | Kat performansı, iş yükü ölçümü |
| **Teknik Servis** | Dönem içinde bildirilen arıza ve bakım kayıtları | Bakım maliyeti ve tekrarlayan arıza analizi |
| **Stok** | Anlık stok durumu; kritik seviyedekiler en üstte | Sipariş öncesi |
| **KPI Özeti** | Dönemin doluluk, ADR, RevPAR, ALOS ve iptal göstergeleri | Aylık yönetim raporu, yatırımcı sunumu |

> **Mali raporlar** (Gelir, Gün Sonu, KPI Özeti) yalnızca **"Mali raporları
> görüntüleme"** yetkisi olan kullanıcının listesinde **görünür**. Yetkiniz
> yoksa bu satırlar hiç çıkmaz — tıklayınca hata veren bir seçenek göstermek
> yerine liste sadeleştirilmiştir. Aynı şekilde üstteki ADR ve RevPAR
> kartlarında `-` görürsünüz.

### Tarih aralığı

Hazır aralıklar: **Bugün · Son 7 Gün · Bu Ay · Geçen Ay · Son 90 Gün**.
Elle de girebilirsiniz.

> **Bitiş tarihi dahildir.** "1 Ağustos – 15 Ağustos" seçtiğinizde 15 Ağustos
> da rapora girer. Rapor başlığında dönem her zaman bu şekilde, kapsayıcı
> olarak yazar (ör. *"1 Agustos 2026 - 15 Agustos 2026 (15 gece)"*) ve dışa
> aktarılan dosyada da aynı metin görünür.

Tek gün isteyen raporlarda (Gün Sonu, Giriş-Çıkış, Kat Hizmetleri) **bitiş
tarihi alanı gizlenir**; yalnızca başlangıç tarihi kullanılır. Stok raporu
anlık durumu gösterir, tarihten etkilenmez.

### Üstteki göstergeler

Rapor türünden bağımsız olarak seçili dönemin **Doluluk, ADR, RevPAR, ALOS
ve İptal Oranı** göstergeleri üstte durur.

- **ALOS** = ortalama konaklama süresi (gece). Uzadıkça oda başına işletme
  maliyeti düşer; uzun konaklama tarifeleri planlanırken bu göstergeye
  bakılır.
- **İptal Oranı** kartının altında **gelmeme (no-show)** oranı da yazar.
  İkisi bilinçli olarak ayrı tutulur: iptal önceden bildirilir ve oda yeniden
  satılabilir, gelmemede ise oda o gece boş kalır.

### Rapor içinde arama

Sağ üstteki arama kutusu üretilmiş rapor tablosunda süzme yapar. Altta
`gösterilen / toplam satır (süzüldü)` bilgisi görünür.

### Dışa aktarma

Alt satırdaki **PDF**, **Excel** ve **CSV** düğmeleri raporu dosyaya yazar.
Dosya adı otomatik üretilir (ör. `doluluk-20260801-20260815.pdf`) ve dosya
her zaman programın **exports** klasörüne kaydedilir.

Kayıt sonrası bildirimde tam yol yazar; **Klasoru Ac** düğmesi o klasörü
Windows Gezgini'nde açar.

Dışa aktarma **"Rapor dışa aktarma"** yetkisi ister; yetkiniz yoksa düğmeler
kapalıdır. Her dışa aktarma denetim günlüğüne yazılır.

---

## 11. Yapay Zekâ Merkezi

### Ne yapar

Solda hazır görev düğmeleri vardır:

| Görev | Ne üretir |
|---|---|
| **Günlük Özet** | Bugünün panel verilerini yazıya döker |
| **Doluluk Analizi** | Son 30 günün doluluk eğilimini yorumlar |
| **Fiyat Önerisi** | Önümüzdeki 14 gün için fiyat **önerisi** üretir |
| **Mesaj Taslağı** | Aşağıya yazdığınız bağlamdan misafir mesajı taslağı yazar |
| **Yorum Analizi** | Yapıştırdığınız misafir yorumunu sınıflandırır |
| **Serbest Soru** | Girdi alanına yazdığınız soruyu yanıtlar |

### Ne YAPMAZ

- **Hiçbir veriyi kendiliğinden değiştirmez.** Rezervasyon açmaz, iptal
  etmez, fiyat güncellemez, folyoya ücret işlemez.
- **Fiyat önerisini uygulamaz.** Fiyat önerisi sonucunun üstünde şu uyarı
  zorunlu olarak gösterilir:

  > Bu bir öneridir. Uygulamak için Fiyatlar ekranından onaylamanız gerekir.

  Bu ekranda fiyatı değiştiren **hiçbir düğme yoktur**.
- **Misafirin kişisel bilgilerini dışarı göndermez.** Yazdığınız metindeki
  e-posta adresleri, telefon numaraları ve uzun numara dizileri (kimlik, kart
  vb.) modele gönderilmeden önce otomatik olarak `[e-posta gizlendi]`,
  `[telefon gizlendi]`, `[numara gizlendi]` ile değiştirilir. Bir şey
  gözden kaçarsa istek hiç gönderilmez ve şu hatayı alırsınız:

  > Yapay zeka isteği kişisel veri içerdiği için gönderilmedi.

### "AI tarafından oluşturuldu" rozeti

Yapay zekânın ürettiği **her** içeriğin yanında bu rozet bulunur. Rozetin
üzerine geldiğinizde şu not çıkar:

> Yapay zeka ciktilari hata icerebilir. Kritik kararlarda dogrulayin.

Kopyaladığınız metinlerin sonuna da şu satır eklenir:

> Bu metin yapay zeka tarafından oluşturulmuştur.

**Rozetin anlamı şudur:** o metin bir insan tarafından değil, bir dil modeli
tarafından yazılmıştır. Model akıcı ama yanlış cümleler kurabilir; sayıları
karıştırabilir. Misafire gönderilecek bir mesajı, yönetime sunulacak bir
özeti veya bir fiyat kararını **göndermeden/uygulamadan önce mutlaka
okuyun ve rakamları kaynağından (Raporlar ekranı) doğrulayın.**

### Bağlantı ve model seçimi

Üst satırda sağlayıcı, model ve bir durum rozeti (*Kontrol edilmedi*,
*Kontrol ediliyor...*, bağlantı başarılı/başarısız) vardır. **Baglantiyi Test
Et** düğmesi anlık kontrol yapar.

Yapay zekâ kapalıysa ekran bunu söyler ve çözümü yazar:

> Ayarlar > Yapay Zeka ekranından yapay zekayı etkinleştirin; yerel kullanım
> için LM Studio sunucusunu başlatın.

### Bekleme ve iptal

Yerel bir model 10–60 saniye sürebilir; bu sırada bir ilerleme çubuğu ve
**Iptal** düğmesi görünür. Program donmaz, başka ekrana geçebilirsiniz.

> **İptal düğmesi ne yapar, ne yapmaz:** Ekranı hemen serbest bırakır ve
> gelen yanıtı yok sayar. Ancak sunucuya gönderilmiş bir isteği dışarıdan
> durdurmak mümkün değildir; model üretmeye devam eder ve kullanım kaydı
> yazılır. Ücretli bir sağlayıcı kullanıyorsanız iptal ettiğiniz istek yine
> de maliyet oluşturabilir.

Kurulum ve model seçimi için: [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md).

---

## 12. Klavye kısayolları

| Kısayol | İşlev |
|---|---|
| **F5** | Açık ekranı yeniler ("Veriler yenilendi." bildirimi çıkar) |
| **Ctrl+Q** | Programı kapatır |
| **Ctrl+1** | Yönetim Paneli |
| **Ctrl+2** | Rezervasyonlar |
| **Ctrl+3** | Ön Büro |
| **Ctrl+4** | Odalar |
| **Ctrl+5** | Misafirler |
| **Ctrl+R** | Raporlar |
| **Enter** | Giriş ekranında girişi tamamlar; misafir arama kutusunda aramayı başlatır |
| **Esc** | Açık pencereyi kapatır (zorunlu parola değişimi hariç) |
| **Çift tıklama** | Listede satırın ana işlemini açar (rezervasyon ayrıntısı, giriş penceresi, folyo…) |
| **Sağ tık** | Oda planında oda durumu menüsünü açar |

Kat Hizmetleri, Teknik Servis, Yapay Zekâ Merkezi ve Ayarlar ekranlarının
klavye kısayolu **yoktur**; sol menüden açılırlar.

> **Not:** Yapay Zekâ Merkezi'ndeki yazı alanında *"Ctrl+Enter: gonder"*
> ipucu görünür, ancak bu kısayol şu an **çalışmamaktadır**. Mesajı göndermek
> için **Gonder** düğmesini kullanın.

---

## 13. Roller ve yetkiler

Sistemde **72 izin** ve **7 hazır rol** tanımlıdır. Bir kullanıcıya birden çok
rol verilebilir; yetkiler birleşir.

> **Bu sürümde kullanıcı ve rol yönetimi ekranı henüz yoktur.** Yeni kullanıcı
> açma ve rol atama işlemleri arayüzden yapılamaz; sistem sorumlusunun
> müdahalesini gerektirir. Aşağıdaki tablo, hazır rollerin **hangi işlemleri
> kapsadığını** anlatır.

| Rol | Kim kullanır | Neler yapabilir | Neler **yapamaz** |
|---|---|---|---|
| **Sistem Yöneticisi** (`admin`) | Sistem sorumlusu | Her şey (72 izin) | — |
| **Otel Müdürü** (`manager`) | Otel müdürü | Tüm operasyon, mali raporlar, ayarlar, kimlik görüntüleme, kural aşma, oda blokeleme, denetim günlüğü (64 izin) | Kullanıcı/rol yönetimi, yedekleme–geri yükleme, AI Geliştirme Merkezi |
| **Ön Büro Görevlisi** (`frontdesk`) | Resepsiyon | Rezervasyon oluşturma/düzenleme/iptal, giriş–çıkış, folyoya ücret işleme, tahsilat, misafir kaydı, oda durumu değiştirme, arıza bildirme, rapor görüntüleme (24 izin) | Ücret geçersiz kılma, iade, indirim, **erken giriş / geç çıkış ücreti**, mali raporlar, kimlik numarasını açık görme, oda blokeleme, kara liste |
| **Kat Hizmetleri** (`housekeeping`) | Kat şefi ve görevlileri | Görev atama, başlatma, tamamlama, temizlik kontrolü, oda durumu değiştirme, kayıp eşya, arıza bildirme, stok hareketi (14 izin) | Rezervasyon/folyo işlemleri, raporlar |
| **Teknik Servis** (`maintenance`) | Teknik ekip | Arıza kaydı açma/atama/çözme, **odayı satışa kapatma**, oda durumu değiştirme, stok hareketi, satın alma talebi (13 izin) | Rezervasyon, folyo, tahsilat, raporlar |
| **Muhasebe** (`accounting`) | Muhasebe | Folyo, ücret işleme, **geçersiz kılma**, indirim, tahsilat, **iade**, fatura, gelir–gider, gün sonu kapanışı, **mali raporlar ve dışa aktarma**, satın alma onayı (22 izin) | Rezervasyon oluşturma, giriş–çıkış, oda ve kat işlemleri |
| **Görüntüleyici** (`viewer`) | Denetçi, stajyer, sahibi | Yalnızca okuma: panel, oda, fiyat, rezervasyon, misafir, folyo, kat hizmetleri, teknik servis, stok, raporlar (11 izin) | Hiçbir kayıt değiştiremez |

### Nasıl anlarım yetkim var mı?

Üç işaret vardır:

1. **Ekran sol menüde yoksa** o ekrana hiç yetkiniz yoktur.
2. **Düğme kapalıysa** fareyi üzerinde bekletin; nedeni yazar
   (ör. *"Bu islem icin 'Odeme alma' yetkisi gerekiyor. Yoneticinize
   basvurun."*).
3. **İşlem sırasında** şu ileti çıkarsa yetkiniz yok demektir:
   *"Bu islem icin yetkiniz bulunmuyor."*

> Yetkisi olmayan düğmeler **gizlenmez, kapatılır**. Böylece o işlemin var
> olduğunu ama sizin yapamayacağınızı görebilirsiniz.

Yetki denetimi yalnızca ekranda değil, **kaydı yazan katmanda da** yapılır.
Yani bir düğmenin kapalı olması tek başına güvenlik önlemi değildir; işlem
sunucu tarafında ikinci kez denetlenir.

---

## 14. Sık sorulanlar

**Parolamı unuttum, ne yapmalıyım?**
Sistem sorumlunuza başvurun. **Bu sürümde programın içinde parola sıfırlayan
bir ekran yoktur**; sistem sorumlusunun sunucudaki komut satırından size yeni
bir hesap açması gerekir. Yordam
[INSTALLATION_WINDOWS.md](INSTALLATION_WINDOWS.md) → "Yönetici parolası
kaybolduğunda" bölümünde anlatılmıştır.

**Yanlış ücret işledim, silebilir miyim?**
Hayır — ve bu bilinçlidir. Folyodaki ücretler **silinmez**, gerekçe yazılarak
**geçersiz kılınır**. Satır üstü çizili olarak listede kalır ve toplama dahil
edilmez. Bu işlem "Ücret geçersiz kılma" yetkisi ister (muhasebe, müdür,
yönetici).

**Misafir çıkarken parasını ödemedi, çıkışı nasıl yaparım?**
Önce tahsilat yapmayı deneyin. Mümkün değilse çıkış penceresindeki **"Kalan
bakiyeyi cari hesaba devret"** kutusunu kullanın — bu kutu yalnızca finans
yetkisi olan kullanıcılarda açıktır ve işlem denetim günlüğüne yazılır.

**Misafir bugün çıktı, odayı bugün yeniden satabilir miyim?**
Evet. Çıkış günü konaklamaya dahil değildir; oda o gece yeni bir misafire
satılabilir. Sistem buna izin verir, çakışma uyarısı vermez.

**Oda kirli ama misafir bekliyor, giriş yapabilir miyim?**
Evet, ancak bilinçli bir onayla. Giriş penceresinde beliren uyarıyı okuyup
onay kutusunu işaretlemeniz gerekir. Kat hizmetlerini bilgilendirmeniz
önerilir.

**Doluluk oranı panelde ve raporda neden farklı çıkıyor?**
Paydası farklıdır. Panel, hem "Servis Dışı" hem "Arızalı" odaları satılabilir
oda sayısından düşer; rapor yalnızca "Arızalı" odaları düşer. Ayrıca panel
**bugünü**, rapor **seçtiğiniz dönemi** gösterir.

**ADR neden beklediğimden düşük çıkıyor?**
ADR yalnızca **oda gelirini** sayar. Restoran, SPA, minibar gibi gelirler
dahil değildir. Toplam geliri görmek için Raporlar > Gelir raporlarına bakın.

**İptal ücreti hesaplandı, misafirden nasıl tahsil ederim?**
Program ücreti hesaplar ve size gösterir ancak folyoya otomatik işlemez.
Tahsil edilecekse ilgili tutarı folyoya elle ekleyip tahsilat alın.

**Rezervasyonu iptal ettim, oda serbest kaldı mı?**
Evet. İptal ve "Gelmedi" işlemleri rezervasyonun tüm oda satırlarını iptal
eder ve odalar yeniden satılabilir hâle gelir.

**Bir arkadaşımda olan menü bende yok, program bozuk mu?**
Hayır. Sol menüde yalnızca yetkiniz olan ekranlar görünür. Yetki değişikliği
için sistem sorumlunuza başvurun.

**Finans ve Stok ekranlarını açtım, boş görünüyor.**
Bu ekranlar henüz tamamlanmadı. Ekranda ne planlandığı ve aynı işi şu an nasıl
yapabileceğiniz yazılıdır (tahsilat → Ön Büro, mali özet ve stok → Raporlar).

**Fatura kesebiliyor muyum? e-Fatura gönderiliyor mu?**
**Hayır.** e-Fatura, e-Arşiv ve Kimlik Bildirim Sistemi (KBS) entegrasyonları
**tamamlanmamıştır** ve varsayılan olarak kapalıdır. Bu yükümlülükleri şu an
mevcut yöntemlerinizle yerine getirmeye devam etmelisiniz. Ayrıntı:
[ROADMAP.md](ROADMAP.md).

**Yapay zekânın verdiği rakama güvenebilir miyim?**
Doğrulamadan güvenmeyin. Her yapay zekâ çıktısı "AI tarafından oluşturuldu"
rozetiyle işaretlidir ve hata içerebilir. Rakamları Raporlar ekranından teyit
edin.

**Verilerim yedekleniyor mu?**
Otomatik değil. Yedek almak için **Ayarlar > Yedekleme** sekmesindeki **Yedek
Al** düğmesini kullanın (bu işlem "Yedek alma" yetkisi ister) ya da sistem
sorumlunuzdan düzenli yedek almasını isteyin. Ayrıntı:
[INSTALLATION_WINDOWS.md](INSTALLATION_WINDOWS.md) → Yedekleme bölümü.

**Yaptığım işlemler kayıt altında mı?**
Evet. Giriş–çıkış, iptal, ücret geçersiz kılma, kimlik görüntüleme, kara
liste, oda blokeleme ve rapor dışa aktarma gibi kritik işlemler kullanıcı adı
ve zaman damgasıyla **denetim günlüğüne** yazılır.

---

## İlgili belgeler

| Belge | İçerik |
|---|---|
| [INSTALLATION_WINDOWS.md](INSTALLATION_WINDOWS.md) | Kurulum, güncelleme, yedekleme, kaldırma |
| [LM_STUDIO_SETUP.md](LM_STUDIO_SETUP.md) | Yerel yapay zekâ kurulumu |
| [ROADMAP.md](ROADMAP.md) | Henüz yapılmamış modüller |
| [../SECURITY.md](../SECURITY.md) | Güvenlik politikası |
| [../README.md](../README.md) | Genel bakış |
