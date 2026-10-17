[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Setup command failed with exit code $LASTEXITCODE. Fix the error above and run setup.bat again."
    }
}

try {
    Write-Host 'Parity setup - Python 3.14, Chromium, MiniLM and free local Qwen chat'
    Write-Host 'First setup downloads several GB. Later runs reuse verified caches.'
    $cacheRoot = Join-Path $projectRoot '.cache'
    $tempRoot = Join-Path $cacheRoot 'tmp'
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $env:TEMP = $tempRoot
    $env:TMP = $tempRoot
    $env:PYTHONUTF8 = '1'
    $env:PIP_CACHE_DIR = Join-Path $cacheRoot 'pip'
    $env:HF_HOME = Join-Path $cacheRoot 'huggingface'
    $env:PARITY_MODEL_CACHE = Join-Path $cacheRoot 'models'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $cacheRoot 'ms-playwright'
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
    $env:HF_HUB_DISABLE_XET = '1'
    $env:PARITY_OFFLINE = '0'
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($launcher) {
            Invoke-Checked $launcher.Source @('-3.14', '-m', 'venv', (Join-Path $projectRoot '.venv'))
        } elseif ($pythonCommand) {
            Invoke-Checked $pythonCommand.Source @('-c', 'import sys; assert sys.version_info[:2] == (3,14), "Install Python 3.14 for this tested release."')
            Invoke-Checked $pythonCommand.Source @('-m', 'venv', (Join-Path $projectRoot '.venv'))
        } else {
            throw 'Install Python 3.14 for Windows, then run setup.bat again.'
        }
    }
    Invoke-Checked $venvPython @('-c', 'import sys; assert sys.version_info[:2] == (3,14), "This .venv uses another Python version. Rename it and run setup.bat with Python 3.14."; print("Python", sys.version.split()[0])')
    $lockPath = Join-Path $projectRoot 'requirements-lock.txt'
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        $lockPath = Join-Path $projectRoot 'requirements.txt'
    }
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', $lockPath)
    Invoke-Checked $venvPython @((Join-Path $projectRoot 'scripts\cache_model.py'))
    Invoke-Checked $venvPython @('-m', 'playwright', 'install', 'chromium')
    Invoke-Checked $venvPython @((Join-Path $projectRoot 'scripts\setup_local_chat.py'))
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html') -PathType Leaf)) {
        throw 'The prebuilt frontend is missing. Extract the complete Parity release ZIP.'
    }
    Write-Host ''
    Write-Host 'Setup complete. Run start.bat to open Parity.' -ForegroundColor Green
    Write-Host 'No API key, paid account, or Node installation is needed for local chat.'
    exit 0
} catch {
    Write-Host ''
    Write-Host ('Setup failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
