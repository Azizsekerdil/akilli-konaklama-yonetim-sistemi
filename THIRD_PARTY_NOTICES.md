# Ucuncu Parti Bildirimleri (Third Party Notices)

> **Bu proje ucuncu parti KAYNAK KODU icermez.**
>
> Asagida listelenen kutuphanelerin hicbiri bu depoya kopyalanmamis
> (vendoring yapilmamis), catallanmamis (fork) veya yamalanmamistir. Tumu
> **PyPI uzerinden standart sekilde** (`pip install -r requirements.txt`)
> kurulur, kendi depolarinda barinir ve **kendi lisanslari altindadir**.
> Bu belge yalnizca bir bildirim/atif listesidir; bu paketlerin telif hakki
> sahipleri kendi eserlerinin sahibi olmaya devam eder.
>
> Acik kaynak PMS depolarinin incelemesi ve "neden hicbir kod kopyalanmadi"
> gerekcesi icin [`docs/GITHUB_RESEARCH.md`](docs/GITHUB_RESEARCH.md)
> dosyasina bakiniz.

- **Belge tarihi:** 2026-08-15
- **Proje:** Akilli Konaklama Yonetim Sistemi (`akilli-konaklama-yonetim-sistemi` 0.1.0)
- **Python:** 3.11.9

---

## Nasil dogrulandi

| Alan | Kaynak |
|---|---|
| Paket adi ve **kurulu surum** | `.\.venv\Scripts\python.exe -m pip list` ciktisi (gercek ortam) |
| Bagimlilik listesi (dogrudan) | `requirements.txt`, `requirements-dev.txt`, `pyproject.toml` |
| Lisans | Kurulu dagitimin `*.dist-info/METADATA` dosyasindaki `License-Expression` alani; yoksa `License ::` siniflandiricisi; belirsiz kalanlar PyPI JSON API'si ile ayrica dogrulandi |
| Proje adresi | Paket ust verisindeki `Home-page` / `Project-URL` alani |

Lisansi paket ust verisinde **SPDX kimligi olarak** yer almayan, yalnizca genel
siniflandirici ("BSD License", "Apache Software License") ile verilen paketler
tabloda `*` isaretiyle gosterilmistir; bu satirlarda SPDX kimligi paketin resmi
proje sayfasindan cikarilmistir ve kesin ifade dogrulanmasi icin paketin kendi
LICENSE dosyasina bakilmalidir.

**Kullanim durumu sutunu dogru olsun diye,** bagimliligin kod icinde gercekten
`import` edilip edilmedigi `app/`, `tests/` ve `alembic/` agaclarinda arandi.
Proje erken asamadadir; bildirilen bagimliliklarin bir kismi mimaride
planlanmis ancak henuz kod icinde kullanilmamistir. Bunlar acikca
**"planli"** olarak isaretlenmistir - bildirimin dogru olmasi, listenin uzun
gorunmesinden onemlidir. Bu sutun **2026-08-15 tarihli kod durumunu** yansitir
ve kod buyudukce guncellenmelidir; lisans yukumlulugu acisindan belirleyici
olan, paketin kurulu ve dagitilan bagimlilik listesinde bulunmasidir - kod
icinde `import` edilip edilmemesi degil.

---

## 1. Dogrudan calisma zamani bagimliliklari

Urunle birlikte dagitilan bagimliliklardir (`pyproject.toml` -> `dependencies`).

