# ─────────────────────────────────────────────────────────────
# Local CI check — mirrors .github/workflows/ci.yml so you
# can validate before pushing (Windows PowerShell).
#
# Usage:  .\scripts\check.ps1
# ─────────────────────────────────────────────────────────────

$ROOT = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$PASS = 0
$FAIL = 0

function Pass($msg) { Write-Host "✅ $msg" -ForegroundColor Green; $script:PASS++ }
function Fail($msg) { Write-Host "❌ $msg" -ForegroundColor Red;   $script:FAIL++ }
function Info($msg) { Write-Host "━━ $msg ━━" -ForegroundColor Yellow }

# ── Hygiene ──────────────────────────────────────────────────
Info "Repo hygiene"
Set-Location $ROOT

$envFiles = git ls-files '*.env' | Select-String -NotMatch '\.env\.example'
if ($envFiles) { Fail ".env files tracked: $envFiles" } else { Pass "No .env files tracked" }

$pycFiles = git ls-files -- '__pycache__' '*.pyc' '*.pyo' '*.pyd' | Out-String
if ([string]::IsNullOrWhiteSpace($pycFiles)) { Pass "No __pycache__ or .pyc tracked" } else { Fail "__pycache__ / .pyc tracked" }

$outFiles = git ls-files 'backend/output/' | Out-String
if ([string]::IsNullOrWhiteSpace($outFiles)) { Pass "No backend/output/ tracked" } else { Fail "backend/output/ tracked" }

$ndFiles = git ls-files 'node_modules' 'dist' 'frontend/node_modules' 'frontend/dist' | Out-String
if ([string]::IsNullOrWhiteSpace($ndFiles)) { Pass "No node_modules/ or dist/ tracked" } else { Fail "node_modules/dist tracked" }

$junk = git ls-files '.DS_Store' 'Thumbs.db' | Out-String
if ([string]::IsNullOrWhiteSpace($junk)) { Pass "No OS junk files tracked" } else { Fail "OS junk files tracked" }

# ── Backend ──────────────────────────────────────────────────
Info "Backend"
Set-Location "$ROOT\backend"

python -m pip install --upgrade pip -q 2>$null
pip install -r requirements.txt -q
if ($LASTEXITCODE -eq 0) { Pass "pip install" } else { Fail "pip install" }

python -m compileall app/ tests/ -q
if ($LASTEXITCODE -eq 0) { Pass "compileall app" } else { Fail "compileall app" }

pip install ruff -q 2>$null
ruff check app/ tests/
if ($LASTEXITCODE -eq 0) { Pass "ruff lint" } else { Fail "ruff lint" }

python -m pytest tests/ -v --tb=short
if ($LASTEXITCODE -eq 0) { Pass "pytest" } else { Fail "pytest" }

python -c "from app.main import app; print('  imports OK')"
if ($LASTEXITCODE -eq 0) { Pass "app imports" } else { Fail "app imports" }

# ── Frontend ─────────────────────────────────────────────────
Info "Frontend"
Set-Location "$ROOT\frontend"

npm ci --legacy-peer-deps
if ($LASTEXITCODE -eq 0) { Pass "npm ci" } else { Fail "npm ci" }

npx tsc -b
if ($LASTEXITCODE -eq 0) { Pass "TypeScript type check" } else { Fail "TypeScript type check" }

npm run lint
if ($LASTEXITCODE -eq 0) { Pass "npm lint" } else { Fail "npm lint" }

npx vitest run
if ($LASTEXITCODE -eq 0) { Pass "vitest tests" } else { Fail "vitest tests" }

npm run build
if ($LASTEXITCODE -eq 0) { Pass "npm build" } else { Fail "npm build" }

# ── Security ─────────────────────────────────────────────────
Info "Security audit (warnings only)"

npm audit --audit-level=critical
if ($LASTEXITCODE -eq 0) { Pass "npm audit" } else { Write-Host "  ⚠️  npm audit found criticals — review package.json" -ForegroundColor Yellow }

pip install pip-audit -q 2>$null
Set-Location "$ROOT\backend"
pip-audit --desc on -r requirements.txt
if ($LASTEXITCODE -eq 0) { Pass "pip-audit" } else { Write-Host "  ⚠️  pip-audit found vulnerabilities — review requirements.txt" -ForegroundColor Yellow }

# ── Summary ──────────────────────────────────────────────────
Write-Host "`n══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Results: ${PASS} passed, ${FAIL} failed" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════" -ForegroundColor Cyan
if ($FAIL -gt 0) { exit 1 }
