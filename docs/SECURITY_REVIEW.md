# Güvenlik İncelemesi

`SECURITY.md` bir **politika** belgesidir: neyin yapılması gerektiğini söyler.
Bu belge ise bir **inceleme raporudur**: o politikanın kodda gerçekten
uygulanıp uygulanmadığını satır satır doğrular.

Her iddia üç şeyle desteklenir:

1. **Uygulama** — hangi dosyanın hangi satırında yapıldığı
2. **Test** — hangi testin bunu koruduğu
3. **Doğrulama** — okuyucunun kendi makinesinde çalıştırabileceği komut

Doğrulanamayan hiçbir şey "uygulandı" diye yazılmamıştır. Doğrulama sırasında
bulunan **tutarsızlıklar ve zayıflıklar 9. bölümde** açıkça listelenmiştir.

| | |
|---|---|
| İnceleme tarihi | 2026-08-15 |
| Depo durumu | `main`, `93ab8b7` |
| İnceleme türü | Kaynak kod okuma + test çalıştırma + statik analiz |
| **Bağımsız sızma testi** | **YAPILMADI** |
| Test sonucu | 985 test geçiyor (bkz. [TEST_REPORT](TEST_REPORT.md)) |

> Bu bir iç incelemedir; kodu yazan tarafın kendi doğrulamasıdır. Bağımsız bir
> güvenlik denetiminin yerini **tutmaz**.

---

## 1. Kimlik doğrulama

### 1.1 Parola saklama — Argon2id

**Uygulama.** Parametreler `app/core/config.py:130-133` içinde tanımlıdır:

```python
    # Argon2id parametreleri - OWASP 2024 onerilerine yakin, masaustu icin dengeli.
    argon2_time_cost: int = Field(default=3, ge=1, le=10)
    argon2_memory_cost: int = Field(default=65536, ge=8192, le=1048576)
    argon2_parallelism: int = Field(default=2, ge=1, le=16)
```

`app/security/passwords.py:90-99` bu değerleri `PasswordHasher`'a geçirir:

```python
    return PasswordHasher(
        time_cost=security.argon2_time_cost,
        memory_cost=security.argon2_memory_cost,
        parallelism=security.argon2_parallelism,
        hash_len=32,
        ...
```

| Parametre | Değer | Değerlendirme |
|---|---:|---|
| `time_cost` (t) | 3 | OWASP asgarisi (t=2, m=19 MiB) üzerinde |
| `memory_cost` (m) | 65 536 KiB = **64 MiB** | OWASP'ın 19 MiB asgarisinin ~3,4 katı |
| `parallelism` (p) | 2 | Masaüstü için makul |
| `hash_len` | 32 bayt | Standart |

Değerler `ge`/`le` sınırlarıyla korunmuştur: yapılandırmayla `memory_cost`
8 MiB'nin altına indirilemez.

**Testler.**

| Ne doğrulanıyor | Dosya:satır |
|---|---|
| Hash düz parolayı içermez | `tests/security/test_passwords.py:23` |
| Aynı parola farklı hash üretir (tuz) | `tests/security/test_passwords.py:30` |
| Doğru/yanlış parola ayrımı | `tests/security/test_passwords.py:34`, `:38` |
| Bozuk hash istisna sızdırmaz | `tests/security/test_passwords.py:46` |
| Unicode normalleştirme | `tests/security/test_passwords.py:51` |

**Doğrulama.**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/security/test_passwords.py
.\.venv\Scripts\python.exe -c "from app.security.passwords import hash_password; print(hash_password('DenemeParola2026')[:32])"
# Cikti '$argon2id$v=19$m=65536,t=3,p=2$...' ile baslamalidir
```

### 1.2 Parola politikası

**Uygulama.** `app/security/passwords.py:162-201`. Asgari uzunluk
`app/core/config.py:128` ile gelir (`password_min_length`, varsayılan **10**).

| Kural | Satır |
|---|---|
| En az `min_length` karakter | `passwords.py:185` |
| En fazla 128 karakter | `passwords.py:187` |
| En az bir harf (Türkçe harfler dahil) | `passwords.py:189` |
| En az bir rakam | `passwords.py:191` |
| Yaygın parola listesinde olmama | `passwords.py:193` (`COMMON_PASSWORDS`, `passwords.py:33`) |
| Kullanıcı adını içermeme | `passwords.py:198` |
| En az 4 farklı karakter | `passwords.py:200` |

**Testler.** `tests/security/test_passwords.py:59-86` (`TestParolaPolitikasi`):
`test_zayif_parolalar_reddedilir` parametriktir,
`test_kullanici_adini_iceren_parola_reddedilir` ve
`test_asiri_uzun_parola_reddedilir` ayrı ayrı yazılmıştır.

**Üretilen parolalar.** `passwords.py:204` (`generate_password`) `secrets`
modülünü kullanır, 12 karakterin altına izin vermez ve karıştırılabilir
karakterleri (`l`, `I`, `O`, `0`, `1`) alfabeden çıkarır. Yönetici hesabı
kurulurken parola verilmezse **20 karakterlik** rastgele parola üretilir
(`app/security/bootstrap.py:167`). Test: `test_passwords.py:90`
(`test_uretilen_parola_politikayi_gecer`).

### 1.3 Kaba kuvvet koruması

**Uygulama.** `app/security/auth.py:111-118`:

```python
    stored_hash = user.password_hash if user is not None else _dummy_hash()
    password_ok = verify_password(password, stored_hash)
    ...
            user.failed_login_count += 1
            if user.failed_login_count >= settings.max_failed_logins:
                user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
```

Varsayılanlar `app/core/config.py:126-127`: **5 başarısız deneme**,
**15 dakika kilit**. Kilit süresi `auth.py:103` içinde kullanıcıya kalan
dakika olarak bildirilir. Başarılı girişte sayaç ve kilit sıfırlanır
(`auth.py:134-135`).

**Testler.**

```python
class TestKabaKuvvetKorumasi:
    def test_ardisik_hatali_denemede_hesap_kilitlenir(self, secured_session, admin_user):
        for _ in range(5):
            with pytest.raises(AuthenticationError):
                auth.authenticate(secured_session, "admin", "YanlisParola123")

        # Artik dogru parolayla bile giremez.
        with pytest.raises(AccountLockedError) as hata:
            auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        assert "kilitlendi" in hata.value.user_message
```

`tests/security/test_auth.py:77` ve `:87`
(`test_basarili_giris_sayaci_sifirlar`).

### 1.4 Kullanıcı sayımının (user enumeration) engellenmesi

**Uygulama.** `app/security/auth.py:48-54` ve `:111`. Kullanıcı yoksa
**kukla bir hash** üzerinde doğrulama yapılır; böylece "kullanıcı yok"
durumu ile "parola yanlış" durumu arasında ölçülebilir bir zaman farkı
oluşmaz:

```python
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("zamanlama-saldirisi-onleyici-kukla-deger")
    return _DUMMY_HASH
```

**Test.** `tests/security/test_auth.py:44`:

```python
    def test_olmayan_kullanici_ayni_hatayi_verir(self, secured_session, admin_user):
        """Kullanici sayimi engellenmeli: iki durum ayni mesaji dondurmeli."""
        with pytest.raises(AuthenticationError) as yok:
            auth.authenticate(secured_session, "boyle-biri-yok", "HerhangiBir123")
        with pytest.raises(AuthenticationError) as yanlis:
            auth.authenticate(secured_session, "admin", "YanlisParola123")
        assert yok.value.user_message == yanlis.value.user_message