| Paket | Kurulu surum | Lisans | Proje adresi | Projede ne icin kullaniliyor |
|---|---|---|---|---|
| SQLAlchemy | 2.0.52 | MIT | https://www.sqlalchemy.org | **Kullaniliyor.** 60 tabloluk ORM semasi (`app/infrastructure/db/models/`), `Base`/`TimestampMixin`/`enum_column` altyapisi, `session_scope` oturum yonetimi ve depo (repository) katmani |
| alembic | 1.19.1 | MIT | https://github.com/sqlalchemy/alembic/ | **Kullaniliyor.** Veritabani sema gocleri (`alembic/env.py`, `alembic/versions/`) |
| pydantic | 2.13.4 | MIT | https://github.com/pydantic/pydantic | **Kullaniliyor.** Yapilandirma dogrulama (`Field`, `SecretStr`, `field_validator`) ve ileride API sema modelleri |
| pydantic-settings | 2.15.0 | MIT | https://github.com/pydantic/pydantic-settings | **Kullaniliyor.** `app/core/config.py` icindeki `Settings` sinifi; ortam degiskeni ve `.env` okuma |
| python-dateutil | 2.9.0.post0 | Apache-2.0 VEYA BSD-3-Clause (ikili lisans) * | https://github.com/dateutil/dateutil | **Planli.** Tekrarlayan tarih kurallari ve esnek tarih ayristirma (gece denetimi / raporlama takvimleri) |
| fastapi | 0.141.1 | MIT | https://github.com/fastapi/fastapi | **Planli.** Servis katmani REST API'si (kanal yoneticisi, mobil istemci, entegrasyon uc noktalari) |
| uvicorn[standard] | 0.52.3 | BSD-3-Clause | https://uvicorn.dev/ | **Planli.** FastAPI servisinin ASGI sunucusu. `[standard]` ekstrasi `httptools`, `watchfiles`, `websockets`, `python-dotenv`, `PyYAML`, `colorama` paketlerini getirir |
| httpx | 0.28.1 | BSD-3-Clause * | https://github.com/encode/httpx | **Kullaniliyor.** Dis servis cagrilari; `app/ai/errors.py` icinde yapay zeka saglayici hata siniflandirmasi `httpx` istisnalari uzerinden yapilir |
| python-multipart | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart | **Planli.** API uzerinden dosya yukleme (kimlik belgesi taramasi, fatura eki) |
| PySide6 | 6.9.3 | **LGPL-3.0-only VEYA GPL-2.0-only VEYA GPL-3.0-only** | https://pyside.org | **Kullaniliyor.** Masaustu arayuz: `app/main.py`, `app/ui/login.py`, `app/ui/widgets/`. **Copyleft - bkz. Bolum 5** |
| argon2-cffi | 25.1.0 | MIT | https://github.com/hynek/argon2-cffi | **Kullaniliyor.** Parola ozetleme; `app/security/passwords.py` Argon2id kullanir |
| cryptography | 50.0.0 | Apache-2.0 VEYA BSD-3-Clause (ikili lisans) | https://github.com/pyca/cryptography | **Kullaniliyor.** Alan duzeyinde sifreleme; `app/infrastructure/db/types.py` icinde kimlik/pasaport alanlari icin Fernet |
| keyring | 25.7.0 | MIT | https://github.com/jaraco/keyring | **Kullaniliyor.** Isletim sistemi anahtarligi uzerinden sir saklama; `app/core/secret_store.py` |
| python-dotenv | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv | **Dolayli olarak kullaniliyor.** `.env` okuma isini pydantic-settings ustlenir; paket ayrica `uvicorn[standard]` tarafindan da cekilir |
| slowapi | 0.1.10 | MIT | https://github.com/laurents/slowapi | **Planli.** API istek hizi sinirlama (brute-force korumasi) |
| reportlab | 5.0.0 | BSD (ReportLab BSD lisansi) * | https://www.reportlab.com/ | **Kullaniliyor.** PDF uretimi (fatura, folio dokumu, konaklama belgesi); `app/reporting/exporters/pdf_exporter.py` |
| openpyxl | 3.1.5 | MIT | https://openpyxl.readthedocs.io | **Kullaniliyor.** Excel disa aktarma (gunluk rapor, doluluk ve gelir tablolari); `app/reporting/exporters/excel_exporter.py` |
| structlog | 26.1.0 | MIT VEYA Apache-2.0 (ikili lisans) | https://github.com/hynek/structlog | **Kullaniliyor.** Yapisal ve maskeli loglama; `app/core/log.py` |
| numpy | 2.4.6 | BSD-3-Clause VE 0BSD VE MIT VE Zlib VE CC0-1.0 | https://numpy.org | **Planli.** Talep tahmini ve gelir yonetimi hesaplari |
| tiktoken | 0.13.0 | MIT | https://github.com/openai/tiktoken | **Planli.** Yapay zeka istemlerinde jeton (token) sayimi ve maliyet tahmini. `pyproject.toml` icinde `python_version < "3.13"` kosuluna baglidir |

### Istege bagli ekstra

