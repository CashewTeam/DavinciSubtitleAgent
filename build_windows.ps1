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

$Machine = (& $Python @PythonArgs -c "import platform; print(platform.machine())").Trim().ToLowerInvariant()
if ($Machine -notin @("amd64", "x86_64")) {
    throw "Windows packages are built for x64 only; current architecture is $Machine."
}
$Architecture = "x64"
$ExpectedPeMachine = 0x8664

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

function Get-PeMachine([string]$Path) {
    $Bytes = [System.IO.File]::ReadAllBytes($Path)
    $PeOffset = [BitConverter]::ToInt32($Bytes, 0x3C)
    if ($PeOffset -lt 0 -or $PeOffset + 6 -gt $Bytes.Length) {
        throw "Invalid PE executable: $Path"
    }
    if ([System.Text.Encoding]::ASCII.GetString($Bytes, $PeOffset, 4) -ne "PE`0`0") {
        throw "Invalid PE signature: $Path"
    }
    return [BitConverter]::ToUInt16($Bytes, $PeOffset + 4)
}

foreach ($ExpectedExe in @($AppExe, $CliExe)) {
    $PeMachine = Get-PeMachine $ExpectedExe
    if ($PeMachine -ne $ExpectedPeMachine) {
        throw "Unexpected executable architecture for ${ExpectedExe}: PE machine 0x$($PeMachine.ToString('X4')), expected 0x$($ExpectedPeMachine.ToString('X4'))."
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

$ZipPath = Join-Path $DistPath ("SubtitleAgent_Windows_{0}_{1}.zip" -f $Architecture, $Version)
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
