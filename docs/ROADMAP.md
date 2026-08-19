# Yol Haritası ve Bilinen Eksikler

Bu belge **dürüstlük belgesidir**: neyin bittiğini değil, neyin
bitmediğini anlatır. Bir özelliğin burada listelenmesi, üretimde
kullanılmaması gerektiği anlamına gelir.

---

## Tamamlanmamış modüller

### Türkiye'ye özel entegrasyonlar — YAPILMADI

| Modül | Durum | Ne var | Ne yok |
|---|---|---|---|
| **e-Fatura / e-Arşiv** | Veri modeli hazır | `Invoice` tablosunda `einvoice_uuid`, `einvoice_ettn`, `einvoice_status` alanları | GİB entegrasyonu, entegratör bağlantısı, UBL-TR XML üretimi, imzalama |
| **Kimlik Bildirim Sistemi (KBS)** | Yapılandırma anahtarı var | `.env` içinde `HOTEL_KBS_*` ayarları | Emniyet servisine bağlantı, XML/webservis şeması, bildirim takibi |
| **Konaklama vergisi beyanı** | Vergi oranı tanımlanabiliyor | `TaxRate` tablosu | Beyanname üretimi |

> **Bu modüller "yapılandırma gerekli" durumundadır ve varsayılan olarak
> kapalıdır.** Gerçek bir entegratör ile bağlantı kurulmadan, ilgili
> mevzuata uygunluk doğrulanmadan üretimde kullanılmamalıdır. Yasal uyum
> sorumluluğu işletmeye aittir.

### Arayüz ekranları

| Ekran | Durum |
|---|---|
| Finans | İş mantığı ve raporlar hazır; ayrı ekran yok. Tahsilat/folyo işlemleri Ön Büro ekranından yapılabiliyor. |
| Stok | İş mantığı ve raporlar hazır; ayrı ekran yok. Kritik stok uyarıları panelde görünüyor. |
| Personel/Vardiya | Veri modeli hazır; ekran yok. |
| Oda tipi ve fiyat plan yönetimi | Veri modeli ve servis hazır; düzenleme ekranı yok (demo veri ve doğrudan veritabanı ile yönetiliyor). |

### Yapay zekâ

| Özellik | Durum |
|---|---|
| LM Studio bağlantısı | **Çalışıyor**, gerçek istekle doğrulandı |
| NVIDIA sağlayıcı kodu | **Hazır**, gerçek çağrı **yapılmadı** (API anahtarı gerekir) |
| Anthropic sağlayıcı kodu | **Hazır**, gerçek çağrı yapılmadı |
| RAG (belge soru-cevap) | Veri modeli (`Document`, `DocumentChunk`) ve gömme modeli hazır; indeksleme akışı **tamamlanmadı** |
| Görsel belge analizi | Sağlayıcı destekliyor; iş akışı bağlanmadı |

---

## Bilinen teknik eksikler

1. **Numara üreteçleri eşzamanlı güvenli değil.** Rezervasyon ve folyo
   numaraları `MAX()+1` ile üretilir. Çok kullanıcılı yoğun kullanımda iki
   kullanıcı aynı numarayı alabilir; benzersizlik kısıtı ikinciyi reddeder
   ve çağıran taraf yeniden denemelidir. **Çözüm:** veritabanı dizisi
   (sequence) veya tesis bazlı sayaç tablosu.

2. **Numaralar tesis bazlı değil, veritabanı genelinde.** Çok tesisli
   kurulumda tesis kodlu önek gerekir.

3. **Türkçe büyük/küçük harf araması SQLite'ta sınırlı.** `ILIKE` yalnızca
   ASCII'de harf duyarsızdır; "İ/ı" gibi harflerde PostgreSQL + `unaccent`
   gerekir.

4. **CRM özeti yalnızca asıl misafiri sayar.** Refakatçi olarak konaklanan
   geceler misafirin toplamına yansımaz.

5. **`OperationsRepository` iki tabloyu birlikte yönetir** ama tek tiple
   parametrelenmiştir; `get_or_404` yanlış tabloya bakabilir.

6. **Mypy tamamen temiz değil.** Birkaç dosyada tip uyarısı kaldı;
   zorunlu kapı değil, isteğe bağlı adım olarak çalışıyor.

7. **UI smoke testleri sınırlı.** Ekranların açıldığı ve veri yüklediği
   test ediliyor; kullanıcı etkileşimi (tıklama akışları) kapsamlı test
   edilmiyor.

---

## Sonraki sürümler

### v0.2 — Operasyon tamamlama
- Finans ve Stok ekranları
- Oda tipi / fiyat planı düzenleme ekranı
- Personel ve vardiya yönetimi
- Numara üretiminde eşzamanlılık düzeltmesi
- Grup rezervasyonu arayüzü

### v0.3 — Yapay zekâ derinleştirme
- RAG belge indeksleme akışının tamamlanması
- Görsel belge analizi (kimlik okuma — KVKK değerlendirmesiyle)
- Talep tahmini ve dinamik fiyat önerisi
- Misafir yorumu sınıflandırma

### v0.4 — Entegrasyonlar
- e-Fatura entegratör bağlantısı
- KBS bildirimi
- Kanal yöneticisi (Booking.com, Expedia) taslağı
- E-posta/SMS bildirim altyapısı

### v1.0 — Üretim olgunluğu
- PostgreSQL üretim kurulumu ve göç rehberi
- Çok tesisli kurulum testleri
- Bağımsız güvenlik denetimi
- Performans testleri (10.000+ rezervasyon)
- Kullanıcı kabul testleri

---

## Katkıda bulunmak

Yukarıdaki maddelerden birine katkıda bulunmak isterseniz
[CONTRIBUTING.md](../CONTRIBUTING.md) dosyasına bakın. Özellikle şu alanlar
yardıma açıktır:

- Türkiye mevzuatı entegrasyonları (e-Fatura, KBS) — alan bilgisi gerektirir
- Gerçek otel işletmelerinden geri bildirim ve iş akışı düzeltmeleri
- Çeviri (İngilizce arayüz metinleri)
- Performans testleri
