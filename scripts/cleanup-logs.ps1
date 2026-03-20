# EMSX Log Cleanup and Maintenance Script
# Run this script periodically (e.g., daily via Task Scheduler) to maintain log hygiene
#
# Usage: .\scripts\cleanup-logs.ps1 [-Force]
# Use -Force to actually delete files (default is dry-run mode)

param(
    [switch]$Force = $false,
    [int]$MaxAgeDays = 3,
    [int]$MaxFiles = 3,
    [string]$LogDir = "C:\Users\hrchen\Documents\EMSX\logs"
)

$ErrorActionPreference = "Stop"

Write-Host "=== EMSX Log Cleanup Script ===" -ForegroundColor Cyan
Write-Host "Log Directory: $LogDir"
Write-Host "Max Age: $MaxAgeDays days"
Write-Host "Max Files: $MaxFiles"
Write-Host "Mode: $(if ($Force) { 'EXECUTE' } else { 'DRY-RUN (add -Force to execute)' })" -ForegroundColor $(if ($Force) { 'Red' } else { 'Yellow' })
Write-Host ""

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
    Write-Host "Log directory does not exist: $LogDir" -ForegroundColor Red
    exit 1
}

# Get all log files
$AllLogFiles = Get-ChildItem -Path $LogDir -Filter "emsx_api.log*" -File | Sort-Object LastWriteTime -Descending

if ($AllLogFiles.Count -eq 0) {
    Write-Host "No log files found in $LogDir" -ForegroundColor Yellow
    exit 0
}

Write-Host "Found $($AllLogFiles.Count) log files:" -ForegroundColor Green
$AllLogFiles | ForEach-Object { 
    $SizeMB = [math]::Round($_.Length / 1MB, 2)
    Write-Host "  - $($_.Name) ($SizeMB MB, $($_.LastWriteTime))" 
}
Write-Host ""

$FilesToDelete = @()
$CutoffDate = (Get-Date).AddDays(-$MaxAgeDays)

# Identify files to delete (older than max age)
$AgeBasedDeletes = $AllLogFiles | Where-Object { $_.LastWriteTime -lt $CutoffDate }
if ($AgeBasedDeletes) {
    Write-Host "Files older than $MaxAgeDays days (will be deleted):" -ForegroundColor Yellow
    $AgeBasedDeletes | ForEach-Object { 
        Write-Host "  - $($_.Name) ($($_.LastWriteTime))" 
        $FilesToDelete += $_
    }
    Write-Host ""
}

# Identify excess files (beyond max count)
$CurrentFiles = $AllLogFiles | Where-Object { $_ -notin $FilesToDelete }
if ($CurrentFiles.Count -gt $MaxFiles) {
    $ExcessFiles = $CurrentFiles | Select-Object -Skip $MaxFiles
    Write-Host "Excess files beyond limit of $MaxFiles (will be deleted):" -ForegroundColor Yellow
    $ExcessFiles | ForEach-Object { 
        Write-Host "  - $($_.Name)" 
        $FilesToDelete += $_
    }
    Write-Host ""
}

# Calculate space to be freed
$SpaceToFree = ($FilesToDelete | Measure-Object -Property Length -Sum).Sum
$SpaceToFreeMB = [math]::Round($SpaceToFree / 1MB, 2)

if ($FilesToDelete.Count -eq 0) {
    Write-Host "No files need to be deleted. Log directory is clean." -ForegroundColor Green
    exit 0
}

Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  Files to delete: $($FilesToDelete.Count)"
Write-Host "  Space to free: $SpaceToFreeMB MB"
Write-Host ""

if (-not $Force) {
    Write-Host "This is a dry run. No files were deleted." -ForegroundColor Yellow
    Write-Host "Run with -Force to execute cleanup." -ForegroundColor Yellow
    exit 0
}

# Execute deletion
Write-Host "Executing cleanup..." -ForegroundColor Red
$DeletedCount = 0
foreach ($File in $FilesToDelete) {
    try {
        Remove-Item $File.FullName -Force
        Write-Host "  Deleted: $($File.Name)" -ForegroundColor Green
        $DeletedCount++
    }
    catch {
        Write-Host "  ERROR deleting $($File.Name): $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Cleanup complete. Deleted $DeletedCount files, freed $SpaceToFreeMB MB." -ForegroundColor Green

# Show remaining files
$RemainingFiles = Get-ChildItem -Path $LogDir -Filter "emsx_api.log*" -File | Sort-Object LastWriteTime -Descending
$RemainingSize = ($RemainingFiles | Measure-Object -Property Length -Sum).Sum
$RemainingSizeMB = [math]::Round($RemainingSize / 1MB, 2)
Write-Host "Remaining: $($RemainingFiles.Count) files, $RemainingSizeMB MB"
