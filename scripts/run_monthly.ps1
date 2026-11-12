<#
.SYNOPSIS
    Routine mensuelle automatisable du personal-quant-lab (aucun ordre exécuté).

.DESCRIPTION
    Lance `python main.py run-month --refresh-data --notify` avec l'environnement .venv
    (notifications envoyées seulement si config/notify.yaml les active),
    écrit toute la sortie dans logs\YYYY-MM.log et renvoie le code de sortie de
    la CLI :
        0 = rapport généré sans alerte critique
        1 = erreur technique (données, configuration...)
        2 = rapport généré mais statut CRITICAL (lire les alertes)
    La décision reste manuelle : le script ne fait que préparer le rapport et
    l'entrée PENDING du journal de paper trading.

.PARAMETER NoRefresh
    N'actualise pas les données (utilise le fichier local).

.PARAMETER CliArgs
    Arguments supplémentaires passés tels quels à `main.py run-month`, placés
    après les options du script (ex. `run_monthly.ps1 -NoRefresh --report-date 2026-08-31`).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_monthly.ps1
#>
param(
    [switch]$NoRefresh,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs = @()
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("{0}.log" -f (Get-Date -Format "yyyy-MM"))

function Write-Log([string]$message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

if (-not (Test-Path $python)) {
    Write-Log "ERREUR : $python introuvable. Lance d'abord scripts\setup.ps1."
    exit 1
}

$arguments = @("main.py", "run-month", "--notify")
if (-not $NoRefresh) { $arguments += "--refresh-data" }
$arguments += $CliArgs

# Sortie Python en UTF-8 pour un journal lisible (accents, flèches).
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$stdout = [System.IO.Path]::GetTempFileName()
$stderr = [System.IO.Path]::GetTempFileName()
Write-Log ("Démarrage : python " + ($arguments -join " "))
try {
    $quoted = $arguments | ForEach-Object { if ($_ -match "\s") { '"' + $_ + '"' } else { $_ } }
    $process = Start-Process -FilePath $python -ArgumentList $quoted -WorkingDirectory $root `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $code = $process.ExitCode
    foreach ($file in @($stdout, $stderr)) {
        $content = Get-Content -Path $file -Encoding UTF8
        if ($content) {
            $content | ForEach-Object { Write-Host $_ }
            Add-Content -Path $log -Value $content -Encoding UTF8
        }
    }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $stdout, $stderr
}

switch ($code) {
    0 { Write-Log "Terminé : rapport généré (code 0). Décision manuelle à renseigner." }
    2 { Write-Log "Terminé avec statut CRITICAL (code 2) : lire les alertes du rapport avant toute décision." }
    default { Write-Log "ÉCHEC (code $code) : voir le détail ci-dessus." }
}
exit $code
