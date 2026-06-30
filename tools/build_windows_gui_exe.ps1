$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Building campy-gui.exe with PyInstaller..."
pyinstaller .\packaging\windows\campy_gui.spec --noconfirm --clean

Write-Host ""
Write-Host "Build complete."
Write-Host "Executable folder:"
Write-Host "  $RepoRoot\dist\campy-gui"
