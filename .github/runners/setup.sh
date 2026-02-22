#!/usr/bin/env bash
set -euo pipefail

# Self-hosted runner setup script for Hermes
# Registers and starts a GitHub Actions runner on the current machine.
#
# Prerequisites:
#   - gh CLI authenticated (gh auth login)
#   - Docker installed (for Docker-in-Docker jobs)
#
# Usage:
#   ./setup.sh                    # interactive
#   ./setup.sh --token XXXXX      # non-interactive

OWNER="${GITHUB_OWNER:-WhiteDevil-93}"
REPO="${GITHUB_REPO:-Hermes-pro}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
RUNNER_VERSION="2.321.0"
LABELS="self-hosted,linux,x64,hermes"

# ---------- Parse args ----------
TOKEN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --repo)  REPO="$2";  shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ---------- Get registration token ----------
if [ -z "$TOKEN" ]; then
  echo "Fetching runner registration token via gh CLI..."
  TOKEN=$(gh api "repos/$OWNER/$REPO/actions/runners/registration-token" \
    --method POST --jq '.token')
fi

if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not obtain runner token."
  echo "Run: gh api repos/$OWNER/$REPO/actions/runners/registration-token --method POST"
  exit 1
fi

# ---------- Download runner ----------
echo "Installing runner to $RUNNER_DIR..."
mkdir -p "$RUNNER_DIR" && cd "$RUNNER_DIR"

ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  ARCH_LABEL="x64" ;;
  aarch64) ARCH_LABEL="arm64" ;;
  *)       echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

TARBALL="actions-runner-linux-${ARCH_LABEL}-${RUNNER_VERSION}.tar.gz"
if [ ! -f "$TARBALL" ]; then
  curl -sL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}" -o "$TARBALL"
fi
tar xzf "$TARBALL"

# ---------- Configure ----------
./config.sh \
  --url "https://github.com/$OWNER/$REPO" \
  --token "$TOKEN" \
  --name "hermes-$(hostname)-$$" \
  --labels "$LABELS" \
  --work _work \
  --replace \
  --unattended

# ---------- Install & start as service ----------
echo ""
echo "Runner configured. Starting..."

if command -v systemctl &>/dev/null; then
  sudo ./svc.sh install
  sudo ./svc.sh start
  echo "Runner installed as systemd service."
  echo "  Status: sudo ./svc.sh status"
  echo "  Stop:   sudo ./svc.sh stop"
  echo "  Remove: sudo ./svc.sh uninstall"
else
  echo "systemd not found — running in foreground."
  echo "Press Ctrl+C to stop."
  ./run.sh
fi
