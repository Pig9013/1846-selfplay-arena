# Check the local prerequisites for 1846 Self-Play Arena.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host "== 1846 Self-Play Arena bootstrap =="

$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) { Write-Host "python not found on PATH" -ForegroundColor Red; exit 1 }
$ver = & python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
Write-Host "python $ver"

if (-not (Test-Path "runtime/rubyinstaller-3.4.9-1-x64/bin/ruby.exe")) {
  Write-Host "Ruby runtime missing: restore runtime/ from the release bundle" -ForegroundColor Red
  exit 1
}
Write-Host "ruby runtime: ok"

$engine = Join-Path (Split-Path -Parent $PSScriptRoot) "18xx-master"
if (-not (Test-Path (Join-Path $engine "lib/engine.rb"))) {
  Write-Host "rules engine missing at $engine" -ForegroundColor Yellow
  Write-Host "clone it with:  git clone https://github.com/tobymao/18xx \"$engine\""
  exit 1
}
Write-Host "rules engine: $engine"

& python -c "import torch, sys; print('torch', torch.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "torch not installed - the platform still runs, training needs: pip install torch" -ForegroundColor Yellow
}

Write-Host "ready. start the platform with 启动平台.cmd" -ForegroundColor Green
