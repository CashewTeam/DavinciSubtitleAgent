param(
  [ValidateSet("Release","Debug")]
  [string]$Configuration = "Release",
  [int]$Jobs = 8,
  [string]$OrtDir = "",
  [ValidateSet("Ninja","Ninja Multi-Config")]
  [string]$Generator = "Ninja Multi-Config"
)

$ErrorActionPreference = "Stop"

function Write-Die($msg) {
  Write-Host "ERROR: $msg" -ForegroundColor Red
  exit 1
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildDir = Join-Path $repoRoot ("build-" + $Configuration)

if ([string]::IsNullOrWhiteSpace($OrtDir)) {
  $OrtDir = Join-Path $repoRoot "models\\onnxruntime-win-x64-1.23.2"
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\\Installer\\vswhere.exe"
if (!(Test-Path $vswhere)) {
  Write-Die "vswhere.exe not found: $vswhere (install Visual Studio Build Tools first)"
}

$vsInstall = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ([string]::IsNullOrWhiteSpace($vsInstall)) {
  Write-Die "Visual Studio Build Tools not found (missing VC.Tools.x86.x64)"
}

$vsDevCmd = Join-Path $vsInstall "Common7\\Tools\\VsDevCmd.bat"
if (!(Test-Path $vsDevCmd)) {
  Write-Die "VsDevCmd.bat not found: $vsDevCmd"
}

if (!(Test-Path (Join-Path $OrtDir "include\\onnxruntime_cxx_api.h"))) {
  Write-Die "ONNX Runtime headers missing under: $OrtDir\\include"
}

Write-Host "VSDEVCMD=$vsDevCmd"
Write-Host "REPO_ROOT=$repoRoot"
Write-Host "BUILD_DIR=$buildDir"
Write-Host "ORT_DIR=$OrtDir"
Write-Host ""

# Capture the dev environment from VsDevCmd.bat into this PowerShell session
$tmp = [System.IO.Path]::GetTempFileName()
try {
  cmd /c "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && set > `"$tmp`""
  Get-Content $tmp | ForEach-Object {
    $line = $_
    $idx = $line.IndexOf("=")
    if ($idx -gt 0) {
      $name = $line.Substring(0, $idx)
      $value = $line.Substring($idx + 1)
      Set-Item -Path ("Env:$name") -Value $value | Out-Null
    }
  }
} finally {
  Remove-Item -Force $tmp -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

# Always isolate builds by generator to avoid accidentally mixing build artifacts
# (and, on Windows, to reduce the chances of picking up the wrong ORT libs at runtime).
$buildDir = Join-Path $repoRoot ("build-" + $Configuration + "-" + ($Generator -replace " ", "-"))
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

# If a legacy build directory exists (older script versions), leave it alone but never reuse it.
$cachePath = Join-Path $buildDir "CMakeCache.txt"
if (Test-Path $cachePath) {
  $cache = Get-Content $cachePath -ErrorAction SilentlyContinue
  $cacheGen = ($cache | Where-Object { $_ -like "CMAKE_GENERATOR:*" } | Select-Object -First 1)
  if ($cacheGen -and ($cacheGen -notlike "*=$Generator")) {
    Write-Host "Note: generator mismatch detected; using BUILD_DIR=$buildDir"
  }
}

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

& cmake -S $repoRoot -B $buildDir -G $Generator `
  -DUSE_SYSTEM_ORT=ON `
  -DONNXRUNTIME_DIR="$OrtDir"

& cmake --build $buildDir -j $Jobs --config $Configuration
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
$exeGuess = Join-Path $buildDir "cpp-ort-aligner.exe"
$exeGuess2 = Join-Path $buildDir (Join-Path $Configuration "cpp-ort-aligner.exe")
if (Test-Path $exeGuess2) { $exeGuess = $exeGuess2 }
Write-Host "Build OK: $exeGuess" -ForegroundColor Green

# Ensure runtime loads the correct ORT DLLs (avoid incompatible copies under System32).
# Windows DLL search prefers the executable directory, so we copy the bundled runtime next to the exe.
$ortLib = Join-Path $OrtDir "lib"
$exeDir = Split-Path -Parent $exeGuess
$dlls = @(
  "onnxruntime.dll",
  "onnxruntime_providers_shared.dll"
)
foreach ($dll in $dlls) {
  $src = Join-Path $ortLib $dll
  $dst = Join-Path $exeDir $dll
  if (Test-Path $src) {
    Copy-Item -Force $src $dst
    Write-Host "Copied: $dll -> $exeDir" -ForegroundColor DarkGray
  }
}
