param(
    [string]$NavigatorIds = "",
    [string]$ComponentId = "",
    [double]$WorkerIntervalSeconds = 0.15,
    [int]$BatchesPerTick = 3,
    [string]$RedisUrl = $env:REDIS_URL,
    [string]$RedisPrefix = $env:REDIS_PREFIX
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ScriptDir "backend"
Set-Location $BackendDir

$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    python -m venv .venv
}

if ([string]::IsNullOrWhiteSpace($RedisUrl)) {
    $RedisUrl = "redis://127.0.0.1:6379/0"
}

if ([string]::IsNullOrWhiteSpace($RedisPrefix)) {
    $RedisPrefix = "inspection"
}

$env:PYTHONUNBUFFERED = "1"
$env:REDIS_URL = $RedisUrl
$env:REDIS_PREFIX = $RedisPrefix
$env:WORKER_INTERVAL_SECONDS = [string]$WorkerIntervalSeconds
$env:NAVIGATOR_BATCHES_PER_TICK = [string]$BatchesPerTick

if (-not [string]::IsNullOrWhiteSpace($NavigatorIds)) {
    $env:NAVIGATOR_IDS = $NavigatorIds
    Remove-Item Env:COMPONENT_ID -ErrorAction SilentlyContinue
} elseif (-not [string]::IsNullOrWhiteSpace($ComponentId)) {
    $env:COMPONENT_ID = $ComponentId
    Remove-Item Env:NAVIGATOR_IDS -ErrorAction SilentlyContinue
} else {
    Remove-Item Env:COMPONENT_ID -ErrorAction SilentlyContinue
    Remove-Item Env:NAVIGATOR_IDS -ErrorAction SilentlyContinue
}

& $VenvPython -m pip install -r requirements.txt
& $VenvPython -u -m app.workers.navigator_worker
