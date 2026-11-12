# Pousse l'historique vers origin commit par commit (connexion instable : petits paquets + nouvelles tentatives).
# Usage : powershell -ExecutionPolicy Bypass -File scripts\push-incremental.ps1 [-Branch main] [-Retries 5]
param([string]$Branch = "main", [int]$Retries = 5)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
git -C $repo config http.postBuffer 524288000
git -C $repo config http.lowSpeedLimit 1000
git -C $repo config http.lowSpeedTime 60

$commits = git -C $repo rev-list --reverse $Branch
$i = 0
foreach ($c in $commits) {
    $i++
    $ok = $false
    for ($t = 1; $t -le $Retries -and -not $ok; $t++) {
        Write-Host "[$i/$($commits.Count)] $($c.Substring(0,7)) (essai $t)"
        git -C $repo push origin "${c}:refs/heads/$Branch" 2>&1 | Out-Host
        if ($LASTEXITCODE -eq 0) { $ok = $true } else { Start-Sleep -Seconds (5 * $t) }
    }
    if (-not $ok) { Write-Host "Echec sur $c : relancez le script, il reprendra la ou il s'est arrete."; exit 1 }
}
git -C $repo push -u origin $Branch 2>&1 | Out-Host
Write-Host "Termine : $($commits.Count) commits sur origin/$Branch"
