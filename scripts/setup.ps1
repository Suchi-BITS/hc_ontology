# Thin wrapper kept for compatibility. The real implementation is scripts/dev.py (stdlib only).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..
python scripts\dev.py setup
