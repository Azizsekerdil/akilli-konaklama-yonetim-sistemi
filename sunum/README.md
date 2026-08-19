# Tanıtım Sunumu

Programın tanıtım sunumu **elle düzenlenmez**; [`sunum_uret.py`](sunum_uret.py)
tarafından tek kaynaktan üretilir. Bir cümleyi değiştirmek için betikteki
`SLAYTLAR` listesi düzenlenir ve betik yeniden çalıştırılır.

---

## Üretilen dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `Akilli_Konaklama_Tanitim.pptx` | Türkçe sunum — toplantıda açılan asıl dosya |
| `Akilli_Konaklama_Tanitim.pdf` | Aynı sunumun taşınabilir hâli |
| `Akilli_Konaklama_Tanitim.html` | Tek dosyalık **mobil** sunum; slaytlar gömülüdür, internet gerekmez |
| `Akilli_Konaklama_Tanitim_Baski.pptx` / `.pdf` | Beyaz zeminli **baskı** sürümü |
| `Akilli_Konaklama_Intro_EN.*` | Yukarıdakilerin İngilizcesi |
| `Akilli_Konaklama_Intro_EN_Print.*` | İngilizce baskı sürümü |

26 slayt (8'i uygulama ekran görüntüsü) · 16:9 · yazı tipi Calibri.

**Neden ayrı bir baskı sürümü var?** Ekran sürümünün 26 slaydının her birinin
arka planı tam sayfa koyudur; mono lazer yazıcıda bu, sayfa başına ~%95 toner
demektir. Baskı sürümü zemini beyaza çevirir, vurgu renklerini beyaz zeminde
kontrastı ≥ 4.5 olacak şekilde koyulaştırır ve kart zeminlerini çok açık gri
(`#F5F7F9`) yapar — yapı korunur, mürekkep gitmez.

---

## Üretme

```powershell
python sunum\sunum_uret.py
```

| Seçenek | Etki |
|---|---|
| *(yok)* | İki dil × (ekran + baskı) → 10 dosya |
| `--dil tr` / `--dil en` | Tek dil |
| `--sadece-pptx` | PDF, HTML ve baskı sürümü atlanır (PowerPoint gerekmez) |
| `--kontrol` | Üretmeden **metin sığma denetimi** yapar ve mevcut dosyaları listeler |

Gereksinimler: `python-pptx`, `pywin32` ve **PowerPoint** (PDF ve slayt
PNG'leri PowerPoint COM ile üretilir — başka bir dönüştürücü yazı tipi ve
emoji yorumunda farklılık üretir, o zaman PDF ile ekranda görülen slayt aynı
olmaz).

```powershell
python -m pip install python-pptx pywin32
```

> Bu paketler uygulamanın çalışma zamanı bağımlılığı **değildir**;
> `requirements.txt` içinde yer almazlar. Sunum yalnızca yayın hazırlarken
> üretilir.

---

## Ekran görüntüleri

Sunumdaki uygulama görüntüleri [`ekranlar/`](ekranlar/) klasöründe durur ve
[`ekran_yakala.py`](ekran_yakala.py) tarafından üretilir:

```powershell
.\.venv\Scripts\python.exe sunum\ekran_yakala.py
```

Betik **geçici bir klasörde** sıfırdan demo veritabanı kurar (mevcut veriye
dokunmaz), yönetici hesabıyla programatik giriş yapar ve her sayfayı PNG
olarak basar. Görüntülerdeki verilerin tamamı sentetiktir; gerçek kişi verisi
içermez. Arayüz değiştiğinde önce bu betik, sonra `sunum_uret.py`
çalıştırılır — görüntüler kendi kendine güncellenmez. Bir görüntü eksikse
sunum üretimi ne yapılacağını söyleyen bir hatayla durur, boş çerçeve basmaz.

---

## İçerik nerede duruyor?

| Ne | Nerede |
|---|---|
| Slayt metinleri (iki dilli) | `SLAYTLAR` listesi |
| Ekran görüntüleri | `ekranlar/` — `ekran_yakala.py` üretir |
| Renkler | `PALET_EKRAN` ve `PALET_BASKI` |
| Kutu konumları ve puntolar | `YERLEŞİM` bölümü |
| Metin uzunluğu bütçeleri | `BUTCE` |

Her metin `("türkçe", "english")` ikilisidir. Bir slayt eklenip İngilizcesi
unutulursa üretim başlarken durur — sessizce Türkçe basmaz.

Kutular sabittir; metin uzarsa PowerPoint onu küçültmez, **taşırır**. Bu
yüzden üretimden önce her metin `BUTCE` değerlerine göre ölçülür:

```powershell
python sunum\sunum_uret.py --kontrol
```

---

## Sunumdaki sayılar

Sürüm numarası `pyproject.toml`'dan okunur. Ölçüm sayıları (985 test, %77,5
kapsam, 72 izin, 60 tablo, bandit ve pip-audit bulguları) **15 Ağustos 2026**
tarihli ölçümlerdir ve komutlarıyla birlikte şurada yazılıdır:

- [`docs/TEST_REPORT.md`](../docs/TEST_REPORT.md)
- [`docs/SECURITY_REVIEW.md`](../docs/SECURITY_REVIEW.md)
- [`docs/ROADMAP.md`](../docs/ROADMAP.md) — sunumdaki "yapılmayanlar" slaydının kaynağı

Bu belgeler yeniden ölçüldüğünde `sunum_uret.py` içindeki `OLCUM_TARIHI` ve
ilgili sayılar da güncellenmelidir. Sunum kendi kendine güncellenmez; ama
neyin güncelleneceği tek dosyada durur.
