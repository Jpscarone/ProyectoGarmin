#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ $# -lt 1 ]]; then
  echo 'Uso: ./scripts/safe_commit.sh "mensaje" [--push]'
  exit 1
fi

MESSAGE="$1"
PUSH_FLAG="${2:-}"

git status --short

echo
echo "== Checks previos =="
"${SCRIPT_DIR}/check.sh"

echo
echo "== Git add / commit =="
git add .
git commit -m "${MESSAGE}"

if [[ "${PUSH_FLAG}" == "--push" ]]; then
  echo
  echo "== Git push =="
  git push
fi