| Paket | Kurulu surum | Lisans | Proje adresi | Kullanim |
|---|---|---|---|---|
| psycopg[binary] | **kurulu degil** | LGPL-3.0-or-later | https://github.com/psycopg/psycopg | PostgreSQL kullanilacaksa `pip install ".[postgres]"` ile kurulur. **LGPL** oldugu icin dagitim bicimi PySide6 ile ayni dikkatle degerlendirilmelidir |

---

## 2. Dogrudan gelistirme / test / guvenlik bagimliliklari

Bu paketler **urunle birlikte dagitilmaz**; yalnizca gelistirme ortaminda
bulunur. Bu nedenle lisans yukumlulukleri (paketleme araclari dahil) son
kullaniciya gecmez.

| Paket | Kurulu surum | Lisans | Proje adresi | Projede ne icin kullaniliyor |
|---|---|---|---|---|
| pytest | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ | **Kullaniliyor.** Tum test paketinin kosucusu (`tests/`) |
| pytest-cov | 7.1.0 | MIT | https://pypi.org/project/pytest-cov/ | Kapsam (coverage) raporlamasi; `pyproject.toml` -> `[tool.coverage]` |
| pytest-qt | 4.5.0 | MIT | http://github.com/pytest-dev/pytest-qt | **Planli.** PySide6 arayuz duman (smoke) testleri; `ui` isareti |
| pytest-asyncio | 1.4.0 | Apache-2.0 | https://github.com/pytest-dev/pytest-asyncio | Asenkron testler; `asyncio_mode = "auto"` |
| pytest-mock | 3.15.1 | MIT | https://github.com/pytest-dev/pytest-mock/ | Test cifti (mock) yardimcilari |
| freezegun | 1.5.5 | Apache-2.0 | https://github.com/spulec/freezegun | **Planli.** Zaman dondurma; gece denetimi ve konaklama suresi testleri icin |
| respx | 0.23.1 | BSD-3-Clause * | https://github.com/lundberg/respx | **Kullaniliyor.** `httpx` cagrilarinin taklit edilmesi; `tests/ai/test_providers.py` ve `tests/ai/test_registry.py` tamamen sahte HTTP uzerinde calisir |
| ruff | 0.16.3 | MIT | https://docs.astral.sh/ruff | **Kullaniliyor.** Linter + import siralama; `E,W,F,I,B,C4,UP,N,S,A,DTZ,RUF` kural kumeleri |
| black | 26.5.1 | MIT | https://github.com/psf/black | **Kullaniliyor.** Kod bicimlendirme, satir uzunlugu 100 |
| mypy | 2.3.0 | MIT | https://www.mypy-lang.org/ | Statik tip denetimi; `pydantic.mypy` eklentisiyle |
| types-python-dateutil | 2.9.0.20260807 | Apache-2.0 | https://github.com/python/typeshed | `python-dateutil` icin tip taslaklari |
| bandit[toml] | 1.9.4 | Apache-2.0 | https://bandit.readthedocs.io/ | Guvenlik taramasi; `pyproject.toml` -> `[tool.bandit]` |
| pip-audit | 2.10.1 | Apache-2.0 * | https://pypi.org/project/pip-audit/ | Bagimliliklarda bilinen zafiyet taramasi |
| detect-secrets | 1.5.0 | Apache-2.0 * | https://github.com/Yelp/detect-secrets | Depoya sir (parola, anahtar) sizmasini engelleme |
| pyinstaller | 6.22.0 | **GPL-2.0-or-later + onyukleyici istisnasi** | https://pyinstaller.org | **Planli.** Windows icin tek dosyalik dagitim paketi. **Bkz. Bolum 5** |

---

## 3. Dolayli (transitive) bagimliliklar

Yukaridaki paketlerin kendi bagimliliklaridir; dogrudan secilmemislerdir.
Kurulu surumler gercek sanal ortamdan alinmistir.

