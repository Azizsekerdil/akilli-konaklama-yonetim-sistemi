# Test Raporu

Bu belge **ölçülmüş** sonuçları içerir. Her sayı, aşağıda komutu verilen bir
çalıştırmanın çıktısından alınmıştır; hiçbiri tahmin veya hatırlama değildir.

> **BU BÖLÜM YENİDEN ÖLÇÜLDÜ — 19 Ağustos 2026.**
>
> Aşağıdaki özet, kamuya açık sürüm için sıfırdan çalıştırılan ölçümdür.
> Belgenin geri kalanındaki ayrıntılı bölümler 15 Ağustos 2026 tarihli
> önceki ölçümden gelir ve **o tarihli anlık görüntü** olarak okunmalıdır;
> hangi sayının hangi ölçümden geldiği bölüm başlıklarında yazılıdır.
> Sunumdaki sayılar bu belgeden kopyalanmaz: `sunum/olcum.py` onları
> sunum üretilirken doğrudan kaynak koddan ölçer.

| | |
|---|---|
| Ölçüm tarihi (özet) | 2026-08-19 |
| Sürüm | 0.1.0 |
| Toplanan test | 1075 |
| Geçen / atlanan | 1074 / 1 (`live` işaretli, gerçek LM Studio ister) |
| Dal dahil kapsam | %77,6 |
| `ruff check app tests` | 0 bulgu |
| `black --check app tests` | temiz |
| `bandit -r app` | 0 yüksek · 0 orta · 9 düşük · 0 `#nosec` |
| gitleaks (depo ağacı) | 0 bulgu (yapılandırma ile); 3 incelenmiş yanlış pozitif (yapılandırmasız) |
| detect-secrets | 0 bulgu |
| semgrep `p/security-audit`+`p/secrets`+`p/python` | 0 bulgu (224 dosya) |
| Platform | Windows 11 Pro 10.0.26200 |
| Python | 3.11.9 |
| pytest | 9.1.1 |
| ruff | 0.16.3 |
| bandit | 1.9.4 |
| pip-audit | 2.10.1 |

---

## 0. Önceki ölçüm (15 Ağustos 2026) — arka plan

| | |
|---|---|
| Ölçüm tarihi | 2026-08-15 |
| Platform | Windows 11 Pro 10.0.26200 |
| Python | 3.11.9 |
| pytest | 9.1.1 |
| ruff | 0.16.3 |
| bandit | 1.9.4 |
| pip-audit | 2.10.1 |

> Bu rapor bir **anlık görüntüdür**. Kodu değiştirdikten sonra sayılar
> değişir; raporu güncellemeden önce komutları yeniden çalıştırın.

---

## 1. Özet

```powershell
.\.venv\Scripts\python.exe -m pytest -q --no-header -m "not live"
```

Gerçek çıktının son satırı:

```
985 passed, 1 deselected in 91.01s (0:01:31)
```

| Ölçüt | Değer |
|---|---|
| Toplanan test (tümü) | 986 |
| Çalışan test | 985 |
| **Geçen** | **985** |
| Başarısız | 0 |
| Hata (error) | 0 |
| Atlanan (`skip`) | 0 |
| Seçim dışı (`deselect`) | 1 |
| Süre | 91.01 s |

### Neden 1 test seçim dışı?

Tek bir test `live` işaretlidir ve **gerçek bir dış servise** bağlanır:

```
tests/ai/test_providers.py::test_gercek_lmstudio_model_listesi
```

Doğrulama:

```powershell
.\.venv\Scripts\python.exe -m pytest --co -q -m "live"
# 1/986 tests collected (985 deselected) in 0.58s
```

`-m "not live"` varsayılandır (`scripts/test.ps1` bu işareti otomatik ekler),
çünkü LM Studio kurulu olmayan bir makinede testin başarısız olması yanıltıcı
olurdu. Gerçek bağlantıyı sınamak için:

```powershell
.\scripts\test.ps1 -Live
```

Kalan 985 testin **hiçbiri ağa çıkmaz**; yapay zekâ HTTP çağrıları `respx` ile
taklit edilir. Bu, bir davranış iddiası değil, testle korunan bir kuraldır:
`tests/ai/test_providers.py:888` — `test_hicbir_ag_baglantisi_acilmaz`.

---

## 2. Paket bazında dağılım

```powershell
.\.venv\Scripts\python.exe -m pytest --co -q -m "not live" tests/<paket>
```

| Paket | Test | Kapsadığı alan |
|---|---:|---|
| `tests/domain` | 99 | Müsaitlik, fiyat, durum makinesi, para/tarih değer nesneleri |
| `tests/security` | 58 | Parola, kimlik doğrulama/oturum, izin kataloğu |
| `tests/infrastructure` | 126 | Şifreleme, repository sorguları, demo veri üreteci |
| `tests/application` | 158 | Rezervasyon, ön büro, folyo, misafir, operasyon, AI servisi |
| `tests/ai` | 122 (+1 `live`) | Sağlayıcı adaptörleri, hata eşlemesi, yedek zinciri |
| `tests/ui` | 178 | PySide6 ekran ve diyalog testleri (offscreen) |
| `tests/reporting` | 106 | KPI motoru, sorgular, PDF/Excel/CSV dışa aktarma |
| `tests/devcenter` | 138 | Komut politikası, sandbox, oturum durum makinesi |
| **Toplam** | **985** | |

