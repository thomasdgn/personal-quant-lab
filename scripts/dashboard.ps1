<#
.SYNOPSIS
    Ouvre le tableau de bord local (lecture seule) dans le navigateur.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dashboard.ps1
#>
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
Set-Location $root
& $python -m streamlit run app\dashboard.py
