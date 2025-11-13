param(
    [string]$TargetRoot = "$PSScriptRoot\..\..\data\input",
    [string]$FolderName = "test_run"
)

Write-Host "Starting test script..."
Write-Host "Target root: $TargetRoot"
Write-Host "Folder name: $FolderName"

# Resolve full path and normalize
$fullPath = Resolve-Path -Path (Join-Path -Path $TargetRoot -ChildPath $FolderName) -ErrorAction SilentlyContinue
if (-not $fullPath) {
    $fullPath = Join-Path -Path (Resolve-Path -Path $TargetRoot).Path -ChildPath $FolderName
}

Write-Host "Ensuring directory exists at: $fullPath"
New-Item -ItemType Directory -Path $fullPath -Force | Out-Null

Write-Host "Directory created."
Start-Sleep -Seconds 2
Write-Host "Completed successfully."