| Paket | Surum | Lisans | Proje adresi |
|---|---|---|---|
| altgraph | 0.17.5 | MIT | https://altgraph.readthedocs.io |
| annotated-doc | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.14.2 | MIT | https://github.com/agronholm/anyio |
| argon2-cffi-bindings | 25.1.0 | MIT | https://github.com/hynek/argon2-cffi-bindings |
| ast_serialize | 0.8.0 | MIT | https://github.com/mypyc/ast_serialize |
| backports.tarfile | 1.2.0 | MIT * | https://github.com/jaraco/backports.tarfile |
| boolean.py | 5.0 | BSD-2-Clause | https://github.com/bastikr/boolean.py |
| CacheControl | 0.14.4 | Apache-2.0 | https://pypi.org/project/CacheControl/ |
| certifi | 2026.7.22 | **MPL-2.0** | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| charset-normalizer | 3.5.0 | MIT | https://pypi.org/project/charset-normalizer/ |
| click | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| colorama | 0.4.6 | BSD-3-Clause * | https://github.com/tartley/colorama |
| coverage | 7.15.4 | Apache-2.0 | https://github.com/coveragepy/coveragepy |
| cyclonedx-python-lib | 11.12.0 | Apache-2.0 * | https://github.com/CycloneDX/cyclonedx-python-lib |
| defusedxml | 0.7.1 | PSF-2.0 * | https://github.com/tiran/defusedxml |
| Deprecated | 1.3.1 | MIT * | https://github.com/laurent-laporte-pro/deprecated |
| et_xmlfile | 2.0.0 | MIT * | https://foss.heptapod.net/openpyxl/et_xmlfile |
| filelock | 3.32.3 | MIT | https://github.com/tox-dev/py-filelock |
| greenlet | 3.5.5 | MIT VE PSF-2.0 | https://greenlet.readthedocs.io |
| h11 | 0.16.0 | MIT * | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httptools | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| importlib_metadata | 9.0.0 | Apache-2.0 | https://github.com/python/importlib_metadata |
| iniconfig | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| jaraco.classes | 3.4.0 | MIT * | https://github.com/jaraco/jaraco.classes |
| jaraco.context | 6.1.2 | MIT | https://github.com/jaraco/jaraco.context |
| jaraco.functools | 4.6.0 | MIT | https://github.com/jaraco/jaraco.functools |
| librt | 0.15.0 | MIT | https://github.com/mypyc/librt |
| license-expression | 30.4.4 | Apache-2.0 | https://github.com/aboutcode-org/license-expression |
| limits | 5.8.0 | MIT | https://limits.readthedocs.org |
| Mako | 1.4.1 | MIT | https://www.makotemplates.org/ |
| markdown-it-py | 4.2.0 | MIT * | https://github.com/executablebooks/markdown-it-py |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| mdurl | 0.1.2 | MIT * | https://github.com/executablebooks/mdurl |
| more-itertools | 11.1.0 | MIT | https://github.com/more-itertools/more-itertools |
| msgpack | 1.2.1 | Apache-2.0 | https://msgpack.org/ |
| mypy_extensions | 1.1.0 | MIT | https://github.com/python/mypy_extensions |
| packageurl-python | 0.17.6 | MIT * | https://github.com/package-url/packageurl-python |
| packaging | 26.3 | Apache-2.0 VEYA BSD-2-Clause | https://github.com/pypa/packaging |
| pathspec | 1.1.1 | **MPL-2.0** | https://github.com/cpburnz/python-pathspec |
| pefile | 2024.8.26 | MIT | https://github.com/erocarrera/pefile |
| pillow | 12.3.0 | MIT-CMU | https://python-pillow.github.io |
| pip | 26.2.1 | MIT | https://pip.pypa.io/ |
| pip-api | 0.0.34 | Apache-2.0 * | http://github.com/di/pip-api |
| pip-requirements-parser | 32.0.1 | MIT | https://github.com/nexB/pip-requirements-parser |
| platformdirs | 4.11.3 | MIT | https://github.com/tox-dev/platformdirs |
| pluggy | 1.6.0 | MIT * | https://pypi.org/project/pluggy/ |
| py-serializable | 2.1.0 | Apache-2.0 * | https://github.com/madpah/serializable |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic_core | 2.46.4 | MIT | https://github.com/pydantic/pydantic |
| Pygments | 2.20.0 | BSD-2-Clause | https://pygments.org |
| pyinstaller-hooks-contrib | 2026.6 | **Apache-2.0 ve GPL-2.0 (karisik)** | https://github.com/pyinstaller/pyinstaller-hooks-contrib |
| pyparsing | 3.3.2 | MIT | https://github.com/pyparsing/pyparsing/ |
| PySide6_Addons | 6.9.3 | **LGPL-3.0-only VEYA GPL-2.0-only VEYA GPL-3.0-only** | https://pyside.org |
| PySide6_Essentials | 6.9.3 | **LGPL-3.0-only VEYA GPL-2.0-only VEYA GPL-3.0-only** | https://pyside.org |
| pytokens | 0.4.1 | MIT * | https://github.com/tusharsadhwani/pytokens |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | https://github.com/enthought/pywin32-ctypes |
| PyYAML | 6.0.3 | MIT * | https://pyyaml.org/ |
| regex | 2026.7.19 | Apache-2.0 VE CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| requests | 2.34.2 | Apache-2.0 * | https://github.com/psf/requests |
| rich | 15.0.0 | MIT * | https://github.com/Textualize/rich |
| setuptools | 65.5.0 | MIT * | https://github.com/pypa/setuptools |
| shiboken6 | 6.9.3 | **LGPL-3.0-only VEYA GPL-2.0-only VEYA GPL-3.0-only** | https://pyside.org |
| six | 1.17.0 | MIT * | https://github.com/benjaminp/six |
| sortedcontainers | 2.4.0 | Apache-2.0 * | http://www.grantjenks.com/docs/sortedcontainers/ |
| starlette | 1.6.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| stevedore | 5.9.0 | Apache-2.0 | https://docs.openstack.org/stevedore |
| tomli | 2.4.1 | MIT | https://github.com/hukkin/tomli |
| tomli_w | 1.2.0 | MIT * | https://github.com/hukkin/tomli-w |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| urllib3 | 2.7.0 | MIT | https://pypi.org/project/urllib3/ |
| watchfiles | 1.2.0 | MIT * | https://github.com/samuelcolvin/watchfiles |
| websockets | 17.0.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |
| wrapt | 2.3.0 | BSD-2-Clause | https://github.com/GrahamDumpleton/wrapt |
| zipp | 4.1.0 | MIT | https://github.com/jaraco/zipp |

