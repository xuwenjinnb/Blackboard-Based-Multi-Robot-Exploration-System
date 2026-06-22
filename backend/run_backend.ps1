$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

function Test-VenvPython {
    if (-not (Test-Path $VenvPython)) {
        return $false
    }

    & $VenvPython -c "import sys; print(sys.executable)" *> $null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-VenvPython)) {
    if (Test-Path ".venv") {
        $BackupName = ".venv-broken-$(Get-Date -Format 'yyyyMMddHHmmss')"
        Rename-Item -LiteralPath ".venv" -NewName $BackupName
        Write-Host "Existing .venv is broken; renamed it to $BackupName"
    }

    python -m venv .venv
}

& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
