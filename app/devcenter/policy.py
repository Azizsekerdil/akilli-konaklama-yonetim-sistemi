"""Komut guvenlik politikasi.

Bu modul, AI Gelistirme Merkezi'nin **en kritik** parcasidir: hangi komutun
calistirilabilecegine burada karar verilir.

Tasarim: izin listesi (allowlist) onceliklidir
-----------------------------------------------
Yalnizca yasak listesi (denylist) tutmak guvenli degildir - saldirgan ya da
hatali bir model, listede olmayan bir yolla ayni zarari verebilir
(``cmd /c del``, ``powershell -enc <base64>``, ``python -c "shutil.rmtree(...)"``).

Bu yuzden karar su sirayla verilir:

1. **Yasak desen** eslesirse -> ENGELLE (koşulsuz)
2. **Hassas dosya hedefi** varsa -> ENGELLE (koşulsuz, komutun adina
   bakilmaksizin - bkz. :data:`SENSITIVE_TARGETS`)
3. Komut **izin listesinde** ise -> risk seviyesine gore izin ver
4. Hicbiri degilse -> **ONAY ISTE** (bilinmeyen komut asla sessizce calismaz)

Ayrica her komut, calisma dizini :data:`sandbox_root` icinde olacak sekilde
dogrulanir; yol kacislari (``..``) cozumlenerek engellenir.

.. important::
   2. adim izin listesinden **once** gelir. Izin listesi "hangi ikili
   calisir" sorusunu cozer, "o ikili neyi okur" sorusunu cozmez: ``head``
   mesru sekilde salt-okunurdur ama ``head .env`` yine de sir sizdirir.
   Bu yuzden ``.env``, anahtar dosyalari, kimlik bilgisi depolari ve
   misafir veritabani **her okuyucu icin** kapalidir.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.config import get_settings
from app.core.log import get_logger

log = get_logger(__name__)


class RiskLevel(str, Enum):
    """Bir komutun risk seviyesi."""

    SAFE = "safe"
    """Salt okunur; onaysiz calistirilabilir (or. ``git status``, ``pytest``)."""

    WRITE = "write"
    """Dosya/depo degistirir; **kullanici onayi gerekir**."""

    DANGEROUS = "dangerous"
    """Geri alinmasi zor; onay + acik gerekce gerekir."""

    BLOCKED = "blocked"
    """Hicbir kosulda calistirilmaz."""

    @property
    def requires_approval(self) -> bool:
        return self is not RiskLevel.SAFE

    @property
    def label(self) -> str:
        return {
            "safe": "Guvenli",
            "write": "Degisiklik yapar",
            "dangerous": "Riskli",
            "blocked": "Engellendi",
        }[self.value]


# --------------------------------------------------------------------------
#  Yasak desenler - KOSULSUZ ENGELLENIR
# --------------------------------------------------------------------------
#: Her desen ``(regex, insan-okunur gerekce)`` ciftidir.
#: Desenler komutun **tam metni** uzerinde, kucuk harfe cevrilmis olarak
#: aranir; boylece ``DEL`` ve ``del`` ayni sekilde yakalanir.
BLOCKED_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        # --- Toplu silme ---
        # NOT: Bayrak SIRASI serbest oldugu icin her bayrak AYRI aranir.
        # "remove-item .* -recurse .* -force" bicimi bir desen,
        # "-Force -Recurse" sirasini KACIRIRDI. Ayni sekilde "rm -rf" i
        # yakalayip "rm -fr" i kaciran bir desen de yaziliyordu.
        (r"\bremove-item\b[^;|&]*\s-recurse\b", "Ozyinelemeli silme"),
        (r"\bremove-item\b[^;|&]*\s-force\b", "Zorla silme"),
        (r"\brm\b\s+(-\S*\s+)*-\S*[rf]", "Ozyinelemeli/zorla silme (rm)"),
        (r"\brmdir\b", "Klasor silme"),
        (r"\bdel\b\s+/[sq]", "Toplu dosya silme (del /s)"),
        (r"\bformat\b\s+[a-z]:", "Disk bicimlendirme"),
        (r"\bdiskpart\b", "Disk bolum yonetimi"),
        (r"\bmkfs\b", "Dosya sistemi olusturma"),
        (r"\bcipher\b\s+/w", "Guvenli silme (cipher /w)"),
        # --- Kayit defteri ---
        (r"\breg\s+(add|delete|import)\b", "Kayit defteri degisikligi"),
        (r"\bregedit\b", "Kayit defteri duzenleyici"),
        (r"\bset-itemproperty\b.*hk(lm|cu|cr|u|cc):", "Kayit defteri yazma"),
        (r"\bnew-itemproperty\b.*hk(lm|cu):", "Kayit defteri yazma"),
        (r"\bremove-itemproperty\b.*hk(lm|cu):", "Kayit defteri silme"),
        # --- Kullanici / yetki yonetimi ---
        (r"\bnet\s+(user|localgroup|group)\b", "Kullanici/grup yonetimi"),
        (r"\bnew-localuser\b", "Kullanici olusturma"),
        (r"\badd-localgroupmember\b", "Grup uyeligi degisikligi"),
        (r"\bicacls\b", "Dosya izin degisikligi"),
        (r"\btakeown\b", "Dosya sahipligi degisikligi"),
        (r"\bcacls\b", "Dosya izin degisikligi"),
        # --- Sistem ayarlari / servisler ---
        (r"\b(shutdown|restart-computer|stop-computer)\b", "Sistem kapatma"),
        (r"\bbcdedit\b", "Onyukleme yapilandirmasi"),
        (r"\bset-executionpolicy\b", "PowerShell yurutme politikasi"),
        (r"\b(sc|set-service|new-service)\s+(config|create|delete)", "Servis yonetimi"),
        (r"\bschtasks\b", "Zamanlanmis gorev"),
        (r"\bregister-scheduledtask\b", "Zamanlanmis gorev"),
        (r"\bwmic\b", "WMI komut satiri"),
        (r"\bnetsh\b", "Ag yapilandirmasi"),
        (r"\b(disable|enable)-computerrestore\b", "Sistem geri yukleme"),
        (r"\bvssadmin\b", "Golge kopya yonetimi"),
        (r"\bwbadmin\b", "Yedekleme yonetimi"),
        # --- Uzaktan kod indirme/calistirma ---
        (r"\binvoke-expression\b", "Dinamik kod calistirma (iex)"),
        (r"(^|[\s;|])iex([\s(]|$)", "Dinamik kod calistirma (iex)"),
        (r"\binvoke-webrequest\b.*\|\s*(iex|invoke-expression)", "Indir-ve-calistir"),
        (r"\bcurl\b.*\|\s*(bash|sh|powershell|pwsh)", "Indir-ve-calistir"),
        (r"\bwget\b.*\|\s*(bash|sh)", "Indir-ve-calistir"),
        (r"\bpowershell\b.*\s-e(nc|ncodedcommand)?\s", "Base64 kodlanmis komut"),
        (r"\bstart-process\b.*-verb\s+runas", "Yonetici olarak calistirma"),
        (r"\bcertutil\b.*-urlcache", "certutil ile dosya indirme"),
        (r"\bbitsadmin\b", "BITS ile dosya indirme"),
        # --- Kimlik bilgisi erisimi ---
        (r"\bget-credential\b", "Kimlik bilgisi istemi"),
        (r"\bcmdkey\b", "Kimlik bilgisi deposu"),
        (r"\bmimikatz\b", "Kimlik bilgisi cikarma araci"),
        (r"\bget-storedcredential\b", "Kimlik bilgisi okuma"),
        (r"lsass", "LSASS surec erisimi"),
        # --- Git tarihini yeniden yazma / uzak depoya yazma ---
        (r"\bgit\s+push\b.*(--force|-f\b)", "Zorla push (tarih yeniden yazilir)"),
        (r"\bgit\s+push\b", "Uzak depoya gonderim - kullanici kendisi yapmalidir"),
        (r"\bgit\s+reset\b.*--hard", "Calisma agacini geri donusu olmadan sifirlama"),
        (r"\bgit\s+clean\b.*-[a-z]*f", "Takipsiz dosyalari silme"),
        (r"\bgit\s+filter-branch\b", "Tarih yeniden yazma"),
        (r"\bgit\s+config\b.*user\.(name|email)", "Git kimlik degisikligi"),
        # --- Kabuk karistirma / arka plan ---
        (r"\bcmd(\.exe)?\s+/[ck]\b", "PowerShell icinde CMD calistirma"),
        (r"\bstart-job\b", "Arka plan isi (izlenemez)"),
        (r"\bstart-process\b.*-nonewwindow.*-passthru", "Izlenemeyen arka plan sureci"),
        (r"&\s*$", "Arka plana atma"),
        # --- Ortam / sir sizdirma ---
        # NOT: Asagidaki desenler yalnizca **ek** bir katmandir. Asil koruma
        # okuyucu-bagimsizdir: bkz. SENSITIVE_TARGETS ve
        # CommandPolicy._check_sensitive_targets. Belirli bir okuyucuyu
        # (cat/type/get-content) sayan bir liste, sayilmayan bir okuyucuyla
        # (head, tail, findstr, select-string, more, python -c ...) daima
        # asilabilir; bu yuzden karar komut adina degil **hedefe** bakar.
        (r"\bgci\s+env:", "Tum ortam degiskenlerini listeleme"),
        (r"\bget-childitem\s+env:", "Tum ortam degiskenlerini listeleme"),
        (r"\bls\s+env:", "Tum ortam degiskenlerini listeleme"),
        (r"\bdir\s+env:", "Tum ortam degiskenlerini listeleme"),
        (r"\bprintenv\b", "Tum ortam degiskenlerini listeleme"),
        (r"\$env:", "Ortam degiskeni okuma"),
        (r"%[a-z_]*(key|secret|token|password|pwd)[a-z_]*%", "Ortam degiskeni okuma"),
        # (Eski, okuyucuya ozgu desenler. SENSITIVE_TARGETS bunlari zaten
        #  kapsar; derinlemesine savunma icin korunurlar. ".env.example" bir
        #  SABLONDUR ve sir icermez - negatif ileri bakisla haric tutulur.)
        (r"type\s+.*\.env(?!\.(example|sample|template|dist))\b", ".env dosyasini okuma"),
        (
            r"\bget-content\b.*\.env(?!\.(example|sample|template|dist))\b",
            ".env dosyasini okuma",
        ),
        (r"\bcat\b.*\.env(?!\.(example|sample|template|dist))\b", ".env dosyasini okuma"),
    )
)

# --------------------------------------------------------------------------
#  Hassas hedefler - OKUYUCUDAN BAGIMSIZ ENGELLEME
# --------------------------------------------------------------------------
#: Bir komutun **herhangi** bir argumaninda gecerse komut kosulsuz engellenir.
#:
#: Gerekce (guvenlik incelemesi bulgusu HTL-H1): onceki surumde yalnizca uc
#: okuyucu (``type``, ``get-content``, ``cat``) ``.env`` icin engelleniyordu,
#: ancak ``head``, ``tail``, ``findstr``, ``select-string`` komutlari **SAFE**
#: siniftaydi - yani hic onay sorulmadan calisiyorlardi. Bir modelin onerdigi
#: ``head .env`` komutu oturum imzalama anahtarini ve alan sifreleme anahtarini
#: onaysiz ekrana basabiliyordu. Ayni sekilde ``get-content data/hotel.db``
#: misafir veritabanini okuyabiliyordu. Cozum: karar komutun adina degil,
#: **dokundugu dosyaya** bakar; yeni bir okuyucu eklemek korumayi delmez.
#:
#: Her giris ``(regex, insan-okunur gerekce)`` ciftidir ve komutun
#: **tek tek argumanlari** uzerinde (kucuk harfe cevrilmis, tirnaklari
#: soyulmus, ters bolu ``/`` yapilmis olarak) aranir.
SENSITIVE_TARGETS: Final[tuple[tuple[re.Pattern[str], str], ...]] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        # .env ve turevleri: ".env", ".env.local", "config/.env", "env.production"
        # ".env" ve ".env.<ortam>" kapali; ".env.example" gibi SABLONLAR acik -
        # sablon dosyasi sir icermez ve kullanicinin onu okuyabilmesi gerekir.
        (r"(^|[/])\.env$", "Ortam dosyasi (.env) - sir icerir"),
        (
            r"(^|[/])\.env\.(?!example|sample|template|dist)",
            "Ortam dosyasi (.env.*) - sir icerir",
        ),
        (r"(^|[/])env\.(local|dev|prod|production|test)$", "Ortam dosyasi - sir icerir"),
        # Anahtar / sertifika materyali
        (r"\.(pem|key|pfx|p12|crt|cer|jks|keystore|asc|gpg)$", "Anahtar/sertifika dosyasi"),
        (r"(^|[/])id_(rsa|dsa|ecdsa|ed25519)", "SSH ozel anahtari"),
        (r"(^|[/])\.ssh([/]|$)", "SSH anahtar klasoru"),
        (r"(^|[/])\.aws([/]|$)", "Bulut kimlik bilgisi klasoru"),
        (r"(^|[/])\.netrc$", "Kimlik bilgisi dosyasi"),
        (r"(^|[/])\.git-credentials$", "Git kimlik bilgisi dosyasi"),
        (r"(^|[/])credentials(\.json)?$", "Kimlik bilgisi dosyasi"),
        (r"client_secret", "OAuth istemci sirri"),
        (r"(^|[/])\.secrets\.baseline", "Sir tarama temel dosyasi"),
        (r"(^|[/])secrets?([/]|$)", "Sir klasoru"),
        # Isletme verisi: misafir veritabani, yedek, dokum
        (r"\.(db|sqlite|sqlite3|db-wal|db-shm|db-journal)$", "Veritabani dosyasi - kisisel veri"),
        (r"\.(dump|bak|sql)$", "Veritabani dokumu/yedegi - kisisel veri"),
        (r"(^|[/])(data|backups)([/]|$)", "Veri/yedek klasoru - kisisel veri"),
        # Genel anahtar-benzeri DOSYA adlari. Uzanti sarti bilincli: yalnizca
        # "api_key" dizgesini aramak (findstr api_key app/core/config.py)
        # mesru bir islemdir ve engellenmemelidir; engellenen sey o adi tasiyan
        # bir DOSYAYA dokunmaktir.
        (
            r"(^|[/])[^/]*api[_-]?key[^/]*\.(txt|json|env|key|cfg|conf|ini|ya?ml|xml|log)$",
            "Anahtar dosyasi",
        ),
        (
            r"(^|[/])[^/]*password[^/]*\.(txt|json|csv|xlsx?|key|env|cfg|conf|ini|ya?ml|log)$",
            "Parola dosyasi",
        ),
    )
)

# --------------------------------------------------------------------------
#  Izin listesi
# --------------------------------------------------------------------------
#: Salt okunur, onaysiz calistirilabilen komutlar.
SAFE_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "git status",
        "git log",
        "git diff",
        "git show",
        "git branch",
        "git remote",
        "git stash list",
        "git rev-parse",
        "git ls-files",
        "python --version",
        "python -V",
        "pip list",
        "pip show",
        "pip --version",
        "pytest",
        "ruff",
        "black",
        "mypy",
        "bandit",
        "pip-audit",
        "alembic",
        "dir",
        "ls",
        "get-childitem",
        "pwd",
        "get-location",
        "where",
        "which",
        "type",
        "get-content",
        "cat",
        "head",
        "tail",
        "findstr",
        "select-string",
        "echo",
        "write-output",
        "measure-object",
        "sort-object",
        "select-object",
    }
)

#: Degisiklik yapan ama izin verilen komut onekleri (onay gerekir).
WRITE_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "git add",
        "git commit",
        "git checkout",
        "git switch",
        "git restore",
        "git merge",
        "git stash",
        "git tag",
        "git cherry-pick",
        "git revert",
        "pip install",
        "pip uninstall",
        "alembic revision",
        "alembic upgrade",
        "alembic downgrade",
        "alembic stamp",
        "python -m app.cli",
        "new-item",
        "set-content",
        "add-content",
        "copy-item",
        "move-item",
        "mkdir",
        "touch",
        "copy",
        "move",
    }
)

#: Riskli ama tumuyle yasak olmayan komutlar (onay + gerekce).
DANGEROUS_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "remove-item",
        "rm",
        "git branch -d",
        "git branch -D",
        "alembic downgrade base",
    }
)

#: Komut icinde gecerse sir sizintisi riski doguran ifadeler.
SECRET_MARKERS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "api-key",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "nvapi-",
    "sk-",
    "bearer ",
)


@dataclass(frozen=True, slots=True)
class CommandDecision:
    """Bir komut icin verilen karar."""

    command: str
    risk: RiskLevel
    reason: str
    """Kullaniciya gosterilecek Turkce aciklama."""

    matched_rule: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.risk is not RiskLevel.BLOCKED

    @property
    def needs_approval(self) -> bool:
        return self.allowed and self.risk.requires_approval


@dataclass(slots=True)
class CommandPolicy:
    """Komut degerlendirme politikasi."""

    sandbox_root: Path = field(default_factory=lambda: get_settings().devcenter.sandbox_root)
    allow_network: bool = False
    """``pip install`` gibi ag erisimi gerektiren komutlara izin verilsin mi?"""

    max_command_length: int = 2000

    # ---------------------------------------------------------------- #
    def evaluate(self, command: str, *, cwd: Path | None = None) -> CommandDecision:
        """Komutu degerlendirir ve karar dondurur."""
        raw = (command or "").strip()

        if not raw:
            return CommandDecision(raw, RiskLevel.BLOCKED, "Bos komut calistirilamaz.")

        if len(raw) > self.max_command_length:
            return CommandDecision(
                raw,
                RiskLevel.BLOCKED,
                f"Komut cok uzun ({len(raw)} karakter). Bu genellikle kodlanmis "
                "veya gizlenmis bir komuta isaret eder.",
            )

        # --- 1) Calisma dizini sandbox icinde mi? ---
        if cwd is not None:
            problem = self._check_cwd(cwd)
            if problem:
                return CommandDecision(raw, RiskLevel.BLOCKED, problem)

        # --- 2) Yasak desenler (koşulsuz) ---
        for pattern, reason in BLOCKED_PATTERNS:
            if pattern.search(raw):
                log.warning(
                    "komut_engellendi",
                    reason=reason,
                    pattern=pattern.pattern,
                )
                return CommandDecision(
                    raw,
                    RiskLevel.BLOCKED,
                    f"Bu komut guvenlik politikasi geregi engellendi: {reason}.",
                    matched_rule=pattern.pattern,
                )

        # --- 3) Hassas dosya hedefi var mi? (OKUYUCUDAN BAGIMSIZ) ---
        #
        # Bu kontrol izin listesinden ONCE calisir: "guvenli" siniftaki bir
        # okuyucu (head/tail/findstr/select-string/cat/type/get-content...)
        # bile sir veya kisisel veri iceren bir dosyaya dokunuyorsa komut
        # calistirilmaz. Bkz. SENSITIVE_TARGETS.
        sensitive = self._check_sensitive_targets(raw)
        if sensitive:
            return CommandDecision(raw, RiskLevel.BLOCKED, sensitive[0], matched_rule=sensitive[1])

        # --- 4) Sandbox disina yol referansi var mi? ---
        path_problem = self._check_paths(raw)
        if path_problem:
            return CommandDecision(raw, RiskLevel.BLOCKED, path_problem)

        warnings: list[str] = []

        # --- 5) Sir sizintisi uyarisi ---
        lowered = raw.lower()
        for marker in SECRET_MARKERS:
            if marker in lowered:
                warnings.append(
                    f"Komut '{marker}' ifadesini iceriyor. Gizli bilgi iceren "
                    "komutlar loglanmaz ama yine de dikkatli olun."
                )
                break

        # --- 6) Zincirleme komut ---
        if self._has_chaining(raw):
            warnings.append(
                "Komut birden fazla islem zinciri iceriyor; her parcasini "
                "ayri ayri gozden gecirin."
            )

        # --- 7) Izin listesi eslesmesi ---
        normalized = " ".join(lowered.split())

        for prefix in sorted(DANGEROUS_COMMANDS, key=len, reverse=True):
            if normalized.startswith(prefix):
                return CommandDecision(
                    raw,
                    RiskLevel.DANGEROUS,
                    "Bu komut geri alinmasi zor bir degisiklik yapar. "
                    "Devam etmeden once gerekcesini dogrulayin.",
                    matched_rule=prefix,
                    warnings=tuple(warnings),
                )

        for prefix in sorted(WRITE_COMMANDS, key=len, reverse=True):
            if normalized.startswith(prefix):
                if prefix.startswith("pip install") and not self.allow_network:
                    return CommandDecision(
                        raw,
                        RiskLevel.BLOCKED,
                        "Bagimlilik kurulumu bu oturumda kapalidir. Yeni bir paket "
                        "gerekiyorsa once requirements.txt guncellenmeli ve "
                        "kurulum kullanici tarafindan yapilmalidir.",
                        matched_rule=prefix,
                    )
                return CommandDecision(
                    raw,
                    RiskLevel.WRITE,
                    "Bu komut dosya veya depo uzerinde degisiklik yapar.",
                    matched_rule=prefix,
                    warnings=tuple(warnings),
                )

        for prefix in sorted(SAFE_COMMANDS, key=len, reverse=True):
            if normalized == prefix or normalized.startswith(prefix + " "):
                # Guvenli komut bile zincirleme iceriyorsa onay istenir:
                # "git status; rm -r x" ilk parcasiyla guvenli gorunur.
                if self._has_chaining(raw):
                    return CommandDecision(
                        raw,
                        RiskLevel.WRITE,
                        "Komut guvenli bir komutla basliyor ancak zincirleme "
                        "islem iceriyor; bu yuzden onay gerekiyor.",
                        matched_rule=prefix,
                        warnings=tuple(warnings),
                    )
                return CommandDecision(
                    raw,
                    RiskLevel.SAFE,
                    "Salt okunur komut.",
                    matched_rule=prefix,
                    warnings=tuple(warnings),
                )

        # --- 8) Bilinmeyen komut: asla sessizce calistirilmaz ---
        return CommandDecision(
            raw,
            RiskLevel.WRITE,
            "Bu komut izin listesinde yok. Ne yaptigini dogrulamadan " "onaylamayin.",
            warnings=tuple(warnings),
        )

    # ---------------------------------------------------------------- #
    def _check_cwd(self, cwd: Path) -> str | None:
        """Calisma dizini sandbox icinde mi?"""
        try:
            resolved = Path(cwd).resolve()
            root = self.sandbox_root.resolve()
        except OSError as exc:  # pragma: no cover - gecersiz yol
            return f"Calisma dizini cozulemedi: {exc}"

        if resolved != root and root not in resolved.parents:
            return (
                f"Calisma dizini proje klasorunun disinda: {resolved}\n"
                f"Islemler yalnizca {root} icinde yapilabilir."
            )
        return None

    @staticmethod
    def _check_sensitive_targets(command: str) -> tuple[str, str] | None:
        """Komut hassas bir dosyaya dokunuyor mu? (okuyucudan bagimsiz)

        Komutun **her argumani** :data:`SENSITIVE_TARGETS` desenlerine karsi
        sinanir. Eslesme varsa ``(gerekce_metni, eslesen_desen)`` doner.

        Neden komut adina bakilmiyor?
        -----------------------------
        Bir izin listesi "hangi ikili calisir" sorusunu cozer; "o ikili neyi
        okur" sorusunu cozmez. ``head``, ``tail``, ``findstr``,
        ``select-string`` gibi komutlar mesru sekilde SAFE siniftadir - ama
        hedefleri ``.env`` ise sonuc ayni: sir ekrana basilir. Bu yuzden
        engelleme **hedefe** baglanmistir.

        >>> CommandPolicy._check_sensitive_targets("head .env") is not None
        True
        >>> CommandPolicy._check_sensitive_targets("git status") is None
        True
        """
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            # Dengesiz tirnak: ayristirilamayan komut hassas hedef sinamasindan
            # kacamamali. Ham metni tek parca gibi degerlendir.
            tokens = [command]

        for token in tokens:
            cleaned = token.strip("'\"").replace("\\", "/").strip().lower()
            if not cleaned:
                continue
            # "-Path" gibi bayrak adlari degil, degerleri onemlidir; ancak
            # "-Path=.env" bicimini de yakalamak icin '=' sonrasina da bakilir.
            candidates = [cleaned]
            if "=" in cleaned:
                candidates.append(cleaned.split("=", 1)[1])
            if ":" in cleaned and not re.match(r"^[a-z]:/", cleaned):
                candidates.append(cleaned.split(":", 1)[1])

            for value in candidates:
                if not value:
                    continue
                for pattern, reason in SENSITIVE_TARGETS:
                    if pattern.search(value):
                        log.warning(
                            "hassas_hedef_engellendi",
                            reason=reason,
                            pattern=pattern.pattern,
                        )
                        return (
                            "Bu komut hassas bir dosyaya eriseceginden guvenlik "
                            f"politikasi geregi engellendi: {reason}. "
                            "Komutun adi degil, dokundugu dosya belirleyicidir.",
                            pattern.pattern,
                        )
        return None

    def _check_paths(self, command: str) -> str | None:
        """Komuttaki mutlak yollarin sandbox disina cikmadigini dogrular.

        Windows'ta ``C:\\Windows\\System32`` gibi sistem klasorleri ve
        kullanicinin ev dizini disaridadir. Goreli ``..`` kacislari da
        cozumlenerek kontrol edilir.
        """
        root = self.sandbox_root.resolve()

        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            # Dengesiz tirnak - guvenli tarafta kal.
            return "Komuttaki tirnak isaretleri dengesiz; ayristirilamadi."

        for token in tokens:
            cleaned = token.strip("'\"")
            if not cleaned:
                continue

            looks_like_path = (
                re.match(r"^[a-zA-Z]:[\\/]", cleaned)
                or cleaned.startswith("\\\\")
                or ".." in cleaned.replace("...", "")
            )
            if not looks_like_path:
                continue

            if cleaned.startswith("\\\\"):
                return f"Ag paylasimina erisim engellendi: {cleaned}"

            try:
                candidate = (
                    (root / cleaned).resolve()
                    if not Path(cleaned).is_absolute()
                    else Path(cleaned).resolve()
                )
            except (OSError, ValueError):
                continue

            if candidate != root and root not in candidate.parents:
                return (
                    f"Proje klasoru disindaki bir yola erisim engellendi:\n"
                    f"  {candidate}\n"
                    f"Izin verilen kok: {root}"
                )
        return None

    @staticmethod
    def _has_chaining(command: str) -> bool:
        """Komut zincirleme/yonlendirme iceriyor mu?

        Tirnak icindeki noktali virgul ve boru isaretleri sayilmaz; aksi halde
        ``git commit -m "a; b"`` yanlislikla zincir sayilirdi.
        """
        depth_single = False
        depth_double = False
        for index, char in enumerate(command):
            if char == "'" and not depth_double:
                depth_single = not depth_single
            elif char == '"' and not depth_single:
                depth_double = not depth_double
            elif not depth_single and not depth_double:
                if char in ";&":
                    return True
                if char == "|":
                    # Tek boru: PowerShell nesne hatti; guvenli sayilir.
                    # Cift boru (||) mantiksal zincirdir.
                    if index + 1 < len(command) and command[index + 1] == "|":
                        return True
                if char == ">":
                    return True
        return False


#: Varsayilan politika ornegi.
_default_policy: CommandPolicy | None = None


def get_policy() -> CommandPolicy:
    """Varsayilan politika ornegini dondurur."""
    global _default_policy
    if _default_policy is None:
        _default_policy = CommandPolicy()
    return _default_policy


def reset_policy() -> None:
    """Politika ornegini sifirlar (ayar degisikligi ve testler icin)."""
    global _default_policy
    _default_policy = None


def evaluate_command(command: str, *, cwd: Path | None = None) -> CommandDecision:
    """Komutu varsayilan politikayla degerlendirir."""
    return get_policy().evaluate(command, cwd=cwd)


__all__ = [
    "BLOCKED_PATTERNS",
    "DANGEROUS_COMMANDS",
    "SAFE_COMMANDS",
    "SECRET_MARKERS",
    "SENSITIVE_TARGETS",
    "WRITE_COMMANDS",
    "CommandDecision",
    "CommandPolicy",
    "RiskLevel",
    "evaluate_command",
    "get_policy",
    "reset_policy",
]
