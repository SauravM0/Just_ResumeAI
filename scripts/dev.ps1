param(
    [switch]$Build,
    [switch]$Stop,
    [switch]$Clean,
    [ValidateSet("backend", "frontend", "all")]
    [string]$Logs = "backend",
    [switch]$NoLogs,
    [switch]$VerboseLogs
)

$ErrorActionPreference = "Stop"

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$QuietOnSuccess
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & docker compose @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference

    if ($exitCode -ne 0) {
        $output
        exit $exitCode
    }

    if (-not $QuietOnSuccess) {
        $output
    }
}

if ($Stop) {
    Invoke-Compose -Arguments @("down")
    exit 0
}

if ($Clean) {
    Invoke-Compose -Arguments @("down")
    docker builder prune -a -f
    exit 0
}

if ($Build) {
    Invoke-Compose -Arguments @("--progress", "quiet", "build")
}

if ($VerboseLogs) {
    $env:LOG_LEVEL = "INFO"
}

Invoke-Compose -Arguments @("up", "-d") -QuietOnSuccess

Write-Host ""
Write-Host "JustResume is running:"
Write-Host "  Frontend:    http://localhost:3099"
Write-Host "  API Docs:    http://localhost:8000/docs"
Write-Host "  Health:      http://localhost:8000/api/v1/health"
if ($VerboseLogs) {
    Write-Host "  Log level:   INFO"
}
Write-Host ""
Write-Host "Status:"
docker compose ps

if ($NoLogs) {
    exit 0
}

Write-Host ""
Write-Host "Streaming $Logs logs. Press Ctrl+C to stop watching logs; containers will keep running."
Write-Host ""

if ($Logs -eq "all") {
    docker compose logs --tail=100 -f
} else {
    docker compose logs --tail=100 -f $Logs
}
