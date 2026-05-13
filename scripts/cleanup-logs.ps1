<#
.SYNOPSIS
    EMSX Log Cleanup and Maintenance Script
    Cleans up log files across all subdirectories with independent retention policies.

.DESCRIPTION
    Manages log retention for four log categories under the logs/ directory:
    - api/       Backend API logs (emsx_api.log*)
    - service/   Service Manager logs (backend-*.log, frontend-*.log)
    - costview/  CostView pipeline logs (fillfetch.log*, backfill_raw_bdib.log)
    - backfill/  Manual backfill script logs (attribution_*.log, regime_*.log)
    - root/      Orphaned legacy files (startup-error.html)

.PARAMETER Force
    Actually delete files (default is dry-run mode).

.PARAMETER LogRoot
    Root log directory (default: EMSX project logs/).

.PARAMETER ApiMaxAgeDays
    Retention days for api/ logs (default: 3).

.PARAMETER ApiMaxFiles
    Max files to keep in api/ (default: 3).

.PARAMETER ServiceMaxAgeDays
    Retention days for service/ logs (default: 7).

.PARAMETER ServiceMaxFiles
    Max files to keep in service/ (default: 10).

.PARAMETER CostviewMaxAgeDays
    Retention days for costview/ logs (default: 30).

.PARAMETER CostviewMaxFiles
    Max files to keep in costview/ (default: 35).

.PARAMETER BackfillMaxAgeDays
    Retention days for backfill/ logs (default: 30).

.PARAMETER BackfillMaxFiles
    Max files to keep in backfill/ (default: 20).

.PARAMETER OrphanMaxAgeDays
    Retention days for orphaned root files (default: 7).

.EXAMPLE
    .\scripts\cleanup-logs.ps1
    Dry-run showing what would be deleted.

.EXAMPLE
    .\scripts\cleanup-logs.ps1 -Force
    Execute cleanup with default retention policies.

.EXAMPLE
    .\scripts\cleanup-logs.ps1 -Force -ServiceMaxAgeDays 14 -BackfillMaxAgeDays 60
    Execute with custom retention for service and backfill logs.
#>

param(
    [switch]$Force = $false,
    [string]$LogRoot = "C:\Users\hrchen\Documents\EMSX\logs",
    [int]$ApiMaxAgeDays = 3,
    [int]$ApiMaxFiles = 3,
    [int]$ServiceMaxAgeDays = 7,
    [int]$ServiceMaxFiles = 10,
    [int]$CostviewMaxAgeDays = 30,
    [int]$CostviewMaxFiles = 35,
    [int]$BackfillMaxAgeDays = 30,
    [int]$BackfillMaxFiles = 20,
    [int]$OrphanMaxAgeDays = 7
)

$ErrorActionPreference = "Stop"

Write-Host "=== EMSX Log Cleanup Script ===" -ForegroundColor Cyan
Write-Host "Log Root: $LogRoot"
Write-Host "Mode: $(if ($Force) { 'EXECUTE' } else { 'DRY-RUN (add -Force to execute)' })" -ForegroundColor $(if ($Force) { 'Red' } else { 'Yellow' })
Write-Host ""

if (-not (Test-Path $LogRoot)) {
    Write-Host "Log directory does not exist: $LogRoot" -ForegroundColor Red
    exit 1
}

$TotalSpaceFreed = 0
$TotalFilesDeleted = 0
$AllResults = @()

function Clear-LogSubdir {
    param(
        [string]$Label,
        [string]$Dir,
        [string]$Filter,
        [int]$MaxAgeDays,
        [int]$MaxFiles
    )

    $fullPath = Join-Path $LogRoot $Dir
    if (-not (Test-Path $fullPath)) {
        Write-Host "[$Label] Directory not found: $fullPath" -ForegroundColor Yellow
        return
    }

    $files = Get-ChildItem -Path $fullPath -Filter $Filter -File | Sort-Object LastWriteTime -Descending
    if ($files.Count -eq 0) {
        Write-Host "[$Label] No matching files found" -ForegroundColor Gray
        return
    }

    Write-Host "[$Label] Found $($files.Count) file(s)" -ForegroundColor Green
    $toDelete = @()
    $cutoff = (Get-Date).AddDays(-$MaxAgeDays)

    # 按年龄删除
    $ageBased = $files | Where-Object { $_.LastWriteTime -lt $cutoff }
    foreach ($f in $ageBased) { $toDelete += $f }

    # 超出数量限制删除最旧的
    $remaining = $files | Where-Object { $_ -notin $toDelete }
    if ($remaining.Count -gt $MaxFiles) {
        $excess = $remaining | Select-Object -Skip $MaxFiles
        foreach ($f in $excess) { $toDelete += $f }
    }

    if ($toDelete.Count -eq 0) {
        Write-Host "  Nothing to clean." -ForegroundColor Gray
        return
    }

    $space = ($toDelete | Measure-Object -Property Length -Sum).Sum
    Write-Host "  Queued: $($toDelete.Count) file(s), $('{0:N2}' -f ($space / 1MB)) MB" -ForegroundColor Yellow
    foreach ($f in $toDelete | Sort-Object LastWriteTime) {
        Write-Host "    $($f.Name) ($($f.LastWriteTime.ToString('yyyy-MM-dd HH:mm')), $('{0:N2}' -f ($f.Length / 1MB)) MB)" -ForegroundColor DarkYellow
    }

    if (-not $Force) { return }

    $deleted = 0
    $freed = 0
    foreach ($f in $toDelete) {
        try {
            Remove-Item $f.FullName -Force
            $deleted++
            $freed += $f.Length
        } catch {
            Write-Host "    ERROR: $($f.Name) - $_" -ForegroundColor Red
        }
    }

    Write-Host "  Deleted: $deleted file(s), $('{0:N2}' -f ($freed / 1MB)) MB" -ForegroundColor Green
    $script:TotalFilesDeleted += $deleted
    $script:TotalSpaceFreed += $freed
}

