param(
    [ValidateSet('Install', 'Run', 'Test')]
    [string]$Mode = 'Run'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    throw 'This installer supports Windows 10/11 x64. ARM64 and 32-bit Windows are not supported yet.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$assets = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'setup-assets.json') -Raw | ConvertFrom-Json
$dataRoot = if ($env:SM_DATA_DIR) { [IO.Path]::GetFullPath($env:SM_DATA_DIR) } else { Join-Path $env:LOCALAPPDATA 'SmallCloset' }
$env:SM_DATA_DIR = $dataRoot
$env:SM_TESSDATA = Join-Path $dataRoot 'tessdata'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $dataRoot 'browsers'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $dataRoot 'python'
$env:UV_CACHE_DIR = Join-Path $dataRoot 'uv-cache'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$uvExe = Join-Path $dataRoot 'tools\uv.exe'
$pythonExe = Join-Path $dataRoot 'windows-env\Scripts\python.exe'
$readyFile = Join-Path $dataRoot 'windows-install.json'

function Test-Hash([string]$Path, [string]$Expected) {
    return (Test-Path -LiteralPath $Path -PathType Leaf) -and ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Expected)
}

function Install-Uv {
    if (Test-Hash $uvExe $assets.uv.exe_sha256) { return }
    $tools = Split-Path -Parent $uvExe
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    $wheel = Join-Path $tools 'uv-download.whl'
    $temporaryExe = Join-Path $tools 'uv-download.exe'
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $assets.uv.url -OutFile $wheel -TimeoutSec 180
        if (-not (Test-Hash $wheel $assets.uv.sha256)) { throw 'uv download checksum mismatch. Download stopped; do not disable verification.' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($wheel)
        try {
            $entry = $archive.GetEntry($assets.uv.entry)
            if ($null -eq $entry) { throw 'uv executable was not found in the verified wheel.' }
            $inputStream = $entry.Open()
            try {
                $outputStream = [IO.File]::Create($temporaryExe)
                try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
            } finally { $inputStream.Dispose() }
        } finally { $archive.Dispose() }
        if (-not (Test-Hash $temporaryExe $assets.uv.exe_sha256)) { throw 'uv executable checksum mismatch.' }
        Move-Item -LiteralPath $temporaryExe -Destination $uvExe -Force
    } finally {
        if (Test-Path -LiteralPath $wheel) { Remove-Item -LiteralPath $wheel -Force }
        if (Test-Path -LiteralPath $temporaryExe) { Remove-Item -LiteralPath $temporaryExe -Force }
    }
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE. See the output above." }
}

function Get-SetupFingerprint {
    return (Get-FileHash -LiteralPath (Join-Path $projectRoot 'requirements-windows.txt') -Algorithm SHA256).Hash + (Get-FileHash -LiteralPath (Join-Path $projectRoot 'requirements.txt') -Algorithm SHA256).Hash + (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'setup-assets.json') -Algorithm SHA256).Hash
}

function Install-SmallCloset {
    Write-Host '[1/4] Preparing a private Python runtime. No system Python or Linux is required.'
    Install-Uv
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Invoke-Checked $uvExe @('venv', '--no-project', '--managed-python', '--python', $assets.python, (Join-Path $dataRoot 'windows-env'))
    }
    Write-Host '[2/4] Installing application and bundled OCR wheels.'
    Invoke-Checked $uvExe @('pip', 'install', '--python', $pythonExe, '--only-binary', ':all:', '-r', (Join-Path $projectRoot 'requirements-windows.txt'))
    Write-Host '[3/4] Installing Chromium. The first download may take several minutes.'
    Invoke-Checked $pythonExe @('-m', 'playwright', 'install', 'chromium')
    Write-Host '[4/4] Verifying Korean/English OCR models and the local OCR engine.'
    Invoke-Checked $pythonExe @((Join-Path $PSScriptRoot 'setup_models.py'), '--check-ocr')
    $fingerprint = Get-SetupFingerprint
    @{ requirements = $fingerprint; python = $assets.python } | ConvertTo-Json | Set-Content -LiteralPath $readyFile -Encoding UTF8
    Write-Host 'Installation complete. Double-click START-WINDOWS.bat.' -ForegroundColor Green
}

Push-Location -LiteralPath $projectRoot
try {
    if ($Mode -eq 'Install') {
        Install-SmallCloset
    } else {
        $needsInstall = -not (Test-Path -LiteralPath $pythonExe) -or -not (Test-Path -LiteralPath $readyFile)
        if (-not $needsInstall) {
            $saved = Get-Content -LiteralPath $readyFile -Raw | ConvertFrom-Json
            $fingerprint = Get-SetupFingerprint
            $needsInstall = $saved.requirements -ne $fingerprint -or $saved.python -ne $assets.python
        }
        if ($needsInstall) { Install-SmallCloset }
        if ($Mode -eq 'Test') {
            Invoke-Checked $uvExe @('pip', 'install', '--python', $pythonExe, '-r', (Join-Path $projectRoot 'requirements-dev.txt'))
            $env:SM_HEADLESS = '1'
            $env:SM_BROWSER_TESTS = '1'
            Invoke-Checked $pythonExe @((Join-Path $PSScriptRoot 'test.py'))
            Invoke-Checked $pythonExe @((Join-Path $PSScriptRoot 'smoke_ui.py'))
            Invoke-Checked $pythonExe @((Join-Path $PSScriptRoot 'smoke_desktop.py'))
        } else {
            Write-Host 'Opening SmallCloset in your browser. Keep this window open; Ctrl+C stops the program.'
            Invoke-Checked $pythonExe @('-m', 'smallcloset.desktop')
        }
    }
} catch {
    Write-Host ('SmallCloset could not finish: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
