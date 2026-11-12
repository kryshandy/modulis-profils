# Pousse l'historique vers origin commit par commit (connexion instable : petits paquets + nouvelles tentatives).
# Ne renvoie que les commits absents du dépôt distant : on peut relancer le script autant de fois que nécessaire.
# Usage : powershell -ExecutionPolicy Bypass -File scripts\push-incremental.ps1 [-Branch main] [-Retries 5]
param([string]$Branch = "main", [int]$Retries = 5)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
git -C $repo config http.postBuffer 524288000
git -C $repo config http.lowSpeedLimit 1000
git -C $repo config http.lowSpeedTime 60

git -C $repo fetch origin $Branch 2>&1 | Out-Null
$remoteExists = ($LASTEXITCODE -eq 0)
if ($remoteExists) {
    $commits = @(git -C $repo rev-list --reverse "origin/$Branch..$Branch")
} else {
    $commits = @(git -C $repo rev-list --reverse $Branch)
}
if ($commits.Count -eq 0) { Write-Host "Rien a pousser : origin/$Branch est a jour."; exit 0 }

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
git -C $repo branch --set-upstream-to "origin/$Branch" $Branch 2>&1 | Out-Host
Write-Host "Termine : $($commits.Count) nouveau(x) commit(s) sur origin/$Branch"