function Clear-OrphanedRoot {
    param([int]$MaxAgeDays)

    $cutoff = (Get-Date).AddDays(-$MaxAgeDays)

    $orphanFilters = @(
        "backend-startup*.log",
        "frontend-startup*.log",
        "backend-*.log",
        "frontend-*.log",
        "startup-error.html"
    )

    $files = @()
    foreach ($filter in $orphanFilters) {
        $files += Get-ChildItem -Path $LogRoot -Filter $filter -File
    }
    $files = $files | Where-Object { $_.LastWriteTime -lt $cutoff } | Sort-Object LastWriteTime -Descending

    if ($files.Count -eq 0) {
        Write-Host "[root] No orphaned files older than $MaxAgeDays days" -ForegroundColor Gray
        return
    }

    $space = ($files | Measure-Object -Property Length -Sum).Sum
    Write-Host "[root] Found $($files.Count) orphaned file(s), $('{0:N2}' -f ($space / 1MB)) MB" -ForegroundColor Yellow
    foreach ($f in $files) {
        Write-Host "    $($f.Name) ($($f.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))" -ForegroundColor DarkYellow
    }

    if (-not $Force) { return }

    $deleted = 0
    $freed = 0
    foreach ($f in $files) {
        try {
            Remove-Item $f.FullName -Force
            $deleted++
            $freed += $f.Length
        } catch {
            Write-Host "    ERROR: $($f.Name) - $_" -ForegroundColor Red
        }
    }

    Write-Host "  Deleted: $deleted file(s), $('{0:N2}' -f ($freed / 1MB)) MB" -ForegroundColor Green
    $script:TotalFilesDeleted += $deleted
    $script:TotalSpaceFreed += $freed
}

Write-Host "=== Retention Policies ===" -ForegroundColor Cyan
Write-Host "  api/       : max $ApiMaxAgeDays days, max $ApiMaxFiles files"
Write-Host "  service/   : max $ServiceMaxAgeDays days, max $ServiceMaxFiles files"
Write-Host "  costview/  : max $CostviewMaxAgeDays days, max $CostviewMaxFiles files"
Write-Host "  backfill/  : max $BackfillMaxAgeDays days, max $BackfillMaxFiles files"
Write-Host "  root/      : max $OrphanMaxAgeDays days (orphaned)"
Write-Host ""

Write-Host "=== Cleaning by Category ===" -ForegroundColor Cyan
Clear-LogSubdir -Label "api"       -Dir "api"      -Filter "emsx_api.log*"         -MaxAgeDays $ApiMaxAgeDays       -MaxFiles $ApiMaxFiles
Clear-LogSubdir -Label "service"   -Dir "service"  -Filter "*.log"                -MaxAgeDays $ServiceMaxAgeDays   -MaxFiles $ServiceMaxFiles
Clear-LogSubdir -Label "costview"  -Dir "costview" -Filter "*.log*"               -MaxAgeDays $CostviewMaxAgeDays  -MaxFiles $CostviewMaxFiles
Clear-LogSubdir -Label "backfill"  -Dir "backfill" -Filter "*.log"                -MaxAgeDays $BackfillMaxAgeDays  -MaxFiles $BackfillMaxFiles
Clear-OrphanedRoot -MaxAgeDays $OrphanMaxAgeDays

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
if ($Force) {
    Write-Host "Cleaned: $TotalFilesDeleted file(s), $('{0:N2}' -f ($TotalSpaceFreed / 1MB)) MB freed" -ForegroundColor Green
} else {
    Write-Host "Dry-run complete. Add -Force to execute cleanup." -ForegroundColor Yellow
}

# Show remaining
Write-Host ""
Write-Host "=== Remaining Logs ===" -ForegroundColor Cyan
Get-ChildItem $LogRoot -Recurse -File | Where-Object { $_.Name -ne ".gitkeep" } | Sort-Object DirectoryName | ForEach-Object {
    $rel = $_.DirectoryName.Substring($LogRoot.Length).TrimStart('\')
    $label = if ($rel) { "$rel/$($_.Name)" } else { $_.Name }
    Write-Host "  $label ($('{0:N2}' -f ($_.Length / 1MB)) MB, $($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))" -ForegroundColor Gray
}
