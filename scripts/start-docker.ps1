param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"

if ($Build) {
    docker compose --progress quiet build
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$composeOutput = & docker compose up -d 2>&1
$composeExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($composeExitCode -ne 0) {
    $composeOutput
    exit $composeExitCode
}

Write-Host ""
Write-Host "JustResume is running:"
Write-Host "  Frontend:    http://localhost:3099"
Write-Host "  API Docs:    http://localhost:8000/docs"
Write-Host "  Health:      http://localhost:8000/api/v1/health"
Write-Host ""
Write-Host "Status:"
docker compose ps
