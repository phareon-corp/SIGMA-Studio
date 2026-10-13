<#
    Build do ia4294 para Windows: venv → PyInstaller → instalador.

    Rode numa máquina Windows 10/11 64 bits, na raiz do projeto:

        powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1

    Precisa de: Python 3.11+ (python.org, "Add to PATH") e, para o instalador,
    Inno Setup 6 (https://jrsoftware.org/isdl.php). Sem o Inno o script ainda
    gera dist\ia4294\, que roda como pasta portátil.

    Não há como fazer este passo a partir do Linux: PySide6 e o bootloader do
    PyInstaller são binários do alvo, e PyInstaller não faz cross-compile.
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipTests,
    [switch]$Portable   # só a pasta, sem chamar o Inno Setup
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "== ia4294 → Windows ==  $root" -ForegroundColor Cyan

# 1. venv dedicado à build, para não misturar com o de desenvolvimento
$venv = Join-Path $root ".venv-win"
if (-not (Test-Path $venv)) {
    & $Python -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --upgrade pip wheel | Out-Null
& $py -m pip install -e ".[dev]"
& $py -m pip install "pyinstaller>=6.6"

# 2. a suíte roda offscreen; se quebrar aqui, não adianta empacotar
if (-not $SkipTests) {
    $env:QT_QPA_PLATFORM = "offscreen"
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "a suíte falhou: build cancelada" }
    Remove-Item Env:\QT_QPA_PLATFORM
}

# 3. ícone (vem do mesmo desenho da janela) e congelamento
& $py packaging\make_icon.py
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm packaging\ia4294.spec
if (-not (Test-Path "dist\ia4294\ia4294.exe")) { throw "PyInstaller não gerou dist\ia4294\ia4294.exe" }

# 4. fumaça: abre e fecha sozinho no simulador, sem tela
$proc = Start-Process -FilePath "dist\ia4294\ia4294.exe" -ArgumentList "--sim","--sim-speed","0.05","--screenshot","dist\fumaca.png" -PassThru
if (-not $proc.WaitForExit(120000)) { $proc.Kill(); throw "o executável não fechou sozinho: veja dist\fumaca.png" }
if (-not (Test-Path "dist\fumaca.png")) { throw "o executável abriu mas não desenhou a janela" }
Write-Host "fumaça ok: dist\fumaca.png" -ForegroundColor Green

# 5. instalador
if ($Portable) {
    Write-Host "pasta portátil pronta: dist\ia4294\" -ForegroundColor Green
    exit 0
}
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup 6 não encontrado; ficou só a pasta portátil em dist\ia4294\."
    exit 0
}
& $iscc packaging\ia4294.iss
Write-Host "instalador: dist\ia4294-0.1.0-setup.exe" -ForegroundColor Green
