#!/usr/bin/env bash
set -euo pipefail

LINES="${1:-120}"

show_logs() {
  local service="$1"
  echo
  echo "== Logs ${service} =="
  if journalctl -u "${service}" -n "${LINES}" --no-pager >/dev/null 2>&1; then
    journalctl -u "${service}" -n "${LINES}" --no-pager
  else
    sudo journalctl -u "${service}" -n "${LINES}" --no-pager
  fi
}

show_logs "training_app"
show_logs "training_mcp"