```

> **Kısıt:** Test yalnızca **mesajların aynı olduğunu** doğrular; zaman farkının
> istatistiksel olarak ölçüldüğü bir test yoktur. Kukla hash kod düzeyinde
> mevcuttur ancak zamanlama eşitliği ölçülmemiştir.

### 1.5 Oturum yönetimi

**Uygulama.**

| Önlem | Konum |
|---|---|
| Jeton veritabanında SHA-256 özeti olarak saklanır | `app/security/auth.py:148`, `app/security/passwords.py:233` |
| Jeton `secrets.token_urlsafe(48)` ile üretilir | `app/security/passwords.py:228` |
| Oturum çözümü özet üzerinden yapılır | `app/security/auth.py:218` |
| Çıkışta oturum geçersizleşir | `app/security/auth.py:239` |
| Tüm oturumlar iptal edilebilir | `app/security/auth.py:262` |
| Parola değişimi tüm oturumları kapatır | `app/security/auth.py:294` |
| Süresi dolan oturumlar temizlenir | `app/security/auth.py:280` |
| Zaman aşımı 30 dk (yapılandırılabilir) | `app/core/config.py:125` |

Argon2 yerine SHA-256 seçiminin gerekçesi kodda yazılıdır
(`passwords.py:233-240`): jeton zaten yüksek entropili rastgele bir
değerdir, sözlük saldırısına açık değildir ve her istekte doğrulanacağı
için hızlı olmalıdır.

**Testler.** `tests/security/test_auth.py:99-155` (`TestOturum`, 8 test) ve
`:211` (`TestOturumTemizligi`). En kritiği:

```python
    def test_jeton_veritabaninda_duz_saklanmaz(self, secured_session, admin_user):
        """Veritabani sizsa bile aktif oturumlar ele gecirilememeli."""
        sonuc = auth.authenticate(secured_session, "admin", ADMIN_PAROLA)
        oturum = secured_session.get(UserSession, sonuc.session_id)
        assert oturum is not None
        assert oturum.token_hash != sonuc.token
        assert sonuc.token not in oturum.token_hash
```

**Doğrulama.**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/security/test_auth.py
# 24 passed
```

---

## 2. Yetkilendirme (RBAC)

### 2.1 İzin kataloğu — ölçülmüş sayı: **72 izin, 7 rol**

```powershell
.\.venv\Scripts\python.exe -c "from app.security.permissions import PERMISSIONS, DEFAULT_ROLES; print(len(PERMISSIONS), len(DEFAULT_ROLES))"
# 72 7
```

> **Tutarsızlık.** `SECURITY.md:31` ve `76cb23f` commit mesajı **78 izin**
> demektedir; kodda **72** vardır. Kod doğrudur, belge eskimiştir.
> Düzeltilmesi gereken bir belge hatasıdır (bkz. 9. bölüm, madde 1).

Kategoriye göre dağılım (`permissions_by_category()` çıktısı):

| Kategori | İzin | Kategori | İzin |
|---|---:|---|---:|
| Panel | 1 | Kat Hizmetleri | 5 |
| Tesis | 2 | Teknik Servis | 4 |
| Oda | 4 | Personel | 3 |
| Fiyat | 2 | Stok | 6 |
| Rezervasyon | 5 | Rapor | 3 |
| Misafir | 7 | Yapay Zeka | 4 |
| Ön Büro | 3 | Geliştirme | 3 |
| **Finans** | **12** | Sistem | 8 |

### 2.2 Rol matrisi

`DEFAULT_ROLES` (`app/security/permissions.py`) — ölçülmüş değerler:

| Rol kodu | Ad | İzin sayısı | Sistem rolü |
|---|---|---:|---|
| `admin` | Sistem Yöneticisi | 72 (tümü) | Evet |
| `manager` | Otel Müdürü | 64 | Evet |
| `frontdesk` | Ön Büro Görevlisi | 24 | Evet |
| `accounting` | Muhasebe | 22 | Evet |
| `housekeeping` | Kat Hizmetleri | 14 | Evet |
| `maintenance` | Teknik Servis | 13 | Evet |
| `viewer` | Görüntüleyici | 11 | Evet |

Dikkat çeken iki tasarım kararı, testle korunuyor:

- Müdür rolü **Geliştirme Merkezi'ne erişemez**:
  `tests/security/test_permissions.py:51` —
  `test_mudur_rolu_gelistirme_merkezine_erisemez`
- Görüntüleyici rolü **hiçbir yazma yetkisi taşımaz**:
  `tests/security/test_permissions.py:42` —
  `test_goruntuleyici_rolu_yazma_yetkisi_icermez`

Joker izin desteği (`reservation.*`) vardır ve modül sınırını aşmadığı
test edilmiştir (`tests/security/test_auth.py:182`):

```python
        assert kullanici.has_permission(Perm.RESERVATION_CREATE)
        assert kullanici.has_permission(Perm.RESERVATION_CANCEL)
        assert not kullanici.has_permission(Perm.FINANCE_MANAGE)
```

Pasif rol izin vermez (`test_auth.py:204`).

### 2.3 Kontrol iki katmanda birden yapılır

**Servis katmanı.** `app/application/context.py:39`:

```python
    def require(self, permission: str) -> None:
        """Kullanicinin izni yoksa hata firlatir ve denetime yazar."""
        if self.system:
            return

        if self.user is None:
            raise AuthorizationError(...)

        if not self.user.has_permission(permission):
            audit.record(
                self.session,
                action=AuditAction.PERMISSION_DENIED,
                ...
```

Servis dosyalarında **61 adet** `ctx.require(...)` çağrısı vardır:

```powershell
Get-ChildItem app\application\services\*.py | ForEach-Object { (Select-String -Path $_ -Pattern '\.require\(' -AllMatches).Matches.Count } | Measure-Object -Sum
```

| Servis | `require` sayısı |
|---|---:|
| `guest_service.py` | 12 |
| `frontdesk_service.py` | 9 |
| `housekeeping_service.py` | 9 |
| `maintenance_service.py` | 9 |
| `folio_service.py` | 8 |
| `reservation_service.py` | 8 |
| `ai_service.py` | 4 |
| `dashboard_service.py` | 2 |
| **Toplam** | **61** |

**Arayüz katmanı.** `app/application/context.py:62` (`can`) ve
`app/ui/session.py:101` düğme etkinliği için kullanılır; `app/ui` içinde
**58 adet** `.can(...)` çağrısı vardır. Arayüz kontrolü *ek* bir
kolaylıktır, güvenlik sınırı değildir — servis çağrısı ayrıca reddeder.

### 2.4 Kritik senaryo: finans modülüne yetkisiz erişim

`tests/security/test_auth.py:159`:

```python
    def test_yetkisiz_kullanici_finans_modulune_erisemez(self, secured_session, frontdesk_user):
        """KRITIK: on buro personeli mali raporlari goremez."""
        assert not frontdesk_user.has_permission(Perm.REPORT_FINANCIAL)
        with pytest.raises(AuthorizationError) as hata:
            auth.require_permission(frontdesk_user, Perm.REPORT_FINANCIAL)
        assert hata.value.permission == Perm.REPORT_FINANCIAL
```

Aynı senaryo diğer katmanlarda:

| Katman | Dosya:satır |
|---|---|
| Servis (ücret geçersiz kılma) | `tests/application/test_frontdesk_service.py:285` |
| Arayüz — rapor listesinde görünmez | `tests/ui/test_reports_ai_pages.py:194` |
| Arayüz — KPI kartı maskelenir | `tests/ui/test_reports_ai_pages.py:207` |
| Denetime yazılır | `tests/application/test_reservation_service.py:535` |