`*` = SPDX kimligi paket ust verisinde acikca bulunmuyor; genel siniflandirici
veya serbest metin lisans alanindan cikarildi.

---

## 4. Lisans dagilimi ozeti

| Lisans ailesi | Yaklasik paket sayisi | Not |
|---|---|---|
| MIT / MIT-0 / MIT-CMU | Cogunluk | Yukumluluk: telif bildirimini koru |
| BSD (2/3-Clause) | Onemli bir kisim | Yukumluluk: telif bildirimini ve sorumluluk reddini koru |
| Apache-2.0 | Onemli bir kisim | Ek olarak patent hibesi ve degistirilen dosyalarin isaretlenmesi |
| PSF-2.0 | `typing_extensions`, `defusedxml`, `greenlet` (kismi) | Python Software Foundation lisansi; izin veren |
| **MPL-2.0** | `certifi`, `pathspec` | Dosya duzeyinde copyleft - **degistirilmedigi** surece bildirim disinda yukumluluk dogurmaz |
| **LGPL-3.0** | `PySide6`, `PySide6_Essentials`, `PySide6_Addons`, `shiboken6` (ve secilirse `psycopg`) | **Bolum 5'e bakiniz** |
| **GPL-2.0-or-later + istisna** | `pyinstaller` (ve kismen `pyinstaller-hooks-contrib`) | Yalnizca derleme zamani araci; **Bolum 5'e bakiniz** |

Bu projede **hicbir AGPL veya SSPL lisansli bagimlilik yoktur.**

---

## 5. Copyleft ve dagitim notlari

Bu bolum, urunun ticari olarak dagitilmasi asamasinda mutlaka okunmalidir.

### 5.1 PySide6 / Qt - LGPL-3.0

PySide6, shiboken6 ve dolayisiyla Qt kutuphaneleri
`LGPL-3.0-only VEYA GPL-2.0-only VEYA GPL-3.0-only` uclu secenegiyle gelir.
Kapali kaynak ticari bir urun icin uygun secenek **LGPL-3.0**'dir ve su
kosullari getirir:

