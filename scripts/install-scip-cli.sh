#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$ROOT/.bin"
SCIP_BIN="$BIN_DIR/scip"
TAG="${SCIP_VERSION:-v0.7.1}"

is_sourcegraph_scip() {
  local bin="$1"
  [[ -f "$bin" ]] || return 1
  if head -1 "$bin" 2>/dev/null | grep -qi python; then
    return 1
  fi
  "$bin" print --help >/dev/null 2>&1
}

remove_wrong_pypi_scip() {
  if [[ -n "${VIRTUAL_ENV:-}" ]] && command -v pip >/dev/null 2>&1; then
    if pip show scip >/dev/null 2>&1; then
      echo "Removing wrong PyPI package 'scip' from venv (not Sourcegraph SCIP)..."
      pip uninstall -y scip || true
    fi
  fi
}

install_from_release() {
  local os arch asset
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"
  case "$arch" in
    x86_64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *)
      echo "Unsupported architecture: $arch"
      return 1
      ;;
  esac
  asset="scip-${os}-${arch}.tar.gz"
  local url="https://github.com/scip-code/scip/releases/download/${TAG}/${asset}"

  echo "Downloading ${url}..."
  mkdir -p "$BIN_DIR"
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL "$url" | tar -xzf - -C "$tmp" scip
  install -m 755 "$tmp/scip" "$SCIP_BIN"
  rm -rf "$tmp"
  echo "Installed Sourcegraph scip CLI: $SCIP_BIN"
}

remove_wrong_pypi_scip

for candidate in \
  "$SCIP_BIN" \
  "$(go env GOPATH 2>/dev/null)/bin/scip" \
  /opt/homebrew/bin/scip \
  /usr/local/bin/scip \
  "$(command -v scip 2>/dev/null || true)"
do
  if [[ -n "$candidate" ]] && is_sourcegraph_scip "$candidate"; then
    echo "Sourcegraph scip CLI already ok: $candidate"
    "$candidate" version 2>/dev/null || true
    exit 0
  fi
done

if install_from_release; then
  if is_sourcegraph_scip "$SCIP_BIN"; then
    "$SCIP_BIN" version 2>/dev/null || "$SCIP_BIN" print --help | head -3
    echo ""
    echo "Add to PATH for worker and shell:"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    exit 0
  fi
fi

if command -v go >/dev/null 2>&1; then
  echo "Release download failed; trying go install at v0.7.1..."
  if go install github.com/sourcegraph/scip/cmd/scip@v0.7.1 2>/dev/null; then
    GOPATH_BIN="$(go env GOPATH)/bin/scip"
    if is_sourcegraph_scip "$GOPATH_BIN"; then
      echo "Installed: $GOPATH_BIN"
      echo 'export PATH="$(go env GOPATH)/bin:$PATH"'
      exit 0
    fi
  fi
fi

echo "Failed to install Sourcegraph scip CLI."
echo "Manual: https://github.com/scip-code/scip/releases/tag/${TAG}"
exit 1