### Dosya bazında

| Dosya | Test |
|---|---:|
| `tests/domain/test_availability.py` | 24 |
| `tests/domain/test_pricing.py` | 23 |
| `tests/domain/test_reservation_state.py` | 18 |
| `tests/domain/test_value_objects.py` | 34 |
| `tests/security/test_auth.py` | 24 |
| `tests/security/test_passwords.py` | 21 |
| `tests/security/test_permissions.py` | 13 |
| `tests/infrastructure/test_encryption.py` | 21 |
| `tests/infrastructure/test_repositories.py` | 64 |
| `tests/infrastructure/test_seed.py` | 41 |
| `tests/application/test_ai_service.py` | 29 |
| `tests/application/test_frontdesk_service.py` | 23 |
| `tests/application/test_guest_service.py` | 28 |
| `tests/application/test_operations_services.py` | 50 |
| `tests/application/test_reservation_service.py` | 28 |
| `tests/ai/test_providers.py` | 81 (+1 `live`) |
| `tests/ai/test_registry.py` | 41 |
| `tests/ui/test_frontdesk_page.py` | 35 |
| `tests/ui/test_guests_settings_pages.py` | 40 |
| `tests/ui/test_operations_pages.py` | 37 |
| `tests/ui/test_reports_ai_pages.py` | 25 |
| `tests/ui/test_reservations_page.py` | 41 |
| `tests/reporting/test_exporters.py` | 62 |
| `tests/reporting/test_kpi.py` | 44 |
| `tests/devcenter/test_policy.py` | 83 |
| `tests/devcenter/test_session.py` | 28 |
| `tests/devcenter/test_workspace.py` | 27 |

---

## 3. Kapsam (coverage)

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not live" --cov=app --cov-report=term
```

Gerçek çıktının son iki satırı:

```
TOTAL                                                          17246   3463   3214    461  77.5%
985 passed, 1 deselected in 153.14s (0:02:33)
```

| Ölçüt | Değer |
|---|---:|
| Toplam deyim (statement) | 17 246 |
| Kapsanmayan deyim | 3 463 |
| Dal (branch) | 3 214 |
| Kısmi dal | 461 |
| **Toplam kapsam (dal dahil)** | **%77.5** |
| Yalnız deyim kapsamı | %79.9 |
| Yalnız dal kapsamı | %64.3 |

> Kapsam yapılandırması `pyproject.toml:232` (`[tool.coverage.run]`) içindedir:
> `branch = true`, `app/main.py` ve `alembic/` hariç tutulur.

### Paket bazında kapsam

Aşağıdaki tablo `--cov-report=json` çıktısından toplanmıştır; toplam satırı
coverage'ın kendi hesabıyla (%77.5) birebir tutmaktadır.

| Paket | Deyim | Dal | Kapsam |
|---|---:|---:|---:|
| `app/domain` | 872 | 134 | **%96.1** |
| `app/reporting` | 685 | 168 | **%96.4** |
| `app/ai` | 1 018 | 244 | %91.0 |
| `app/infrastructure` | 2 920 | 448 | %89.9 |
| `app/security` | 464 | 106 | %89.3 |
| `app/application` | 1 919 | 504 | %83.1 |
| `app/core` | 591 | 108 | %79.4 |
| `app/devcenter` | 823 | 228 | %75.4 |
| `app/ui` | 7 731 | 1 232 | %67.1 |
| `app/cli.py` | 218 | 42 | **%0.0** |
| **TOPLAM** | **17 246** | **3 214** | **%77.5** |

İş kurallarının bulunduğu katmanlar (`domain`, `reporting`, `ai`,
`infrastructure`, `security`) %89'un üzerindedir. Toplamı aşağı çeken kısım
`app/ui`'dir ve orada da düşüklüğün nedeni belirli dosyaların **hiç**
test edilmemiş olmasıdır (aşağıya bakınız), ekranların yarım test edilmesi
değil.

### En düşük kapsamlı 15 dosya

| Dosya | Deyim | Kapsanmayan | Kapsam |
|---|---:|---:|---:|
| `app/cli.py` | 218 | 218 | %0.0 |
| `app/ui/first_run.py` | 192 | 192 | %0.0 |
| `app/ui/login.py` | 179 | 179 | %0.0 |
| `app/ui/main_window.py` | 160 | 160 | %0.0 |
| `app/ui/pages/dev_center_page.py` | 342 | 342 | %0.0 |
| `app/ui/pages/registry.py` | 39 | 39 | %0.0 |
| `app/ui/pages/dashboard_page.py` | 189 | 159 | %14.2 |
| `app/ui/pages/placeholder_page.py` | 45 | 35 | %19.6 |
| `app/infrastructure/backup.py` | 101 | 74 | %20.9 |
| `app/infrastructure/db/session.py` | 79 | 53 | %27.4 |
| `app/devcenter/terminal.py` | 106 | 68 | %29.7 |
| `app/application/services/dashboard_service.py` | 144 | 76 | %39.5 |
| `app/devcenter/quality.py` | 94 | 37 | %52.8 |
| `app/core/secret_store.py` | 81 | 33 | %54.2 |
| `app/ui/dialogs/folio_dialog.py` | 499 | 213 | %57.6 |

Bu listenin yorumu 6. bölümdedir. **%0 olan altı dosya, üretimde çalışan
gerçek kodtur** — kapsam dışı bırakılmış yardımcı dosyalar değil.

---

## 4. Kritik senaryo kapsamı

Kullanıcının açıkça istediği 13 senaryonun her biri için ilgili test
`ripgrep` ile aranıp dosyası açılarak doğrulanmıştır. Satır numaraları
`93ab8b7` durumuna aittir.

### 4.1 Aynı odaya çakışan iki rezervasyon — KAPSANIYOR

| Katman | Dosya:satır | Test |
|---|---|---|
| Domain | `tests/domain/test_availability.py:43` | `test_ayni_odaya_cakisan_rezervasyon_engellenir` |
| Servis | `tests/application/test_reservation_service.py:130` | `test_ayni_odaya_cakisan_rezervasyon_reddedilir` |
| Arayüz | `tests/ui/test_reservations_page.py:484` | `test_cakisma_hatasi_anlasilir_gosterilir` |

Domain testinin gövdesi, hata mesajının **hangi rezervasyonla** çakışıldığını
söylediğini de doğrular:

```python
def test_ayni_odaya_cakisan_rezervasyon_engellenir(self):
    """EN KRITIK KURAL: ayni oda ayni gece iki kez satilamaz."""
    mevcut = [Booking(ODA, aralik(10, 14), confirmation_number="RZV-0001")]

    with pytest.raises(OverlappingReservationError) as hata:
        check_availability(aralik(12, 16), room_id=ODA, existing_bookings=mevcut)

    assert "RZV-0001" in hata.value.user_message
