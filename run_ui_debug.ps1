param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$PythonArgs = @()
if ($env:PYTHON_BIN) {
    $Python = $env:PYTHON_BIN
} elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot "venv\Scripts\python.exe")) {
    $Python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
} else {
    $Python = (Get-Command py -ErrorAction Stop).Source
    $PythonArgs = @("-3.12")
}

& $Python @PythonArgs -c "import customtkinter" *> $null
if ($LASTEXITCODE -ne 0) {
    throw "customtkinter is not available in $Python. Create the project venv and install requirements.txt."
}

$env:PYTHONUNBUFFERED = "1"
& $Python @PythonArgs (Join-Path $PSScriptRoot "subtitle_agent_app.py") @ScriptArgs
exit $LASTEXITCODE
