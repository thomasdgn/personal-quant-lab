<#
.SYNOPSIS
    Contrôle qualité : lint ruff puis tests pytest avec couverture.

.DESCRIPTION
    - ruff check .  (échec = arrêt)
    - pytest avec couverture de src/ (résumé console + rapport HTML dans htmlcov/)
    Objectif documenté : couverture >= 85 % sur src/ (non bloquant).

.PARAMETER Fast
    Exclut les tests marqués "slow" (walk-forward, AppTest, CLI de bout en bout).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Fast
#>
param([switch]$Fast)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
Set-Location $root

Write-Host "=== ruff ==="
& $python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== pytest + couverture ==="
$arguments = @("-m", "pytest", "--cov=src", "--cov-report=term:skip-covered", "--cov-report=html")
# Suite complète parallélisée (pytest-xdist) ; le mode rapide reste séquentiel (démarrage des workers coûteux).
if ($Fast) { $arguments += @("-m", "not slow") } else { $arguments += @("-n", "auto") }
& $python @arguments
exit $LASTEXITCODE
