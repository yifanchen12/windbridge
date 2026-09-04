$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

$python = ".venv\Scripts\python.exe"
& $python -m pip install --disable-pip-version-check -r requirements.txt
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "WindBridge" `
    --icon "assets\app_icon.ico" `
    --collect-all "tkinterdnd2" `
    --add-data "web;web" `
    --add-data "assets;assets" `
    main.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$smoke = Start-Process -FilePath "dist\WindBridge.exe" -ArgumentList "--smoke-test" -Wait -PassThru -WindowStyle Hidden
if ($smoke.ExitCode -ne 0) { exit $smoke.ExitCode }
Write-Host "Built: $PSScriptRoot\dist\WindBridge.exe"
