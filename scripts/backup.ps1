<#
.SYNOPSIS
    Veritabani yedegi alir ve eski yedekleri temizler.

.DESCRIPTION
    SQLite icin dosya kopyalamak yerine `VACUUM INTO` kullanilir. Nedeni:
    uygulama calisirken WAL kipinde dosyayi kopyalamak, henuz ana dosyaya
    yazilmamis islemleri kacirabilir ve TUTARSIZ bir yedek uretir.
    `VACUUM INTO` ise tutarli bir anlik goruntu yazar.

    PostgreSQL kullaniyorsaniz bu betik uyarir ve pg_dump onerir.

    Yedekler HOTEL_BACKUP_DIR (varsayilan: backups\) altina
    hotel_YYYYMMDD_HHMMSS.db adiyla yazilir.

.PARAMETER Keep
    Saklanacak yedek sayisi. Varsayilan .env icindeki HOTEL_BACKUP_RETENTION
    veya 14.

.PARAMETER Restore
    Geri yuklenecek yedek dosyasinin yolu. ONAY ISTER.

.PARAMETER Force
    Geri yuklemede onay sormaz. DIKKATLI KULLANIN.

.EXAMPLE
    .\scripts\backup.ps1

.EXAMPLE
    .\scripts\backup.ps1 -Restore backups\hotel_20260815_143000.db
#>
[CmdletBinding()]
param(
    [int]$Keep = 0,
    [string]$Restore = '',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host '[HATA] Sanal ortam yok. Once: .\scripts\setup.ps1' -ForegroundColor Red
    exit 1
}

Push-Location $ProjectRoot
try {
    if ($Restore) {
        # -------------------- GERI YUKLEME --------------------
        if (-not (Test-Path $Restore)) {
            Write-Host "[HATA] Yedek dosyasi bulunamadi: $Restore" -ForegroundColor Red
            exit 1
        }

        Write-Host ''
        Write-Host '  DIKKAT: GERI YUKLEME' -ForegroundColor Yellow
        Write-Host '  Mevcut veritabaninin UZERINE YAZILACAK.' -ForegroundColor Yellow
        Write-Host "  Kaynak: $Restore" -ForegroundColor Gray
        Write-Host ''

        if (-not $Force) {
            $answer = Read-Host '  Devam etmek icin "EVET" yazin'
            if ($answer -ne 'EVET') {
                Write-Host '  Iptal edildi.' -ForegroundColor Gray
                exit 0
            }
        }

        & $VenvPython -m app.cli restore --source $Restore --confirm
        exit $LASTEXITCODE
    }

    # -------------------- YEDEK ALMA --------------------
    $args = @('-m', 'app.cli', 'backup')
    if ($Keep -gt 0) {
        $args += @('--keep', "$Keep")
    }
    & $VenvPython @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
