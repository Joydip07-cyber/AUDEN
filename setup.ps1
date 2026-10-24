# Compatibility wrapper. First-run setup is built into AUDEN now; this script
# simply opens the same wizard for anyone used to running setup.ps1 directly.
# Run:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
python auden.py --setup
exit $LASTEXITCODE
