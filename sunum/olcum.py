"""Sunumdaki sayilari **kaynak koddan olcer**.

Neden ayri bir modul?
---------------------
Onceki surumde slayt metinlerindeki sayilar (test adedi, tablo adedi, izin
adedi, kapsam yuzdesi) elle yazilmisti ve "bu sayilar olculdu" diyen bir
dipnotla birlikte basiliyordu. Kod degistiginde sayilar degismiyordu; sunum
sessizce yanlislasiyordu.

Bagimsiz bir yayin oncesi incelemede bu sinifin en agir ornegi tespit edildi:
"kapatildi (<islem numarasi>)" seklinde dort duzeltme kaydi gosteriliyordu,
ancak o islemlerin ucu **hicbir satir silmiyordu** - yani mevcut bir acigi
kapatmis olamazlardi. Depoyu klonlayan herkes bunu tek komutla dogrulayabilir.
Bu modul, ayni sinifta bir hatanin sayilar tarafinda tekrarlanmasini onler.

Kullanim::

    from sunum.olcum import olc
    degerler = olc()          # {"test": 1051, "tablo": 60, ...}

Her deger **o an** depodan hesaplanir. Hesaplanamayan bir deger ``None``
doner; ``sunum_uret.py`` bu durumda ilgili ifadeyi slayttan **cikarir**,
tahmini bir sayi basmaz.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
#  Tek tek olcumler
# --------------------------------------------------------------------------
def tablo_sayisi() -> int | None:
    """SQLAlchemy ust verisinden gercek tablo adedini okur.

    Kaynak metninde ``__tablename__`` aramak bu projede ise yaramaz: tablo
    adlari :class:`app.infrastructure.db.base.Base` icinde ``declared_attr``
    ile sinif adindan turetilir. Dogru sayim, modelleri yukleyip
    ``Base.metadata.tables`` uzunlugunu okumaktir - ara tablolar dahil.
    """
    try:
        sys.path.insert(0, str(KOK))
        import app.infrastructure.db.models  # noqa: F401 - kayit icin gerekli
        from app.infrastructure.db.base import Base

        return len(Base.metadata.tables) or None
    except Exception:
        return None


def orm_model_sayisi() -> int | None:
    """Tanimli ORM sinifi adedi (ara tablolar haric)."""
    try:
        sys.path.insert(0, str(KOK))
        import app.infrastructure.db.models  # noqa: F401
        from app.infrastructure.db.base import Base

        return len(list(Base.registry.mappers)) or None
    except Exception:
        return None


def izin_ve_rol_sayisi() -> tuple[int | None, int | None]:
    """Izin katalogunu ve varsayilan rolleri koddan okur."""
    try:
        sys.path.insert(0, str(KOK))
        from app.security.permissions import DEFAULT_ROLES, PERMISSIONS

        return len(PERMISSIONS), len(DEFAULT_ROLES)
    except Exception:
        return None, None


def saglayici_sayisi() -> int | None:
    """Kayitli yapay zeka saglayicilarini sayar."""
    try:
        sys.path.insert(0, str(KOK))
        from app.core.config import ProviderName

        return len(list(ProviderName))
    except Exception:
        return None


def ekran_sayisi() -> int | None:
    """``sunum/ekranlar/`` altindaki yakalanmis ekran goruntulerini sayar."""
    dizin = Path(__file__).resolve().parent / "ekranlar"
    if not dizin.is_dir():
        return None
    return len(list(dizin.glob("*.png"))) or None


def test_sayisi(python: str | None = None, hedef: str = "tests") -> int | None:
    """``pytest --collect-only`` ile **gercekten toplanan** test adedini olcer.

    ``def test_`` satirlarini saymak yanlis sonuc verir:
    ``@pytest.mark.parametrize`` bir tanimi onlarca teste cevirir. Bu yuzden
    sayim pytest'in kendisine yaptirilir.
    """
    yorumlayici = python or sys.executable
    try:
        sonuc = subprocess.run(  # noqa: S603 - sabit arguman listesi, shell yok
            [
                yorumlayici,
                "-m",
                "pytest",
                hedef,
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=KOK,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    eslesme = re.search(r"(\d+)\s+tests? collected", sonuc.stdout)
    if eslesme:
        return int(eslesme.group(1))
    eslesme = re.search(r"(\d+)/(\d+) tests collected", sonuc.stdout)
    if eslesme:
        return int(eslesme.group(1))
    return None


#: Slaytta "katman katman" dokumu icin olculecek test dizinleri.
KATMANLAR: dict[str, str] = {
    "tests/domain": "alan",
    "tests/security": "guvenlik",
    "tests/infrastructure": "altyapi",
    "tests/application": "uygulama",
    "tests/ai": "yapayzeka",
    "tests/ui": "arayuz",
    "tests/reporting": "raporlama",
    "tests/devcenter": "devmerkezi",
}


def katman_test_sayilari(python: str | None = None) -> dict[str, int]:
    """Her test dizini icin toplanan test adedini olcer."""
    sonuc: dict[str, int] = {}
    for yol, etiket in KATMANLAR.items():
        if not (KOK / yol).is_dir():
            continue
        adet = test_sayisi(python, hedef=yol)
        if adet is not None:
            sonuc[etiket] = adet
    return sonuc


def bandit_bulgulari(bandit: str | None = None) -> dict[str, int] | None:
    """bandit'i calistirip onem seviyesine gore bulgu sayilarini dondurur."""
    yorumlayici = bandit or sys.executable
    try:
        sonuc = subprocess.run(  # noqa: S603
            [
                yorumlayici,
                "-m",
                "bandit",
                "-q",
                "-c",
                "pyproject.toml",
                "-r",
                "app",
                "-f",
                "json",
            ],
            cwd=KOK,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # bandit ilerleme cubugunu stdout'a basar; JSON ondan sonra baslar.
    ham = sonuc.stdout
    basla = ham.find("{")
    if basla < 0:
        return None
    try:
        veri = json.loads(ham[basla:])
    except ValueError:
        return None
    sayim = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for bulgu in veri.get("results", []):
        seviye = str(bulgu.get("issue_severity", "")).upper()
        if seviye in sayim:
            sayim[seviye] += 1
    sayim["NOSEC"] = int(veri.get("metrics", {}).get("_totals", {}).get("nosec", 0))
    return sayim


def ruff_bulgu_sayisi(python: str | None = None) -> int | None:
    """``ruff check app tests`` bulgu adedini dondurur.

    Kapsam bilincli olarak CI'daki zorunlu kapiyla **aynidir**
    (``.github/workflows/ci.yml`` -> "Lint (ruff)"). Slaytta anlatilan sey o
    kapidir; farkli bir kapsam olcmek, slaydi yine dogrulanamaz kilardi.
    ``sunum/`` yalnizca yayin hazirlarken calisan bir uretim aracidir ve
    CI kapisinin disindadir.
    """
    yorumlayici = python or sys.executable
    try:
        sonuc = subprocess.run(  # noqa: S603
            [yorumlayici, "-m", "ruff", "check", "app", "tests", "--output-format", "json"],
            cwd=KOK,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return len(json.loads(sonuc.stdout))
    except ValueError:
        return None


def kapsam_yuzdesi() -> float | None:
    """Varsa ``coverage.json`` dosyasindan dal dahil kapsami okur.

    Dosya yoksa ``None`` doner - sunum o zaman kapsam iddiasini **basmaz**.
    Tahmini bir yuzde basmak, olculmus bir yuzde gibi gorunurdu.
    """
    for aday in (KOK / "coverage.json", KOK / "reports" / "coverage.json"):
        if aday.is_file():
            try:
                veri = json.loads(aday.read_text(encoding="utf-8"))
                return round(float(veri["totals"]["percent_covered"]), 1)
            except (ValueError, KeyError, TypeError):
                continue
    return None


def surum() -> str:
    """``pyproject.toml`` icindeki surum numarasi."""
    metin = (KOK / "pyproject.toml").read_text(encoding="utf-8")
    eslesme = re.search(r'^version\s*=\s*"([^"]+)"', metin, re.MULTILINE)
    return eslesme.group(1) if eslesme else "0.0.0"


# --------------------------------------------------------------------------
#  Toplu olcum
# --------------------------------------------------------------------------
def olc(*, testleri_calistir: bool = True, python: str | None = None) -> dict[str, object]:
    """Tum olcumleri yapar ve sozluk dondurur.

    Parameters
    ----------
    testleri_calistir:
        ``False`` ise test sayimi atlanir (hizli onizleme icin). Bu durumda
        ``test`` degeri ``None`` olur ve sunum test sayisini basmaz.
    """
    izin, rol = izin_ve_rol_sayisi()
    return {
        "tablo": tablo_sayisi(),
        "model": orm_model_sayisi(),
        "izin": izin,
        "rol": rol,
        "saglayici": saglayici_sayisi(),
        "ekran": ekran_sayisi(),
        "test": test_sayisi(python) if testleri_calistir else None,
        "katman": katman_test_sayilari(python) if testleri_calistir else {},
        "bandit": bandit_bulgulari(python) if testleri_calistir else None,
        "ruff": ruff_bulgu_sayisi(python) if testleri_calistir else None,
        "kapsam": kapsam_yuzdesi(),
        "surum": surum(),
    }


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ayristirici = argparse.ArgumentParser(description="Sunum sayilarini olcer")
    ayristirici.add_argument(
        "--hizli", action="store_true", help="Test sayimini atla (pytest calistirmaz)"
    )
    secenek = ayristirici.parse_args()
    for anahtar, deger in olc(testleri_calistir=not secenek.hizli).items():
        print(f"{anahtar:12} = {deger if deger is not None else 'OLCULEMEDI'}")
