# Build Ghost Controller for Windows (x86_64).
#   .\packaging\build-windows.ps1              -> dist\ghost-handler\ (onedir bundle)
#   .\packaging\build-windows.ps1 -Installer   -> + dist\Ghost_Controller-Setup-x86_64.exe
# The Windows counterpart of build-linux.sh; Inno Setup 6 must be installed
# for -Installer (choco install innosetup).
param([switch]$Installer)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Checked {
    & $args[0] $args[1..($args.Length - 1)]
    if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $args" }
}

$Venv = if ($env:VENV) { $env:VENV } else { ".venv-desktop" }
$Py = "$Venv\Scripts\python.exe"
$AppVer = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([0-9.]+)"').Matches[0].Groups[1].Value
# Tests and the smoke run print non-ASCII; the default code page cannot encode it.
$env:PYTHONUTF8 = "1"

if (-not (Test-Path $Py)) {
    Invoke-Checked python -m venv $Venv
    Invoke-Checked $Py -m pip install --upgrade pip
    Invoke-Checked $Py -m pip install -r requirements.txt
    Invoke-Checked $Py -m pip install pyinstaller pillow
}

Write-Host "== regenerate tokens =="
Invoke-Checked $Py tools\gen_tokens.py

Write-Host "== smoke test (headless) =="
Invoke-Checked $Py tests\smoke_test.py

Write-Host "== icon =="
New-Item -ItemType Directory -Force build | Out-Null
Invoke-Checked $Py -c "from PIL import Image; Image.open('design/icon-256.png').save('build/ghost-controller.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Write-Host "== pyinstaller =="
Invoke-Checked "$Venv\Scripts\pyinstaller.exe" --noconfirm --clean packaging\ghost-handler.spec
Write-Host "bundle: dist\ghost-handler\ghost-handler.exe"

if ($Installer) {
    Write-Host "== installer =="
    $Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $Iscc) {
        $Iscc = Get-ChildItem "${env:ProgramFiles(x86)}\Inno Setup *\ISCC.exe", "$env:ProgramFiles\Inno Setup *\ISCC.exe" `
            -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $Iscc) { throw "Inno Setup (ISCC.exe) not found - choco install innosetup" }
    Invoke-Checked $Iscc "/DAppVersion=$AppVer" packaging\ghost-controller.iss
    Write-Host "installer: dist\Ghost_Controller-Setup-x86_64.exe"
}
