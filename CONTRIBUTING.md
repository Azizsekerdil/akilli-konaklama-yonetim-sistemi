# Katkı Rehberi

Bu projeye katkıda bulunmak istediğiniz için teşekkürler.

## Geliştirme ortamı

```powershell
git clone https://github.com/Azizsekerdil/akilli-konaklama-yonetim-sistemi.git
cd akilli-konaklama-yonetim-sistemi
.\scripts\setup.ps1 -DemoData
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Kalite zinciri

Değişikliğinizi göndermeden önce **mutlaka** çalıştırın:

```powershell
.\scripts\test.ps1
```

Bu komut sırasıyla `black` → `ruff` → `mypy` → `pytest` → `bandit` →
`pip-audit` çalıştırır. Zorunlu adımlar (`ruff`, `pytest`) geçmeden
değişiklik kabul edilmez.

## Kod standartları

| Konu | Kural |
|---|---|
| Dil | Docstring ve yorumlar **Türkçe**, ASCII-güvenli yazılır (`cakisma`, `musaitlik`). Kullanıcıya **gösterilen** metinlerde Türkçe karakter serbesttir. |
| Tip ipuçları | Zorunlu. Modern sözdizimi: `str \| None`, `list[int]` |
| Satır uzunluğu | 100 (black) |
| Import | `from __future__ import annotations` her dosyanın başında |
| Para | **Asla `float` kullanmayın.** `Decimal` veya `Money` |
| Tarih-saat | `utcnow()` kullanın; naive `datetime` yasak |
| Modül sonu | `__all__` listesi |

### Docstring'ler "neden"i anlatır

Kodun *ne yaptığı* zaten okunabilir. Docstring'de **neden öyle yapıldığını**
ve varsa tuzağı yazın:

```python
def create_checkpoint(self) -> Checkpoint:
    """Değişiklik öncesi geri dönüş noktası oluşturur.

    ``git stash create`` kullanılır: çalışma ağacını **değiştirmeden**
    mevcut durumu bir commit nesnesi olarak kaydeder. ``git stash push``
    kullanılsaydı kullanıcının dosyaları anında geri alınır ve
    beklenmedik biçimde kaybolmuş gibi görünürdü.
    """
```

## Mimari kuralları

```
ui → application → domain ← infrastructure
```

- **`app/domain`** hiçbir framework'e bağımlı değildir. SQLAlchemy, PySide6
  veya FastAPI import edilmez. İş kuralları veritabanı olmadan test edilebilir.
- **`app/ui`** iş kuralı içermez. Veriye yalnızca
  `app/application/services` üzerinden erişir.
- **Repository'ler** domain kurallarını bilmez; ORM satırlarını domain veri
  yapılarına çevirir.
- **Servisler** kuralları tekrarlamaz; `app/domain/rules` içindeki saf
  fonksiyonları çağırır.

### ORM nesnesi oturum dışına çıkarılmaz

`service_context` bloğu bittiğinde ORM nesneleri detached olur ve
ilişkilere erişim `DetachedInstanceError` fırlatır. Blok içinde düz veri
yapısına (dataclass/dict) çevirin.

## Test yazma

- Her davranış değişikliği bir testle gelir
- Test adları Türkçe ve **ne doğruladığını** anlatır:
  `test_ayni_odaya_cakisan_rezervasyon_reddedilir`
- Kritik kurallar için "bu test geçmezse ne bozulur" yorumu ekleyin
- Gerçek dış servis gerektiren testler `@pytest.mark.live` ile işaretlenir
  ve varsayılan olarak atlanır

### Hata mesajı testleri

`pytest.raises(match=...)` `str(exception)` üzerinde çalışır; `HotelError`'da
bu değer teknik `detail` alanıdır. Kullanıcıya gösterilen metni doğrulamak
için `user_message` okuyun:

```python
with pytest.raises(BusinessRuleError) as hata:
    ...
assert "kara listede" in hata.value.user_message
```

## Güvenlik kuralları

- API anahtarı, parola veya gerçek kimlik verisi **koda yazılmaz**
- Test verileri **tamamen uydurma** olmalı; kimlik numaraları geçersiz
  biçimde, e-postalar `.local` alan adında
- Yeni bir hassas alan eklerseniz `app/core/log.py` maskeleme listesine ekleyin
- Veri değiştiren her servis metodu `ctx.require(Perm.X)` ile başlar ve
  `ctx.audit(...)` ile denetime yazar

## Commit mesajları

Türkçe, açıklayıcı ve **neden**i anlatan:

```
feat(reservation): cakisma kontrolu iki asamali hale getirildi

Yazma oncesi kontrol, es zamanli iki istekte ikisini de geciririr.
Kayit yazildiktan sonra kontrol tekrarlanir; cakisma varsa islem
geri alinir.
```

Önek: `feat` · `fix` · `refactor` · `test` · `docs` · `chore` · `perf`

## Pull request

1. `main` üzerinde çalışmayın; özellik dalı açın (`feat/oda-plani`)
2. Kalite zincirini çalıştırın
3. PR açıklamasında: ne değişti, **neden**, nasıl test edildi
4. Arayüz değişikliği yaptıysanız ekran görüntüsü ekleyin

## Yardıma açık alanlar

Öncelikli konular [docs/ROADMAP.md](docs/ROADMAP.md) içinde listelidir.
Özellikle Türkiye mevzuatı entegrasyonları (e-Fatura, KBS) alan bilgisi
gerektirir ve katkıya açıktır.
