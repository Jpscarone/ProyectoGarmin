#!/usr/bin/env bash
set -euo pipefail

SERVICES=("training_app" "training_mcp")
FAILED=0

run_systemctl() {
  if systemctl "$@" >/dev/null 2>&1; then
    systemctl "$@"
  else
    sudo systemctl "$@"
  fi
}

for service in "${SERVICES[@]}"; do
  echo
  echo "== Reiniciando ${service} =="
  if ! run_systemctl status "${service}" --no-pager -l >/dev/null 2>&1; then
    echo "Servicio no disponible o sin permisos: ${service}"
    FAILED=1
    continue
  fi
  if ! run_systemctl restart "${service}"; then
    echo "Fallo el restart de ${service}."
    FAILED=1
    continue
  fi
  if ! run_systemctl status "${service}" --no-pager -l; then
    echo "No se pudo obtener status de ${service} despues del restart."
    FAILED=1
  fi
done

exit "${FAILED}"
