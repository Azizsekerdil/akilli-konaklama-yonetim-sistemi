<#
.SYNOPSIS
    Akilli Konaklama Yonetim Sistemi - uygulamayi baslatir.

.DESCRIPTION
    Masaustu arayuzunu (PySide6) baslatir. Baslamadan once ortamin hazir
    olup olmadigini kontrol eder ve eksik varsa ne yapilmasi gerektigini
    acikca soyler.

.PARAMETER Api
    Masaustu arayuzu yerine yalnizca FastAPI servisini baslatir.

.PARAMETER Debug
    Ayrintili log ile baslatir (HOTEL_LOG_LEVEL=DEBUG).

.EXAMPLE
    .\scripts\run.ps1

.EXAMPLE
    .\scripts\run.ps1 -Api
#>
[CmdletBinding()]
param(
    [switch]$Api,
    [switch]$Debug
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$VenvPythonw = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'

function Write-Err {
    param([string]$Message)
    Write-Host "[HATA] $Message" -ForegroundColor Red
}

# --- Ortam kontrolu ---
if (-not (Test-Path $VenvPython)) {
    Write-Err 'Sanal ortam bulunamadi.'
    Write-Host 'Once kurulumu calistirin:' -ForegroundColor Yellow
    Write-Host '    .\scripts\setup.ps1' -ForegroundColor Cyan
    exit 1
}

$envFile = Join-Path $ProjectRoot '.env'
if (-not (Test-Path $envFile)) {
    Write-Host '[!] .env dosyasi yok; varsayilan ayarlarla baslatiliyor.' -ForegroundColor Yellow
    Write-Host '    Onerilen: .\scripts\setup.ps1' -ForegroundColor Gray
}

if ($Debug) {
    $env:HOTEL_LOG_LEVEL = 'DEBUG'
    $env:HOTEL_APP_DEBUG = 'true'
}

Push-Location $ProjectRoot
try {
    if ($Api) {
        Write-Host 'FastAPI servisi baslatiliyor...' -ForegroundColor Cyan
        Write-Host 'Durdurmak icin Ctrl+C' -ForegroundColor Gray
        & $VenvPython -m app.api.server
    } else {
        Write-Host 'Masaustu arayuzu baslatiliyor...' -ForegroundColor Cyan
        & $VenvPython -m app.main
        if ($LASTEXITCODE -ne 0) {
            Write-Host ''
            Write-Err "Uygulama $LASTEXITCODE kodu ile sonlandi."
            Write-Host 'Loglar: logs\error.log' -ForegroundColor Yellow
            exit $LASTEXITCODE
        }
    }
} finally {
    Pop-Location
}
