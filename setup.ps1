[CmdletBinding()]
param([ValidateSet('postgresql','sqlite')][string]$Profile = 'postgresql', [switch]$WithoutModels, [switch]$WithoutBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Setup stopped with exit code $LASTEXITCODE. Fix the error above and rerun setup.bat." }
}
try {
    $env:PYTHONUTF8 = '1'
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) { Invoke-Checked $launcher.Source @('-3.14','-m','venv',(Join-Path $PSScriptRoot '.venv')) }
        else {
            $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
            if (-not $pythonCommand) { throw 'Install Python 3.14 for Windows, then run setup.bat again.' }
            Invoke-Checked $pythonCommand.Source @('-c','import sys; assert sys.version_info[:2] == (3,14), "Install Python 3.14."')
            Invoke-Checked $pythonCommand.Source @('-m','venv',(Join-Path $PSScriptRoot '.venv'))
        }
    }
    $setupArgs = @((Join-Path $PSScriptRoot 'scripts\setup.py'),'--profile',$Profile)
    if ($WithoutModels) { $setupArgs += '--without-models' }
    if ($WithoutBrowser) { $setupArgs += '--without-browser' }
    Invoke-Checked $venvPython $setupArgs
    Write-Host 'Setup complete. Run start.bat.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host ('Setup failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