```

Yardımcı testler: aynı istek içinde çakışma
(`test_reservation_service.py:214`), tarih değişiminde kendisiyle
çakışmama (`:394`), başkasıyla çakışma (`:415`), bitişik rezervasyonun
engellenmemesi (`test_availability.py:62`), demo verinin çakışma
üretmemesi (`tests/infrastructure/test_seed.py:346`).

### 4.2 İptal edilen rezervasyon — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| Durum makinesi | `tests/domain/test_reservation_state.py:49` | `test_iptal_edilen_rezervasyona_check_in_yapilamaz` |
| Oda serbest kalır | `tests/application/test_reservation_service.py:233` | `test_iptal_edilen_rezervasyon_odayi_serbest_birakir` |
| Çifte iptal | `tests/application/test_reservation_service.py:342` | `test_iptal_edilen_rezervasyon_yeniden_iptal_edilemez` |
| Gerekçe zorunlu | `tests/application/test_reservation_service.py:355` | `test_iptal_gerekcesi_zorunlu` |
| Check-in engeli | `tests/application/test_frontdesk_service.py:114` | `test_iptal_edilen_rezervasyona_giris_engellenir` |
| Doluluk şişmez | `tests/reporting/test_exporters.py:835` | `test_iptal_ve_gelmeme_dolulugu_sisirmez` |
| Arayüz | `tests/ui/test_reservations_page.py:339` | `test_gerekce_verilmezse_iptal_yapilmaz` |

### 4.3 No-show — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| Tam tutar cezası | `tests/domain/test_pricing.py:223` | `test_no_show_tam_tutar` |
| Kısmi ceza | `tests/domain/test_pricing.py:230` | `test_no_show_kismi_ceza` |
| Servis hesabı | `tests/application/test_reservation_service.py:366` | `test_no_show_cezasi_hesaplanir` |
| Sonraki geçişler | `tests/domain/test_reservation_state.py:67` | `test_no_show_sonrasi_yalnizca_iptal` |
| KPI ayrımı | `tests/reporting/test_kpi.py:203` | `test_no_show_orani_iptalden_ayridir` |
| Demo veri örneği | `tests/infrastructure/test_seed.py:431` | `test_iptal_ve_gelmedi_ornekleri_var` |

### 4.4 Erken giriş ve geç çıkış — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| Fiyat kuralı | `tests/domain/test_pricing.py:241` | `test_erken_giris_dilim_basina_ucretlendirilir` |
| Erken giriş → folyo | `tests/application/test_frontdesk_service.py:120` | `test_erken_giris_ucreti_folyoya_islenir` |
| Geç çıkış → folyo | `tests/application/test_frontdesk_service.py:176` | `test_gec_cikis_ucreti_islenir` |
| Yetki kontrolü (UI) | `tests/ui/test_frontdesk_page.py:556` | `test_gec_cikis_yetkisi_yoksa_alan_bunu_yazar` |

Servis testi ücreti sayı sayı doğrular, "bir ücret oluştu" ile yetinmez:

```python
def test_erken_giris_ucreti_folyoya_islenir(self, admin_ctx, reservation):
    service = FrontdeskService(admin_ctx)
    service.check_in(reservation.rooms[0].id, early_check_in_hours=4)

    folio = FolioService(admin_ctx).folio_for_room(reservation.rooms[0].id)
    assert folio is not None
    early = [c for c in folio.charges if c.charge_type is ChargeType.EARLY_CHECKIN]
    assert len(early) == 1
    # Gecelik 1000 TL, 4 saat -> 2 dilim x %25 = %50
    assert early[0].total_amount == Decimal("500.00")
