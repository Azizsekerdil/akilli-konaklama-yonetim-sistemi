"""Kalite zinciri: format -> lint -> tip -> test -> guvenlik.

Sira bilincli secilmistir:

1. **format** (black) - bicimlendirme once yapilir ki lint gurultusu azalsin
2. **lint** (ruff) - stil ve olasi hata desenleri
3. **tip** (mypy) - tip tutarliligi
4. **test** (pytest) - davranis dogrulugu; en onemli kapi
5. **guvenlik** (bandit) - guvenlik desenleri; en yavas adim en sona

Zincir **ilk basarisizlikta durmaz**: tum adimlar calisir ve sonuclar birlikte
raporlanir. Nedeni, kullanicinin tek seferde tum sorunlari gormesidir; her
duzeltmeden sonra yeni bir hatayla karsilasmak yorucudur.

Ancak **testler basarisizsa dal birlestirilmez** - bu kural
:mod:`app.devcenter.session` icinde uygulanir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.core.log import get_logger
from app.devcenter.terminal import CommandResult, run_command

log = get_logger(__name__)


class StepOutcome(str, Enum):
    """Bir kalite adiminin sonucu."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    """Arac calistirilamadi (kurulu degil vb.)."""

    @property
    def label(self) -> str:
        return {
            "passed": "Gecti",
            "failed": "Basarisiz",
            "skipped": "Atlandi",
            "error": "Calistirilamadi",
        }[self.value]


@dataclass(slots=True)
class QualityStep:
    """Zincirdeki tek bir adim."""

    key: str
    title: str
    command: str
    blocking: bool = False
    """``True`` ise bu adim gecmeden degisiklik birlestirilemez."""

    optional: bool = False
    """Arac kurulu degilse hata degil, atlanmis sayilir."""


@dataclass(slots=True)
class StepResult:
    """Bir adimin calistirma sonucu."""

    step: QualityStep
    outcome: StepOutcome
    result: CommandResult | None = None
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.outcome in {StepOutcome.PASSED, StepOutcome.SKIPPED}

    @property
    def duration(self) -> float:
        return self.result.duration_seconds if self.result else 0.0


@dataclass(slots=True)
class QualityReport:
    """Tum zincirin sonucu."""

    steps: list[StepResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(step.passed for step in self.steps)

    @property
    def blocking_passed(self) -> bool:
        """Birlestirmeyi engelleyen adimlarin tamami gecti mi?"""
        return all(s.passed for s in self.steps if s.step.blocking)

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if not s.passed]

    @property
    def total_duration(self) -> float:
        return round(sum(s.duration for s in self.steps), 1)

    def summary_lines(self) -> list[str]:
        """Arayuzde/raporda gosterilecek ozet satirlari."""
        lines: list[str] = []
        for step in self.steps:
            mark = {
                StepOutcome.PASSED: "[OK]",
                StepOutcome.FAILED: "[BASARISIZ]",
                StepOutcome.SKIPPED: "[ATLANDI]",
                StepOutcome.ERROR: "[HATA]",
            }[step.outcome]
            blocking = " (zorunlu)" if step.step.blocking else ""
            lines.append(f"{mark} {step.step.title}{blocking} - {step.duration:.1f} sn")
        return lines

    def failure_detail(self) -> str:
        """Basarisiz adimlarin ciktisi - kullaniciya gosterilir."""
        chunks: list[str] = []
        for step in self.failed_steps:
            chunks.append(f"### {step.step.title}")
            if step.detail:
                chunks.append(step.detail)
            if step.result:
                chunks.append(step.result.output[:4000])
        return "\n\n".join(chunks)


def default_steps(*, target: str = "app tests") -> list[QualityStep]:
    """Varsayilan kalite zinciri.

    ``target`` daraltilarak yalnizca degisen dosyalar denetlenebilir; bu,
    buyuk projelerde zinciri hizlandirir.
    """
    venv = ".\\.venv\\Scripts"
    return [
        QualityStep(
            key="format",
            title="Bicimlendirme (black)",
            command=f"{venv}\\black.exe {target} --quiet",
        ),
        QualityStep(
            key="lint",
            title="Lint (ruff)",
            command=f"{venv}\\ruff.exe check {target} --output-format=concise",
            blocking=True,
        ),
        QualityStep(
            key="typecheck",
            title="Tip kontrolu (mypy)",
            command=f"{venv}\\mypy.exe app --no-error-summary",
            optional=True,
        ),
        QualityStep(
            key="test",
            title="Testler (pytest)",
            command=f'{venv}\\python.exe -m pytest -q --no-header -m "not live"',
            blocking=True,
        ),
        QualityStep(
            key="security",
            title="Guvenlik taramasi (bandit)",
            command=f"{venv}\\bandit.exe -q -c pyproject.toml -r app",
            optional=True,
        ),
    ]


def run_quality_chain(
    *,
    root: Path,
    steps: list[QualityStep] | None = None,
    timeout_per_step: int = 900,
) -> QualityReport:
    """Kalite zincirini calistirir ve rapor dondurur.

    Adimlar ``approved=True`` ile calistirilir: bunlar sabit, politika
    tarafindan bilinen ve kullanicinin gorev basinda onayladigi araclardir.
    Kullanicidan gelen keyfi komutlar bu yoldan GECMEZ.
    """
    report = QualityReport()

    for step in steps or default_steps():
        log.info("kalite_adimi_basladi", step=step.key)
        try:
            result = run_command(
                step.command,
                cwd=root,
                timeout=timeout_per_step,
                approved=True,
            )
        except Exception as exc:
            report.steps.append(
                StepResult(
                    step=step,
                    outcome=StepOutcome.ERROR,
                    detail=f"Adim calistirilamadi: {exc}",
                )
            )
            continue

        if result.success:
            outcome = StepOutcome.PASSED
        elif step.optional and _looks_like_missing_tool(result):
            outcome = StepOutcome.SKIPPED
        else:
            outcome = StepOutcome.FAILED

        report.steps.append(StepResult(step=step, outcome=outcome, result=result))
        log.info("kalite_adimi_bitti", step=step.key, outcome=outcome.value)

    log.info(
        "kalite_zinciri_tamamlandi",
        all_passed=report.all_passed,
        blocking_passed=report.blocking_passed,
        duration=report.total_duration,
    )
    return report


def _looks_like_missing_tool(result: CommandResult) -> bool:
    """Arac kurulu olmadigi icin mi basarisiz oldu?"""
    text = (result.stderr + result.stdout).lower()
    markers = (
        "is not recognized",
        "tanimlanmadi",
        "cannot find path",
        "bulunamadi",
        "no module named",
    )
    return any(marker in text for marker in markers)


__all__ = [
    "QualityReport",
    "QualityStep",
    "StepOutcome",
    "StepResult",
    "default_steps",
    "run_quality_chain",
]
