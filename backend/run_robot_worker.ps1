param(
    [string]$VehicleId = $env:VEHICLE_ID,
    [double]$WorkerIntervalSeconds = 0.3,
    [int]$StepsPerTick = 1,
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
$env:WORKER_INTERVAL_SECONDS = [string]$WorkerIntervalSeconds
$env:ROBOT_STEPS_PER_TICK = [string]$StepsPerTick
if ([string]::IsNullOrWhiteSpace($VehicleId)) {
    Remove-Item Env:VEHICLE_ID -ErrorAction SilentlyContinue
} else {
    $env:VEHICLE_ID = $VehicleId
}
Remove-Item Env:VEHICLE_X -ErrorAction SilentlyContinue
Remove-Item Env:VEHICLE_Y -ErrorAction SilentlyContinue
Remove-Item Env:VEHICLE_HEADING -ErrorAction SilentlyContinue
Remove-Item Env:ROBOT_AUTO_REGISTER -ErrorAction SilentlyContinue

& $VenvPython -m pip install -r requirements.txt
& $VenvPython -u -m app.workers.robot_worker