```

### 4.5 Oda bakım nedeniyle satışa kapalı — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| Domain kuralı | `tests/domain/test_availability.py:117` | `test_bakimdaki_oda_satilamaz` |
| Süresiz blok | `tests/domain/test_availability.py:126` | `test_suresiz_blok_her_tarihi_kapatir` |
| Check-in engeli | `tests/application/test_frontdesk_service.py:106` | `test_bakimdaki_odaya_giris_engellenir` |
| Satılabilir listeden düşer | `tests/infrastructure/test_repositories.py:278` | `test_list_rooms_only_sellable_bakimdaki_odayi_atlar` |
| Açık arıza kaydı bloke eder | `tests/infrastructure/test_repositories.py:359` | `test_blocks_for_range_acik_ariza_kaydini_da_kapsar` |
| Satılmış oda kapatılamaz | `tests/application/test_operations_services.py:351` | `test_satilmis_oda_servis_disi_yapilamaz` |
| Yetkiliyle zorlama | `tests/application/test_operations_services.py:367` | `test_force_ile_yetkili_servis_disi_yapabilir` |
| KPI paydası | `tests/reporting/test_kpi.py:243` | `test_calculate_kpis_arizali_odayi_paydadan_duser` |

### 4.6 Hatalı ödeme tutarı — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| Fazla ödeme reddi | `tests/application/test_frontdesk_service.py:219` | `test_fazla_odeme_reddedilir` |
| Bilinçli fazla ödeme | `tests/application/test_frontdesk_service.py:231` | `test_bilincli_fazla_odemeye_izin_verilir` |
| Negatif ödeme | `tests/application/test_frontdesk_service.py:246` | `test_negatif_odeme_reddedilir` |
| Açık bakiyeyle çıkış | `tests/application/test_frontdesk_service.py:133` | `test_bakiye_acikken_cikis_engellenir` |
| Arayüz ayrıştırma | `tests/ui/test_frontdesk_page.py:659` | `test_gecersiz_tutar_anlasilir_hata_verir` |
| Negatif tutar (rezervasyon) | `tests/ui/test_reservations_page.py:541` | `test_negatif_tutar_reddedilir` |

Testin kendi docstring'i senaryoyu adıyla anıyor:

```python
def test_fazla_odeme_reddedilir(self, admin_ctx, reservation):
    """KRITIK: hatali odeme tutari (or. 2000 yerine 20000) yakalanmali."""
```

### 4.7 Yetkisiz kullanıcının finans modülüne erişimi — KAPSANIYOR

| Katman | Dosya:satır | Test |
|---|---|---|
| Servis/yetki | `tests/security/test_auth.py:159` | `test_yetkisiz_kullanici_finans_modulune_erisemez` |
| Ücret geçersiz kılma | `tests/security/test_auth.py:166` | `test_yetkisiz_kullanici_ucret_gecersiz_kilamaz` |
| Servis katmanı tekrarı | `tests/application/test_frontdesk_service.py:285` | `test_yetkisiz_kullanici_ucret_gecersiz_kilamaz` |
| Rapor listesi gizlenir | `tests/ui/test_reports_ai_pages.py:194` | `test_mali_raporlar_yetkisiz_kullanicida_listede_yok` |
| KPI kartı maskelenir | `tests/ui/test_reports_ai_pages.py:207` | `test_mali_kpi_kartlari_yetkisiz_kullanicida_maskelenir` |
| Düğme pasif | `tests/ui/test_frontdesk_page.py:394` | `test_yetkisiz_kullanicida_gecersiz_kil_dugmesi_pasif` |
| Ret denetime yazılır | `tests/application/test_reservation_service.py:535` | `test_yetki_reddi_denetime_yazilir` |

Kontrol **iki katmanda birden** yapılır: arayüzdeki pasif düğme tek başına
güvenlik sayılmaz, servis çağrısı da reddedilir.

### 4.8 Yerel modelin çalışmaması — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| Bağlantı reddi → `AIConnectionError` | `tests/ai/test_providers.py:319` | `test_baglanti_reddi` |
| Türkçe çözüm önerisi | `tests/application/test_ai_service.py:328` | `test_baglanti_hatasi_turkce_cozum_onerisi_tasir` |
| Yedeğe geçilir | `tests/ai/test_registry.py:144` | `test_gecici_hatalarda_yedege_gecilir` (`AIConnectionError` parametresi) |
| Yedek yoksa özgün hata | `tests/ai/test_registry.py:171` | `test_yedek_yoksa_ozgun_hata_firlatilir` |
| Kayıt `FAILED` olur | `tests/application/test_ai_service.py:231` | `test_basarisiz_cagri_da_kaydedilir` |
| Arayüzde durum gösterilir | `tests/ui/test_reports_ai_pages.py:373` | `test_yapay_zeka_kapaliyken_durum_ve_cozum_gosterilir` |

Sağlayıcı testi, öneri metninin gerçekten LM Studio'ya işaret ettiğini
doğrular:

```python
@respx.mock
def test_baglanti_reddi(self):
    respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("baglanti reddedildi"))
    with yerel_saglayici() as saglayici, pytest.raises(ConnErr) as hata:
        saglayici.chat(istek())
    assert "LM Studio" in (hata.value.remedy or "")
