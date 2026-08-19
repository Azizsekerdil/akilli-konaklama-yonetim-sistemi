# GitHub Acik Kaynak Arastirmasi ve Lisans Analizi

> **Amac:** Bu belge, Akilli Konaklama Yonetim Sistemi gelistirilirken sektordeki
> acik kaynak otel yonetimi / PMS / rezervasyon projelerinin taranmasini,
> lisanslarinin **gercek dosya icerigi uzerinden** dogrulanmasini ve hangi
> **kavramsal** yaklasimlarin ilham kaynagi oldugunu kayit altina alir.
>
> **Onemli:** Bu projede hicbir ucuncu parti deponun kaynak kodu kopyalanmamis,
> uyarlanmamis veya turetilmemistir. Ayrintili gerekce icin
> [Bolum 4 - Sonuc](#4-sonuc) bolumune bakiniz.

- **Arastirma tarihi:** 2026-08-15
- **Incelenen depo sayisi:** 19 (14 ayrintili kart + 5 kisa degerlendirme)
- **Hazirlayan:** proje ekibi

---

## Yontem ve dogrulama notu

Verilerin nasil toplandigi, okurun her satiri kendi basina dogrulayabilmesi icin
acikca yazilmistir:

| Alan | Kaynak | Guvenilirlik |
|---|---|---|
| Yildiz / catallama (fork) sayisi | GitHub REST API `GET /repos/{owner}/{repo}` -> `stargazers_count`, `forks_count` | Dogrulandi (anlik deger) |
| Son guncelleme | Ayni cagri -> `pushed_at` (son commit itmesi) | Dogrulandi |
| Arsiv durumu | Ayni cagri -> `archived` | Dogrulandi |
| Katkici sayisi | `GET /repos/{owner}/{repo}/contributors?per_page=100` dizi uzunlugu | Yalnizca tek sayfaya sigan depolar icin dogrulandi; digerleri "dogrulanamadi" |
| **Lisans** | **`GET /repos/{owner}/{repo}/license` ile LICENSE dosyasinin GERCEK icerigi cozulup okundu; ayrica `raw.githubusercontent.com` uzerinden ham dosya cekildi** | Dogrulandi |
| Kod organizasyonu / test varligi | `GET /repos/{owner}/{repo}/contents/` kok dizin listesi | Dogrulandi (yalnizca kok dizin duzeyinde) |
| Ozellik listesi | Deponun kendi README dosyasi | Deponun **iddiasi**; calistirilarak dogrulanmadi |

### Neden lisans etiketine degil, dosya icerigine bakildi

GitHub arayuzundeki lisans rozeti, `licensee` adli bir siniflandiricinin
tahminidir ve **baglayici degildir**. Bu arastirmada iki somut yanilticilik
ornegi bulundu:

1. `franknyarkoh/bookings` ve `ahmadpak/havenir_hotel_erpnext` depolarinda
   `license.txt` dosyasinin **tum icerigi tek satirdan** ibaret:
   `License: MIT`. Bu, MIT lisansinin kendisi degildir - lisans metninin
   sartlari ve sorumluluk reddi hic yok. GitHub bu dosyayi siniflandiramadigi
   icin `NOASSERTION` / "Other" dondurmektedir.
2. `OCA/vertical-hotel` deposunun kok LICENSE dosyasi AGPL-3.0'dir, fakat OCA
   politikasi geregi **her Odoo modulunun kendi lisansi olabilir**. Bu yuzden
   modul duzeyindeki `__manifest__.py` icindeki `license` anahtari da ayrica
   kontrol edildi (`hotel` modulu: `"AGPL-3"` - kok lisansla ayni).

### Dogrulanamayan alanlar

Katkici sayilari, kod satiri sayilari, gercek uretim kullanimi ve "test var mi"
sorusunun derinligi (kok dizinde `tests/` klasoru gormek, testlerin anlamli
oldugunu kanitlamaz) tam olarak dogrulanamamistir. Bu alanlar acikca
**"dogrulanamadi"** olarak isaretlenmistir. Hicbir sayisal deger tahmin
edilmemistir.

---

## Ozet tablo

Butun degerler 2026-08-15 tarihindeki anlik durumdur.

| # | Depo | Teknoloji | Son itme | Yildiz | Fork | Arsiv | LICENSE dosyasindan dogrulanan lisans |
|---:|---|---|---|---:|---:|---|---|
| 1 | [OCA/vertical-hotel](https://github.com/OCA/vertical-hotel) | Odoo (Python), PostgreSQL | 2026-07-22 | 155 | 278 | Hayir | **AGPL-3.0** |
| 2 | [frappe/hospitality](https://github.com/frappe/hospitality) | Frappe/ERPNext, MariaDB | 2023-02-16 | 72 | 112 | **Evet** | **GPL-3.0** |
| 3 | [Gifted87/erpnext_hospitality_core](https://github.com/Gifted87/erpnext_hospitality_core) | Frappe/ERPNext, MariaDB | 2026-07-12 | 19 | 32 | Hayir | **GPL-2.0** |
| 4 | [Just-Moh-it/HotinGo](https://github.com/Just-Moh-it/HotinGo) | Tkinter + MySQL | 2023-10-20 | 244 | 72 | **Evet** | MIT |
| 5 | [ranxi2001/Hotel-information-management-system](https://github.com/ranxi2001/Hotel-information-management-system) | PyQt5 + MySQL 8 | 2026-06-17 | 129 | 14 | Hayir | MIT |
| 6 | [okanuregen/Django---Hotel-Management-System](https://github.com/okanuregen/Django---Hotel-Management-System) | Django | 2021-03-07 | 90 | 59 | Hayir | **LISANS DOSYASI YOK** |
| 7 | [JonnyS1226/Hotel-management](https://github.com/JonnyS1226/Hotel-management) | PyQt5 + MySQL | 2021-11-02 | 59 | 7 | Hayir | **LISANS DOSYASI YOK** |
| 8 | [franknyarkoh/bookings](https://github.com/franknyarkoh/bookings) | Frappe/ERPNext | 2021-03-29 | 59 | 55 | Hayir | **Belirsiz** (tek satir: `License: MIT`) |
| 9 | [ahmadpak/havenir_hotel_erpnext](https://github.com/ahmadpak/havenir_hotel_erpnext) | Frappe/ERPNext | 2021-09-14 | 30 | 45 | Hayir | **Belirsiz** (tek satir: `License: MIT`) |
| 10 | [amadeus4dev/amadeus-hotel-booking-django](https://github.com/amadeus4dev/amadeus-hotel-booking-django) | Django + Amadeus API | 2026-01-29 | 29 | 21 | **Evet** | MIT |
| 11 | [Kamva-Ntlanga/hospitality-management-system](https://github.com/Kamva-Ntlanga/hospitality-management-system) | FastAPI, bellek ici depo | 2026-06-07 | 20 | 20 | Hayir | MIT |
| 12 | [immodded/hotelhub](https://github.com/immodded/hotelhub) | Django | 2025-12-01 | 19 | 7 | Hayir | MIT |
| 13 | [shiningflash/django-reservation-system](https://github.com/shiningflash/django-reservation-system) | Django + DRF + PostgreSQL | 2024-12-11 | 8 | 0 | Hayir | MIT |
| 14 | [XuanShine/PyPMS](https://github.com/XuanShine/PyPMS) | Django + CLI | 2019-01-30 | 4 | 0 | Hayir | **LISANS DOSYASI YOK** |
| 15 | [anisbhsl/Hotel-Management-System](https://github.com/anisbhsl/Hotel-Management-System) | Django | 2018-03-09 | 46 | 40 | **Evet** | **LISANS DOSYASI YOK** |
| 16 | [rajatrawal/hotel-booking-logic-django](https://github.com/rajatrawal/hotel-booking-logic-django) | Django | 2023-10-31 | 5 | 4 | Hayir | **LISANS DOSYASI YOK** |
| 17 | [guduchango/fastapi-booking](https://github.com/guduchango/fastapi-booking) | FastAPI + PostgreSQL + Redis | 2025-04-14 | 3 | 0 | Hayir | **LISANS DOSYASI YOK** |
| 18 | [SrinithiSaiprasath/Hotel-Management-System](https://github.com/SrinithiSaiprasath/Hotel-Management-System) | Tkinter + SQL | 2023-12-24 | 2 | 4 | Hayir | **LISANS DOSYASI YOK** |
| 19 | [julianrametta/fastapi_design](https://github.com/julianrametta/fastapi_design) | FastAPI + SQLAlchemy + SQLite | 2023-01-21 | 0 | 0 | Hayir | **LISANS DOSYASI YOK** |

**Cikarim:** Incelenen 19 deponun **8'inde hic lisans dosyasi yok**, 2'sinde
lisans dosyasi gecerli bir lisans metni degil, 3'u guclu copyleft (AGPL/GPL).
Yalnizca 6 depo net ve izin veren (MIT) lisansa sahip. Bu, alanin genel
tablosudur ve "acik kaynak" kelimesinin tek basina kullanim hakki vermedigini
gosterir.

---

## Ayrintili inceleme kartlari

### 1. OCA/vertical-hotel

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/OCA/vertical-hotel |
| **Teknoloji** | Odoo (Python 3), PostgreSQL, Odoo web arayuzu (XML gorunumler + OWL) |
| **Son guncelleme** | 2026-07 (`pushed_at` 2026-07-22); depo 2014-06'da acilmis |
| **Yildiz / Fork** | 155 / 278 |
| **Katkici** | 30 (tek sayfada listelenen; toplam daha fazla olabilir) |
| **Varsayilan dal** | `18.0` (Odoo surumu basina ayri dal) |
| **Temel ozellikler** | 14.0 dalinda moduller: `hotel` (folio ve otel yapilandirmasi), `hotel_reservation`, `hotel_housekeeping`, `hotel_restaurant`, `report_hotel_reservation`, `report_hotel_restaurant`. 18.0 dalinda su an yalnizca `hotel` modulu tasinmis durumda. |
| **Kod organizasyonu** | Odoo modul mimarisi: her modul `models/`, `views/`, `security/`, `report/`, `wizard/`, `data/`, `demo/`, `i18n/` alt dizinlerine ayrilmis. `hotel/models/` icinde `hotel_folio.py`, `hotel_room.py`, `hotel_services.py`, `account_move.py`, `res_company.py`, `product_product.py`. Katmanli degil, **cerceve-guduml** (framework-driven) yapi; is mantigi ORM modellerinin icindedir. |
| **Test** | `hotel` modulu (14.0) altinda `tests/` dizini **yok**. Depo genelinde `.pre-commit-config.yaml`, `.ruff.toml`, `.pylintrc` ve OCA CI yapilandirmasi var. |
| **LICENSE dosyasi (dogrulandi)** | Kok `LICENSE` dosyasinin ilk satirlari: `GNU AFFERO GENERAL PUBLIC LICENSE` / `Version 3, 19 November 2007`. Ayrica `hotel/__manifest__.py` icindeki `"license": "AGPL-3"` degeri kontrol edildi - kok lisansla tutarli. |
| **Ticari kullanim / degistirme** | Ticari kullanim serbest, **ancak AGPL-3.0**: turetilmis eser dagitilirsa kaynak kod ayni lisansla acilmak zorundadir ve **ag uzerinden hizmet verilmesi bile (Bolum 13) kaynak kodu acma yukumlulugu dogurur**. Kapali kaynak bir PMS icin kabul edilemez. |
| **Guvenlik / bakim** | Aktif bakimda (OCA kurumsal topluluk yapisi, dal basina surum politikasi, pre-commit + CI). Bakim durumu bu listedeki en iyi ornek. |
| **Alinabilecek FIKIRLER** | (a) **Folio** kavraminin merkezi olmasi: konaklama boyunca olusan tum yuklerin toplandigi bir "hesap dosyasi". (b) Otel isleyisinin ayri is alanlarina (rezervasyon / kat hizmetleri / restoran / raporlama) bolunmesi. (c) Odoo modul manifestosunun bagimlilik grafi ile ozellik acip kapatma fikri. |
| **Kullanilmamasi gereken bolumler** | **Hicbir satiri.** AGPL-3.0 lisansli kod, MIT lisansli bu projeye hicbir sekilde alinamaz - dosya, snippet, sema DDL veya cevrilmis kod olarak dahi. Odoo'ya ozgu ORM desenleri (`_inherit`, `api.depends`) zaten SQLAlchemy'ye tasinabilir nitelikte degildir. |

---

### 2. frappe/hospitality

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/frappe/hospitality |
| **Teknoloji** | Frappe Framework (Python), MariaDB, Frappe Desk arayuzu |
| **Son guncelleme** | 2023-02 (`pushed_at` 2023-02-16); README'ye gore depo 2023-10-04'te arsivlenmis |
| **Yildiz / Fork** | 72 / 112 |
| **Katkici** | 14 |
| **Temel ozellikler** | Iki alan: restoran (menu, masa, rezervasyon, siparis girisi, faturalama) ve otel (oda tanimi, rezervasyon, rezervasyondan fatura uretimi). |
| **Kod organizasyonu** | Frappe "app" yapisi: DocType tabanli. Her varlik bir DocType JSON semasi + denetleyici Python sinifi. Katmanli mimari yok; sema, arayuz ve is mantigi ayni DocType tanimindan turer. |
| **Test** | Dogrulanamadi (kok dizin listesi ayrica alinmadi; Frappe uygulamalarinda testler DocType klasorlerinin icine gomulur). |
| **LICENSE dosyasi (dogrulandi)** | `license.txt` ilk satirlari: `GNU GENERAL PUBLIC LICENSE` / `Version 3, 29 June 2007`. |
| **Ticari kullanim / degistirme** | Ticari kullanim serbest, fakat **GPL-3.0**: dagitilan turetilmis eserin kaynagi acilmak zorunda. Ayrica calistigi Frappe/ERPNext platformunun kendisi de GPL-3.0'dir. |
| **Guvenlik / bakim** | **Arsivlenmis - salt okunur.** Guvenlik yamasi gelmeyecek. Uretimde kullanilmasi onerilmez. |
| **Alinabilecek FIKIRLER** | Otel ve restorani ayni "hospitality" catisinda toplayip yine de ayri modul olarak tutma karari. Bu, bizim `app/infrastructure/db/models/` altindaki alan bazli dosya bolunmesiyle ayni yonde bir fikirdir (kavramsal duzeyde). |
| **Kullanilmamasi gereken bolumler** | Tamami. GPL-3.0 kod alinamaz. Ayrica DocType JSON semalari, Frappe'nin kendi calisma zamanina bagimlidir; tasinmasi teknik olarak da anlamsizdir. |

---

### 3. Gifted87/erpnext_hospitality_core

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/Gifted87/erpnext_hospitality_core |
| **Teknoloji** | Frappe Framework (Python), ERPNext entegrasyonu, MariaDB |
| **Son guncelleme** | 2026-07 (`pushed_at` 2026-07-12); depo 2025-12'de acilmis |
| **Yildiz / Fork** | 19 / 32 |
| **Katkici** | 3 |
| **Temel ozellikler** | README iddiasi: Guest Folio (konaklamanin ana hesabi) ve Folio Transaction; tarih araligina bagli `Room Rate Plan` (mevsimsel / hafta sonu fiyatlandirma); renk kodlu kat hizmetleri panosu; **gece denetimi (night audit)** motoru - gunluk oda ucretini otomatik isler ve gec cikislari yonetir. README acikca "kanal yoneticisi (channel manager) yoktur, PMS ERP'nin kendisidir" der. |
| **Kod organizasyonu** | Frappe app (`hospitality_core/` paketi). Kok dizinde `check_night_audit.py`, `debug_autoprint.py`, `debug_counts.py`, `debug_pop.py`, `diag_eod.py`, `verify_folio_balance.py`, `fix_workspace.py` gibi **cok sayida ad-hoc hata ayiklama betigi** depoya birakilmis. |
| **Test** | Ayri bir `tests/` dizini **yok**. `run_test_pos.py`, `test_autoprint.sh` gibi elle calistirilan betikler var; otomatik test kosumu dogrulanamadi. |
| **LICENSE dosyasi (dogrulandi)** | `license.txt` ilk satirlari: `GNU GENERAL PUBLIC LICENSE` / `Version 2, June 1991` / `Copyright (C) 1989, 1991 Free Software Foundation, Inc.`. README de "GNU General Public License v2.0" der - tutarli. |
| **Ticari kullanim / degistirme** | **GPL-2.0**: ticari kullanim serbest, ancak dagitilan turetilmis eserin kaynagi GPL-2.0 ile acilmalidir. MIT projesiyle bagdasmaz. |
| **Guvenlik / bakim** | Genc ve aktif ama tek gelistirici agirlikli; kok dizinde uretim disi hata ayiklama betiklerinin bulunmasi olgunluk sinyali degildir. |
| **Alinabilecek FIKIRLER** | En degerli fikir kaynagi: (a) **Folio + Folio Transaction ayrimi** - basligin (folio) ve satirlarin (transaction) ayri varliklar olmasi. (b) **Gece denetimi**nin ayri ve zamanlanmis bir surec olmasi; oda ucretinin rezervasyon aninda degil, her gece ayri bir yuk (charge) satiri olarak islenmesi. (c) `Room Rate Plan`'in tarih araligi tasimasi - fiyatin odaya degil, plan+tarih ikilisine bagli olmasi. Bunlarin hepsi **sektor standardi** kavramlardir (asagiya bkz. Bolum 2). |
| **Kullanilmamasi gereken bolumler** | Kaynak kodunun tamami (GPL-2.0). Ayrica kok dizindeki hata ayiklama betikleri desen olarak da ornek alinmamalidir. |

---

### 4. Just-Moh-it/HotinGo

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/Just-Moh-it/HotinGo |
| **Teknoloji** | Python + Tkinter (masaustu GUI) + MySQL |
| **Son guncelleme** | 2023-10 (`pushed_at` 2023-10-20); depo 2020-10'da acilmis |
| **Yildiz / Fork** | 244 / 72 (bu aramadaki en cok yildizli Python otel projesi) |
| **Katkici** | 1 |
| **Temel ozellikler** | Oda rezervasyonu, musteri kaydi, faturalama iceren masaustu arayuz. Ozellikle arayuz gorselligiyle dikkat cekmis. |
| **Kod organizasyonu** | Yalin ama okunakli ayrim: `main.py` (giris), `controller.py` (is mantigi, ~7 KB), `config.py` (yapilandirma), `gui/` (arayuz), `sql/` (sema), `assets/`. `.env.example` dosyasi var - sirlarin depoya girmemesi icin dogru yaklasim. |
| **Test** | `tests/` dizini **yok**; otomatik test yok. |
| **LICENSE dosyasi (dogrulandi)** | Dosya adi `LICENSE.txt`. Icerik MIT lisans metni; ilk satir: `Copyright 2022 © Mohit & Anirudh Agarwal`, ardindan standart `Permission is hereby granted, free of charge...` paragrafi. GitHub etiketi MIT ile tutarli. |
| **Ticari kullanim / degistirme** | MIT: ticari kullanim, degistirme ve yeniden dagitim serbest. **Tek kosul:** telif bildirimi ve lisans metni turetilmis eserde korunmalidir. |
| **Guvenlik / bakim** | **Arsivlenmis - salt okunur.** Guvenlik duzeltmesi gelmeyecek. |
| **Alinabilecek FIKIRLER** | (a) `config.py` / `controller.py` / `gui/` uclu ayrimi - masaustu bir uygulamada bile arayuzun is mantigindan ayrilmasi gerektigi fikri (bizde `app/ui` -> `app/application` -> `app/domain` olarak cok daha kati uygulanir). (b) `.env.example` dosyasinin depoda, `.env` dosyasinin `.gitignore`'da olmasi. |
| **Kullanilmamasi gereken bolumler** | Tkinter'e ozgu arayuz kodu (bu proje PySide6 kullanir - tasinmaz). SQL sorgularinin dogrudan denetleyici icinde kurulmasi deseni; parametreli sorgu / ORM kullanimi tercih edilmelidir. Arsivlenmis oldugu icin guvenlik acisindan referans alinmamalidir. |

---

### 5. ranxi2001/Hotel-information-management-system

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/ranxi2001/Hotel-information-management-system |
| **Teknoloji** | Python + PyQt5 (masaustu) + MySQL 8.0.29 |
| **Son guncelleme** | 2026-06 (`pushed_at` 2026-06-17); depo 2022-07'de acilmis |
| **Yildiz / Fork** | 129 / 14 |
| **Katkici** | 1 |
| **Temel ozellikler** | Veritabani dersi proje odevi: oda, musteri, personel ve konaklama kayitlarinin CRUD yonetimi; deneyim raporu (Cince) ile birlikte. |
| **Kod organizasyonu** | `Main.py` (tek giris), `ui/` (Qt Designer ciktilari), `hotelManagement.sql` (sema), `references/`, `pictures/`. **Monolitik**: is mantigi arayuz dosyalarina gomulu, katman ayrimi yok. |
| **Test** | `tests/` dizini **yok**. |
| **LICENSE dosyasi (dogrulandi)** | Kok `LICENSE` dosyasi MIT metni; ilk satir `MIT License`, telif satiri `Copyright (c) 2022 ranxi169`. |
| **Ticari kullanim / degistirme** | MIT - serbest; telif bildirimi korunmali. |
| **Guvenlik / bakim** | Tek kisilik ders projesi. Son itme yeni gorunse de icerik akademik odev niteliginde; uretim guvenligi icin referans degildir. |
| **Alinabilecek FIKIRLER** | Bu projeyle **teknoloji ortakligi** acisindan ilginc (Python + Qt masaustu + iliskisel veritabani). Alinacak tek kavramsal fikir: masaustu PMS'te oda listesinin "izgara/plan" (grid) gorunumu, kullanicinin gunluk operasyonu tek ekrandan gormesi ihtiyaci. |
| **Kullanilmamasi gereken bolumler** | Mimarisinin tamami - is mantiginin Qt widget'larina gomulmesi, bu projenin `ui -> application -> domain` kuralinin tam tersidir. SQL semasi da MySQL'e ozgudur ve normalizasyon duzeyi dogrulanmamistir. |

---

### 6. okanuregen/Django---Hotel-Management-System

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/okanuregen/Django---Hotel-Management-System |
| **Teknoloji** | Django (Python) |
| **Son guncelleme** | 2021-03 (`pushed_at` 2021-03-07); depo 2021-02'de acilmis - toplam ~10 gunluk aktif gelistirme |
| **Yildiz / Fork** | 90 / 59 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | README iddiasi: "veritabani tablolari normalizasyon kurallarina gore olusturuldu". Otel yonetimi icin temel CRUD. |
| **Kod organizasyonu** | Kok dizin: `HMS/` (Django projesi), `Documents/`, `Screenshots/`, `README.md`, `.gitattributes`. Tek Django projesi; katman ayrimi dogrulanamadi. |
| **Test** | Kok dizinde `tests/` yok; Django app ici `tests.py` varligi dogrulanamadi. |
| **LICENSE dosyasi (dogrulandi)** | Kok dizin listesi cekildi: `.gitattributes`, `Documents`, `HMS`, `README.md`, `Screenshots`. **LICENSE / COPYING / LICENCE adinda hicbir dosya yok.** GitHub API `license` alani da `null`. |
| **Ticari kullanim / degistirme** | **YASAK.** Lisans belirtilmemis eserler varsayilan olarak "tum haklari sakli"dir (bkz. Bolum 1). Kopyalama, degistirme ve dagitim hakki verilmemistir. |
| **Guvenlik / bakim** | 2021'den beri guncellenmemis. Django surumu dogrulanamadi ama tarih itibariyle destegi bitmis bir surum olmasi kuvvetle muhtemeldir. |
| **Alinabilecek FIKIRLER** | README'nin "normalizasyon kurallarina gore tasarlandi" vurgusu disinda ayirt edici bir fikir bulunamadi. Bu proje zaten normalize, 60 tabloluk bir semaya sahiptir. |
| **Kullanilmamasi gereken bolumler** | **Tamami.** Lisanssiz oldugu icin tek satiri bile alinamaz; ayrica bakimsizdir. |

---

### 7. JonnyS1226/Hotel-management

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/JonnyS1226/Hotel-management |
| **Teknoloji** | Python 3.7 + PyQt5 + MySQL |
| **Son guncelleme** | 2021-11 (`pushed_at` 2021-11-02) |
| **Yildiz / Fork** | 59 / 7 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | Veritabani dersi projesi (Cince aciklama): oda ve musteri yonetimi, konaklama kayitlari. |
| **Kod organizasyonu** | Kok dizin: `HotelManagement/`, `hotelManagement.sql`, `README.md`, ekran goruntusu klasoru. Monolitik masaustu uygulama. |
| **Test** | `tests/` dizini **yok**. |
| **LICENSE dosyasi (dogrulandi)** | Kok dizin listesinde LICENSE/COPYING **yok**; GitHub API `license` alani `null`. |
| **Ticari kullanim / degistirme** | **YASAK** - lisanssiz, tum haklari sakli. |
| **Guvenlik / bakim** | 2021'den beri guncellenmemis; Python 3.7 destegi sona ermistir. |
| **Alinabilecek FIKIRLER** | Yok denecek kadar az. Ders odevi kapsaminda; ozgun bir is akisi veya veri modeli katkisi tespit edilmedi. |
| **Kullanilmamasi gereken bolumler** | Tamami (lisanssiz). |

---

### 8. franknyarkoh/bookings

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/franknyarkoh/bookings |
| **Teknoloji** | Frappe Framework / ERPNext uygulamasi (Python), MariaDB |
| **Son guncelleme** | 2021-03 (`pushed_at` 2021-03-29) |
| **Yildiz / Fork** | 59 / 55 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | README iddiasi: oda yonetimi, **mevsimsel fiyat (seasonal rates) yonetimi**, kat hizmetleri (housekeeping), rezervasyona ek hizmet/urun satisi (booking extras). |
| **Kod organizasyonu** | Frappe app; DocType tabanli. Katmanli mimari yok. |
| **Test** | Dogrulanamadi. |
| **LICENSE dosyasi (dogrulandi)** | **Bu deponun `license.txt` dosyasi cozuldu ve tum icerigi tek satirdir: `License: MIT`.** Bu, MIT lisans metni **degildir**; izinlerin kapsami, sart kosulan telif bildirimi ve garanti reddi yoktur. GitHub API bu nedenle `spdx_id: NOASSERTION`, `name: "Other"` dondurmektedir. |
| **Ticari kullanim / degistirme** | **Belirsiz - kullanilmamalidir.** Niyet MIT gorunse de gecerli bir lisans hibesi metni yoktur. Ayrica proje, GPL-3.0 lisansli Frappe/ERPNext uzerine kurulu bir uygulamadir; bu, "MIT" iddiasini hukuken daha da tartismali kilar. |
| **Guvenlik / bakim** | 2021'den beri guncellenmemis; dayandigi ERPNext surumu cok eskidir. |
| **Alinabilecek FIKIRLER** | (a) **Mevsimsel fiyat** kavraminin ayri bir varlik olmasi. (b) **Booking extras** - rezervasyona bagli ek satislarin (kahvalti, transfer, spa) rezervasyondan ayri satirlar olarak tutulmasi; bu, bizim `ChargeType` ve folio yuk satirlari yaklasimimizla ayni kavramsal aile icindedir. |
| **Kullanilmamasi gereken bolumler** | **Kodun tamami.** Lisans belirsizligi tek basina diskalifiye sebebidir. Bu depo, "GitHub etiketine guvenme, dosyayi ac" kuralinin somut kanitidir. |

---

### 9. ahmadpak/havenir_hotel_erpnext

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/ahmadpak/havenir_hotel_erpnext |
| **Teknoloji** | Frappe Framework / ERPNext uygulamasi (Python), MariaDB |
| **Son guncelleme** | 2021-09 (`pushed_at` 2021-09-14) |
| **Yildiz / Fork** | 30 / 45 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | ERPNext icin otel yonetimi uygulamasi; ayrintili ozellik listesi README uzerinden dogrulanmadi. |
| **Kod organizasyonu** | Frappe app; DocType tabanli. |
| **Test** | Dogrulanamadi. |
| **LICENSE dosyasi (dogrulandi)** | 8 numarayla **aynen ayni durum**: `license.txt` icerigi tek satir - `License: MIT`. GitHub `NOASSERTION` / "Other" dondurmektedir. |
| **Ticari kullanim / degistirme** | **Belirsiz - kullanilmamalidir.** |
| **Guvenlik / bakim** | 2021'den beri guncellenmemis. |
| **Alinabilecek FIKIRLER** | 8 numaradaki fikirlerin otesinde ayirt edici bir katki tespit edilmedi. |
| **Kullanilmamasi gereken bolumler** | Kodun tamami. |

---

### 10. amadeus4dev/amadeus-hotel-booking-django

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/amadeus4dev/amadeus-hotel-booking-django |
| **Teknoloji** | Django + Amadeus Self-Service REST API'leri; birincil dil GitHub'a gore HTML (sablon agirlikli) |
| **Son guncelleme** | 2026-01 (`pushed_at` 2026-01-29 - arsivleme islemi); depo 2020-02'de acilmis |
| **Yildiz / Fork** | 29 / 21 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | Otel arama ve rezervasyon "booking engine" **demosu**. Kendi envanterini tutmaz; dis GDS/toplayici API'sini tuketir. |
| **Kod organizasyonu** | Standart Django proje + sablonlar. Demo amacli, katmanli degil. |
| **Test** | Dogrulanamadi. |
| **LICENSE dosyasi (dogrulandi)** | Kok `LICENSE` dosyasi cozuldu; ilk satirlar: `The MIT License (MIT)` / `Copyright (c) 2017 Amadeus IT Group SA`. Kurumsal sahipli, gecerli MIT metni. |
| **Ticari kullanim / degistirme** | MIT - serbest; telif bildirimi korunmali. Ancak **kodun calismasi icin gereken Amadeus API'si ayri ticari sartlara tabidir**; lisansin izin vermesi, servisin ucretsiz oldugu anlamina gelmez. |
| **Guvenlik / bakim** | **Arsivlenmis - salt okunur.** Bagimliliklari eskimis durumda. |
| **Alinabilecek FIKIRLER** | (a) **Dis rezervasyon saglayicisinin arkasina bir soyutlama koyma** fikri: arama, teklif (offer) ve rezervasyon (booking) adimlarinin ayri islemler olmasi. Bu, ilerideki kanal yoneticisi / OTA entegrasyonu icin dogru sinirdir. (b) "Teklifin fiyati gecicidir, rezervasyon aninda yeniden dogrulanir" ilkesi. |
| **Kullanilmamasi gereken bolumler** | Django sablonlari ve gorunum kodu (bu proje PySide6 masaustu + FastAPI servis kullanir). Arsivlenmis bagimlilik surumleri hicbir sekilde ornek alinmamalidir. |

---

### 11. Kamva-Ntlanga/hospitality-management-system

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/Kamva-Ntlanga/hospitality-management-system |
| **Teknoloji** | FastAPI + Uvicorn; veri deposu **bellek ici** (gelecekteki veritabani icin yer tutucu siniflar); arayuz olarak otomatik uretilen Swagger UI / ReDoc |
| **Son guncelleme** | 2026-06 (`pushed_at` 2026-06-07); depo 2026-03'te acilmis |
| **Yildiz / Fork** | 20 / 20 |
| **Katkici** | 4 |
| **Temel ozellikler** | Oda yonetimi, misafir profilleri, rezervasyon isleme, odeme, kat hizmetleri koordinasyonu ve servis talepleri - tamami REST API olarak. |
| **Kod organizasyonu** | **Bu listedeki en acik katmanli yapi:** `src/` (alan siniflari), `services/` (is mantigi), `api/` (uc noktalar), `repositories/` (veri erisimi), `factories/` + `creational_patterns/` (nesne uretimi), `future_stubs/`. Ayrica `domain_model.md`, `class_diagram.md`, `state_transition_diagrams.md`, `repository_class_diagram.md` gibi tasarim belgeleri var. |
| **Test** | **Var** - kok dizinde `tests/` mevcut, `TEST_CASES.md` belgesi ve `.github/` altinda CI yapilandirmasi ile birlikte (ekran goruntuleri CI kosumunu belgelemis). |
| **LICENSE dosyasi (dogrulandi)** | Kok `LICENSE` cozuldu; ilk satirlar: `MIT License` / `Copyright (c) 2025 Kamva Ntlanga`. |
| **Ticari kullanim / degistirme** | MIT - serbest; telif bildirimi korunmali. |
| **Guvenlik / bakim** | Genc, aktif ama **acikca egitim amacli** (yazilim muhendisligi dersi odevi; `ASSIGNMENT*.md`, `REFLECTION_ASSIGNMENT*.md` dosyalari). Verinin bellek ici tutulmasi uretime uygun degildir. |
| **Alinabilecek FIKIRLER** | (a) **Depo (repository) katmaninin arayuz olarak tanimlanip is mantigindan ayrilmasi** - bu projede `app/infrastructure/db/repositories/base.py` ile ayni kavramsal cozum. (b) Rezervasyon icin **acik durum gecisi diyagrami** tutulmasi; bizde bu, `app/domain/rules/reservation_state.py` icinde calisir kod olarak yasar. (c) Tasarim belgelerinin depoda, kodun yaninda tutulmasi. |
| **Kullanilmamasi gereken bolumler** | Bellek ici depolama yaklasimi (kalicilik yok, es zamanlilik yok). "Creational patterns" klasorunun ders geregi zorlanmis desen kullanimi - gercek ihtiyac olmadan fabrika/singleton uretmek bu projede kacinilan bir seydir. |

---

### 12. immodded/hotelhub

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/immodded/hotelhub |
| **Teknoloji** | Django; veritabani README'de belirtilmemis (varsayilan `settings.py` uzerinden ayarlanir); duyarli (responsive) web arayuzu |
| **Son guncelleme** | 2025-12 (`pushed_at` 2025-12-01); depo 2023-11'de acilmis |
| **Yildiz / Fork** | 19 / 7 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | Kimlik dogrulama ve yetkilendirme, oda yonetimi (musaitlik ve doluluk takibi), giris/cikis (check-in / check-out) surecleri, misafir ve rezervasyon yonetimi. |
| **Kod organizasyonu** | Django app bazli ayrim: `accounts`, `guest`, `hotelmanagement`, `room`, `main`. Alan bazli bolunme acisindan makul; ancak Django'nun standart "fat model / view" yapisinin otesine gecen bir katmanlasma yok. |
| **Test** | README'de test cercevesi veya test dosyasi **belirtilmemis**; dogrulanamadi. |
| **LICENSE dosyasi (dogrulandi)** | Kok `LICENSE` cozuldu; ilk satirlar: `MIT License` / `Copyright (c) 2023 immodded`. |
| **Ticari kullanim / degistirme** | MIT - serbest; telif bildirimi korunmali. |
| **Guvenlik / bakim** | Toplam commit sayisi cok dusuk (README'ye gore 7 commit). Tek kisilik, dusuk hacimli proje. |
| **Alinabilecek FIKIRLER** | Kimlik/hesap (`accounts`) alaninin misafir (`guest`) alanindan **ayri tutulmasi**. Bu ayrim onemlidir: personel kullanicisi ile otelde kalan misafir farkli varliklardir, birlestirilmemelidir. Bu proje de ayni ayrimi `models/security.py` ve `models/guests.py` olarak uygular. |
| **Kullanilmamasi gereken bolumler** | Django'ya ozgu her sey. Ayrica veritabani secimi ve gocler belgelenmemis; ornek alinacak bir kalicilik stratejisi yok. |

---

### 13. shiningflash/django-reservation-system

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/shiningflash/django-reservation-system |
| **Teknoloji** | Django + Django REST Framework, PostgreSQL, Docker / Docker Compose, Swagger belgelendirmesi |
| **Son guncelleme** | 2024-12 (`pushed_at` 2024-12-11); depo 2021-09'da acilmis |
| **Yildiz / Fork** | 8 / 0 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | Dort alan: kullanici yonetimi (kayit, giris, parola degisimi), oda yonetimi, musteri yonetimi ve rezervasyon sistemi (gercek zamanli check-in / check-out) + odeme takibi. |
| **Kod organizasyonu** | `src/` (kaynak), `docs/` (belgeler), Docker dosyalari, `requirements`. REST uc noktalari alan bazli gruplanmis (admin / customer / room / booking / payment). Django standardinin uzerinde bir katmanlasma yok. |
| **Test** | **Var** - README `python3 manage.py test` komutunu belgeliyor (Docker konteyneri icinde). |
| **LICENSE dosyasi (dogrulandi)** | Kok `LICENSE` cozuldu; ilk satirlar: `MIT License` / `Copyright (c) 2024 Amirul Islam`. |
| **Ticari kullanim / degistirme** | MIT - serbest; telif bildirimi korunmali. |
| **Guvenlik / bakim** | Dusuk ilgi (8 yildiz, 0 fork) fakat Docker + Swagger + test kombinasyonu, listenin cogundan daha disiplinli. Son guncelleme 2024 sonu. |
| **Alinabilecek FIKIRLER** | (a) **Check-in / check-out'un rezervasyondan ayri bir durum gecisi** olarak modellenmesi - rezervasyon "onaylandi" ile "giris yapildi" ayni sey degildir. Bizde bu ayrim `ReservationStatus` ve `StayStatus` enumlari olarak zaten mevcuttur. (b) Odemenin rezervasyondan bagimsiz izlenmesi. (c) API belgelendirmesinin kodla birlikte uretilmesi. |
| **Kullanilmamasi gereken bolumler** | Django/DRF'e ozgu her sey. Ayrica "musteri" ve "kullanici"nin ayni REST alaninda karisik yonetilmesi; bu proje `guests` ile `security.users` arasinda daha kati bir sinir cizer. |

---

### 14. XuanShine/PyPMS

| Alan | Deger |
|---|---|
| **Adres** | https://github.com/XuanShine/PyPMS |
| **Teknoloji** | Django (kok dizinde `manage.py`, `webapp/`) + ayrica bir komut satiri arayuzu (`pms_cli.py`); SQLite (`db.sqlite3` depoya islenmis) |
| **Son guncelleme** | 2019-01 (`pushed_at` 2019-01-30) |
| **Yildiz / Fork** | 4 / 0 |
| **Katkici** | Dogrulanamadi |
| **Temel ozellikler** | Adi dogrudan "PMS for hotel" olan tek depo; ancak icerik terk edilmis bir taslak duzeyinde. `tmp.py` gibi gecici dosyalar depoda. |
| **Kod organizasyonu** | `PyPMS/` (cekirdek), `webapp/` (web katmani), `pms_cli.py` (CLI). **Cekirdek mantigi ile web arayuzunun ayrilmasi fikri dogru**, ancak uygulanmasi tamamlanmamis. |
| **Test** | `pytest.ini` dosyasi **var**, fakat kok dizinde `tests/` klasoru yok; test kapsami dogrulanamadi. |
| **LICENSE dosyasi (dogrulandi)** | Kok dizin listesi cekildi: `.gitignore`, `PyPMS`, `README.md`, `db.sqlite3`, `manage.py`, `pms_cli.py`, `pytest.ini`, `requirements.txt`, `setup.py`, `tmp.py`, `webapp`. **LICENSE/COPYING yok**; GitHub API `license` alani `null`. |
| **Ticari kullanim / degistirme** | **YASAK** - lisanssiz, tum haklari sakli. |
| **Guvenlik / bakim** | Terk edilmis (2019). Ayrica **`db.sqlite3` veritabani dosyasi depoya islenmis** - versiyon kontrolune veri koymak, gercek bir otelde KVKK acisindan agir bir hatadir. |
| **Alinabilecek FIKIRLER** | Tek degerli fikir: **cekirdek PMS mantiginin sunum katmanindan (web/CLI) bagimsiz bir paket olmasi**. Bu proje ayni fikri cok daha kati uygular (`app/domain` SQLAlchemy dahi import etmez). |
| **Kullanilmamasi gereken bolumler** | Tamami (lisanssiz + terk edilmis). Veritabani dosyasinin depoya islenmesi, acikca **kacinilmasi gereken** bir uygulamadir. |

---

## Kisa degerlendirilen depolar

Asagidakiler tarandi ancak ayrintili kart acilmasini hak edecek ozgun katki
tasimadigi icin ozetle gecilmistir.

| Depo | Neden ayrintili incelenmedi | Lisans (dosyadan dogrulandi) | Dikkat ceken nokta |
|---|---|---|---|
| [anisbhsl/Hotel-Management-System](https://github.com/anisbhsl/Hotel-Management-System) | 2018'den beri guncellenmemis, arsivlenmis | **Yok** (kok dizinde LICENSE/COPYING bulunamadi) | `db.sqlite3` depoya islenmis |
| [rajatrawal/hotel-booking-logic-django](https://github.com/rajatrawal/hotel-booking-logic-django) | Tek gunluk gelistirme (2023-10-30/31) | **Yok** | **`.env` dosyasi depoya islenmis** - sir sizintisi riski; ayrica `db.sqlite3` islenmis |
| [guduchango/fastapi-booking](https://github.com/guduchango/fastapi-booking) | 3 gunluk proje, 3 yildiz | **Yok** | Altyapi tarafi ilgi cekici: `tests/`, `pytest.ini`, Prometheus/Grafana, Locust yuk testi, OpenTelemetry toplayici yapilandirmasi. Lisanssiz oldugu icin kod olarak degil, yalnizca **gozlemlenebilirlik disiplini** acisindan not edildi. |
| [SrinithiSaiprasath/Hotel-Management-System](https://github.com/SrinithiSaiprasath/Hotel-Management-System) | Kok dizinde yalnizca `README.md` ve tek dosya `hotelamanagement.py` | **Yok** | Tek dosyalik Tkinter odevi |
| [julianrametta/fastapi_design](https://github.com/julianrametta/fastapi_design) | 0 yildiz, 2023'ten beri durgun | **Yok** | `src/` + `tests/` + Poetry + pre-commit ile duzenli iskelet; lisanssiz |

**Kapsam disi birakilan:** QloApps gibi tam ozellikli acik kaynak PMS'ler
**PHP** tabanli oldugu icin bu arastirmanin kapsami (Python) disinda tutulmustur;
ne kod ne de lisans incelemesi yapilmamistir.

---

## 1. Lisans siniflandirmasi

### 1.1 Izin veren (permissive) lisanslar - MIT / Apache-2.0 / BSD / Unlicense

Bu lisanslar kodun ticari urunlerde, kaynak kodu acmadan kullanilmasina izin
verir. Tipik tek yukumluluk **atif**tir: telif bildirimi ve lisans metni
turetilmis eserde korunmalidir. Apache-2.0 ayrica acik bir **patent hibesi**
ve degistirilen dosyalarin isaretlenmesi yukumlulugu getirir.

Bu arastirmada dogrulanan izin veren lisansli depolar:

| Depo | Lisans | Dogrulama |
|---|---|---|
| Just-Moh-it/HotinGo | MIT | `LICENSE.txt` - tam MIT metni, `Copyright 2022 © Mohit & Anirudh Agarwal` |
| ranxi2001/Hotel-information-management-system | MIT | `LICENSE` - tam MIT metni, `Copyright (c) 2022 ranxi169` |
| amadeus4dev/amadeus-hotel-booking-django | MIT | `LICENSE` - `The MIT License (MIT)`, `Copyright (c) 2017 Amadeus IT Group SA` |
| Kamva-Ntlanga/hospitality-management-system | MIT | `LICENSE` - tam MIT metni, `Copyright (c) 2025 Kamva Ntlanga` |
| immodded/hotelhub | MIT | `LICENSE` - tam MIT metni, `Copyright (c) 2023 immodded` |
| shiningflash/django-reservation-system | MIT | `LICENSE` - tam MIT metni, `Copyright (c) 2024 Amirul Islam` |

> Not: Bu depolardan **hicbirinin kodu** bu projeye alinmamistir. Lisansin izin
> vermesi, kod almanin dogru oldugu anlamina gelmez; teknoloji yiginlari
> (Tkinter, Django, PyQt5) bu projeyle uyusmaz ve alinacak kodun bakim yuku
> kazancindan buyuktur.

### 1.2 Kacinilmasi gerekenler - GPL / AGPL / LGPL / SSPL

| Aile | Bu arastirmadaki ornek | Neden bu projeye alinamaz |
|---|---|---|
| **AGPL-3.0** | OCA/vertical-hotel | En agir copyleft. Kodun bir turevi **ag uzerinden hizmet olarak sunulsa bile** (Bolum 13) kaynak kodun kullaniciya sunulmasi zorunludur. Bulut/kiralik PMS senaryosunda tum projeyi acmak gerekirdi. |
| **GPL-3.0** | frappe/hospitality | Turetilmis eserin tamami GPL-3.0 ile dagitilmak zorundadir. MIT ile birlestirilmis bir urun, butun olarak GPL-3.0 olur. |
| **GPL-2.0** | Gifted87/erpnext_hospitality_core | Ayni copyleft mantigi; ayrica GPL-2.0 ile Apache-2.0 arasinda bilinen patent maddesi uyumsuzlugu vardir. |
| **LGPL** | (Bu depo listesinde yok; ancak bagimlilik tarafinda **PySide6/Qt** LGPL-3.0'dir - bkz. `THIRD_PARTY_NOTICES.md`) | LGPL, **dinamik baglanma** ile kapali kaynak kullanima izin verir; fakat kutuphanenin degistirilmemesi ve kullanicinin kutuphaneyi degistirip yeniden baglayabilmesi sarti gecerlidir. Kaynak **kopyalamak** ise LGPL'i tetikler. |
| **SSPL** | (Bu listede yok) | OSI tarafindan acik kaynak sayilmaz. Hizmet olarak sunulmasi halinde tum yonetim/dagitim yigininin acilmasini ister. Ticari PMS icin uygun degildir. |

**Kural:** Copyleft lisansli bir depodan kod almak, bu projenin MIT lisansini
gecersiz kilar ve tum urunu o lisansa mahkum eder. Bu nedenle
**GPL/AGPL/LGPL/SSPL kaynakli hicbir kod bu projeye alinmamistir.**

### 1.3 Lisansi belirtilmemis depolar - neden "tum haklari sakli"

Incelenen 19 deponun **8'inde** hicbir lisans dosyasi yoktur:
`okanuregen/Django---Hotel-Management-System`, `JonnyS1226/Hotel-management`,
`XuanShine/PyPMS`, `anisbhsl/Hotel-Management-System`,
`rajatrawal/hotel-booking-logic-django`, `guduchango/fastapi-booking`,
`SrinithiSaiprasath/Hotel-Management-System`, `julianrametta/fastapi_design`.

Bu depolar **kullanilamaz.** Gerekce:

1. **Telif hakki dogustan ve otomatiktir.** Bern Sozlesmesi'ne taraf ulkelerde
   (Turkiye dahil) bir eser yaratildigi anda telif hakki dogar; tescil veya
   bildirim gerekmez. Yani kod, yazildigi anda korumalidir.
2. **Lisans, telif sahibinin verdigi izindir.** Lisans yoksa **izin de yoktur**.
   Varsayilan durum "her sey serbest" degil, tam tersi: **tum haklari sakli**
   (all rights reserved).
3. **Halka acik olmak izin degildir.** GitHub'da kodu gorunur kilmak,
   GitHub Kullanim Sartlari geregi yalnizca **goruntuleme ve depo catallama
   (fork)** hakki verir; kopyalama, degistirme, dagitma veya urune gomme hakki
   vermez. GitHub'in kendi belgeleri de lisanssiz depolar icin bunu acikca
   soyler.
4. **"Ders odevi", "kucuk proje" veya "kimse dava etmez" savunma degildir.**
   Gercek otellerde kullanilacak ticari bir urunde, kaynagi belirsiz kod
   tasimak kabul edilemez bir hukuki risktir.
5. **Belirsiz lisans metni de lisanssizlikla ayni sonucu verir.** Yukarida
   8 ve 9 numarali depolarda gorulen tek satirlik `License: MIT` dosyasi,
   hangi haklarin hangi kosullarla verildigini tanimlamaz. Sozlesme
   olusturmadigi icin **guvenilemez**.

---

## 2. Bu projeye alinan fikirler

Bu bolum, arastirmanin dogrudan urune yansiyan kismidir. Asagidakiler
**kavramlardir**; konaklama sektorunun onlarca yildir kullandigi, ders
kitaplarinda ve HTNG/OTA gibi standart calismalarinda yer alan yerlesik
modelleme yaklasimlaridir. **Hicbiri belirli bir depodan kopyalanmamistir;**
birden fazla projede birbirinden bagimsiz olarak gorulmus olmalari, zaten
sektor standardi olduklarinin gostergesidir.

| # | Kavram | Nerede gozlemlendi | Bu projede karsiligi |
|---|---|---|---|
| 1 | **Folio / yuk (charge) muhasebe modeli** - konaklama boyunca olusan tum yuklerin tek bir hesap dosyasinda toplanmasi; baslik (folio) ile satirlarin (charge/transaction) ayri varliklar olmasi | OCA `hotel_folio`, Gifted87 `Guest Folio` + `Folio Transaction` | `app/domain/enums.py`: `FolioStatus`, `ChargeType`, `TransactionDirection`; `app/infrastructure/db/models/billing.py` |
| 2 | **Rate plan (fiyat plani) yapisi** - fiyatin odaya degil, plan + tarih araligi + pansiyon tipi bileskesine bagli olmasi; mevsimsel ve hafta sonu fiyatlandirmanin ayri kayitlar olmasi | Gifted87 `Room Rate Plan`, franknyarkoh "seasonal rates" | `RatePlanType`, `MealPlan` enumlari; `app/domain/rules/pricing.py` |
| 3 | **Oda durumunun ikiye ayrilmasi** - "satilabilirlik/doluluk" ile "temizlik durumu" farkli eksenlerdir; bos ama kirli bir oda satilabilir degildir ama dolu da degildir | OCA `hotel_housekeeping` modulunun ayri bir modul olmasi; franknyarkoh housekeeping | `RoomOccupancyStatus` **ve** `RoomHousekeepingStatus` olarak **iki ayri enum**; `app/domain/rules/availability.py` |
| 4 | **Rezervasyon durumu ile konaklama durumunun ayrilmasi** - "onaylandi" ile "giris yapildi" ayni sey degildir; check-in/check-out ayri gecislerdir | shiningflash (check-in/check-out ayri islem), Kamva-Ntlanga (durum gecis diyagramlari) | `ReservationStatus` ve `StayStatus` enumlari; durum makinesi `app/domain/rules/reservation_state.py` (testleri: `tests/domain/test_reservation_state.py`) |
| 5 | **Gece denetimi (night audit)** - oda ucretinin rezervasyon aninda tek kalemde degil, her gece ayri bir yuk satiri olarak islenmesi; gec cikis ve konaklama uzatmalarinin bu surecte yakalanmasi | Gifted87 night audit motoru | Fiyatlandirmanin gun bazli hesaplanmasi (`app/domain/rules/pricing.py`, `DateRange` deger nesnesi) |
| 6 | **Misafir ile kullanici hesabinin ayri varliklar olmasi** - otelde kalan kisi ile sisteme giren personel farkli kavramlardir; birlestirilmemelidir | immodded (`accounts` vs `guest` app ayrimi) | `app/infrastructure/db/models/guests.py` ile `app/infrastructure/db/models/security.py` ayrimi; RBAC izin katalogu `app/security/permissions.py` |
| 7 | **Depo (repository) katmaninin is mantigindan ayrilmasi** | Kamva-Ntlanga `repositories/` + `services/` ayrimi | `app/infrastructure/db/repositories/base.py` ve alan bazli depolar; `app/domain` katmani SQLAlchemy import etmez |
| 8 | **Ek satislarin (extras) rezervasyondan ayri satirlar olmasi** - kahvalti, transfer, spa gibi kalemler rezervasyon fiyatina gomulmez | franknyarkoh "booking extras", OCA `hotel_services` | `ChargeType` enumu ve `ServiceCategory`; folio yuk satirlari |
| 9 | **Dis rezervasyon saglayicisinin arkasina soyutlama koyma** - arama / teklif / rezervasyon adimlarinin ayri islemler olmasi, tekliflerin gecici oldugu | amadeus4dev demo akisi | Ileriye donuk kanal yoneticisi entegrasyonu icin planlanan sinir (henuz uygulanmadi) |
| 10 | **Is alanlarinin ayri modullere bolunmesi** - rezervasyon / kat hizmetleri / bakim / stok / muhasebe | OCA modul yapisi, frappe/hospitality | `app/infrastructure/db/models/` altinda `reservations.py`, `operations.py`, `billing.py`, `inventory.py`, `rooms.py`, `guests.py`, `organization.py`, `security.py`, `system.py`, `ai.py` |

### 2.1 Kod kopyalanmadiginin gerekcesi

- Ilham alinan depolarin **hicbiri** bu projenin teknoloji yigini ile ayni
  degildir: bu proje **SQLAlchemy 2.x + Pydantic v2 + PySide6 + FastAPI**
  kullanir; incelenen projeler Odoo ORM, Frappe DocType, Django ORM, Tkinter
  veya PyQt5 uzerine kuruludur. Bir satir bile dogrudan tasinabilir degildir.
- Fikirlerin cogu **birden fazla bagimsiz projede** ayni sekilde gorulmustur;
  bu, telif korumasi kapsaminda olmayan **fikir/yontem** duzeyinde olduklarinin
  gostergesidir. Telif hakki ifadeyi (kodu) korur, fikri degil.
- Bu projenin enum katalogu, deger nesneleri (`Money`, `DateRange`), hata
  hiyerarsisi (`HotelError`), maskeli loglama ve alan sifreleme yaklasimi
  incelenen depolarin **hicbirinde** mevcut degildir; ozgun tasarimdir.

---

## 3. Alinmayanlar ve nedeni

| Alinmayan yaklasim | Nerede goruldu | Neden alinmadi |
|---|---|---|
| Copyleft lisansli her turlu kod (AGPL/GPL) | OCA, frappe, Gifted87 | MIT lisansli bir urunu lisans ihlaline sokar; tum projenin acilmasini zorunlu kilardi |
| Lisanssiz depolardan kod/sema | 8 depo | Tum haklari sakli; kullanim izni yok (bkz. 1.3) |
| Belirsiz `License: MIT` tek satirlik lisans dosyali kod | franknyarkoh, ahmadpak | Gecerli bir lisans hibesi metni degil; hukuki dayanak yok |
| Is mantiginin arayuz widget'larina gomulmesi | ranxi2001, JonnyS1226, HotinGo | `ui -> application -> domain` katman kuralini ihlal eder; test edilemez hale getirir |
| ORM modeli icinde is kurali (Odoo/Frappe deseni) | OCA, frappe, Gifted87 | `app/domain` katmani cerceve bagimsizdir; is kurallari SQLAlchemy'siz test edilebilmelidir |
| Bellek ici veri deposu | Kamva-Ntlanga | Kalicilik ve es zamanlilik yok; gercek otel operasyonuna uygun degil |
| Para birimlerinin `float` ile tutulmasi | Birden fazla depoda gozlemlenen yaygin desen | Yuvarlama hatasi finansal kayittir; bu proje `Decimal` tabanli `Money` deger nesnesi kullanir |
| Naive (saat dilimsiz) `datetime` kullanimi | Yaygin | Gece denetimi ve isletme gunu hesaplarini bozar; bu projede `utcnow()` ve ruff `DTZ` kurallari zorunlu tutulur |
| `db.sqlite3` veritabaninin depoya islenmesi | XuanShine, anisbhsl, rajatrawal | Gercek misafir verisi sizdirma riski; KVKK acisindan agir ihlal |
| `.env` dosyasinin depoya islenmesi | rajatrawal | Sir sizintisi. Bu projede `.env` `.gitignore` icindedir, yalnizca `.env.example` islenir; ayrica `detect-secrets` taramasi calisir |
| Frappe/Odoo gibi bir ERP platformuna gomulme | OCA, frappe, Gifted87, franknyarkoh, ahmadpak | Kucuk/orta olcekli Turk otellerinde ERP kurulumu ve bakim maliyeti kabul edilemez; bu proje bagimsiz masaustu + servis olarak calisir |
| Dis GDS/OTA API'sine bagimli tasarim | amadeus4dev | Cevrimdisi calisabilmek zorunlu bir gerekliliktir; dis servisler opsiyonel entegrasyon katmaninda kalmalidir |
| Otomatik test bulunmayan yapi | Incelenen 19 deponun cogunlugu | Bu projede `tests/` agaci alan, altyapi ve guvenlik testleriyle birlikte surekli buyumektedir; testsiz bir yapi finansal islem yapan yazilim icin savunulamaz |

---

## 4. Sonuc

1. **Bu projede hicbir ucuncu parti kaynak kodu kopyalanmamistir.** Yukarida
   incelenen 19 deponun hicbirinden dosya, fonksiyon, sinif, veritabani semasi
   DDL'i, yapilandirma dosyasi veya yorum satiri alinmamistir. Izin veren (MIT)
   lisansli depolar dahil, hicbirinden kod tasinmamistir.

2. **Yalnizca kavramsal ilham alinmistir.** Bolum 2'de listelenen folio/charge
   muhasebesi, rate plan yapisi, oda durumu ayrimi, gece denetimi gibi
   yaklasimlar konaklama sektorunun **standart kavramlaridir**; telif korumasi
   fikirleri degil ifadeyi (kodu) kapsar. Bu kavramlarin bu projedeki
   uygulamasi (enum katalogu, `Money`/`DateRange` deger nesneleri, durum
   makinesi, katmanli mimari) bastan yazilmistir.

3. **Tum dis kod, PyPI uzerinden standart bagimlilik olarak kullanilmaktadir.**
   Hicbir kutuphane depoya kopyalanmamis (vendoring yapilmamis), hicbir
   kutuphane catallanmamis (fork) veya yamalanmamistir. Bagimliliklarin tam
   listesi, surumleri, lisanslari ve kullanim amaclari
   [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) dosyasindadir.

4. **Bu proje MIT lisanslidir** (bkz. kok dizindeki `LICENSE`) ve bu lisans,
   yukaridaki uc maddenin dogru olmasi sayesinde gecerlidir. Copyleft bir
   kaynaktan tek satir kod alinmasi bu lisansi gecersiz kilardi.

5. **Dikkat edilmesi gereken tek copyleft nokta bagimlilik tarafindadir:**
   masaustu arayuz icin kullanilan **PySide6/Qt LGPL-3.0** kosullarina baglidir
   ve dagitim bicimi (ozellikle tek dosyalik PyInstaller paketi) bu kosullar
   gozetilerek yapilmalidir. Ayrintili degerlendirme
   [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) icindeki
   "Copyleft ve dagitim notlari" bolumundedir.

---

## Kaynaklar

Tum lisans bilgileri asagidaki adreslerdeki dosyalarin gercek icerigi cozulerek
dogrulanmistir (2026-08-15):

- [OCA/vertical-hotel](https://github.com/OCA/vertical-hotel)
- [frappe/hospitality](https://github.com/frappe/hospitality)
- [Gifted87/erpnext_hospitality_core](https://github.com/Gifted87/erpnext_hospitality_core)
- [Just-Moh-it/HotinGo](https://github.com/Just-Moh-it/HotinGo)
- [ranxi2001/Hotel-information-management-system](https://github.com/ranxi2001/Hotel-information-management-system)
- [okanuregen/Django---Hotel-Management-System](https://github.com/okanuregen/Django---Hotel-Management-System)
- [JonnyS1226/Hotel-management](https://github.com/JonnyS1226/Hotel-management)
- [franknyarkoh/bookings](https://github.com/franknyarkoh/bookings)
- [ahmadpak/havenir_hotel_erpnext](https://github.com/ahmadpak/havenir_hotel_erpnext)
- [amadeus4dev/amadeus-hotel-booking-django](https://github.com/amadeus4dev/amadeus-hotel-booking-django)
- [Kamva-Ntlanga/hospitality-management-system](https://github.com/Kamva-Ntlanga/hospitality-management-system)
- [immodded/hotelhub](https://github.com/immodded/hotelhub)
- [shiningflash/django-reservation-system](https://github.com/shiningflash/django-reservation-system)
- [XuanShine/PyPMS](https://github.com/XuanShine/PyPMS)
- [anisbhsl/Hotel-Management-System](https://github.com/anisbhsl/Hotel-Management-System)
- [rajatrawal/hotel-booking-logic-django](https://github.com/rajatrawal/hotel-booking-logic-django)
- [guduchango/fastapi-booking](https://github.com/guduchango/fastapi-booking)
- [SrinithiSaiprasath/Hotel-Management-System](https://github.com/SrinithiSaiprasath/Hotel-Management-System)
- [julianrametta/fastapi_design](https://github.com/julianrametta/fastapi_design)

**Yasal uyari:** Bu belge muhendislik amacli bir degerlendirmedir, hukuki gorus
degildir. Lisans yorumlari iyi niyetle ve dosya iceriklerine dayanarak
yapilmistir. Ticari dagitim oncesinde, ozellikle PySide6/Qt LGPL kosullari ve
PyInstaller ile paketleme konusunda hukuk musaviri gorusu alinmasi onerilir.
