#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

activate_venv() {
  local candidate
  for candidate in ".venv/bin/activate" "venv/bin/activate" "env/bin/activate"; do
    if [[ -f "${PROJECT_ROOT}/${candidate}" ]]; then
      # shellcheck disable=SC1090
      source "${PROJECT_ROOT}/${candidate}"
      echo "Usando virtualenv: ${candidate}"
      return 0
    fi
  done
  echo "No se encontro virtualenv en .venv/, venv/ ni env/. Se usa el Python actual."
}

activate_venv

echo "Python: $(command -v python)"
python --version

echo
echo "== Compileall =="
python -m compileall app

if [[ -d tests ]]; then
  echo
  echo "== Pytest =="
  if python -m pytest --version >/dev/null 2>&1; then
    python -m pytest
  else
    echo "pytest no esta instalado en el entorno actual."
    exit 1
  fi
fi
