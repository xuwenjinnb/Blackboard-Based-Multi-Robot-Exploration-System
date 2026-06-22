$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
$DistName = "exe" + [char]0x6587 + [char]0x4EF6
$Dist = Join-Path $Root $DistName
$BuildRoot = Join-Path $Dist "_pyinstaller_build"
$SpecRoot = Join-Path $Dist "_pyinstaller_specs"
$BackendPath = Join-Path $Root "backend"
$PackagingPath = Join-Path $BackendPath "packaging"
$FrontendDist = Join-Path $Root "frontend\Pathfinding-Visualizer-ThreeJS-master\dist"
$FrontendData = "$FrontendDist;frontend\Pathfinding-Visualizer-ThreeJS-master\dist"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python not found: $Python"
}

if (-not (Test-Path -LiteralPath (Join-Path $FrontendDist "index.html"))) {
    throw "Frontend dist not found: $FrontendDist"
}

New-Item -ItemType Directory -Force -Path $Dist, $BuildRoot, $SpecRoot | Out-Null

$CommonArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--console",
    "--paths", $BackendPath,
    "--paths", $PackagingPath,
    "--distpath", $Dist,
    "--specpath", $SpecRoot,
    "--hidden-import", "component_args",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.http.h11_impl",
    "--hidden-import", "uvicorn.protocols.http.httptools_impl",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.protocols.websockets.websockets_impl",
    "--hidden-import", "uvicorn.lifespan.on",
    "--hidden-import", "uvicorn.lifespan.off",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.loops.asyncio",
    "--exclude-module", "torch",
    "--exclude-module", "tensorflow",
    "--exclude-module", "numpy",
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib"
)

function Build-ComponentExe {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Entry,
        [string[]]$ExtraArgs = @()
    )

    $WorkPath = Join-Path $BuildRoot $Name
    Write-Host "Building $Name.exe ..." -ForegroundColor Cyan
    & $Python @CommonArgs "--name" $Name "--workpath" $WorkPath @ExtraArgs $Entry
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed for $Name.exe with exit code $LASTEXITCODE"
    }
}

Build-ComponentExe `
    -Name "api_gateway" `
    -Entry (Join-Path $Root "backend\packaging\api_gateway_entry.py") `
    -ExtraArgs @("--collect-submodules", "app", "--add-data", $FrontendData)

Build-ComponentExe `
    -Name "controller_worker" `
    -Entry (Join-Path $Root "backend\packaging\controller_worker_entry.py") `
    -ExtraArgs @("--collect-submodules", "app")

Build-ComponentExe `
    -Name "navigator_worker" `
    -Entry (Join-Path $Root "backend\packaging\navigator_worker_entry.py") `
    -ExtraArgs @("--collect-submodules", "app")

Build-ComponentExe `
    -Name "robot_worker" `
    -Entry (Join-Path $Root "backend\packaging\robot_worker_entry.py") `
    -ExtraArgs @("--collect-submodules", "app")

Build-ComponentExe `
    -Name "display_ui" `
    -Entry (Join-Path $Root "backend\packaging\display_ui_entry.py") `
    -ExtraArgs @("--add-data", $FrontendData)

Write-Host ""
Write-Host "EXE output directory: $Dist" -ForegroundColor Green
