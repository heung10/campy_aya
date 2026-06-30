param(
    [string]$EnvName = "campy"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Creating/updating conda environment '$EnvName' from environment.yml..."
conda env update --name $EnvName --file environment.yml --prune

Write-Host ""
Write-Host "Environment is ready."
Write-Host "Next commands:"
Write-Host "  conda activate $EnvName"
Write-Host "  campy-gui"
