param(
    [string]$BaseUrl = 'http://localhost:3000',
    [string]$Username = 'trader1',
    [string]$Password = 'password',
    [int]$TimeoutSec = 5,
    [int]$MaxWaitSeconds = 0,
    [int]$PollIntervalSeconds = 2,
    [switch]$RequireReady,
    [switch]$JsonOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-JsonRequest {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [object]$Body = $null
    )

    $requestParams = @{
        Method = $Method
        Uri = $Uri
        TimeoutSec = $TimeoutSec
        Headers = $Headers
        UseBasicParsing = $true
    }

    if ($null -ne $Body) {
        $requestParams['ContentType'] = 'application/json'
        $requestParams['Body'] = ($Body | ConvertTo-Json -Depth 6)
    }

    $response = Invoke-WebRequest @requestParams
    if ([string]::IsNullOrWhiteSpace($response.Content)) {
        return $null
    }

    return $response.Content | ConvertFrom-Json
}

function Get-StartupStatus {
    param([hashtable]$Headers)

    return Invoke-JsonRequest -Method 'GET' -Uri "$BaseUrl/api/startup-status" -Headers $Headers
}

function Get-AuthHeaders {
    try {
        return @{ Authorization = 'Bearer smoke-check' }
    }
    catch {
        return @{}
    }
}

function Try-LoginHeaders {
    $loginResponse = Invoke-JsonRequest -Method 'POST' -Uri "$BaseUrl/api/auth/login" -Headers @{} -Body @{
        username = $Username
        password = $Password
    }

    if (-not $loginResponse.success -or -not $loginResponse.data.token) {
        throw "Login failed: $($loginResponse | ConvertTo-Json -Depth 6)"
    }

    return @{ Authorization = "Bearer $($loginResponse.data.token)" }
}

function Resolve-Headers {
    try {
        $headers = Get-AuthHeaders
        $null = Get-StartupStatus -Headers $headers
        return $headers
    }
    catch {
        return Try-LoginHeaders
    }
}

function New-StartupSummary {
    param(
        [object]$HealthResponse,
        [object]$StartupResponse
    )

    $data = $StartupResponse.data
    return [pscustomobject]@{
        baseUrl = $BaseUrl
        httpReady = $true
        healthSuccess = [bool]($null -ne $HealthResponse -and $HealthResponse.success -eq $true)
        healthMessage = if ($null -ne $HealthResponse) { $HealthResponse.message } else { $null }
        phase = $data.phase
        ready = [bool]$data.ready
        message = $StartupResponse.message
        bloombergStatus = $data.bloomberg.status
        subscriptionsReady = [bool]$data.subscriptions.ready
        ordersInitPaintDone = [bool]$data.subscriptions.ordersInitPaintDone
        routesInitPaintDone = [bool]$data.subscriptions.routesInitPaintDone
        orderCount = [int]$data.subscriptions.orderCount
        routeCount = [int]$data.subscriptions.routeCount
        backend = $data.backend
        bloomberg = $data.bloomberg
        subscriptions = $data.subscriptions
    }
}

function Write-StartupSummary {
    param([object]$Summary)

    if ($JsonOutput) {
        $Summary | ConvertTo-Json -Depth 8
        return
    }

    Write-Host "phase=$($Summary.phase) ready=$($Summary.ready) httpReady=$($Summary.httpReady) bloomberg=$($Summary.bloombergStatus) ordersInit=$($Summary.ordersInitPaintDone) routesInit=$($Summary.routesInitPaintDone) orders=$($Summary.orderCount) routes=$($Summary.routeCount)" -ForegroundColor Cyan
    if ($Summary.message) {
        Write-Host $Summary.message -ForegroundColor DarkGray
    }
}

$healthResponse = $null
try {
    $healthResponse = Invoke-JsonRequest -Method 'GET' -Uri "$BaseUrl/api/health" -Headers @{}
}
catch {
    Write-Error "Backend health endpoint is not reachable: $($_.Exception.Message)"
    exit 1
}

if ($null -eq $healthResponse) {
    Write-Error 'Backend /api/health returned an empty response.'
    exit 1
}

$headers = Resolve-Headers
$deadline = if ($MaxWaitSeconds -gt 0) { (Get-Date).AddSeconds($MaxWaitSeconds) } else { $null }

while ($true) {
    try {
        $startupResponse = Get-StartupStatus -Headers $headers
        if (-not $startupResponse.success) {
            throw "startup-status returned success=false: $($startupResponse | ConvertTo-Json -Depth 6)"
        }

        $summary = New-StartupSummary -HealthResponse $healthResponse -StartupResponse $startupResponse
        Write-StartupSummary -Summary $summary

        if (-not $RequireReady -or $summary.ready) {
            exit 0
        }

        if ($deadline -and (Get-Date) -ge $deadline) {
            Write-Error "startup-status did not reach ready within $MaxWaitSeconds seconds."
            exit 2
        }

        Start-Sleep -Seconds $PollIntervalSeconds
    }
    catch {
        Write-Error "startup-status check failed: $($_.Exception.Message)"
        exit 1
    }
}