**Doğrulama.**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/security/test_permissions.py tests/security/test_auth.py
# 37 passed
```

---

## 3. Kişisel veri (KVKK)

### 3.1 Şifreleme kanıtı — ham SQL testi

Bu, belgedeki en güçlü kanıttır: kimlik numarasının diskte düz metin
olmadığı, ORM'i devre dışı bırakıp **ham SQL** ile okunarak doğrulanır.

`tests/infrastructure/test_encryption.py:68`:

```python
class TestVeritabaninaYazim:
    def test_kimlik_numarasi_diskte_duz_metin_degil(self, session, sample_guest):
        """KRITIK KVKK KONTROLU: ham SQL ile okundugunda numara gorunmemeli."""
        ham = session.execute(
            text("SELECT identity_number FROM guest WHERE id = :id"),
            {"id": sample_guest.id},
        ).scalar_one()

        assert ham is not None
        assert "11111111110" not in ham
        assert ham.startswith("enc:v1:")
```

Aynı dosyadaki tamamlayıcı testler:

| Ne doğrulanıyor | Satır |
|---|---|
| ORM üzerinden okununca çözülür | `:79` |
| Kör indeksle arama çalışır | `:85` |
| İkisi birlikte güncellenir | `:93` |
| Aynı değer farklı şifreli metin üretir (rastgele nonce) | `:33` |
| Şifresiz eski değerler bozulmadan geçer | `:37` |

**Uygulama.** `app/infrastructure/db/types.py:66` (`encrypt_value`) —
Fernet (AES-128-CBC + HMAC-SHA256), `enc:v1:` öneki çift şifrelemeyi
önler (`types.py:43`).

### 3.2 Kör indeks (blind index)

Şifreli sütunda `WHERE identity_number = ?` çalışmaz; çözüm HMAC-SHA256
tabanlı deterministik bir indeks sütunudur (`types.py:173`):

```python
    key_material = get_secret(FIELD_KEY_NAME) or os.environ.get(
        "HOTEL_FIELD_ENCRYPTION_KEY", "gelistirme-varsayilani"
    )
    digest = hmac.new(
        f"{key_material}:{salt}".encode(),
        value.strip().encode("utf-8"),
        hashlib.sha256,
    ).digest()
```

Testler: `test_encryption.py:47-64` (`TestKorIndeks`, 5 test) — aynı
değerin aynı indeksi ürettiği, farklı değerin farklı indeks ürettiği,
indeksin ham değeri içermediği, boşlukların önemsiz olduğu.

> **Zayıflık.** Anahtar bulunamazsa `"gelistirme-varsayilani"` sabiti
> kullanılır. Bu durumda kör indeks **kaynak kodunu okuyan herkes
> tarafından sözlük saldırısıyla çözülebilir** (11 haneli TCKN uzayı
> kaba kuvvete açıktır). `SECURITY.md:38`'in "sözlük saldırısına kapalı"
> ifadesi **yalnızca anahtar gerçekten ayarlıysa** doğrudur.
> Ayrıntı ve azaltma: 9. bölüm, madde 3.

### 3.3 Kimlik numarasını açık görmek ayrı yetkidir

**Uygulama.** `Perm.GUEST_VIEW_IDENTITY` (`app/security/permissions.py:57`).

**Testler** (`tests/application/test_guest_service.py`):

| Ne doğrulanıyor | Satır |
|---|---|
| Profil çağrısı varsayılan olarak maskeler | `:137` |
| Yetkisiz kullanıcı maskeli değer alır, denetim kaydı **oluşmaz** | `:161` |
| Yetkili kullanıcı açık değer alır, denetim kaydı oluşur | `:172` |
| Denetim açıklamasına numaranın kendisi yazılmaz | `:184` |
| **Her görüntüleme ayrı kayıt üretir** | `:187` |

```python
def test_every_reveal_creates_a_separate_audit_entry(...):
    """Her goruntuleme ayri kayit uretir - tek bir 'ilk erisim' kaydi yetmez."""
    service.reveal_identity(crm_guest.id)
    service.reveal_identity(crm_guest.id)

    assert len(_audit_reads(admin_ctx.session)) == 2
```

Arayüz tarafı: `tests/ui/test_guests_settings_pages.py:220` (maskeli
görünür), `:228` (yetkisizde "Göster" pasif), `:238` (göster → açık değer
+ denetim kaydı), `:362` (düzenleme kipinde alan boş gelir — mevcut değer
sızmaz).

### 3.4 Yapay zekâya gönderilen metin maskelenir

**Testler.** `tests/application/test_ai_service.py:177`
(`test_serbest_metinde_iletisim_bilgisi_maskelenir`), `:199`
(`test_maskeleme_para_tutarlarini_bozmaz` — maskeleme yanlışlıkla
tutarları bozmamalı), `:205` (`test_maskeleme_gercek_verileri_yakalar`).

Ayrıca sohbet geçmişi **sahiplik kontrolünden** geçer
(`app/application/services/ai_service.py:991`):

```python
        if conversation is None or conversation.user_id != self.ctx.user_id:
            return []
```

Test: `tests/application/test_ai_service.py:486` —
`test_baskasinin_sohbeti_okunmaz`; başkasının mesajının modele giden
istemde **bulunmadığını** doğrular.

**Doğrulama.**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/infrastructure/test_encryption.py tests/application/test_guest_service.py
# 49 passed
```

---

## 4. Sır yönetimi

### 4.1 Çözümleme sırası

**Uygulama.** `app/core/secret_store.py:113` (`get_secret`):

1. **keyring** (Windows Credential Manager) — `secret_store.py:124-131`
2. **Ortam değişkeni / `.env`** — `secret_store.py:133-136`, yalnızca
   `allow_env=True` iken
3. Bulunamazsa `None` (`:138`); `require_secret` (`:141`) anlamlı bir
   `ConfigurationError` üretir ve **çözüm önerisini** taşır

`set_secret` (`:158`) keyring yoksa `SecretBackend.ENV` döner ve **değeri
yazmaz** — böylece kullanıcı "kaydedildi" sanmaz.

Veritabanı yalnızca `SecretRef` (`secret_store.py:67`) tutar; sınıfın
docstring'i açıktır: *"Bir sirra isaret eden referans. **Degerin kendisini
icermez.**"*

### 4.2 Hata mesajlarında anahtar değeri geçmez

`tests/ai/test_providers.py:675`:

```python
        assert hata.value.context["keyring_entry"] == "nvidia_api_key"
        # Hata ayrintisinda yalnizca sirrin ADI gecer, degeri degil.
        assert "nvapi" not in str(hata.value.detail or "")
```

### 4.3 Depoda sır yok — doğrulandı

```powershell
git ls-files | Select-String -Pattern '\.env|\.db$|\.sqlite|\.key$|secret'
```

Gerçek çıktı — **yalnızca iki satır**:

```
.env.example
app/core/secret_store.py
```

İlki şablondur (anahtar alanları boş), ikincisi kaynak kodudur. Depoda
`.env`, veritabanı dosyası, `.key` dosyası veya yedek **yoktur**. Takip
edilen toplam dosya sayısı: 176.

`.gitignore` ilgili satırları (gerçek içerik):

```
.env
.env.*
!.env.example
*.key
secrets/
client_secret*.json
*api_key*
*apikey*
...
*.db
*.sqlite
*.sqlite3
*.db-journal
*.db-wal
*.db-shm
backups/
logs/
*.log
```

Bu kural **CI'da da zorunludur** — `.github/workflows/ci.yml` "Depoda hassas dosya var mi" adımı
her koşuda `git ls-files` çıktısını tarar ve hassas dosya bulursa yapıyı
kırar:

```yaml
      - name: Depoda hassas dosya var mi
        shell: pwsh
        run: |
          $sizinti = git ls-files | Select-String -Pattern '(^|/)\.env$|\.db$|\.sqlite3?$|\.pem$|\.key$|^backups/|^logs/|^data/'
          if ($sizinti) { ... exit 1 }
```

Ayrıca `detect-secrets` taraması (`ci.yml` → "Gizli bilgi taramasi (detect-secrets)" adımı) bulgu varsa `exit 1`
verir.

**Doğrulama.**

```powershell
git ls-files | Select-String -Pattern '(^|/)\.env$|\.db$|\.sqlite3?$|\.pem$|\.key$|^backups/|^logs/'
# Cikti bos olmalidir
```

---

## 5. Loglama ve denetim

### 5.1 Otomatik maskeleme

**Uygulama.** `app/core/log.py` içinde altı desen tanımlıdır:

| Desen | Satır |
|---|---|
| API anahtarı | `log.py:46` |
| `Authorization: Bearer ...` | `log.py:51` |
| E-posta | `log.py:56` |
| TCKN (`\b[1-9][0-9]{10}\b`) | `log.py:61` |
| Kart numarası | `log.py:64` |
| Telefon | `log.py:69` |

`mask_text` (`log.py:97`) metin içinde, `mask_value` (`log.py:116`) sözlük
anahtarı adına göre maskeler ve **iç içe sözlükleri de** dolaşır
(`log.py:132`). Maskelenecek anahtar adları `SECRET_KEY_NAMES`
(`app/core/secret_store.py:31`, 17 ad) listesinden gelir.

**Testler** (`tests/infrastructure/test_encryption.py`):

| Ne doğrulanıyor | Satır |
|---|---|
| API anahtarı gizlenir | `:109` |
| E-posta kısaltılır (`a***@ornek.com`) | `:112` |
| Hassas alan adı tamamen maskelenir | `:115` |
| Zararsız alan değişmez | `:119` |
| İç içe sözlük maskelenir | `:122` |
| Kimlik numarası maskelenir (`123*****901`) | `:100` |
| Kısa değer tamamen maskelenir | `:103` |

### 5.2 Denetim günlüğü

**Uygulama.** `app/security/audit.py`. Modül docstring'i ilkeyi belirtir:
günlük **yalnızca eklenir** (append-only), kayıtlar güncellenmez ve
silinmez.

İki katmanlı koruma (`audit.py:25-48`):

```python
#: Denetim kaydina hicbir kosulda yazilmayacak alanlar.
_NEVER_LOG = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "token_hash",
        "api_key",
        "secret",
        "identity_number",
        "card_number",
    }
)
```

Bu alanlar **atılır**; kalan alanlar `mask_value` ile maskelenerek yazılır.
Yani "denetim izi tutalım" derken kimlik numarası kalıcı olarak diske
yazılmaz.

**Testler.**

| Olay | Dosya:satır |
|---|---|
| Başarılı giriş | `tests/security/test_auth.py:58` |
| Başarısız giriş | `tests/security/test_auth.py:66` |
| Yetki reddi | `tests/application/test_reservation_service.py:535` |
| Rezervasyon oluşturma | `tests/application/test_reservation_service.py:81` |
| Kimlik görüntüleme (her seferinde) | `tests/application/test_guest_service.py:187` |
| Yapay zekâ isteği | `tests/application/test_ai_service.py:274` |
| Geliştirme görevi başlatma | `tests/devcenter/test_session.py:290` |

---

## 6. AI Geliştirme Merkezi

Bu, projedeki **en yüksek riskli** yetenektir: yapay zekâya kod yazdırma ve
komut çalıştırma. Bu nedenle katmanlı savunma ile kurulmuş ve
`tests/devcenter` altında **138 test** yazılmıştır.

### 6.1 Komut politikası — 83 test

`tests/devcenter/test_policy.py`, saldırı testi olarak yazılmıştır.

**Tehlikeli komut varyantı sayısı — ölçülmüş: 45**

```powershell
.\.venv\Scripts\python.exe -m pytest --co -q "tests/devcenter/test_policy.py::TestYasakKomutlar::test_tehlikeli_komut_engellenir"
# 45 tests collected in 0.02s
```

Bu 45 varyant `tests/devcenter/test_policy.py:31-88` içinde kategorilere
ayrılmıştır:

| Kategori | Örnek varyantlar | Adet |
|---|---|---:|
| Toplu silme | `rm -rf /`, `Remove-Item -Recurse -Force C:\`, `format C:`, `diskpart`, `cipher /w:C` | 9 |
| Kayıt defteri | `reg add`, `reg delete`, `regedit /s`, `Set-ItemProperty HKLM:\...` | 4 |
| Kullanıcı yönetimi | `net user ... /add`, `net localgroup Administrators`, `New-LocalUser`, `icacls`, `takeown` | 5 |
| Sistem | `shutdown`, `Restart-Computer`, `bcdedit`, `Set-ExecutionPolicy Unrestricted`, `schtasks`, `vssadmin delete shadows`, `netsh firewall ... disable` | 7 |
| Uzaktan kod | `Invoke-Expression (New-Object Net.WebClient)...`, `iex (irm ...)`, `curl ... \| bash`, `powershell -enc`, `certutil -urlcache`, `bitsadmin /transfer` | 6 |
| Kimlik bilgisi | `Get-Credential`, `cmdkey /list` | 2 |
| Git tehlikeleri | `git push --force`, `git push origin main`, `git reset --hard HEAD~5`, `git clean -fdx`, `git filter-branch` | 5 |
| Kabuk karıştırma / arka plan | `cmd /c del *.py`, `cmd.exe /k format C:`, `Start-Job -ScriptBlock { rm -r . }` | 3 |
| **Sır sızdırma** | `Get-ChildItem env:`, `type .env`, `Get-Content .env`, `cat .env` | 4 |

Her varyant için doğrulanan (`test_policy.py:90`):

```python
    def test_tehlikeli_komut_engellenir(self, policy: CommandPolicy, command: str):
        decision = policy.evaluate(command)
        assert (
            decision.risk is RiskLevel.BLOCKED
        ), f"ENGELLENMESI GEREKEN KOMUT GECTI: {command!r} -> {decision.risk}"
        assert not decision.allowed
        assert decision.reason
