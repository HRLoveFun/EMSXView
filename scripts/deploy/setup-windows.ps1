# EMSXView Trading Platform - Windows Setup Script
# Run as Administrator (right-click -> Run as Administrator)
# Or: Start-Process powershell -Verb RunAs -ArgumentList "-File .\scripts\setup-windows.ps1"

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  EMSXView Trading Platform - Windows Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Check if running as administrator
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "Please run this script as Administrator!" -ForegroundColor Red
    exit 1
}

# Get project directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir

# Check Docker Desktop
Write-Host "`nChecking Docker Desktop..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version
    Write-Host "OK Docker: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "FAIL Docker not found. Install from https://www.docker.com/products/docker-desktop" -ForegroundColor Red
    exit 1
}

# Support docker compose v2 or docker-compose v1
$composeCmd = $null
try {
    docker compose version | Out-Null
    $composeCmd = "docker compose"
    Write-Host "OK Docker Compose v2 (docker compose)" -ForegroundColor Green
} catch {
    try {
        docker-compose --version | Out-Null
        $composeCmd = "docker-compose"
        Write-Host "OK Docker Compose v1 (docker-compose)" -ForegroundColor Green
    } catch {
        Write-Host "FAIL Docker Compose not found" -ForegroundColor Red
        exit 1
    }
}

# Create logs directory
Write-Host "`nCreating directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "$projectDir\logs" | Out-Null
Write-Host "OK directories created" -ForegroundColor Green

# Check/create .env file
$envFile = "$projectDir\.env"
$envExample = "$projectDir\.env.example"

if (-NOT (Test-Path $envFile)) {
    Write-Host "`nCreating .env from template..." -ForegroundColor Yellow
    if (-NOT (Test-Path $envExample)) {
        Write-Host "FAIL .env.example not found at $envExample" -ForegroundColor Red
        exit 1
    }
    Copy-Item $envExample $envFile
    Write-Host "OK .env created - PLEASE EDIT $envFile before continuing!" -ForegroundColor Yellow
    Write-Host "   Especially set JWT_SECRET to a long random string." -ForegroundColor Yellow
    Write-Host "   Then re-run this script." -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "OK .env already exists" -ForegroundColor Green
}

# Warn if JWT_SECRET is still default
$jwtLine = (Get-Content $envFile | Select-String "^JWT_SECRET=").ToString()
if ($jwtLine -like "*change-this*" -or $jwtLine -like "*your-super-secret*") {
    Write-Host "WARN JWT_SECRET looks like the default value - change it in .env!" -ForegroundColor Yellow
}

# Check Bloomberg connection
Write-Host "`nChecking Bloomberg Terminal connection..." -ForegroundColor Yellow
$envContent = Get-Content $envFile
$bloombergHostLine = $envContent | Select-String "^BLOOMBERG_HOST="
$bloombergPortLine  = $envContent | Select-String "^BLOOMBERG_PORT="

$bloombergHost = if ($bloombergHostLine) { $bloombergHostLine.ToString().Split("=",2)[1].Trim() } else { "host.docker.internal" }
$bloombergPort = if ($bloombergPortLine)  { [int]$bloombergPortLine.ToString().Split("=",2)[1].Trim() } else { 8194 }

Write-Host "Bloomberg Host: $bloombergHost" -ForegroundColor Cyan
Write-Host "Bloomberg Port: $bloombergPort" -ForegroundColor Cyan

# host.docker.internal resolves to 127.0.0.1 for the test
$testHost = if ($bloombergHost -eq "host.docker.internal") { "127.0.0.1" } else { $bloombergHost }
$connectionTest = Test-NetConnection -ComputerName $testHost -Port $bloombergPort -WarningAction SilentlyContinue

if ($connectionTest.TcpTestSucceeded) {
    Write-Host "OK Bloomberg Terminal is reachable" -ForegroundColor Green
} else {
    Write-Host "WARN Cannot reach Bloomberg on $bloombergHost`:$bloombergPort" -ForegroundColor Yellow
    Write-Host "     Ensure Bloomberg Terminal is running, logged in, and API is enabled (API<GO>)." -ForegroundColor Yellow
    Write-Host "     Continuing with build anyway..." -ForegroundColor Yellow
}

# Build Docker images
Write-Host "`nBuilding Docker images (may take a few minutes on first run)..." -ForegroundColor Yellow
Set-Location $projectDir
Invoke-Expression "$composeCmd build"

if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL Docker build failed" -ForegroundColor Red
    exit 1
}
Write-Host "OK Docker images built" -ForegroundColor Green

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "`nStart the platform:" -ForegroundColor Cyan
Write-Host "  $composeCmd up -d" -ForegroundColor White
Write-Host "`nAccess URLs:" -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost" -ForegroundColor White
Write-Host "  API docs: http://localhost/api/docs" -ForegroundColor White
Write-Host "  Health:   http://localhost/api/health" -ForegroundColor White
Write-Host "`nDefault credentials (change ASAP):" -ForegroundColor Yellow
Write-Host "  trader1 / password" -ForegroundColor White
Write-Host "  admin   / password" -ForegroundColor White
