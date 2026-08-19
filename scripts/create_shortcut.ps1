<#
.SYNOPSIS
    Masaustune ve Baslat menusune kisayol olusturur.

.DESCRIPTION
    Iki kip destekler:

    1. **Paketlenmis kip** (varsayilan): dist\ altindaki .exe dosyasina
       kisayol olusturur. Once .\scripts\build.ps1 calistirilmalidir.
    2. **Gelistirme kipi** (-Dev): sanal ortamdaki pythonw.exe ile
       uygulamayi baslatan kisayol olusturur. Paketleme gerektirmez.

    pythonw.exe kullanilmasinin nedeni: python.exe bir konsol penceresi
    acar ve masaustu uygulamasinin arkasinda siyah bir pencere kalir.

.PARAMETER Dev
    Paketlenmis .exe yerine sanal ortamdan calistiran kisayol olusturur.

.PARAMETER StartMenu
    Masaustune ek olarak Baslat menusune de ekler.

.PARAMETER Remove
    Olusturulan kisayollari siler.

.EXAMPLE
    .\scripts\create_shortcut.ps1

.EXAMPLE
    .\scripts\create_shortcut.ps1 -Dev -StartMenu
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$StartMenu,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ShortcutName = 'Akilli Konaklama Yonetimi'
$DesktopPath = [Environment]::GetFolderPath('Desktop')
$StartMenuPath = Join-Path ([Environment]::GetFolderPath('Programs')) 'Akilli Konaklama'

function Write-Ok    { param([string]$m) Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn  { param([string]$m) Write-Host "    [!] $m"  -ForegroundColor Yellow }
function Write-Err   { param([string]$m) Write-Host "[HATA] $m"   -ForegroundColor Red }

# ---------------------------------------------------------------------------
#  Silme
# ---------------------------------------------------------------------------
if ($Remove) {
    Write-Host ''
    Write-Host '==> Kisayollar siliniyor' -ForegroundColor Cyan

    $removed = 0
    $desktopLink = Join-Path $DesktopPath "$ShortcutName.lnk"
    if (Test-Path $desktopLink) {
        Remove-Item $desktopLink -Force
        Write-Ok "Masaustu kisayolu silindi"
        $removed++
    }
    if (Test-Path $StartMenuPath) {
        Remove-Item $StartMenuPath -Recurse -Force
        Write-Ok "Baslat menusu klasoru silindi"
        $removed++
    }
    if ($removed -eq 0) { Write-Warn 'Silinecek kisayol bulunamadi.' }
    exit 0
}

# ---------------------------------------------------------------------------
#  Hedefi belirle
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '========================================================' -ForegroundColor White
Write-Host '  Kisayol olusturuluyor' -ForegroundColor White
Write-Host '========================================================' -ForegroundColor White

if ($Dev) {
    $targetPath = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
    $arguments = '-m app.main'
    $workingDir = $ProjectRoot

    if (-not (Test-Path $targetPath)) {
        Write-Err 'Sanal ortam bulunamadi.'
        Write-Host 'Once kurulumu calistirin: .\scripts\setup.ps1' -ForegroundColor Yellow
        exit 1
    }
    Write-Host '  Kip: gelistirme (sanal ortamdan calisir)' -ForegroundColor Gray
} else {
    # dist\ altinda .exe ara
    $exe = Get-ChildItem -Path (Join-Path $ProjectRoot 'dist') -Filter '*.exe' -Recurse -ErrorAction SilentlyContinue |
           Sort-Object Length -Descending |
           Select-Object -First 1

    if (-not $exe) {
        Write-Err 'dist\ klasorunde .exe bulunamadi.'
        Write-Host ''
        Write-Host 'Secenekler:' -ForegroundColor Yellow
        Write-Host '  1) Once paketleyin:   .\scripts\build.ps1' -ForegroundColor Cyan
        Write-Host '  2) Gelistirme kipi:   .\scripts\create_shortcut.ps1 -Dev' -ForegroundColor Cyan
        exit 1
    }

    $targetPath = $exe.FullName
    $arguments = ''
    $workingDir = $exe.DirectoryName
    Write-Host "  Kip: paketlenmis (.exe)" -ForegroundColor Gray
}

Write-Host "  Hedef: $targetPath" -ForegroundColor Gray

# Simge: paketlenmis .exe kendi simgesini tasir; gelistirme kipinde
# pythonw.exe'nin simgesi yerine uygulamanin kendi simgesi kullanilir.
$iconPath = Join-Path $ProjectRoot 'app\ui\resources\icons\app.ico'
$useIcon = Test-Path $iconPath

# ---------------------------------------------------------------------------
#  Kisayolu olustur
# ---------------------------------------------------------------------------
function New-AppShortcut {
    param([string]$LinkPath)

    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($LinkPath)
        $shortcut.TargetPath = $targetPath
        if ($arguments) { $shortcut.Arguments = $arguments }
        $shortcut.WorkingDirectory = $workingDir
        $shortcut.Description = 'Akilli Konaklama Yonetim Sistemi'
        $shortcut.WindowStyle = 1
        if ($useIcon) { $shortcut.IconLocation = "$iconPath,0" }
        $shortcut.Save()
    } finally {
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
    }
}

Write-Host ''
Write-Host '==> Masaustu' -ForegroundColor Cyan
$desktopLink = Join-Path $DesktopPath "$ShortcutName.lnk"
New-AppShortcut -LinkPath $desktopLink
Write-Ok $desktopLink

if ($StartMenu) {
    Write-Host ''
    Write-Host '==> Baslat menusu' -ForegroundColor Cyan
    if (-not (Test-Path $StartMenuPath)) {
        New-Item -ItemType Directory -Path $StartMenuPath -Force | Out-Null
    }
    $startLink = Join-Path $StartMenuPath "$ShortcutName.lnk"
    New-AppShortcut -LinkPath $startLink
    Write-Ok $startLink
}

if (-not $useIcon) {
    Write-Host ''
    Write-Warn 'Uygulama simgesi bulunamadi; varsayilan simge kullanildi.'
    Write-Host '    Simgeyi uretmek icin:' -ForegroundColor Gray
    Write-Host '        .\.venv\Scripts\python.exe packaging\make_icon.py' -ForegroundColor Cyan
}

Write-Host ''
Write-Host '  Kisayol hazir. Masaustunden calistirabilirsiniz.' -ForegroundColor Green
Write-Host '  Kaldirmak icin: .\scripts\create_shortcut.ps1 -Remove' -ForegroundColor Gray
Write-Host ''