1. Qt/PySide6 kutuphanelerine **dinamik** olarak baglanilmali; statik baglama
   ek yukumluluk dogurur.
2. Kutuphanelerin **kaynak kodu degistirilmemelidir**. Degistirilirse,
   degisiklikler LGPL-3.0 ile yayimlanmak zorundadir. Bu projede PySide6/Qt
   **degistirilmemistir**.
3. Son kullaniciya, PySide6/Qt'nin kendi surumunu koyup uygulamayi **yeniden
   baglayabilme (relinking)** imkani taninmalidir. Pratikte bu, Qt kutuphane
   dosyalarinin ayri dosyalar olarak dagitilmasi ve LGPL metninin urunle
   birlikte verilmesiyle saglanir.
4. Bu belge ve LGPL-3.0 lisans metni dagitim paketine dahil edilmelidir.
5. Alternatif olarak The Qt Company'den **ticari Qt lisansi** alinabilir; bu
   durumda yukaridaki kosullar gecerli olmaz.

> **Uyari:** PyInstaller `--onefile` modu Qt kutuphanelerini tek bir yurutulebilir
> dosyanin icine gomer. Bu, yukaridaki 3. maddedeki yeniden baglama hakkini
> pratikte zorlastirir. Ticari dagitimda `--onedir` modu (kutuphaneler ayri
> dosyalar olarak) tercih edilmeli veya ticari Qt lisansi alinmalidir.
>
> **Mevcut durum (2026-08-15 tarihinde dogrulandi):** `scripts/build.ps1` bu
> karara uygundur - varsayilan kip `--onedir`'dir ve tek dosya paketi yalnizca
> acik `-OneFile` anahtariyla uretilir. `-OneFile` ticari dagitimda
> kullanilacaksa once ticari Qt lisansi alinmalidir.

### 5.1.1 Lisans metinlerinin pakete girmesi - **UYGULANDI**

5.1'in 4. maddesi bir yukumluluktur ve bir yayin oncesi incelemede
**uretilen paketin bu yukumlulugu karsilamadigi** tespit edildi: `dist/`
klasorunde ne bu belge, ne LGPL metni, ne de projenin kendi MIT metni vardi.
Iki yukumluluk ayni anda karsilanmiyordu.

Simdi iki katmanli olarak zorunlu kilinmistir:

1. `packaging/hotel.spec`, paketleme **baslamadan once** su dosyalarin
   varligini dogrular; biri eksikse derleme durur:
   - `LICENSE` (MIT, telif bildirimi tum kopyalarda bulunmalidir)
   - `THIRD_PARTY_NOTICES.md` (bu belge)
   - `packaging/licenses/GPL-3.0.txt`
   - `packaging/licenses/LGPL-3.0.txt`
2. `scripts/build.ps1`, derleme **bittikten sonra** ayni dosyalarin
   uretilen ciktida gercekten bulundugunu dogrular.

> **Acik kalan is:** `packaging/licenses/LGPL-3.0.txt` bu depoda **yoktur**.
> LGPL-3.0 metninin **birebir** olmasi gerekir; depoyu hazirlayan surec
> dogrulanabilir birebir bir kopyaya cevrimdisi erisemedigi icin metni
> tahminle yazmak yerine eksik birakmayi secti - yaklasik bir lisans metni,
> lisans metni degildir. **Ikili paket uretmeden once** eklenmelidir; nasil
> yapilacagi `packaging/licenses/README.md` icinde yazilidir. Kaynak koddan
> calistirmak icin gerekli degildir.

`GPL-3.0.txt` depoda vardir (LGPL-3.0 kendi metninde GPL-3.0'in sart ve
kosullarini icerir, dolayisiyla ikisi birlikte dagitilir).

### 5.2 PyInstaller - GPL-2.0-or-later + onyukleyici istisnasi

PyInstaller GPL-2.0-or-later lisanslidir, **ancak** ozel bir istisna icerir.
`COPYING.txt` dosyasindan dogrulanan ifade su izni verir: yazarlar, derlenmis
onyukleyiciyi (bootloader) ve ilgili dosyalari baska programlarla
birlestirmeye ve bu birlesimleri "bu dosyalarin kullanimindan kaynaklanan
hicbir kisitlama olmaksizin" dagitmaya sinirsiz izin verir.

