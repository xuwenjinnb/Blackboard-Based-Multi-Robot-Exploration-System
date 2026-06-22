param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8000,
    [double]$BroadcastIntervalSeconds = 0.3,
    [string]$RedisUrl = $env:REDIS_URL,
    [string]$RedisPrefix = $env:REDIS_PREFIX,
    [string]$NodeId = "computer-a"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

function Test-VenvPython {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        return $false
    }
    & $VenvPython -c "import sys; print(sys.executable)" *> $null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-VenvPython)) {
    throw "The Python virtual environment is missing or broken. Recreate backend\.venv first."
}

if ([string]::IsNullOrWhiteSpace($RedisUrl)) {
    $RedisUrl = "redis://127.0.0.1:6379/0"
}

if ([string]::IsNullOrWhiteSpace($RedisPrefix)) {
    $RedisPrefix = "inspection"
}

$env:PYTHONUNBUFFERED = "1"
$env:DEPLOYMENT_ROLE = "api"
$env:RUN_EMBEDDED_SIMULATION = "false"
$env:NODE_ID = $NodeId
$env:REDIS_URL = $RedisUrl
$env:REDIS_PREFIX = $RedisPrefix
$env:BROADCAST_INTERVAL_SECONDS = [string]$BroadcastIntervalSeconds

Write-Host "Checking Redis: $RedisUrl" -ForegroundColor Cyan
& $VenvPython -c "import os, redis; client = redis.Redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=5); assert client.ping(); print('Redis connection OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Cannot connect to Redis at $RedisUrl"
}

Write-Host "Starting distributed API node..." -ForegroundColor Cyan
Write-Host "URL: http://127.0.0.1:$Port/pathfinding"
Write-Host "Embedded simulation is disabled."

& $VenvPython -m uvicorn app.main:app --host $HostAddress --port $Port
