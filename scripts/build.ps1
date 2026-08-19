<#
.SYNOPSIS
    Windows calistirilabilir dosyasi (.exe) uretir.

.DESCRIPTION
    PyInstaller ile dist\ altina paket olusturur.

    Varsayilan olarak "onedir" kipi kullanilir (tek klasor). Nedeni: "onefile"
    kipi her calistirmada gecici klasore acilir; bu hem baslangici yavaslatir
    hem de bazi kurumsal antiviruslerin uygulamayi karantinaya almasina yol
    acar. Tek dosya isteniyorsa -OneFile kullanin.

    Yazilabilir veriler (veritabani, log, yedek) .exe'nin YANINDA tutulur;
    boylece uygulama tasinabilir kalir (bkz. app/core/paths.py).

.PARAMETER OneFile
    Tek dosyalik .exe uretir (yavas baslangic, antivirus riski).

.PARAMETER Clean
    Onceki build ve dist ciktilarini siler.

.PARAMETER SkipTests
    Paketleme oncesi test calistirmaz. ONERILMEZ.

.EXAMPLE
    .\scripts\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$OneFile,
    [switch]$Clean,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvScripts = Join-Path $ProjectRoot '.venv\Scripts'
$VenvPython = Join-Path $VenvScripts 'python.exe'
$DistPath = Join-Path $ProjectRoot 'dist'
$BuildPath = Join-Path $ProjectRoot 'build'

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

if (-not (Test-Path $VenvPython)) {
    Write-Host '[HATA] Sanal ortam yok. Once: .\scripts\setup.ps1' -ForegroundColor Red
    exit 1
}

Push-Location $ProjectRoot
try {
    # --- Testler ---
    if (-not $SkipTests) {
        Write-Step 'Testler calistiriliyor (paketleme oncesi kontrol)'
        & $VenvPython -m pytest -q --no-header -m 'not live'
        if ($LASTEXITCODE -ne 0) {
            Write-Host ''
            Write-Host '[HATA] Testler basarisiz. Paketleme durduruldu.' -ForegroundColor Red
            Write-Host 'Yine de paketlemek icin: .\scripts\build.ps1 -SkipTests' -ForegroundColor Yellow
            exit 1
        }
        Write-Host '    [OK] Testler gecti' -ForegroundColor Green
    }

    # --- Temizlik ---
    if ($Clean) {
        Write-Step 'Onceki ciktilar temizleniyor'
        foreach ($path in @($DistPath, $BuildPath)) {
            if (Test-Path $path) {
                Remove-Item -Recurse -Force $path
                Write-Host "    Silindi: $path" -ForegroundColor Gray
            }
        }
    }

    # --- PyInstaller ---
    Write-Step 'PyInstaller calistiriliyor'
    Write-Host '    Bu islem birkac dakika surebilir.' -ForegroundColor Gray

    $specFile = Join-Path $ProjectRoot 'packaging\hotel.spec'
    if (-not (Test-Path $specFile)) {
        Write-Host "[HATA] Spec dosyasi bulunamadi: $specFile" -ForegroundColor Red
        exit 1
    }

    if ($OneFile) {
        $env:HOTEL_BUILD_ONEFILE = '1'
        Write-Host '    Kip: tek dosya (onefile)' -ForegroundColor Gray
    } else {
        $env:HOTEL_BUILD_ONEFILE = '0'
        Write-Host '    Kip: klasor (onedir)' -ForegroundColor Gray
    }

    & (Join-Path $VenvScripts 'pyinstaller.exe') $specFile --noconfirm --distpath $DistPath --workpath $BuildPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[HATA] Paketleme basarisiz.' -ForegroundColor Red
        exit 1
    }
} finally {
    Remove-Item Env:\HOTEL_BUILD_ONEFILE -ErrorAction SilentlyContinue
    Pop-Location
}

# --- Lisans dogrulamasi (uretilen ciktinin uzerinde) ---
#
# Yayin oncesi denetim bulgusu HTL-H4: spec dosyasindaki 'datas' listesine
# guvenmek yeterli degildir - bir dosya adi degisirse ya da PyInstaller bir
# girdiyi sessizce atlarsa hata fark edilmez. Bu yuzden URETILEN cikti
# uzerinde ayrica dogrulanir.
Write-Step 'Lisans dosyalari cikti icinde dogrulaniyor'

$requiredInDist = @(
    'LICENSE',
    'THIRD_PARTY_NOTICES.md',
    'GPL-3.0.txt',
    'LGPL-3.0.txt'
)

$distFiles = Get-ChildItem -Path $DistPath -Recurse -File -ErrorAction SilentlyContinue
$missingInDist = @()
foreach ($rel in $requiredInDist) {
    $found = $distFiles | Where-Object { $_.Name -eq $rel } | Select-Object -First 1
    if (-not $found) { $missingInDist += $rel }
}

if ($missingInDist.Count -gt 0) {
    Write-Host ''
    Write-Host '[HATA] Uretilen paket zorunlu lisans dosyalarini icermiyor:' -ForegroundColor Red
    foreach ($m in $missingInDist) { Write-Host "    - $m" -ForegroundColor Red }
    Write-Host ''
    Write-Host '  Bu bir dagitim YUKUMLULUGUDUR (MIT telif bildirimi + Qt/PySide6' -ForegroundColor Yellow
    Write-Host '  icin LGPL-3.0 metni). Ayrinti: packaging\licenses\README.md' -ForegroundColor Yellow
    exit 1
}
Write-Host '    [OK] Lisans dosyalari pakette' -ForegroundColor Green

# --- Ozet ---
Write-Host ''
Write-Host '========================================================' -ForegroundColor Green
Write-Host '  PAKETLEME TAMAMLANDI' -ForegroundColor Green
Write-Host '========================================================' -ForegroundColor Green
Write-Host ''
Write-Host "  Cikti klasoru: $DistPath" -ForegroundColor White

$exe = Get-ChildItem -Path $DistPath -Filter '*.exe' -Recurse -ErrorAction SilentlyContinue |
       Select-Object -First 1
if ($exe) {
    $sizeMb = [math]::Round($exe.Length / 1MB, 1)
    Write-Host "  Calistirilabilir: $($exe.FullName)" -ForegroundColor Cyan
    Write-Host "  Boyut: $sizeMb MB" -ForegroundColor Gray
}
Write-Host ''
Write-Host '  NOT: Veritabani ve loglar .exe ile ayni klasorde tutulur.' -ForegroundColor Yellow
Write-Host '  Uygulamayi tasirken bu klasorun tamamini kopyalayin.' -ForegroundColor Yellow
Write-Host ''