Sonuc: **PyInstaller ile paketlenen bu urun GPL olmak zorunda degildir.**
PyInstaller'in kendisi zaten yalnizca bir derleme araci olup urunle
dagitilmaz. `pyinstaller-hooks-contrib` paketi Apache-2.0 ve GPL-2.0 lisansli
dosyalarin karisimidir; o da yalnizca derleme zamanindadir.

### 5.3 MPL-2.0 paketler (certifi, pathspec)

MPL-2.0 **dosya duzeyinde** copyleft'tir: yalnizca MPL lisansli dosyalarin
kendisi degistirilirse, degisikliklerin ayni lisansla yayimlanmasi gerekir.
Bu projede her ikisi de degistirilmeden kullanilmaktadir; bu belgede
bildirilmeleri yeterlidir.

### 5.4 Yasal uyari

Bu belge muhendislik amacli hazirlanmis bir bildirim listesidir, **hukuki gorus
degildir**. Lisans metinleri iyi niyetle ve paket ust verileri ile resmi proje
sayfalari uzerinden dogrulanmistir. Ticari dagitimdan once, ozellikle
PySide6/Qt LGPL kosullari acisindan hukuk musaviri gorusu alinmasi onerilir.

---

## 5.5 Tanitim sunumundaki yazi tipi

`docs/presentation/` altindaki PPTX ve PDF dosyalari **Calibri** ile
dizilmistir. Calibri, Microsoft'un tescilli bir yazi tipidir ve Windows /
Microsoft Office ile birlikte gelir; bu depoda **yazi tipi dosyasi
dagitilmaz**. PDF'ler, PowerPoint tarafindan uretilirken yazi tipinin bir
**alt kumesini** gomer.

**Neden libre bir yazi tipi kullanilmadi?** Kullanilmasi tercih edilirdi
(Inter, Source Sans 3, DejaVu Sans). Ancak sunum PowerPoint COM ile
uretilir ve PowerPoint yalnizca **isletim sisteminde kurulu** yazi tiplerini
kullanabilir; uretim makinesinde kurulu libre bir yazi tipi yoktu ve bir
yazi tipi kurmak sistem yapilandirmasini degistirmek anlamina geldiginden
bu hazirlik kapsaminin disinda birakildi. Karar `docs/known-limitations.md`
7. maddede de kayitlidir.

**Libre bir yazi tipine gecmek isteyen icin:** `sunum/sunum_uret.py`
icindeki yazi tipi adini degistirmek ve o yazi tipini uretim makinesine
kurmak yeterlidir; slayt yerlesimi punto bazlidir, yeniden olcumlenir
(`python sunum/sunum_uret.py --kontrol`).

## 6. Bagimliliklarin guncel tutulmasi

- Zafiyet taramasi: `.\.venv\Scripts\python.exe -m pip_audit`
- Sir taramasi: `.\.venv\Scripts\detect-secrets.exe scan`
- Statik guvenlik taramasi: `.\.venv\Scripts\bandit.exe -c pyproject.toml -r app`
- Bu belge, `requirements.txt` veya `requirements-dev.txt` her degistiginde
  guncellenmelidir. Surum sutunundaki degerler **kurulu** surumlerdir;
  `requirements.txt` icindeki aralik kisitlariyla birebir ayni degildir.

---

## 7. Bu projenin lisansi

Akilli Konaklama Yonetim Sistemi **MIT lisansi** altinda dagitilir. Lisansin
tam metni depo kokundeki [`LICENSE`](LICENSE) dosyasindadir.

```
MIT License

Copyright (c) 2026 Aziz Sekerdil

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**MIT lisansinin kapsami yalnizca bu projenin kendi kaynak kodudur.** Yukarida
listelenen ucuncu parti paketler bu lisansin kapsaminda degildir; her biri
kendi lisansi altinda kalir ve o lisansin kosullari gecerlidir.

**Ek not (kok `LICENSE` dosyasindan):** Bu yazilim, konaklama isletmelerinin
veri islemesini kolaylastirir ancak KVKK, e-Fatura, Kimlik Bildirim Sistemi ve
diger yasal yukumluluklere uyum sorumlulugu tamamen kullanici isletmeye aittir.
