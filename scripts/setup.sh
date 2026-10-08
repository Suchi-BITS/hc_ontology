#!/usr/bin/env bash
# Thin wrapper kept for compatibility. The real implementation is scripts/dev.py (stdlib only).
set -e
cd "$(dirname "$0")/.."
exec python3 scripts/dev.py setup "$@"
