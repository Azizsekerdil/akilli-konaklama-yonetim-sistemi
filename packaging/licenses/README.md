# Dagitim paketine giren lisans metinleri

Bu klasordeki dosyalar **ikili (binary) dagitim paketine** kopyalanir
(`packaging/hotel.spec` -> `datas`). Amac, `THIRD_PARTY_NOTICES.md` §5.1'de
yazili yukumlulugu **kagit uzerinde degil, uretilen pakette** yerine
getirmektir.

Bagimsiz bir yayin oncesi denetimde (bulgu **HTL-H4**) uretilen `dist/`
klasorunun ne projenin kendi MIT metnini ne de bagli Qt kutuphanelerinin
gerektirdigi LGPL metnini icermedigi tespit edildi. Iki yukumluluk ayni anda
karsilanmiyordu:

* **MIT** - kendi lisansimiz, telif bildiriminin *tum kopyalarda* yer
  almasini sart kosar.
* **LGPL-3.0** - PySide6 / Qt dinamik olarak baglanir; lisans metninin
  dagitimla birlikte verilmesi gerekir.

`hotel.spec` artik **derleme zamaninda dogrular**: asagidaki dosyalardan biri
eksikse paketleme baslamadan durur.

---

## Icerik

| Dosya | Ne | Durum |
|---|---|---|
| `GPL-3.0.txt` | GNU General Public License v3.0, birebir metin | **Depoda** |
| `LGPL-3.0.txt` | GNU Lesser General Public License v3.0, birebir metin | **EKSIK - eklenmelidir** |

### `LGPL-3.0.txt` neden depoda degil?

LGPL-3.0, GPL-3.0 metnine **ek izinler** getiren ayri bir belgedir ve
yukumlulugu karsilamak icin **birebir** (verbatim) olmasi gerekir. Bu depoyu
hazirlayan otomatik surec, dogrulanabilir birebir bir kopyaya cevrimdisi
erisemedigi icin metni tahminle yazmak yerine **eksik birakmayi** secti:
yaklasik bir lisans metni, lisans metni degildir.

Ikili paket uretmeden once:

```powershell
# Birebir metni FSF'nin kendi adresinden alin ve buraya kaydedin:
#   https://www.gnu.org/licenses/lgpl-3.0.txt
# Dosya adi tam olarak LGPL-3.0.txt olmalidir.
```

`GPL-3.0.txt` de gereklidir ve depoda vardir: LGPL-3.0 kendi metninde
GPL-3.0'in sart ve kosullarini **icerir**, dolayisiyla ikisi birlikte
dagitilir.

### Provenans

`GPL-3.0.txt`, bu makinede kurulu bir Python paketinin (`numpy`, sürüm
2.4.6) dagittigi birebir lisans paketinden alinmistir; icerik 18 bolumun
tamamini ve "END OF TERMS AND CONDITIONS" kapanisini icerir. SHA-256:

```
e57f1c320b8cf8798a7d2ff83a6f9e06a33a03585f6e065fea97f1d86db84052
```

---

## Kendi lisansimiz

`LICENSE` (MIT) ve `THIRD_PARTY_NOTICES.md` depo kokunde durur ve paketleme
sirasinda oradan alinir; bu klasore kopyalanmaz.
