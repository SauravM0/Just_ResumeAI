# Install pre-commit hooks for secret scanning
# Run from repository root

$hooksDir = Join-Path $PSScriptRoot ".githooks"
$gitHooksDir = Join-Path $PSScriptRoot ".git\hooks"

if (-not (Test-Path $hooksDir)) {
    Write-Error "Error: .githooks directory not found."
    exit 1
}

if (-not (Test-Path $gitHooksDir)) {
    New-Item -ItemType Directory -Path $gitHooksDir -Force | Out-Null
}

Copy-Item -Path (Join-Path $hooksDir "pre-commit") -Destination (Join-Path $gitHooksDir "pre-commit") -Force
Write-Host "Installed pre-commit hook to .git/hooks/pre-commit"

# Make executable on Unix-like systems (no-op on Windows)
if ($IsMacOS -or $IsLinux) {
    chmod +x (Join-Path $gitHooksDir "pre-commit")
}

Write-Host "Security checks will run automatically before each commit."