```

Politikanın diğer test sınıfları:

| Sınıf | Ne koruyor | Satır |
|---|---|---|
| `TestSandboxKacisi` | Mutlak sistem yolu, `..` ile üst dizin, ağ paylaşımı (`\\`), sandbox dışı çalışma dizini | `:112` |
| `TestGuvenliKomutlar` | Salt okunur komutlar onaysız geçer | `:145` |
| `TestOnayGerektirenler` | Yazma komutu onay ister; **bilinmeyen komut sessizce çalışmaz** | `:169`, `:192` |
| `TestZincirlemeKomut` | `;`, `\|`, yönlendirme zinciri onay ister; tırnak içindeki `;` zincir sayılmaz | `:199` |
| `TestSirSizintisi` | Sır içeren komut uyarı üretir; dengesiz tırnak engellenir | `:224` |
| `TestBagimlilikKurulumu` | `pip install` **varsayılan kapalı** | `:235` |
| `TestRiskSeviyesi` | Yalnızca "güvenli" seviyesi onaysız | `:248` |
| Büyük/küçük harfle atlatma | `test_buyuk_kucuk_harf_atlatilamaz` | `:98` |

Temel tasarım kararı: **izin listesi önceliklidir**, yalnızca yasak liste
tutulmaz. Yalnızca yasak liste tutmak yetersizdir, çünkü listede olmayan bir
yolla aynı zarar verilebilir. Bilinmeyen komut asla sessizce çalışmaz.

### 6.2 Sandbox ve dosya koruması — 27 test

`app/devcenter/workspace.py:32` — `PROTECTED_PATHS` içinde `.env`, `.git`
ve devamı; `:45` `PROTECTED_SUFFIXES`. Çözümleme `workspace.py:191-202`
üç kontrol yapar: yol kökündeki ad, dosya adı ve uzantı.

Test: `tests/devcenter/test_workspace.py:42` —
`test_env_dosyasi_korunur`. Ayrıca `test_workspace.py`
`test_kismi_yazma_olmaz` ile dosya bu arada değiştiyse **kısmi yazma
olmadan** işlemin durduğunu doğrular.

### 6.3 Alt sürece sır geçirilmez

`app/devcenter/terminal.py:37-45`:

```python
#: Alt surece ASLA gecirilmeyecek ortam degiskeni kaliplari.
_SENSITIVE_ENV_MARKERS = (
    "API_KEY",
    "APIKEY",
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "CREDENTIAL",
    "HOTEL_FIELD_ENCRYPTION_KEY",
)
```

`terminal.py:83` (`_clean_environment`) bu kalıpları içeren tüm ortam
değişkenlerini eler ve alt sürece `HOTEL_DEVCENTER_CHILD=1` işareti bırakır.
Fonksiyonun docstring'i bunu "ikinci savunma katmanı" olarak tanımlar —
politika zaten `type .env` gibi komutları engeller.

> **Boşluk.** `tests/devcenter/` altında `test_terminal.py` **yoktur**;
> `_clean_environment()` için doğrudan bir test bulunmamaktadır.
> `app/devcenter/terminal.py` kapsamı **%29.7**'dir. Kod incelemeyle
> doğrulanmıştır, testle değil. Bkz. 9. bölüm, madde 4.

### 6.4 Git koruması

`app/devcenter/git_guard.py:35`:

```python
PROTECTED_BRANCHES = frozenset({"main", "master", "develop", "release"})
```

Bu dallara doğrudan işleme (`git_guard.py:332`) ve bu dalların silinmesi
(`:341`) reddedilir. Modül docstring'i (`git_guard.py:14`): *bu modül
hiçbir zaman `git push` yapmaz.* Kontrol noktası `git stash create` ile
alınır (`:186`), çünkü `git stash push` kullanıcının dosyalarını anında
geri alır ve kaybolmuş gibi görünürdü.

### 6.5 Oturum durum makinesi — 28 test

`tests/devcenter/test_session.py`:

| Ne doğrulanıyor | Satır |
|---|---|
| İkinci görev, birincisi sürerken başlamaz | `:125` |
| Onaylı birleştirme ayrı adımdır | `:229` |
| İptal değişiklikleri geri alır | `:246` |
| **Yetkisiz kullanıcı görev başlatamaz** | `:265` |
| **Yetkisiz kullanıcı komut çalıştıramaz** | `:274` |
| Görev başlatma denetime yazılır | `:290` |

### 6.6 Yapılandırma uyarıları

`app/core/config.py:439` — onay zorunluluğu kapatılmışsa başlangıçta uyarı
loglanır:

```python
        if not self.devcenter.require_approval:
            warnings.append(
                "AI Gelistirme Merkezi onay istemeden calisacak sekilde ayarlanmis. "
                "Bu ayar onerilmez."
            )
```

**Doğrulama.**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/devcenter
# 138 passed
```

---

## 7. Bağımlılık güvenliği

### 7.1 pip-audit — gerçek çıktı

```powershell
.\.venv\Scripts\pip-audit.exe --skip-editable
```

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

**Değerlendirme.**

- Etkilenen tek paket `setuptools 65.5.0`'dır. `requirements.txt` içinde
  **yer almaz**; `python -m venv` tarafından sanal ortama kurulan
  varsayılan sürümdür. Yani uygulamanın çalışma zamanı bağımlılığı değil,
  geliştirme ortamının bir parçasıdır.
