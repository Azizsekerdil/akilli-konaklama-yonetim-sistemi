<#
.SYNOPSIS
    Akilli Konaklama Yonetim Sistemi - ilk kurulum betigi.

.DESCRIPTION
    Sirasiyla:
      1. Python surumunu dogrular (3.11 - 3.13)
      2. Sanal ortami olusturur (.venv)
      3. Bagimliliklari kurar
      4. .env dosyasi yoksa .env.example uzerinden guvenli bir baslangic uretir
         (HOTEL_SECRET_KEY rastgele uretilir)
      5. Veritabani goclerini uygular
      6. Guvenlik verilerini (izin/rol/yonetici) kurar
      7. Istege bagli demo veri ekler

    Betik idempotenttir: birden fazla calistirilmasi guvenlidir.

.PARAMETER DemoData
    Demo veri olusturur. Gercek isletme verisi olan bir kurulumda KULLANMAYIN.

.PARAMETER Force
    Mevcut sanal ortami siler ve yeniden olusturur.

.PARAMETER SkipDeps
    Bagimlilik kurulumunu atlar (yalnizca goc ve kurulum calisir).

.EXAMPLE
    .\scripts\setup.ps1
    Standart kurulum.

.EXAMPLE
    .\scripts\setup.ps1 -DemoData
    Kurulum + demo veri.
#>
[CmdletBinding()]
param(
    [switch]$DemoData,
    [switch]$Force,
    [switch]$SkipDeps
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $VenvPath 'Scripts\python.exe'

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    [!] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "    [HATA] $Message" -ForegroundColor Red
}

Write-Host ''
Write-Host '========================================================' -ForegroundColor White
Write-Host '  Akilli Konaklama Yonetim Sistemi - Kurulum' -ForegroundColor White
Write-Host '========================================================' -ForegroundColor White
Write-Host "  Proje klasoru: $ProjectRoot"

# ---------------------------------------------------------------------------
# 1) Python surumu
# ---------------------------------------------------------------------------
Write-Step 'Python surumu kontrol ediliyor'

$pythonExe = $null
foreach ($candidate in @('3.12', '3.11', '3.13')) {
    try {
        $out = & py "-$candidate" --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = @('py', "-$candidate")
            Write-Ok "Python $candidate bulundu ($out)"
            break
        }
    } catch {
        # bu surum yok, sonrakini dene
    }
}

if (-not $pythonExe) {
    try {
        $version = & python --version 2>&1
        if ($version -match 'Python (\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 11 -and $minor -le 13) {
                $pythonExe = @('python')
                Write-Ok "Python $major.$minor bulundu"
            } else {
                Write-Err "Python $major.$minor destekleniyor degil. 3.11, 3.12 veya 3.13 gerekir."
                Write-Host '    Indirme: https://www.python.org/downloads/'
                exit 1
            }
        }
    } catch {
        Write-Err 'Python bulunamadi.'
        Write-Host '    Python 3.11 veya 3.12 kurun: https://www.python.org/downloads/'
        Write-Host '    Kurulumda "Add Python to PATH" secenegini isaretleyin.'
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 2) Sanal ortam
# ---------------------------------------------------------------------------
Write-Step 'Sanal ortam hazirlaniyor'

if ($Force -and (Test-Path $VenvPath)) {
    Write-Warn 'Mevcut sanal ortam siliniyor (-Force)'
    Remove-Item -Recurse -Force $VenvPath
}

if (Test-Path $VenvPython) {
    Write-Ok 'Sanal ortam zaten mevcut'
} else {
    Write-Host '    Olusturuluyor... (bir dakika surebilir)'
    & $pythonExe[0] $pythonExe[1..($pythonExe.Length - 1)] -m venv $VenvPath
    if (-not (Test-Path $VenvPython)) {
        Write-Err 'Sanal ortam olusturulamadi.'
        exit 1
    }
    Write-Ok 'Sanal ortam olusturuldu'
}

