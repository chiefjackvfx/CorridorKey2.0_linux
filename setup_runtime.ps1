$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
Set-Location -LiteralPath $project
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Supported: Windows x86-64' }
$tools = Join-Path $project '.runtime\tools'
$downloads = Join-Path $project '.runtime\downloads'
New-Item -ItemType Directory -Force -Path "$tools\bin", $downloads | Out-Null
$env:UV_UNMANAGED_INSTALL = "$tools\bin"
$env:UV_NO_MODIFY_PATH = '1'
$env:UV_NO_CONFIG = '1'
$env:UV_PYTHON_INSTALL_DIR = "$tools\python"
$env:UV_CACHE_DIR = "$downloads\uv"
Remove-Item Env:PYTHONHOME, Env:PYTHONPATH, Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
$uv = "$tools\bin\uv.exe"
$needsUv = -not (Test-Path -LiteralPath $uv)
if (-not $needsUv) { $needsUv = ((& $uv --version) -notlike 'uv 0.12.21 *') }
if ($needsUv) {
    $installer = "$downloads\install-uv.ps1"
    Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/0.12.21/install.ps1' -OutFile $installer
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $uv python install 3.12 --no-bin --no-registry
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$runtimePython = (& $uv python find --managed-python --no-project 3.12).Trim()
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $runtimePython "$project\runtime_setup.py" --uv $uv --python $runtimePython @args
exit $LASTEXITCODE
