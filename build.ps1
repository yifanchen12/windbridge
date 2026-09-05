param([string]$OutputDirectory = "dist")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

$python = ".venv\Scripts\python.exe"
& $python -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "WindBridge" `
    --distpath $OutputDirectory `
    --icon "assets\app_icon.ico" `
    --collect-all "tkinterdnd2" `
    --add-data "web;web" `
    --add-data "assets;assets" `
    main.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$executable = Join-Path $OutputDirectory "WindBridge.exe"
$smoke = Start-Process -FilePath $executable -ArgumentList "--smoke-test" -Wait -PassThru -WindowStyle Hidden
if ($smoke.ExitCode -ne 0) { exit $smoke.ExitCode }
Write-Host "Built: $executable"