```

### 4.9 Bulut API zaman aşımı — KAPSANIYOR (bir kısıtla)

| Konu | Dosya:satır | Test |
|---|---|---|
| Aktarım zaman aşımı → `AITimeoutError` | `tests/ai/test_providers.py:326` | `test_zaman_asimi` |
| Ayrı durumla kaydedilir (`TIMEOUT`) | `tests/application/test_ai_service.py:245` | `test_zaman_asimi_ayri_durumla_kaydedilir` |
| Çözüm önerisi taşır | `tests/application/test_ai_service.py:340` | `test_zaman_asimi_hatasi_cozum_onerisi_tasir` |
| Yedeğe geçilir | `tests/ai/test_registry.py:144` | `test_gecici_hatalarda_yedege_gecilir` (`AITimeoutError` parametresi) |

**Kısıt — dürüstlük notu:** `test_zaman_asimi` testi LM Studio adaptörü
üzerinden çalışır, NVIDIA/Anthropic üzerinden değil. Ancak zaman aşımı
eşlemesi sağlayıcıya özgü değildir; ortak taban sınıfta yapılır:

- `app/ai/base.py:373` — her HTTP çağrısı `map_transport_error(...)` ile sarılır
- `app/ai/errors.py:204` — `isinstance(exc, httpx.TimeoutException)` → `AITimeoutError`
- `app/ai/providers/nvidia.py:36` — `class NvidiaProvider(OpenAICompatibleProvider)`,
  yani aynı taban çağrı yolunu kullanır

Yani bulut sağlayıcıda zaman aşımı **aynı kod yolundan** geçer, fakat
NVIDIA/Anthropic adresine karşı ayrıca yazılmış bir zaman aşımı testi
**yoktur**. 6. bölümde boşluk olarak listelenmiştir.

### 4.10 API kotasının dolması — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| 429 → `AIQuotaError` | `tests/ai/test_providers.py:305` | `test_kota_hatasi` |
| 429 yeniden denenir | `tests/ai/test_providers.py:361` | `test_429_yeniden_denenir` |
| Yedeğe geçilir | `tests/ai/test_registry.py:144` | `test_gecici_hatalarda_yedege_gecilir` (`AIQuotaError` parametresi) |

```python
@respx.mock
def test_kota_hatasi(self):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(429, json={"error": "rate limit"}))
    with yerel_saglayici() as saglayici, pytest.raises(AIQuotaError) as hata:
        saglayici.chat(istek())
    assert "Kota" in (hata.value.remedy or "")
```

### 4.11 Geçersiz API anahtarı — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| 401 ve 403 → `AIAuthenticationError` | `tests/ai/test_providers.py:297` | `test_kimlik_hatasi` (parametrik: 401, 403) |
| 401'de yeniden denenmez | `tests/ai/test_providers.py:380` | `test_401_de_yeniden_denenmez` |
| Anahtar hiç yoksa | `tests/ai/test_providers.py:675` | `test_anahtar_yoksa_kimlik_hatasi` (NVIDIA) |
| **Yedeğe geçilmez** | `tests/ai/test_registry.py:163` | `test_kalici_hatalarda_yedege_gecilmez` |
| Ayarlar ekranı davranışı | `tests/ui/test_guests_settings_pages.py:430` | `test_yapay_zeka_kapaliyken_test_dugmesi_pasif` |

Kalıcı hatada yedeğe geçmeme kararı testin docstring'inde gerekçelendirilmiş:

```python
def test_kalici_hatalarda_yedege_gecilmez(self, hata: AIProviderError):
    """Anahtar hatasini yedekle gizlemek, kullanicinin sorunu gormesini engeller."""