# ---------------------------------------------------------------------------
# 3) Bagimliliklar
# ---------------------------------------------------------------------------
if ($SkipDeps) {
    Write-Step 'Bagimlilik kurulumu atlandi (-SkipDeps)'
} else {
    Write-Step 'Bagimliliklar kuruluyor'
    Write-Host '    PySide6 buyuk bir pakettir; ilk kurulum birkac dakika surebilir.'

    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt') --progress-bar off
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Bagimliliklar kurulamadi. Internet baglantinizi kontrol edin.'
        exit 1
    }
    & $VenvPython -m pip install -e $ProjectRoot --no-deps --quiet
    Write-Ok 'Bagimliliklar kuruldu'
}

# ---------------------------------------------------------------------------
# 4) .env dosyasi
# ---------------------------------------------------------------------------
Write-Step 'Ortam dosyasi (.env) hazirlaniyor'

$envFile = Join-Path $ProjectRoot '.env'
$envExample = Join-Path $ProjectRoot '.env.example'

if (Test-Path $envFile) {
    Write-Ok '.env zaten mevcut - DOKUNULMADI'
} else {
    if (-not (Test-Path $envExample)) {
        Write-Err '.env.example bulunamadi.'
        exit 1
    }
    # Rastgele, kriptografik olarak guvenli bir oturum anahtari uret.
    $secret = & $VenvPython -c "import secrets; print(secrets.token_urlsafe(64))"
    $content = Get-Content $envExample -Raw -Encoding UTF8
    $content = $content -replace 'HOTEL_SECRET_KEY=.*', "HOTEL_SECRET_KEY=$secret"
    Set-Content -Path $envFile -Value $content -Encoding UTF8
    Write-Ok '.env olusturuldu ve rastgele HOTEL_SECRET_KEY yazildi'
    Write-Warn '.env dosyasi git tarafindan izlenmez; yedegini guvenli tutun.'
}

# ---------------------------------------------------------------------------
# 5) Veritabani goclerini uygula
# ---------------------------------------------------------------------------
Write-Step 'Veritabani goclerini uygulaniyor'

Push-Location $ProjectRoot
try {
    & (Join-Path $VenvPath 'Scripts\alembic.exe') upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Veritabani gocleri uygulanamadi.'
        Write-Host '    Ayrinti icin: .\.venv\Scripts\alembic.exe upgrade head'
        exit 1
    }
    Write-Ok 'Veritabani guncel'
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 6) Guvenlik kurulumu (izin / rol / yonetici)
# ---------------------------------------------------------------------------
Write-Step 'Izinler, roller ve yonetici hesabi kuruluyor'

Push-Location $ProjectRoot
try {
    & $VenvPython -m app.cli bootstrap
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Guvenlik kurulumu basarisiz.'
        exit 1
    }
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 7) Demo veri
# ---------------------------------------------------------------------------
if ($DemoData) {
    Write-Step 'Demo veri olusturuluyor'
    Write-Warn 'Demo veri tamamen hayalidir; gercek isletme verisi degildir.'
    Push-Location $ProjectRoot
    try {
        & $VenvPython -m app.cli seed-demo
        if ($LASTEXITCODE -ne 0) {
            Write-Err 'Demo veri olusturulamadi.'
            exit 1
        }
    } finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# Ozet
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '========================================================' -ForegroundColor Green
Write-Host '  KURULUM TAMAMLANDI' -ForegroundColor Green
Write-Host '========================================================' -ForegroundColor Green
Write-Host ''
Write-Host '  Uygulamayi baslatmak icin:' -ForegroundColor White
Write-Host '      .\scripts\run.ps1' -ForegroundColor Cyan
Write-Host ''
Write-Host '  Testleri calistirmak icin:' -ForegroundColor White
Write-Host '      .\scripts\test.ps1' -ForegroundColor Cyan
Write-Host ''
if (-not $DemoData) {
    Write-Host '  Demo veri eklemek icin:' -ForegroundColor White
    Write-Host '      .\scripts\setup.ps1 -DemoData' -ForegroundColor Cyan
    Write-Host ''
}
Write-Host '  Yapay zeka icin LM Studio kullanacaksaniz:' -ForegroundColor White
Write-Host '      LM Studio > Developer > Start Server (varsayilan port 1234)' -ForegroundColor Gray
Write-Host '      Ayrinti: docs\LM_STUDIO_SETUP.md' -ForegroundColor Gray
Write-Host ''
