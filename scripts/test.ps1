<#
.SYNOPSIS
    Kod kalitesi ve test zinciri.

.DESCRIPTION
    Sirasiyla calistirir:  format -> lint -> tip kontrolu -> test -> guvenlik
    Bu sira bilincli secilmistir: bicimlendirme once yapilir ki lint gurultusu
    azalsin; guvenlik taramasi en sona birakilir cunku en yavas adimdir.

    Herhangi bir adim basarisiz olursa betik sonraki adimlara devam eder ve
    sonunda ozet gosterir; boylece tek calistirmada tum sorunlar gorulur.

.PARAMETER Fast
    Yalnizca testleri calistirir (bicimlendirme/lint/guvenlik atlanir).

.PARAMETER Coverage
    Kapsam raporu uretir (htmlcov/index.html).

.PARAMETER Live
    Gercek dis servis gerektiren testleri de calistirir (LM Studio vb.).
    Varsayilan olarak bu testler ATLANIR.

.PARAMETER NoFix
    Bicimlendirme ve lint duzeltmelerini uygulamaz, yalnizca denetler.

.EXAMPLE
    .\scripts\test.ps1

.EXAMPLE
    .\scripts\test.ps1 -Coverage
#>
[CmdletBinding()]
param(
    [switch]$Fast,
    [switch]$Coverage,
    [switch]$Live,
    [switch]$NoFix
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvScripts = Join-Path $ProjectRoot '.venv\Scripts'
$VenvPython = Join-Path $VenvScripts 'python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host '[HATA] Sanal ortam yok. Once: .\scripts\setup.ps1' -ForegroundColor Red
    exit 1
}

$results = [ordered]@{}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    Write-Host ''
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Action
    $ok = ($LASTEXITCODE -eq 0)
    $script:results[$Name] = $ok
    if ($ok) {
        Write-Host "    [OK] $Name" -ForegroundColor Green
    } else {
        Write-Host "    [BASARISIZ] $Name" -ForegroundColor Red
    }
}

Push-Location $ProjectRoot
try {
    if (-not $Fast) {
        if ($NoFix) {
            Invoke-Step 'Bicimlendirme denetimi (black)' {
                & (Join-Path $VenvScripts 'black.exe') app tests --check --quiet
            }
            Invoke-Step 'Lint (ruff)' {
                & (Join-Path $VenvScripts 'ruff.exe') check app tests --output-format=concise
            }
        } else {
            Invoke-Step 'Bicimlendirme (black)' {
                & (Join-Path $VenvScripts 'black.exe') app tests --quiet
            }
            Invoke-Step 'Lint (ruff --fix)' {
                & (Join-Path $VenvScripts 'ruff.exe') check app tests --fix --output-format=concise
            }
        }

        Invoke-Step 'Tip kontrolu (mypy)' {
            & (Join-Path $VenvScripts 'mypy.exe') app --no-error-summary
        }
    }

    # --- Testler ---
    $pytestArgs = @('-q', '--no-header')
    if (-not $Live) {
        # Gercek dis servis gerektiren testler varsayilan olarak atlanir.
        $pytestArgs += @('-m', 'not live')
    }
    if ($Coverage) {
        $pytestArgs += @('--cov=app', '--cov-report=term-missing:skip-covered', '--cov-report=html')
    }

    Invoke-Step 'Testler (pytest)' {
        & $VenvPython -m pytest @pytestArgs
    }

    if (-not $Fast) {
        Invoke-Step 'Guvenlik taramasi (bandit)' {
            & (Join-Path $VenvScripts 'bandit.exe') -q -c pyproject.toml -r app
        }
        Invoke-Step 'Bagimlilik guvenligi (pip-audit)' {
            & (Join-Path $VenvScripts 'pip-audit.exe') --skip-editable
        }
    }
} finally {
    Pop-Location
}

# --- Ozet ---
Write-Host ''
Write-Host '========================================================' -ForegroundColor White
Write-Host '  OZET' -ForegroundColor White
Write-Host '========================================================' -ForegroundColor White
$failed = 0
foreach ($key in $results.Keys) {
    if ($results[$key]) {
        Write-Host ("  [OK]        " + $key) -ForegroundColor Green
    } else {
        Write-Host ("  [BASARISIZ] " + $key) -ForegroundColor Red
        $failed++
    }
}
Write-Host ''

if ($Coverage) {
    Write-Host "  Kapsam raporu: $(Join-Path $ProjectRoot 'htmlcov\index.html')" -ForegroundColor Cyan
    Write-Host ''
}

if ($failed -gt 0) {
    Write-Host "  $failed adim basarisiz." -ForegroundColor Red
    exit 1
}
Write-Host '  Tum adimlar basarili.' -ForegroundColor Green
exit 0
