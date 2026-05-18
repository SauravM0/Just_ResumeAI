#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Local CI check — mirrors .github/workflows/ci.yml so you
# can validate before pushing.
#
# Usage:  bash scripts/check.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BOLD="\033[1m"
RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"
PASS=0
FAIL=0

pass() { echo -e "${GREEN}✅ $1${RESET}"; ((PASS++)); }
fail() { echo -e "${RED}❌ $1${RESET}"; ((FAIL++)); }
info() { echo -e "${YELLOW}━━ $1 ━━${RESET}"; }

cleanup() { [[ -d "$TEMP_SRC" ]] && rm -rf "$TEMP_SRC"; }

# ── Hygiene checks ───────────────────────────────────────────
SECTION="repo-hygiene"
info "Repo hygiene"

cd "$ROOT"

# .env tracked
ENV_FILES=$(git ls-files '*.env' | grep -v '.env.example' || true)
if [ -n "$ENV_FILES" ]; then fail ".env files tracked: $ENV_FILES"; else pass "No .env files tracked"; fi

# pycache / .pyc tracked
PYC_FILES=$(git ls-files -- '__pycache__' '*.pyc' '*.pyo' '*.pyd' || true)
if [ -n "$PYC_FILES" ]; then fail "__pycache__ / .pyc tracked: $PYC_FILES"; else pass "No __pycache__ or .pyc tracked"; fi

# backend/output tracked
OUT_FILES=$(git ls-files 'backend/output/' || true)
if [ -n "$OUT_FILES" ]; then fail "backend/output/ tracked: $OUT_FILES"; else pass "No backend/output/ tracked"; fi

# node_modules / dist tracked
ND_FILES=$(git ls-files 'node_modules' 'dist' 'frontend/node_modules' 'frontend/dist' || true)
if [ -n "$ND_FILES" ]; then fail "node_modules/dist tracked: $ND_FILES"; else pass "No node_modules/ or dist/ tracked"; fi

# OS junk tracked
JUNK=$(git ls-files '.DS_Store' 'Thumbs.db' || true)
if [ -n "$JUNK" ]; then fail "OS junk files tracked: $JUNK"; else pass "No OS junk files tracked"; fi

# ── Backend checks ───────────────────────────────────────────
SECTION="backend"
info "Backend"

cd "$ROOT/backend"

# pip install
python -m pip install --upgrade pip -q 2>/dev/null || true
pip install -r requirements.txt -q && pass "pip install" || fail "pip install"

# compileall
python -m compileall app/ tests/ -q && pass "compileall app" || fail "compileall app"

# ruff lint
pip install ruff -q 2>/dev/null || true
ruff check app/ tests/ && pass "ruff lint" || fail "ruff lint"

# pytest
python -m pytest tests/ -v --tb=short && pass "pytest" || fail "pytest"

# import check
python -c "from app.main import app; print('  imports OK')" && pass "app imports" || fail "app imports"

# ── Frontend checks ──────────────────────────────────────────
SECTION="frontend"
info "Frontend"

cd "$ROOT/frontend"

# npm ci
npm ci --legacy-peer-deps && pass "npm ci" || fail "npm ci"

# tsc
npx tsc -b && pass "TypeScript type check" || fail "TypeScript type check"

# lint
npm run lint && pass "npm lint" || fail "npm lint"

# test
npx vitest run && pass "vitest tests" || fail "vitest tests"

# build
npm run build && pass "npm build" || fail "npm build"

# ── Security audit (non-blocking) ────────────────────────────
info "Security audit (warnings only)"

npm audit --audit-level=critical && pass "npm audit" || echo "  ⚠️  npm audit found criticals — review package.json"

pip install pip-audit -q 2>/dev/null || true
cd "$ROOT/backend"
pip-audit --desc on -r requirements.txt && pass "pip-audit" || echo "  ⚠️  pip-audit found vulnerabilities — review requirements.txt"

# ── Summary ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════${RESET}"
echo -e "${BOLD}  Results: ${GREEN}${PASS} passed${RESET}, ${RED}${FAIL} failed${RESET}${RESET}"
echo -e "${BOLD}══════════════════════════════════════${RESET}"
if (( FAIL > 0 )); then
  exit 1
fi
