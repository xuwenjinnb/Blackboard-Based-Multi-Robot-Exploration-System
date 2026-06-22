param(
    [string]$ComponentId = "controller-01",
    [double]$WorkerIntervalSeconds = 0.3,
    [bool]$ControllerSingleton = $true,
    [int]$ControllerLockTtlSeconds = 10,
    [string]$RedisUrl = $env:REDIS_URL,
    [string]$RedisPrefix = $env:REDIS_PREFIX
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

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
$env:COMPONENT_ID = $ComponentId
$env:WORKER_INTERVAL_SECONDS = [string]$WorkerIntervalSeconds
$env:CONTROLLER_SINGLETON = [string]$ControllerSingleton
$env:CONTROLLER_LOCK_TTL_SECONDS = [string]$ControllerLockTtlSeconds

& $VenvPython -m pip install -r requirements.txt
& $VenvPython -u -m app.workers.controller_worker