```

Ayrıca `test_anahtar_yoksa_kimlik_hatasi`, hata ayrıntısında **anahtarın
değerinin değil yalnızca adının** geçtiğini doğrular
(`assert "nvapi" not in str(hata.value.detail or "")`).

### 4.12 Yapay zekânın geçersiz JSON döndürmesi — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| JSON olmayan HTTP gövdesi | `tests/ai/test_providers.py:340` | `test_json_olmayan_yanit_bicim_hatasi` |
| Modelin düz metin dönmesi | `tests/ai/test_providers.py:517` | `test_gecersiz_json_hata_verir` |
| Boş yanıt | `tests/ai/test_providers.py:521` | `test_bos_yanit_hata_verir` |
| Üst düzey dizi reddi | `tests/ai/test_providers.py:525` | `test_ust_duzey_dizi_kabul_edilmez` |
| Markdown bloğundan ayıklama | `tests/ai/test_providers.py:502` | `test_markdown_kod_blogundan_ayiklanir` |
| Servis katmanı + kullanım kaydı | `tests/application/test_ai_service.py:350` | `test_gecersiz_json_anlasilir_hata_uretir` |
| Yedeğe geçilmez | `tests/ai/test_registry.py:163` | `test_kalici_hatalarda_yedege_gecilmez` (`AIResponseFormatError`) |

### 4.13 Raporun boş veriyle oluşturulması — KAPSANIYOR

| Konu | Dosya:satır | Test |
|---|---|---|
| Boş veritabanında 9 rapor sorgusu | `tests/reporting/test_exporters.py:558` | `test_bos_veritabaninda_tum_raporlar_bos_ama_gecerli` |
| Boş veritabanında KPI sıfır | `tests/reporting/test_exporters.py:580` | `test_bos_veritabaninda_kpi_sifirdir` |
| Boş rapor üç biçimde dışa aktarılır | `tests/reporting/test_exporters.py:589` | `test_bos_rapor_ucu_de_disa_aktarilabilir` |
| Boş tablo → geçerli CSV | `tests/reporting/test_exporters.py:335` | `test_csv_bos_tabloda_gecerli_dosya_uretir` |
| Boş tablo → geçerli Excel | `tests/reporting/test_exporters.py:395` | `test_excel_bos_tabloda_gecerli_dosya_uretir` |
| Boş tablo → geçerli PDF | `tests/reporting/test_exporters.py:470` | `test_pdf_bos_tabloda_gecerli_dosya_uretir` |
| Sıfıra bölme yok | `tests/reporting/test_kpi.py:271` | `test_calculate_kpis_bos_veride_cokmez` |
| Boş envanterde RevPAR | `tests/reporting/test_kpi.py:145` | `test_revpar_bos_envanterde_sifir` |

### Sonuç tablosu

| # | Senaryo | Durum |
|---|---|---|
| 1 | Aynı odaya çakışan iki rezervasyon | KAPSANIYOR |
| 2 | İptal edilen rezervasyon | KAPSANIYOR |
| 3 | No-show | KAPSANIYOR |
| 4 | Erken giriş ve geç çıkış | KAPSANIYOR |
| 5 | Oda bakım nedeniyle satışa kapalı | KAPSANIYOR |
| 6 | Hatalı ödeme tutarı | KAPSANIYOR |
| 7 | Yetkisiz kullanıcı finans modülüne erişim | KAPSANIYOR |
| 8 | Yerel model çalışmaması | KAPSANIYOR |
| 9 | Bulut API zaman aşımı | KAPSANIYOR — yalnız ortak kod yolu üzerinden (4.9) |
| 10 | API kotası dolması | KAPSANIYOR |
| 11 | Geçersiz API anahtarı | KAPSANIYOR |
| 12 | Yapay zekâ geçersiz JSON döndürmesi | KAPSANIYOR |
| 13 | Rapor boş veriyle oluşturulması | KAPSANIYOR |

---

## 5. Statik analiz

### 5.1 ruff — **2 bulgu (temiz değil)**

```powershell
.\.venv\Scripts\ruff.exe check app tests --output-format=concise
```

Gerçek çıktı:

```
app\main.py:47:5: S110 `try`-`except`-`pass` detected, consider logging the exception
app\main.py:47:24: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
Found 2 errors.
[*] 1 fixable with the `--fix` option.
```

Çıkış kodu: `1`.

İlgili kaynak (`app/main.py:36-48`) — açılış hatasını dosyaya yazmayı deneyen
blok:

```python
    try:
        path = paths.DATA_ROOT / "startup_error.log"
        with path.open("a", encoding="utf-8") as handle:
            ...
    except Exception:  # noqa: BLE001 - hata yazarken hata verme
        pass
```

Değerlendirme:

- `RUF100` doğru bir uyarıdır: `BLE` kural ailesi `pyproject.toml:119`
  içindeki `select` listesinde yok, dolayısıyla `# noqa: BLE001` boşa
  yazılmış. `--fix` ile giderilebilir.
- `S110` ise bilerek yazılmış bir desendir: hata *günlüğe yazarken* oluşan
  hatayı yutmak amaçlıdır. Kurala uymak için ya `contextlib.suppress`
  kullanmak ya da bu dosya için `per-file-ignores` eklemek gerekir.
- **Bu iki bulgu CI'ı kırar:** `.github/workflows/ci.yml` "Lint (ruff)" adımı ruff adımını
  `continue-on-error` olmadan çalıştırır. `CONTRIBUTING.md:23` de ruff'ı
  zorunlu kapı sayar.

> Bu, raporun yazıldığı sırada bulunan **gerçek** durumdur. Depoda "ruff
> temiz" diyen daha eski commit mesajları vardır (`efb861d`); ruff 0.16.3 ile
> bugünkü çalıştırma bu iki bulguyu üretmektedir.

### 5.2 bandit — 0 orta/yüksek, 9 düşük

```powershell
.\.venv\Scripts\bandit.exe -q -c pyproject.toml -r app
```

Gerçek özet çıktısı:

```
Code scanned:
        Total lines of code: 35807
        Total lines skipped (#nosec): 0

Run metrics:
        Total issues (by severity):
                Undefined: 0
                Low: 9
                Medium: 0
                High: 0
        Total issues (by confidence):
                Undefined: 0
                Low: 0
                Medium: 2
                High: 7
```

Çıkış kodu `1` (bandit bulgu olduğunda 1 döner). Bulguların tamamı:

| Kural | Önem | Güven | Konum | Açıklama | Değerlendirme |
|---|---|---|---|---|---|
| B404 | Low | High | `app/devcenter/git_guard.py:21` | `subprocess` içe aktarımı | Kasıtlı — Git kontrol noktası için gerekli |
| B607 | Low | High | `app/devcenter/git_guard.py:100` | Kısmi yürütülebilir yol (`git`) | Kasıtlı, `pyproject.toml:165` içinde gerekçesiyle muaf |
| B603 | Low | High | `app/devcenter/git_guard.py:108` | `subprocess` çağrısı | Argümanlar sabit liste, `shell=False` |
| B404 | Low | High | `app/devcenter/terminal.py:24` | `subprocess` içe aktarımı | AI Geliştirme Merkezi'nin çekirdek yeteneği |
| B603 | Low | High | `app/devcenter/terminal.py:189` | `subprocess` çağrısı | Komut önce `CommandPolicy`'den geçer (bkz. `tests/devcenter/test_policy.py`) |
| B311 | Low | High | `app/infrastructure/seed/demo_data.py:2793` | Kriptografik olmayan `random` | Demo veri üreteci; belirlenimci olması **istenir** |
| B110 | Low | High | `app/main.py:47` | `try/except/pass` | 5.1'deki `S110` ile aynı satır |
| B105 | Low | Medium | `app/ui/i18n.py:157` | "Olası sabit parola: `Parola Degistir`" | **Yanlış pozitif** — arayüz menü metni |
| B105 | Low | Medium | `app/ui/i18n.py:277` | "Olası sabit parola: `Change Password`" | **Yanlış pozitif** — arayüz menü metni |

