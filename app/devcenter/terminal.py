"""Kisitlanmis komut calistirma.

Guvenlik onlemleri
------------------
* **Politika zorunlulugu**: her komut :mod:`app.devcenter.policy` tarafindan
  degerlendirilir. Onay gerektiren bir komut ``approved=True`` olmadan
  calistirilamaz - bu bayrak yalnizca kullanici arayuzde onay verdiginde
  gecirilir.
* **Sandbox**: calisma dizini proje kokunun disina cikamaz.
* **Zaman asimi**: her komutun ust siniri vardir; sonsuza kadar calisan bir
  islem arayuzu kilitlemez.
* **Cikti siniri**: cok buyuk cikti kesilir; bellek tuketimi sinirlanir.
* **Temiz ortam**: alt surece **gizli ortam degiskenleri gecirilmez**
  (``HOTEL_*_API_KEY``, ``HOTEL_SECRET_KEY`` vb. temizlenir).
* **Maskeleme**: ciktida API anahtari/parola kalibi bulunursa maskelenir.
* **Arka plan yok**: her komut bekleyerek calistirilir; izlenemeyen arka plan
  sureci baslatilmaz.
* **Denetim**: calistirilan ve engellenen her komut denetim gunlugune yazilir.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import CommandBlockedError, SandboxViolationError
from app.core.log import get_logger, mask_text
from app.devcenter.policy import CommandDecision, CommandPolicy, RiskLevel, get_policy

log = get_logger(__name__)

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


@dataclass(slots=True)
class CommandResult:
    """Bir komutun calistirma sonucu."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    cwd: str
    truncated: bool = False
    timed_out: bool = False
    decision: CommandDecision | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        """Birlesik cikti (stdout + stderr)."""
        parts = [self.stdout.rstrip()]
        if self.stderr.strip():
            parts.append("--- hata akisi ---")
            parts.append(self.stderr.rstrip())
        return "\n".join(p for p in parts if p)

    def summary(self) -> str:
        """Kullaniciya gosterilecek tek satirlik ozet."""
        if self.timed_out:
            return f"Zaman asimi ({self.duration_seconds:.1f} sn)"
        state = "basarili" if self.success else f"hata (cikis kodu {self.exit_code})"
        return f"{state} - {self.duration_seconds:.1f} sn"


def _clean_environment() -> dict[str, str]:
    """Alt surec icin gizli degerleri temizlenmis ortam uretir.

    Yapay zekanin onerdigi bir komut ``echo $env:HOTEL_NVIDIA_API_KEY``
    calistirsa bile ortada anahtar bulunmaz. Politika bunu zaten engeller;
    bu ikinci savunma katmanidir.
    """
    cleaned = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
            continue
        cleaned[key] = value

    # Alt surecin uygulama veritabanina yazmasini zorlastirmak icin
    # test ortami isareti birakilir; uygulama kodu bunu gorurse uyarir.
    cleaned["HOTEL_DEVCENTER_CHILD"] = "1"
    return cleaned


def run_command(
    command: str,
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    approved: bool = False,
    policy: CommandPolicy | None = None,
    max_output_bytes: int | None = None,
) -> CommandResult:
    """Komutu politika denetiminden gecirerek calistirir.

    Parameters
    ----------
    approved:
        Kullanici arayuzde komutu **gorup onayladiysa** ``True``. Onay
        gerektiren bir komut bu bayrak olmadan calistirilmaz.

    Raises
    ------
    CommandBlockedError
        Komut politika tarafindan engellendiyse veya onay gerekip de
        verilmediyse.
    SandboxViolationError
        Calisma dizini proje kokunun disindaysa.
    """
    settings = get_settings().devcenter
    active_policy = policy or get_policy()
    root = active_policy.sandbox_root
    work_dir = Path(cwd) if cwd else root

    # --- Sandbox dogrulamasi ---
    try:
        resolved_cwd = work_dir.resolve()
    except OSError as exc:  # pragma: no cover
        raise SandboxViolationError(detail=str(exc)) from exc

    if resolved_cwd != root.resolve() and root.resolve() not in resolved_cwd.parents:
        raise SandboxViolationError(
            detail=f"cwd={resolved_cwd}, root={root}",
            context={"cwd": str(resolved_cwd)},
        )
    if not resolved_cwd.exists():
        raise SandboxViolationError("Calisma dizini bulunamadi.", detail=str(resolved_cwd))

    # --- Politika ---
    decision = active_policy.evaluate(command, cwd=resolved_cwd)

    if decision.risk is RiskLevel.BLOCKED:
        log.warning("komut_engellendi", risk=decision.risk.value, reason=decision.reason)
        raise CommandBlockedError(decision.reason, command=command)

    if decision.needs_approval and not approved:
        raise CommandBlockedError(
            "Bu komut calistirilmadan once onaylanmalidir.",
            command=command,
            context={"risk": decision.risk.value, "reason": decision.reason},
        )

    effective_timeout = timeout or settings.command_timeout
    output_limit = max_output_bytes or settings.max_output_bytes

    # --- Calistirma ---
    # PowerShell kullanilir; CMD ile KARISTIRILMAZ (farkli sozdizimleri
    # birbirine gecerse sessiz hatalar olusur).
    argv = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]

    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(  # noqa: S603 - argv listesi, shell=False
            argv,
            cwd=str(resolved_cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=effective_timeout,
            env=_clean_environment(),
            shell=False,
            check=False,
        )
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (
            exc.stdout.decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        stderr += f"\n[Komut {effective_timeout} saniye icinde tamamlanmadi ve durduruldu.]"
        exit_code = -1
    except OSError as exc:  # pragma: no cover - kabuk bulunamadi
        stdout, stderr, exit_code = "", f"Komut calistirilamadi: {exc}", -1

    duration = time.monotonic() - started

    # --- Cikti siniri ve maskeleme ---
    truncated = False
    if len(stdout) > output_limit:
        stdout = stdout[:output_limit] + f"\n[... cikti {output_limit} bayt sonrasi kesildi]"
        truncated = True
    if len(stderr) > output_limit:
        stderr = stderr[:output_limit] + "\n[... kesildi]"
        truncated = True

    # Ciktida kazara bir anahtar/parola gorunurse maskelenir.
    stdout = mask_text(stdout)
    stderr = mask_text(stderr)

    result = CommandResult(
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=round(duration, 2),
        cwd=str(resolved_cwd),
        truncated=truncated,
        timed_out=timed_out,
        decision=decision,
    )

    log.info(
        "komut_calistirildi",
        risk=decision.risk.value,
        exit_code=exit_code,
        duration=result.duration_seconds,
        timed_out=timed_out,
    )
    return result


@dataclass(slots=True)
class CommandLog:
    """Oturum boyunca calistirilan komutlarin kaydi."""

    entries: list[CommandResult] = field(default_factory=list)

    def add(self, result: CommandResult) -> None:
        self.entries.append(result)

    @property
    def failed_count(self) -> int:
        return sum(1 for entry in self.entries if not entry.success)

    def as_text(self) -> str:
        """Rapor icin metin dokumu."""
        lines: list[str] = []
        for entry in self.entries:
            lines.append(f"$ {entry.command}")
            lines.append(f"  -> {entry.summary()}")
        return "\n".join(lines)


__all__ = ["CommandLog", "CommandResult", "run_command"]
