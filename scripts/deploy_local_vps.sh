#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

RUN_MIGRATIONS=0
if [[ "${1:-}" == "--migrate" ]]; then
  RUN_MIGRATIONS=1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Este directorio no es un repo Git."
  exit 1
fi

echo "Repo: $(git rev-parse --show-toplevel)"
echo "Rama actual: $(git branch --show-current)"
echo
git status --short

if [[ -n "$(git status --porcelain)" ]]; then
  echo
  echo "Hay cambios locales sin commit. Hace commit/stash antes de pull."
  exit 1
fi

echo
echo "== git pull --ff-only =="
git pull --ff-only

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [[ -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
elif [[ -f "env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "env/bin/activate"
fi

if [[ -f "alembic.ini" ]]; then
  if [[ "${RUN_MIGRATIONS}" -eq 1 ]]; then
    echo
    echo "== alembic upgrade head =="
    alembic upgrade head
  else
    echo
    echo "alembic.ini detectado. Las migraciones no se ejecutan automaticamente."
    echo "Usa ./scripts/deploy_local_vps.sh --migrate si este deploy realmente requiere migracion."
  fi
fi

echo
"${SCRIPT_DIR}/check.sh"

echo
"${SCRIPT_DIR}/restart.sh"

echo
"${SCRIPT_DIR}/app_logs.sh" 120
