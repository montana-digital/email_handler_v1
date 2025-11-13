param(
    [string]$TargetRoot = "$PSScriptRoot\..\..\data\input",
    [string]$FolderName = "test_run"
)

Write-Host "Starting test script..."
Write-Host "Target root: $TargetRoot"
Write-Host "Folder name: $FolderName"

$resolvedRoot = Resolve-Path -Path $TargetRoot -ErrorAction SilentlyContinue
if (-not $resolvedRoot) {
    Write-Host "Target root not found. Creating parent directories."
    New-Item -ItemType Directory -Path $TargetRoot -Force | Out-Null
    $resolvedRoot = Resolve-Path -Path $TargetRoot
}

$fullPath = Join-Path -Path $resolvedRoot -ChildPath $FolderName

Write-Host "Ensuring directory exists at: $fullPath"
New-Item -ItemType Directory -Path $fullPath -Force | Out-Null

Write-Host "Directory created."
Start-Sleep -Seconds 2
Write-Host "Completed successfully."

