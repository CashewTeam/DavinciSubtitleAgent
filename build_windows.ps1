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

& $Python @PythonArgs -c "import PyInstaller, customtkinter"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller and customtkinter must be installed in $Python. Install requirements.txt first."
}

$Version = (& $Python @PythonArgs -c "from subtitle_agent_app.main import APP_VERSION; print(APP_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) {
    throw "Could not read the application version."
}

$DistPath = Join-Path $PSScriptRoot "dist\windows"
$WorkPath = Join-Path $PSScriptRoot "build\windows"
& $Python @PythonArgs -m PyInstaller --clean --noconfirm --distpath $DistPath --workpath $WorkPath "SubtitleAgentWindows.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$AppDir = Join-Path $DistPath "Subtitle Agent"
$AppExe = Join-Path $AppDir "Subtitle Agent.exe"
$CliExe = Join-Path $AppDir "Subtitle Agent CLI.exe"
foreach ($ExpectedExe in @($AppExe, $CliExe)) {
    if (-not (Test-Path -LiteralPath $ExpectedExe)) {
        throw "Expected packaged executable was not created: $ExpectedExe"
    }
}

$PythonDll = Get-ChildItem -LiteralPath $AppDir -Filter "python312.dll" -Recurse -File | Select-Object -First 1
if (-not $PythonDll) {
    throw "The packaged application is missing python312.dll: $AppDir"
}
foreach ($RuntimeDllName in @("VCRUNTIME140.dll", "VCRUNTIME140_1.dll")) {
    $RuntimeDll = Get-ChildItem -LiteralPath $AppDir -Filter $RuntimeDllName -Recurse -File | Select-Object -First 1
    if (-not $RuntimeDll) {
        throw "The packaged application is missing ${RuntimeDllName}: $AppDir"
    }
}

$ZipPath = Join-Path $DistPath ("SubtitleAgent_Windows_x64_{0}.zip" -f $Version)
$WorkspaceRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
$ZipFullPath = [System.IO.Path]::GetFullPath($ZipPath)
if (-not $ZipFullPath.StartsWith($WorkspaceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to write package outside the project workspace: $ZipFullPath"
}
if (Test-Path -LiteralPath $ZipFullPath) {
    Remove-Item -LiteralPath $ZipFullPath -Force
}

Compress-Archive -LiteralPath $AppDir -DestinationPath $ZipFullPath -CompressionLevel Optimal

$IntermediateDir = Join-Path $WorkPath "SubtitleAgentWindows"
foreach ($IntermediateExeName in @("Subtitle Agent.exe", "Subtitle Agent CLI.exe")) {
    $IntermediateExe = Join-Path $IntermediateDir $IntermediateExeName
    if (Test-Path -LiteralPath $IntermediateExe) {
        Remove-Item -LiteralPath $IntermediateExe -Force
    }
}

Write-Output "Windows package ready: $ZipFullPath"
Write-Output "Launch the GUI from: $([System.IO.Path]::GetFullPath($AppExe))"
Write-Output "Intermediate EXEs under '$WorkPath' were removed; only the dist directory and ZIP are runnable packages."
