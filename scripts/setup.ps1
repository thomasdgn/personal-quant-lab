<#
.SYNOPSIS
    (Re)crée l'environnement Python du personal-quant-lab et vérifie l'installation.

.DESCRIPTION
    1. Crée .venv si absent (ou le recrée avec -Recreate).
    2. Installe requirements-dev.txt via "python -m pip" (évite les pip.exe cassés
       quand le dossier du projet a été déplacé).
    3. Enregistre le noyau Jupyter "quant-lab".
    4. Lance la suite de tests (hors-ligne).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Recreate
#>
param(
    [switch]$Recreate,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if ($Recreate -and (Test-Path ".venv")) {
    Write-Host "Suppression de l'ancien .venv..."
    Remove-Item -Recurse -Force ".venv"
}
if (-not (Test-Path $venvPython)) {
    Write-Host "Création de .venv avec '$Python'..."
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Échec de la création du venv." }
}

Write-Host "Installation des dépendances (requirements-dev.txt)..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r requirements-dev.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Échec de l'installation des dépendances." }

Write-Host "Enregistrement du noyau Jupyter 'quant-lab'..."
& $venvPython -m ipykernel install --user --name quant-lab --display-name "Python (quant-lab)" | Out-Null

Write-Host "Lancement des tests..."
& $venvPython -m pytest
if ($LASTEXITCODE -ne 0) { throw "Des tests échouent." }

Write-Host ""
Write-Host "Installation OK. Prochaine étape : .venv\Scripts\python.exe main.py status"
