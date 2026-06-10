#!/usr/bin/env bash
set -euo pipefail

LINES="${1:-120}"

if journalctl -u training_mcp -n "${LINES}" --no-pager >/dev/null 2>&1; then
  journalctl -u training_mcp -n "${LINES}" --no-pager
else
  sudo journalctl -u training_mcp -n "${LINES}" --no-pager
fi