Yüksek veya orta önemde bulgu **yoktur**. `#nosec` ile bastırılmış hiçbir
satır yoktur (`Total lines skipped (#nosec): 0`) — yani bulgular gizlenerek
değil, gerçekten bulunmayarak sıfırdır.

### 5.3 pip-audit — **7 bilinen açık, 1 pakette**

```powershell
.\.venv\Scripts\pip-audit.exe --skip-editable
```

Gerçek çıktı:

```
Found 7 known vulnerabilities in 1 package

Name       Version Fix Versions ID
---------- ------- ------------ ----------------
setuptools 65.5.0  65.5.1       PYSEC-2022-43012
setuptools 65.5.0  65.5.1       PYSEC-2022-43012
setuptools 65.5.0  78.1.1       PYSEC-2025-49
setuptools 65.5.0  78.1.1       PYSEC-2025-49
setuptools 65.5.0  70.0.0       PYSEC-2026-1918
setuptools 65.5.0  83.0.0       PYSEC-2026-3447
setuptools 65.5.0  83.0.0       PYSEC-2026-3447

Name                             Skip Reason
-------------------------------- -------------------------------
akilli-konaklama-yonetim-sistemi distribution marked as editable
```

Çıkış kodu: `1`.

Tek etkilenen paket **`setuptools 65.5.0`**'dır ve bu, sanal ortamın
`python -m venv` tarafından kurulan varsayılan sürümüdür — uygulamanın
çalışma zamanı bağımlılığı değildir (`requirements.txt` içinde yer almaz).
Yine de kurulum makinesinde bulunduğu için güncellenmelidir:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade setuptools
```

`.github/workflows/ci.yml` pip-audit adımı pip-audit adımını bilinçli olarak
`continue-on-error: true` ile çalıştırır; gerekçesi dosyada yazılıdır:
bir bağımlılıkta açık çıkması PR'ı bloklamamalı ama görünür olmalıdır.

### 5.4 Diğer kapılar

| Araç | Durum | Not |
|---|---|---|
| `black --check` | Bu raporda **çalıştırılmadı** | `scripts/test.ps1:72` ve CI'da var |
| `mypy` | Bu raporda **çalıştırılmadı** | Zorunlu kapı değil: CI'da `continue-on-error: true` (`ci.yml` mypy adımı), `ROADMAP.md` maddesi 6 |
| `detect-secrets` | Bu raporda **çalıştırılmadı** | Yalnızca CI adımı (`ci.yml` detect-secrets adımı) |
| `alembic check` | Bu raporda **çalıştırılmadı** | CI'da göçlerin şemayla tutarlılığını doğrular (`ci.yml` göç adımı) |

---

## 6. Bilinen test boşlukları

Dürüstlük gereği: aşağıdakiler test edilmiyor ya da yetersiz test ediliyor.

1. **Uygulama açılış yolu hiç test edilmiyor.** `app/ui/login.py` (%0),
   `app/ui/main_window.py` (%0), `app/ui/first_run.py` (%0) ve
   `app/ui/pages/registry.py` (%0). Yani "uygulama açılıyor mu, giriş ekranı
   çalışıyor mu, sayfa kayıt defteri doğru sayfayı yüklüyor mu" sorularının
   otomatik yanıtı yoktur; yalnızca elle denenmiştir.

2. **`app/cli.py` %0.** `bootstrap`, `seed-demo`, `backup`, `restore`,
   `check-ai`, `doctor` komutlarının hiçbiri test edilmiyor. Yedekleme
   modülü de düşük: `app/infrastructure/backup.py` %20.9. Bu, **geri
   yükleme akışının doğrulanmadığı** anlamına gelir — `SECURITY.md` üretim
   öncesi listesinde "geri yükleme denendi" maddesinin neden elle yapılması
   gerektiği budur.

3. **AI Geliştirme Merkezi ekranı ve terminali.**
   `app/ui/pages/dev_center_page.py` %0, `app/devcenter/terminal.py` %29.7.
   Politika katmanı (`policy.py` %93.4) ve çalışma alanı
   (`workspace.py` %94.4) iyi test edilmiştir, ancak **komutu fiilen
   çalıştıran** katman değildir. Özellikle `_clean_environment()`
   (`app/devcenter/terminal.py:83`) — alt sürece gizli ortam değişkenlerinin
   geçirilmemesi — için **doğrudan bir test yoktur**. `tests/devcenter/`
   altında `test_terminal.py` dosyası bulunmamaktadır.

4. **Bulut sağlayıcılara karşı ağ hatası testi yok.** Zaman aşımı, kota ve
   kimlik hatası testleri LM Studio adaptörü üzerinden yazılmıştır. Ortak
   taban (`app/ai/base.py:373`) aynı olduğu için kod yolu kapsanır, fakat
   NVIDIA/Anthropic uç noktalarına karşı `respx` ile yazılmış eşdeğer bir
   hata testi yoktur. Ayrıca **hiçbir gerçek NVIDIA/Anthropic çağrısı
   yapılmamıştır** (`docs/ROADMAP.md`).

5. **Panel (dashboard) zayıf.** `app/application/services/dashboard_service.py`
   %39.5 ve `app/ui/pages/dashboard_page.py` %14.2. Panel KPI'larının
   doğruluğu esas olarak `tests/reporting/test_kpi.py` üzerinden dolaylı
   doğrulanıyor.

6. **Folyo diyaloğu %57.6.** `app/ui/dialogs/folio_dialog.py` en büyük
   test edilmemiş arayüz parçasıdır; para ayrıştırma fonksiyonu
   (`parse_amount`) test edilmiş, diyalog akışının kalanı edilmemiştir.

7. **Eşzamanlılık testi yok.** `ROADMAP.md` maddesi 1'de anlatılan
   `MAX()+1` numara üreteci yarışı, tek iş parçacıklı testlerle
   yakalanamaz. Aynı şekilde rezervasyon çakışmasının ikinci aşama
   (yazma sonrası) kontrolü de gerçek eşzamanlı yükle sınanmamıştır.

8. **Performans testi yok.** `ROADMAP.md` v1.0'da planlanan "10.000+
   rezervasyon" ölçümü yapılmamıştır. Demo veri 1246 kayıttır.

9. **Kullanıcı etkileşim akışları sınırlı.** Arayüz testleri ekranın
   açılması, veri yüklemesi, düğme etkinliği ve yetki maskelemesine
   odaklanır; uçtan uca tıklama senaryoları (rezervasyon oluştur → giriş
   yap → ücret ekle → tahsil et → çıkış yap) tek bir arayüz testinde
   birleştirilmemiştir. Bu akış yalnızca servis katmanında test edilir.

10. **`app/infrastructure/db/session.py` %27.4.** Veritabanı bağlantı
    kurulumu, PRAGMA ayarları ve WAL kipi yolu büyük ölçüde kapsam
    dışıdır.

---

## 7. Testleri çalıştırma

### Tam zincir (önerilen)

```powershell
.\scripts\test.ps1
```

Sırasıyla: `black` → `ruff --fix` → `mypy` → `pytest` → `bandit` →
`pip-audit`. Bir adım başarısız olsa bile sonrakiler çalışır ve sonda özet
gösterilir (`scripts/test.ps1:51-66`).

| Seçenek | Etkisi |
|---|---|
| `-Fast` | Yalnızca `pytest`; biçimlendirme, lint ve güvenlik atlanır |
| `-Coverage` | `htmlcov/index.html` üretir |
| `-Live` | `live` işaretli testi de çalıştırır (LM Studio açık olmalı) |
| `-NoFix` | `black`/`ruff` yalnızca denetler, düzeltme uygulamaz |

### Doğrudan pytest

```powershell
# Tüm testler (dış servis gerektirenler hariç)
.\.venv\Scripts\python.exe -m pytest -q --no-header -m "not live"

