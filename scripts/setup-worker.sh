#!/usr/bin/env bash
# Install and verify all tools required by Ripple Temporal workers.
# Run once on each worker node before starting ripple/worker.py.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$ROOT/.bin"

ok()   { echo "  [ok]  $*"; }
warn() { echo "  [!!]  $*"; }
need() { echo "  [--]  $*"; }

echo ""
echo "=== Ripple worker setup ==="
echo ""

# ── 1. scip CLI ───────────────────────────────────────────────────────────────
echo "-- scip CLI"
if "$BIN_DIR/scip" print --help >/dev/null 2>&1; then
  ok "scip already in .bin/scip"
else
  bash "$ROOT/scripts/install-scip-cli.sh"
fi

# Symlink to /usr/local/bin so it is on PATH for all workers
if ! command -v scip >/dev/null 2>&1; then
  warn "scip not on PATH — add this to your shell profile or worker start script:"
  warn "  export PATH=\"$BIN_DIR:\$PATH\""
  export PATH="$BIN_DIR:$PATH"
  ok "scip added to PATH for this session"
else
  ok "scip on PATH: $(command -v scip)"
fi

# ── 2. Node version (scip-typescript needs ≥18) ───────────────────────────────
echo ""
echo "-- Node.js"
NODE_VER="$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1 || echo 0)"
if [[ "$NODE_VER" -lt 18 ]]; then
  warn "Node v$NODE_VER detected — scip-typescript requires ≥18"
  if command -v nvm >/dev/null 2>&1 || [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.nvm/nvm.sh"
    nvm install 20 --lts
    nvm use 20
    ok "Switched to Node $(node --version) via nvm"
  else
    warn "nvm not found — install Node 20 manually: https://nodejs.org"
    warn "Or: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
  fi
else
  ok "Node v$(node --version) — OK"
fi

# ── 3. scip-typescript ────────────────────────────────────────────────────────
echo ""
echo "-- scip-typescript"
if command -v scip-typescript >/dev/null 2>&1; then
  ok "scip-typescript: $(scip-typescript --version 2>/dev/null || echo installed)"
else
  need "Installing @sourcegraph/scip-typescript..."
  npm install -g @sourcegraph/scip-typescript
  ok "scip-typescript installed"
fi

# ── 4. scip-python ────────────────────────────────────────────────────────────
echo ""
echo "-- scip-python"
if command -v scip-python >/dev/null 2>&1; then
  ok "scip-python: $(scip-python --version 2>/dev/null || echo installed)"
else
  need "Installing @sourcegraph/scip-python..."
  npm install -g @sourcegraph/scip-python
  ok "scip-python installed"
fi

# ── 5. scip-java / coursier ───────────────────────────────────────────────────
echo ""
echo "-- scip-java"
if command -v scip-java >/dev/null 2>&1; then
  ok "scip-java: $(scip-java --version 2>/dev/null || echo installed)"
elif command -v coursier >/dev/null 2>&1; then
  ok "coursier available — scip-java will be launched via coursier at index time"
else
  warn "Neither scip-java nor coursier found — Java repos will not be indexed"
  warn "Install coursier: https://get-coursier.io/docs/cli-installation"
fi

# ── 6. Java (required by scip-java) ──────────────────────────────────────────
echo ""
echo "-- Java"
if command -v java >/dev/null 2>&1; then
  JAVA_VER="$(java -version 2>&1 | head -1)"
  ok "java: $JAVA_VER"
else
  warn "java not found — Java/Kotlin indexing will fail"
fi

# ── 7. codebase-memory-mcp (default RIPPLE_GRAPH_TOOL) ───────────────────────
echo ""
echo "-- codebase-memory-mcp"
if command -v codebase-memory-mcp >/dev/null 2>&1; then
  ok "codebase-memory-mcp: $(codebase-memory-mcp --version 2>/dev/null || echo installed)"
else
  need "Installing codebase-memory-mcp@latest..."
  npm install -g codebase-memory-mcp
  ok "codebase-memory-mcp installed"
fi

# ── 8. Python deps ────────────────────────────────────────────────────────────
echo ""
echo "-- Python dependencies"
pip install -q -r "$ROOT/requirements.txt"
ok "requirements.txt installed"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Verification ==="
PASS=true
for tool in scip scip-typescript scip-python codebase-memory-mcp; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool"
  else
    warn "$tool  ← MISSING"
    PASS=false
  fi
done

echo ""
if $PASS; then
  echo "All required tools installed. Worker is ready."
  echo "Start with:  cd $ROOT && python -m ripple.worker"
else
  echo "Some tools are missing — check warnings above."
  exit 1
fi