- Yine de makinede bulunduğu için düzeltilmelidir:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade setuptools
.\.venv\Scripts\pip-audit.exe --skip-editable   # yeniden dogrulayin
```

- Uygulamanın kendi bağımlılıklarında (`requirements.txt`) bilinen açık
  **bulunmamıştır**.

### 7.2 bandit — 0 yüksek, 0 orta, 9 düşük

```powershell
.\.venv\Scripts\bandit.exe -q -c pyproject.toml -r app
```

```
Total lines of code: 35807
Total lines skipped (#nosec): 0
Total issues (by severity):  Low: 9   Medium: 0   High: 0
```

Dokuz bulgunun tamamı ve değerlendirmesi
[TEST_REPORT.md](TEST_REPORT.md) 5.2 bölümündedir. Özet: altısı AI
Geliştirme Merkezi'nin bilinçli `subprocess` kullanımı, biri demo veri
üretecinin `random` kullanımı, ikisi arayüz metnindeki "Parola Değiştir"
ifadesini parola sanan **yanlış pozitiftir**.

Önemli: **`#nosec` ile bastırılmış hiçbir satır yoktur** (`Total lines
skipped (#nosec): 0`). Yüksek/orta bulgu sıfırdır, çünkü gerçekten
yoktur — gizlendiği için değil.

### 7.3 Üçüncü parti kaynak kodu

`git log` (`09d5040`): *"Bu projede hicbir ucuncu parti kaynak kodu
kopyalanmamistir; yalnizca PyPI uzerinden standart bagimliliklar
kullanilmistir."* Lisans analizi
[GITHUB_RESEARCH.md](GITHUB_RESEARCH.md) ve
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) içindedir.

---

## 8. Bulunan ve düzeltilen güvenlik sorunları

Aşağıdakiler `git log` commit gövdelerinden alınmıştır. Hepsi **geliştirme
sırasında** bulunmuş ve düzeltilmiştir; her biri için bir gerileme testi
vardır.

### 8.1 Oda satışa kapatmada yetki boşluğu — `efb861d`

> *"Oda satisa kapatmada YETKI BOSLUGU: `set_room_status` yolu çakışan
> rezervasyon kontrolünü atlıyordu ve bu yol ön büro/kat hizmetleri
> rollerine açıktı. Artık o gecenin rezervasyonları taranıyor."*

**Etki.** Ön büro veya kat hizmetleri personeli, satılmış bir odayı
"servis dışı" işaretleyerek rezervasyon kontrolünü dolanabiliyordu.

**Gerileme testleri.**

- `tests/application/test_operations_services.py:351` —
  `test_satilmis_oda_servis_disi_yapilamaz`
- `tests/application/test_operations_services.py:367` —
  `test_force_ile_yetkili_servis_disi_yapabilir` (yalnızca yetkili
  kullanıcı aşabilir)
- `tests/application/test_operations_services.py:344` —
  `test_yetkisiz_kullanici_oda_durumu_degistiremez`
- `tests/ui/test_operations_pages.py:725` —
  `test_yetkisiz_kullanicida_bloke_secenegi_pasif`

### 8.2 Yapay zekâ sohbet geçmişinde sahiplik kontrolü yoktu — `efb861d`

> *"AI sohbet geçmişinde SAHİPLİK KONTROLÜ YOKTU; başkasının serbest metin
> sohbeti modele gidebilirdi."*

**Etki.** Sohbet numarası (`conversation_id`) tahmin edilerek başka bir
kullanıcının serbest metin yazışması modele gönderilebiliyordu.

**Düzeltme.** `app/application/services/ai_service.py:991` —
`conversation.user_id != self.ctx.user_id` ise boş liste döner.
Kod yorumu ayrıca *"boyle bir sohbet var ama sizin degil" demek de bilgi
sizdirir* diyerek ayrıştırılmış hata mesajı vermemeyi gerekçelendiriyor.

**Gerileme testi.** `tests/application/test_ai_service.py:486` —
`test_baskasinin_sohbeti_okunmaz`.

### 8.3 Komut politikasında iki gerçek atlatma — `16c599b`

> *"Testlerin ortaya çıkardığı iki gerçek açık düzeltildi: silme komutunda
> bayrak sırası değişince desen kaçıyordu; depo durum çıktısında boşluk
> kırpma sütun hizasını bozup hazırlanmış/değişmiş ayrımını tersine
> çeviriyordu."*

**Etki.** (1) `Remove-Item -Force -Recurse` gibi bayrak sırası değiştirilmiş
bir silme komutu politikadan geçebiliyordu. (2) `git status --porcelain`
çıktısındaki boşluk kırpma, hangi dosyanın hazırlandığı bilgisini ters
çeviriyordu.

**Gerileme testleri.** `tests/devcenter/test_policy.py:35-36` — hem
`Remove-Item -Recurse -Force C:\` hem `remove-item -recurse -force .`
varyantları listede; `test_policy.py:98` —
`test_buyuk_kucuk_harf_atlatilamaz`.

### 8.4 Mali tutarlılık hataları — `67bd605`

> *"Folyo bakiyesi EKSİK hesaplanıyordu... Aynı oda satırına ikinci kez
> giriş yapılabiliyordu... İptal edilmiş rezervasyon tekrar iptal edilip
> ceza iki kez hesaplanabiliyordu... Geçersiz tarih aralığı ham
> `ValueError` fırlatıyordu."*

Bunlar klasik "güvenlik açığı" değildir ancak **mali doğruluk** sorunudur
ve bir PMS'te aynı ağırlıktadır.

**Gerileme testleri.**

| Sorun | Test |
|---|---|
| Çifte iptal, çifte ceza | `tests/application/test_reservation_service.py:342` |
| Aynı odaya ikinci giriş | `tests/application/test_frontdesk_service.py` (`TestCheckIn`) |
| Folyo bakiyesi | `tests/infrastructure/test_seed.py:439` — `test_folio_bakiyeleri_tutarlidir` |
| Ham istisna sızması | `app/core/exceptions.py` katmanı, `tests/ui/test_frontdesk_page.py:659` |

### 8.5 Yedeğe geçişte anahtar hatasının gizlenmesi — `09c17fe`

> *"yedeğe geçiş yalnızca GEÇİCİ hatalarda; 401/404'te geçilmez"*

**Etki.** Geçersiz API anahtarında sessizce yedek sağlayıcıya geçilseydi,
kullanıcı anahtarının bozuk olduğunu asla öğrenmez, faturası artardı.

**Gerileme testi.** `tests/ai/test_registry.py:163`, docstring'iyle
birlikte: *"Anahtar hatasini yedekle gizlemek, kullanicinin sorunu
gormesini engeller."*

### 8.6 Modül adlandırma — `7a246c3`

> *"Modül adları bilerek `log`/`secret_store` seçildi: `logging.py` ve
> `secrets.py` standart kütüphaneyi gölgeleyip `ModuleNotFoundError`
> üretiyor."*

Bir güvenlik açığı değil, ama `secrets` modülünün gölgelenmesi kriptografik
rastgelelik kaynağını bozabileceği için burada anılmaya değer.

---

## 9. Kalan riskler ve azaltmalar

Bu bölüm dürüstlük bölümüdür. `SECURITY.md`'deki "Bilinen sınırlar"
listesini **doğrular ve genişletir**.

### 9.1 Belge–kod tutarsızlığı: izin sayısı — **GİDERİLDİ**

| | |
|---|---|
| **Durum** | **Kapatıldı.** `SECURITY.md` 72 yazacak şekilde düzeltildi ve
sayının nasıl ölçüleceği belgeye eklendi |
| **Bulgu (geçmiş)** | `SECURITY.md` "78 izin" diyordu; kodda 72 izin var |
| **Kanıt** | `python -c "from app.security.permissions import PERMISSIONS; print(len(PERMISSIONS))"` → `72` |
| **Risk** | Düşük — belge hatası, işlevsel açık değil. Ancak güvenlik belgesine güven zedelenir |
| **Azaltma** | `SECURITY.md` güncellenmeli. Daha iyisi: sayıyı belgeye gömmek yerine `permissions_by_category()` çıktısına atıf yapmak |

### 9.2 ruff kapısı — **GİDERİLDİ**

| | |
|---|---|
| **Durum** | **Kapatıldı.** `ruff check app tests` ve `black --check app tests`
temiz çıkıyor; sayı sunum üretilirken `sunum/olcum.py` tarafından ölçülür |
| **Bulgu (geçmiş)** | `ruff check app tests` bulgu veriyordu, çıkış kodu 1 |
| **Kanıt** | [TEST_REPORT.md](TEST_REPORT.md) 5.1 |
| **Risk** | Düşük–orta. Doğrudan bir açık değil, ama CI'daki zorunlu lint adımı (`ci.yml` → "Lint (ruff)" adımı) kırılır ve bu, gelecekteki gerçek lint bulgularının fark edilmesini geciktirir. `S110` (`try/except/pass`) kuralının kendisi bir güvenlik kuralıdır |
| **Azaltma** | `RUF100` için `ruff check app tests --fix`; `S110` için ya `contextlib.suppress(Exception)` kullanmak ya da `app/main.py` için gerekçeli `per-file-ignores` eklemek |

### 9.3 Kör indeks anahtarının varsayılan değeri — **GİDERİLDİ**

> Bu madde, açık **kapatıldıktan sonra** geçmiş zamanda yazılmıştır.
> Açığın ayrıntısını, düzeltilmemiş bir kodun yanında yayımlamak okuyucuya
> çalışan bir saldırı yolu vermek olurdu.

| | |
|---|---|
| **Durum** | **Kapatıldı.** Gömülü sabit yedek anahtar kaldırıldı.
`blind_index` artık anahtar materyali yoksa `ConfigurationError` fırlatır
(fail-closed). Yalnızca `HOTEL_APP_ENV=testing` altında sabit bir test
anahtarı kullanılır ve o anahtar gerçek veriye hiçbir zaman uygulanmaz.
Gerileme testleri: `tests/infrastructure/test_encryption_failclosed.py`
(`TestKorIndeksSabitYedekYok`) |
| **Bulgu (geçmiş)** | Anahtar bulunamazsa HMAC anahtarı kaynak koda gömülü bir sabitti |
| **Risk** | **Orta–yüksek.** Bu durumda kimlik numarası sütunu Fernet ile şifreli kalır, ancak **kör indeks sütunu** herkesin bildiği bir anahtarla üretilir. Veritabanı dosyasına erişen biri 11 haneli TCKN uzayını kaba kuvvetle tarayıp indeksleri eşleyebilir. `SECURITY.md:38`'in "sözlük saldırısına kapalı" ifadesi bu senaryoda **geçerli değildir** |
| **Ne zaman oluşur** | keyring kullanılamıyorsa (CI, headless, keyring arka ucu yoksa) **ve** `HOTEL_FIELD_ENCRYPTION_KEY` ayarlı değilse |
| **Azaltma** | Kurulumda `HOTEL_FIELD_ENCRYPTION_KEY` mutlaka ayarlanmalı; üretim öncesi kontrol listesine eklendi (10. bölüm). Kod tarafında daha iyi çözüm: varsayılana düşmek yerine **hata fırlatmak** (üretim ortamında) |
| **Doğrulama** | `.\.venv\Scripts\python.exe -c "from app.core.secret_store import get_secret, is_keyring_available; print('keyring:', is_keyring_available(), '| anahtar var mi:', bool(get_secret('field_encryption_key')))"` |

### 9.4 Alan şifreleme anahtarı kalıcı olmayabilir — **GİDERİLDİ**

| | |
|---|---|
| **Durum** | **Kapatıldı.** Anahtar kalıcı olarak yazılamıyorsa uygulama
artık sessizce yeni anahtar üretmez: `ConfigurationError` fırlatır. Çözülemeyen
bir kayıt için `decrypt_value` boş dizge **döndürmez**, `DecryptionError`
fırlatır ve kullanıcıya "bu kaydın üzerine yazmayın" der. Durum, veri
girilmeden önce `encryption_key_status()` ile sorulabilir. Gerileme testleri:
`tests/infrastructure/test_encryption_failclosed.py` |
| **Bulgu (geçmiş)** | keyring yoksa anahtar yazılmadan `SecretBackend.ENV` dönüyor, her açılışta yeni anahtar üretiliyor ve çözülemeyen kayıtlar sessizce boşalıyordu (veri kaybı) |
| **Risk** | **Yüksek (veri kaybı).** keyring'siz bir ortamda her uygulama başlangıcı yeni bir anahtar üretir. Önceki oturumda şifrelenen kimlik numaraları çözülemez; `decrypt_value` (`types.py:86-90`) `InvalidToken` yakalayıp **boş dizge** döner — yani veri sessizce kaybolur, yalnızca `alan_sifre_cozme_basarisiz` log kaydı bırakır |
| **Azaltma** | Kurulumda keyring'in çalıştığı doğrulanmalı (`hotel doctor`). Anahtar mutlaka ayrıca yedeklenmeli. `backup.ps1` **anahtarı yedeklemez** — bu, `SECURITY.md` "Bilinen sınırlar" maddesi 1'de zaten belirtilmiştir |

### 9.11 Komut politikası yalnızca komutun adına bakıyordu — **GİDERİLDİ**

> Bağımsız bir yayın öncesi incelemede üretilerek doğrulandı ve kapatıldı.
> Madde, açık **kapatıldıktan sonra** yazılmıştır.

| | |
|---|---|
| **Durum** | **Kapatıldı.** Karar artık komutun adına değil, **dokunduğu dosyaya** bakıyor: `app/devcenter/policy.py` içindeki `SENSITIVE_TARGETS` listesi ve `_check_sensitive_targets`, izin listesi değerlendirmesinden **önce** çalışır. `.env` (ve türevleri), anahtar/sertifika dosyaları, kimlik bilgisi depoları, `.secrets.baseline` ve misafir veritabanı/yedekleri **hangi okuyucu kullanılırsa kullanılsın** kapalıdır. `.env.example` bir şablondur ve açık bırakılmıştır |
| **Bulgu (geçmiş)** | Yasak listesi yalnızca üç okuyucuyu (`type`, `get-content`, `cat`) `.env` için engelliyordu; `head`, `tail`, `findstr`, `select-string` ise **SAFE** sınıftaydı — yani onay sorulmadan çalışıyordu. Aynı değerlendirme misafir veritabanının okunmasını da "güvenli" sayıyordu |
| **İkinci yarı** | Çıktı maskeleyicisi yalnızca önekli anahtarları (`sk-`, `nvapi-`) ve sabit bir ad listesini tanıyordu; oturum imzalama anahtarı gibi **öneksiz** uzun dizgeler maskelenmeden geçiyordu. `app/core/log.py` içine `_SECRET_ASSIGNMENT_PATTERN` eklendi: adı sır-benzeri olan her atamanın değeri, biçiminden bağımsız maskelenir |
| **Gerileme testleri** | `tests/devcenter/test_policy.py::TestHassasDosyaOkumaGerilemesi` (dokuz okuyucu × iki hedef sınıfı, artı yol biçimleri ve ortam değişkeni dökümü) ve `tests/infrastructure/test_encryption_failclosed.py::TestLogMaskelemeOneksizAnahtarlar` |
| **Kalan sınır** | Koruma dosya **hedefine** bakar. Bir komut hedefi çalışma anında üretirse (ör. bir betiğin içinden okuma) politika bunu göremez; bu yüzden bilinmeyen komutlar hâlâ onay ister ve `python -c` gibi çalıştırıcılar izin listesinde değildir |

### 9.5 AI Geliştirme Merkezi terminali test edilmiyor

| | |
|---|---|
| **Bulgu** | `tests/devcenter/test_terminal.py` yok; `app/devcenter/terminal.py` kapsamı %29.7. `_clean_environment()` (`terminal.py:83`) için doğrudan test bulunmuyor |
| **Risk** | Orta. Politika katmanı (%93.4) ve çalışma alanı (%94.4) iyi test edilmiştir; ancak komutu **fiilen çalıştıran** ve ortamı temizleyen katman testsizdir. Bir gerileme sessizce girebilir |
| **Azaltma** | `_clean_environment()` için bir test yazmak ucuz ve yüksek değerlidir: sahte bir `HOTEL_TEST_API_KEY` ortam değişkeni koyup çıktının içermediğini doğrulamak yeterlidir |

### 9.6 Açılış ve kimlik doğrulama arayüzü test edilmiyor

| | |
|---|---|
| **Bulgu** | `app/ui/login.py` %0, `app/ui/main_window.py` %0, `app/ui/first_run.py` %0, `app/cli.py` %0 |
| **Risk** | Orta. Kimlik doğrulama **mantığı** (`app/security/auth.py` %91.6) iyi test edilmiştir; test edilmeyen kısım o mantığı çağıran ekrandır. Giriş ekranındaki bir hata (örn. hatalı deneme sayacının çağrılmaması) testle yakalanmaz |
| **Azaltma** | Giriş ekranı için offscreen smoke testi yazmak; en azından "yanlış parola → hata, 5 deneme → kilit mesajı" akışı |

### 9.7 SQLite dosya sistemi izinlerine güvenir

`SECURITY.md` "Bilinen sınırlar" maddesi 2'de belirtilmiştir ve
**doğrulanmıştır**: şifreleme yalnızca `EncryptedString` kullanan alanlara
uygulanır (kimlik/pasaport numarası). Misafir adı, telefonu, e-postası,
konaklama geçmişi ve mali kayıtlar **düz metindir**. Veritabanı dosyasına
erişimi olan biri bunları okuyabilir.

**Azaltma.** Veritabanı dosyası yalnızca uygulama kullanıcısının
erişebildiği bir klasörde tutulmalı; çok kullanıcılı kurulumda PostgreSQL
ve disk şifrelemesi (BitLocker) kullanılmalıdır.

### 9.8 Eşzamanlılık

`ROADMAP.md` maddesi 1'de belirtilen `MAX()+1` numara üreteci yarışı
**doğrulanmıştır**. Rezervasyon çakışma kontrolü iki aşamalıdır
(`67bd605`: *"cakisma kontrolu IKI asamali (yazmadan once kullaniciya
anlamli hata, yazdiktan sonra yaris kosulu korumasi)"*), ancak bu koruma
**eşzamanlı yükle sınanmamıştır**. Tek iş parçacıklı testler yarış
koşullarını yakalayamaz.

### 9.9 Bağımsız denetim ve sızma testi yapılmadı

Bu belgedeki tüm doğrulamalar kodu yazan tarafın kendi incelemesidir.
Otomatik taramalar (bandit, pip-audit, detect-secrets) ve 985 test
mevcuttur; **bağımsız bir güvenlik denetimi veya sızma testi
yapılmamıştır.** `ROADMAP.md` v1.0 planında yer alır.

### 9.10 Tamamlanmamış yasal entegrasyonlar

e-Fatura, e-Arşiv ve Kimlik Bildirim Sistemi (KBS) **yalnızca veri modeli
düzeyindedir**. KVKK, vergi ve KBS yükümlülüklerine uyum sorumluluğu
işletmeye aittir. Bkz. [ROADMAP.md](ROADMAP.md) ve README "Yasal uyarı".

### Risk özeti

| # | Risk | Seviye | Durum |
|---|---|---|---|
| 9.4 | Şifreleme anahtarının kalıcı olmaması → veri kaybı | Yüksek | Belgelendi, azaltma kurulum adımında |
| 9.3 | Kör indeks varsayılan anahtarı | Orta–yüksek | Belgelendi, kontrol listesine eklendi |
| 9.5 | Devcenter terminali testsiz | Orta | Açık boşluk |
| 9.6 | Giriş/açılış arayüzü testsiz | Orta | Açık boşluk |
| 9.7 | Şifrelenmemiş kişisel alanlar | Orta | Tasarım kararı, belgelendi |
| 9.8 | Eşzamanlılık yarışları | Orta | `ROADMAP` v0.2 |
| 9.9 | Bağımsız denetim yok | Orta | `ROADMAP` v1.0 |
| 9.2 | ruff kapısı kırık | Düşük–orta | Kolay düzeltilir |
| 9.1 | Belgede yanlış izin sayısı | Düşük | Kolay düzeltilir |

---

## 10. Üretim öncesi kontrol listesi

`SECURITY.md`'deki liste **temeldir**; aşağıdaki bu incelemenin bulgularıyla
genişletilmiş sürümdür. Her madde için doğrulama komutu verilmiştir.

### 10.1 Sırlar ve anahtarlar

- [ ] `HOTEL_SECRET_KEY` varsayılan değerden değiştirildi
  ```powershell
  .\.venv\Scripts\python.exe -c "from app.core.config import get_settings; print('GUVENSIZ' if get_settings().security.uses_default_secret else 'ozellestirilmis')"
  ```
- [ ] **`HOTEL_FIELD_ENCRYPTION_KEY` ayarlandı veya keyring çalışıyor** *(yeni — 9.3, 9.4)*
  ```powershell
  .\.venv\Scripts\python.exe -c "from app.core.secret_store import get_secret, is_keyring_available; print('keyring:', is_keyring_available(), '| anahtar:', bool(get_secret('field_encryption_key')))"
  ```
- [ ] Alan şifreleme anahtarı **veritabanından ayrı** bir yerde yedeklendi
      (`backup.ps1` anahtarı yedeklemez)
- [ ] API anahtarları keyring'e yazıldı, `.env` içinde bırakılmadı
- [ ] Depoda hassas dosya yok
  ```powershell
  git ls-files | Select-String -Pattern '(^|/)\.env$|\.db$|\.sqlite3?$|\.pem$|\.key$|^backups/|^logs/'
  ```

### 10.2 Ortam ve yapılandırma

- [ ] `HOTEL_APP_ENV=production`, `HOTEL_APP_DEBUG=false`
- [ ] Başlangıç uyarıları temiz *(yeni)*
  ```powershell
  .\.venv\Scripts\python.exe -c "from app.core.config import get_settings; [print('UYARI:', w) for w in get_settings().startup_warnings()]"
  ```
- [ ] API sunucusu yalnızca `127.0.0.1` üzerinde dinliyor
- [ ] SQL `echo` kapalı (loglara sorgu ve parametre yazılmasın)
- [ ] LM Studio kullanılıyorsa yalnızca yerel adreste çalışıyor

### 10.3 Hesaplar ve yetkiler

- [ ] Yönetici parolası değiştirildi
- [ ] Demo hesapları (`demo.mudur`, `demo.onburo`, `demo.kat`,
      `demo.teknik`, `demo.muhasebe`) **silindi**
- [ ] Demo veri temizlendi
- [ ] Kullanıcılara **en az yetki** ilkesiyle rol atandı
- [ ] `guest.view_identity` yetkisi yalnızca gerçekten ihtiyacı olanda *(yeni)*
- [ ] `report.financial` ve `finance.*` yetkileri denetlendi *(yeni)*
- [ ] AI Geliştirme Merkezi yetkisi (`devcenter.*`) yalnızca gerekli kişide
- [ ] Kullanılmayan sistem rolleri pasife alındı

### 10.4 Veri ve yedekleme

- [ ] Otomatik yedekleme kuruldu
- [ ] **Geri yükleme fiilen denendi** — `app/infrastructure/backup.py`
      kapsamı %20.9, `app/cli.py` %0; bu akış otomatik test edilmiyor,
      elle doğrulanmalıdır *(vurgu — 9.6, TEST_REPORT 6.2)*
  ```powershell
  .\scripts\backup.ps1
  .\scripts\backup.ps1 -Restore backups\hotel_<tarih>.db
  ```
- [ ] Veritabanı dosyası yalnızca uygulama kullanıcısının erişebildiği
      klasörde *(yeni — 9.7)*
- [ ] Disk şifrelemesi (BitLocker) açık *(yeni — 9.7)*
- [ ] Vergi oranları işletmenin gerçek oranlarıyla güncellendi

### 10.5 Kalite kapıları

- [ ] Tüm testler geçiyor
  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q --no-header -m "not live"
  ```
- [ ] `ruff` temiz *(şu anda **değil** — bkz. 9.2)*
  ```powershell
  .\.venv\Scripts\ruff.exe check app tests --output-format=concise
  ```
- [ ] `bandit` yüksek/orta bulgu vermiyor
  ```powershell
  .\.venv\Scripts\bandit.exe -q -c pyproject.toml -r app
  ```
- [ ] `pip-audit` temiz *(şu anda `setuptools` açığı var — bkz. 7.1)*
  ```powershell
  .\.venv\Scripts\pip-audit.exe --skip-editable
  ```
- [ ] Veritabanı göçleri şemayla tutarlı *(yeni)*
  ```powershell
  .\.venv\Scripts\alembic.exe upgrade head
  .\.venv\Scripts\alembic.exe check
  ```

### 10.6 İşletme süreci

- [ ] Denetim günlüğünün kimler tarafından, ne sıklıkla inceleneceği
      belirlendi *(yeni)*
- [ ] Personel çıkışında hesabın pasife alınması süreci tanımlandı *(yeni)*
- [ ] KVKK aydınlatma metni ve açık rıza akışı işletme tarafından
      hazırlandı — yazılım izinleri **kaydeder**, metni üretmez
- [ ] e-Fatura/KBS yükümlülüklerinin bu yazılımla **karşılanmadığı**
      işletmeye bildirildi (bkz. README "Yasal uyarı")

---

## İlgili belgeler

| Belge | İçerik |
|---|---|
| [SECURITY](../SECURITY.md) | Güvenlik **politikası** ve açık bildirimi |
| [TEST_REPORT](TEST_REPORT.md) | Ölçülmüş test ve statik analiz sonuçları |
| [ROADMAP](ROADMAP.md) | Yapılmamış işler ve bilinen teknik eksikler |
| [ARCHITECTURE](ARCHITECTURE.md) | Katmanlı mimari ve tasarım kararları |
| [GITHUB_RESEARCH](GITHUB_RESEARCH.md) | Açık kaynak lisans analizi |