# Tek paket
.\.venv\Scripts\python.exe -m pytest -q -m "not live" tests/domain

# Tek test
.\.venv\Scripts\python.exe -m pytest tests/domain/test_availability.py::TestCakismaEngelleme::test_ayni_odaya_cakisan_rezervasyon_engellenir

# Kapsam
.\.venv\Scripts\python.exe -m pytest -q -m "not live" --cov=app --cov-report=term

# Yalnızca toplama (çalıştırmadan sayım)
.\.venv\Scripts\python.exe -m pytest --co -q -m "not live"
```

### İşaretler (marker)

`pyproject.toml:214` içinde tanımlıdır; `--strict-markers` açık olduğu için
tanımsız bir işaret yazım hatası sayılır ve test toplama başarısız olur.

| İşaret | Anlamı |
|---|---|
| `unit` | Hızlı, izole birim testi |
| `integration` | Veritabanı/servis entegrasyonu |
| `api` | FastAPI uç nokta testi |
| `ui` | PySide6 arayüz testi (`QT_QPA_PLATFORM=offscreen` gerekir) |
| `ai` | Yapay zekâ sağlayıcı testi (taklit) |
| `live` | **Gerçek dış servis gerektirir** — varsayılan olarak atlanır |
| `slow` | Uzun süren test |

### Sürekli tümleştirme

`.github/workflows/ci.yml` Windows üzerinde Python 3.11 ve 3.12 ile
çalışır. Hedef platform Windows olduğu için Linux koşucusu bilinçli olarak
kullanılmaz (gerekçe dosyanın başında yazılıdır). CI'daki zorunlu adımlar:
`black --check`, `ruff check`, `alembic upgrade head` + `alembic check`,
`pytest`, `bandit`, `detect-secrets` ve "depoda hassas dosya var mı"
kontrolü. `mypy` ve `pip-audit` bilgi amaçlıdır.

---

## İlgili belgeler

| Belge | İçerik |
|---|---|
| [SECURITY_REVIEW](SECURITY_REVIEW.md) | Güvenlik iddialarının kanıtlı incelemesi |
| [ROADMAP](ROADMAP.md) | Yapılmamış işler ve bilinen teknik eksikler |
| [CONTRIBUTING](../CONTRIBUTING.md) | Kalite zinciri ve kod standartları |
| [SECURITY](../SECURITY.md) | Güvenlik politikası ve açık bildirimi |
